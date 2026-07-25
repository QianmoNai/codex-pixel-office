#!/usr/bin/env python3
"""Native Windows WebView2 shell for Codex Pixel Office."""

from __future__ import annotations

import argparse
from collections.abc import MutableMapping
import ctypes
import importlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Iterable, Mapping

from desktop_common import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    LocalOfficeServer,
    SMOKE_STATE_SCRIPT,
    SMOKE_TEST_TIMEOUT_SECONDS,
    WINDOW_TITLE,
    encode_smoke_payload,
    normalized_smoke_payload,
    resolve_windows_icon_path,
)
from server import DEFAULT_ACTIVE_MINUTES, positive_finite_minutes


WEBVIEW2_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
WEBVIEW2_MIN_VERSION = (86, 0, 622, 0)
DOTNET_FRAMEWORK_KEY = r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full"
DOTNET_FRAMEWORK_MIN_RELEASE = 394802
WINDOWS_MIN_SIZE = (960, 600)


class WindowsDesktopError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Codex Pixel Office Windows desktop application"
    )
    parser.add_argument(
        "--codex-home",
        default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")),
        help="Codex home containing state_5.sqlite and sessions/",
    )
    parser.add_argument(
        "--active-minutes",
        type=positive_finite_minutes,
        default=DEFAULT_ACTIVE_MINUTES,
        help="include sessions updated within this many minutes",
    )
    parser.add_argument(
        "--codex-bin",
        default=os.environ.get("CODEX_PIXEL_CODEX_BIN", "codex"),
        help="Codex CLI executable (for example codex.exe or codex.cmd)",
    )
    parser.add_argument(
        "--fullscreen",
        action="store_true",
        help="open the office in fullscreen mode",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="enable pywebview debugging tools",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="load the complete UI, report JSON readiness, and exit automatically",
    )
    parser.add_argument(
        "--smoke-timeout",
        type=positive_finite_minutes,
        default=SMOKE_TEST_TIMEOUT_SECONDS / 60.0,
        help=argparse.SUPPRESS,
    )
    return parser


def windows_storage_path(environment: Mapping[str, str] | None = None) -> Path:
    variables = os.environ if environment is None else environment
    local_app_data = variables.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "CodexPixelOffice" / "WebView2"


def configured_fixed_runtime(
    environment: Mapping[str, str] | None = None,
) -> tuple[Path | None, str | None]:
    variables = os.environ if environment is None else environment
    raw = variables.get("CODEX_PIXEL_WEBVIEW2_RUNTIME", "").strip()
    if not raw:
        return None, None
    if raw.startswith((r"\\", "//")):
        return None, "CODEX_PIXEL_WEBVIEW2_RUNTIME must use a local drive, not a UNC path"
    try:
        path = Path(raw).expanduser().resolve()
    except OSError as error:
        return None, f"CODEX_PIXEL_WEBVIEW2_RUNTIME is invalid: {error}"
    executable = path / "msedgewebview2.exe"
    if path.is_dir() and executable.is_file():
        return path, None
    return None, f"CODEX_PIXEL_WEBVIEW2_RUNTIME is invalid: {path}"


def _version_key(value: object) -> tuple[int, int, int, int] | None:
    raw = str(value or "").strip()
    try:
        parts = tuple(int(part) for part in raw.split("."))
    except ValueError:
        return None
    if not parts or any(part < 0 for part in parts):
        return None
    return (parts + (0, 0, 0, 0))[:4]


def webview2_version_is_supported(value: object) -> bool:
    version = _version_key(value)
    return version is not None and version >= WEBVIEW2_MIN_VERSION


def registered_webview2_version(registry: Any | None = None) -> str | None:
    if registry is None:
        try:
            import winreg as registry  # type: ignore[no-redef]
        except ImportError:
            return None

    key_paths = (
        rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_ID}",
        rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_ID}",
    )
    hives = tuple(
        hive
        for hive in (
            getattr(registry, "HKEY_CURRENT_USER", None),
            getattr(registry, "HKEY_LOCAL_MACHINE", None),
        )
        if hive is not None
    )
    views = tuple(
        dict.fromkeys(
            (
                0,
                getattr(registry, "KEY_WOW64_32KEY", 0),
                getattr(registry, "KEY_WOW64_64KEY", 0),
            )
        )
    )
    key_read = getattr(registry, "KEY_READ", 0)
    best_version: str | None = None
    best_key: tuple[int, int, int, int] | None = None
    for hive in hives:
        for key_path in key_paths:
            for view in views:
                try:
                    with registry.OpenKey(hive, key_path, 0, key_read | view) as key:
                        value, _kind = registry.QueryValueEx(key, "pv")
                except OSError:
                    continue
                version = str(value or "").strip()
                version_key = _version_key(version)
                if version_key is not None and version_key != (0, 0, 0, 0):
                    if best_key is None or version_key > best_key:
                        best_version = version
                        best_key = version_key
    return best_version


def registered_dotnet_release(registry: Any | None = None) -> int | None:
    if registry is None:
        try:
            import winreg as registry  # type: ignore[no-redef]
        except ImportError:
            return None

    hive = getattr(registry, "HKEY_LOCAL_MACHINE", None)
    if hive is None:
        return None
    views = tuple(
        dict.fromkeys(
            (
                0,
                getattr(registry, "KEY_WOW64_32KEY", 0),
                getattr(registry, "KEY_WOW64_64KEY", 0),
            )
        )
    )
    key_read = getattr(registry, "KEY_READ", 0)
    best_release: int | None = None
    for view in views:
        try:
            with registry.OpenKey(
                hive,
                DOTNET_FRAMEWORK_KEY,
                0,
                key_read | view,
            ) as key:
                value, _kind = registry.QueryValueEx(key, "Release")
                release = int(value)
        except (OSError, TypeError, ValueError):
            continue
        if best_release is None or release > best_release:
            best_release = release
    return best_release


def require_webview2(
    *,
    environment: Mapping[str, str] | None = None,
    registry: Any | None = None,
) -> Path | None:
    fixed_runtime, fixed_error = configured_fixed_runtime(environment)
    if fixed_error:
        raise WindowsDesktopError(fixed_error)
    dotnet_release = registered_dotnet_release(registry)
    if dotnet_release is None or dotnet_release < DOTNET_FRAMEWORK_MIN_RELEASE:
        raise WindowsDesktopError(
            "Microsoft .NET Framework 4.6.2 or newer is required for the WebView2 desktop window"
        )
    if fixed_runtime is not None:
        return fixed_runtime
    version = registered_webview2_version(registry)
    if version is None:
        raise WindowsDesktopError(
            "Microsoft Edge WebView2 Runtime was not found. Install the Evergreen Runtime from "
            f"{WEBVIEW2_DOWNLOAD_URL}"
        )
    if not webview2_version_is_supported(version):
        minimum = ".".join(str(part) for part in WEBVIEW2_MIN_VERSION)
        raise WindowsDesktopError(
            f"Microsoft Edge WebView2 Runtime {minimum} or newer is required; found {version}"
        )
    return None


def load_webview(
    importer: Callable[[str], Any] = importlib.import_module,
) -> Any:
    try:
        return importer("webview")
    except (ImportError, ModuleNotFoundError) as error:
        raise WindowsDesktopError(
            "pywebview is not installed. Run: py -3 -m pip install -r requirements-windows.txt"
        ) from error


def configure_webview(webview: Any, fixed_runtime: Path | None = None) -> None:
    settings = getattr(webview, "settings", None)
    if not isinstance(settings, MutableMapping):
        raise WindowsDesktopError("the installed pywebview version does not expose settings")
    settings["ALLOW_DOWNLOADS"] = False
    settings["ALLOW_FILE_URLS"] = False
    settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    if fixed_runtime is not None:
        settings["WEBVIEW2_RUNTIME_PATH"] = str(fixed_runtime)


def _destroy_window(window: Any) -> None:
    try:
        window.destroy()
    except Exception:
        pass


def _readiness_worker(
    window: Any,
    result: dict[str, Any],
    timeout_seconds: float,
    smoke_test: bool,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    loaded_event = getattr(getattr(window, "events", None), "loaded", None)
    wait_for_load = getattr(loaded_event, "wait", None)
    if callable(wait_for_load):
        try:
            if not wait_for_load(max(0.0, deadline - time.monotonic())):
                last_error = "the WebView2 page load event timed out"
        except Exception as error:
            last_error = str(error)
        if last_error:
            deadline = time.monotonic()
    while time.monotonic() < deadline:
        try:
            state = window.evaluate_js(SMOKE_STATE_SCRIPT)
            if isinstance(state, str):
                state = json.loads(state)
            payload = normalized_smoke_payload(state)
            if payload is not None:
                if smoke_test:
                    print(encode_smoke_payload(payload), flush=True)
                result["exit_code"] = 0
                result.pop("error", None)
                if smoke_test:
                    _destroy_window(window)
                return
        except Exception as error:
            last_error = str(error)
        time.sleep(0.1)

    result["exit_code"] = 2 if smoke_test else 1
    if smoke_test:
        payload: dict[str, object] = {"ok": False, "error": "timeout"}
        if last_error:
            payload["detail"] = last_error[:500]
        print(encode_smoke_payload(payload), file=sys.stderr, flush=True)
    else:
        detail = "The WebView2 office page did not become ready"
        if last_error:
            detail += f": {last_error[:500]}"
        result["error"] = detail
    _destroy_window(window)


def _startup_worker(
    webview: Any,
    window: Any,
    result: dict[str, Any],
    timeout_seconds: float,
    smoke_test: bool,
) -> None:
    renderer = str(getattr(webview, "renderer", "") or "").lower()
    if renderer != "edgechromium":
        detail = f"pywebview selected {renderer or 'an unknown renderer'} instead of WebView2"
        result["exit_code"] = 2 if smoke_test else 1
        if smoke_test:
            print(
                encode_smoke_payload(
                    {"ok": False, "error": "renderer-unavailable", "detail": detail}
                ),
                file=sys.stderr,
                flush=True,
            )
        else:
            result["error"] = detail
        _destroy_window(window)
        return
    _readiness_worker(window, result, timeout_seconds, smoke_test)


def run_webview(
    args: argparse.Namespace,
    webview: Any,
    backend: LocalOfficeServer,
    *,
    fixed_runtime: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> int:
    configure_webview(webview, fixed_runtime)
    storage_path = windows_storage_path(environment)
    storage_path.mkdir(parents=True, exist_ok=True)
    icon_path = resolve_windows_icon_path(backend.static_root)
    window = webview.create_window(
        WINDOW_TITLE,
        url=backend.url,
        width=DEFAULT_WINDOW_WIDTH,
        height=DEFAULT_WINDOW_HEIGHT,
        min_size=WINDOWS_MIN_SIZE,
        resizable=True,
        fullscreen=args.fullscreen,
        background_color="#2d2948",
        text_select=True,
        zoomable=True,
    )
    if window is None:
        raise WindowsDesktopError("pywebview could not create the application window")

    result: dict[str, Any] = {
        "exit_code": 2 if args.smoke_test else 1,
    }
    if not args.smoke_test:
        result["error"] = "WebView2 did not finish initializing"
    start_options: dict[str, Any] = {
        "gui": "edgechromium",
        "debug": args.debug,
        "private_mode": False,
        "storage_path": str(storage_path),
    }
    if icon_path is not None:
        start_options["icon"] = str(icon_path)

    webview.start(
        _startup_worker,
        (webview, window, result, args.smoke_timeout * 60.0, args.smoke_test),
        **start_options,
    )
    if result.get("error"):
        raise WindowsDesktopError(str(result["error"]))
    return int(result["exit_code"])


def show_error(message: str, *, dialog: bool = True) -> None:
    print(f"Could not open Codex Pixel Office: {message}", file=sys.stderr, flush=True)
    if not dialog or sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.MessageBoxW(0, message, WINDOW_TITLE, 0x10)
    except Exception:
        pass


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if sys.platform != "win32":
        show_error("windows_app.py is only supported on Windows", dialog=False)
        return 2 if args.smoke_test else 1

    try:
        fixed_runtime = require_webview2()
        webview = load_webview()
        backend = LocalOfficeServer(
            args.codex_home,
            args.active_minutes,
            codex_bin=args.codex_bin,
        )
        with backend:
            return run_webview(
                args,
                webview,
                backend,
                fixed_runtime=fixed_runtime,
            )
    except Exception as error:
        show_error(str(error), dialog=not args.smoke_test)
        return 2 if args.smoke_test else 1


if __name__ == "__main__":
    raise SystemExit(main())

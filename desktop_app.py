#!/usr/bin/env python3
"""Native GTK desktop shell for Codex Pixel Office."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Iterable

from desktop_common import (
    APPLICATION_ID,
    DEFAULT_STATIC_ROOT,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    LocalOfficeServer,
    SMOKE_STATE_SCRIPT,
    SMOKE_TEST_TIMEOUT_SECONDS,
    WINDOW_TITLE,
    normalized_smoke_payload,
    resolve_icon_path,
)
from server import (
    DEFAULT_ACTIVE_MINUTES,
    positive_finite_minutes,
)


GTK_IMPORT_ERROR: BaseException | None = None
try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("WebKit", "6.0")
    from gi.repository import Gdk, Gio, GLib, Gtk, WebKit  # noqa: E402
except (ImportError, ValueError) as error:  # Windows and headless test environments
    GTK_IMPORT_ERROR = error
    Gdk = Gio = GLib = Gtk = WebKit = None

GTK_AVAILABLE = GTK_IMPORT_ERROR is None


class _UnavailableGtkApplication:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("GTK4 and WebKitGTK 6 are not available") from GTK_IMPORT_ERROR


_GtkApplicationBase = Gtk.Application if GTK_AVAILABLE else _UnavailableGtkApplication


class PixelOfficeApplication(_GtkApplicationBase):
    def __init__(
        self,
        backend: LocalOfficeServer,
        *,
        fullscreen: bool = False,
        smoke_test: bool = False,
    ) -> None:
        if not GTK_AVAILABLE:
            raise RuntimeError("GTK4 and WebKitGTK 6 are not available") from GTK_IMPORT_ERROR
        super().__init__(
            application_id=APPLICATION_ID,
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.backend = backend
        self.fullscreen_requested = fullscreen
        self.smoke_test = smoke_test
        self.exit_code = 0
        self.window: Gtk.ApplicationWindow | None = None
        self.web_view: WebKit.WebView | None = None
        self._smoke_poll_source = 0
        self._smoke_timeout_source = 0
        self._smoke_evaluation_pending = False
        self._smoke_finished = False
        self.connect("shutdown", self._on_shutdown)

    def _configure_icon(self, window: Gtk.ApplicationWindow) -> None:
        icon_path = resolve_icon_path(self.backend.static_root)
        display = Gdk.Display.get_default()
        if icon_path is None or display is None:
            return
        theme = Gtk.IconTheme.get_for_display(display)
        theme.add_search_path(str(icon_path.parent))
        Gtk.Window.set_default_icon_name(icon_path.stem)
        window.set_icon_name(icon_path.stem)

    def do_activate(self) -> None:
        try:
            self._activate()
        except Exception as error:
            if self.smoke_test:
                self._fail_smoke("application-start-failed", str(error))
            else:
                print(f"Could not open Codex Pixel Office: {error}", file=sys.stderr)
                self.exit_code = 1
                self.backend.close()
                self.quit()

    def _activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        window = Gtk.ApplicationWindow(application=self)
        window.set_title(WINDOW_TITLE)
        window.set_default_size(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        window.connect("close-request", self._on_close_request)
        self._configure_icon(window)

        web_view = WebKit.WebView()
        web_view.set_hexpand(True)
        web_view.set_vexpand(True)
        web_view.connect("load-changed", self._on_load_changed)
        web_view.connect("load-failed", self._on_load_failed)
        web_view.connect("web-process-terminated", self._on_web_process_terminated)
        window.set_child(web_view)

        self.window = window
        self.web_view = web_view
        if self.fullscreen_requested:
            window.fullscreen()
        window.present()
        web_view.load_uri(self.backend.url)

        if self.smoke_test:
            self._smoke_timeout_source = GLib.timeout_add(
                int(SMOKE_TEST_TIMEOUT_SECONDS * 1000),
                self._on_smoke_timeout,
            )

    def _on_close_request(self, _window: Gtk.ApplicationWindow) -> bool:
        self.backend.close()
        return False

    def _on_shutdown(self, _application: Gtk.Application) -> None:
        self._remove_smoke_sources()
        self.backend.close()

    def _on_load_changed(self, _web_view: WebKit.WebView, event: WebKit.LoadEvent) -> None:
        if not self.smoke_test or self._smoke_finished:
            return
        if event == WebKit.LoadEvent.FINISHED and not self._smoke_poll_source:
            self._smoke_poll_source = GLib.timeout_add(100, self._poll_smoke_state)

    def _on_load_failed(
        self,
        _web_view: WebKit.WebView,
        event: WebKit.LoadEvent,
        failing_uri: str,
        error: GLib.Error,
    ) -> bool:
        if self.smoke_test and event != WebKit.LoadEvent.STARTED:
            self._fail_smoke("page-load-failed", f"{failing_uri}: {error.message}")
        return False

    def _on_web_process_terminated(
        self,
        _web_view: WebKit.WebView,
        _reason: WebKit.WebProcessTerminationReason,
    ) -> None:
        if self.smoke_test:
            self._fail_smoke("web-process-terminated")

    def _poll_smoke_state(self) -> bool:
        if self._smoke_finished:
            return GLib.SOURCE_REMOVE
        if self._smoke_evaluation_pending or self.web_view is None:
            return GLib.SOURCE_CONTINUE
        self._smoke_evaluation_pending = True
        self.web_view.evaluate_javascript(
            SMOKE_STATE_SCRIPT,
            -1,
            None,
            self.backend.url,
            None,
            self._on_smoke_state,
            None,
        )
        return GLib.SOURCE_CONTINUE

    def _on_smoke_state(
        self,
        web_view: WebKit.WebView,
        result: Gio.AsyncResult,
        _user_data: object,
    ) -> None:
        self._smoke_evaluation_pending = False
        if self._smoke_finished:
            return
        try:
            value = web_view.evaluate_javascript_finish(result)
            state = json.loads(value.to_json(0))
        except (GLib.Error, TypeError, ValueError, json.JSONDecodeError):
            return
        payload = normalized_smoke_payload(state)
        if payload is None:
            return
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)
        self._finish_smoke(0)

    def _on_smoke_timeout(self) -> bool:
        self._smoke_timeout_source = 0
        self._fail_smoke("timeout")
        return GLib.SOURCE_REMOVE

    def _fail_smoke(self, error: str, detail: str | None = None) -> None:
        if self._smoke_finished:
            return
        payload: dict[str, object] = {"ok": False, "error": error}
        if detail:
            payload["detail"] = detail
        print(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            file=sys.stderr,
            flush=True,
        )
        self._finish_smoke(2)

    def _remove_smoke_sources(self) -> None:
        for attribute in ("_smoke_poll_source", "_smoke_timeout_source"):
            source = getattr(self, attribute)
            if source:
                GLib.source_remove(source)
                setattr(self, attribute, 0)

    def _finish_smoke(self, exit_code: int) -> None:
        if self._smoke_finished:
            return
        self._smoke_finished = True
        self.exit_code = exit_code
        self._remove_smoke_sources()
        self.backend.close()
        if self.window is not None:
            self.window.destroy()
        self.quit()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex Pixel Office desktop application")
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
        "--smoke-test",
        action="store_true",
        help="load the complete UI, report JSON readiness, and exit automatically",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not GTK_AVAILABLE:
        error_payload = {"ok": False, "error": "gtk-unavailable"}
        if args.smoke_test:
            print(
                json.dumps(error_payload, separators=(",", ":")),
                file=sys.stderr,
                flush=True,
            )
            return 2
        print(
            "Could not open Codex Pixel Office: GTK4 and WebKitGTK 6 are not available. "
            "On Windows, run windows_app.py instead.",
            file=sys.stderr,
        )
        return 1
    display_available = Gtk.init_check() and Gdk.Display.get_default() is not None
    if not display_available:
        if args.smoke_test:
            print(
                json.dumps(
                    {"ok": False, "error": "display-unavailable"},
                    separators=(",", ":"),
                ),
                file=sys.stderr,
                flush=True,
            )
            return 2
        print("Could not open Codex Pixel Office: no graphical display is available", file=sys.stderr)
        return 1

    try:
        backend = LocalOfficeServer(
            args.codex_home,
            args.active_minutes,
            codex_bin=args.codex_bin,
        )
        backend.start()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Could not start Codex Pixel Office: {error}", file=sys.stderr)
        return 1

    application = PixelOfficeApplication(
        backend,
        fullscreen=args.fullscreen,
        smoke_test=args.smoke_test,
    )
    try:
        run_status = application.run([])
        if args.smoke_test and not application._smoke_finished:
            print(
                json.dumps(
                    {"ok": False, "error": "application-exited-before-ready"},
                    separators=(",", ":"),
                ),
                file=sys.stderr,
                flush=True,
            )
            return 2
        return application.exit_code or int(run_status)
    except (GLib.Error, RuntimeError) as error:
        print(f"Could not open Codex Pixel Office: {error}", file=sys.stderr)
        return 1
    finally:
        backend.close()


if __name__ == "__main__":
    raise SystemExit(main())

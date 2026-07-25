import io
from collections import UserDict
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import windows_app  # noqa: E402
from desktop_common import resolve_windows_icon_path  # noqa: E402


class FakeRegistryKey:
    def __init__(self, values):
        self.values = values

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return None


class FakeRegistry:
    HKEY_CURRENT_USER = "hkcu"
    HKEY_LOCAL_MACHINE = "hklm"
    KEY_READ = 1
    KEY_WOW64_32KEY = 2
    KEY_WOW64_64KEY = 4
    WEBVIEW2_VERSION = "136.0.3240.76"
    DOTNET_RELEASE = 528040

    @classmethod
    def OpenKey(cls, _hive, key_path, _reserved, _access):
        if windows_app.WEBVIEW2_CLIENT_ID in key_path:
            return FakeRegistryKey({"pv": cls.WEBVIEW2_VERSION})
        if key_path == windows_app.DOTNET_FRAMEWORK_KEY:
            return FakeRegistryKey({"Release": cls.DOTNET_RELEASE})
        raise FileNotFoundError(key_path)

    @staticmethod
    def QueryValueEx(key, name):
        if name not in key.values:
            raise FileNotFoundError(name)
        return key.values[name], 1


class OldWebViewRegistry(FakeRegistry):
    WEBVIEW2_VERSION = "85.0.1.0"


class OldDotNetRegistry(FakeRegistry):
    DOTNET_RELEASE = windows_app.DOTNET_FRAMEWORK_MIN_RELEASE - 1


class MissingWebViewRegistry(FakeRegistry):
    WEBVIEW2_VERSION = "0.0.0.0"


class FakeWindow:
    def __init__(self):
        self.destroyed = False

    def evaluate_js(self, _script):
        return {
            "ready": True,
            "sessions": 0,
            "actions": [],
            "roaming": 0,
            "reactions": [],
            "roamingEnabled": True,
        }

    def destroy(self):
        self.destroyed = True


class FakeWebview:
    def __init__(self):
        self.renderer = "edgechromium"
        self.settings = UserDict(
            {
                "ALLOW_DOWNLOADS": True,
                "ALLOW_FILE_URLS": True,
                "OPEN_EXTERNAL_LINKS_IN_BROWSER": False,
                "WEBVIEW2_RUNTIME_PATH": None,
            }
        )
        self.window = FakeWindow()
        self.create_calls = []
        self.start_calls = []

    def create_window(self, *args, **kwargs):
        self.create_calls.append((args, kwargs))
        return self.window

    def start(self, func=None, args=None, **kwargs):
        self.start_calls.append((func, args, kwargs))
        if func is not None:
            func(*(args or ()))


class FakeBackend:
    url = "http://127.0.0.1:54321/"
    static_root = PROJECT_ROOT / "static"

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return None


class WindowsAppTests(unittest.TestCase):
    def test_parser_and_non_windows_entrypoint(self):
        args = windows_app.build_parser().parse_args(
            [
                "--codex-home",
                r"C:\Users\Pixel\.codex",
                "--active-minutes",
                "12.5",
                "--codex-bin",
                r"C:\Tools\codex.cmd",
                "--fullscreen",
                "--debug",
            ]
        )
        self.assertEqual(12.5, args.active_minutes)
        self.assertTrue(args.fullscreen)
        self.assertTrue(args.debug)
        self.assertTrue(args.codex_bin.endswith("codex.cmd"))

        if sys.platform != "win32":
            error = io.StringIO()
            with redirect_stderr(error):
                result = windows_app.main([])
            self.assertEqual(1, result)
            self.assertIn("only supported on Windows", error.getvalue())

    def test_webview2_registry_and_fixed_runtime_detection(self):
        self.assertEqual(
            "136.0.3240.76",
            windows_app.registered_webview2_version(FakeRegistry),
        )
        self.assertIsNone(windows_app.require_webview2(registry=FakeRegistry))
        self.assertEqual(528040, windows_app.registered_dotnet_release(FakeRegistry))
        self.assertTrue(
            windows_app.webview2_version_is_supported("136.0.3240.76")
        )
        self.assertFalse(windows_app.webview2_version_is_supported("85.0.1.0"))
        with self.assertRaisesRegex(
            windows_app.WindowsDesktopError,
            "WebView2 Runtime",
        ):
            windows_app.require_webview2(
                environment={}, registry=MissingWebViewRegistry
            )
        with self.assertRaisesRegex(windows_app.WindowsDesktopError, "86.0.622.0"):
            windows_app.require_webview2(environment={}, registry=OldWebViewRegistry)
        with self.assertRaisesRegex(windows_app.WindowsDesktopError, ".NET Framework"):
            windows_app.require_webview2(environment={}, registry=OldDotNetRegistry)

        with tempfile.TemporaryDirectory() as tempdir:
            runtime = Path(tempdir) / "Fixed Runtime"
            runtime.mkdir()
            (runtime / "msedgewebview2.exe").write_bytes(b"runtime")
            detected = windows_app.require_webview2(
                environment={"CODEX_PIXEL_WEBVIEW2_RUNTIME": str(runtime)},
                registry=FakeRegistry,
            )
            self.assertEqual(runtime.resolve(), detected)

            with self.assertRaisesRegex(windows_app.WindowsDesktopError, "invalid"):
                windows_app.require_webview2(
                    environment={
                        "CODEX_PIXEL_WEBVIEW2_RUNTIME": str(runtime / "missing")
                    },
                    registry=object(),
                )

        with self.assertRaisesRegex(windows_app.WindowsDesktopError, "UNC"):
            windows_app.require_webview2(
                environment={"CODEX_PIXEL_WEBVIEW2_RUNTIME": r"\\server\runtime"},
                registry=FakeRegistry,
            )

    def test_missing_pywebview_has_actionable_error(self):
        def missing(_name):
            raise ModuleNotFoundError("webview")

        with self.assertRaisesRegex(
            windows_app.WindowsDesktopError,
            "requirements-windows.txt",
        ):
            windows_app.load_webview(missing)

    def test_windows_icon_prefers_ico(self):
        icon = resolve_windows_icon_path(PROJECT_ROOT / "static")
        self.assertIsNotNone(icon)
        self.assertEqual(".ico", icon.suffix.lower())
        with tempfile.TemporaryDirectory() as tempdir:
            assets = Path(tempdir) / "assets"
            assets.mkdir()
            (assets / "app-icon.png").write_bytes(b"png")
            self.assertIsNone(resolve_windows_icon_path(tempdir))

    def test_webview_window_contract_and_smoke(self):
        args = windows_app.build_parser().parse_args(
            ["--fullscreen", "--smoke-test"]
        )
        webview = FakeWebview()
        with tempfile.TemporaryDirectory() as tempdir:
            output = io.StringIO()
            with redirect_stdout(output):
                result = windows_app.run_webview(
                    args,
                    webview,
                    FakeBackend(),
                    environment={"LOCALAPPDATA": tempdir},
                )

            self.assertEqual(0, result)
            self.assertTrue(webview.window.destroyed)
            self.assertIn('"ok":true', output.getvalue())
            self.assertEqual(1, len(webview.create_calls))
            title_args, window_options = webview.create_calls[0]
            self.assertEqual((windows_app.WINDOW_TITLE,), title_args)
            self.assertEqual(FakeBackend.url, window_options["url"])
            self.assertTrue(window_options["fullscreen"])
            self.assertEqual((1440, 900), (
                window_options["width"],
                window_options["height"],
            ))
            self.assertEqual("edgechromium", webview.start_calls[0][2]["gui"])
            self.assertFalse(webview.start_calls[0][2]["private_mode"])
            self.assertFalse(webview.settings["ALLOW_DOWNLOADS"])
            self.assertFalse(webview.settings["ALLOW_FILE_URLS"])

    def test_smoke_test_defaults_to_failure_if_startup_callback_never_runs(self):
        class EarlyReturnWebview(FakeWebview):
            def start(self, func=None, args=None, **kwargs):
                self.start_calls.append((func, args, kwargs))

        args = windows_app.build_parser().parse_args(["--smoke-test"])
        webview = EarlyReturnWebview()
        with tempfile.TemporaryDirectory() as tempdir:
            result = windows_app.run_webview(
                args,
                webview,
                FakeBackend(),
                environment={"LOCALAPPDATA": tempdir},
            )
        self.assertEqual(2, result)

    def test_normal_startup_rejects_a_webview2_page_that_never_becomes_ready(self):
        class NeverLoadedEvent:
            def wait(self, _timeout):
                return False

        class NeverReadyWindow(FakeWindow):
            def __init__(self):
                super().__init__()
                self.events = type("Events", (), {"loaded": NeverLoadedEvent()})()

            def evaluate_js(self, _script):
                raise AssertionError("JavaScript must not run before WebView2 reports a load")

        class NeverReadyWebview(FakeWebview):
            def __init__(self):
                super().__init__()
                self.window = NeverReadyWindow()

        args = windows_app.build_parser().parse_args(
            ["--smoke-timeout", "0.001"]
        )
        webview = NeverReadyWebview()
        with tempfile.TemporaryDirectory() as tempdir, self.assertRaisesRegex(
            windows_app.WindowsDesktopError,
            "did not become ready",
        ):
            windows_app.run_webview(
                args,
                webview,
                FakeBackend(),
                environment={"LOCALAPPDATA": tempdir},
            )
        self.assertTrue(webview.window.destroyed)

    def test_main_catches_pywebview_style_exceptions(self):
        class FakeWebViewException(Exception):
            pass

        error = io.StringIO()
        with (
            mock.patch.object(windows_app.sys, "platform", "win32"),
            mock.patch.object(windows_app, "require_webview2", return_value=None),
            mock.patch.object(windows_app, "load_webview", return_value=object()),
            mock.patch.object(
                windows_app,
                "LocalOfficeServer",
                return_value=FakeBackend(),
            ),
            mock.patch.object(
                windows_app,
                "run_webview",
                side_effect=FakeWebViewException("managed GUI failed"),
            ),
            redirect_stderr(error),
        ):
            result = windows_app.main(["--smoke-test"])
        self.assertEqual(2, result)
        self.assertIn("managed GUI failed", error.getvalue())


if __name__ == "__main__":
    unittest.main()

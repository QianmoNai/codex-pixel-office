import io
import json
from contextlib import redirect_stderr, redirect_stdout
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import desktop_app  # noqa: E402


class FakeChatService:
    """Lifecycle spy that represents one owned, still-running child process."""

    def __init__(self):
        self.close_calls = 0
        self.start_calls = 0
        self.child_running = True

    def start(self, *_args, **_kwargs):
        self.start_calls += 1
        raise AssertionError("a read-only dashboard smoke test must not start chat")

    def close(self):
        self.close_calls += 1
        self.child_running = False


class LocalOfficeServerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.codex_home = self.root / ".codex"
        self.codex_home.mkdir()
        self.static_root = self.root / "static"
        self.static_root.mkdir()
        (self.static_root / "index.html").write_text(
            "<!doctype html><title>Pixel Office test</title>",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_backend_binds_random_loopback_port_and_stops_reliably(self):
        backend = desktop_app.LocalOfficeServer(
            self.codex_home,
            12.5,
            static_root=self.static_root,
        )
        self.assertFalse(backend.is_running)
        with self.assertRaises(RuntimeError):
            _ = backend.url

        url = backend.start()
        thread = backend.thread
        server = backend.server
        self.assertIsNotNone(thread)
        self.assertIsNotNone(server)
        self.assertTrue(backend.is_running)
        self.assertEqual(url, backend.start())
        self.assertEqual("127.0.0.1", server.server_address[0])
        self.assertGreater(server.server_port, 0)

        with urlopen(url + "api/health", timeout=2) as response:
            health = json.load(response)
        self.assertEqual("degraded", health["status"])
        with urlopen(url, timeout=2) as response:
            self.assertIn(b"Pixel Office test", response.read())

        port = server.server_port
        backend.close()
        backend.close()
        self.assertFalse(backend.is_running)
        self.assertFalse(thread.is_alive())
        with self.assertRaises(RuntimeError):
            backend.start()
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=0.25)

    def test_context_manager_closes_server_after_error(self):
        backend = desktop_app.LocalOfficeServer(
            self.codex_home,
            static_root=self.static_root,
        )
        with self.assertRaisesRegex(RuntimeError, "inside test"):
            with backend:
                thread = backend.thread
                self.assertTrue(backend.is_running)
                raise RuntimeError("inside test")
        self.assertIsNotNone(thread)
        self.assertFalse(thread.is_alive())

    def test_readiness_probe_ignores_http_proxy_environment(self):
        backend = desktop_app.LocalOfficeServer(
            self.codex_home,
            static_root=self.static_root,
        )
        proxy_environment = {
            "HTTP_PROXY": "http://127.0.0.1:1",
            "http_proxy": "http://127.0.0.1:1",
            "NO_PROXY": "",
            "no_proxy": "",
        }
        try:
            with mock.patch.dict(os.environ, proxy_environment):
                url = backend.start()
            self.assertTrue(url.startswith("http://127.0.0.1:"))
        finally:
            backend.close()

    def test_concurrent_close_waits_for_shutdown_to_finish(self):
        backend = desktop_app.LocalOfficeServer(
            self.codex_home,
            static_root=self.static_root,
        )
        backend.start()
        server = backend.server
        thread = backend.thread
        self.assertIsNotNone(server)
        self.assertIsNotNone(thread)

        shutdown_entered = threading.Event()
        allow_shutdown = threading.Event()
        original_shutdown = server.shutdown

        def delayed_shutdown():
            shutdown_entered.set()
            self.assertTrue(allow_shutdown.wait(timeout=2))
            original_shutdown()

        server.shutdown = delayed_shutdown
        errors = []

        def close_backend():
            try:
                backend.close()
            except BaseException as error:  # keep failures visible in this test thread
                errors.append(error)

        first = threading.Thread(target=close_backend)
        second = threading.Thread(target=close_backend)
        first.start()
        self.assertTrue(shutdown_entered.wait(timeout=1))
        second.start()
        time.sleep(0.05)
        self.assertTrue(second.is_alive())
        self.assertTrue(thread.is_alive())

        allow_shutdown.set()
        first.join(timeout=2)
        second.join(timeout=2)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertFalse(thread.is_alive())
        self.assertEqual([], errors)

    def test_static_bundle_must_exist(self):
        with self.assertRaises(FileNotFoundError):
            desktop_app.LocalOfficeServer(
                self.codex_home,
                static_root=self.root / "missing-static",
            )

    def test_close_cleans_chat_service_owned_child(self):
        chat_service = FakeChatService()
        backend = desktop_app.LocalOfficeServer(
            self.codex_home,
            static_root=self.static_root,
            chat_service=chat_service,
        )
        backend.start()
        self.assertTrue(chat_service.child_running)
        backend.close()

        self.assertFalse(chat_service.child_running)
        self.assertGreaterEqual(chat_service.close_calls, 1)
        self.assertEqual(0, chat_service.start_calls)

    def test_webkit_smoke_does_not_start_chat(self):
        if not desktop_app.GTK_AVAILABLE:
            self.skipTest("GTK4 and WebKitGTK 6 are not available")
        desktop_app.Gtk.init_check()
        if desktop_app.Gdk.Display.get_default() is None:
            self.skipTest("a graphical display is required for the WebKit smoke test")

        chat_service = FakeChatService()
        backend = desktop_app.LocalOfficeServer(
            self.codex_home,
            static_root=PROJECT_ROOT / "static",
            chat_service=chat_service,
        )
        backend.start()
        application = desktop_app.PixelOfficeApplication(
            backend,
            smoke_test=True,
        )
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                run_status = application.run([])
        finally:
            backend.close()

        self.assertEqual(0, run_status)
        self.assertEqual(0, application.exit_code)
        payload = json.loads(output.getvalue().strip().splitlines()[-1])
        self.assertTrue(payload["ok"])
        self.assertEqual(0, chat_service.start_calls)
        self.assertFalse(chat_service.child_running)
        self.assertGreaterEqual(chat_service.close_calls, 1)


class DesktopArgumentTests(unittest.TestCase):
    def test_supported_options_are_parsed(self):
        args = desktop_app.build_parser().parse_args(
            [
                "--codex-home",
                "/tmp/codex-test-home",
                "--active-minutes",
                "7.5",
                "--codex-bin",
                "/tmp/codex-test-bin",
                "--fullscreen",
                "--smoke-test",
            ]
        )
        self.assertEqual("/tmp/codex-test-home", args.codex_home)
        self.assertEqual(7.5, args.active_minutes)
        self.assertEqual("/tmp/codex-test-bin", args.codex_bin)
        self.assertTrue(args.fullscreen)
        self.assertTrue(args.smoke_test)

    def test_active_minutes_rejects_invalid_values(self):
        for value in ("0", "-1", "nan", "inf", "not-a-number"):
            with self.subTest(value=value):
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    desktop_app.build_parser().parse_args(
                        ["--active-minutes", value]
                    )

    def test_window_contract_and_icon_preference(self):
        self.assertEqual(
            "io.github.qianmo.CodexPixelOffice",
            desktop_app.APPLICATION_ID,
        )
        self.assertEqual((1440, 900), (
            desktop_app.DEFAULT_WINDOW_WIDTH,
            desktop_app.DEFAULT_WINDOW_HEIGHT,
        ))
        with tempfile.TemporaryDirectory() as tempdir:
            assets = Path(tempdir) / "assets"
            assets.mkdir()
            fallback = assets / "status-working.png"
            fallback.write_bytes(b"fallback")
            self.assertEqual(fallback.resolve(), desktop_app.resolve_icon_path(tempdir))
            preferred = assets / "app-icon.png"
            preferred.write_bytes(b"preferred")
            self.assertEqual(preferred.resolve(), desktop_app.resolve_icon_path(tempdir))

    def test_smoke_test_without_a_display_fails_with_json(self):
        environment = os.environ.copy()
        environment.pop("DISPLAY", None)
        environment.pop("WAYLAND_DISPLAY", None)
        environment["GDK_BACKEND"] = "x11"
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "desktop_app.py"),
                "--smoke-test",
                "--codex-home",
                "/tmp/codex-pixel-office-no-display",
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        json_lines = [
            line for line in result.stderr.splitlines() if line.startswith("{")
        ]
        self.assertTrue(json_lines, result.stderr)
        self.assertEqual(
            {
                "ok": False,
                "error": "display-unavailable" if desktop_app.GTK_AVAILABLE else "gtk-unavailable",
            },
            json.loads(json_lines[-1]),
        )


if __name__ == "__main__":
    unittest.main()

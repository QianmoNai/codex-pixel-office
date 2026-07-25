#!/usr/bin/env python3
"""Cross-platform desktop helpers for Codex Pixel Office."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from http.client import HTTPConnection

from server import (
    CodexChatService,
    DEFAULT_ACTIVE_MINUTES,
    PixelOfficeHTTPServer,
    SessionService,
    make_handler,
)


APPLICATION_ID = "io.github.qianmo.CodexPixelOffice"
WINDOW_TITLE = "Codex Pixel Office"
DEFAULT_WINDOW_WIDTH = 1440
DEFAULT_WINDOW_HEIGHT = 900
SERVER_START_TIMEOUT_SECONDS = 5.0
SERVER_STOP_TIMEOUT_SECONDS = 5.0
SMOKE_TEST_TIMEOUT_SECONDS = 15.0

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_STATIC_ROOT = PROJECT_ROOT / "static"


def resolve_icon_path(
    static_root: Path | str = DEFAULT_STATIC_ROOT,
    filenames: tuple[str, ...] = ("app-icon.png", "status-working.png"),
) -> Path | None:
    """Return the preferred bundled icon, with the status sprite as fallback."""

    assets = Path(static_root).resolve() / "assets"
    for filename in filenames:
        candidate = assets / filename
        if candidate.is_file():
            return candidate
    return None


def resolve_windows_icon_path(
    static_root: Path | str = DEFAULT_STATIC_ROOT,
) -> Path | None:
    return resolve_icon_path(static_root, ("app-icon.ico",))


class LocalOfficeServer:
    """Own the loopback HTTP server and its serving thread."""

    def __init__(
        self,
        codex_home: Path | str,
        active_minutes: float = DEFAULT_ACTIVE_MINUTES,
        *,
        static_root: Path | str = DEFAULT_STATIC_ROOT,
        codex_bin: Path | str | None = None,
        chat_service: CodexChatService | None = None,
    ) -> None:
        self.service = SessionService(codex_home, active_minutes)
        self.static_root = Path(static_root).expanduser().resolve()
        if not self.static_root.is_dir():
            raise FileNotFoundError(f"static bundle was not found: {self.static_root}")
        configured_codex_bin = codex_bin or os.environ.get("CODEX_PIXEL_CODEX_BIN") or "codex"
        self.chat_service = chat_service or CodexChatService(
            self.service,
            codex_bin=configured_codex_bin,
        )

        self._server: PixelOfficeHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._close_condition = threading.Condition(self._lock)
        self._closed = False
        self._closing = False

    @property
    def server(self) -> PixelOfficeHTTPServer | None:
        return self._server

    @property
    def thread(self) -> threading.Thread | None:
        return self._thread

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive() and not self._closed

    @property
    def url(self) -> str:
        server = self._server
        if server is None:
            raise RuntimeError("the local office server has not been started")
        return f"http://127.0.0.1:{server.server_port}/"

    def _serve(self) -> None:
        server = self._server
        if server is not None:
            server.serve_forever(poll_interval=0.1)

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + SERVER_START_TIMEOUT_SECONDS
        last_error: BaseException | None = None
        while time.monotonic() < deadline:
            thread = self._thread
            if thread is None or not thread.is_alive():
                raise RuntimeError("the local office server stopped during startup")
            connection: HTTPConnection | None = None
            try:
                server = self._server
                if server is None:
                    raise RuntimeError("the local office server is unavailable")
                connection = HTTPConnection(
                    "127.0.0.1",
                    server.server_port,
                    timeout=0.25,
                )
                connection.request("GET", "/api/health")
                response = connection.getresponse()
                if response.status == 200:
                    response.read()
                    return
            except OSError as error:
                last_error = error
                time.sleep(0.02)
            finally:
                if connection is not None:
                    connection.close()
        message = "timed out while starting the local office server"
        if last_error is not None:
            message += f": {last_error}"
        raise RuntimeError(message)

    def start(self) -> str:
        with self._lock:
            if self._closed:
                raise RuntimeError("a closed local office server cannot be restarted")
            if self.is_running:
                return self.url

            configured_handler = make_handler(
                self.service,
                self.static_root,
                self.chat_service,
            )

            class QuietDesktopHandler(configured_handler):
                def log_message(self, _format: str, *_args: object) -> None:
                    return

            self._server = PixelOfficeHTTPServer(
                ("127.0.0.1", 0),
                QuietDesktopHandler,
            )
            self._thread = threading.Thread(
                target=self._serve,
                name="codex-pixel-office-http",
                daemon=True,
            )
            self._thread.start()

        try:
            self._wait_until_ready()
        except BaseException:
            self.close()
            raise
        return self.url

    def close(self) -> None:
        with self._close_condition:
            if self._closed:
                while self._closing:
                    self._close_condition.wait()
                return
            self._closed = True
            self._closing = True
            server = self._server
            thread = self._thread

        try:
            if server is not None:
                try:
                    if thread is not None and thread.is_alive():
                        server.shutdown()
                finally:
                    server.server_close()
            if thread is not None and thread.is_alive():
                thread.join(timeout=SERVER_STOP_TIMEOUT_SECONDS)
        finally:
            with self._close_condition:
                self._closing = False
                self._close_condition.notify_all()

    def __enter__(self) -> "LocalOfficeServer":
        self.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


SMOKE_STATE_SCRIPT = r"""
(() => {
  const connection = document.getElementById("connectionText");
  const emptyOffice = document.getElementById("emptyOffice");
  const agents = document.querySelectorAll("#agentsLayer .agent[data-session-id]");
  const actions = [...agents].map((agent) => agent.dataset.action).filter(Boolean);
  const reactions = [...agents]
    .flatMap((agent) => [...agent.classList])
    .filter((name) => name.startsWith("reaction-"));
  const emptyVisible = Boolean(emptyOffice && !emptyOffice.hidden);
  return {
    ready: Boolean(connection && (emptyVisible || (agents.length > 0 && actions.length === agents.length))),
    sessions: agents.length,
    empty: emptyVisible,
    connection: connection ? connection.textContent.trim() : "",
    actions: [...new Set(actions)].sort(),
    roaming: document.querySelectorAll("#agentsLayer .agent.is-roaming").length,
    reactions: [...new Set(reactions)].sort(),
    roamingEnabled: document.getElementById("roamToggle")?.getAttribute("aria-pressed") === "true"
  };
})()
"""


def normalized_smoke_payload(state: object) -> dict[str, object] | None:
    """Normalize a browser smoke result shared by GTK and WebView2 shells."""

    if not isinstance(state, dict) or state.get("ready") is not True:
        return None
    sessions = int(state.get("sessions", 0))
    return {
        "ok": True,
        "state": "sessions" if sessions else "empty",
        "sessions": sessions,
        "actions": state.get("actions", []),
        "roaming": int(state.get("roaming", 0)),
        "reactions": state.get("reactions", []),
        "roaming_enabled": bool(state.get("roamingEnabled", False)),
    }


def encode_smoke_payload(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

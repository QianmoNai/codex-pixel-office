import json
from contextlib import redirect_stderr
import http.client
from http import HTTPStatus
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import server  # noqa: E402


def event(kind, **payload):
    return {"timestamp": "2023-11-14T22:13:20Z", "type": "event_msg", "payload": {"type": kind, **payload}}


class ActivityClassificationTests(unittest.TestCase):
    def test_core_statuses(self):
        cases = {
            "working": ([event("task_started")], "working"),
            "thinking": ([event("task_started"), event("reasoning")], "thinking"),
            "tool": (
                [
                    event("task_started"),
                    event("custom_tool_call", call_id="call-1", name="exec", input="secret"),
                ],
                "tool",
            ),
            "waiting": (
                [event("task_started"), event("task_complete")],
                "waiting",
            ),
            "idle": ([event("reasoning")], "idle"),
        }
        for name, (events, expected) in cases.items():
            with self.subTest(name=name):
                age = 301 if name == "idle" else 5
                status, _ = server.classify_activity(events, age, 300)
                self.assertEqual(expected, status)

    def test_tool_output_and_wait_tools(self):
        events = [
            event("custom_tool_call", call_id="call-1", name="exec"),
            event("custom_tool_call_output", call_id="call-1", output="private"),
        ]
        self.assertEqual(
            ("working", "Processing tool result"),
            server.classify_activity(events, 1),
        )
        waiting = [event("function_call", call_id="call-2", name="wait_agent")]
        self.assertEqual(
            ("waiting", "Waiting for agents"),
            server.classify_activity(waiting, 1),
        )

    def test_activity_never_contains_tool_arguments(self):
        secret = "do-not-display-this-command"
        _, activity = server.classify_activity(
            [event("custom_tool_call", call_id="x", name="exec", input=secret)],
            1,
        )
        self.assertNotIn(secret, activity)
        self.assertEqual("Using exec", activity)


class SessionServiceTests(unittest.TestCase):
    NOW = 1_700_000_000.0

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.home = Path(self.tempdir.name) / ".codex"
        self.home.mkdir()
        self.database = self.home / "state_5.sqlite"
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                source TEXT NOT NULL,
                model_provider TEXT NOT NULL,
                cwd TEXT NOT NULL,
                title TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at_ms INTEGER,
                updated_at_ms INTEGER,
                thread_source TEXT,
                model TEXT,
                first_user_message TEXT,
                agent_nickname TEXT,
                agent_role TEXT
            );
            CREATE TABLE thread_spawn_edges (
                parent_thread_id TEXT NOT NULL,
                child_thread_id TEXT NOT NULL PRIMARY KEY,
                status TEXT NOT NULL
            );
            """
        )
        rows = [
            (
                "parent-1111",
                "sessions/parent.jsonl",
                int(self.NOW - 100),
                int(self.NOW - 20),
                "cli",
                "openai",
                "/work/parent",
                "Parent task",
                0,
                int((self.NOW - 100) * 1000),
                int((self.NOW - 20) * 1000),
                "user",
                "gpt-test",
                "",
                None,
                None,
            ),
            (
                "child-2222",
                "sessions/child.jsonl",
                int(self.NOW - 90),
                int(self.NOW - 10),
                json.dumps(
                    {
                        "subagent": {
                            "thread_spawn": {"parent_thread_id": "parent-1111"}
                        }
                    }
                ),
                "openai",
                "/work/child",
                "Child task",
                0,
                int((self.NOW - 90) * 1000),
                int((self.NOW - 10) * 1000),
                "subagent",
                "gpt-test",
                "",
                "Ada",
                "researcher",
            ),
            (
                "old-3333",
                "sessions/old.jsonl",
                int(self.NOW - 4000),
                int(self.NOW - 3600),
                "cli",
                "openai",
                "/work/old",
                "Old task",
                0,
                None,
                None,
                "user",
                "gpt-test",
                "",
                None,
                None,
            ),
            (
                "archived-4444",
                "sessions/archived.jsonl",
                int(self.NOW - 100),
                int(self.NOW - 5),
                "cli",
                "openai",
                "/work/archived",
                "Archived task",
                1,
                None,
                None,
                "user",
                "gpt-test",
                "",
                None,
                None,
            ),
        ]
        connection.executemany(
            """
            INSERT INTO threads (
                id, rollout_path, created_at, updated_at, source, model_provider,
                cwd, title, archived, created_at_ms, updated_at_ms, thread_source,
                model, first_user_message, agent_nickname, agent_role
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.execute(
            "INSERT INTO thread_spawn_edges VALUES (?, ?, ?)",
            ("parent-1111", "child-2222", "open"),
        )
        connection.commit()
        connection.close()

        sessions = self.home / "sessions"
        sessions.mkdir()
        self._write_rollout(
            sessions / "parent.jsonl",
            [event("task_started"), event("task_complete")],
        )
        self._write_rollout(
            sessions / "child.jsonl",
            [
                event("task_started"),
                event(
                    "custom_tool_call",
                    call_id="tool-1",
                    name="exec",
                    input="should remain private",
                ),
            ],
        )

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def _write_rollout(path, events):
        path.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")

    def service(self):
        return server.SessionService(self.home, 30, now=lambda: self.NOW)

    def test_windows_command_resolution_and_process_group_options(self):
        batch_path = r"C:\Codex & Tools\codex.cmd"
        command = server.executable_command(
            "codex",
            ["exec", "resume", "session-123", "-"],
            platform_name="nt",
            resolver=lambda _value: batch_path,
            environment={"COMSPEC": r"C:\Windows\System32\cmd.exe"},
        )
        self.assertEqual(r"C:\Windows\System32\cmd.exe", command[0])
        self.assertEqual(["/d", "/s", "/c"], command[1:4])
        self.assertIn(f'"{batch_path}"', command[4])
        self.assertIn("session-123", command[4])

        direct = server.executable_command(
            "codex",
            ["--version"],
            platform_name="nt",
            resolver=lambda _value: r"C:\Tools\codex.exe",
        )
        self.assertEqual([r"C:\Tools\codex.exe", "--version"], direct)

        options = server.process_group_options("nt")
        self.assertIn("creationflags", options)
        self.assertTrue(
            options["creationflags"] & server.WINDOWS_CREATE_NEW_PROCESS_GROUP
        )
        self.assertTrue(options["creationflags"] & server.WINDOWS_CREATE_NO_WINDOW)
        self.assertEqual({"start_new_session": True}, server.process_group_options("posix"))

    def test_windows_process_tree_cleanup_uses_taskkill(self):
        calls = []

        class FakeProcess:
            pid = 4321

            def __init__(self):
                self.returncode = None
                self.kill_calls = 0
                self.terminate_calls = 0

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                if self.returncode is None:
                    raise subprocess.TimeoutExpired("fake", timeout)
                return self.returncode

            def terminate(self):
                self.terminate_calls += 1

            def kill(self):
                self.kill_calls += 1
                self.returncode = -9

        process = FakeProcess()

        def tree_runner(command, **kwargs):
            calls.append((command, kwargs))
            process.returncode = 1
            return subprocess.CompletedProcess(command, 0)

        chat = server.CodexChatService(
            self.service(),
            platform_name="nt",
            tree_runner=tree_runner,
        )
        chat._terminate_process(process)
        self.assertEqual(1, len(calls))
        self.assertEqual(["/PID", "4321", "/T", "/F"], calls[0][0][1:])
        self.assertIn("taskkill", calls[0][0][0].lower())
        self.assertEqual(0, process.terminate_calls)
        self.assertEqual(0, process.kill_calls)

    def test_read_only_database_uri_supports_special_paths(self):
        with tempfile.TemporaryDirectory() as tempdir:
            home = Path(tempdir) / "用户 # 100%" / ".codex"
            home.mkdir(parents=True)
            connection = sqlite3.connect(home / "state_5.sqlite")
            connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY)")
            connection.commit()
            connection.close()

            payload = server.SessionService(home).health_payload()
            self.assertEqual("ok", payload["status"])
            self.assertTrue(payload["database_available"])

    def _fake_codex(self):
        tool_dir = Path(self.tempdir.name) / "Codex & Tools"
        tool_dir.mkdir(exist_ok=True)
        script = tool_dir / "fake-codex.py"
        script.write_text(
            """import json
import os
import sys
import time

prompt = sys.stdin.read()
delay = float(os.environ.get("FAKE_CODEX_DELAY", "0"))
if delay:
    time.sleep(delay)
wait_file = os.environ.get("FAKE_CODEX_WAIT_FILE")
while wait_file and not os.path.exists(wait_file):
    time.sleep(0.01)
arguments = sys.argv[1:]
session_id = arguments[-2] if "resume" in arguments else os.environ.get("FAKE_CODEX_NEW_SESSION", "new-session-5555")
print(json.dumps({"type": "thread.started", "thread_id": session_id}), flush=True)
print(json.dumps({"type": "turn.started"}), flush=True)
print(json.dumps({"type": "item.completed", "item": {"type": "reasoning", "text": "reasoning-secret"}}), flush=True)
print(json.dumps({"type": "item.started", "item": {"type": "command_execution", "command": "tool-secret"}}), flush=True)
report = {"argv": sys.argv[1:], "prompt": prompt, "codex_home": os.environ.get("CODEX_HOME"), "cwd": os.getcwd()}
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(report)}}), flush=True)
print(json.dumps({"type": "turn.completed"}), flush=True)
print("stderr-secret", file=sys.stderr, flush=True)
""",
            encoding="utf-8",
        )
        if os.name == "nt":
            launcher = tool_dir / "fake-codex.cmd"
            launcher.write_text(
                f'@echo off\n"{sys.executable}" "{script}" %*\n',
                encoding="utf-8",
            )
            return launcher
        launcher = tool_dir / "fake-codex"
        launcher.write_text(
            f"#!{sys.executable}\n" + script.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        return launcher

    def _chat_server(self, chat_service):
        static = Path(self.tempdir.name) / f"chat-static-{time.monotonic_ns()}"
        static.mkdir()
        (static / "index.html").write_text("pixel office", encoding="utf-8")
        httpd = server.PixelOfficeHTTPServer(
            ("127.0.0.1", 0),
            server.make_handler(self.service(), static, chat_service),
        )
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return httpd, thread

    @staticmethod
    def _open_chat_stream(
        httpd,
        payload,
        *,
        content_type="application/json",
        path="/api/chat",
    ):
        body = json.dumps(payload).encode("utf-8")
        connection = http.client.HTTPConnection(
            "127.0.0.1", httpd.server_port, timeout=5
        )
        connection.request(
            "POST",
            path,
            body=body,
            headers={"Content-Type": content_type},
        )
        response = connection.getresponse()
        return connection, response

    @classmethod
    def _post_chat(
        cls,
        httpd,
        payload,
        *,
        content_type="application/json",
        path="/api/chat",
    ):
        connection, response = cls._open_chat_stream(
            httpd,
            payload,
            content_type=content_type,
            path=path,
        )
        status = response.status
        content_type_header = response.getheader("Content-Type") or ""
        data = response.read()
        connection.close()
        return status, content_type_header, data

    def test_active_minutes_rejects_non_finite_and_non_positive_values(self):
        for value in (float("nan"), float("inf"), float("-inf"), 0, -1):
            with self.subTest(service_value=value):
                with self.assertRaises(ValueError):
                    server.SessionService(self.home, value)
            with self.subTest(cli_value=value):
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    server.build_parser().parse_args(
                        ["--active-minutes", str(value)]
                    )

        service = server.SessionService(self.home, "0.5", now=lambda: self.NOW)
        payload = service.sessions_payload()
        self.assertTrue(payload["database_available"])
        self.assertEqual(0.5, payload["active_minutes"])
        self.assertNotIn("NaN", json.dumps(payload, allow_nan=False))

    def test_sessions_payload_filters_and_shapes_rows(self):
        payload = self.service().sessions_payload()
        self.assertTrue(payload["database_available"])
        self.assertIsNone(payload["warning"])
        self.assertEqual(["child-2222", "parent-1111"], [item["id"] for item in payload["sessions"]])
        self.assertEqual(1, payload["counts"]["tool"])
        self.assertEqual(1, payload["counts"]["waiting"])
        self.assertEqual(2, sum(payload["counts"].values()))

        child = payload["sessions"][0]
        required = {
            "id",
            "title",
            "cwd",
            "model",
            "source",
            "updated_at",
            "age_seconds",
            "status",
            "activity",
            "is_subagent",
            "parent_id",
            "color_seed",
            "short_id",
        }
        self.assertLessEqual(required, child.keys())
        self.assertTrue(child["is_subagent"])
        self.assertEqual("parent-1111", child["parent_id"])
        self.assertEqual("subagent", child["source"])
        self.assertEqual("Using exec", child["activity"])
        self.assertNotIn("should remain private", child["activity"])
        self.assertIsInstance(child["color_seed"], int)

    def test_history_payload_searches_unarchived_sessions_without_rollouts(self):
        service = self.service()
        with mock.patch.object(
            service,
            "_rollout_activity",
            side_effect=AssertionError("history must not inspect rollout content"),
        ):
            payload = service.history_payload(limit=10)
        self.assertTrue(payload["database_available"])
        self.assertEqual(
            ["child-2222", "parent-1111", "old-3333"],
            [item["id"] for item in payload["sessions"]],
        )
        self.assertNotIn("archived-4444", {item["id"] for item in payload["sessions"]})
        old = payload["sessions"][-1]
        self.assertFalse(old["is_active"])
        self.assertEqual("Old task", old["title"])

        searched = service.history_payload("old task", 10)
        self.assertEqual(["old-3333"], [item["id"] for item in searched["sessions"]])
        limited = service.history_payload("", 1)
        self.assertEqual(1, len(limited["sessions"]))

    def test_database_prefilters_active_rows_and_only_loads_their_edges(self):
        connection = sqlite3.connect(self.database)
        connection.execute(
            "INSERT INTO thread_spawn_edges VALUES (?, ?, ?)",
            ("parent-1111", "old-3333", "closed"),
        )
        connection.commit()
        connection.close()

        service = self.service()
        rows, parents = service._read_database(self.NOW - service.active_seconds)
        self.assertEqual(
            {"parent-1111", "child-2222"},
            {str(row["id"]) for row in rows},
        )
        self.assertEqual({"child-2222": "parent-1111"}, parents)

    def test_active_sql_filter_keeps_old_iso_timestamp_schemas_compatible(self):
        with tempfile.TemporaryDirectory() as tempdir:
            home = Path(tempdir) / ".codex"
            home.mkdir()
            database = home / "state_5.sqlite"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, updated_at TEXT)"
            )
            connection.executemany(
                "INSERT INTO threads VALUES (?, ?, ?)",
                [
                    ("iso-active", "missing.jsonl", server._utc_iso(self.NOW - 5)),
                    ("iso-old", "missing.jsonl", server._utc_iso(self.NOW - 4000)),
                ],
            )
            connection.commit()
            connection.close()

            payload = server.SessionService(
                home,
                30,
                now=lambda: self.NOW,
                snapshot_cache_seconds=0,
            ).sessions_payload()
            self.assertEqual(["iso-active"], [item["id"] for item in payload["sessions"]])

    def test_rollout_classification_cache_invalidates_on_file_change(self):
        service = server.SessionService(
            self.home,
            30,
            now=lambda: self.NOW,
            snapshot_cache_seconds=0,
        )
        original_reader = server.read_rollout_tail
        with mock.patch.object(
            server, "read_rollout_tail", wraps=original_reader
        ) as reader:
            first = service.sessions_payload()
            second = service.sessions_payload()
            self.assertEqual(2, reader.call_count)
            self.assertEqual(first["counts"], second["counts"])

            child_rollout = self.home / "sessions" / "child.jsonl"
            with child_rollout.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event("task_complete")) + "\n")
            changed = service.sessions_payload()

        self.assertEqual(3, reader.call_count)
        child = next(item for item in changed["sessions"] if item["id"] == "child-2222")
        self.assertEqual("waiting", child["status"])

    def test_session_snapshot_is_single_flight_and_refreshes_volatile_fields(self):
        wall_clock = [self.NOW]
        monotonic_clock = [100.0]
        service = server.SessionService(
            self.home,
            30,
            now=lambda: wall_clock[0],
            monotonic=lambda: monotonic_clock[0],
            snapshot_cache_seconds=10,
        )
        original_builder = service._build_sessions_payload
        entered = threading.Event()
        release = threading.Event()
        build_count = 0
        count_lock = threading.Lock()

        def slow_builder(now):
            nonlocal build_count
            with count_lock:
                build_count += 1
            entered.set()
            self.assertTrue(release.wait(2))
            return original_builder(now)

        results = []
        with mock.patch.object(service, "_build_sessions_payload", side_effect=slow_builder):
            workers = [
                threading.Thread(target=lambda: results.append(service.sessions_payload()))
                for _ in range(6)
            ]
            for worker in workers:
                worker.start()
            self.assertTrue(entered.wait(1))
            release.set()
            for worker in workers:
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())

            self.assertEqual(1, build_count)
            self.assertEqual(6, len(results))
            initial_age = results[0]["sessions"][0]["age_seconds"]
            initial_generated_at = results[0]["generated_at"]

            wall_clock[0] += 3
            cached = service.sessions_payload()
            self.assertEqual(1, build_count)
            self.assertEqual(initial_age + 3, cached["sessions"][0]["age_seconds"])
            self.assertNotEqual(initial_generated_at, cached["generated_at"])

            monotonic_clock[0] += 11
            release.set()
            service.sessions_payload()
            self.assertEqual(2, build_count)

    def test_chat_event_mapper_only_exposes_allowlisted_content(self):
        secret = "do-not-expose-command-or-reasoning"
        events = [
            {"type": "item.completed", "item": {"type": "reasoning", "text": secret}},
            {"type": "item.started", "item": {"type": "command_execution", "command": secret}},
            {"type": "item.started", "item": {"type": "mcp_tool_call", "arguments": secret}},
            {"type": "error", "message": secret},
        ]
        mapped = [server.map_codex_chat_event(item, "parent-1111") for item in events]
        serialized = json.dumps(mapped, ensure_ascii=False)
        self.assertNotIn(secret, serialized)
        self.assertIsNone(mapped[0])
        self.assertEqual("command", mapped[1]["tool"])
        self.assertEqual("mcp", mapped[2]["tool"])
        self.assertEqual("codex_failed", mapped[3]["code"])

        assistant = server.map_codex_chat_event(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "safe reply\nnext line"},
            },
            "parent-1111",
        )
        self.assertEqual("assistant", assistant["type"])
        self.assertEqual("safe reply\nnext line", assistant["message"])

        started = server.map_codex_chat_event(
            {"type": "thread.started", "thread_id": "new-session-5555"},
            None,
        )
        self.assertEqual("new-session-5555", started["session_id"])
        invalid = server.map_codex_chat_event(
            {"type": "thread.started", "thread_id": "--unsafe"},
            None,
        )
        self.assertEqual("invalid_session", invalid["code"])

    def test_resolve_chat_target_checks_database_and_falls_back(self):
        service = self.service()
        self.assertEqual(self.home.resolve(), service.resolve_chat_target("parent-1111"))
        self.assertIsNone(service.resolve_chat_target("missing-session"))
        self.assertIsNone(service.resolve_chat_target("archived-4444"))

    def test_chat_http_uses_fake_cli_and_filters_private_events(self):
        fake_codex = self._fake_codex()
        service = self.service()
        chat = server.CodexChatService(
            service,
            codex_bin=fake_codex,
            timeout_seconds=3,
            heartbeat_seconds=0.05,
        )
        httpd, thread = self._chat_server(chat)
        try:
            status, content_type, body = self._post_chat(
                httpd,
                {"session_id": "parent-1111", "message": "hello from office"},
            )
            self.assertEqual(200, status)
            self.assertIn("application/x-ndjson", content_type)
            events = [json.loads(line) for line in body.splitlines()]
            self.assertEqual("started", events[0]["status"])
            self.assertTrue(server.valid_chat_request_id(events[0].get("request_id")))
            self.assertEqual("done", events[-1]["type"])
            self.assertTrue(events[-1]["ok"])
            report_event = next(item for item in events if item["type"] == "assistant")
            report = json.loads(report_event["message"])
            self.assertEqual(
                [
                    "exec",
                    "resume",
                    "--json",
                    "--skip-git-repo-check",
                    "parent-1111",
                    "-",
                ],
                report["argv"],
            )
            self.assertEqual("hello from office", report["prompt"])
            self.assertEqual(str(self.home.resolve()), report["codex_home"])
            self.assertEqual(str(self.home.resolve()), report["cwd"])
            response_text = body.decode("utf-8")
            self.assertNotIn("reasoning-secret", response_text)
            self.assertNotIn("tool-secret", response_text)
            self.assertNotIn("stderr-secret", response_text)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_new_chat_http_creates_session_in_requested_directory(self):
        fake_codex = self._fake_codex()
        chat = server.CodexChatService(
            self.service(),
            codex_bin=fake_codex,
            timeout_seconds=3,
            heartbeat_seconds=0.05,
        )
        httpd, thread = self._chat_server(chat)
        try:
            status, content_type, body = self._post_chat(
                httpd,
                {
                    "cwd": str(self.home),
                    "message": "start overtime",
                    "model": "gpt-test",
                },
                path="/api/chat/new",
            )
            self.assertEqual(200, status)
            self.assertIn("application/x-ndjson", content_type)
            events = [json.loads(line) for line in body.splitlines()]
            self.assertTrue(server.valid_chat_request_id(events[0].get("request_id")))
            connected = next(
                item
                for item in events
                if item.get("status") == "connected"
            )
            self.assertEqual("new-session-5555", connected["session_id"])
            report = json.loads(
                next(item for item in events if item["type"] == "assistant")["message"]
            )
            self.assertEqual(
                [
                    "exec",
                    "--json",
                    "--skip-git-repo-check",
                    "--model",
                    "gpt-test",
                    "-",
                ],
                report["argv"],
            )
            self.assertEqual("start overtime", report["prompt"])
            self.assertEqual(str(self.home.resolve()), report["cwd"])
            self.assertTrue(events[-1]["ok"])

            status, _, response_body = self._post_chat(
                httpd,
                {"cwd": str(self.home / "missing"), "message": "hello"},
                path="/api/chat/new",
            )
            self.assertEqual(400, status)
            self.assertEqual("invalid_cwd", json.loads(response_body)["code"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_chat_model_override_validation_and_catalog(self):
        fake_codex = self._fake_codex()
        service = self.service()
        suggestions = server.CodexChatService(service, codex_bin=fake_codex).models_payload()
        self.assertEqual([{"id": "gpt-test", "label": "gpt-test"}], suggestions["models"])
        self.assertEqual("gpt-test", suggestions["default_model"])
        self.assertFalse(suggestions["authoritative"])
        self.assertTrue(suggestions["supports_custom"])

        (self.home / "config.toml").write_text('model = "gpt-config"\n', encoding="utf-8")
        configured = server.CodexChatService(service, codex_bin=fake_codex).models_payload()
        self.assertEqual("gpt-config", configured["default_model"])
        self.assertIn({"id": "gpt-config", "label": "gpt-config"}, configured["models"])

        chat = server.CodexChatService(
            service,
            codex_bin=fake_codex,
            timeout_seconds=3,
            heartbeat_seconds=0.05,
            allowed_models=["gpt-test", "gpt-safe/mini"],
            default_model="gpt-test",
        )
        httpd, thread = self._chat_server(chat)
        try:
            with urlopen(
                f"http://127.0.0.1:{httpd.server_port}/api/chat/models",
                timeout=2,
            ) as response:
                catalog = json.load(response)
            self.assertEqual(
                [
                    {"id": "gpt-safe/mini", "label": "gpt-safe/mini"},
                    {"id": "gpt-test", "label": "gpt-test"},
                ],
                catalog["models"],
            )
            self.assertEqual("gpt-test", catalog["default_model"])
            self.assertTrue(catalog["authoritative"])
            self.assertFalse(catalog["supports_custom"])

            status, _, body = self._post_chat(
                httpd,
                {
                    "session_id": "parent-1111",
                    "message": "use selected model",
                    "model": "gpt-test",
                },
            )
            self.assertEqual(200, status)
            events = [json.loads(line) for line in body.splitlines()]
            report = json.loads(next(item for item in events if item["type"] == "assistant")["message"])
            self.assertEqual(
                [
                    "exec",
                    "resume",
                    "--json",
                    "--skip-git-repo-check",
                    "--model",
                    "gpt-test",
                    "parent-1111",
                    "-",
                ],
                report["argv"],
            )

            for invalid_model in ("--dangerous", "gpt test", "gpt;rm", "", 123):
                with self.subTest(invalid_model=invalid_model):
                    status, _, response_body = self._post_chat(
                        httpd,
                        {
                            "session_id": "parent-1111",
                            "message": "hello",
                            "model": invalid_model,
                        },
                    )
                    self.assertEqual(400, status)
                    self.assertEqual("invalid_model", json.loads(response_body)["code"])

            status, _, response_body = self._post_chat(
                httpd,
                {
                    "session_id": "parent-1111",
                    "message": "hello",
                    "model": "gpt-unlisted",
                },
            )
            self.assertEqual(400, status)
            self.assertEqual("model_not_allowed", json.loads(response_body)["code"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_chat_model_catalog_uses_installed_codex_catalog(self):
        service = self.service()
        (self.home / "config.toml").write_text(
            'model = "gpt-catalog-one"\n',
            encoding="utf-8",
        )
        calls = []

        def catalog_runner(command, **kwargs):
            calls.append((command, kwargs))
            payload = {
                "models": [
                    {
                        "slug": "gpt-catalog-two",
                        "display_name": "GPT Catalog Two",
                        "visibility": "list",
                        "priority": 2,
                    },
                    {
                        "slug": "gpt-catalog-one",
                        "display_name": "GPT Catalog One",
                        "visibility": "list",
                        "priority": 1,
                    },
                    {
                        "slug": "gpt-hidden",
                        "display_name": "Hidden",
                        "visibility": "hidden",
                        "priority": 0,
                    },
                ]
            }
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(payload).encode("utf-8"),
                stderr=b"",
            )

        chat = server.CodexChatService(
            service,
            codex_bin="codex-test",
            catalog_runner=catalog_runner,
        )
        catalog = chat.models_payload()
        self.assertEqual(
            [
                {"id": "gpt-catalog-one", "label": "GPT Catalog One"},
                {"id": "gpt-catalog-two", "label": "GPT Catalog Two"},
                {"id": "gpt-test", "label": "gpt-test"},
            ],
            catalog["models"],
        )
        self.assertEqual("gpt-catalog-one", catalog["default_model"])
        self.assertEqual("codex_bundled_catalog", catalog["source"])
        self.assertEqual(
            ["codex-test", "debug", "models", "--bundled"],
            calls[0][0],
        )
        self.assertFalse(calls[0][1]["shell"])
        self.assertEqual(subprocess.DEVNULL, calls[0][1]["stdin"])

    def test_chat_http_validation_and_session_lock(self):
        fake_codex = self._fake_codex()
        service = self.service()
        chat = server.CodexChatService(
            service,
            codex_bin=fake_codex,
            timeout_seconds=3,
            heartbeat_seconds=0.05,
            max_concurrent=1,
        )
        httpd, thread = self._chat_server(chat)
        first_result = []
        try:
            status, _, _ = self._post_chat(
                httpd,
                {"session_id": "parent-1111", "message": "hello"},
                content_type="text/plain",
            )
            self.assertEqual(415, status)
            status, _, _ = self._post_chat(
                httpd,
                {"session_id": "missing-session", "message": "hello"},
            )
            self.assertEqual(404, status)
            status, _, _ = self._post_chat(
                httpd,
                {"session_id": "-bad-option", "message": "hello"},
            )
            self.assertEqual(400, status)
            status, _, _ = self._post_chat(
                httpd,
                {"session_id": "parent-1111", "message": "x" * 12001},
            )
            self.assertEqual(400, status)

            def first_request():
                first_result.append(
                    self._post_chat(
                        httpd,
                        {"session_id": "parent-1111", "message": "first"},
                    )[0]
                )

            release_file = Path(self.tempdir.name) / "release-fake-codex"
            with mock.patch.dict(os.environ, {"FAKE_CODEX_WAIT_FILE": str(release_file)}):
                request_thread = threading.Thread(target=first_request)
                request_thread.start()
                deadline = time.monotonic() + 2
                while chat.active_count == 0 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(1, chat.active_count)
                status, _, body = self._post_chat(
                    httpd,
                    {"session_id": "parent-1111", "message": "second"},
                )
                self.assertEqual(409, status)
                self.assertEqual("session_busy", json.loads(body)["code"])
                status, _, body = self._post_chat(
                    httpd,
                    {"session_id": "child-2222", "message": "different session"},
                )
                self.assertEqual(409, status)
                self.assertEqual("global_busy", json.loads(body)["code"])
                release_file.write_text("release", encoding="utf-8")
                request_thread.join(timeout=5)
            self.assertEqual([200], first_result)
            self.assertEqual(0, chat.active_count)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_chat_interrupt_stops_running_turn_and_stale_id_is_harmless(self):
        fake_codex = self._fake_codex()
        chat = server.CodexChatService(
            self.service(),
            codex_bin=fake_codex,
            timeout_seconds=5,
            heartbeat_seconds=1,
            terminate_grace_seconds=0.05,
        )
        httpd, thread = self._chat_server(chat)
        connections = []

        def open_blocked_turn(wait_file):
            with mock.patch.dict(
                os.environ,
                {"FAKE_CODEX_WAIT_FILE": str(wait_file)},
            ):
                connection, response = self._open_chat_stream(
                    httpd,
                    {"session_id": "parent-1111", "message": "keep working"},
                )
            connections.append(connection)
            self.assertEqual(HTTPStatus.OK, response.status)
            first_line = response.readline()
            self.assertTrue(first_line)
            first_event = json.loads(first_line)
            self.assertEqual("started", first_event["status"])
            self.assertTrue(server.valid_chat_request_id(first_event.get("request_id")))
            return response, first_event["request_id"]

        def interrupt(request_id):
            status, _, body = self._post_chat(
                httpd,
                {"request_id": request_id},
                path="/api/chat/interrupt",
            )
            self.assertEqual(HTTPStatus.OK, status)
            return json.loads(body)

        try:
            first_response, first_request_id = open_blocked_turn(
                Path(self.tempdir.name) / "interrupt-wait-first"
            )
            self.assertEqual(1, chat.active_count)

            first_interrupt = interrupt(first_request_id)
            self.assertTrue(first_interrupt["ok"])
            self.assertTrue(first_interrupt["interrupted"])
            first_events = [
                json.loads(line)
                for line in first_response.read().splitlines()
                if line.strip()
            ]
            self.assertEqual(
                "interrupted",
                next(item for item in first_events if item["type"] == "status")["status"],
            )
            first_done = next(item for item in first_events if item["type"] == "done")
            self.assertFalse(first_done["ok"])
            self.assertTrue(first_done["interrupted"])
            self.assertFalse(any(item["type"] == "error" for item in first_events))
            self.assertEqual(0, chat.active_count)

            repeated = interrupt(first_request_id)
            self.assertFalse(repeated["interrupted"])

            second_response, second_request_id = open_blocked_turn(
                Path(self.tempdir.name) / "interrupt-wait-second"
            )
            self.assertNotEqual(first_request_id, second_request_id)
            self.assertEqual(1, chat.active_count)

            stale = interrupt(first_request_id)
            self.assertFalse(stale["interrupted"])
            self.assertEqual(1, chat.active_count)

            current = interrupt(second_request_id)
            self.assertTrue(current["interrupted"])
            second_events = [
                json.loads(line)
                for line in second_response.read().splitlines()
                if line.strip()
            ]
            second_done = next(item for item in second_events if item["type"] == "done")
            self.assertTrue(second_done["interrupted"])
            self.assertEqual(0, chat.active_count)
        finally:
            for connection in connections:
                connection.close()
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_chat_interrupt_validates_request_id_and_requires_loopback(self):
        chat = server.CodexChatService(self.service(), codex_bin=self._fake_codex())
        httpd, thread = self._chat_server(chat)
        try:
            invalid_values = (
                None,
                "",
                "0" * 31,
                "0" * 33,
                "A" * 32,
                "g" * 32,
                123,
            )
            for request_id in invalid_values:
                with self.subTest(request_id=request_id):
                    status, _, body = self._post_chat(
                        httpd,
                        {"request_id": request_id},
                        path="/api/chat/interrupt",
                    )
                    self.assertEqual(HTTPStatus.BAD_REQUEST, status)
                    self.assertEqual("invalid_request_id", json.loads(body)["code"])

            status, _, body = self._post_chat(
                httpd,
                {"request_id": "f" * 32},
                path="/api/chat/interrupt",
            )
            self.assertEqual(HTTPStatus.OK, status)
            self.assertFalse(json.loads(body)["interrupted"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

        handler = object.__new__(server.PixelOfficeHandler)
        handler.client_address = ("192.168.1.50", 12345)
        handler._send_json = mock.Mock()
        handler.chat_service = mock.Mock()
        handler._handle_chat_interrupt()
        handler._send_json.assert_called_once_with(
            HTTPStatus.FORBIDDEN,
            {"error": "chat is only available from this computer"},
        )
        handler.chat_service.interrupt.assert_not_called()

    def test_chat_http_requires_bounded_json_body_and_loopback_client(self):
        handler = object.__new__(server.PixelOfficeHandler)
        handler.client_address = ("192.168.1.50", 12345)
        self.assertFalse(handler._client_is_loopback())
        handler.client_address = ("::1", 12345)
        self.assertTrue(handler._client_is_loopback())

        chat = server.CodexChatService(self.service(), codex_bin=self._fake_codex())
        httpd, thread = self._chat_server(chat)
        try:
            connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=2)
            connection.putrequest("POST", "/api/chat")
            connection.putheader("Content-Type", "application/json")
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(411, response.status)
            response.read()
            connection.close()

            connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=2)
            connection.putrequest("POST", "/api/chat")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(server.MAX_CHAT_BODY_BYTES + 1))
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(413, response.status)
            response.read()
            connection.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_chat_timeout_and_close_terminate_fake_cli(self):
        fake_codex = self._fake_codex()
        service = self.service()
        with mock.patch.dict(os.environ, {"FAKE_CODEX_DELAY": "2"}):
            chat = server.CodexChatService(
                service,
                codex_bin=fake_codex,
                timeout_seconds=0.15,
                heartbeat_seconds=0.05,
                terminate_grace_seconds=0.05,
            )
            job = chat.start("parent-1111", "timeout", self.home)
            events = list(chat.events_for(job))
            self.assertEqual("timeout", next(item for item in events if item["type"] == "error")["code"])
            self.assertFalse(events[-1]["ok"])
            self.assertEqual(0, chat.active_count)

            chat = server.CodexChatService(
                service,
                codex_bin=fake_codex,
                timeout_seconds=5,
                heartbeat_seconds=0.05,
                terminate_grace_seconds=0.05,
            )
            job = chat.start("parent-1111", "shutdown", self.home)
            self.assertIsNone(job.process.poll())
            chat.close()
            self.assertIsNotNone(job.process.poll())
            self.assertEqual(0, chat.active_count)

    def test_chat_deadline_covers_blocked_stdin_write(self):
        write_started = threading.Event()
        process_released = threading.Event()

        class BlockingStdin:
            def __init__(self):
                self.closed = False

            def write(self, value):
                write_started.set()
                process_released.wait(2)
                return len(value)

            def close(self):
                self.closed = True

        class FakeProcess:
            pid = None

            def __init__(self):
                self.stdin = BlockingStdin()
                self.stdout = io.BytesIO()
                self.stderr = io.BytesIO()
                self.returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                if self.returncode is None:
                    raise subprocess.TimeoutExpired("fake", timeout)
                return self.returncode

            def terminate(self):
                self.returncode = -15
                process_released.set()

            def kill(self):
                self.returncode = -9
                process_released.set()

        process = FakeProcess()
        chat = server.CodexChatService(
            self.service(),
            runner=lambda *args, **kwargs: process,
            platform_name="other",
            timeout_seconds=0.15,
            heartbeat_seconds=0.02,
            terminate_grace_seconds=0.01,
        )
        started_at = time.monotonic()
        job = chat.start("parent-1111", "blocked prompt", self.home)
        self.assertTrue(write_started.wait(1))
        self.assertLess(time.monotonic() - started_at, 1)

        events = list(chat.events_for(job))
        self.assertEqual(
            "timeout",
            next(item for item in events if item["type"] == "error")["code"],
        )
        self.assertFalse(events[-1]["ok"])
        self.assertIsNotNone(process.poll())
        self.assertEqual(0, chat.active_count)

    def test_ndjson_writes_use_the_remaining_chat_deadline(self):
        class FakeConnection:
            def __init__(self):
                self.timeouts = []

            def settimeout(self, value):
                self.timeouts.append(value)

        handler = object.__new__(server.PixelOfficeHandler)
        handler.chat_service = mock.Mock(monotonic=lambda: 10.0)
        handler.connection = FakeConnection()
        handler.wfile = io.BytesIO()

        handler._write_ndjson({"type": "status"}, 12.5)
        self.assertEqual([2.5], handler.connection.timeouts)
        self.assertEqual(b'{"type":"status"}\n', handler.wfile.getvalue())
        with self.assertRaises(TimeoutError):
            handler._write_ndjson({"type": "done"}, 9.0)

    def test_missing_rollout_and_missing_database_are_safe(self):
        (self.home / "sessions" / "child.jsonl").unlink()
        payload = self.service().sessions_payload()
        child = next(item for item in payload["sessions"] if item["id"] == "child-2222")
        self.assertEqual("working", child["status"])

        missing = server.SessionService(self.home / "missing", now=lambda: self.NOW)
        missing_payload = missing.sessions_payload()
        self.assertFalse(missing_payload["database_available"])
        self.assertEqual([], missing_payload["sessions"])
        self.assertEqual("degraded", missing.health_payload()["status"])

    def test_http_api_and_static_traversal_protection(self):
        static = Path(self.tempdir.name) / "static"
        static.mkdir()
        (static / "index.html").write_text("pixel office", encoding="utf-8")
        (Path(self.tempdir.name) / "secret.txt").write_text("secret", encoding="utf-8")
        httpd = server.PixelOfficeHTTPServer(
            ("127.0.0.1", 0), server.make_handler(self.service(), static)
        )
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_port}"
        try:
            with urlopen(base + "/api/health", timeout=2) as response:
                health = json.load(response)
            self.assertEqual("ok", health["status"])

            for host in (f"localhost:{httpd.server_port}", "127.0.0.1", f"[::1]:{httpd.server_port}"):
                with self.subTest(valid_host=host):
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", httpd.server_port, timeout=2
                    )
                    connection.request("GET", "/api/health", headers={"Host": host})
                    response = connection.getresponse()
                    self.assertEqual(200, response.status)
                    response.read()
                    connection.close()

            for host in ("attacker.example", "127.0.0.1.attacker.example", "localhost:99999"):
                with self.subTest(rejected_host=host):
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", httpd.server_port, timeout=2
                    )
                    connection.request(
                        "GET", "/api/health", headers={"Host": host}
                    )
                    response = connection.getresponse()
                    self.assertEqual(403, response.status)
                    self.assertEqual("invalid Host header", json.load(response)["error"])
                    connection.close()

            with urlopen(base + "/api/sessions", timeout=2) as response:
                api_payload = json.load(response)
            self.assertEqual(2, len(api_payload["sessions"]))

            with urlopen(
                base + "/api/sessions/history?q=Old&limit=10",
                timeout=2,
            ) as response:
                history = json.load(response)
            self.assertEqual(["old-3333"], [item["id"] for item in history["sessions"]])
            with self.assertRaises(HTTPError) as context:
                urlopen(base + "/api/sessions/history?limit=0", timeout=2)
            self.assertEqual(400, context.exception.code)
            context.exception.close()

            with urlopen(base + "/", timeout=2) as response:
                self.assertEqual(b"pixel office", response.read())

            with self.assertRaises(HTTPError) as context:
                urlopen(base + "/%2e%2e/secret.txt", timeout=2)
            self.assertEqual(404, context.exception.code)
            context.exception.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_sensitive_history_and_new_chat_require_loopback_client(self):
        handler = object.__new__(server.PixelOfficeHandler)
        handler.client_address = ("192.168.1.50", 12345)
        handler.path = "/api/sessions/history"
        handler._send_json = mock.Mock()
        handler._handle_history()
        self.assertEqual(HTTPStatus.FORBIDDEN, handler._send_json.call_args.args[0])

        handler._send_json.reset_mock()
        handler._handle_new_chat()
        self.assertEqual(HTTPStatus.FORBIDDEN, handler._send_json.call_args.args[0])

    def test_non_loopback_binding_allows_lan_host_headers(self):
        static = Path(self.tempdir.name) / "lan-static"
        static.mkdir()
        (static / "index.html").write_text("pixel office", encoding="utf-8")
        httpd = server.PixelOfficeHTTPServer(
            ("0.0.0.0", 0), server.make_handler(self.service(), static)
        )
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", httpd.server_port, timeout=2
            )
            connection.request(
                "GET", "/api/health", headers={"Host": "pixel-office.lan:8765"}
            )
            response = connection.getresponse()
            self.assertEqual(200, response.status)
            self.assertEqual("ok", json.load(response)["status"])
            connection.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_project_static_bundle_is_complete_and_served(self):
        static = PROJECT_ROOT / "static"
        required = {
            "/": "text/html",
            "/styles.css": "text/css",
            "/app.js": "text/javascript",
            "/assets/office-bg.png": "image/png",
            "/assets/worker-00.png": "image/png",
            "/assets/boss.png": "image/png",
        }
        httpd = server.PixelOfficeHTTPServer(
            ("127.0.0.1", 0), server.make_handler(self.service(), static)
        )
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_port}"
        try:
            for path, content_type in required.items():
                with self.subTest(path=path):
                    with urlopen(base + path, timeout=2) as response:
                        body = response.read()
                        self.assertEqual(200, response.status)
                        self.assertTrue(body)
                        self.assertTrue(
                            response.headers.get_content_type().startswith(content_type)
                        )
                        self.assertEqual("DENY", response.headers["X-Frame-Options"])
                        self.assertIn(
                            "default-src 'self'",
                            response.headers["Content-Security-Policy"],
                        )
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_overtime_frontend_contract_is_bundled(self):
        index = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        script = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "static" / "styles.css").read_text(encoding="utf-8")

        for element_id in (
            'id="overtimeButton"',
            'id="overtimeModal"',
            'id="overtimeNewPanel"',
            'id="overtimeHistoryPanel"',
            'id="overtimeHistoryList"',
        ):
            self.assertIn(element_id, index)
        self.assertIn('const HISTORY_API_URL = "/api/sessions/history"', script)
        self.assertIn('const NEW_CHAT_API_URL = "/api/chat/new"', script)
        self.assertIn(".overtime-mode-panel[hidden]", styles)

    def test_chat_interrupt_frontend_contract_is_bundled(self):
        index = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        script = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="chatInterrupt"', index)
        self.assertIn('const INTERRUPT_CHAT_API_URL = "/api/chat/interrupt"', script)
        self.assertIn("async function interruptChatMessage", script)
        self.assertIn("markChatInterrupted", script)
        self.assertIn(".chat-interrupt", styles)
        self.assertIn(".chat-status.is-interrupted", styles)


if __name__ == "__main__":
    unittest.main()

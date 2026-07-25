#!/usr/bin/env python3
"""Local, dependency-free backend for Codex Pixel Office."""

from __future__ import annotations

import argparse
from collections import OrderedDict
import hashlib
import ipaddress
import json
import math
import mimetypes
import os
from pathlib import Path
import queue
import re
import signal
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import tomllib
import uuid
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import parse_qs, unquote, urlsplit


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_ACTIVE_MINUTES = 30.0
DEFAULT_IDLE_SECONDS = 300.0
ROLLOUT_TAIL_BYTES = 1024 * 1024
ROLLOUT_CACHE_MAX_ENTRIES = 128
DEFAULT_SESSION_SNAPSHOT_CACHE_SECONDS = 0.75
STATUSES = ("working", "thinking", "tool", "waiting", "idle")
MAX_CHAT_BODY_BYTES = 64 * 1024
MAX_CHAT_MESSAGE_CHARS = 12_000
MAX_CHAT_SESSION_ID_CHARS = 256
MAX_CHAT_MODEL_CHARS = 128
MAX_CHAT_CWD_CHARS = 4096
MAX_HISTORY_QUERY_CHARS = 200
DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 100
MAX_CHAT_EVENT_LINE_BYTES = 256 * 1024
MAX_CHAT_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_CHAT_STDERR_BYTES = 16 * 1024
DEFAULT_CHAT_TIMEOUT_SECONDS = 10 * 60.0
DEFAULT_CHAT_HEARTBEAT_SECONDS = 5.0
DEFAULT_CHAT_MAX_CONCURRENT = 4
DEFAULT_CHAT_TERMINATE_GRACE_SECONDS = 1.0
DEFAULT_MODEL_CATALOG_TIMEOUT_SECONDS = 5.0
MAX_MODEL_CATALOG_BYTES = 2 * 1024 * 1024
CHAT_MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
CHAT_SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
WINDOWS_CREATE_NEW_PROCESS_GROUP = 0x00000200
WINDOWS_CREATE_NO_WINDOW = 0x08000000

TOOL_CALL_TYPES = {"custom_tool_call", "function_call"}
TOOL_OUTPUT_TYPES = {"custom_tool_call_output", "function_call_output"}
WAIT_TOOL_NAMES = {"request_user_input", "wait", "wait_agent"}
IGNORED_ACTIVITY_TYPES = {
    "token_count",
    "thread_settings_applied",
    "session_meta",
    "turn_context",
    "world_state",
    "inter_agent_communication_metadata",
}


def positive_finite_minutes(value: Any) -> float:
    """Argparse converter shared with tests; JSON must never receive NaN/Inf."""

    try:
        minutes = float(value)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if not math.isfinite(minutes) or minutes <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return minutes


def valid_chat_model(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= MAX_CHAT_MODEL_CHARS
        and CHAT_MODEL_PATTERN.fullmatch(value) is not None
    )


def valid_chat_session_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= MAX_CHAT_SESSION_ID_CHARS
        and CHAT_SESSION_ID_PATTERN.fullmatch(value) is not None
    )


def resolve_new_chat_cwd(value: Any) -> Path | None:
    """Resolve a local working directory without accepting options or NULs."""

    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= MAX_CHAT_CWD_CHARS
        or not value.strip()
        or "\x00" in value
    ):
        return None
    try:
        path = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    return path if path.is_dir() else None


def executable_command(
    executable: Path | str,
    arguments: Sequence[str],
    *,
    platform_name: str | None = None,
    resolver: Callable[[str], str | None] = shutil.which,
    environment: Mapping[str, str] | None = None,
) -> list[str]:
    """Resolve an executable and safely bridge Windows batch launchers."""

    platform_name = os.name if platform_name is None else platform_name
    executable_text = str(executable)
    resolved = resolver(executable_text) or executable_text
    command = [resolved, *[str(argument) for argument in arguments]]
    if platform_name != "nt" or Path(resolved).suffix.lower() not in {".bat", ".cmd"}:
        return command

    variables = os.environ if environment is None else environment
    comspec = variables.get("COMSPEC") or "cmd.exe"
    # cmd.exe needs the batch file as one command string. The executable is
    # always quoted so metacharacters in an installation path stay literal;
    # all user-controlled values in arguments are separately allowlisted.
    quoted_executable = f'"{resolved.replace("%", "%%")}"'
    argument_line = subprocess.list2cmdline(command[1:])
    inner = f"{quoted_executable} {argument_line}" if argument_line else quoted_executable
    return [comspec, "/d", "/s", "/c", f'"{inner}"']


def process_group_options(platform_name: str | None = None) -> dict[str, Any]:
    """Return platform-specific Popen options for reliable tree cleanup."""

    platform_name = os.name if platform_name is None else platform_name
    if platform_name == "posix":
        return {"start_new_session": True}
    if platform_name == "nt":
        flags = getattr(
            subprocess,
            "CREATE_NEW_PROCESS_GROUP",
            WINDOWS_CREATE_NEW_PROCESS_GROUP,
        )
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", WINDOWS_CREATE_NO_WINDOW)
        return {"creationflags": flags}
    return {}


def _utc_iso(epoch_seconds: float) -> str:
    dt = datetime.fromtimestamp(max(0.0, epoch_seconds), tz=timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _epoch_seconds(value: Any, *, milliseconds: bool = False) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    if milliseconds or number > 100_000_000_000:
        number /= 1000.0
    return number if number > 0 else None


def _event_parts(event: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        payload = {}
    kind = payload.get("type") or event.get("type") or ""
    return str(kind), payload


def _safe_tool_name(value: Any) -> str:
    name = str(value or "tool")
    name = re.sub(r"[^A-Za-z0-9_.:-]+", "_", name).strip("_")
    return (name or "tool")[:64]


def classify_activity(
    events: Sequence[Mapping[str, Any]],
    age_seconds: float,
    idle_after_seconds: float = DEFAULT_IDLE_SECONDS,
) -> tuple[str, str]:
    """Classify a rollout tail without exposing prompts or tool arguments."""

    pending_calls: dict[str, tuple[int, str]] = {}
    last_meaningful: tuple[int, str, Mapping[str, Any]] | None = None
    task_is_running = False

    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            continue
        kind, payload = _event_parts(event)

        if kind == "task_started":
            task_is_running = True
            pending_calls.clear()
        elif kind == "task_complete":
            task_is_running = False
            pending_calls.clear()
        elif kind in TOOL_CALL_TYPES:
            call_id = str(payload.get("call_id") or f"anonymous-{index}")
            pending_calls[call_id] = (index, _safe_tool_name(payload.get("name")))
        elif kind in TOOL_OUTPUT_TYPES:
            call_id = payload.get("call_id")
            if call_id is not None:
                pending_calls.pop(str(call_id), None)

        if kind not in IGNORED_ACTIVITY_TYPES:
            last_meaningful = (index, kind, payload)

    if age_seconds >= idle_after_seconds:
        return "idle", "Idle"

    if pending_calls:
        _, tool_name = max(pending_calls.values(), key=lambda item: item[0])
        if tool_name in WAIT_TOOL_NAMES:
            if tool_name == "request_user_input":
                return "waiting", "Waiting for input"
            if tool_name == "wait_agent":
                return "waiting", "Waiting for agents"
            return "waiting", "Waiting"
        return "tool", f"Using {tool_name}"

    if last_meaningful is None:
        return "working", "Active session"

    _, kind, payload = last_meaningful
    if kind == "task_complete":
        return "waiting", "Waiting for input"
    if kind == "reasoning":
        return "thinking", "Thinking"
    if kind in TOOL_CALL_TYPES:
        return "tool", f"Using {_safe_tool_name(payload.get('name'))}"
    if kind in TOOL_OUTPUT_TYPES:
        return "working", "Processing tool result"
    if kind == "image_generation_call":
        return "tool", "Generating an image"
    if kind in {"patch_apply_begin", "patch_apply_end"}:
        return "working", "Applying changes"
    if kind == "sub_agent_activity":
        return "working", "Coordinating agents"
    if kind in {"message", "agent_message"}:
        role = str(payload.get("role") or "")
        phase = str(payload.get("phase") or "")
        if phase == "final_answer":
            return "waiting", "Waiting for input"
        if role == "user":
            return "working", "Reading request"
        if task_is_running:
            return "working", "Writing a response"
        return "waiting", "Waiting for input"
    if kind in {"user_message", "task_started"}:
        return "working", "Reading request" if kind == "user_message" else "Starting task"
    if task_is_running:
        return "working", "Working"
    return "working", "Active session"


def read_rollout_tail(path: Path, max_bytes: int = ROLLOUT_TAIL_BYTES) -> list[dict[str, Any]]:
    """Read only the useful tail of an append-only rollout JSONL file."""

    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            offset = max(0, size - max_bytes)
            handle.seek(offset)
            data = handle.read(max_bytes)
    except OSError:
        return []

    if offset:
        newline = data.find(b"\n")
        if newline < 0:
            return []
        data = data[newline + 1 :]

    events: list[dict[str, Any]] = []
    for raw_line in data.splitlines():
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            # The final line can be incomplete while Codex is appending it.
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


class SessionService:
    def __init__(
        self,
        codex_home: Path | str,
        active_minutes: float = DEFAULT_ACTIVE_MINUTES,
        *,
        now: Callable[[], float] = time.time,
        idle_after_seconds: float = DEFAULT_IDLE_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        snapshot_cache_seconds: float = DEFAULT_SESSION_SNAPSHOT_CACHE_SECONDS,
    ) -> None:
        self.codex_home = Path(codex_home).expanduser().resolve()
        self.database_path = self.codex_home / "state_5.sqlite"
        self.active_minutes = float(active_minutes)
        if not math.isfinite(self.active_minutes) or self.active_minutes <= 0:
            raise ValueError("active_minutes must be a finite number greater than zero")
        self.active_seconds = self.active_minutes * 60.0
        self.idle_after_seconds = min(float(idle_after_seconds), self.active_seconds)
        self._now = now
        self._monotonic = monotonic
        self.snapshot_cache_seconds = max(0.0, float(snapshot_cache_seconds))
        self._rollout_cache_lock = threading.Lock()
        self._rollout_cache: OrderedDict[
            Path, tuple[tuple[int, int, int, int], tuple[str, str]]
        ] = OrderedDict()
        self._snapshot_condition = threading.Condition()
        self._snapshot_building = False
        self._snapshot_payload: dict[str, Any] | None = None
        self._snapshot_expires_at = 0.0

    def _connect_read_only(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise FileNotFoundError(self.database_path)
        uri = self.database_path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=0.25)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 250")
        return connection

    @staticmethod
    def _warning_for(error: BaseException) -> str:
        if isinstance(error, FileNotFoundError):
            return "Codex state database was not found"
        message = str(error).lower()
        if "locked" in message or "busy" in message:
            return "Codex state database is temporarily busy"
        return "Codex state database is unavailable"

    @staticmethod
    def _active_sql_filter(
        columns: set[str], cutoff: float
    ) -> tuple[str, list[float]]:
        """Build a conservative timestamp pre-filter for mixed Codex schemas.

        SQLite tables created by older Codex versions can store ISO timestamps or
        numeric-looking strings. Those rows stay in the candidate set and receive
        the exact Python conversion below; genuinely numeric rows are filtered in
        SQLite so the common schema does not require a full table scan in Python.
        """

        predicates: list[str] = []
        parameters: list[float] = []
        for name, threshold in (
            ("updated_at_ms", cutoff * 1000.0),
            ("updated_at", cutoff),
            ("created_at_ms", cutoff * 1000.0),
            ("created_at", cutoff),
        ):
            if name not in columns:
                continue
            predicates.append(
                f'("{name}" IS NOT NULL AND "{name}" >= ?)'
            )
            parameters.append(threshold)
        if not predicates:
            return "", []
        return "(" + " OR ".join(predicates) + ")", parameters

    def _read_database(self, cutoff: float) -> tuple[list[dict[str, Any]], dict[str, str]]:
        connection = self._connect_read_only()
        try:
            connection.execute("BEGIN")
            columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(threads)")
            }
            if "id" not in columns:
                raise sqlite3.DatabaseError("threads table is missing")

            wanted = (
                "id",
                "rollout_path",
                "created_at",
                "updated_at",
                "created_at_ms",
                "updated_at_ms",
                "recency_at",
                "recency_at_ms",
                "source",
                "thread_source",
                "model_provider",
                "model",
                "cwd",
                "title",
                "first_user_message",
                "agent_nickname",
                "agent_role",
                "archived",
            )
            selected = [name for name in wanted if name in columns]
            quoted = ", ".join(f'"{name}"' for name in selected)
            filters: list[str] = []
            parameters: list[float] = []
            if "archived" in columns:
                filters.append('COALESCE("archived", 0) = 0')
            timestamp_filter, timestamp_parameters = self._active_sql_filter(
                columns, cutoff
            )
            if timestamp_filter:
                filters.append(timestamp_filter)
                parameters.extend(timestamp_parameters)
            where = f" WHERE {' AND '.join(filters)}" if filters else ""
            candidates = [
                dict(row)
                for row in connection.execute(
                    f"SELECT {quoted} FROM threads{where}", parameters
                )
            ]
            # This fallback is intentionally retained after the SQL pre-filter:
            # it handles ISO timestamps and numeric text exactly like old builds.
            rows = []
            for row in candidates:
                updated = self._row_epoch(row, "updated") or self._row_epoch(
                    row, "created"
                )
                if updated is not None and updated >= cutoff:
                    rows.append(row)

            parents: dict[str, str] = {}
            edge_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(thread_spawn_edges)")
            }
            active_ids = [str(row.get("id") or "") for row in rows]
            active_ids = [session_id for session_id in active_ids if session_id]
            if active_ids and {"parent_thread_id", "child_thread_id"} <= edge_columns:
                # Stay comfortably below SQLite's variable limit on older builds.
                for offset in range(0, len(active_ids), 500):
                    batch = active_ids[offset : offset + 500]
                    placeholders = ",".join("?" for _ in batch)
                    for row in connection.execute(
                        "SELECT parent_thread_id, child_thread_id "
                        f"FROM thread_spawn_edges WHERE child_thread_id IN ({placeholders})",
                        batch,
                    ):
                        parents[str(row[1])] = str(row[0])
            return rows, parents
        finally:
            connection.close()

    @staticmethod
    def _row_epoch(row: Mapping[str, Any], prefix: str) -> float | None:
        candidates = [
            _epoch_seconds(row.get(f"{prefix}_at_ms"), milliseconds=True),
            _epoch_seconds(row.get(f"{prefix}_at")),
        ]
        valid = [candidate for candidate in candidates if candidate is not None]
        return max(valid) if valid else None

    def _safe_rollout_path(self, value: Any) -> Path | None:
        if not isinstance(value, str) or not value:
            return None
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.codex_home / path
        path = path.resolve()
        try:
            path.relative_to(self.codex_home)
        except ValueError:
            return None
        return path

    def _rollout_activity(self, path: Path, age_seconds: int) -> tuple[str, str]:
        """Classify one rollout, caching only its small age-independent result."""

        try:
            stat_result = path.stat()
        except OSError:
            with self._rollout_cache_lock:
                self._rollout_cache.pop(path, None)
            return classify_activity((), age_seconds, self.idle_after_seconds)
        signature = (
            int(stat_result.st_dev),
            int(stat_result.st_ino),
            int(stat_result.st_size),
            int(stat_result.st_mtime_ns),
        )
        with self._rollout_cache_lock:
            cached = self._rollout_cache.get(path)
            if cached is not None and cached[0] == signature:
                self._rollout_cache.move_to_end(path)
                base_status, base_activity = cached[1]
                if age_seconds >= self.idle_after_seconds:
                    return "idle", "Idle"
                return base_status, base_activity

            base_activity = classify_activity(
                read_rollout_tail(path), 0, self.idle_after_seconds
            )
            self._rollout_cache[path] = (signature, base_activity)
            self._rollout_cache.move_to_end(path)
            while len(self._rollout_cache) > ROLLOUT_CACHE_MAX_ENTRIES:
                self._rollout_cache.popitem(last=False)
            if age_seconds >= self.idle_after_seconds:
                return "idle", "Idle"
            return base_activity

    @staticmethod
    def _source_details(row: Mapping[str, Any]) -> tuple[str, str | None, bool]:
        raw_source = row.get("source")
        thread_source = str(row.get("thread_source") or "")
        parent_id: str | None = None
        structured_subagent = False
        if isinstance(raw_source, str) and raw_source.startswith("{"):
            try:
                source_object = json.loads(raw_source)
                spawn = source_object.get("subagent", {}).get("thread_spawn", {})
                if isinstance(spawn, Mapping):
                    parent = spawn.get("parent_thread_id")
                    parent_id = str(parent) if parent else None
                    structured_subagent = bool(spawn)
            except (AttributeError, json.JSONDecodeError):
                pass

        is_subagent = structured_subagent or thread_source == "subagent" or bool(parent_id)
        if is_subagent:
            source = "subagent"
        elif isinstance(raw_source, str) and raw_source:
            source = raw_source[:80]
        elif thread_source:
            source = thread_source[:80]
        else:
            source = "unknown"
        return source, parent_id, is_subagent

    def _build_sessions_payload(self, now: float) -> dict[str, Any]:
        active_minutes: int | float = (
            int(self.active_minutes) if self.active_minutes.is_integer() else self.active_minutes
        )
        payload: dict[str, Any] = {
            "sessions": [],
            "counts": {status: 0 for status in STATUSES},
            "generated_at": _utc_iso(now),
            "active_minutes": active_minutes,
            "database_available": False,
            "warning": None,
        }
        cutoff = now - self.active_seconds
        try:
            rows, parents = self._read_database(cutoff)
        except (FileNotFoundError, OSError, sqlite3.Error) as error:
            payload["warning"] = self._warning_for(error)
            return payload

        sessions: list[dict[str, Any]] = []
        for row in rows:
            updated = self._row_epoch(row, "updated") or self._row_epoch(row, "created")
            if updated is None or updated < cutoff:
                continue
            age_seconds = max(0, int(now - updated))
            session_id = str(row.get("id") or "")
            if not session_id:
                continue

            source, source_parent, is_subagent = self._source_details(row)
            parent_id = parents.get(session_id) or source_parent
            is_subagent = is_subagent or bool(parent_id)
            rollout_path = self._safe_rollout_path(row.get("rollout_path"))
            if rollout_path is None:
                status, activity = classify_activity(
                    (), age_seconds, self.idle_after_seconds
                )
            else:
                status, activity = self._rollout_activity(rollout_path, age_seconds)
            title = str(
                row.get("title") or row.get("first_user_message") or "Untitled session"
            )
            model = str(row.get("model") or row.get("model_provider") or "unknown")
            color_seed = int.from_bytes(
                hashlib.sha256(session_id.encode("utf-8")).digest()[:4], "big"
            )
            session = {
                "id": session_id,
                "title": title,
                "cwd": str(row.get("cwd") or ""),
                "model": model,
                "source": "subagent" if is_subagent else source,
                "updated_at": _utc_iso(updated),
                "age_seconds": age_seconds,
                "status": status,
                "activity": activity,
                "is_subagent": is_subagent,
                "parent_id": parent_id,
                "color_seed": color_seed,
                # UUIDv7 thread IDs share their timestamp-heavy prefix, so the
                # final eight characters are much more useful in a crowded UI.
                "short_id": session_id.replace("-", "")[-8:],
                "agent_nickname": row.get("agent_nickname"),
                "agent_role": row.get("agent_role"),
            }
            sessions.append(session)

        sessions.sort(key=lambda item: (item["age_seconds"], item["id"]))
        counts = {status: 0 for status in STATUSES}
        for session in sessions:
            counts[session["status"]] += 1
        payload.update(
            sessions=sessions,
            counts=counts,
            database_available=True,
        )
        return payload

    def _freshen_snapshot(
        self, payload: Mapping[str, Any], now: float
    ) -> dict[str, Any]:
        """Copy cached data while keeping response timestamps and ages current."""

        fresh = dict(payload)
        fresh["generated_at"] = _utc_iso(now)
        sessions: list[dict[str, Any]] = []
        cutoff = now - self.active_seconds
        for cached_session in payload.get("sessions", []):
            if not isinstance(cached_session, Mapping):
                continue
            updated = _epoch_seconds(cached_session.get("updated_at"))
            if updated is not None and updated < cutoff:
                continue
            session = dict(cached_session)
            if updated is not None:
                age_seconds = max(0, int(now - updated))
                session["age_seconds"] = age_seconds
                if age_seconds >= self.idle_after_seconds:
                    session["status"] = "idle"
                    session["activity"] = "Idle"
            sessions.append(session)
        counts = {status: 0 for status in STATUSES}
        for session in sessions:
            status = session.get("status")
            if status in counts:
                counts[str(status)] += 1
        fresh["sessions"] = sessions
        fresh["counts"] = counts
        return fresh

    def sessions_payload(self) -> dict[str, Any]:
        """Return a short-lived, single-flight snapshot for polling clients."""

        while True:
            cache_now = self._monotonic()
            wall_now = self._now()
            with self._snapshot_condition:
                if (
                    self._snapshot_payload is not None
                    and cache_now < self._snapshot_expires_at
                ):
                    return self._freshen_snapshot(self._snapshot_payload, wall_now)
                if not self._snapshot_building:
                    self._snapshot_building = True
                    break
                self._snapshot_condition.wait()

        try:
            payload = self._build_sessions_payload(wall_now)
        except BaseException:
            with self._snapshot_condition:
                self._snapshot_building = False
                self._snapshot_condition.notify_all()
            raise

        with self._snapshot_condition:
            self._snapshot_payload = payload
            self._snapshot_expires_at = (
                self._monotonic() + self.snapshot_cache_seconds
            )
            self._snapshot_building = False
            self._snapshot_condition.notify_all()
        return self._freshen_snapshot(payload, wall_now)

    @staticmethod
    def _history_epoch(row: Mapping[str, Any]) -> float | None:
        values = [
            _epoch_seconds(row.get("recency_at_ms"), milliseconds=True),
            _epoch_seconds(row.get("recency_at")),
            SessionService._row_epoch(row, "updated"),
            SessionService._row_epoch(row, "created"),
        ]
        valid = [value for value in values if value is not None]
        return max(valid) if valid else None

    @staticmethod
    def _history_matches(row: Mapping[str, Any], query: str) -> bool:
        if not query:
            return True
        needle = query.casefold()
        fields = (
            "id",
            "title",
            "first_user_message",
            "cwd",
            "model",
            "model_provider",
            "agent_nickname",
            "agent_role",
        )
        return any(
            needle in str(row.get(name) or "")[:10_000].casefold()
            for name in fields
        )

    def history_payload(
        self,
        query: str = "",
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> dict[str, Any]:
        """Return safe, unarchived thread metadata without reading rollout content."""

        now = self._now()
        payload: dict[str, Any] = {
            "sessions": [],
            "generated_at": _utc_iso(now),
            "database_available": False,
            "warning": None,
            "query": query,
            "limit": limit,
        }
        try:
            connection = self._connect_read_only()
            try:
                connection.execute("BEGIN")
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(threads)")
                }
                if "id" not in columns:
                    raise sqlite3.DatabaseError("threads table is missing")
                wanted = (
                    "id",
                    "created_at",
                    "updated_at",
                    "created_at_ms",
                    "updated_at_ms",
                    "recency_at",
                    "recency_at_ms",
                    "source",
                    "thread_source",
                    "model_provider",
                    "model",
                    "cwd",
                    "title",
                    "first_user_message",
                    "agent_nickname",
                    "agent_role",
                )
                selected = [name for name in wanted if name in columns]
                quoted = ", ".join(f'"{name}"' for name in selected)
                where = (
                    ' WHERE COALESCE("archived", 0) = 0'
                    if "archived" in columns
                    else ""
                )
                order_column = next(
                    (
                        name
                        for name in (
                            "recency_at_ms",
                            "updated_at_ms",
                            "recency_at",
                            "updated_at",
                            "created_at_ms",
                            "created_at",
                        )
                        if name in columns
                    ),
                    "id",
                )
                cursor = connection.execute(
                    f'SELECT {quoted} FROM threads{where} '
                    f'ORDER BY "{order_column}" DESC, "id" DESC'
                )
                rows: list[dict[str, Any]] = []
                while len(rows) < limit:
                    batch = cursor.fetchmany(256)
                    if not batch:
                        break
                    for raw_row in batch:
                        row = dict(raw_row)
                        if self._history_matches(row, query):
                            rows.append(row)
                            if len(rows) >= limit:
                                break

                parents: dict[str, str] = {}
                edge_columns = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info(thread_spawn_edges)"
                    )
                }
                session_ids = [
                    str(row.get("id") or "")
                    for row in rows
                    if valid_chat_session_id(row.get("id"))
                ]
                if session_ids and {
                    "parent_thread_id",
                    "child_thread_id",
                } <= edge_columns:
                    placeholders = ",".join("?" for _ in session_ids)
                    for edge in connection.execute(
                        "SELECT parent_thread_id, child_thread_id "
                        f"FROM thread_spawn_edges WHERE child_thread_id IN ({placeholders})",
                        session_ids,
                    ):
                        parents[str(edge[1])] = str(edge[0])
            finally:
                connection.close()
        except (FileNotFoundError, OSError, sqlite3.Error) as error:
            payload["warning"] = self._warning_for(error)
            return payload

        sessions: list[dict[str, Any]] = []
        for row in rows:
            session_id = str(row.get("id") or "")
            if not valid_chat_session_id(session_id):
                continue
            updated = self._history_epoch(row)
            age_seconds = max(0, int(now - updated)) if updated is not None else 0
            source, source_parent, is_subagent = self._source_details(row)
            parent_id = parents.get(session_id) or source_parent
            is_subagent = is_subagent or bool(parent_id)
            title = str(
                row.get("title")
                or row.get("first_user_message")
                or "Untitled session"
            ).strip()[:400]
            model_value = row.get("model") or row.get("model_provider") or "unknown"
            model = str(model_value)[:MAX_CHAT_MODEL_CHARS]
            sessions.append(
                {
                    "id": session_id,
                    "short_id": session_id.replace("-", "")[-8:],
                    "title": title or "Untitled session",
                    "cwd": str(row.get("cwd") or "")[:MAX_CHAT_CWD_CHARS],
                    "model": model,
                    "source": "subagent" if is_subagent else source,
                    "updated_at": _utc_iso(updated) if updated is not None else "",
                    "age_seconds": age_seconds,
                    "is_active": updated is not None and age_seconds <= self.active_seconds,
                    "is_subagent": is_subagent,
                    "parent_id": parent_id,
                    "agent_nickname": str(row.get("agent_nickname") or "")[:160],
                    "agent_role": str(row.get("agent_role") or "")[:160],
                }
            )
        payload.update(sessions=sessions, database_available=True)
        return payload

    def known_chat_models(self) -> list[str]:
        """Return safe model identifiers observed in unarchived local threads."""

        connection = self._connect_read_only()
        try:
            columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(threads)")
            }
            if "model" not in columns:
                return []
            archived = ' WHERE COALESCE("archived", 0) = 0' if "archived" in columns else ""
            rows = connection.execute(
                f'SELECT DISTINCT "model" FROM threads{archived} ORDER BY "model" LIMIT 128'
            )
            return sorted(
                {
                    str(row[0])
                    for row in rows
                    if valid_chat_model(row[0])
                }
            )
        finally:
            connection.close()

    def default_chat_model(self, known_models: Sequence[str] = ()) -> str | None:
        try:
            with (self.codex_home / "config.toml").open("rb") as handle:
                configured = tomllib.load(handle).get("model")
            if valid_chat_model(configured):
                return configured
        except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
            pass
        try:
            connection = self._connect_read_only()
            try:
                columns = {
                    str(row[1]) for row in connection.execute("PRAGMA table_info(threads)")
                }
                if "model" in columns:
                    archived = ' AND COALESCE("archived", 0) = 0' if "archived" in columns else ""
                    order_column = next(
                        (
                            name
                            for name in (
                                "recency_at_ms",
                                "updated_at_ms",
                                "recency_at",
                                "updated_at",
                                "created_at_ms",
                                "created_at",
                            )
                            if name in columns
                        ),
                        None,
                    )
                    order = f' ORDER BY "{order_column}" DESC' if order_column else ""
                    row = connection.execute(
                        f'SELECT "model" FROM threads WHERE "model" IS NOT NULL '
                        f'AND "model" != ?{archived}{order} LIMIT 1',
                        ("",),
                    ).fetchone()
                    if row is not None and valid_chat_model(row[0]):
                        return str(row[0])
            finally:
                connection.close()
        except (FileNotFoundError, OSError, sqlite3.Error):
            pass
        return known_models[0] if known_models else None

    def resolve_chat_target(self, session_id: str) -> Path | None:
        """Resolve one unarchived thread to a safe working directory."""

        connection = self._connect_read_only()
        try:
            columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(threads)")
            }
            if "id" not in columns:
                raise sqlite3.DatabaseError("threads table is missing")
            selected = '"cwd"' if "cwd" in columns else "NULL"
            archived = ' AND COALESCE("archived", 0) = 0' if "archived" in columns else ""
            row = connection.execute(
                f'SELECT {selected} AS cwd FROM threads WHERE "id" = ?{archived} LIMIT 1',
                (session_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None

        raw_cwd = row["cwd"]
        if isinstance(raw_cwd, str) and raw_cwd:
            try:
                cwd = Path(raw_cwd).expanduser().resolve()
                if cwd.is_dir():
                    return cwd
            except OSError:
                pass
        if self.codex_home.is_dir():
            return self.codex_home
        return Path.home().resolve()

    def health_payload(self) -> dict[str, Any]:
        available = False
        warning: str | None = None
        try:
            connection = self._connect_read_only()
            try:
                connection.execute("SELECT 1 FROM threads LIMIT 1").fetchone()
                available = True
            finally:
                connection.close()
        except (FileNotFoundError, OSError, sqlite3.Error) as error:
            warning = self._warning_for(error)

        return {
            "status": "ok" if available else "degraded",
            "service": "codex-pixel-office",
            "database_available": available,
            "warning": warning,
            "generated_at": _utc_iso(self._now()),
        }


class ChatBusyError(RuntimeError):
    def __init__(self, scope: str) -> None:
        super().__init__(scope)
        self.scope = scope


class ChatUnavailableError(RuntimeError):
    pass


def map_codex_chat_event(
    event: Mapping[str, Any], expected_session_id: str | None
) -> dict[str, Any] | None:
    """Map Codex JSONL to a small allowlisted public event contract."""

    event_type = str(event.get("type") or "")
    if event_type == "thread.started":
        thread_id = str(event.get("thread_id") or "")
        if not valid_chat_session_id(thread_id):
            return {
                "type": "error",
                "code": "invalid_session",
                "message": "Codex reported an invalid session",
            }
        if expected_session_id is not None and thread_id != expected_session_id:
            return {
                "type": "error",
                "code": "session_mismatch",
                "message": "Codex resumed a different session",
            }
        return {
            "type": "status",
            "status": "connected",
            "message": "已连接会话",
            "session_id": thread_id,
        }
    if event_type == "turn.started":
        return {"type": "status", "status": "working", "message": "正在处理"}
    if event_type == "turn.completed":
        return {"type": "status", "status": "completed", "message": "处理完成"}
    if event_type in {"turn.failed", "error"}:
        return {
            "type": "error",
            "code": "codex_failed",
            "message": "Codex request failed",
        }
    if event_type not in {"item.started", "item.completed"}:
        return None

    item = event.get("item")
    if not isinstance(item, Mapping):
        return None
    item_type = str(item.get("type") or "")
    if event_type == "item.completed" and item_type == "agent_message":
        text = item.get("text")
        if isinstance(text, str) and text:
            return {"type": "assistant", "message": text}
        return None
    if event_type != "item.started":
        return None
    tool_names = {
        "command_execution": ("command", "正在运行命令"),
        "file_change": ("files", "正在修改文件"),
        "mcp_tool_call": ("mcp", "正在调用 MCP 工具"),
        "web_search": ("search", "正在搜索资料"),
        "plan_update": ("plan", "正在更新计划"),
    }
    tool = tool_names.get(item_type)
    if tool:
        return {
            "type": "status",
            "status": "using_tool",
            "tool": tool[0],
            "message": tool[1],
        }
    return None


class _ChatJob:
    def __init__(
        self,
        reservation_key: str,
        session_id: str | None,
        deadline: float,
    ) -> None:
        self.reservation_key = reservation_key
        self.session_id = session_id
        self.is_new = session_id is None
        self.deadline = deadline
        self.process: subprocess.Popen[bytes] | Any | None = None
        self.events: queue.Queue[tuple[str, bytes | None]] = queue.Queue(maxsize=128)
        self.stop_event = threading.Event()
        self.cancelled = threading.Event()
        self.timed_out = threading.Event()
        self.finished = threading.Event()
        self.threads: list[threading.Thread] = []
        self.watchdog: threading.Thread | None = None
        self.stderr_tail = bytearray()


class CodexChatService:
    """Run one resumed Codex turn with bounded streaming and lifecycle control."""

    def __init__(
        self,
        session_service: SessionService,
        *,
        codex_bin: Path | str = "codex",
        runner: Callable[..., Any] = subprocess.Popen,
        timeout_seconds: float = DEFAULT_CHAT_TIMEOUT_SECONDS,
        heartbeat_seconds: float = DEFAULT_CHAT_HEARTBEAT_SECONDS,
        max_concurrent: int = DEFAULT_CHAT_MAX_CONCURRENT,
        terminate_grace_seconds: float = DEFAULT_CHAT_TERMINATE_GRACE_SECONDS,
        allowed_models: Iterable[str] | None = None,
        default_model: str | None = None,
        catalog_runner: Callable[..., Any] | None = None,
        catalog_popen: Callable[..., Any] = subprocess.Popen,
        catalog_timeout_seconds: float = DEFAULT_MODEL_CATALOG_TIMEOUT_SECONDS,
        tree_runner: Callable[..., Any] = subprocess.run,
        executable_resolver: Callable[[str], str | None] = shutil.which,
        platform_name: str | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session_service = session_service
        self.codex_bin = str(codex_bin)
        self.runner = runner
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.heartbeat_seconds = max(0.05, float(heartbeat_seconds))
        self.max_concurrent = max(1, int(max_concurrent))
        self.terminate_grace_seconds = max(0.0, float(terminate_grace_seconds))
        if allowed_models is None:
            self.allowed_models: frozenset[str] | None = None
        else:
            if isinstance(allowed_models, (str, bytes)):
                raise ValueError("allowed_models must be an iterable of model identifiers")
            model_set = frozenset(allowed_models)
            if not all(valid_chat_model(model) for model in model_set):
                raise ValueError("allowed_models contains an invalid model identifier")
            self.allowed_models = model_set
        if default_model is not None and not valid_chat_model(default_model):
            raise ValueError("default_model is invalid")
        if (
            default_model is not None
            and self.allowed_models is not None
            and default_model not in self.allowed_models
        ):
            raise ValueError("default_model must be included in allowed_models")
        self.default_model = default_model
        self.catalog_runner = catalog_runner
        self.catalog_popen = catalog_popen
        self.catalog_timeout_seconds = max(0.1, float(catalog_timeout_seconds))
        self.tree_runner = tree_runner
        self.executable_resolver = executable_resolver
        self.platform_name = os.name if platform_name is None else platform_name
        self.monotonic = monotonic
        self._condition = threading.Condition()
        self._active: dict[str, _ChatJob] = {}
        self._closed = False

    @property
    def active_count(self) -> int:
        with self._condition:
            return len(self._active)

    def model_is_allowed(self, model: str | None) -> bool:
        return model is None or self.allowed_models is None or model in self.allowed_models

    def _codex_command(self, *arguments: str) -> list[str]:
        return executable_command(
            self.codex_bin,
            arguments,
            platform_name=self.platform_name,
            resolver=self.executable_resolver,
        )

    def _run_catalog_process(self, command: Sequence[str], **kwargs: Any) -> Any | None:
        try:
            process = self.catalog_popen(
                command,
                **kwargs,
                **process_group_options(self.platform_name),
            )
        except (OSError, TypeError, ValueError):
            return None
        try:
            stdout, _stderr = process.communicate(timeout=self.catalog_timeout_seconds)
        except subprocess.TimeoutExpired:
            self._terminate_process(process)
            return None
        except (OSError, ValueError):
            self._terminate_process(process)
            return None
        return subprocess.CompletedProcess(
            command,
            process.returncode,
            stdout=stdout,
            stderr=b"",
        )

    def _bundled_model_catalog(self) -> list[dict[str, str]] | None:
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(self.session_service.codex_home)
        cwd = self.session_service.codex_home
        if not cwd.is_dir():
            cwd = Path.home()
        command = self._codex_command("debug", "models", "--bundled")
        runner_kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.DEVNULL,
            "cwd": str(cwd),
            "env": environment,
            "shell": False,
        }
        try:
            if self.catalog_runner is None:
                result = self._run_catalog_process(command, **runner_kwargs)
            else:
                result = self.catalog_runner(
                    command,
                    **runner_kwargs,
                    timeout=self.catalog_timeout_seconds,
                    check=False,
                )
        except (OSError, subprocess.TimeoutExpired, TypeError, ValueError):
            return None
        if result is None:
            return None
        if getattr(result, "returncode", 1) != 0:
            return None
        raw = getattr(result, "stdout", b"")
        if isinstance(raw, str):
            raw = raw.encode("utf-8", errors="replace")
        if not isinstance(raw, bytes) or len(raw) > MAX_MODEL_CATALOG_BYTES:
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        items = payload.get("models") if isinstance(payload, Mapping) else None
        if not isinstance(items, list):
            return None

        ranked: list[tuple[int, int, str, str]] = []
        seen: set[str] = set()
        for index, item in enumerate(items):
            if not isinstance(item, Mapping) or str(item.get("visibility") or "") != "list":
                continue
            model_id = item.get("slug")
            if not valid_chat_model(model_id) or model_id in seen:
                continue
            label = item.get("display_name")
            if not isinstance(label, str) or not label.strip():
                label = model_id
            try:
                priority = int(item.get("priority"))
            except (TypeError, ValueError):
                priority = 1_000_000
            seen.add(model_id)
            ranked.append((priority, index, model_id, label.strip()[:160]))
        ranked.sort(key=lambda item: (item[0], item[1]))
        return [{"id": item[2], "label": item[3]} for item in ranked[:128]]

    def models_payload(self) -> dict[str, Any]:
        if self.allowed_models is not None:
            model_ids = sorted(self.allowed_models)
            default_model = self.default_model or (model_ids[0] if model_ids else None)
            return {
                "models": [{"id": model, "label": model} for model in model_ids],
                "default_model": default_model,
                "source": "configured_allowlist",
                "authoritative": True,
                "supports_custom": False,
                "warning": None,
            }
        catalog = self._bundled_model_catalog()
        model_records = list(catalog or [])
        seen = {item["id"] for item in model_records}
        try:
            local_model_ids = self.session_service.known_chat_models()
            warning = None
        except (FileNotFoundError, OSError, sqlite3.Error) as error:
            local_model_ids = []
            warning = self.session_service._warning_for(error)
        for model_id in local_model_ids:
            if model_id not in seen:
                model_records.append({"id": model_id, "label": model_id})
                seen.add(model_id)
        default_model = self.default_model or self.session_service.default_chat_model(
            [item["id"] for item in model_records]
        )
        if default_model is not None and default_model not in seen:
            model_records.insert(0, {"id": default_model, "label": default_model})
        return {
            "models": model_records,
            "default_model": default_model,
            "source": "codex_bundled_catalog" if catalog is not None else "local_sessions",
            "authoritative": False,
            "supports_custom": True,
            "warning": warning,
        }

    def _reserve(self, session_id: str | None) -> _ChatJob:
        with self._condition:
            if self._closed:
                raise ChatUnavailableError("chat service is closed")
            if session_id is not None and any(
                active.session_id == session_id for active in self._active.values()
            ):
                raise ChatBusyError("session")
            if len(self._active) >= self.max_concurrent:
                raise ChatBusyError("global")
            reservation_key = session_id or f"new:{uuid.uuid4().hex}"
            job = _ChatJob(
                reservation_key,
                session_id,
                self.monotonic() + self.timeout_seconds,
            )
            self._active[reservation_key] = job
            return job

    def _finish(self, job: _ChatJob) -> None:
        with self._condition:
            if self._active.get(job.reservation_key) is job:
                del self._active[job.reservation_key]
            job.finished.set()
            self._condition.notify_all()

    def _adopt_session_id(self, job: _ChatJob, session_id: str) -> bool:
        with self._condition:
            if job.session_id is not None:
                return job.session_id == session_id
            if any(
                active is not job and active.session_id == session_id
                for active in self._active.values()
            ):
                return False
            job.session_id = session_id
            return True

    @staticmethod
    def _pipe_bytes(value: bytes | str) -> bytes:
        return value if isinstance(value, bytes) else value.encode("utf-8", "replace")

    def _queue_event(self, job: _ChatJob, kind: str, value: bytes | None = None) -> None:
        while not job.stop_event.is_set():
            try:
                job.events.put((kind, value), timeout=0.1)
                return
            except queue.Full:
                continue

    def _read_stdout(self, job: _ChatJob) -> None:
        pipe = job.process.stdout if job.process is not None else None
        try:
            if pipe is None:
                return
            while not job.stop_event.is_set():
                line = pipe.readline(MAX_CHAT_EVENT_LINE_BYTES + 1)
                if not line:
                    break
                raw = self._pipe_bytes(line)
                if len(raw) > MAX_CHAT_EVENT_LINE_BYTES:
                    while raw and not raw.endswith(b"\n") and not job.stop_event.is_set():
                        extra = pipe.readline(MAX_CHAT_EVENT_LINE_BYTES + 1)
                        if not extra:
                            break
                        raw = self._pipe_bytes(extra)
                    self._queue_event(job, "overlong")
                    continue
                self._queue_event(job, "stdout", raw)
        except (OSError, ValueError):
            pass
        finally:
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    pass
            self._queue_event(job, "stdout_done")

    def _read_stderr(self, job: _ChatJob) -> None:
        pipe = job.process.stderr if job.process is not None else None
        try:
            if pipe is None:
                return
            while not job.stop_event.is_set():
                chunk = pipe.read(4096)
                if not chunk:
                    break
                raw = self._pipe_bytes(chunk)
                job.stderr_tail.extend(raw)
                if len(job.stderr_tail) > MAX_CHAT_STDERR_BYTES:
                    del job.stderr_tail[:-MAX_CHAT_STDERR_BYTES]
        except (OSError, ValueError):
            pass
        finally:
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    pass

    def _write_stdin(self, job: _ChatJob, message: str) -> None:
        """Write the prompt off-thread so a full pipe cannot block the request."""

        pipe = job.process.stdin if job.process is not None else None
        failed = False
        try:
            if pipe is None:
                raise OSError("Codex stdin is unavailable")
            value: bytes | str = message.encode("utf-8")
            while value and not job.stop_event.is_set():
                try:
                    written = pipe.write(value)
                except TypeError:
                    if isinstance(value, bytes):
                        value = value.decode("utf-8")
                        continue
                    raise
                if written is None:
                    break
                if not isinstance(written, int) or written <= 0:
                    raise OSError("Codex stdin stopped accepting data")
                value = value[written:]
        except (BrokenPipeError, OSError, ValueError, TypeError):
            failed = True
        finally:
            if pipe is not None:
                try:
                    pipe.close()
                except (BrokenPipeError, OSError, ValueError):
                    failed = True
            if failed and not job.stop_event.is_set():
                self._queue_event(job, "stdin_error")

    def _deadline_watchdog(self, job: _ChatJob) -> None:
        remaining = max(0.0, job.deadline - self.monotonic())
        if job.finished.wait(remaining):
            return
        job.timed_out.set()
        job.stop_event.set()
        if job.process is not None:
            self._terminate_process(job.process)
        self._close_job_pipes(job)
        self._finish(job)

    @staticmethod
    def _close_job_pipes(job: _ChatJob) -> None:
        for thread in job.threads:
            thread.join(timeout=0.5)
        process = job.process
        if process is None:
            return
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is None:
                continue
            try:
                pipe.close()
            except OSError:
                pass

    def _terminate_process(self, process: Any) -> None:
        try:
            if process.poll() is not None:
                return
        except (OSError, ValueError):
            return
        pid = getattr(process, "pid", None)
        if self.platform_name == "nt" and pid:
            system_root = os.environ.get("SystemRoot")
            taskkill = (
                str(Path(system_root) / "System32" / "taskkill.exe")
                if system_root
                else "taskkill.exe"
            )
            try:
                self.tree_runner(
                    [taskkill, "/PID", str(pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=max(1.0, self.terminate_grace_seconds),
                    check=False,
                    creationflags=getattr(
                        subprocess,
                        "CREATE_NO_WINDOW",
                        WINDOWS_CREATE_NO_WINDOW,
                    ),
                )
            except (OSError, subprocess.TimeoutExpired, TypeError, ValueError):
                try:
                    process.terminate()
                except (OSError, ProcessLookupError):
                    pass
        else:
            try:
                if self.platform_name == "posix" and pid:
                    os.killpg(pid, signal.SIGTERM)
                else:
                    process.terminate()
            except (OSError, ProcessLookupError):
                pass
        try:
            process.wait(timeout=self.terminate_grace_seconds)
            return
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass
        try:
            if self.platform_name == "posix" and pid:
                os.killpg(pid, signal.SIGKILL)
            else:
                process.kill()
        except (OSError, ProcessLookupError):
            pass
        try:
            process.wait(timeout=self.terminate_grace_seconds)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass

    def _start_process(
        self,
        job: _ChatJob,
        arguments: list[str],
        message: str,
        cwd: Path,
    ) -> _ChatJob:
        command = self._codex_command(*arguments)
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(self.session_service.codex_home)
        try:
            process = self.runner(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(cwd),
                env=environment,
                shell=False,
                bufsize=0,
                **process_group_options(self.platform_name),
            )
        except (OSError, ValueError) as error:
            self._finish(job)
            raise ChatUnavailableError("could not start Codex") from error

        with self._condition:
            job.process = process
            cancelled = self._closed or job.cancelled.is_set()
        expired = self.monotonic() >= job.deadline
        if cancelled or expired:
            if expired:
                job.timed_out.set()
            self._terminate_process(process)
            self._finish(job)
            message_text = (
                "chat request timed out" if expired else "chat service is closed"
            )
            raise ChatUnavailableError(message_text)

        job.threads = [
            threading.Thread(target=self._read_stdout, args=(job,), daemon=True),
            threading.Thread(target=self._read_stderr, args=(job,), daemon=True),
            threading.Thread(target=self._write_stdin, args=(job, message), daemon=True),
        ]
        for thread in job.threads:
            thread.start()
        job.watchdog = threading.Thread(
            target=self._deadline_watchdog,
            args=(job,),
            daemon=True,
        )
        job.watchdog.start()
        return job

    def start(
        self,
        session_id: str,
        message: str,
        cwd: Path,
        model: str | None = None,
    ) -> _ChatJob:
        job = self._reserve(session_id)
        arguments = [
            "exec",
            "resume",
            "--json",
            "--skip-git-repo-check",
        ]
        if model is not None:
            arguments.extend(["--model", model])
        arguments.extend([session_id, "-"])
        return self._start_process(job, arguments, message, cwd)

    def start_new(
        self,
        message: str,
        cwd: Path,
        model: str | None = None,
    ) -> _ChatJob:
        job = self._reserve(None)
        arguments = ["exec", "--json", "--skip-git-repo-check"]
        if model is not None:
            arguments.extend(["--model", model])
        arguments.append("-")
        return self._start_process(job, arguments, message, cwd)

    def events_for(self, job: _ChatJob) -> Iterable[dict[str, Any]]:
        process = job.process
        if process is None:
            return
        deadline = job.deadline
        stdout_done = False
        failed = False
        reported_error = False
        output_bytes = 0
        raw_output_bytes = 0
        try:
            while not job.cancelled.is_set():
                remaining = deadline - self.monotonic()
                if job.timed_out.is_set() or remaining <= 0:
                    job.timed_out.set()
                    self._terminate_process(process)
                    failed = True
                    reported_error = True
                    yield {
                        "type": "error",
                        "code": "timeout",
                        "message": "Codex request timed out",
                    }
                    break
                if stdout_done and process.poll() is not None:
                    break
                try:
                    kind, raw = job.events.get(
                        timeout=min(self.heartbeat_seconds, remaining)
                    )
                except queue.Empty:
                    if process.poll() is None:
                        yield {"type": "status", "status": "working", "message": "正在处理"}
                    continue
                if kind == "stdout_done":
                    stdout_done = True
                    continue
                if kind == "stdin_error":
                    self._terminate_process(process)
                    failed = True
                    reported_error = True
                    yield {
                        "type": "error",
                        "code": "codex_failed",
                        "message": "Codex request failed",
                    }
                    break
                if kind == "overlong":
                    self._terminate_process(process)
                    failed = True
                    reported_error = True
                    yield {
                        "type": "error",
                        "code": "output_limit",
                        "message": "Codex output exceeded the safety limit",
                    }
                    break
                if kind != "stdout" or raw is None:
                    continue
                raw_output_bytes += len(raw)
                if raw_output_bytes > MAX_CHAT_OUTPUT_BYTES:
                    self._terminate_process(process)
                    failed = True
                    reported_error = True
                    yield {
                        "type": "error",
                        "code": "output_limit",
                        "message": "Codex output exceeded the safety limit",
                    }
                    break
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(parsed, Mapping):
                    continue
                mapped = map_codex_chat_event(parsed, job.session_id)
                if mapped is None:
                    continue
                mapped_session_id = mapped.get("session_id")
                if isinstance(mapped_session_id, str) and not self._adopt_session_id(
                    job, mapped_session_id
                ):
                    mapped = {
                        "type": "error",
                        "code": "session_busy",
                        "message": "Codex session already has a request in progress",
                    }
                mapped_size = len(
                    json.dumps(mapped, ensure_ascii=False, allow_nan=False).encode("utf-8")
                )
                if output_bytes + mapped_size > MAX_CHAT_OUTPUT_BYTES:
                    self._terminate_process(process)
                    failed = True
                    reported_error = True
                    yield {
                        "type": "error",
                        "code": "output_limit",
                        "message": "Codex output exceeded the safety limit",
                    }
                    break
                output_bytes += mapped_size
                if mapped.get("type") == "error":
                    failed = True
                    reported_error = True
                    if mapped.get("code") in {
                        "invalid_session",
                        "session_busy",
                        "session_mismatch",
                    }:
                        self._terminate_process(process)
                yield mapped
                if mapped.get("code") in {
                    "invalid_session",
                    "session_busy",
                    "session_mismatch",
                }:
                    break

            returncode = process.poll()
            if job.is_new and job.session_id is None and not job.cancelled.is_set():
                failed = True
                if not reported_error:
                    reported_error = True
                    yield {
                        "type": "error",
                        "code": "codex_failed",
                        "message": "Codex did not report the new session",
                    }
            if not job.cancelled.is_set() and returncode not in (None, 0):
                failed = True
                if not reported_error:
                    reported_error = True
                    yield {
                        "type": "error",
                        "code": "codex_failed",
                        "message": "Codex request failed",
                    }
            if not job.cancelled.is_set():
                yield {"type": "done", "ok": not failed and returncode == 0}
        finally:
            job.stop_event.set()
            if process.poll() is None:
                self._terminate_process(process)
            self._close_job_pipes(job)
            self._finish(job)

    def cancel(self, job: _ChatJob) -> None:
        job.cancelled.set()
        job.stop_event.set()
        if job.process is not None:
            self._terminate_process(job.process)
        self._close_job_pipes(job)
        self._finish(job)

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            jobs = list(self._active.values())
            for job in jobs:
                job.cancelled.set()
                job.stop_event.set()
        for job in jobs:
            if job.process is not None:
                self._terminate_process(job.process)
            self._close_job_pipes(job)
            self._finish(job)


class PixelOfficeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def _close_chat_service(self) -> None:
        chat_service = getattr(self.RequestHandlerClass, "chat_service", None)
        if chat_service is not None:
            chat_service.close()

    def shutdown(self) -> None:
        self._close_chat_service()
        super().shutdown()

    def server_close(self) -> None:
        self._close_chat_service()
        super().server_close()


class PixelOfficeHandler(BaseHTTPRequestHandler):
    server_version = "CodexPixelOffice/1.0"
    service: SessionService
    chat_service: CodexChatService
    static_root: Path

    def _requires_loopback_host_check(self) -> bool:
        bound_host = str(self.server.server_address[0]).split("%", 1)[0]
        if bound_host.lower() == "localhost":
            return True
        try:
            return ipaddress.ip_address(bound_host).is_loopback
        except ValueError:
            return False

    def _valid_loopback_host_header(self) -> bool:
        values = self.headers.get_all("Host", failobj=[])
        if len(values) != 1:
            return False
        host = values[0].strip().lower()
        match = re.fullmatch(
            r"(?:localhost|127\.0\.0\.1)(?::([0-9]{1,5}))?|\[::1\](?::([0-9]{1,5}))?",
            host,
        )
        if match is None:
            return False
        port = next((item for item in match.groups() if item is not None), None)
        return port is None or int(port) <= 65535

    def _client_is_loopback(self) -> bool:
        host = str(self.client_address[0]).split("%", 1)[0]
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def _send_security_headers(self) -> None:
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )

    def _send_json(self, status: int, value: Mapping[str, Any], *, head: bool = False) -> None:
        body = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self._send_security_headers()
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _set_stream_write_deadline(self, deadline: float) -> None:
        remaining = deadline - self.chat_service.monotonic()
        if remaining <= 0:
            raise TimeoutError("chat response deadline expired")
        self.connection.settimeout(remaining)

    def _send_ndjson_headers(self, deadline: float) -> None:
        self._set_stream_write_deadline(deadline)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self._send_security_headers()
        self.end_headers()
        self.close_connection = True

    def _write_ndjson(self, value: Mapping[str, Any], deadline: float) -> None:
        line = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        self._set_stream_write_deadline(deadline)
        self.wfile.write(line)
        self.wfile.flush()

    def _read_chat_json(self) -> Mapping[str, Any] | None:
        if self.headers.get("Transfer-Encoding") is not None:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "transfer encoding is not supported"})
            return None
        if self.headers.get_content_type() != "application/json":
            self._send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "content type must be application/json"})
            return None
        lengths = self.headers.get_all("Content-Length", failobj=[])
        if not lengths:
            self._send_json(HTTPStatus.LENGTH_REQUIRED, {"error": "content length is required"})
            return None
        if len(lengths) != 1 or re.fullmatch(r"[0-9]+", lengths[0].strip()) is None:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid content length"})
            return None
        length = int(lengths[0])
        if length > MAX_CHAT_BODY_BYTES:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request body is too large"})
            return None
        try:
            body = self.rfile.read(length)
        except OSError:
            return None
        if len(body) != length:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "incomplete request body"})
            return None
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON body"})
            return None
        if not isinstance(value, Mapping):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "JSON body must be an object"})
            return None
        return value

    def _validated_chat_message_model(
        self, value: Mapping[str, Any]
    ) -> tuple[str, str | None] | None:
        message = value.get("message")
        model = value.get("model")
        if not isinstance(message, str):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "message must be a string"})
            return None
        if (
            not 1 <= len(message) <= MAX_CHAT_MESSAGE_CHARS
            or not message.strip()
            or "\x00" in message
        ):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "message must contain 1 to 12000 characters"},
            )
            return None
        if model is not None and not valid_chat_model(model):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": "model must be a safe model identifier of at most 128 characters",
                    "code": "invalid_model",
                },
            )
            return None
        if model is not None and not self.chat_service.model_is_allowed(model):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": "model is not allowed by this server",
                    "code": "model_not_allowed",
                },
            )
            return None
        return message, model

    def _stream_chat_job(self, job: _ChatJob) -> None:
        try:
            self._send_ndjson_headers(job.deadline)
            self._write_ndjson(
                {"type": "status", "status": "started", "message": "已开始处理"},
                job.deadline,
            )
            for event in self.chat_service.events_for(job):
                self._write_ndjson(event, job.deadline)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        except Exception:
            try:
                self._write_ndjson(
                    {
                        "type": "error",
                        "code": "internal_error",
                        "message": "Codex chat stopped unexpectedly",
                    },
                    job.deadline,
                )
                self._write_ndjson({"type": "done", "ok": False}, job.deadline)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
        finally:
            self.chat_service.cancel(job)

    def _handle_chat(self) -> None:
        if not self._client_is_loopback():
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "chat is only available from this computer"})
            return
        value = self._read_chat_json()
        if value is None:
            return
        session_id = value.get("session_id")
        if not isinstance(session_id, str):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "session_id must be a string"})
            return
        if not valid_chat_session_id(session_id):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid session_id"})
            return
        validated = self._validated_chat_message_model(value)
        if validated is None:
            return
        message, model = validated
        try:
            cwd = self.service.resolve_chat_target(session_id)
        except (FileNotFoundError, OSError, sqlite3.Error):
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Codex session database is unavailable"})
            return
        if cwd is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "session not found"})
            return
        try:
            if model is None:
                job = self.chat_service.start(session_id, message, cwd)
            else:
                job = self.chat_service.start(session_id, message, cwd, model)
        except ChatBusyError as error:
            message_text = "this session already has a request in progress" if error.scope == "session" else "too many chat requests are in progress"
            self._send_json(HTTPStatus.CONFLICT, {"error": message_text, "code": f"{error.scope}_busy"})
            return
        except ChatUnavailableError:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Codex chat is unavailable"})
            return

        self._stream_chat_job(job)

    def _handle_new_chat(self) -> None:
        if not self._client_is_loopback():
            self._send_json(
                HTTPStatus.FORBIDDEN,
                {"error": "chat is only available from this computer"},
            )
            return
        value = self._read_chat_json()
        if value is None:
            return
        validated = self._validated_chat_message_model(value)
        if validated is None:
            return
        message, model = validated
        cwd = resolve_new_chat_cwd(value.get("cwd"))
        if cwd is None:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": "cwd must be an existing local directory",
                    "code": "invalid_cwd",
                },
            )
            return
        try:
            job = self.chat_service.start_new(message, cwd, model)
        except ChatBusyError:
            self._send_json(
                HTTPStatus.CONFLICT,
                {
                    "error": "too many chat requests are in progress",
                    "code": "global_busy",
                },
            )
            return
        except ChatUnavailableError:
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "Codex chat is unavailable"},
            )
            return
        self._stream_chat_job(job)

    def _handle_history(self, *, head: bool = False) -> None:
        if not self._client_is_loopback():
            self._send_json(
                HTTPStatus.FORBIDDEN,
                {"error": "session history is only available from this computer"},
                head=head,
            )
            return
        parameters = parse_qs(
            urlsplit(self.path).query,
            keep_blank_values=True,
            strict_parsing=False,
        )
        query_values = parameters.get("q", [""])
        limit_values = parameters.get("limit", [str(DEFAULT_HISTORY_LIMIT)])
        if len(query_values) != 1 or len(limit_values) != 1:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "q and limit may only be provided once"},
                head=head,
            )
            return
        query = query_values[0].strip()
        if len(query) > MAX_HISTORY_QUERY_CHARS or "\x00" in query:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "q must contain at most 200 safe characters"},
                head=head,
            )
            return
        raw_limit = limit_values[0]
        if re.fullmatch(r"[0-9]{1,3}", raw_limit) is None:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "limit must be an integer from 1 to 100"},
                head=head,
            )
            return
        limit = int(raw_limit)
        if not 1 <= limit <= MAX_HISTORY_LIMIT:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "limit must be an integer from 1 to 100"},
                head=head,
            )
            return
        self._send_json(
            HTTPStatus.OK,
            self.service.history_payload(query, limit),
            head=head,
        )

    def _static_candidate(self, request_path: str) -> Path | None:
        try:
            decoded = unquote(request_path, errors="strict")
        except UnicodeDecodeError:
            return None
        if "\x00" in decoded:
            return None
        relative = decoded.lstrip("/")
        if not relative or decoded.endswith("/"):
            relative += "index.html"
        candidate = (self.static_root / relative).resolve()
        try:
            candidate.relative_to(self.static_root)
        except ValueError:
            return None
        if candidate.is_dir():
            candidate = (candidate / "index.html").resolve()
            try:
                candidate.relative_to(self.static_root)
            except ValueError:
                return None
        return candidate if candidate.is_file() else None

    def _send_static(self, request_path: str, *, head: bool = False) -> None:
        candidate = self._static_candidate(request_path)
        if candidate is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"}, head=head)
            return
        try:
            size = candidate.stat().st_size
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._send_security_headers()
            self.end_headers()
            if not head:
                with candidate.open("rb") as handle:
                    shutil.copyfileobj(handle, self.wfile)
        except OSError:
            if not self.wfile.closed:
                self.close_connection = True

    def _handle(self, *, head: bool = False) -> None:
        path = urlsplit(self.path).path
        try:
            if self._requires_loopback_host_check() and not self._valid_loopback_host_header():
                self._send_json(
                    HTTPStatus.FORBIDDEN,
                    {"error": "invalid Host header"},
                    head=head,
                )
            elif path.rstrip("/") == "/api/sessions":
                self._send_json(HTTPStatus.OK, self.service.sessions_payload(), head=head)
            elif path.rstrip("/") == "/api/sessions/history":
                self._handle_history(head=head)
            elif path.rstrip("/") == "/api/health":
                self._send_json(HTTPStatus.OK, self.service.health_payload(), head=head)
            elif path.rstrip("/") == "/api/chat/models":
                if not self._client_is_loopback():
                    self._send_json(
                        HTTPStatus.FORBIDDEN,
                        {"error": "chat models are only available from this computer"},
                        head=head,
                    )
                else:
                    self._send_json(
                        HTTPStatus.OK,
                        self.chat_service.models_payload(),
                        head=head,
                    )
            elif path.startswith("/api/"):
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "unknown API endpoint"}, head=head)
            else:
                self._send_static(path, head=head)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "internal server error"},
                head=head,
            )

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._handle()

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._handle(head=True)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        try:
            if self._requires_loopback_host_check() and not self._valid_loopback_host_header():
                self._send_json(HTTPStatus.FORBIDDEN, {"error": "invalid Host header"})
            elif path.rstrip("/") == "/api/chat":
                self._handle_chat()
            elif path.rstrip("/") == "/api/chat/new":
                self._handle_new_chat()
            elif path.startswith("/api/"):
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "unknown API endpoint"})
            else:
                self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method not allowed"})
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal server error"})


def make_handler(
    service: SessionService,
    static_root: Path | str,
    chat_service: CodexChatService | None = None,
) -> type[PixelOfficeHandler]:
    root = Path(static_root).resolve()

    class ConfiguredHandler(PixelOfficeHandler):
        pass

    ConfiguredHandler.service = service
    ConfiguredHandler.chat_service = chat_service or CodexChatService(service)
    ConfiguredHandler.static_root = root
    return ConfiguredHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex Pixel Office local server")
    parser.add_argument("--host", default=DEFAULT_HOST, help="listen address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="listen port")
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
        "--open-browser",
        action="store_true",
        help="open the dashboard after the server has bound its final port",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 <= args.port <= 65535:
        raise SystemExit("--port must be between 0 and 65535")
    service = SessionService(args.codex_home, args.active_minutes)
    static_root = Path(__file__).resolve().parent / "static"
    chat_service = CodexChatService(service, codex_bin=args.codex_bin)
    server = PixelOfficeHTTPServer(
        (args.host, args.port), make_handler(service, static_root, chat_service)
    )
    bound_host, bound_port = server.server_address[:2]
    display_host = args.host or bound_host
    if display_host in {"0.0.0.0", "::"}:
        display_host = "127.0.0.1"
    if ":" in display_host and not display_host.startswith("["):
        display_host = f"[{display_host}]"
    dashboard_url = f"http://{display_host}:{bound_port}"
    print(f"Codex Pixel Office: {dashboard_url}", flush=True)
    if args.open_browser:
        try:
            opened = webbrowser.open(dashboard_url)
            if opened is False:
                print(
                    f"Could not open a browser automatically. Open {dashboard_url} manually.",
                    file=sys.stderr,
                )
        except (OSError, webbrowser.Error) as error:
            print(f"Could not open a browser: {error}", file=sys.stderr)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping Codex Pixel Office", file=sys.stderr)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

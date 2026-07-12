from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
import threading
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4


MAX_INCLUDED_LOG_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class DiagnosticBundle:
    session_id: str
    path: Path
    created_at: str
    event_count: int
    trace_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "path": str(self.path),
            "file_name": self.path.name,
            "created_at": self.created_at,
            "event_count": self.event_count,
            "trace_count": self.trace_count,
            "size_bytes": self.path.stat().st_size if self.path.exists() else 0,
        }


class SessionDiagnosticStore:
    """Persistent, secret-free diagnostics grouped by user session."""

    def __init__(
        self,
        *,
        root: Path,
        runs_root: Path,
        project_root: Path,
        bot_root: Path,
        service_log_paths: Sequence[Path] = (),
    ) -> None:
        self.root = root.resolve()
        self.sessions_root = self.root / "sessions"
        self.bundles_root = self.root / "bundles"
        self.runs_root = runs_root.resolve()
        self.project_root = project_root.resolve()
        self.bot_root = bot_root.resolve()
        self.service_log_paths = tuple(path.resolve() for path in service_log_paths)
        self._lock = threading.Lock()
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        self.bundles_root.mkdir(parents=True, exist_ok=True)

    def append(self, session_id: str, event_type: str, payload: Mapping[str, Any]) -> Path:
        path = self.event_log_path(session_id)
        body = {
            "event_id": uuid4().hex,
            "ts": utc_now(),
            "session_id": session_id,
            "event_type": event_type,
            "payload": json_safe(dict(payload)),
        }
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(raw)
        return path

    def status(self, session_id: str) -> dict[str, Any]:
        events = self.read_events(session_id)
        bundles = sorted(
            self.bundles_root.glob(f"diagnostics_{session_key(session_id)}_*.zip"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        return {
            "session_id": session_id,
            "event_log_path": str(self.event_log_path(session_id)),
            "event_count": len(events),
            "trace_paths": self._trace_paths(events),
            "latest_bundle": str(bundles[0]) if bundles else "",
        }

    def read_events(self, session_id: str) -> list[dict[str, Any]]:
        path = self.event_log_path(session_id)
        if not path.exists():
            return []
        result: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                result.append(item)
        return result

    def export(
        self,
        session_id: str,
        *,
        conversation: Iterable[Mapping[str, Any]],
        version: str,
        public_config: Mapping[str, Any] | None = None,
    ) -> DiagnosticBundle:
        events = self.read_events(session_id)
        trace_paths = [Path(item) for item in self._trace_paths(events)]
        created_at = utc_now()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self.bundles_root / f"diagnostics_{session_key(session_id)}_{timestamp}.zip"
        temporary = target.with_suffix(".tmp")
        manifest = {
            "schema_version": 1,
            "product": "wiicon-chatbot-v5",
            "version": version,
            "created_at": created_at,
            "session_id": session_id,
            "event_count": len(events),
            "trace_count": len(trace_paths),
            "contains_secrets": False,
        }
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            write_json(archive, "manifest.json", manifest)
            write_json(archive, "session/conversation.json", {"session_id": session_id, "messages": list(conversation)})
            archive.writestr(
                "session/events.jsonl",
                "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in events),
            )
            write_json(
                archive,
                "system/runtime.json",
                {
                    "platform": platform.platform(),
                    "python": sys.version,
                    "executable": sys.executable,
                    "cwd": os.getcwd(),
                    "project_root": str(self.project_root),
                    "bot_root": str(self.bot_root),
                    "runs_root": str(self.runs_root),
                    "public_config": json_safe(dict(public_config or {})),
                },
            )
            self._include_bot_config(archive)
            for trace_path in trace_paths:
                self._include_trace(archive, trace_path)
            for log_path in self.service_log_paths:
                self._include_log_tail(archive, log_path)
        temporary.replace(target)
        return DiagnosticBundle(
            session_id=session_id,
            path=target,
            created_at=created_at,
            event_count=len(events),
            trace_count=len(trace_paths),
        )

    def resolve_bundle(self, file_name: str) -> Path | None:
        candidate = (self.bundles_root / Path(file_name).name).resolve()
        if candidate.parent != self.bundles_root or not candidate.is_file() or candidate.suffix.lower() != ".zip":
            return None
        return candidate

    def event_log_path(self, session_id: str) -> Path:
        return self.sessions_root / session_key(session_id) / "events.jsonl"

    def _trace_paths(self, events: Sequence[Mapping[str, Any]]) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        for event in events:
            payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
            result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
            raw_path = str(payload.get("trace_path") or result.get("trace_path") or "").strip()
            if not raw_path or raw_path in seen:
                continue
            candidate = Path(raw_path).resolve()
            if path_is_within(candidate, self.runs_root) and candidate.is_dir():
                seen.add(raw_path)
                paths.append(str(candidate))
        return paths

    def _include_bot_config(self, archive: zipfile.ZipFile) -> None:
        path = self.bot_root / "bot.yaml"
        if path.is_file():
            archive.write(path, "config/bot.yaml")

    def _include_trace(self, archive: zipfile.ZipFile, trace_path: Path) -> None:
        if not path_is_within(trace_path, self.runs_root) or not trace_path.is_dir():
            return
        for path in sorted(trace_path.rglob("*")):
            if path.is_file():
                relative = path.relative_to(trace_path)
                archive.write(path, str(Path("traces") / trace_path.name / relative))

    def _include_log_tail(self, archive: zipfile.ZipFile, path: Path) -> None:
        if not path.is_file():
            return
        with path.open("rb") as stream:
            size = path.stat().st_size
            if size > MAX_INCLUDED_LOG_BYTES:
                stream.seek(-MAX_INCLUDED_LOG_BYTES, os.SEEK_END)
            raw = stream.read()
        archive.writestr(str(Path("logs") / path.name), raw)


def session_key(session_id: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", session_id.strip()).strip(".-")[:48] or "session"
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:10]
    return f"{normalized}_{digest}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return str(value)


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def write_json(archive: zipfile.ZipFile, name: str, payload: Mapping[str, Any]) -> None:
    archive.writestr(name, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

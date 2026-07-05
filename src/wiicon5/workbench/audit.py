from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from uuid import uuid4

from wiicon5.workbench.models import jsonable


@dataclass(frozen=True)
class WorkbenchAuditEvent:
    event_id: str
    event_type: str
    bot_id: str
    actor: str
    ts: str
    object_type: str = ""
    object_id: str = ""
    before_hash: str = ""
    after_hash: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        bot_id: str,
        actor: str,
        object_type: str = "",
        object_id: str = "",
        before: Any = None,
        after: Any = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> "WorkbenchAuditEvent":
        return cls(
            event_id=uuid4().hex,
            event_type=event_type,
            bot_id=bot_id,
            actor=actor,
            ts=utc_now(),
            object_type=object_type,
            object_id=object_id,
            before_hash=payload_hash(before) if before is not None else "",
            after_hash=payload_hash(after) if after is not None else "",
            payload=compact_payload(payload or {}),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkbenchAuditEvent":
        return cls(
            event_id=str(data.get("event_id") or ""),
            event_type=str(data.get("event_type") or ""),
            bot_id=str(data.get("bot_id") or ""),
            actor=str(data.get("actor") or ""),
            ts=str(data.get("ts") or ""),
            object_type=str(data.get("object_type") or ""),
            object_id=str(data.get("object_id") or ""),
            before_hash=str(data.get("before_hash") or ""),
            after_hash=str(data.get("after_hash") or ""),
            payload=dict(data.get("payload", {})) if isinstance(data.get("payload"), Mapping) else {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "bot_id": self.bot_id,
            "actor": self.actor,
            "ts": self.ts,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "before_hash": self.before_hash,
            "after_hash": self.after_hash,
            "payload": jsonable(self.payload),
        }


class WorkbenchAuditLog:
    def __init__(self, path: Path, *, bot_id: str) -> None:
        self.path = path
        self.bot_id = bot_id

    def append(
        self,
        *,
        event_type: str,
        actor: str,
        object_type: str = "",
        object_id: str = "",
        before: Any = None,
        after: Any = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> WorkbenchAuditEvent:
        event = WorkbenchAuditEvent.create(
            event_type=event_type,
            bot_id=self.bot_id,
            actor=actor,
            object_type=object_type,
            object_id=object_id,
            before=before,
            after=after,
            payload=payload,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return event

    def read(self) -> List[WorkbenchAuditEvent]:
        if not self.path.exists():
            return []
        events: List[WorkbenchAuditEvent] = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, Mapping):
                events.append(WorkbenchAuditEvent.from_dict(payload))
        return events

    def filter_by_object(self, object_id: str) -> List[WorkbenchAuditEvent]:
        return [event for event in self.read() if event.object_id == object_id]


def payload_hash(payload: Any) -> str:
    body = json.dumps(jsonable(payload), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def compact_payload(payload: Mapping[str, Any], *, max_depth: int = 4) -> Dict[str, Any]:
    compacted = _compact(payload, max_depth=max_depth)
    return compacted if isinstance(compacted, dict) else {}


def _compact(value: Any, *, max_depth: int) -> Any:
    if max_depth <= 0:
        return "<truncated>"
    value = jsonable(value)
    if isinstance(value, str):
        return value if len(value) <= 2000 else value[:2000] + "...<truncated>"
    if isinstance(value, list):
        items = [_compact(item, max_depth=max_depth - 1) for item in value[:20]]
        if len(value) > 20:
            items.append(f"...<{len(value) - 20} more>")
        return items
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for index, key in enumerate(sorted(value.keys())):
            if index >= 50:
                result["..."] = f"<{len(value) - 50} more keys>"
                break
            result[str(key)] = _compact(value[key], max_depth=max_depth - 1)
        return result
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from wiicon5.workbench.audit import compact_payload, utc_now
from wiicon5.workbench.store import atomic_write_text


@dataclass(frozen=True)
class WorkbenchTraceRun:
    run_id: str
    path: Path

    def write_json(self, name: str, payload: Any) -> Path:
        file_name = safe_trace_name(name) + ".json"
        path = self.path / file_name
        atomic_write_text(
            path,
            json.dumps(compact_for_trace(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        return path

    def to_dict(self) -> dict[str, str]:
        return {"run_id": self.run_id, "path": str(self.path)}


class WorkbenchTraceWriter:
    def __init__(self, *, bot_instance_root: Path) -> None:
        self.root = bot_instance_root / "runs"

    def start(
        self,
        *,
        action: str,
        actor: str,
        object_type: str = "",
        object_id: str = "",
        request: Mapping[str, Any] | None = None,
    ) -> WorkbenchTraceRun:
        run_id = "workbench_" + safe_trace_name(action) + "_" + uuid4().hex[:12]
        run = WorkbenchTraceRun(run_id=run_id, path=self.root / run_id)
        run.write_json(
            "request",
            {
                "ts": utc_now(),
                "action": action,
                "actor": actor,
                "object_type": object_type,
                "object_id": object_id,
                "request": dict(request or {}),
            },
        )
        return run


def safe_trace_name(value: str) -> str:
    name = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_.-]+", "_", str(value or "").strip())
    name = re.sub(r"_+", "_", name).strip("._-")
    return name or "trace"


def compact_for_trace(payload: Any) -> Any:
    if isinstance(payload, Mapping):
        return compact_payload(payload, max_depth=6)
    return compact_payload({"value": payload}, max_depth=6).get("value")

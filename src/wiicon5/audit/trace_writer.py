from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4


class TraceWriter:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def new_run(self, prefix: str = "run") -> "RunTrace":
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{prefix}_{ts}_{uuid4().hex[:8]}"
        path = self.root / run_id
        path.mkdir(parents=True, exist_ok=False)
        return RunTrace(run_id=run_id, path=path)


class RunTrace:
    def __init__(self, run_id: str, path: Path) -> None:
        self.run_id = run_id
        self.path = path

    def write_json(self, relative_path: str, payload: Dict[str, Any]) -> Path:
        path = self.path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {"run_id": self.run_id, "ts": datetime.now(timezone.utc).isoformat(), **payload}
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def append_jsonl(self, relative_path: str, payload: Dict[str, Any]) -> Path:
        path = self.path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {"run_id": self.run_id, "ts": datetime.now(timezone.utc).isoformat(), **payload}
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(body, ensure_ascii=False) + "\n")
        return path


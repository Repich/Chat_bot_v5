from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from wiicon5.onboarding.pipeline import run_onboarding


STATUS_FILE_NAME = "training_status.json"


@dataclass(frozen=True)
class TrainingStatus:
    state: str
    trained: bool
    running: bool
    message: str
    output_dir: str
    config_dump: str = ""
    mcp_url: str = ""
    started_at: str = ""
    finished_at: str = ""
    files_read: int = 0
    objects_count: int = 0
    query_patterns_count: int = 0
    register_usage_count: int = 0
    binding_candidates_count: int = 0
    error: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "state": self.state,
            "trained": self.trained,
            "running": self.running,
            "message": self.message,
            "output_dir": self.output_dir,
            "config_dump": self.config_dump,
            "mcp_url": self.mcp_url,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "files_read": self.files_read,
            "objects_count": self.objects_count,
            "query_patterns_count": self.query_patterns_count,
            "register_usage_count": self.register_usage_count,
            "binding_candidates_count": self.binding_candidates_count,
            "error": self.error,
        }


class OnboardingManager:
    def __init__(self, *, bot_instance_root: Path, mcp_url: str = "") -> None:
        self.bot_instance_root = bot_instance_root
        self.mcp_url = mcp_url
        self.output_dir = self.bot_instance_root / "onboarding"
        self.status_path = self.output_dir / STATUS_FILE_NAME
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def status(self) -> TrainingStatus:
        with self._lock:
            running = bool(self._thread and self._thread.is_alive())
        stored = self._read_status()
        if running:
            return self._coerce_status(stored, running=True)
        if stored:
            status = self._coerce_status(stored, running=False)
            if status.state == "completed" and not self._required_outputs_exist():
                return TrainingStatus(
                    state="incomplete",
                    trained=False,
                    running=False,
                    message="Файлы первоначального обучения не найдены или повреждены.",
                    output_dir=str(self.output_dir),
                    config_dump=status.config_dump,
                    mcp_url=status.mcp_url,
                    started_at=status.started_at,
                    finished_at=status.finished_at,
                    error="required onboarding outputs are missing",
                )
            return status
        if self._required_outputs_exist():
            return TrainingStatus(
                state="completed",
                trained=True,
                running=False,
                message="Первоначальное обучение выполнено.",
                output_dir=str(self.output_dir),
            )
        return TrainingStatus(
            state="not_started",
            trained=False,
            running=False,
            message="Первоначальное обучение еще не выполнено.",
            output_dir=str(self.output_dir),
        )

    def start(self, *, config_dump: Path, mcp_url: Optional[str] = None, background: bool = True) -> TrainingStatus:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self._coerce_status(self._read_status(), running=True)
            effective_mcp_url = self.mcp_url if mcp_url is None else mcp_url
            if background:
                self._write_status(self._started_payload(config_dump, effective_mcp_url))
                self._thread = threading.Thread(
                    target=self._run_safely,
                    kwargs={"config_dump": config_dump, "mcp_url": effective_mcp_url},
                    daemon=True,
                )
                self._thread.start()
                return self._coerce_status(self._read_status(), running=True)
        self._run_safely(config_dump=config_dump, mcp_url=self.mcp_url if mcp_url is None else mcp_url)
        return self.status()

    def _run_safely(self, *, config_dump: Path, mcp_url: str) -> None:
        try:
            started_payload = self._started_payload(config_dump, mcp_url)
            self._write_status(started_payload)
            result = run_onboarding(config_dump=config_dump, bot_instance=self.bot_instance_root, mcp_url=mcp_url)
            payload = {
                "state": "completed",
                "trained": True,
                "running": False,
                "message": "Первоначальное обучение выполнено.",
                "output_dir": str(result.output_dir),
                "config_dump": str(config_dump),
                "mcp_url": mcp_url,
                "started_at": str(started_payload.get("started_at") or ""),
                "finished_at": utc_now(),
                **result.to_dict(),
            }
            payload["output_dir"] = str(result.output_dir)
            self._write_status(payload)
        except Exception as exc:  # Persist diagnostics for the admin UI.
            payload = self._read_status() or self._started_payload(config_dump, mcp_url)
            payload.update(
                {
                    "state": "failed",
                    "trained": False,
                    "running": False,
                    "message": "Первоначальное обучение завершилось ошибкой.",
                    "finished_at": utc_now(),
                    "error": str(exc),
                    "output_dir": str(self.output_dir),
                }
            )
            self._write_status(payload)

    def _started_payload(self, config_dump: Path, mcp_url: str) -> Dict[str, object]:
        return {
            "state": "running",
            "trained": False,
            "running": True,
            "message": "Первоначальное обучение выполняется.",
            "output_dir": str(self.output_dir),
            "config_dump": str(config_dump),
            "mcp_url": mcp_url,
            "started_at": utc_now(),
            "finished_at": "",
        }

    def _required_outputs_exist(self) -> bool:
        required = [
            self.output_dir / "metadata_index.sqlite",
            self.output_dir / "candidate_bindings.json",
            self.output_dir / "candidate_semantic_roles.json",
            self.output_dir / "candidate_query_patterns.jsonl",
            self.output_dir / "register_usage_map.json",
            self.output_dir / "onboarding_manifest.json",
            self.output_dir / "onboarding_report.md",
        ]
        return all(path.exists() for path in required) and (self.output_dir / "metadata_index.sqlite").stat().st_size > 0

    def _read_status(self) -> Dict[str, object]:
        try:
            data = json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_status(self, payload: Dict[str, object]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.status_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.status_path)

    def _coerce_status(self, payload: Dict[str, object], *, running: bool) -> TrainingStatus:
        state = str(payload.get("state") or ("running" if running else "not_started"))
        trained = bool(payload.get("trained")) and state == "completed"
        if running:
            state = "running"
            trained = False
        return TrainingStatus(
            state=state,
            trained=trained,
            running=running,
            message=str(payload.get("message") or ""),
            output_dir=str(payload.get("output_dir") or self.output_dir),
            config_dump=str(payload.get("config_dump") or ""),
            mcp_url=str(payload.get("mcp_url") or ""),
            started_at=str(payload.get("started_at") or ""),
            finished_at=str(payload.get("finished_at") or ""),
            files_read=int(payload.get("files_read") or 0),
            objects_count=int(payload.get("objects_count") or 0),
            query_patterns_count=int(payload.get("query_patterns_count") or 0),
            register_usage_count=int(payload.get("register_usage_count") or 0),
            binding_candidates_count=int(payload.get("binding_candidates_count") or 0),
            error=str(payload.get("error") or ""),
        )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

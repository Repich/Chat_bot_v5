from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from wiicon5.skills.query_template_learning import LEARNED_QUERY_SCHEMA_VERSION
from wiicon5.skills.semantic_contract import SEMANTIC_CONTRACT_SCHEMA_VERSION


@dataclass(frozen=True)
class LearnedSkillMigrationResult:
    moved: List[Dict[str, str]] = field(default_factory=list)
    kept: List[str] = field(default_factory=list)
    errors: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"moved": list(self.moved), "kept": list(self.kept), "errors": list(self.errors)}


def quarantine_legacy_learned_skills(skills_dir: Path) -> LearnedSkillMigrationResult:
    learned_dir = skills_dir / "learned"
    quarantine_dir = learned_dir / "quarantine" / "pre_semantic_contract_v2"
    moved: List[Dict[str, str]] = []
    kept: List[str] = []
    errors: List[Dict[str, str]] = []
    for state in ("active", "inactive"):
        state_dir = learned_dir / state
        if not state_dir.exists():
            continue
        for path in sorted(state_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                reason = f"invalid_json:{exc}"
                destination = quarantine_path(quarantine_dir / "invalid", path)
                move_file(path, destination)
                moved.append({"source": str(path), "destination": str(destination), "reason": reason})
                continue
            reason = legacy_reason(payload)
            if not reason:
                kept.append(str(path))
                continue
            try:
                destination = quarantine_path(quarantine_dir / state, path)
                move_file(path, destination)
                moved.append({"source": str(path), "destination": str(destination), "reason": reason})
            except OSError as exc:
                errors.append({"source": str(path), "error": str(exc), "reason": reason})
    result = LearnedSkillMigrationResult(moved=moved, kept=kept, errors=errors)
    if moved or errors:
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "ts": datetime.now(timezone.utc).isoformat(),
            **result.to_dict(),
        }
        (quarantine_dir / "migration_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return result


def legacy_reason(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "payload_is_not_object"
    implementation = payload.get("implementation") if isinstance(payload.get("implementation"), dict) else {}
    semantic_contract = payload.get("semantic_contract") if isinstance(payload.get("semantic_contract"), dict) else {}
    if implementation.get("kind") != "semantic_query_template":
        return "legacy_implementation_kind"
    if int(implementation.get("schema_version") or 0) != LEARNED_QUERY_SCHEMA_VERSION:
        return "legacy_query_template_schema"
    if int(semantic_contract.get("schema_version") or 0) != SEMANTIC_CONTRACT_SCHEMA_VERSION:
        return "legacy_semantic_contract_schema"
    if not str(implementation.get("query") or "").strip():
        return "query_template_missing"
    return ""


def quarantine_path(directory: Path, source: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / source.name
    if not destination.exists():
        return destination
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return directory / f"{source.stem}_{stamp}{source.suffix}"


def move_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)

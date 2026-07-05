from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from wiicon5.models import SkillBinding, SkillContract, SkillStatus
from wiicon5.skills.registry import is_skill_contract_payload
from wiicon5.workbench.audit import WorkbenchAuditLog, utc_now
from wiicon5.workbench.models import jsonable
from wiicon5.workbench.store import atomic_write_text, safe_file_stem


SKILL_PACK_FORMAT = "wiicon5.skill_pack.v1"


def export_skill_pack(
    *,
    skill_ids: Iterable[str],
    global_skills_dir: Path,
    bot_instance_root: Path,
    include_bindings: bool = False,
    bindings_dirs: Optional[Iterable[Path]] = None,
    source_bot_id: str = "",
) -> Dict[str, Any]:
    requested = [item.strip() for item in skill_ids if item.strip()]
    skills: List[Dict[str, Any]] = []
    missing: List[str] = []
    source_paths: Dict[str, str] = {}
    for skill_id in requested:
        found = find_skill(skill_id, [bot_instance_root / "skills", global_skills_dir])
        if found is None:
            missing.append(skill_id)
            continue
        skill, path = found
        skills.append(skill.to_dict())
        source_paths[skill.skill_id] = str(path)
    bindings: List[Dict[str, Any]] = []
    if include_bindings:
        for binding in find_bindings(
            {skill["skill_id"] for skill in skills},
            roots=list(bindings_dirs or []) + [bot_instance_root / "skills" / "bindings"],
        ):
            bindings.append(binding.to_dict())
    return {
        "format": SKILL_PACK_FORMAT,
        "created_at": utc_now(),
        "source_bot_id": source_bot_id or bot_instance_root.name or "local",
        "skills": skills,
        "bindings": bindings,
        "source_paths": source_paths,
        "missing_skill_ids": missing,
        "summary": {
            "requested": len(requested),
            "skills": len(skills),
            "bindings": len(bindings),
            "missing": len(missing),
        },
    }


def save_skill_pack(pack: Mapping[str, Any], path: Path) -> None:
    atomic_write_text(path, json.dumps(jsonable(pack), ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def import_skill_pack(
    *,
    pack_path: Path,
    bot_instance_root: Path,
    include_bindings: bool = False,
    overwrite: bool = False,
    actor: str = "admin",
    audit_log: Optional[WorkbenchAuditLog] = None,
) -> Dict[str, Any]:
    pack = read_pack(pack_path)
    if pack.get("format") != SKILL_PACK_FORMAT:
        raise ValueError(f"Unsupported skill pack format: {pack.get('format')}")
    audit = audit_log or WorkbenchAuditLog(
        bot_instance_root / "workbench" / "audit" / "events.jsonl",
        bot_id=bot_instance_root.name or "local",
    )
    imported: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    for item in pack.get("skills", []):
        if not isinstance(item, Mapping):
            continue
        skill = SkillContract.from_dict(item)
        candidate = imported_candidate_skill(skill, pack_path=pack_path, source_pack=pack)
        path = bot_instance_root / "skills" / "candidates" / f"{safe_file_stem(candidate.skill_id)}.json"
        if path.exists() and not overwrite:
            skipped.append({"skill_id": candidate.skill_id, "reason": "already_exists", "path": str(path)})
            continue
        atomic_write_text(path, json.dumps(candidate.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        audit.append(
            event_type="skill_pack.imported_skill",
            actor=actor or "admin",
            object_type="skill",
            object_id=candidate.skill_id,
            after=candidate.to_dict(),
            payload={"pack_path": str(pack_path), "path": str(path)},
        )
        imported.append({"skill_id": candidate.skill_id, "path": str(path), "status": candidate.status.value})
    imported_bindings: List[Dict[str, str]] = []
    if include_bindings:
        for item in pack.get("bindings", []):
            if not isinstance(item, Mapping):
                continue
            binding = SkillBinding.from_dict(item)
            path = (
                bot_instance_root
                / "skills"
                / "bindings"
                / safe_file_stem(binding.config_fingerprint)
                / f"{safe_file_stem(binding.skill_id)}.binding.json"
            )
            if path.exists() and not overwrite:
                skipped.append({"skill_id": binding.skill_id, "reason": "binding_already_exists", "path": str(path)})
                continue
            atomic_write_text(path, json.dumps(binding.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            audit.append(
                event_type="skill_pack.imported_binding",
                actor=actor or "admin",
                object_type="skill_binding",
                object_id=f"{binding.config_fingerprint}:{binding.skill_id}",
                after=binding.to_dict(),
                payload={"pack_path": str(pack_path), "path": str(path)},
            )
            imported_bindings.append(
                {"skill_id": binding.skill_id, "config_fingerprint": binding.config_fingerprint, "path": str(path)}
            )
    return {
        "ok": not skipped,
        "pack_format": pack.get("format"),
        "imported": imported,
        "bindings": imported_bindings,
        "skipped": skipped,
        "summary": {
            "skills_imported": len(imported),
            "bindings_imported": len(imported_bindings),
            "skipped": len(skipped),
        },
    }


def imported_candidate_skill(skill: SkillContract, *, pack_path: Path, source_pack: Mapping[str, Any]) -> SkillContract:
    tags = unique([*skill.tags, "imported_pack"])
    implementation = dict(skill.implementation)
    implementation["imported_pack"] = {
        "path": str(pack_path),
        "source_bot_id": str(source_pack.get("source_bot_id") or ""),
        "imported_at": utc_now(),
        "original_status": skill.status.value,
    }
    return replace(skill, status=SkillStatus.CANDIDATE, tags=tags, implementation=implementation)


def find_skill(skill_id: str, roots: Iterable[Path]) -> Optional[tuple[SkillContract, Path]]:
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            if "evidence" in path.parts:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not is_skill_contract_payload(payload):
                continue
            try:
                skill = SkillContract.from_dict(payload)
            except (KeyError, TypeError, ValueError):
                continue
            if skill.skill_id == skill_id:
                return skill, path
    return None


def find_bindings(skill_ids: set[str], *, roots: Iterable[Path]) -> List[SkillBinding]:
    result: List[SkillBinding] = []
    seen: set[tuple[str, str]] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                binding = SkillBinding.from_dict(payload)
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            key = (binding.skill_id, binding.config_fingerprint)
            if binding.skill_id in skill_ids and key not in seen:
                result.append(binding)
                seen.add(key)
    return result


def read_pack(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Skill pack must be a JSON object.")
    return payload


def unique(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result

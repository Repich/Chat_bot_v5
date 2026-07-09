from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from wiicon5.models import SkillContract, SkillStatus, status_rank
from wiicon5.skills.registry import is_skill_contract_payload


@dataclass(frozen=True)
class SkillCatalogError:
    path: str
    error: str

    def to_dict(self) -> Dict[str, str]:
        return {"path": self.path, "error": self.error}


@dataclass(frozen=True)
class SkillCatalogItem:
    skill: SkillContract
    source_path: Path
    source_kind: str
    bot_specific: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill.skill_id,
            "version": self.skill.version,
            "kind": self.skill.kind.value,
            "status": self.skill.status.value,
            "description": self.skill.description,
            "capabilities": list(self.skill.capabilities),
            "inputs": [item.to_dict() for item in self.skill.inputs],
            "outputs": [item.to_dict() for item in self.skill.outputs],
            "tags": list(self.skill.tags),
            "semantic_role": self.skill.semantic_role or "",
            "supported_filter_roles": list(self.skill.supported_filter_roles),
            "implementation_strategy": self.skill.implementation_strategy,
            "implementation": dict(self.skill.implementation),
            "source_path": str(self.source_path),
            "source_kind": self.source_kind,
            "bot_specific": self.bot_specific,
            "user_editable": self.user_editable,
            "runtime_active_by_default": self.runtime_active_by_default,
        }

    @property
    def runtime_active_by_default(self) -> bool:
        return self.skill.status not in {SkillStatus.DRAFT, SkillStatus.CANDIDATE, SkillStatus.DEPRECATED, SkillStatus.BLOCKED}

    @property
    def user_editable(self) -> bool:
        if self.skill.implementation_strategy == "learned_query":
            return True
        if self.bot_specific:
            return True
        return "learned" in self.source_path.parts


@dataclass(frozen=True)
class SkillCatalogSnapshot:
    items: List[SkillCatalogItem] = field(default_factory=list)
    errors: List[SkillCatalogError] = field(default_factory=list)

    def get(self, skill_id: str) -> Optional[SkillCatalogItem]:
        matches = [item for item in self.items if item.skill.skill_id == skill_id]
        if not matches:
            return None
        return sorted(matches, key=catalog_sort_key)[0]

    def summary(self) -> Dict[str, Any]:
        by_status: Dict[str, int] = {}
        by_kind: Dict[str, int] = {}
        by_source: Dict[str, int] = {}
        active = 0
        for item in self.items:
            by_status[item.skill.status.value] = by_status.get(item.skill.status.value, 0) + 1
            by_kind[item.skill.kind.value] = by_kind.get(item.skill.kind.value, 0) + 1
            by_source[item.source_kind] = by_source.get(item.source_kind, 0) + 1
            if item.runtime_active_by_default:
                active += 1
        return {
            "total": len(self.items),
            "runtime_active_by_default": active,
            "errors": len(self.errors),
            "by_status": by_status,
            "by_kind": by_kind,
            "by_source": by_source,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary(),
            "skills": [item.to_dict() for item in sorted(self.items, key=catalog_sort_key)],
            "errors": [item.to_dict() for item in self.errors],
        }


class SkillCatalogService:
    def __init__(self, *, global_skills_dir: Path, bot_instance_root: Path) -> None:
        self.global_skills_dir = global_skills_dir
        self.bot_instance_root = bot_instance_root

    def snapshot(self) -> SkillCatalogSnapshot:
        items: List[SkillCatalogItem] = []
        errors: List[SkillCatalogError] = []
        for root, bot_specific in [
            (self.global_skills_dir, False),
            (self.bot_instance_root / "skills", True),
        ]:
            scanned = scan_skill_root(root, bot_specific=bot_specific)
            items.extend(scanned.items)
            errors.extend(scanned.errors)
        return SkillCatalogSnapshot(items=items, errors=errors)


def scan_skill_root(root: Path, *, bot_specific: bool) -> SkillCatalogSnapshot:
    items: List[SkillCatalogItem] = []
    errors: List[SkillCatalogError] = []
    if not root.exists():
        return SkillCatalogSnapshot(items=items, errors=errors)
    for path in sorted(root.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            errors.append(SkillCatalogError(path=str(path), error=str(exc)))
            continue
        if not is_skill_contract_payload(data):
            continue
        try:
            skill = SkillContract.from_dict(data)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(SkillCatalogError(path=str(path), error=str(exc)))
            continue
        items.append(
            SkillCatalogItem(
                skill=skill,
                source_path=path,
                source_kind=source_kind(root, path, bot_specific=bot_specific),
                bot_specific=bot_specific,
            )
        )
    return SkillCatalogSnapshot(items=items, errors=errors)


def source_kind(root: Path, path: Path, *, bot_specific: bool) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path
    parts = relative.parts
    prefix = "bot" if bot_specific else "global"
    if "candidates" in parts:
        return f"{prefix}_candidate"
    if "verified" in parts:
        return f"{prefix}_verified"
    if "stable" in parts:
        return f"{prefix}_stable"
    if "deprecated" in parts:
        return f"{prefix}_deprecated"
    if "blocked" in parts:
        return f"{prefix}_blocked"
    if "learned" in parts:
        return f"{prefix}_learned"
    if "atomic" in parts:
        return f"{prefix}_atomic"
    return f"{prefix}_skill"


def catalog_sort_key(item: SkillCatalogItem) -> tuple[int, int, str, str]:
    bot_rank = 0 if item.bot_specific else 1
    status = -status_rank(item.skill.status)
    return (bot_rank, status, item.skill.skill_id, str(item.source_path))

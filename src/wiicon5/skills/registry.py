from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from wiicon5.models import SkillContract, SkillStatus, status_rank


class SkillRegistry:
    def __init__(self, skills: Iterable[SkillContract] = ()) -> None:
        self._skills: Dict[str, SkillContract] = {}
        for skill in skills:
            self.add(skill)

    @classmethod
    def load_from_dir(cls, root: Path) -> "SkillRegistry":
        registry = cls()
        for path in sorted(root.rglob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if not is_skill_contract_payload(data):
                continue
            registry.add(SkillContract.from_dict(data))
        return registry

    @classmethod
    def load_from_dirs(cls, roots: Iterable[Path]) -> "SkillRegistry":
        registry = cls()
        for root in roots:
            for skill in cls.load_from_dir(root).all():
                registry.add(skill)
        return registry

    def add(self, skill: SkillContract) -> None:
        self._skills[skill.skill_id] = skill

    def get(self, skill_id: str) -> Optional[SkillContract]:
        return self._skills.get(skill_id)

    def all(self) -> List[SkillContract]:
        return list(self._skills.values())

    def active(self) -> List[SkillContract]:
        return [
            skill
            for skill in self._skills.values()
            if skill.status in {SkillStatus.VERIFIED, SkillStatus.STABLE}
            and not skill_auto_blocked(skill)
        ]

    def by_output_type(self, artifact_type: str) -> List[SkillContract]:
        candidates = [skill for skill in self.active() if skill.produces(artifact_type)]
        return sorted(candidates, key=lambda skill: (-status_rank(skill.status), skill.skill_id))

    def by_capability(self, capability: str) -> List[SkillContract]:
        candidates = [skill for skill in self.active() if capability in skill.capabilities]
        return sorted(candidates, key=lambda skill: (-status_rank(skill.status), skill.skill_id))


def is_skill_contract_payload(data: object) -> bool:
    return isinstance(data, dict) and isinstance(data.get("skill_id"), str) and isinstance(data.get("kind"), str)


def skill_auto_blocked(skill: SkillContract) -> bool:
    health = skill.implementation.get("runtime_health") if isinstance(skill.implementation, dict) else {}
    return isinstance(health, dict) and bool(health.get("auto_blocked"))

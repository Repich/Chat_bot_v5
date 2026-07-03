from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from wiicon5.models import SkillContract
from wiicon5.skills.registry import SkillRegistry
from wiicon5.types import TypeSystem


@dataclass(frozen=True)
class CompatibilityEdge:
    from_skill_id: str
    from_output: str
    artifact_type: str
    to_skill_id: str
    to_input: str

    def to_tuple(self) -> Tuple[str, str, str, str, str]:
        return (self.from_skill_id, self.from_output, self.artifact_type, self.to_skill_id, self.to_input)


class SkillGraph:
    def __init__(self, registry: SkillRegistry, type_system: Optional[TypeSystem] = None) -> None:
        self.registry = registry
        self.type_system = type_system or TypeSystem()

    def compatibility_edges(self) -> List[CompatibilityEdge]:
        edges: List[CompatibilityEdge] = []
        skills = self.registry.active()
        for source in skills:
            for output in source.outputs:
                for target in skills:
                    if source.skill_id == target.skill_id:
                        continue
                    for input_port in target.inputs:
                        if self.type_system.is_assignable(output.type, input_port.type):
                            edges.append(
                                CompatibilityEdge(
                                    from_skill_id=source.skill_id,
                                    from_output=output.name,
                                    artifact_type=output.type,
                                    to_skill_id=target.skill_id,
                                    to_input=input_port.name,
                                )
                            )
        return edges

    def producers_by_type(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        for skill in self.registry.active():
            for output in skill.outputs:
                result.setdefault(output.type, []).append(skill.skill_id)
        return result

    def compatible_producers_for_input(self, input_type: str) -> List[SkillContract]:
        return [
            skill
            for skill in self.registry.active()
            if any(self.type_system.is_assignable(output.type, input_type) for output in skill.outputs)
        ]

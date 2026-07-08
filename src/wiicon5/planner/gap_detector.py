from __future__ import annotations

from typing import List, Optional

from wiicon5.models import ArtifactRequirement, GapResolution, SkillGap
from wiicon5.planner.domain_compatibility import constraint_selects_skill_domain, skill_domain_compatible
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.semantic_roles import roles_match
from wiicon5.skills.registry import SkillRegistry
from wiicon5.types import TypeSystem


class GapDetector:
    def __init__(self, registry: SkillRegistry, type_system: Optional[TypeSystem] = None) -> None:
        self.registry = registry
        self.type_system = type_system or TypeSystem()

    def detect_for_requirement(
        self,
        requirement: ArtifactRequirement,
        goal: Optional[GoalDecomposition] = None,
    ) -> Optional[SkillGap]:
        if self.type_system.is_abstract_artifact_type(requirement.type):
            return SkillGap(
                required_capability=f"produce_concrete:{requirement.type}",
                required_output=requirement.type,
                reason=(
                    "Goal requires an abstract technical artifact type. "
                    "A data goal must name a concrete business artifact type before planning."
                ),
                nearest_skill_ids=[],
                recommended_resolution=GapResolution.CREATE_NEW,
                missing=["concrete_artifact_type"],
            )

        producers = [
            skill
            for skill in self.registry.active()
            if any(self.type_system.is_assignable(output.type, requirement.type) for output in skill.outputs)
            and not count_skill_misused_for_non_count_aggregate(skill.skill_id, requirement, goal)
        ]
        if not producers:
            return SkillGap(
                required_capability=f"produce:{requirement.type}",
                required_output=requirement.type,
                reason="No active skill can produce the required artifact type.",
                nearest_skill_ids=[],
                recommended_resolution=GapResolution.CREATE_NEW,
                missing=[requirement.type],
            )

        compatible_producers = [skill for skill in producers if skill_domain_compatible(skill, requirement, goal)]
        if not compatible_producers:
            return SkillGap(
                required_capability=f"compatible_domain:{requirement.type}",
                required_output=requirement.type,
                reason=(
                    "Existing skill can produce the artifact type, but its business domain is not compatible "
                    "with the user goal."
                ),
                nearest_skill_ids=[skill.skill_id for skill in producers],
                recommended_resolution=GapResolution.CREATE_NEW,
                missing=[f"domain:{requirement.type}"],
            )

        missing_filter_roles: List[str] = []
        for constraint in requirement.constraints:
            if not any(_skill_accepts_constraint(skill, constraint) for skill in compatible_producers):
                missing_filter_roles.append(constraint.semantic_field)
        if missing_filter_roles:
            return SkillGap(
                required_capability=f"filter:{requirement.type}",
                required_output=requirement.type,
                reason="Existing skill can produce the artifact, but does not support all requested semantic filters.",
                nearest_skill_ids=[skill.skill_id for skill in compatible_producers],
                recommended_resolution=GapResolution.EXTEND_EXISTING,
                missing=[f"filter:{role}" for role in missing_filter_roles],
            )

        return None


def _skill_accepts_constraint(skill, constraint) -> bool:  # type: ignore[no-untyped-def]
    return (
        any(roles_match(constraint.semantic_field, role) for role in skill.supported_filter_roles)
        or any(roles_match(input_port.name, constraint.semantic_field) for input_port in skill.inputs)
        or constraint_selects_skill_domain(skill, constraint)
    )


def count_skill_misused_for_non_count_aggregate(
    skill_id: str,
    requirement: ArtifactRequirement,
    goal: Optional[GoalDecomposition],
) -> bool:
    if skill_id != "count_entities":
        return False
    if requirement.type not in {"AggregateTable", "CountResult"}:
        return False
    text_parts = [requirement.name]
    if goal is not None:
        text_parts.append(goal.business_goal)
    for constraint in requirement.constraints:
        text_parts.extend([constraint.semantic_field, str(constraint.value or ""), constraint.raw_user_text])
    text = " ".join(text_parts).lower()
    return not any(marker in text for marker in ["сколько", "количество", "число", "count"])

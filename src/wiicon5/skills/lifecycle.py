from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from wiicon5.models import GapResolution, SkillGap


@dataclass(frozen=True)
class SkillEvolutionDecision:
    decision: GapResolution
    target_skill_ids: List[str] = field(default_factory=list)
    reason: str = ""
    forbidden_new_skill: bool = False

    def to_dict(self) -> Dict[str, object]:
        return {
            "decision": self.decision.value,
            "target_skill_ids": list(self.target_skill_ids),
            "reason": self.reason,
            "forbidden_new_skill": self.forbidden_new_skill,
        }


class SkillEvolutionPolicy:
    def decide(self, gap: SkillGap) -> SkillEvolutionDecision:
        if gap.recommended_resolution == GapResolution.EXTEND_EXISTING:
            return SkillEvolutionDecision(
                decision=GapResolution.EXTEND_EXISTING,
                target_skill_ids=list(gap.nearest_skill_ids),
                reason="Existing skill produces the required artifact; extend its accepted filters or binding.",
                forbidden_new_skill=True,
            )
        if gap.recommended_resolution == GapResolution.ADD_BINDING:
            return SkillEvolutionDecision(
                decision=GapResolution.ADD_BINDING,
                target_skill_ids=list(gap.nearest_skill_ids),
                reason="Existing skill contract is suitable; add or repair configuration binding.",
                forbidden_new_skill=True,
            )
        return SkillEvolutionDecision(
            decision=gap.recommended_resolution,
            target_skill_ids=list(gap.nearest_skill_ids),
            reason=gap.reason,
            forbidden_new_skill=False,
        )

    def rejects_new_skill_for_gap(self, gap: SkillGap, proposed_skill_id: str) -> bool:
        decision = self.decide(gap)
        if not decision.forbidden_new_skill:
            return False
        return proposed_skill_id not in decision.target_skill_ids


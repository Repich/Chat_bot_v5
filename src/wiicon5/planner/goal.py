from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from wiicon5.models import ArtifactRequirement


@dataclass(frozen=True)
class GoalDecomposition:
    business_goal: str
    final_artifact_type: str
    expected_answer_type: str = "answer"
    required_artifacts: List[ArtifactRequirement] = field(default_factory=list)
    semantic_contract: Dict[str, Any] = field(default_factory=dict)

    def requirement_for_type(self, artifact_type: str) -> ArtifactRequirement:
        for requirement in self.required_artifacts:
            if requirement.type == artifact_type:
                return requirement
        return ArtifactRequirement(name=artifact_type, type=artifact_type)

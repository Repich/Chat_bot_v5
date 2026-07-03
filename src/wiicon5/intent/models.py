from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class IntentType(str, Enum):
    DATA_QUESTION = "data_question"
    GENERAL_QUESTION = "general_question"
    CLARIFICATION = "clarification"
    OUT_OF_SCOPE = "out_of_scope"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ContextDependency:
    role: str
    artifact_type: str
    source: str
    required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "artifact_type": self.artifact_type,
            "source": self.source,
            "required": self.required,
        }


@dataclass(frozen=True)
class IntentResult:
    intent_type: IntentType
    business_goal: str
    requires_1c_data: bool
    expected_output: str = "answer"
    domain_terms: List[str] = field(default_factory=list)
    context_dependencies: List[ContextDependency] = field(default_factory=list)
    relevant: bool = True
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_type": self.intent_type.value,
            "business_goal": self.business_goal,
            "requires_1c_data": self.requires_1c_data,
            "expected_output": self.expected_output,
            "domain_terms": list(self.domain_terms),
            "context_dependencies": [item.to_dict() for item in self.context_dependencies],
            "relevant": self.relevant,
            "reasoning": self.reasoning,
        }


from __future__ import annotations

from typing import Optional

from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.policies.domain_policy import DomainPolicy


class BaselineIntentPolicy:
    def __init__(self, domain_policy: Optional[DomainPolicy] = None) -> None:
        self.domain_policy = domain_policy or DomainPolicy()

    def detect(self, message: str) -> Optional[IntentResult]:
        text = message.lower()
        if any(marker in text for marker in self.domain_policy.config.data_markers):
            return None
        if not any(marker in text for marker in self.domain_policy.config.general_markers):
            return None
        return IntentResult(
            intent_type=IntentType.GENERAL_QUESTION,
            business_goal=message,
            requires_1c_data=False,
            expected_output="short_answer",
            domain_terms=["general"],
            relevant=True,
            reasoning="Handled by bot instance baseline policy before LLM decomposition.",
        )

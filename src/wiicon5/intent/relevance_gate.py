from __future__ import annotations

from typing import Optional

from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.policies.domain_policy import DomainPolicy


class RelevanceGate:
    def __init__(self, domain_policy: Optional[DomainPolicy] = None) -> None:
        self.domain_policy = domain_policy or DomainPolicy()

    def is_relevant(self, intent: IntentResult) -> bool:
        if not intent.relevant:
            return False
        return intent.intent_type not in {IntentType.OUT_OF_SCOPE, IntentType.UNKNOWN}

    def out_of_scope_message(self, intent: IntentResult) -> str:
        return self.domain_policy.out_of_scope_message(intent)

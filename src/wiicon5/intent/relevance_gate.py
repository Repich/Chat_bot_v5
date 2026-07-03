from __future__ import annotations

from wiicon5.intent.models import IntentResult, IntentType


class RelevanceGate:
    def is_relevant(self, intent: IntentResult) -> bool:
        if not intent.relevant:
            return False
        return intent.intent_type not in {IntentType.OUT_OF_SCOPE, IntentType.UNKNOWN}

    def out_of_scope_message(self, intent: IntentResult) -> str:
        text = " ".join([intent.business_goal, *intent.domain_terms]).lower()
        if any(marker in text for marker in ["погода", "температура", "дожд", "снег"]):
            return "Это вне моей зоны: я работаю с WIICON/WIIC и данными 1С. По погоде лучше познакомлю с отличным синоптиком."
        return "Это вне моей зоны: я работаю с WIICON/WIIC, данными 1С и диагностикой связанных запросов."

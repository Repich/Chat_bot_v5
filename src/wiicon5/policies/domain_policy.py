from __future__ import annotations

from typing import Optional

from wiicon5.bot_instance import BotInstanceConfig
from wiicon5.intent.models import IntentResult


class DomainPolicy:
    def __init__(self, config: Optional[BotInstanceConfig] = None) -> None:
        self.config = config or BotInstanceConfig.default()

    def general_answer(self, intent: IntentResult) -> str:
        text = " ".join([intent.business_goal, *intent.domain_terms]).lower()
        if any(marker in text for marker in ["кто ты", "что ты", "представься", "привет", "здравств"]):
            return self.config.intro_answer
        if any(marker in text for marker in ["умеешь", "возможност", "навык", "можешь"]):
            return self.config.capabilities_answer
        return self.config.default_general_answer

    def out_of_scope_message(self, intent: IntentResult) -> str:
        text = " ".join([intent.business_goal, *intent.domain_terms]).lower()
        if any(marker in text for marker in self.config.weather_markers):
            return self.config.out_of_scope_weather_answer
        return self.config.out_of_scope_answer

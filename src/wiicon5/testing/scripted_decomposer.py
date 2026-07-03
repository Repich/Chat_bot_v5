from __future__ import annotations

from typing import Dict

from wiicon5.conversation.context import ConversationContext
from wiicon5.intent.decomposer import DecompositionResult, GoalDecomposer
from wiicon5.intent.models import IntentResult, IntentType


class ScriptedGoalDecomposer(GoalDecomposer):
    def __init__(self, scripts: Dict[str, DecompositionResult]) -> None:
        self.scripts = dict(scripts)
        self.calls = []

    def decompose(self, message: str, context: ConversationContext) -> DecompositionResult:
        self.calls.append({"message": message, "context": context.to_packet()})
        if message not in self.scripts:
            return DecompositionResult(
                intent=IntentResult(
                    intent_type=IntentType.UNKNOWN,
                    business_goal=message,
                    requires_1c_data=False,
                    relevant=False,
                    reasoning="No scripted decomposition is available.",
                )
            )
        return self.scripts[message]


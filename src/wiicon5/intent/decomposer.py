from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from wiicon5.conversation.context import ConversationContext
from wiicon5.intent.models import IntentResult
from wiicon5.planner.goal import GoalDecomposition


@dataclass(frozen=True)
class DecompositionResult:
    intent: IntentResult
    goal: Optional[GoalDecomposition] = None


class GoalDecomposer(ABC):
    @abstractmethod
    def decompose(self, message: str, context: ConversationContext) -> DecompositionResult:
        raise NotImplementedError


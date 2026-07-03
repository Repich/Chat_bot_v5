from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from wiicon5.conversation.context import ConversationContext
from wiicon5.models import SkillContract
from wiicon5.query.query_draft import QueryDraft


class QueryBuilder(ABC):
    @abstractmethod
    def build(self, skill: SkillContract, inputs: Dict[str, Any], context: ConversationContext) -> QueryDraft:
        raise NotImplementedError


class QueryBuildError(Exception):
    pass

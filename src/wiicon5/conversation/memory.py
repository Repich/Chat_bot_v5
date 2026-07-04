from __future__ import annotations

from typing import Dict
from uuid import uuid4

from wiicon5.conversation.context import ConversationContext


class ConversationMemory:
    def __init__(self, default_config_fingerprint: str = "") -> None:
        self._sessions: Dict[str, ConversationContext] = {}
        self.default_config_fingerprint = default_config_fingerprint

    def get_or_create(self, session_id: str = "") -> ConversationContext:
        effective_session_id = session_id or uuid4().hex
        if effective_session_id not in self._sessions:
            self._sessions[effective_session_id] = ConversationContext(
                session_id=effective_session_id,
                config_fingerprint=self.default_config_fingerprint or None,
            )
        elif self.default_config_fingerprint and self._sessions[effective_session_id].config_fingerprint is None:
            self._sessions[effective_session_id].config_fingerprint = self.default_config_fingerprint
        return self._sessions[effective_session_id]

    def save(self, context: ConversationContext) -> None:
        self._sessions[context.session_id] = context

    def list_contexts(self) -> list[ConversationContext]:
        return sorted(
            self._sessions.values(),
            key=lambda context: context.messages[-1].ts if context.messages else "",
            reverse=True,
        )

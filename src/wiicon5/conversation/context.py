from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from wiicon5.execution.artifacts import Artifact


@dataclass(frozen=True)
class ConversationMessage:
    role: str
    content: str
    message_id: str = field(default_factory=lambda: uuid4().hex)
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "role": self.role,
            "content": self.content,
            "ts": self.ts,
        }


@dataclass(frozen=True)
class ResolvedEntity:
    role: str
    artifact_type: str
    value: Any
    source: str
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "artifact_type": self.artifact_type,
            "value": self.value,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass
class ConversationContext:
    session_id: str
    messages: List[ConversationMessage] = field(default_factory=list)
    artifacts: List[Artifact] = field(default_factory=list)
    resolved_entities: List[ResolvedEntity] = field(default_factory=list)
    config_fingerprint: Optional[str] = None
    user_permissions: List[str] = field(default_factory=list)

    def append_message(self, role: str, content: str) -> ConversationMessage:
        message = ConversationMessage(role=role, content=content)
        self.messages.append(message)
        return message

    def add_artifact(self, artifact: Artifact) -> None:
        self.artifacts.append(artifact)

    def add_resolved_entity(self, entity: ResolvedEntity) -> None:
        self.resolved_entities.append(entity)

    def latest_artifact(self, artifact_type: str) -> Optional[Artifact]:
        for artifact in reversed(self.artifacts):
            if artifact.type == artifact_type:
                return artifact
        return None

    def latest_entity(self, role: str) -> Optional[ResolvedEntity]:
        for entity in reversed(self.resolved_entities):
            if entity.role == role:
                return entity
        return None

    def to_packet(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "config_fingerprint": self.config_fingerprint,
            "user_permissions": list(self.user_permissions),
            "messages": [message.to_dict() for message in self.messages],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "resolved_entities": [entity.to_dict() for entity in self.resolved_entities],
        }


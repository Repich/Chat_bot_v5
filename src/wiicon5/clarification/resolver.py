from __future__ import annotations

from typing import Iterable, Optional

from wiicon5.clarification.models import ClarificationResolution
from wiicon5.clarification.policies import ClarificationPolicy, DocumentAmountClarificationPolicy
from wiicon5.conversation.context import ConversationContext
from wiicon5.execution.artifacts import Artifact


class ClarificationResolver:
    def __init__(self, policies: Optional[Iterable[ClarificationPolicy]] = None) -> None:
        self.policies = list(policies) if policies is not None else [DocumentAmountClarificationPolicy()]

    def resolve(self, message: str, context: ConversationContext) -> Optional[ClarificationResolution]:
        clarification = latest_pending_clarification(context)
        if clarification is None:
            return None
        for policy in self.policies:
            artifact = policy.resolve(message, clarification)
            if artifact is not None:
                return ClarificationResolution(
                    artifact=artifact,
                    reasoning="Resolved from the latest pending ClarificationRequest without another 1C query.",
                    trace={
                        "clarification_artifact": clarification.to_dict(),
                        "resolution_artifact": artifact.to_dict(),
                        "policy": policy.__class__.__name__,
                    },
                )
        return None


def latest_pending_clarification(context: ConversationContext) -> Optional[Artifact]:
    for artifact in reversed(context.artifacts):
        if artifact.type == "ClarificationRequest":
            return artifact
        if artifact.type in {"QueryResult", "UserAnswer"}:
            return None
    return None

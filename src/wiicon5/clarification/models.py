from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from wiicon5.execution.artifacts import Artifact


@dataclass(frozen=True)
class ClarificationResolution:
    """Resolved follow-up answer to a pending clarification request."""

    artifact: Artifact
    reasoning: str
    trace: Dict[str, Any] = field(default_factory=dict)

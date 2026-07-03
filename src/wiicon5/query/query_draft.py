from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class QueryDraft:
    query: str
    limit: int = 100
    include_schema: bool = True
    params: Dict[str, Any] = field(default_factory=dict)
    metadata_dependencies: List[str] = field(default_factory=list)
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "params": dict(self.params),
            "limit": self.limit,
            "include_schema": self.include_schema,
            "metadata_dependencies": list(self.metadata_dependencies),
            "reasoning": self.reasoning,
        }

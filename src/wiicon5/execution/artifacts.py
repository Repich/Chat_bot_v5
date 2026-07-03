from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class Artifact:
    name: str
    type: str
    value: Any
    provenance: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "value": self.value,
            "provenance": list(self.provenance),
        }


@dataclass(frozen=True)
class TypedTable:
    columns: List[str]
    rows: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {"columns": list(self.columns), "rows": list(self.rows)}


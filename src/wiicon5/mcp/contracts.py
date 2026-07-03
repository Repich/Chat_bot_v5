from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class McpQueryRequest:
    query: str
    params: Dict[str, Any] = field(default_factory=dict)
    limit: int = 100
    include_schema: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {"query": self.query, "params": dict(self.params), "limit": self.limit, "include_schema": self.include_schema}


@dataclass(frozen=True)
class McpQueryResponse:
    success: bool
    data: Any = None
    error: str = ""
    schema: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "McpQueryResponse":
        data = payload.get("data")
        if data is None and "result" in payload:
            data = payload.get("result")
        return cls(
            success=bool(payload.get("success")),
            data=data,
            error=str(payload.get("error") or ""),
            schema=payload.get("schema") if isinstance(payload.get("schema"), dict) else {},
            raw=dict(payload),
        )


@dataclass(frozen=True)
class McpMetadataRequest:
    filter: str = ""
    name_mask: str = ""
    attribute_mask: str = ""
    meta_type: str = ""
    limit: int = 50
    offset: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filter": self.filter,
            "name_mask": self.name_mask,
            "attribute_mask": self.attribute_mask,
            "meta_type": self.meta_type,
            "limit": self.limit,
            "offset": self.offset,
        }


@dataclass(frozen=True)
class McpMetadataResponse:
    success: bool
    data: Any = None
    error: str = ""
    returned: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "McpMetadataResponse":
        data = payload.get("data")
        returned = payload.get("returned")
        if returned is None and isinstance(data, list):
            returned = len(data)
        return cls(
            success=bool(payload.get("success")),
            data=data,
            error=str(payload.get("error") or ""),
            returned=int(returned or 0),
            raw=dict(payload),
        )


def normalize_mcp_rows(response: McpQueryResponse) -> List[Dict[str, Any]]:
    data = response.data
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("rows", "items", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []

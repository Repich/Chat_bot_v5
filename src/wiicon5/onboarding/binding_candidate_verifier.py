from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from wiicon5.knowledge.metadata import MetadataObject, metadata_object_from_payload
from wiicon5.mcp.client import McpClient
from wiicon5.mcp.contracts import McpMetadataRequest


@dataclass(frozen=True)
class BindingCandidateVerification:
    candidate: Dict[str, Any]
    status: str
    errors: List[str] = field(default_factory=list)
    metadata_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate": dict(self.candidate),
            "status": self.status,
            "errors": list(self.errors),
            "metadata_summary": dict(self.metadata_summary),
        }


def verify_binding_candidates(candidates: List[Dict[str, Any]], mcp_client: McpClient) -> List[BindingCandidateVerification]:
    metadata_cache: Dict[str, tuple[Optional[MetadataObject], List[str]]] = {}
    return [verify_binding_candidate(candidate, mcp_client, metadata_cache=metadata_cache) for candidate in candidates]


def verify_binding_candidate(
    candidate: Dict[str, Any],
    mcp_client: McpClient,
    *,
    metadata_cache: Optional[Dict[str, tuple[Optional[MetadataObject], List[str]]]] = None,
) -> BindingCandidateVerification:
    object_name = str(candidate.get("object") or candidate.get("metadata_object") or "")
    if not object_name:
        return BindingCandidateVerification(candidate=candidate, status="rejected", errors=["candidate has no object"])
    metadata, metadata_errors = cached_metadata(object_name, mcp_client, metadata_cache)
    if metadata_errors:
        return BindingCandidateVerification(candidate=candidate, status="rejected", errors=metadata_errors)
    if metadata is None:
        return BindingCandidateVerification(
            candidate=candidate,
            status="rejected",
            errors=[f"object {object_name} was not returned by MCP metadata"],
        )
    errors = missing_required_fields(candidate, metadata)
    status = "verified_by_mcp" if not errors else "rejected"
    return BindingCandidateVerification(
        candidate=candidate,
        status=status,
        errors=errors,
        metadata_summary={
            "full_name": metadata.full_name,
            "synonym": metadata.synonym,
            "fields": list(metadata.fields)[:80],
        },
    )


def cached_metadata(
    object_name: str,
    mcp_client: McpClient,
    metadata_cache: Optional[Dict[str, tuple[Optional[MetadataObject], List[str]]]],
) -> tuple[Optional[MetadataObject], List[str]]:
    if metadata_cache is not None and object_name in metadata_cache:
        return metadata_cache[object_name]
    response = mcp_client.get_metadata(McpMetadataRequest(filter=object_name, limit=1))
    if not response.success:
        result = (None, [response.error or "MCP metadata request failed"])
    else:
        result = (metadata_from_response(response.data, object_name), [])
    if metadata_cache is not None:
        metadata_cache[object_name] = result
    return result


def metadata_from_response(data: Any, object_name: str) -> MetadataObject | None:
    payload: Dict[str, Any] | None = None
    if isinstance(data, dict):
        payload = data
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            full_name = str(item.get("ПолноеИмя") or item.get("full_name") or "")
            if full_name == object_name:
                payload = item
                break
        if payload is None and data and isinstance(data[0], dict):
            payload = data[0]
    if payload is None:
        return None
    metadata = metadata_object_from_payload(payload)
    if metadata.full_name and metadata.full_name != object_name:
        return None
    return metadata


def missing_required_fields(candidate: Dict[str, Any], metadata: MetadataObject) -> List[str]:
    required = candidate.get("fields") or candidate.get("required_fields") or []
    if not isinstance(required, list):
        return []
    available = set(metadata.fields)
    return [f"field {field_name} was not returned by MCP metadata" for field_name in required if str(field_name) not in available]

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping


MASKING_ERROR_CODE = "router_v4_guardrails_mask_failed"


def is_guardrail_masking_error(value: Any) -> bool:
    return MASKING_ERROR_CODE in str(value)


def compact_conversation_packet(
    value: Any,
    *,
    current_message: str = "",
    max_messages: int = 4,
    max_message_chars: int = 800,
) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"available": False}
    raw_messages = [item for item in value.get("messages", []) if isinstance(item, Mapping)]
    if (
        raw_messages
        and current_message
        and str(raw_messages[-1].get("role") or "") == "user"
        and str(raw_messages[-1].get("content") or "").strip() == current_message.strip()
    ):
        raw_messages = raw_messages[:-1]
    messages = [
        {
            "role": str(item.get("role") or ""),
            "content": truncate_text(str(item.get("content") or ""), max_message_chars),
        }
        for item in raw_messages[-max_messages:]
    ]
    artifacts = [
        {
            "name": str(item.get("name") or ""),
            "type": str(item.get("type") or ""),
        }
        for item in _mapping_items(value.get("artifacts"), limit=8)
    ]
    resolved_entities = [
        {
            "role": str(item.get("role") or ""),
            "artifact_type": str(item.get("artifact_type") or ""),
            "source": str(item.get("source") or ""),
            "value_omitted": True,
        }
        for item in _mapping_items(value.get("resolved_entities"), limit=8)
    ]
    return {
        "messages": messages,
        "artifacts": artifacts,
        "resolved_entities": resolved_entities,
        "values_omitted": True,
        "context_note": (
            "Gateway masking recovery: bulky history and runtime values are omitted. "
            "Use the current message and dependency types; request clarification if an omitted value is required."
        ),
    }


def compact_skill_catalog(value: Any, *, limit: int = 80) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for item in _mapping_items(value, limit=limit):
        result.append(
            {
                "skill_id": str(item.get("skill_id") or ""),
                "kind": str(item.get("kind") or ""),
                "description": truncate_text(str(item.get("description") or ""), 240),
                "inputs": compact_ports(item.get("inputs")),
                "outputs": compact_ports(item.get("outputs")),
                "semantic_role": str(item.get("semantic_role") or ""),
                "supported_filter_roles": string_list(item.get("supported_filter_roles"), limit=12),
                "output_columns": string_list(item.get("output_columns"), limit=16),
                "semantic_contract": compact_semantic_contract(item.get("semantic_contract")),
            }
        )
    return result


def compact_semantic_contract(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    allowed = (
        "schema_version",
        "operation",
        "subject_role",
        "subject_qualifiers",
        "measure_roles",
        "grouping_roles",
        "ranking",
        "result_kind",
        "result_columns",
        "supported_filter_roles",
        "fixed_filters",
    )
    return {key: value[key] for key in allowed if key in value}


def compact_ports(value: Any) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for item in _mapping_items(value, limit=16):
        port = {
            "name": str(item.get("name") or ""),
            "type": str(item.get("type") or ""),
            "required": bool(item.get("required", True)),
        }
        if item.get("semantic_field"):
            port["semantic_field"] = str(item["semantic_field"])
        result.append(port)
    return result


def string_list(value: Any, *, limit: int) -> List[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        return []
    return [str(item) for item in list(value)[:limit] if str(item).strip()]


def truncate_text(value: str, max_chars: int) -> str:
    normalized = value.strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max(0, max_chars - 3)].rstrip() + "..."


def _mapping_items(value: Any, *, limit: int) -> List[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value[:limit] if isinstance(item, Mapping)]

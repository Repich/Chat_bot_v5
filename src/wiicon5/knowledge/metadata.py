from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List

from wiicon5.mcp.client import McpClient
from wiicon5.mcp.contracts import McpMetadataRequest

TRUST_VERIFIED = "verified"
TRUST_HINT = "hint"
FIELD_HINT_CATEGORIES = {"indexed"}
FIELD_HINT_SOURCES = {"onboarding_index", "source_path", "bsl_regex", "bsl_query", "heuristic"}
FIELD_VERIFIED_SOURCES = {"mcp", "metadata_xml"}
OBJECT_HINT_SOURCES = {"onboarding_index", "source_path", "heuristic"}
OBJECT_VERIFIED_SOURCES = {"mcp", "metadata_xml"}


@dataclass(frozen=True)
class MetadataObject:
    full_name: str
    synonym: str = ""
    fields: List[str] = field(default_factory=list)
    field_details: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)


def metadata_object_source(metadata: MetadataObject) -> str:
    raw_source = metadata.raw.get("_source") or metadata.raw.get("evidence_source") or metadata.raw.get("source") or ""
    return str(raw_source)


def metadata_object_trust(metadata: MetadataObject) -> str:
    raw_trust = metadata.raw.get("_trust") or metadata.raw.get("trust") or ""
    return str(raw_trust)


def is_metadata_object_verified(metadata: MetadataObject) -> bool:
    trust = metadata_object_trust(metadata)
    source = metadata_object_source(metadata)
    if trust == TRUST_VERIFIED or source in OBJECT_VERIFIED_SOURCES:
        return True
    if trust == TRUST_HINT or source in OBJECT_HINT_SOURCES:
        return False
    return bool(metadata.raw)


def field_source(details: Dict[str, Any]) -> str:
    return str(details.get("_source") or details.get("source") or "")


def field_trust(details: Dict[str, Any]) -> str:
    return str(details.get("_trust") or details.get("trust") or "")


def is_field_confirmed(details: Dict[str, Any]) -> bool:
    trust = field_trust(details)
    source = field_source(details)
    category = str(details.get("_category") or "")
    if trust == TRUST_VERIFIED or source in FIELD_VERIFIED_SOURCES:
        return True
    if trust == TRUST_HINT or category in FIELD_HINT_CATEGORIES or source in FIELD_HINT_SOURCES:
        return False
    return True


def confirmed_field_names(metadata: MetadataObject) -> List[str]:
    return [name for name in metadata.fields if is_field_confirmed(metadata.field_details.get(name, {}))]


def confirmed_field_details(metadata: MetadataObject) -> Dict[str, Dict[str, Any]]:
    return {name: details for name, details in metadata.field_details.items() if is_field_confirmed(details)}


class MetadataProvider(ABC):
    @abstractmethod
    def search_objects(self, term: str) -> List[MetadataObject]:
        raise NotImplementedError

    @abstractmethod
    def get_object(self, full_name: str) -> MetadataObject:
        raise NotImplementedError


class McpMetadataProvider(MetadataProvider):
    def __init__(self, mcp_client: McpClient, search_limit: int = 20) -> None:
        self.mcp_client = mcp_client
        self.search_limit = search_limit
        self.last_requests: List[Dict[str, Any]] = []

    def search_objects(self, term: str) -> List[MetadataObject]:
        response = self.mcp_client.get_metadata(McpMetadataRequest(name_mask=term, limit=self.search_limit))
        self.last_requests.append(
            {
                "operation": "search_objects",
                "term": term,
                "success": response.success,
                "error": response.error,
                "returned": response.returned,
            }
        )
        if not response.success:
            return []
        items = response.data if isinstance(response.data, list) else [response.data]
        return [metadata_object_from_payload(item) for item in items if isinstance(item, dict)]

    def get_object(self, full_name: str) -> MetadataObject:
        response = self.mcp_client.get_metadata(McpMetadataRequest(filter=full_name, limit=1))
        self.last_requests.append(
            {
                "operation": "get_object",
                "full_name": full_name,
                "success": response.success,
                "error": response.error,
                "returned": response.returned,
            }
        )
        if not response.success or not isinstance(response.data, dict):
            return MetadataObject(full_name=full_name)
        return metadata_object_from_payload(response.data)


def metadata_object_from_payload(payload: Dict[str, Any]) -> MetadataObject:
    full_name = str(payload.get("ПолноеИмя") or payload.get("full_name") or payload.get("Имя") or "")
    fields = []
    field_details: Dict[str, Dict[str, Any]] = {}
    categories = {
        "Реквизиты": "attribute",
        "Измерения": "dimension",
        "Ресурсы": "resource",
        "СтандартныеРеквизиты": "standard_attribute",
        "ТабличныеЧасти": "table_part",
        "fields": "field",
        "attributes": "attribute",
        "dimensions": "dimension",
        "resources": "resource",
        "standard_attributes": "standard_attribute",
    }
    for key, category in categories.items():
        raw_fields = payload.get(key)
        if isinstance(raw_fields, list):
            for item in raw_fields:
                if isinstance(item, dict) and item.get("Имя"):
                    add_field(fields, field_details, str(item["Имя"]), enrich_field_payload(item, category), category)
                elif isinstance(item, dict) and item.get("name"):
                    add_field(fields, field_details, str(item["name"]), enrich_field_payload(item, category), category)
                elif isinstance(item, str):
                    add_field(fields, field_details, item, {"Имя": item}, category)
    for default_field in ("Ссылка", "Наименование", "Код"):
        add_field(fields, field_details, default_field, {"Имя": default_field}, "standard_attribute")
    return MetadataObject(
        full_name=full_name,
        synonym=str(payload.get("Синоним") or payload.get("synonym") or ""),
        fields=fields,
        field_details=field_details,
        raw={"_source": "mcp", "_trust": TRUST_VERIFIED, **dict(payload)},
    )


def add_unique(items: List[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def add_field(items: List[str], details: Dict[str, Dict[str, Any]], name: str, payload: Dict[str, Any], category: str) -> None:
    add_unique(items, name)
    if name in details:
        return
    enriched = dict(payload)
    enriched["_category"] = category
    enriched.setdefault("_source", "mcp")
    enriched.setdefault("_trust", TRUST_VERIFIED)
    details[name] = enriched


def enrich_field_payload(payload: Dict[str, Any], category: str) -> Dict[str, Any]:
    if category != "table_part":
        return dict(payload)
    enriched = dict(payload)
    nested_fields: List[str] = []
    nested_details: Dict[str, Dict[str, Any]] = {}
    nested_categories = {
        "Реквизиты": "attribute",
        "СтандартныеРеквизиты": "standard_attribute",
        "fields": "field",
        "attributes": "attribute",
        "standard_attributes": "standard_attribute",
    }
    for key, nested_category in nested_categories.items():
        raw_fields = payload.get(key)
        if not isinstance(raw_fields, list):
            continue
        for item in raw_fields:
            if isinstance(item, dict) and item.get("Имя"):
                add_field(nested_fields, nested_details, str(item["Имя"]), item, nested_category)
            elif isinstance(item, dict) and item.get("name"):
                add_field(nested_fields, nested_details, str(item["name"]), item, nested_category)
            elif isinstance(item, str):
                add_field(nested_fields, nested_details, item, {"Имя": item}, nested_category)
    if nested_fields:
        enriched["_nested_fields"] = nested_fields
        enriched["_nested_field_details"] = nested_details
    return enriched

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from wiicon5.knowledge.metadata import (
    MetadataObject,
    MetadataProvider,
    field_source,
    field_trust,
    is_field_confirmed,
    is_metadata_object_verified,
    metadata_object_source,
    metadata_object_trust,
)
from wiicon5.knowledge.onboarding_index import OnboardingMetadataIndex


@dataclass(frozen=True)
class MetadataFieldView:
    name: str
    category: str = ""
    type_text: str = ""
    synonym: str = ""
    source: str = ""
    trust: str = ""
    confirmed: bool = False
    nested_fields: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "type": self.type_text,
            "synonym": self.synonym,
            "source": self.source,
            "trust": self.trust,
            "confirmed": self.confirmed,
            "nested_fields": list(self.nested_fields),
        }


@dataclass(frozen=True)
class MetadataObjectView:
    full_name: str
    synonym: str = ""
    kind: str = ""
    source: str = ""
    trust: str = ""
    confidence: float = 0.0
    confirmed: bool = False
    source_files: List[str] = field(default_factory=list)
    fields: List[MetadataFieldView] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "full_name": self.full_name,
            "synonym": self.synonym,
            "kind": self.kind,
            "source": self.source,
            "trust": self.trust,
            "confidence": self.confidence,
            "confirmed": self.confirmed,
            "source_files": list(self.source_files),
            "fields": [item.to_dict() for item in self.fields],
        }


class MetadataExplorerService:
    def __init__(self, *, provider: Optional[MetadataProvider] = None, index: Optional[OnboardingMetadataIndex] = None) -> None:
        self.provider = provider
        self.index = index

    @classmethod
    def from_bot_instance(cls, bot_instance_root: Path) -> "MetadataExplorerService":
        return cls(index=OnboardingMetadataIndex(bot_instance_root / "onboarding" / "metadata_index.sqlite"))

    def available(self) -> bool:
        if self.provider is not None:
            return True
        return bool(self.index and self.index.available())

    def search(self, term: str, *, limit: int = 20) -> Dict[str, Any]:
        normalized = term.strip()
        if not normalized:
            return {"available": self.available(), "term": normalized, "objects": [], "requests": []}
        objects = self._search_objects(normalized)
        capped = objects[: max(1, min(limit, 50))]
        return {
            "available": self.available(),
            "term": normalized,
            "objects": [object_view(item).to_dict() for item in capped],
            "requests": list(getattr(self.provider, "last_requests", [])) if self.provider is not None else [],
        }

    def get_object(self, full_name: str) -> Dict[str, Any]:
        normalized = full_name.strip()
        if not normalized:
            return {"available": self.available(), "found": False, "object": None, "requests": []}
        metadata = self._get_object(normalized)
        found = bool(metadata.raw or metadata.fields or metadata.synonym)
        return {
            "available": self.available(),
            "found": found,
            "object": object_view(metadata).to_dict() if found else None,
            "requests": list(getattr(self.provider, "last_requests", [])) if self.provider is not None else [],
        }

    def _search_objects(self, term: str) -> List[MetadataObject]:
        if self.provider is not None:
            return self.provider.search_objects(term)
        if self.index is not None:
            return self.index.search_objects(term)
        return []

    def _get_object(self, full_name: str) -> MetadataObject:
        if self.provider is not None:
            return self.provider.get_object(full_name)
        if self.index is not None:
            return self.index.get_object(full_name)
        return MetadataObject(full_name=full_name)


def object_view(metadata: MetadataObject) -> MetadataObjectView:
    raw = metadata.raw
    field_items = [field_view(name, metadata.field_details.get(name, {})) for name in metadata.fields]
    return MetadataObjectView(
        full_name=metadata.full_name,
        synonym=metadata.synonym,
        kind=str(raw.get("kind") or object_kind(metadata.full_name)),
        source=metadata_object_source(metadata),
        trust=metadata_object_trust(metadata),
        confidence=float(raw.get("_confidence") or raw.get("confidence") or 0.0),
        confirmed=is_metadata_object_verified(metadata),
        source_files=[str(item) for item in raw.get("source_files", [])] if isinstance(raw.get("source_files"), list) else [],
        fields=field_items,
    )


def field_view(name: str, details: Dict[str, Any]) -> MetadataFieldView:
    nested = details.get("_nested_fields")
    return MetadataFieldView(
        name=name,
        category=str(details.get("_category") or details.get("category") or ""),
        type_text=str(details.get("Тип") or details.get("type") or details.get("type_text") or ""),
        synonym=str(details.get("Синоним") or details.get("synonym") or ""),
        source=field_source(details),
        trust=field_trust(details),
        confirmed=is_field_confirmed(details),
        nested_fields=[str(item) for item in nested] if isinstance(nested, list) else [],
    )


def object_kind(full_name: str) -> str:
    if "." not in full_name:
        return ""
    return full_name.split(".", 1)[0]

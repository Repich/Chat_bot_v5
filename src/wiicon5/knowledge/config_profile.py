from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from wiicon5.knowledge.metadata import MetadataObject, MetadataProvider


DEFAULT_PROFILE_SEARCH_TERMS = ["Справочник", "Документ", "РегистрНакопления", "РегистрСведений"]


@dataclass(frozen=True)
class ConfigurationProfile:
    fingerprint: str
    base_configuration: str = "unknown"
    objects_count: int = 0
    generated_at: str = ""
    mcp_server_version: str = ""
    source_dump_hash: str = ""
    metadata_hash: str = ""
    sampled_objects: List[str] = field(default_factory=list)
    source: str = "metadata_provider"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "base_configuration": self.base_configuration,
            "objects_count": self.objects_count,
            "generated_at": self.generated_at,
            "mcp_server_version": self.mcp_server_version,
            "source_dump_hash": self.source_dump_hash,
            "metadata_hash": self.metadata_hash,
            "sampled_objects": list(self.sampled_objects),
            "source": self.source,
        }


def build_configuration_profile(
    metadata_provider: MetadataProvider,
    *,
    search_terms: Optional[Iterable[str]] = None,
    limit_objects: int = 200,
    source: str = "metadata_provider",
) -> ConfigurationProfile:
    objects = collect_profile_metadata_objects(metadata_provider, search_terms or DEFAULT_PROFILE_SEARCH_TERMS, limit_objects)
    signatures = [metadata_signature(item) for item in objects]
    if not signatures:
        return ConfigurationProfile(
            fingerprint="unresolved",
            objects_count=0,
            generated_at=datetime.now(timezone.utc).isoformat(),
            metadata_hash="",
            source=source,
        )
    metadata_hash = hash_payload(signatures)
    return ConfigurationProfile(
        fingerprint="cfg_" + metadata_hash[:16],
        objects_count=len(signatures),
        generated_at=datetime.now(timezone.utc).isoformat(),
        metadata_hash=metadata_hash,
        sampled_objects=[item["full_name"] for item in signatures[:50]],
        source=source,
    )


def manual_configuration_profile(fingerprint: str) -> ConfigurationProfile:
    normalized = fingerprint or "local"
    return ConfigurationProfile(
        fingerprint=normalized,
        generated_at=datetime.now(timezone.utc).isoformat(),
        metadata_hash="",
        source="manual",
    )


def configuration_fingerprint_resolved(value: str) -> bool:
    normalized = (value or "").strip().lower()
    return bool(normalized) and normalized not in {"auto", "computed", "unknown", "unresolved"}


def collect_profile_metadata_objects(
    metadata_provider: MetadataProvider,
    search_terms: Iterable[str],
    limit_objects: int,
) -> List[MetadataObject]:
    by_name: Dict[str, MetadataObject] = {}
    for term in search_terms:
        for item in metadata_provider.search_objects(term):
            if item.full_name and item.full_name not in by_name:
                by_name[item.full_name] = item
            if len(by_name) >= limit_objects:
                return sorted(by_name.values(), key=lambda value: value.full_name)
    return sorted(by_name.values(), key=lambda value: value.full_name)


def metadata_signature(item: MetadataObject) -> Dict[str, Any]:
    field_signatures = []
    for name in sorted(item.field_details):
        details = item.field_details[name]
        field_signatures.append(
            {
                "name": name,
                "category": str(details.get("_category") or ""),
                "type": str(details.get("Тип") or details.get("type") or ""),
                "synonym": str(details.get("Синоним") or details.get("synonym") or ""),
                "nested_fields": sorted(str(value) for value in details.get("_nested_fields", []) or []),
            }
        )
    return {
        "full_name": item.full_name,
        "synonym": item.synonym,
        "fields": field_signatures,
    }


def hash_payload(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()

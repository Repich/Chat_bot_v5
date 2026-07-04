from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from wiicon5.knowledge.metadata import MetadataObject, MetadataProvider


@dataclass(frozen=True)
class IndexedMetadataRecord:
    full_name: str
    kind: str
    source_files: List[str] = field(default_factory=list)
    fields: List[str] = field(default_factory=list)
    field_details: Dict[str, Dict[str, object]] = field(default_factory=dict)
    source: str = "onboarding_index"
    trust: str = "hint"
    confidence: float = 0.2
    synonym: str = ""


class OnboardingMetadataIndex:
    def __init__(self, path: Path, search_limit: int = 20) -> None:
        self.path = path
        self.search_limit = search_limit
        self._mtime: float = -1
        self._records: Dict[str, IndexedMetadataRecord] = {}

    def available(self) -> bool:
        return self.path.exists() and self.path.stat().st_size > 0

    def search_objects(self, term: str) -> List[MetadataObject]:
        self._refresh_if_needed()
        normalized = term.strip().lower()
        if not normalized:
            return []
        scored: List[tuple[int, IndexedMetadataRecord]] = []
        for record in self._records.values():
            field_haystacks = []
            for details in record.field_details.values():
                field_haystacks.extend([str(details.get("synonym") or ""), str(details.get("type") or "")])
            haystacks = [
                record.full_name,
                record.kind,
                record.synonym,
                *record.fields,
                *field_haystacks,
                *record.source_files,
            ]
            score = score_record(normalized, haystacks)
            if score:
                scored.append((score, record))
        scored.sort(key=lambda item: (-item[0], item[1].full_name))
        return [metadata_object_from_record(record) for _, record in scored[: self.search_limit]]

    def get_object(self, full_name: str) -> MetadataObject:
        self._refresh_if_needed()
        record = self._records.get(full_name)
        if not record:
            return MetadataObject(full_name=full_name)
        return metadata_object_from_record(record)

    def _refresh_if_needed(self) -> None:
        if not self.available():
            self._mtime = -1
            self._records = {}
            return
        mtime = self.path.stat().st_mtime
        if mtime == self._mtime:
            return
        self._records = self._read_records()
        self._mtime = mtime

    def _read_records(self) -> Dict[str, IndexedMetadataRecord]:
        records: Dict[str, IndexedMetadataRecord] = {}
        fields: Dict[str, List[str]] = {}
        field_details: Dict[str, Dict[str, Dict[str, object]]] = {}
        with sqlite3.connect(self.path) as connection:
            object_columns = table_columns(connection, "objects")
            field_columns = table_columns(connection, "fields")
            if {"category", "source", "trust", "confidence", "type_text", "synonym", "nested_fields_json"}.issubset(
                field_columns
            ):
                for row in connection.execute(
                    """
                    SELECT object_full_name, field_name, category, source, trust, confidence, type_text, synonym, nested_fields_json
                    FROM fields
                    ORDER BY object_full_name, field_name
                    """
                ):
                    full_name = str(row[0])
                    field_name = str(row[1])
                    fields.setdefault(full_name, []).append(field_name)
                    field_details.setdefault(full_name, {})[field_name] = field_details_from_row(
                        field_name=field_name,
                        category=str(row[2]),
                        source=str(row[3]),
                        trust=str(row[4]),
                        confidence=float(row[5]),
                        type_text=str(row[6]),
                        synonym=str(row[7]),
                        nested_fields_json=str(row[8]),
                    )
            else:
                for full_name, field_name in connection.execute(
                    "SELECT object_full_name, field_name FROM fields ORDER BY object_full_name, field_name"
                ):
                    full_name = str(full_name)
                    field_name = str(field_name)
                    fields.setdefault(full_name, []).append(field_name)
                    field_details.setdefault(full_name, {})[field_name] = field_details_from_row(
                        field_name=field_name,
                        category="indexed",
                        source="onboarding_index",
                        trust="hint",
                        confidence=0.2,
                        type_text="",
                        synonym="",
                        nested_fields_json="[]",
                    )
            if {"source", "trust", "confidence", "synonym"}.issubset(object_columns):
                object_rows = connection.execute(
                    "SELECT full_name, kind, source_files_json, source, trust, confidence, synonym FROM objects ORDER BY full_name"
                )
            else:
                object_rows = connection.execute(
                    "SELECT full_name, kind, source_files_json, 'onboarding_index', 'hint', 0.2, '' FROM objects ORDER BY full_name"
                )
            for full_name, kind, source_files_json, source, trust, confidence, synonym in object_rows:
                try:
                    source_files = json.loads(str(source_files_json))
                except json.JSONDecodeError:
                    source_files = []
                if not isinstance(source_files, list):
                    source_files = []
                records[str(full_name)] = IndexedMetadataRecord(
                    full_name=str(full_name),
                    kind=str(kind),
                    source_files=[str(item) for item in source_files],
                    fields=fields.get(str(full_name), []),
                    field_details=field_details.get(str(full_name), {}),
                    source=str(source),
                    trust=str(trust),
                    confidence=float(confidence),
                    synonym=str(synonym),
                )
        return records


class IndexedMetadataProvider(MetadataProvider):
    def __init__(self, primary: MetadataProvider, index: OnboardingMetadataIndex) -> None:
        self.primary = primary
        self.index = index
        self.last_requests: List[Dict[str, object]] = []

    def search_objects(self, term: str) -> List[MetadataObject]:
        primary_request_count = len(getattr(self.primary, "last_requests", []))
        primary_items = self.primary.search_objects(term)
        index_items = self.index.search_objects(term)
        self.last_requests.extend(getattr(self.primary, "last_requests", [])[primary_request_count:])
        self.last_requests.append(
            {
                "operation": "search_objects",
                "term": term,
                "source": "onboarding_index",
                "success": self.index.available(),
                "error": "" if self.index.available() else "onboarding metadata index is not available",
                "returned": len(index_items),
            }
        )
        return merge_metadata_objects(primary_items, index_items)

    def get_object(self, full_name: str) -> MetadataObject:
        primary_request_count = len(getattr(self.primary, "last_requests", []))
        primary_item = self.primary.get_object(full_name)
        self.last_requests.extend(getattr(self.primary, "last_requests", [])[primary_request_count:])
        if primary_item.fields or primary_item.synonym or primary_item.raw:
            return primary_item
        index_item = self.index.get_object(full_name)
        self.last_requests.append(
            {
                "operation": "get_object",
                "full_name": full_name,
                "source": "onboarding_index",
                "success": bool(index_item.raw),
                "error": "" if index_item.raw else "object not found in onboarding metadata index",
                "returned": 1 if index_item.raw else 0,
            }
        )
        return index_item


def score_record(term: str, haystacks: List[str]) -> int:
    score = 0
    for value in haystacks:
        lowered = value.lower()
        if lowered == term:
            score += 100
        elif lowered.endswith("." + term):
            score += 80
        elif term in lowered:
            score += 20
    return score


def metadata_object_from_record(record: IndexedMetadataRecord) -> MetadataObject:
    return MetadataObject(
        full_name=record.full_name,
        synonym=record.synonym,
        fields=list(record.fields),
        field_details={
            field: dict(record.field_details.get(field, field_details_from_row(field_name=field)))
            for field in record.fields
        },
        raw={
            "source": "onboarding_index",
            "_source": record.source,
            "_trust": record.trust,
            "_confidence": record.confidence,
            "kind": record.kind,
            "source_files": list(record.source_files),
        },
    )


def merge_metadata_objects(primary_items: List[MetadataObject], index_items: List[MetadataObject]) -> List[MetadataObject]:
    by_name: Dict[str, MetadataObject] = {}
    for item in primary_items + index_items:
        if not item.full_name or item.full_name in by_name:
            continue
        by_name[item.full_name] = item
    return list(by_name.values())


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def field_details_from_row(
    *,
    field_name: str,
    category: str = "indexed",
    source: str = "onboarding_index",
    trust: str = "hint",
    confidence: float = 0.2,
    type_text: str = "",
    synonym: str = "",
    nested_fields_json: str = "[]",
) -> Dict[str, object]:
    nested_fields, nested_details = parse_nested_fields(nested_fields_json)
    details: Dict[str, object] = {
        "Имя": field_name,
        "name": field_name,
        "Синоним": synonym,
        "synonym": synonym,
        "Тип": type_text,
        "type": type_text,
        "_category": category,
        "_source": source,
        "_trust": trust,
        "_confidence": confidence,
    }
    if nested_fields:
        details["_nested_fields"] = nested_fields
        details["_nested_field_details"] = nested_details
    return details


def parse_nested_fields(raw: str) -> tuple[List[str], Dict[str, Dict[str, object]]]:
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return [], {}
    if not isinstance(items, list):
        return [], {}
    names: List[str] = []
    details: Dict[str, Dict[str, object]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not name:
            continue
        names.append(name)
        nested_names, nested_details = parse_nested_fields(json.dumps(item.get("nested_fields", []), ensure_ascii=False))
        details[name] = {
            "Имя": name,
            "name": name,
            "Синоним": str(item.get("synonym") or ""),
            "synonym": str(item.get("synonym") or ""),
            "Тип": str(item.get("type") or ""),
            "type": str(item.get("type") or ""),
            "_category": str(item.get("category") or "attribute"),
            "_source": str(item.get("source") or "metadata_xml"),
            "_trust": str(item.get("trust") or "verified"),
            "_confidence": float(item.get("confidence") or 0.95),
        }
        if nested_names:
            details[name]["_nested_fields"] = nested_names
            details[name]["_nested_field_details"] = nested_details
    return names, details

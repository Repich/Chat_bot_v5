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
            haystacks = [record.full_name, record.kind, *record.fields, *record.source_files]
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
        with sqlite3.connect(self.path) as connection:
            for full_name, field_name in connection.execute(
                "SELECT object_full_name, field_name FROM fields ORDER BY object_full_name, field_name"
            ):
                fields.setdefault(str(full_name), []).append(str(field_name))
            for full_name, kind, source_files_json in connection.execute(
                "SELECT full_name, kind, source_files_json FROM objects ORDER BY full_name"
            ):
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
                "success": bool(index_item.fields),
                "error": "" if index_item.fields else "object not found in onboarding metadata index",
                "returned": 1 if index_item.fields else 0,
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
        fields=list(record.fields),
        field_details={field: {"Имя": field, "_category": "indexed"} for field in record.fields},
        raw={
            "source": "onboarding_index",
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

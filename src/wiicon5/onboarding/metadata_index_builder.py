from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List

from wiicon5.onboarding.config_dump_reader import DumpFile
from wiicon5.onboarding.onec_xml_parser import ParsedXmlField, ParsedXmlObject, parse_metadata_xml


OBJECT_PATTERN = re.compile(r"\b(Справочник|Документ|РегистрНакопления|РегистрСведений)\.([A-Za-zА-Яа-яЁё0-9_]+)\b")
FIELD_PATTERN = re.compile(r"\b(?:Реквизит|Измерение|Ресурс|Поле)\.([A-Za-zА-Яа-яЁё0-9_]+)\b")
PATH_KIND_BY_DIR = {
    "Catalogs": "Справочник",
    "Documents": "Документ",
    "AccumulationRegisters": "РегистрНакопления",
    "InformationRegisters": "РегистрСведений",
}


@dataclass
class IndexedField:
    name: str
    category: str = "indexed"
    source: str = "bsl_regex"
    trust: str = "hint"
    confidence: float = 0.2
    type_text: str = ""
    synonym: str = ""
    nested_fields: List["IndexedField"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "category": self.category,
            "source": self.source,
            "trust": self.trust,
            "confidence": self.confidence,
            "type": self.type_text,
            "synonym": self.synonym,
            "nested_fields": [item.to_dict() for item in self.nested_fields],
        }


@dataclass
class IndexedObject:
    full_name: str
    kind: str
    source_files: List[str] = field(default_factory=list)
    fields: List[str] = field(default_factory=list)
    field_details: Dict[str, IndexedField] = field(default_factory=dict)
    source: str = "source_path"
    trust: str = "hint"
    confidence: float = 0.2
    synonym: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "full_name": self.full_name,
            "kind": self.kind,
            "source_files": list(self.source_files),
            "fields": list(self.fields),
            "field_details": {name: details.to_dict() for name, details in self.field_details.items()},
            "source": self.source,
            "trust": self.trust,
            "confidence": self.confidence,
            "synonym": self.synonym,
        }


def extract_metadata_objects(files: Iterable[DumpFile]) -> List[IndexedObject]:
    dump_files = list(files)
    by_name: Dict[str, IndexedObject] = {}
    path_full_names = set()
    for dump_file in dump_files:
        parsed_xml = parse_metadata_xml(dump_file.text, relative_path=dump_file.relative_path)
        if parsed_xml is not None:
            add_xml_object(by_name, parsed_xml, dump_file.relative_path)
            path_full_names.add(parsed_xml.full_name)
            continue
        field_hints = indexed_field_hints(extract_field_names(dump_file.text), source="bsl_regex")
        for kind, object_name in objects_from_path(dump_file.relative_path):
            path_full_names.add(f"{kind}.{object_name}")
            add_indexed_object(by_name, kind, object_name, dump_file.relative_path, field_hints)
    restrict_regex_to_path_objects = bool(path_full_names)
    for dump_file in dump_files:
        field_hints = indexed_field_hints(extract_field_names(dump_file.text), source="bsl_regex")
        for match in OBJECT_PATTERN.finditer(dump_file.text + "\n" + dump_file.relative_path):
            kind = match.group(1)
            object_name = match.group(2)
            full_name = f"{kind}.{object_name}"
            if restrict_regex_to_path_objects and full_name not in path_full_names:
                continue
            if not restrict_regex_to_path_objects and not is_plausible_metadata_name(object_name):
                continue
            add_indexed_object(by_name, kind, object_name, dump_file.relative_path, field_hints)
    return sorted(by_name.values(), key=lambda item: item.full_name)


def add_xml_object(by_name: Dict[str, IndexedObject], parsed_xml: ParsedXmlObject, relative_path: str) -> None:
    kind, object_name = split_full_name(parsed_xml.full_name)
    item = add_indexed_object(
        by_name,
        kind,
        object_name,
        relative_path,
        [indexed_field_from_xml(field_item) for field_item in parsed_xml.fields],
    )
    item.source = "metadata_xml"
    item.trust = "verified"
    item.confidence = max(item.confidence, 0.95)
    item.synonym = parsed_xml.synonym


def add_indexed_object(
    by_name: Dict[str, IndexedObject],
    kind: str,
    object_name: str,
    relative_path: str,
    fields: List[IndexedField],
) -> IndexedObject:
    full_name = f"{kind}.{object_name}"
    item = by_name.setdefault(full_name, IndexedObject(full_name=full_name, kind=kind))
    if relative_path not in item.source_files:
        item.source_files.append(relative_path)
    for field_item in fields:
        add_field(item, field_item)
    return item


def add_field(item: IndexedObject, field_item: IndexedField) -> None:
    if field_item.name not in item.fields:
        item.fields.append(field_item.name)
    current = item.field_details.get(field_item.name)
    if current is None or trust_rank(field_item.trust) > trust_rank(current.trust):
        item.field_details[field_item.name] = field_item


def trust_rank(trust: str) -> int:
    return {"hint": 1, "verified": 2}.get(trust, 0)


def split_full_name(full_name: str) -> tuple[str, str]:
    kind, _, object_name = full_name.partition(".")
    return kind, object_name


def indexed_field_hints(field_names: List[str], *, source: str) -> List[IndexedField]:
    return [
        IndexedField(name=field_name, category="indexed", source=source, trust="hint", confidence=0.2)
        for field_name in field_names
    ]


def indexed_field_from_xml(field_item: ParsedXmlField) -> IndexedField:
    return IndexedField(
        name=field_item.name,
        category=field_item.category,
        source="metadata_xml",
        trust="verified",
        confidence=0.95,
        type_text=field_item.type_text,
        synonym=field_item.synonym,
        nested_fields=[indexed_field_from_xml(nested) for nested in field_item.nested_fields],
    )


def objects_from_path(relative_path: str) -> List[tuple[str, str]]:
    parts = relative_path.split("/")
    if len(parts) < 2:
        return []
    kind = PATH_KIND_BY_DIR.get(parts[0])
    if not kind:
        return []
    object_name = Path(parts[1]).stem if "." in parts[1] else parts[1]
    if not object_name:
        return []
    return [(kind, object_name)]


def is_plausible_metadata_name(name: str) -> bool:
    if not name:
        return False
    return any("А" <= char <= "я" or char in "Ёё" for char in name)


def extract_field_names(text: str) -> List[str]:
    fields: List[str] = []
    for match in FIELD_PATTERN.finditer(text):
        field_name = match.group(1)
        if field_name not in fields:
            fields.append(field_name)
    return fields


def write_metadata_index(path: Path, objects: List[IndexedObject]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE IF EXISTS objects")
        connection.execute("DROP TABLE IF EXISTS fields")
        connection.execute(
            """
            CREATE TABLE objects (
                full_name TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                source_files_json TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'source_path',
                trust TEXT NOT NULL DEFAULT 'hint',
                confidence REAL NOT NULL DEFAULT 0.2,
                synonym TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE fields (
                object_full_name TEXT NOT NULL,
                field_name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'indexed',
                source TEXT NOT NULL DEFAULT 'bsl_regex',
                trust TEXT NOT NULL DEFAULT 'hint',
                confidence REAL NOT NULL DEFAULT 0.2,
                type_text TEXT NOT NULL DEFAULT '',
                synonym TEXT NOT NULL DEFAULT '',
                nested_fields_json TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        for item in objects:
            connection.execute(
                """
                INSERT INTO objects(full_name, kind, source_files_json, source, trust, confidence, synonym)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.full_name,
                    item.kind,
                    json.dumps(item.source_files, ensure_ascii=False),
                    item.source,
                    item.trust,
                    item.confidence,
                    item.synonym,
                ),
            )
            for field_name in item.fields:
                field_item = item.field_details.get(
                    field_name,
                    IndexedField(name=field_name, category="indexed", source="bsl_regex", trust="hint"),
                )
                connection.execute(
                    """
                    INSERT INTO fields(
                        object_full_name, field_name, category, source, trust, confidence, type_text, synonym, nested_fields_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.full_name,
                        field_name,
                        field_item.category,
                        field_item.source,
                        field_item.trust,
                        field_item.confidence,
                        field_item.type_text,
                        field_item.synonym,
                        json.dumps([nested.to_dict() for nested in field_item.nested_fields], ensure_ascii=False),
                    ),
                )

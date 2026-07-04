from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List

from wiicon5.onboarding.config_dump_reader import DumpFile


OBJECT_PATTERN = re.compile(r"\b(Справочник|Документ|РегистрНакопления|РегистрСведений)\.([A-Za-zА-Яа-яЁё0-9_]+)\b")
FIELD_PATTERN = re.compile(r"\b(?:Реквизит|Измерение|Ресурс|Поле)\.([A-Za-zА-Яа-яЁё0-9_]+)\b")


@dataclass
class IndexedObject:
    full_name: str
    kind: str
    source_files: List[str] = field(default_factory=list)
    fields: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "full_name": self.full_name,
            "kind": self.kind,
            "source_files": list(self.source_files),
            "fields": list(self.fields),
        }


def extract_metadata_objects(files: Iterable[DumpFile]) -> List[IndexedObject]:
    by_name: Dict[str, IndexedObject] = {}
    for dump_file in files:
        fields = extract_field_names(dump_file.text)
        for match in OBJECT_PATTERN.finditer(dump_file.text + "\n" + dump_file.relative_path):
            kind = match.group(1)
            full_name = f"{kind}.{match.group(2)}"
            item = by_name.setdefault(full_name, IndexedObject(full_name=full_name, kind=kind))
            if dump_file.relative_path not in item.source_files:
                item.source_files.append(dump_file.relative_path)
            for field_name in fields:
                if field_name not in item.fields:
                    item.fields.append(field_name)
    return sorted(by_name.values(), key=lambda item: item.full_name)


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
            "CREATE TABLE objects (full_name TEXT PRIMARY KEY, kind TEXT NOT NULL, source_files_json TEXT NOT NULL)"
        )
        connection.execute("CREATE TABLE fields (object_full_name TEXT NOT NULL, field_name TEXT NOT NULL)")
        for item in objects:
            connection.execute(
                "INSERT INTO objects(full_name, kind, source_files_json) VALUES (?, ?, ?)",
                (item.full_name, item.kind, json.dumps(item.source_files, ensure_ascii=False)),
            )
            for field_name in item.fields:
                connection.execute(
                    "INSERT INTO fields(object_full_name, field_name) VALUES (?, ?)",
                    (item.full_name, field_name),
                )

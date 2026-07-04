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
PATH_KIND_BY_DIR = {
    "Catalogs": "Справочник",
    "Documents": "Документ",
    "AccumulationRegisters": "РегистрНакопления",
    "InformationRegisters": "РегистрСведений",
}


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
    dump_files = list(files)
    by_name: Dict[str, IndexedObject] = {}
    path_full_names = set()
    for dump_file in dump_files:
        fields = extract_field_names(dump_file.text)
        for kind, object_name in objects_from_path(dump_file.relative_path):
            path_full_names.add(f"{kind}.{object_name}")
            add_indexed_object(by_name, kind, object_name, dump_file.relative_path, fields)
    restrict_regex_to_path_objects = bool(path_full_names)
    for dump_file in dump_files:
        fields = extract_field_names(dump_file.text)
        for match in OBJECT_PATTERN.finditer(dump_file.text + "\n" + dump_file.relative_path):
            kind = match.group(1)
            object_name = match.group(2)
            full_name = f"{kind}.{object_name}"
            if restrict_regex_to_path_objects and full_name not in path_full_names:
                continue
            if not restrict_regex_to_path_objects and not is_plausible_metadata_name(object_name):
                continue
            add_indexed_object(by_name, kind, object_name, dump_file.relative_path, fields)
    return sorted(by_name.values(), key=lambda item: item.full_name)


def add_indexed_object(
    by_name: Dict[str, IndexedObject],
    kind: str,
    object_name: str,
    relative_path: str,
    fields: List[str],
) -> None:
    full_name = f"{kind}.{object_name}"
    item = by_name.setdefault(full_name, IndexedObject(full_name=full_name, kind=kind))
    if relative_path not in item.source_files:
        item.source_files.append(relative_path)
    for field_name in fields:
        if field_name not in item.fields:
            item.fields.append(field_name)


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

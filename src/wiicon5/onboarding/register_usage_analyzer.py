from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from wiicon5.onboarding.config_dump_reader import DumpFile
from wiicon5.onboarding.metadata_index_builder import OBJECT_PATTERN


REGISTER_PATTERN = re.compile(r"\b(?:Движения\.|РегистрНакопления\.)([A-Za-zА-Яа-яЁё0-9_]+)\b")


@dataclass(frozen=True)
class RegisterUsageCandidate:
    document: str
    registers: List[str] = field(default_factory=list)
    source_file: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {"document": self.document, "registers": list(self.registers), "source_file": self.source_file}


def analyze_register_usage(files: Iterable[DumpFile]) -> List[RegisterUsageCandidate]:
    result: List[RegisterUsageCandidate] = []
    for dump_file in files:
        document = document_name_from_file(dump_file)
        if not document:
            continue
        registers: List[str] = []
        for match in REGISTER_PATTERN.finditer(dump_file.text):
            full_name = f"РегистрНакопления.{match.group(1)}"
            if full_name not in registers:
                registers.append(full_name)
        if registers:
            result.append(RegisterUsageCandidate(document=document, registers=registers, source_file=dump_file.relative_path))
    return result


def document_name_from_file(dump_file: DumpFile) -> str:
    for match in OBJECT_PATTERN.finditer(dump_file.text + "\n" + dump_file.relative_path):
        if match.group(1) == "Документ":
            return f"Документ.{match.group(2)}"
    return ""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List

from wiicon5.onboarding.config_dump_reader import DumpFile


QUERY_PATTERN = re.compile(r"ВЫБРАТЬ\b(?P<body>.*?)(?:;|КонецЕсли|КонецПроцедуры|КонецФункции|$)", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class QueryPattern:
    pattern_id: str
    source_file: str
    query: str

    def to_dict(self) -> Dict[str, str]:
        return {"pattern_id": self.pattern_id, "source_file": self.source_file, "query": self.query}


def extract_query_patterns(files: Iterable[DumpFile], *, max_patterns: int = 500) -> List[QueryPattern]:
    patterns: List[QueryPattern] = []
    for dump_file in files:
        for match in QUERY_PATTERN.finditer(dump_file.text):
            query = "ВЫБРАТЬ" + match.group("body").strip()
            if len(query) < 20:
                continue
            digest = hashlib.sha1(f"{dump_file.relative_path}\n{query}".encode("utf-8")).hexdigest()[:12]
            patterns.append(QueryPattern(pattern_id=f"query_{digest}", source_file=dump_file.relative_path, query=query))
            if len(patterns) >= max_patterns:
                return patterns
    return patterns

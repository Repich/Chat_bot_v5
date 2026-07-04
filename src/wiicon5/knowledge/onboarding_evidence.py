from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from wiicon5.knowledge.metadata import MetadataObject


class OnboardingEvidenceProvider:
    def __init__(self, onboarding_dir: Path, *, max_register_usage: int = 12, max_query_patterns: int = 8) -> None:
        self.onboarding_dir = onboarding_dir
        self.max_register_usage = max_register_usage
        self.max_query_patterns = max_query_patterns

    def available(self) -> bool:
        return (self.onboarding_dir / "register_usage_map.json").exists() or (
            self.onboarding_dir / "candidate_query_patterns.jsonl"
        ).exists()

    def evidence_for(self, *, search_terms: List[str], metadata_objects: List[MetadataObject]) -> Dict[str, Any]:
        if not self.available():
            return {"available": False}
        terms = evidence_terms(search_terms, metadata_objects)
        return {
            "available": True,
            "terms": terms[:30],
            "register_usage": matching_register_usage(
                self.onboarding_dir / "register_usage_map.json",
                terms=terms,
                limit=self.max_register_usage,
            ),
            "query_patterns": matching_query_patterns(
                self.onboarding_dir / "candidate_query_patterns.jsonl",
                terms=terms,
                limit=self.max_query_patterns,
            ),
        }


def evidence_terms(search_terms: List[str], metadata_objects: List[MetadataObject]) -> List[str]:
    result: List[str] = []
    for item in search_terms:
        add_term(result, item)
    for metadata in metadata_objects:
        add_term(result, metadata.full_name)
        add_term(result, metadata.synonym)
        for part in metadata.full_name.replace(".", " ").split():
            add_term(result, part)
    return result


def matching_register_usage(path: Path, *, terms: List[str], limit: int) -> List[Dict[str, Any]]:
    payload = read_json(path)
    rows = payload.get("items") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    return top_matches(
        [
            {
                "document": str(row.get("document") or ""),
                "registers": [str(item) for item in row.get("registers", [])] if isinstance(row, dict) else [],
                "source_file": str(row.get("source_file") or ""),
            }
            for row in rows
            if isinstance(row, dict)
        ],
        terms=terms,
        fields=["document", "registers", "source_file"],
        limit=limit,
    )


def matching_query_patterns(path: Path, *, terms: List[str], limit: int) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "pattern_id": str(row.get("pattern_id") or ""),
                "source_file": str(row.get("source_file") or ""),
                "query": compact_query(str(row.get("query") or "")),
            }
        )
    return top_matches(rows, terms=terms, fields=["source_file", "query"], limit=limit)


def top_matches(rows: List[Dict[str, Any]], *, terms: List[str], fields: List[str], limit: int) -> List[Dict[str, Any]]:
    scored: List[tuple[int, Dict[str, Any]]] = []
    normalized_terms = [term.lower() for term in terms if len(term.strip()) >= 4]
    for row in rows:
        haystack = " ".join(flatten_field_values(row.get(field) for field in fields)).lower()
        score = 0
        for term in normalized_terms:
            if term and term in haystack:
                score += 10
            else:
                for word in term.split():
                    if len(word) >= 4 and word in haystack:
                        score += 2
        if score:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], stable_row_key(item[1])))
    return [row for _, row in scored[:limit]]


def flatten_field_values(values) -> List[str]:
    result: List[str] = []
    for value in values:
        if isinstance(value, list):
            result.extend(str(item) for item in value)
        else:
            result.append(str(value or ""))
    return result


def compact_query(query: str, *, max_chars: int = 1600) -> str:
    compacted = "\n".join(line.rstrip() for line in query.strip().splitlines() if line.strip())
    if len(compacted) <= max_chars:
        return compacted
    return compacted[: max_chars - 20].rstrip() + "\n...<truncated>"


def stable_row_key(row: Dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def add_term(result: List[str], value: str) -> None:
    value = str(value or "").strip()
    if value and value not in result:
        result.append(value)

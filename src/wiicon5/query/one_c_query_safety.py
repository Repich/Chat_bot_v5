from __future__ import annotations

import re
from typing import Any, List, Mapping, Optional

from wiicon5.models import ValidationIssue, ValidationResult


MUTATING_KEYWORDS = {
    "ВСТАВИТЬ",
    "ОБНОВИТЬ",
    "УДАЛИТЬ",
    "СОЗДАТЬ",
    "ИЗМЕНИТЬ",
    "ПОМЕСТИТЬ",
    "INSERT",
    "UPDATE",
    "DELETE",
    "CREATE",
    "ALTER",
    "DROP",
}


def validate_read_only_query(query: str, params: Optional[Mapping[str, Any]] = None) -> ValidationResult:
    text = query.strip()
    issues: List[ValidationIssue] = []
    if not text:
        issues.append(ValidationIssue("empty_query", "1C query is empty."))
    if text and not text.upper().startswith("ВЫБРАТЬ"):
        issues.append(ValidationIssue("not_select", "1C query must start with ВЫБРАТЬ."))
    tokens = {token.upper() for token in re.findall(r"[A-Za-zА-Яа-яЁё_]+", text)}
    forbidden = sorted(tokens.intersection(MUTATING_KEYWORDS))
    if forbidden:
        issues.append(
            ValidationIssue(
                "mutating_keyword",
                "1C query contains mutating or unsafe keywords: " + ", ".join(forbidden),
            )
        )
    if "|" in text:
        issues.append(ValidationIssue("bsl_string_prefix", "1C query must not contain BSL string prefixes."))
    declared_params = set((params or {}).keys())
    query_params = set(re.findall(r"&([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)", text))
    undeclared = sorted(query_params.difference(declared_params))
    if undeclared:
        issues.append(
            ValidationIssue(
                "undeclared_parameter",
                "1C query contains parameters missing from declarative params: " + ", ".join(undeclared),
            )
        )
    return ValidationResult(ok=not issues, issues=issues)

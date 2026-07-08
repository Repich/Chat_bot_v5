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
    issues.extend(date_literal_issues(text))
    issues.extend(parameter_value_issues(params or {}, query_params))
    return ValidationResult(ok=not issues, issues=issues)


def date_literal_issues(query: str) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for match in re.finditer(r"\bДАТАВРЕМЯ\s*\(\s*(?P<year>\d{1,6})", query, flags=re.IGNORECASE):
        issue = date_year_issue(match.group("year"), f"query literal at position {match.start()}")
        if issue is not None:
            issues.append(issue)
    return issues


def parameter_value_issues(params: Mapping[str, Any], query_params: set[str]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for name, value in params.items():
        if name not in query_params:
            continue
        issue = date_parameter_issue(name, value)
        if issue is not None:
            issues.append(issue)
        if is_empty_guid_value(value):
            issues.append(
                ValidationIssue(
                    "empty_reference_parameter",
                    (
                        f"1C query parameter &{name} contains an empty GUID. "
                        "Resolve a real reference value with a lookup query or use an explicit ПустаяСсылка expression when emptiness is intended."
                    ),
                    name,
                )
            )
    return issues


def date_parameter_issue(name: str, value: Any) -> Optional[ValidationIssue]:
    if not isinstance(value, str):
        return None
    match = re.match(r"^\s*(?P<year>\d{4,6})-\d{2}-\d{2}", value)
    if match is None:
        return None
    return date_year_issue(match.group("year"), f"parameter &{name}", path=name)


def date_year_issue(year_value: str, location: str, path: str = "") -> Optional[ValidationIssue]:
    try:
        year = int(year_value)
    except ValueError:
        return None
    if 1 <= year <= 3999:
        return None
    return ValidationIssue(
        "date_year_out_of_range",
        f"1C date year in {location} must be between 1 and 3999, got {year}.",
        path,
    )


def is_empty_guid_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() == "00000000-0000-0000-0000-000000000000"
    if isinstance(value, Mapping):
        guid = value.get("УникальныйИдентификатор") or value.get("uuid") or value.get("guid")
        return isinstance(guid, str) and is_empty_guid_value(guid)
    return False

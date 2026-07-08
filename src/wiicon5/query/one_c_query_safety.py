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
    issues.extend(ambiguous_alias_issues(text))
    issues.extend(unsupported_subquery_issues(text))
    issues.extend(date_literal_issues(text))
    issues.extend(parameter_value_issues(params or {}, query_params))
    return ValidationResult(ok=not issues, issues=issues)


def ambiguous_alias_issues(query: str) -> List[ValidationIssue]:
    from_match = re.search(r"\bИЗ\b", query, flags=re.IGNORECASE)
    if from_match is None:
        return []
    select_part = query[: from_match.start()]
    from_part = query[from_match.start() :]
    select_aliases = set(alias.lower() for alias in select_field_aliases(select_part))
    aliases = source_aliases(from_part)
    field_names = set(field.lower() for field in dereferenced_field_names_for_aliases(query, aliases))
    issues: List[ValidationIssue] = []
    for alias in aliases:
        normalized = alias.lower()
        if normalized not in select_aliases and normalized not in field_names:
            continue
        if re.search(rf"\b{re.escape(alias)}\.", from_part, flags=re.IGNORECASE) is None:
            continue
        reason = (
            "selected field alias"
            if normalized in select_aliases
            else "field name used in another dereference"
        )
        issues.append(
            ValidationIssue(
                "ambiguous_alias",
                (
                    f"1C query uses '{alias}' both as a source alias and as a {reason}. "
                    "Use distinct aliases, for example source alias 'Ном' and output alias 'Номенклатура'."
                ),
                alias,
            )
        )
    return issues


def select_field_aliases(select_part: str) -> List[str]:
    return re.findall(r"\bКАК\s+([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)\b", select_part, flags=re.IGNORECASE)


def source_aliases(from_part: str) -> List[str]:
    aliases: List[str] = []
    pattern = re.compile(
        r"\b(?:ИЗ|СОЕДИНЕНИЕ)\s+"
        r"(?:[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_.]*)(?:\s*\([^)]*\))?"
        r"\s+КАК\s+([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)\b",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(from_part):
        aliases.append(match.group(1))
    return aliases


def dereferenced_field_names_for_aliases(query: str, aliases: List[str]) -> List[str]:
    alias_names = set(alias.lower() for alias in aliases)
    result: List[str] = []
    pattern = re.compile(
        r"\b([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)\.\s*([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)\b",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(query):
        if match.group(1).lower() in alias_names:
            result.append(match.group(2))
    return result


def unsupported_subquery_issues(query: str) -> List[ValidationIssue]:
    if re.search(r"=\s*\(\s*ВЫБРАТЬ\b", query, flags=re.IGNORECASE | re.DOTALL) is None:
        return []
    return [
        ValidationIssue(
            "unsupported_scalar_subquery",
            (
                "1C query uses a scalar subquery after '='. "
                "Rewrite it as a join with an aggregated subquery, or use an explicitly supported IN/В construction."
            ),
        )
    ]


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

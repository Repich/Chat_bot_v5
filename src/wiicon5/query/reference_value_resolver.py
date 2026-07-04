from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from wiicon5.knowledge.metadata import MetadataObject
from wiicon5.mcp.client import McpClient
from wiicon5.mcp.contracts import McpQueryRequest, normalize_mcp_rows
from wiicon5.query.one_c_query_review import (
    QuerySourceRef,
    is_reference_field,
    metadata_for_source,
    parse_sources,
    reference_param_filters,
    virtual_condition_reference_param_filters,
    virtual_table_args,
)


@dataclass(frozen=True)
class ReferenceValueResolution:
    query: str
    params: Dict[str, Any]
    changed: bool = False
    resolutions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "changed": self.changed,
            "query": self.query,
            "params": dict(self.params),
            "resolutions": list(self.resolutions),
        }


class ReferenceValueResolver:
    def __init__(self, mcp_client: McpClient, *, discovery_limit: int = 200) -> None:
        self.mcp_client = mcp_client
        self.discovery_limit = discovery_limit

    def resolve(
        self,
        *,
        query: str,
        params: Mapping[str, Any],
        metadata_objects: List[MetadataObject],
    ) -> ReferenceValueResolution:
        sources = parse_sources(query)
        metadata_by_name = {item.full_name: item for item in metadata_objects if item.full_name}
        resolved_query = query
        resolved_params: Dict[str, Any] = dict(params)
        resolutions: List[Dict[str, Any]] = []

        for source in sources:
            metadata = metadata_for_source(source, metadata_by_name)
            if metadata is None:
                continue
            resolved_params, param_resolutions = self._resolve_string_params(
                source=source,
                metadata=metadata,
                params=resolved_params,
                query=resolved_query,
            )
            resolutions.extend(param_resolutions)
            resolved_query, resolved_params, literal_resolutions = self._resolve_enum_literals(
                source=source,
                metadata=metadata,
                query=resolved_query,
                params=resolved_params,
            )
            resolutions.extend(literal_resolutions)

        return ReferenceValueResolution(
            query=resolved_query,
            params=resolved_params,
            changed=resolved_query != query or resolved_params != dict(params),
            resolutions=resolutions,
        )

    def _resolve_string_params(
        self,
        *,
        source: QuerySourceRef,
        metadata: MetadataObject,
        params: Dict[str, Any],
        query: str,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        result_params = dict(params)
        resolutions: List[Dict[str, Any]] = []
        field_params = reference_param_filters(query, source.alias)
        if source.virtual_table:
            args = virtual_table_args(source.source)
            condition = args[1] if len(args) > 1 else ""
            for field_name, param_names in virtual_condition_reference_param_filters(condition).items():
                existing = field_params.setdefault(field_name, [])
                for param_name in param_names:
                    if param_name not in existing:
                        existing.append(param_name)
        for field_name, param_names in field_params.items():
            if not is_reference_field(metadata, field_name):
                continue
            for param_name in param_names:
                raw_value = result_params.get(param_name)
                raw_is_empty_list = is_empty_list(raw_value)
                if not is_plain_string(raw_value) and not raw_is_empty_list:
                    continue
                discovery = self._discover_field_values(source=source, field_name=field_name)
                search_text = param_name if raw_is_empty_list else reference_search_text(param_name, str(raw_value))
                match = best_reference_match(search_text, discovery.rows)
                resolutions.append(
                    {
                        "kind": "empty_list_param" if raw_is_empty_list else "string_param",
                        "source": source.source,
                        "field": field_name,
                        "param": param_name,
                        "value": raw_value,
                        "search_text": search_text,
                        "discovery_query": discovery.query,
                        "discovery_ok": discovery.ok,
                        "discovery_error": discovery.error,
                        "candidate_count": len(discovery.rows),
                        "matched": match is not None,
                        "matched_presentation": match.presentation if match else "",
                    }
                )
                if match is not None:
                    result_params[param_name] = [match.value] if raw_is_empty_list else match.value
        return result_params, resolutions

    def _resolve_enum_literals(
        self,
        *,
        source: QuerySourceRef,
        metadata: MetadataObject,
        query: str,
        params: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
        result_query = query
        result_params = dict(params)
        resolutions: List[Dict[str, Any]] = []
        for match in enum_literal_filters(query, source.alias):
            field_name = match["field"]
            if not is_reference_field(metadata, field_name):
                continue
            enum_name = match["enum_name"]
            if enum_name and enum_name not in field_type_text(metadata, field_name):
                continue
            discovery = self._discover_field_values(source=source, field_name=field_name)
            wanted = match["value_name"]
            reference_match = best_reference_match(wanted, discovery.rows)
            resolutions.append(
                {
                    "kind": "enum_literal",
                    "source": source.source,
                    "field": field_name,
                    "enum_name": enum_name,
                    "value_name": wanted,
                    "discovery_query": discovery.query,
                    "discovery_ok": discovery.ok,
                    "discovery_error": discovery.error,
                    "candidate_count": len(discovery.rows),
                    "matched": reference_match is not None,
                    "matched_presentation": reference_match.presentation if reference_match else "",
                }
            )
            if reference_match is None:
                continue
            param_name = unique_param_name(result_params, f"{field_name}_resolved")
            result_params[param_name] = reference_match.value
            result_query = result_query.replace(match["expression"], f"&{param_name}", 1)
        return result_query, result_params, resolutions

    def _discover_field_values(self, *, source: QuerySourceRef, field_name: str) -> "FieldValueDiscovery":
        discovery_source = reference_discovery_source(source)
        query = (
            f"ВЫБРАТЬ ПЕРВЫЕ {self.discovery_limit}\n"
            f"    {source.alias}.{field_name} КАК Значение,\n"
            f"    ПРЕДСТАВЛЕНИЕ({source.alias}.{field_name}) КАК Представление\n"
            "ИЗ\n"
            f"    {discovery_source} КАК {source.alias}\n"
            "СГРУППИРОВАТЬ ПО\n"
            f"    {source.alias}.{field_name},\n"
            f"    ПРЕДСТАВЛЕНИЕ({source.alias}.{field_name})"
        )
        response = self.mcp_client.execute_query(McpQueryRequest(query=query, limit=self.discovery_limit, include_schema=False))
        return FieldValueDiscovery(
            query=query,
            ok=response.success,
            error=response.error,
            rows=normalize_mcp_rows(response) if response.success else [],
        )


def reference_discovery_source(source: QuerySourceRef) -> str:
    if source.virtual_table:
        return f"{source.object_full_name}.{source.virtual_table}()"
    return source.source


@dataclass(frozen=True)
class FieldValueDiscovery:
    query: str
    ok: bool
    error: str
    rows: List[Dict[str, Any]]


@dataclass(frozen=True)
class ReferenceMatch:
    value: Any
    presentation: str
    score: float


def enum_literal_filters(query: str, alias: str) -> List[Dict[str, str]]:
    escaped_alias = re.escape(alias)
    pattern = re.compile(
        rf"\b{escaped_alias}\.(?P<field>[A-Za-zА-Яа-яЁё0-9_]+)\s*=\s*"
        rf"(?P<expression>ЗНАЧЕНИЕ\(\s*Перечисление\.(?P<enum>[A-Za-zА-Яа-яЁё0-9_]+)\."
        rf"(?P<value>[A-Za-zА-Яа-яЁё0-9_]+)\s*\))",
        flags=re.IGNORECASE,
    )
    return [
        {
            "field": match.group("field"),
            "expression": match.group("expression"),
            "enum_name": match.group("enum"),
            "value_name": match.group("value"),
        }
        for match in pattern.finditer(query)
    ]


def best_reference_match(wanted: str, rows: List[Dict[str, Any]]) -> Optional[ReferenceMatch]:
    candidates: List[ReferenceMatch] = []
    for row in rows:
        value = row.get("Значение")
        presentation = str(row.get("Представление") or presentation_from_value(value))
        score = reference_match_score(wanted, value, presentation)
        if score >= 0.5:
            candidates.append(ReferenceMatch(value=value, presentation=presentation, score=score))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-item.score, item.presentation))[0]


def reference_match_score(wanted: str, value: Any, presentation: str) -> float:
    wanted_words = normalized_words(wanted)
    if not wanted_words:
        return 0.0
    candidate_text = " ".join([presentation, presentation_from_value(value)])
    candidate_words = normalized_words(candidate_text)
    if not candidate_words:
        return 0.0
    wanted_structured = structured_tokens(wanted_words)
    if wanted_structured:
        candidate_structured = set(structured_tokens(candidate_words))
        if all(token in candidate_structured for token in wanted_structured):
            return 1.0
        return 0.0
    wanted_compact = "".join(wanted_words)
    candidate_compact = "".join(candidate_words)
    if wanted_compact == candidate_compact:
        return 1.0
    if wanted_compact in candidate_compact or candidate_compact in wanted_compact:
        return 0.9
    matches = 0
    for word in wanted_words:
        if any(words_match(word, candidate) for candidate in candidate_words):
            matches += 1
    return matches / len(wanted_words)


def presentation_from_value(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(
            str(value.get(key) or "")
            for key in ["Представление", "УникальныйИдентификатор", "ТипОбъекта"]
            if value.get(key)
        )
    return str(value or "")


def normalized_words(value: str) -> List[str]:
    compact = re.sub(r"([a-zа-яё])([A-ZА-ЯЁ])", r"\1 \2", value)
    return [item for item in re.split(r"[^0-9A-Za-zА-Яа-яЁё]+", compact.lower()) if item and len(item) >= 3]


def structured_tokens(words: List[str]) -> List[str]:
    result: List[str] = []
    for word in words:
        if is_low_signal_numeric_token(word):
            continue
        if re.search(r"\d", word) and (len(word) >= 4 or re.search(r"[a-zа-яё]", word, flags=re.IGNORECASE)):
            result.append(word)
    return result


def is_low_signal_numeric_token(word: str) -> bool:
    return word.isdigit() and set(word) == {"0"}


def words_match(left: str, right: str) -> bool:
    if left == right:
        return True
    if len(left) >= 4 and len(right) >= 4 and (left in right or right in left):
        return True
    if len(left) >= 5 and len(right) >= 5 and left[:5] == right[:5]:
        return True
    return False


def field_type_text(metadata: MetadataObject, field_name: str) -> str:
    details = metadata.field_details.get(field_name, {})
    return str(details.get("Тип") or details.get("type") or "")


def is_plain_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_empty_list(value: Any) -> bool:
    return isinstance(value, list) and not value


def reference_search_text(param_name: str, raw_value: str) -> str:
    value = raw_value.strip()
    if value and not looks_like_reference_placeholder(value):
        return value
    return param_name


def looks_like_reference_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return True
    if re.fullmatch(r"0{8}-0{4}-0{4}-0{4}-0{12}", normalized):
        return True
    if normalized.startswith(
        (
            "справочникссылка.",
            "документссылка.",
            "перечислениессылка.",
            "планвидовхарактеристикссылка.",
            "плансчетовссылка.",
            "планвидоврасчетовссылка.",
        )
    ):
        return True
    return False


def unique_param_name(params: Mapping[str, Any], base: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_]", "_", base).strip("_") or "param"
    if cleaned[0].isdigit():
        cleaned = f"p_{cleaned}"
    if cleaned not in params:
        return cleaned
    index = 2
    while f"{cleaned}_{index}" in params:
        index += 1
    return f"{cleaned}_{index}"

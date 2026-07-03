from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from wiicon5.conversation.context import ConversationContext
from wiicon5.knowledge.metadata import MetadataObject, MetadataProvider
from wiicon5.models import SemanticFilter, SkillContract
from wiicon5.query.query_builder import QueryBuildError, QueryBuilder
from wiicon5.query.query_draft import QueryDraft


DOCUMENT_TYPE_FIELDS = {"document_type", "document_kind", "object_type", "object_name"}
DATE_FIELDS = {"date", "period", "year"}


@dataclass(frozen=True)
class DocumentObjectCandidate:
    metadata_object: MetadataObject
    score: float
    search_term: str


class DocumentListQueryBuilder(QueryBuilder):
    def __init__(self, metadata_provider: MetadataProvider) -> None:
        self.metadata_provider = metadata_provider
        self.last_diagnostics: Dict[str, Any] = {}

    def build(self, skill: SkillContract, inputs: Dict[str, Any], context: ConversationContext) -> QueryDraft:
        filters = semantic_filters_from_inputs(inputs)
        document_type = document_type_from_filters(filters)
        if not document_type:
            raise QueryBuildError("Document list query requires semantic filter: document_type.")

        candidate = discover_document_object(self.metadata_provider, document_type)
        if candidate is None:
            self.last_diagnostics = {
                "document_type": document_type,
                "metadata_requests": getattr(self.metadata_provider, "last_requests", []),
            }
            raise QueryBuildError(f"Could not resolve document type from metadata: {document_type}")

        draft = build_document_list_query(
            metadata_object=candidate.metadata_object,
            filters=filters,
            limit=limit_from_inputs(inputs),
        )
        self.last_diagnostics = {
            "document_type": document_type,
            "selected_object": candidate.metadata_object.full_name,
            "score": candidate.score,
            "search_term": candidate.search_term,
            "metadata_requests": getattr(self.metadata_provider, "last_requests", []),
        }
        return draft


def build_document_list_query(
    *,
    metadata_object: MetadataObject,
    filters: List[SemanticFilter],
    limit: int,
) -> QueryDraft:
    full_name = metadata_object.full_name
    if not normalized_full_name(full_name).startswith("документ."):
        raise QueryBuildError(f"Metadata object is not a document: {full_name}")

    alias = "Документы"
    params: Dict[str, Any] = {}
    select_fields = document_select_fields(metadata_object)
    select_lines = [f"    {alias}.{field} КАК {field}" for field in select_fields]
    where_lines = []
    for item in filters:
        if item.semantic_field in DOCUMENT_TYPE_FIELDS:
            continue
        where_lines.extend(compile_document_filter(alias, item, params))

    query_lines = [
        f"ВЫБРАТЬ ПЕРВЫЕ {limit}",
        *comma_terminated(select_lines),
        "ИЗ",
        f"    {full_name} КАК {alias}",
    ]
    if where_lines:
        query_lines.append("ГДЕ")
        query_lines.extend(prefixed_conditions(where_lines))
    if "Дата" in select_fields:
        query_lines.extend(["УПОРЯДОЧИТЬ ПО", f"    {alias}.Дата"])
    return QueryDraft(
        query="\n".join(query_lines),
        params=params,
        limit=limit,
        metadata_dependencies=[full_name],
        reasoning="Built generic document list query from metadata-selected document object.",
    )


def discover_document_object(metadata_provider: MetadataProvider, document_type: str) -> Optional[DocumentObjectCandidate]:
    best: Optional[DocumentObjectCandidate] = None
    for term in search_terms_for_document_type(document_type):
        for item in metadata_provider.search_objects(term):
            if not item.full_name:
                continue
            metadata_object = metadata_provider.get_object(item.full_name)
            if not normalized_full_name(metadata_object.full_name).startswith("документ."):
                continue
            score = document_object_score(document_type, metadata_object)
            if score < 0.34:
                continue
            candidate = DocumentObjectCandidate(metadata_object=metadata_object, score=score, search_term=term)
            if best is None or (candidate.score, -len(candidate.metadata_object.full_name)) > (
                best.score,
                -len(best.metadata_object.full_name),
            ):
                best = candidate
    return best


def document_object_score(document_type: str, metadata_object: MetadataObject) -> float:
    target_words = normalized_words(document_type)
    object_words = normalized_words(" ".join([metadata_object.full_name, metadata_object.synonym]))
    if not target_words or not object_words:
        return 0.0
    matches = 0
    for word in target_words:
        if any(words_match(word, candidate) for candidate in object_words):
            matches += 1
    return matches / len(target_words)


def words_match(left: str, right: str) -> bool:
    if left == right:
        return True
    if len(left) >= 4 and len(right) >= 4 and (left in right or right in left):
        return True
    if len(left) >= 5 and len(right) >= 5 and left[:5] == right[:5]:
        return True
    return False


def search_terms_for_document_type(document_type: str) -> List[str]:
    terms = []
    add_unique(terms, document_type.strip())
    words = normalized_words(document_type)
    if words:
        add_unique(terms, " ".join(words))
    if len(words) > 1:
        add_unique(terms, words[0])
        add_unique(terms, words[-1])
    return terms[:4]


def document_type_from_filters(filters: List[SemanticFilter]) -> str:
    for item in filters:
        if item.semantic_field in DOCUMENT_TYPE_FIELDS:
            return str(item.value or item.raw_user_text or "").strip()
    return ""


def document_select_fields(metadata_object: MetadataObject) -> List[str]:
    available = set(metadata_object.fields)
    fields = ["Ссылка"]
    for candidate in ["Номер", "Дата", "Проведен", "ПометкаУдаления"]:
        if candidate in available or normalized_full_name(metadata_object.full_name).startswith("документ."):
            add_unique(fields, candidate)
    return fields


def compile_document_filter(alias: str, item: SemanticFilter, params: Dict[str, Any]) -> List[str]:
    field = item.semantic_field
    if field in DATE_FIELDS:
        return compile_date_filter(alias, item)
    if field == "posted":
        return [f"{alias}.Проведен = {bool_literal(item.value)}"]
    if field == "number":
        operator = item.operator.lower()
        if operator in {"contains", "substring"}:
            return [f"{alias}.Номер ПОДОБНО \"%\" + {render_param(params, 'number', item.value)} + \"%\""]
        return [f"{alias}.Номер = {render_param(params, 'number', item.value)}"]
    raise QueryBuildError(f"Unsupported document list semantic filter: {item.semantic_field}")


def compile_date_filter(alias: str, item: SemanticFilter) -> List[str]:
    year = year_from_value(item.value) or year_from_value(item.raw_user_text)
    if year is None:
        raise QueryBuildError(f"Unsupported date filter value for document list query: {item.value!r}")
    return [
        f"({alias}.Дата >= {date_time_literal(year, 1, 1)} И {alias}.Дата < {date_time_literal(year + 1, 1, 1)})"
    ]


def year_from_value(value: Any) -> Optional[int]:
    if isinstance(value, int) and 1 <= value <= 9999:
        return value
    match = re.search(r"\b(20\d{2}|19\d{2})\b", str(value or ""))
    if match:
        return int(match.group(1))
    return None


def bool_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "ИСТИНА" if value else "ЛОЖЬ"
    normalized = str(value).strip().lower()
    return "ЛОЖЬ" if normalized in {"false", "0", "нет", "непроведен", "не проведен"} else "ИСТИНА"


def date_time_literal(year: int, month: int, day: int) -> str:
    return f"ДАТАВРЕМЯ({year}, {month}, {day})"


def render_param(params: Dict[str, Any], name: str, value: Any) -> str:
    param_name = sanitize_param_name(name)
    if param_name not in params:
        params[param_name] = value
    return f"&{param_name}"


def semantic_filters_from_inputs(inputs: Dict[str, Any]) -> List[SemanticFilter]:
    result = []
    for item in inputs.get("filters", []) or []:
        if isinstance(item, SemanticFilter):
            result.append(item)
        elif isinstance(item, dict):
            result.append(SemanticFilter.from_dict(item))
        else:
            raise QueryBuildError(f"Unsupported semantic filter value: {item!r}")
    return result


def limit_from_inputs(inputs: Dict[str, Any]) -> int:
    raw = inputs.get("limit", 100)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 100
    return max(1, min(value, 1000))


def comma_terminated(lines: List[str]) -> List[str]:
    result = []
    for index, line in enumerate(lines):
        suffix = "," if index < len(lines) - 1 else ""
        result.append(line + suffix)
    return result


def prefixed_conditions(lines: Iterable[str]) -> List[str]:
    result = []
    for index, line in enumerate(lines):
        prefix = "    " if index == 0 else "    И "
        result.append(prefix + line)
    return result


def normalized_words(value: str) -> List[str]:
    compact = re.sub(r"([a-zа-яё])([A-ZА-ЯЁ])", r"\1 \2", value)
    return [item for item in re.split(r"[^0-9A-Za-zА-Яа-яЁё]+", compact.lower()) if item]


def normalized_full_name(value: str) -> str:
    return value.replace(" ", "").lower()


def sanitize_param_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_]", "_", value).strip("_")
    return cleaned or "param"


def add_unique(items: List[str], value: str) -> None:
    if value and value not in items:
        items.append(value)

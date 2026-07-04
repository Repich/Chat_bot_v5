from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from wiicon5.knowledge.metadata import (
    MetadataObject,
    confirmed_field_names,
    is_field_confirmed,
    is_metadata_object_verified,
)
from wiicon5.knowledge.one_c_wiki import EmbeddedOneCWiki


VIRTUAL_TABLES = ("ОстаткиИОбороты", "Остатки", "Обороты")
ACCUMULATION_STANDARD_FIELDS = {"Период", "Регистратор", "НомерСтроки", "Активность", "ВидДвижения", "МоментВремени"}
DOCUMENT_STANDARD_FIELDS = {"Ссылка", "Дата", "Номер", "Проведен", "ПометкаУдаления"}
DOCUMENT_TABLE_PART_STANDARD_FIELDS = {"Ссылка", "НомерСтроки"}


@dataclass(frozen=True)
class QuerySourceRef:
    source: str
    alias: str
    object_full_name: str
    object_type: str
    virtual_table: str = ""
    table_part: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "alias": self.alias,
            "object_full_name": self.object_full_name,
            "object_type": self.object_type,
            "virtual_table": self.virtual_table,
            "table_part": self.table_part,
        }


@dataclass(frozen=True)
class QueryReviewIssue:
    code: str
    message: str
    severity: str = "error"
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class QueryReviewResult:
    ok: bool
    issues: List[QueryReviewIssue] = field(default_factory=list)
    warnings: List[QueryReviewIssue] = field(default_factory=list)
    sources: List[QuerySourceRef] = field(default_factory=list)
    evidence_pack: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.to_dict() for issue in self.issues],
            "warnings": [warning.to_dict() for warning in self.warnings],
            "sources": [source.to_dict() for source in self.sources],
            "evidence_pack": dict(self.evidence_pack),
        }

    def error_text(self) -> str:
        return "; ".join(issue.message for issue in self.issues)


class OneCQueryReviewer:
    def __init__(self, *, wiki: Optional[EmbeddedOneCWiki] = None) -> None:
        self.wiki = wiki or EmbeddedOneCWiki()

    def guidance(self) -> Dict[str, Any]:
        evidence = self.wiki.answer_pack(
            "Правила проверки запросов 1С к регистрам накопления, виртуальным таблицам, документам и табличным частям",
            top_k=4,
        )
        return {
            "rules": [
                "Для таблицы движений РегистрНакопления.<Имя> по умолчанию фильтруй активные записи: <Алиас>.Активность.",
                "Не используй НЕ <Алиас>.Активность или <Алиас>.Активность = ЛОЖЬ для обычной таблицы движений.",
                "Не добавляй <Алиас>.Активность к алиасам виртуальных таблиц Остатки/Обороты/ОстаткиИОбороты.",
                "Для Остатки используй ресурсные поля вида <Ресурс>Остаток; для Обороты - <Ресурс>Оборот.",
                "Для Остатки используй только параметры Остатки(<Период>, <Условие>). Третьего параметра у Остатки нет.",
                "В условии виртуальной таблицы Остатки фильтруй по измерениям регистра; для Регистратор используй таблицу движений.",
                "Для табличных частей документов явно учитывай связь строки с документом.",
            ],
            "evidence": evidence,
        }

    def review(
        self,
        *,
        query: str,
        params: Mapping[str, Any],
        metadata_objects: List[MetadataObject],
    ) -> QueryReviewResult:
        sources = parse_sources(query)
        metadata_by_name = {item.full_name: item for item in metadata_objects if item.full_name}
        evidence_pack = self.wiki.answer_pack(
            "Активность регистров накопления виртуальные таблицы Остатки Обороты документы табличные части запрос",
            top_k=5,
        )
        issues: List[QueryReviewIssue] = []
        warnings: List[QueryReviewIssue] = []
        alias_refs = alias_field_references(query)

        for source in sources:
            refs = alias_refs.get(source.alias, set())
            metadata = metadata_for_source(source, metadata_by_name)
            if metadata is None:
                issues.append(
                    QueryReviewIssue(
                        code="source_not_confirmed_by_metadata",
                        message=f"Источник {source.source} не подтвержден метаданными.",
                        evidence=["metadata_objects"],
                    )
                )
                continue
            if not is_metadata_object_verified(metadata):
                issues.append(
                    QueryReviewIssue(
                        code="source_not_confirmed_by_verified_metadata",
                        message=(
                            f"Источник {source.source} найден только по эвристике onboarding и не подтвержден "
                            "структурой метаданных из MCP или XML выгрузки конфигурации."
                        ),
                        evidence=["metadata_objects"],
                    )
                )
                continue
            if source.object_type == "РегистрНакопления":
                review_accumulation_source(source, refs, query, params, metadata, issues, warnings)
            elif source.object_type == "Документ":
                review_document_source(source, refs, query, issues, warnings)
            if metadata is not None:
                review_confirmed_fields(source, refs, metadata, issues)
                review_reference_string_params(source, query, params, metadata, issues)
                review_unconfirmed_enum_literals(source, query, metadata, issues)

        return QueryReviewResult(
            ok=not issues,
            issues=issues,
            warnings=warnings,
            sources=sources,
            evidence_pack=evidence_pack,
        )


def review_accumulation_source(
    source: QuerySourceRef,
    refs: Set[str],
    query: str,
    params: Mapping[str, Any],
    metadata: Optional[MetadataObject],
    issues: List[QueryReviewIssue],
    warnings: List[QueryReviewIssue],
) -> None:
    evidence = ["one_c_wiki/pages/query-language/accumulation-register-query-review.md"]
    if source.virtual_table:
        if source.virtual_table == "Остатки":
            args = virtual_table_args(source.source)
            extra_args = args[2:] if len(args) > 2 else []
            if any(item.strip() for item in extra_args):
                issues.append(
                    QueryReviewIssue(
                        code="accumulation_balance_invalid_parameters",
                        message=(
                            f"Виртуальная таблица {source.object_full_name}.Остатки() принимает только два параметра: "
                            "период и условие. Убери третий параметр; для отбора используй Остатки(, <Условие>) "
                            "или таблицу движений регистра с фильтром Активность."
                        ),
                        evidence=evidence,
                    )
                )
            condition = args[1] if len(args) > 1 else ""
            review_virtual_condition_reference_params(condition, metadata, params, issues, source)
            dimension_fields = dimensions_for(metadata)
            for field_name in virtual_condition_fields(condition):
                if dimension_fields and field_name not in dimension_fields:
                    issues.append(
                        QueryReviewIssue(
                            code="virtual_table_filter_field_not_dimension",
                            message=(
                                f"Поле {field_name} не является измерением регистра {source.object_full_name}; "
                                "его нельзя использовать как условие виртуальной таблицы Остатки(). "
                                "Фильтруй Остатки() по измерениям или используй таблицу движений регистра."
                            ),
                            evidence=evidence,
                        )
                    )
        if "Активность" in refs:
            issues.append(
                QueryReviewIssue(
                    code="activity_filter_on_virtual_table",
                    message=(
                        f"Нельзя использовать {source.alias}.Активность для виртуальной таблицы "
                        f"{source.object_full_name}.{source.virtual_table}(). Убери этот фильтр: активность учитывается механизмом итогов."
                    ),
                    evidence=evidence,
                )
            )
        dimension_fields = dimensions_for(metadata)
        if dimension_fields and any(field in refs for field in dimension_fields) and virtual_args_empty(source.source):
            warnings.append(
                QueryReviewIssue(
                    code="virtual_table_filter_should_be_parameter",
                    message=(
                        f"Отбор по измерениям виртуальной таблицы {source.alias} лучше передавать параметром "
                        "виртуальной таблицы, а не внешним ГДЕ."
                    ),
                    severity="warning",
                    evidence=evidence,
                )
            )
        return

    if raw_accumulation_has_inactive_filter(query, source.alias):
        issues.append(
            QueryReviewIssue(
                code="raw_accumulation_register_inactive_filter",
                message=(
                    f"Запрос читает неактивные движения {source.object_full_name}. "
                    f"Для актуальных движений используй фильтр {source.alias}.Активность, а не НЕ {source.alias}.Активность."
                ),
                evidence=evidence,
            )
        )
    if "Активность" not in refs:
        issues.append(
            QueryReviewIssue(
                code="raw_accumulation_register_without_activity",
                message=(
                    f"Запрос читает таблицу движений {source.object_full_name} без фильтра {source.alias}.Активность. "
                    "Добавь фильтр активных записей или используй подходящую виртуальную таблицу регистра."
                ),
                evidence=evidence,
            )
        )


def review_document_source(
    source: QuerySourceRef,
    refs: Set[str],
    query: str,
    issues: List[QueryReviewIssue],
    warnings: List[QueryReviewIssue],
) -> None:
    evidence = ["one_c_wiki/pages/query-language/document-query-review.md"]
    if source.table_part and "Ссылка" not in refs:
        issues.append(
            QueryReviewIssue(
                code="document_table_part_without_document_ref",
                message=(
                    f"Источник {source.source} является табличной частью документа. "
                    f"Выбери {source.alias}.Ссылка или соедини строки с документом, чтобы явно учитывать шапку документа."
                ),
                evidence=evidence,
            )
        )
    if not source.table_part and not has_document_period_constraint(query, source.alias):
        warnings.append(
            QueryReviewIssue(
                code="document_query_without_period_filter",
                message=f"Запрос к документам {source.object_full_name} не содержит явного отбора по дате документа.",
                severity="warning",
                evidence=evidence,
            )
        )


def review_confirmed_fields(
    source: QuerySourceRef,
    refs: Set[str],
    metadata: MetadataObject,
    issues: List[QueryReviewIssue],
) -> None:
    if not refs:
        return
    allowed = expected_fields_for_source(source, metadata)
    if not allowed:
        return
    for field_name in sorted(refs):
        if field_name in allowed:
            continue
        issues.append(
            QueryReviewIssue(
                code="field_not_confirmed_by_metadata",
                message=f"Поле {source.alias}.{field_name} не подтверждено метаданными для {source.source}.",
                evidence=["metadata_objects"],
            )
        )


def review_reference_string_params(
    source: QuerySourceRef,
    query: str,
    params: Mapping[str, Any],
    metadata: MetadataObject,
    issues: List[QueryReviewIssue],
) -> None:
    for field_name, param_names in reference_param_filters(query, source.alias).items():
        if not is_reference_field(metadata, field_name):
            continue
        bad_params = [name for name in param_names if is_plain_string_param(params.get(name))]
        if not bad_params:
            continue
        field_type = field_type_text(metadata, field_name)
        issues.append(
            QueryReviewIssue(
                code="reference_filter_string_param",
                message=(
                    f"Поле {source.alias}.{field_name} имеет ссылочный тип {field_type}, но сравнивается со строковым "
                    f"параметром {', '.join('&' + name for name in bad_params)}. "
                    "Сначала получи ссылку на объект или сравнивай реквизит ссылки, например .Наименование."
                ),
                evidence=["metadata_objects", "query_params"],
            )
        )


def review_virtual_condition_reference_params(
    condition: str,
    metadata: Optional[MetadataObject],
    params: Mapping[str, Any],
    issues: List[QueryReviewIssue],
    source: QuerySourceRef,
) -> None:
    if metadata is None or not condition.strip():
        return
    for field_name, param_names in virtual_condition_reference_param_filters(condition).items():
        if not is_reference_field(metadata, field_name):
            continue
        bad_params = [name for name in param_names if is_plain_string_param(params.get(name))]
        if not bad_params:
            continue
        field_type = field_type_text(metadata, field_name)
        issues.append(
            QueryReviewIssue(
                code="reference_filter_string_param",
                message=(
                    f"Поле {field_name} в условии виртуальной таблицы "
                    f"{source.object_full_name}.{source.virtual_table}() имеет ссылочный тип {field_type}, но сравнивается "
                    f"со строковым параметром {', '.join('&' + name for name in bad_params)}. "
                    "Сначала получи ссылку на объект или сравнивай подтвержденный реквизит ссылки, например .Наименование."
                ),
                evidence=["metadata_objects", "query_params"],
            )
        )


def review_unconfirmed_enum_literals(
    source: QuerySourceRef,
    query: str,
    metadata: MetadataObject,
    issues: List[QueryReviewIssue],
) -> None:
    escaped_alias = re.escape(source.alias)
    pattern = re.compile(
        rf"\b{escaped_alias}\.(?P<field>[A-Za-zА-Яа-яЁё0-9_]+)\s*=\s*"
        rf"ЗНАЧЕНИЕ\(\s*Перечисление\.(?P<enum>[A-Za-zА-Яа-яЁё0-9_]+)\."
        rf"(?P<value>[A-Za-zА-Яа-яЁё0-9_]+)\s*\)",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(query):
        field_name = match.group("field")
        if not is_reference_field(metadata, field_name):
            continue
        enum_name = match.group("enum")
        field_type = field_type_text(metadata, field_name)
        if enum_name and enum_name not in field_type:
            continue
        issues.append(
            QueryReviewIssue(
                code="enum_value_not_confirmed_by_metadata",
                message=(
                    f"Значение Перечисление.{enum_name}.{match.group('value')} для поля "
                    f"{source.alias}.{field_name} не подтверждено метаданными или данными. "
                    "Сначала получи реальные значения поля через MCP и передай найденную ссылку параметром."
                ),
                evidence=["metadata_objects", "query_literal"],
            )
        )


def expected_fields_for_source(source: QuerySourceRef, metadata: MetadataObject) -> Set[str]:
    base_fields = set(confirmed_field_names(metadata))
    if source.object_type == "Документ" and source.table_part:
        table_part_fields = fields_for_document_table_part(metadata, source.table_part)
        if table_part_fields:
            return table_part_fields | DOCUMENT_TABLE_PART_STANDARD_FIELDS
        return base_fields | DOCUMENT_TABLE_PART_STANDARD_FIELDS
    if source.object_type == "РегистрНакопления":
        dimensions = dimensions_for(metadata)
        resources = resources_for(metadata)
        if not source.virtual_table:
            return base_fields | ACCUMULATION_STANDARD_FIELDS
        if source.virtual_table == "Остатки":
            return dimensions | {f"{resource}Остаток" for resource in resources}
        if source.virtual_table == "Обороты":
            return dimensions | {"Период"} | {f"{resource}Оборот" for resource in resources}
        if source.virtual_table == "ОстаткиИОбороты":
            result = set(dimensions) | {"Период"}
            for resource in resources:
                result.update(
                    {
                        f"{resource}НачальныйОстаток",
                        f"{resource}Приход",
                        f"{resource}Расход",
                        f"{resource}Оборот",
                        f"{resource}КонечныйОстаток",
                    }
                )
            return result
    if source.object_type == "Документ":
        return base_fields | DOCUMENT_STANDARD_FIELDS
    return base_fields


def metadata_for_source(source: QuerySourceRef, metadata_by_name: Mapping[str, MetadataObject]) -> Optional[MetadataObject]:
    if source.table_part:
        table_part_metadata = metadata_by_name.get(source.source)
        if table_part_metadata is not None:
            return table_part_metadata
    return metadata_by_name.get(source.object_full_name)


def fields_for_document_table_part(metadata: MetadataObject, table_part: str) -> Set[str]:
    details = metadata.field_details.get(table_part)
    if not details or not is_field_confirmed(details):
        return set()
    nested = details.get("_nested_fields")
    if not isinstance(nested, list):
        return set()
    nested_details = details.get("_nested_field_details")
    if isinstance(nested_details, dict):
        return {
            str(item)
            for item in nested
            if item and is_field_confirmed(nested_details.get(str(item), {}))
        }
    return {str(item) for item in nested if item}


def dimensions_for(metadata: Optional[MetadataObject]) -> Set[str]:
    if metadata is None:
        return set()
    return {
        name
        for name, details in metadata.field_details.items()
        if details.get("_category") == "dimension" and is_field_confirmed(details)
    }


def resources_for(metadata: MetadataObject) -> Set[str]:
    return {
        name
        for name, details in metadata.field_details.items()
        if details.get("_category") == "resource" and is_field_confirmed(details)
    }


def reference_param_filters(query: str, alias: str) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    escaped_alias = re.escape(alias)
    equality_pattern = re.compile(
        rf"\b{escaped_alias}\.(?P<field>[A-Za-zА-Яа-яЁё0-9_]+)\s*=\s*&(?P<param>[A-Za-zА-Яа-яЁё0-9_]+)",
        flags=re.IGNORECASE,
    )
    for match in equality_pattern.finditer(query):
        add_param_ref(result, match.group("field"), match.group("param"))

    in_pattern = re.compile(
        rf"\b{escaped_alias}\.(?P<field>[A-Za-zА-Яа-яЁё0-9_]+)\s+В\s*\((?P<params>[^)]*)\)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in in_pattern.finditer(query):
        for param_name in re.findall(r"&([A-Za-zА-Яа-яЁё0-9_]+)", match.group("params")):
            add_param_ref(result, match.group("field"), param_name)
    return result


def virtual_condition_reference_param_filters(condition: str) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    equality_pattern = re.compile(
        r"(?<![.&])\b(?P<field>[A-Za-zА-Яа-яЁё0-9_]+)\s*=\s*&(?P<param>[A-Za-zА-Яа-яЁё0-9_]+)",
        flags=re.IGNORECASE,
    )
    for match in equality_pattern.finditer(condition):
        if not is_top_level_position(condition, match.start("field")):
            continue
        add_param_ref(result, match.group("field"), match.group("param"))

    in_pattern = re.compile(
        r"(?<![.&])\b(?P<field>[A-Za-zА-Яа-яЁё0-9_]+)\s+В\s*\((?P<params>[^)]*)\)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in in_pattern.finditer(condition):
        if not is_top_level_position(condition, match.start("field")):
            continue
        raw_params = match.group("params")
        if re.search(r"\bВЫБРАТЬ\b", raw_params, flags=re.IGNORECASE):
            continue
        for param_name in re.findall(r"&([A-Za-zА-Яа-яЁё0-9_]+)", raw_params):
            add_param_ref(result, match.group("field"), param_name)
    return result


def is_top_level_position(value: str, position: int) -> bool:
    depth = 0
    for char in value[:position]:
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
    return depth == 0


def add_param_ref(result: Dict[str, List[str]], field_name: str, param_name: str) -> None:
    values = result.setdefault(field_name, [])
    if param_name not in values:
        values.append(param_name)


def is_reference_field(metadata: MetadataObject, field_name: str) -> bool:
    details = metadata.field_details.get(field_name)
    if not details or not is_field_confirmed(details):
        return False
    type_text = str(details.get("Тип") or details.get("type") or "")
    normalized = type_text.replace(" ", "").lower()
    return "ссылка." in normalized or normalized.startswith(
        (
            "справочникссылка.",
            "документссылка.",
            "перечислениессылка.",
            "планвидовхарактеристикссылка.",
            "плансчетовссылка.",
            "планвидоврасчетовссылка.",
        )
    )


def field_type_text(metadata: MetadataObject, field_name: str) -> str:
    details = metadata.field_details.get(field_name)
    if not details or not is_field_confirmed(details):
        return ""
    return str(details.get("Тип") or details.get("type") or "")


def is_plain_string_param(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return any(isinstance(item, str) and bool(item.strip()) for item in value)
    return False


def parse_sources(query: str) -> List[QuerySourceRef]:
    result: List[QuerySourceRef] = []
    keyword_pattern = re.compile(
        r"\bИЗ\b|\b(?:(?:ВНУТРЕННЕЕ|ЛЕВОЕ|ПРАВОЕ|ПОЛНОЕ)\s+)?СОЕДИНЕНИЕ\b",
        flags=re.IGNORECASE,
    )
    for match in keyword_pattern.finditer(query):
        parsed = parse_source_after_keyword(query, match.end())
        if parsed is None:
            continue
        source_ref, _ = parsed
        result.append(source_ref)
    return result


def parse_source_after_keyword(query: str, start: int) -> Optional[Tuple[QuerySourceRef, int]]:
    source_pattern = re.compile(
        r"\s*(?P<object_type>РегистрНакопления|РегистрСведений|Документ|Справочник)"
        r"\.(?P<object_name>[A-Za-zА-Яа-яЁё0-9_]+)",
        flags=re.IGNORECASE,
    )
    match = source_pattern.match(query, start)
    if match is None:
        return None
    object_type = match.group("object_type")
    source = f"{object_type}.{match.group('object_name')}"
    position = match.end()

    if position < len(query) and query[position] == ".":
        token_match = re.match(r"\.([A-Za-zА-Яа-яЁё0-9_]+)", query[position:])
        if token_match is not None:
            token = token_match.group(1)
            position += len(token_match.group(0))
            if token.lower() in {item.lower() for item in VIRTUAL_TABLES}:
                source += "." + canonical_virtual_table_name(token)
                position = skip_spaces(query, position)
                if position < len(query) and query[position] == "(":
                    end_position = matching_parenthesis_position(query, position)
                    if end_position is None:
                        return None
                    source += query[position : end_position + 1]
                    position = end_position + 1
            elif object_type.lower() == "документ":
                source += "." + token

    alias_match = re.match(r"\s+КАК\s+(?P<alias>[A-Za-zА-Яа-яЁё0-9_]+)", query[position:], flags=re.IGNORECASE)
    if alias_match is None:
        return None
    alias = alias_match.group("alias")
    source = normalize_space(source)
    source_ref = QuerySourceRef(
        source=source,
        alias=alias,
        object_full_name=object_name_for_source(source),
        object_type=source.split(".", 1)[0],
        virtual_table=virtual_table_for_source(source),
        table_part=table_part_for_source(source),
    )
    return source_ref, position + alias_match.end()


def canonical_virtual_table_name(value: str) -> str:
    for item in VIRTUAL_TABLES:
        if item.lower() == value.lower():
            return item
    return value


def skip_spaces(query: str, position: int) -> int:
    while position < len(query) and query[position].isspace():
        position += 1
    return position


def matching_parenthesis_position(query: str, open_position: int) -> Optional[int]:
    depth = 0
    for position in range(open_position, len(query)):
        char = query[position]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return position
    return None


def object_name_for_source(source: str) -> str:
    for virtual_table in VIRTUAL_TABLES:
        marker = f".{virtual_table}"
        if marker in source:
            return source.split(marker, 1)[0]
    parts = source.split(".")
    if len(parts) >= 2:
        return ".".join(parts[:2])
    return source


def virtual_table_for_source(source: str) -> str:
    for virtual_table in VIRTUAL_TABLES:
        if re.search(rf"\.{virtual_table}(?:\s*\(|$)", source, flags=re.IGNORECASE):
            return virtual_table
    return ""


def table_part_for_source(source: str) -> str:
    if not source.startswith("Документ."):
        return ""
    parts = source.split(".")
    return parts[2] if len(parts) >= 3 else ""


def alias_field_references(query: str) -> Dict[str, Set[str]]:
    result: Dict[str, Set[str]] = {}
    for alias, field_name in re.findall(r"\b([A-Za-zА-Яа-яЁё0-9_]+)\.([A-Za-zА-Яа-яЁё0-9_]+)\b", query):
        result.setdefault(alias, set()).add(field_name)
    return result


def virtual_args_empty(source: str) -> bool:
    match = re.search(r"\((?P<args>.*)\)\s*$", source)
    if match is None:
        return True
    args = match.group("args").strip()
    return not args or all(not item.strip() for item in args.split(","))


def virtual_table_args(source: str) -> List[str]:
    match = re.search(r"\((?P<args>.*)\)\s*$", source)
    if match is None:
        return []
    return split_top_level_commas(match.group("args"))


def split_top_level_commas(value: str) -> List[str]:
    result: List[str] = []
    current: List[str] = []
    depth = 0
    for char in value:
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        if char == "," and depth == 0:
            result.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    result.append("".join(current).strip())
    return result


def virtual_condition_fields(condition: str) -> Set[str]:
    result: Set[str] = set()
    for match in re.finditer(
        r"(?<![.&])\b(?P<field>[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)\s*(?:=|<>|>=|<=|>|<|\bВ\b|\bПОДОБНО\b)",
        condition,
        flags=re.IGNORECASE,
    ):
        field = match.group("field")
        if field.upper() in {"И", "ИЛИ", "НЕ", "В", "ПОДОБНО"}:
            continue
        result.add(field)
    return result


def raw_accumulation_has_inactive_filter(query: str, alias: str) -> bool:
    escaped_alias = re.escape(alias)
    return bool(
        re.search(rf"\bНЕ\s+{escaped_alias}\.Активность\b", query, flags=re.IGNORECASE)
        or re.search(rf"\b{escaped_alias}\.Активность\s*=\s*(?:ЛОЖЬ|FALSE)\b", query, flags=re.IGNORECASE)
    )


def has_document_period_constraint(query: str, alias: str) -> bool:
    return bool(re.search(rf"\b{re.escape(alias)}\.(?:Дата|Период)\b", query, flags=re.IGNORECASE))


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()

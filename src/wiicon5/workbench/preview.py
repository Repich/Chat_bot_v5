from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from wiicon5.knowledge.metadata import MetadataObject
from wiicon5.models import ValidationIssue
from wiicon5.query.one_c_query_review import OneCQueryReviewer
from wiicon5.query.one_c_query_safety import validate_read_only_query
from wiicon5.workbench.models import FieldMapping, HumanSkillDraft


@dataclass(frozen=True)
class QueryPreviewResult:
    ok: bool
    query: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    limit: int = 100
    issues: List[ValidationIssue] = field(default_factory=list)
    safety: Dict[str, Any] = field(default_factory=dict)
    review: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "query": self.query,
            "params": dict(self.params),
            "limit": self.limit,
            "issues": [item.to_dict() for item in self.issues],
            "safety": dict(self.safety),
            "review": dict(self.review),
        }


class QueryPreviewService:
    def __init__(
        self,
        *,
        reviewer: Optional[OneCQueryReviewer] = None,
        metadata_lookup: Optional[Callable[[str], MetadataObject]] = None,
    ) -> None:
        self.reviewer = reviewer or OneCQueryReviewer()
        self.metadata_lookup = metadata_lookup

    def preview(self, draft: HumanSkillDraft) -> QueryPreviewResult:
        issues = validate_recipe(draft)
        if issues:
            return QueryPreviewResult(ok=False, issues=issues)
        query, params, limit = build_top_n_by_metric_query(draft)
        safety = validate_read_only_query(query, params)
        metadata_objects = metadata_objects_from_draft(draft, metadata_lookup=self.metadata_lookup)
        review = self.reviewer.review(query=query, params=params, metadata_objects=metadata_objects)
        all_issues = list(safety.issues)
        all_issues.extend(
            ValidationIssue(code=issue.code, message=issue.message, path="query_review")
            for issue in review.issues
        )
        return QueryPreviewResult(
            ok=safety.ok and review.ok,
            query=query,
            params=params,
            limit=limit,
            issues=all_issues,
            safety=safety.to_dict(),
            review=review.to_dict(),
        )


def validate_recipe(draft: HumanSkillDraft) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    calculation = draft.calculation
    if calculation.kind != "top_n_by_metric":
        issues.append(
            ValidationIssue(
                "unsupported_calculation_kind",
                "Preview currently supports only top_n_by_metric calculation recipes.",
                "calculation.kind",
            )
        )
        return issues
    if not draft.data_sources:
        issues.append(ValidationIssue("missing_data_source", "Select at least one 1C data source.", "data_sources"))
    if not calculation.source_alias:
        issues.append(ValidationIssue("missing_source_alias", "Set calculation.source_alias.", "calculation.source_alias"))
    elif not source_by_alias(draft, calculation.source_alias):
        issues.append(
            ValidationIssue(
                "unknown_source_alias",
                f"Source alias {calculation.source_alias} is not defined in data_sources.",
                "calculation.source_alias",
            )
        )
    if not calculation.group_by:
        issues.append(ValidationIssue("missing_group_by", "Add at least one group_by role or field.", "calculation.group_by"))
    for role in calculation.group_by:
        if not mapping_for_role_or_field(draft.field_mappings, role):
            issues.append(ValidationIssue("missing_group_field_mapping", f"Field mapping not found for {role}.", "field_mappings"))
    if not calculation.measures:
        issues.append(ValidationIssue("missing_measure", "Add at least one measure.", "calculation.measures"))
    for measure in calculation.measures:
        if not measure.expression:
            issues.append(ValidationIssue("missing_measure_expression", f"Measure {measure.role} has no expression.", "calculation.measures"))
        elif not mapping_for_role_or_field(draft.field_mappings, measure.expression):
            issues.append(
                ValidationIssue(
                    "missing_measure_field_mapping",
                    f"Field mapping not found for measure expression {measure.expression}.",
                    "field_mappings",
                )
            )
    return issues


def build_top_n_by_metric_query(draft: HumanSkillDraft) -> tuple[str, Dict[str, Any], int]:
    calculation = draft.calculation
    source = source_by_alias(draft, calculation.source_alias)
    if source is None:
        raise ValueError("source alias was not validated")
    alias = source.alias
    group_fields = [mapping_for_role_or_field(draft.field_mappings, role) for role in calculation.group_by]
    group_fields = [item for item in group_fields if item is not None]
    measure = calculation.measures[0]
    measure_mapping = mapping_for_role_or_field(draft.field_mappings, measure.expression)
    if measure_mapping is None:
        raise ValueError("measure mapping was not validated")
    metric_alias = safe_alias(measure.label or measure.role or measure_mapping.field_name)
    aggregate = aggregate_function(measure.aggregate)
    limit = max(1, min(int(calculation.limit or 10), 100))
    select_lines = [f"    {alias}.{field.field_name} КАК {safe_alias(field.role or field.field_name)}" for field in group_fields]
    select_lines.append(f"    {aggregate}({alias}.{measure_mapping.field_name}) КАК {metric_alias}")
    group_by_lines = [f"    {alias}.{field.field_name}" for field in group_fields]
    where_lines: List[str] = []
    params: Dict[str, Any] = {}
    for item in calculation.filters:
        mapping = mapping_for_role_or_field(draft.field_mappings, item.role)
        if mapping is None:
            continue
        param_name = safe_alias(item.parameter or item.role)
        params[param_name] = None
        operator = filter_operator(item.operator)
        where_lines.append(f"    {alias}.{mapping.field_name} {operator} &{param_name}")
    query_parts = [
        f"ВЫБРАТЬ ПЕРВЫЕ {limit}",
        ",\n".join(select_lines),
        "ИЗ",
        f"    {query_source_name(source.object_name)} КАК {alias}",
    ]
    if where_lines:
        query_parts.extend(["ГДЕ", "\n    И ".join(line.strip() for line in where_lines)])
    query_parts.extend(["СГРУППИРОВАТЬ ПО", ",\n".join(group_by_lines)])
    sort = calculation.sort[0] if calculation.sort else None
    sort_field = safe_alias(sort.field or sort.role) if sort else metric_alias
    direction = "ВОЗР" if sort and sort.direction.lower() in {"asc", "возр", "ascending"} else "УБЫВ"
    query_parts.extend(["УПОРЯДОЧИТЬ ПО", f"    {sort_field} {direction}"])
    return "\n".join(query_parts), params, limit


def metadata_objects_from_draft(
    draft: HumanSkillDraft,
    *,
    metadata_lookup: Optional[Callable[[str], MetadataObject]] = None,
) -> List[MetadataObject]:
    result: List[MetadataObject] = []
    for source in draft.data_sources:
        metadata = lookup_metadata_object(source.object_name, metadata_lookup=metadata_lookup)
        if metadata is not None:
            result.append(metadata)
            continue
        fields = [mapping.field_name for mapping in draft.field_mappings if mapping.source_alias == source.alias]
        details = {
            mapping.field_name: {
                "name": mapping.field_name,
                "Имя": mapping.field_name,
                "_category": "field",
                "_source": "metadata_xml" if mapping.confirmed else "onboarding_index",
                "_trust": "verified" if mapping.confirmed else "hint",
            }
            for mapping in draft.field_mappings
            if mapping.source_alias == source.alias
        }
        result.append(
            MetadataObject(
                full_name=normalize_metadata_source(source.object_name),
                synonym="",
                fields=fields,
                field_details=details,
                raw={
                    "_source": "metadata_xml" if source.trust == "verified" else "onboarding_index",
                    "_trust": source.trust,
                },
            )
        )
    return result


def lookup_metadata_object(
    source_name: str,
    *,
    metadata_lookup: Optional[Callable[[str], MetadataObject]],
) -> Optional[MetadataObject]:
    if metadata_lookup is None:
        return None
    try:
        metadata = metadata_lookup(normalize_metadata_source(source_name))
    except Exception:
        return None
    if metadata.raw or metadata.fields or metadata.synonym:
        return metadata
    return None


def source_by_alias(draft: HumanSkillDraft, alias: str):
    for source in draft.data_sources:
        if source.alias == alias:
            return source
    return None


def mapping_for_role_or_field(mappings: List[FieldMapping], value: str) -> Optional[FieldMapping]:
    for mapping in mappings:
        if mapping.role == value or mapping.field_name == value:
            return mapping
    return None


def query_source_name(source_name: str) -> str:
    stripped = source_name.strip()
    if re.search(r"\.(ОстаткиИОбороты|Остатки|Обороты)$", stripped):
        return stripped + "()"
    return stripped


def normalize_metadata_source(source_name: str) -> str:
    compact = source_name.strip()
    compact = re.sub(r"\.(ОстаткиИОбороты|Остатки|Обороты)\s*(?:\(.*\))?$", "", compact)
    return compact


def aggregate_function(value: str) -> str:
    normalized = value.lower()
    return {
        "sum": "СУММА",
        "сумма": "СУММА",
        "count": "КОЛИЧЕСТВО",
        "количество": "КОЛИЧЕСТВО",
        "max": "МАКСИМУМ",
        "максимум": "МАКСИМУМ",
        "min": "МИНИМУМ",
        "минимум": "МИНИМУМ",
    }.get(normalized, "СУММА")


def filter_operator(value: str) -> str:
    normalized = value.lower()
    return {
        "equals": "=",
        "=": "=",
        "not_equals": "<>",
        "<>": "<>",
        "in": "В",
        "contains": "ПОДОБНО",
        "like": "ПОДОБНО",
    }.get(normalized, "=")


def safe_alias(value: str) -> str:
    alias = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_]+", "_", str(value or "")).strip("_")
    if not alias:
        return "Значение"
    if alias[0].isdigit():
        return "Поле_" + alias
    return alias

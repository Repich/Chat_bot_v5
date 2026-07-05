from __future__ import annotations

from typing import Any, Dict, List, Optional

from wiicon5.conversation.context import ConversationContext
from wiicon5.models import SemanticFilter, SkillContract
from wiicon5.query.query_builder import QueryBuildError, QueryBuilder
from wiicon5.query.query_draft import QueryDraft


class LearnedQueryBuilder(QueryBuilder):
    def build(self, skill: SkillContract, inputs: Dict[str, Any], context: ConversationContext) -> QueryDraft:
        spec = skill.implementation
        expected_fingerprint = str(spec.get("config_fingerprint") or "")
        actual_fingerprint = context.config_fingerprint or ""
        if expected_fingerprint and actual_fingerprint and expected_fingerprint != actual_fingerprint:
            raise QueryBuildError(
                f"Learned skill {skill.skill_id} was created for config {expected_fingerprint}, "
                f"current config is {actual_fingerprint}."
            )
        kind = str(spec.get("kind") or "")
        if kind == "period_metric_aggregate":
            return build_period_metric_aggregate(skill, inputs)
        if kind == "fixed_query":
            query = str(spec.get("query") or "").strip()
            if not query:
                raise QueryBuildError(f"Learned skill {skill.skill_id} has no query.")
            params = dict(spec.get("params") or {})
            for key in list(params.keys()):
                if key in inputs:
                    params[key] = inputs[key]
            return QueryDraft(
                query=query,
                params=params,
                limit=int(spec.get("limit") or inputs.get("limit") or 100),
                metadata_dependencies=[str(item) for item in spec.get("metadata_dependencies", []) or []],
                reasoning=f"Built from learned fixed query skill {skill.skill_id}.",
            )
        raise QueryBuildError(f"Unsupported learned query kind for {skill.skill_id}: {kind}")


def build_period_metric_aggregate(skill: SkillContract, inputs: Dict[str, Any]) -> QueryDraft:
    spec = skill.implementation
    source = required_spec(spec, "source")
    alias = str(spec.get("alias") or "Источник")
    period_field = required_spec(spec, "period_field")
    metrics = spec.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        raise QueryBuildError(f"Learned skill {skill.skill_id} must define metrics.")

    filters = semantic_filters_from_inputs(inputs)
    year = year_from_filters(filters)
    granularity = period_granularity_from_filters(filters)
    params: Dict[str, Any] = {}

    select_lines: List[str] = []
    group_lines: List[str] = []
    if granularity == "year":
        period_expr = f"ГОД({alias}.{period_field})"
        select_lines.append(f"    {period_expr} КАК Год")
        group_lines.append(f"    {period_expr}")

    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        label = str(metric.get("label") or "").strip()
        expression = str(metric.get("expression") or "").strip()
        if not label or not expression:
            continue
        select_lines.append(f"    {expression} КАК {label}")
    if not select_lines:
        raise QueryBuildError(f"Learned skill {skill.skill_id} has no selectable metrics.")

    query_lines = [
        "ВЫБРАТЬ",
        *comma_terminated(select_lines),
        "ИЗ",
        f"    {source} КАК {alias}",
    ]
    where_lines: List[str] = []
    if year is not None:
        params["НачПериода"] = f"{year}-01-01T00:00:00"
        params["КонПериода"] = f"{year}-12-31T23:59:59"
        where_lines.append(f"{alias}.{period_field} МЕЖДУ &НачПериода И &КонПериода")
    if bool(spec.get("activity_filter")):
        activity_field = str(spec.get("activity_field") or "Активность")
        where_lines.append(f"{alias}.{activity_field}")
    if where_lines:
        query_lines.append("ГДЕ")
        query_lines.extend(prefixed_conditions(where_lines))
    if group_lines:
        query_lines.append("СГРУППИРОВАТЬ ПО")
        query_lines.extend(comma_terminated(group_lines))
        query_lines.append("УПОРЯДОЧИТЬ ПО")
        query_lines.append("    Год")

    return QueryDraft(
        query="\n".join(query_lines),
        params=params,
        limit=int(inputs.get("limit") or spec.get("limit") or 100),
        metadata_dependencies=[source],
        reasoning=f"Built from learned period metric aggregate skill {skill.skill_id}.",
    )


def semantic_filters_from_inputs(inputs: Dict[str, Any]) -> List[SemanticFilter]:
    result: List[SemanticFilter] = []
    for item in inputs.get("filters", []) or []:
        if isinstance(item, SemanticFilter):
            result.append(item)
        elif isinstance(item, dict):
            result.append(SemanticFilter.from_dict(item))
    return result


def year_from_filters(filters: List[SemanticFilter]) -> Optional[int]:
    for item in filters:
        if item.semantic_field in {"year", "год"}:
            try:
                return int(item.value)
            except (TypeError, ValueError):
                return None
    return None


def period_granularity_from_filters(filters: List[SemanticFilter]) -> str:
    for item in filters:
        if item.semantic_field in {"period_granularity", "group_by", "granularity"}:
            value = str(item.value or item.raw_user_text or "").lower()
            if "год" in value or "year" in value:
                return "year"
    if any("по год" in item.raw_user_text.lower() for item in filters):
        return "year"
    return ""


def required_spec(spec: Dict[str, Any], key: str) -> str:
    value = str(spec.get(key) or "").strip()
    if not value:
        raise QueryBuildError(f"Learned query spec missing required key: {key}")
    return value


def comma_terminated(lines: List[str]) -> List[str]:
    result = []
    for index, line in enumerate(lines):
        suffix = "," if index < len(lines) - 1 else ""
        result.append(f"{line}{suffix}")
    return result


def prefixed_conditions(lines: List[str]) -> List[str]:
    result = []
    for index, line in enumerate(lines):
        prefix = "    " if index == 0 else "    И "
        result.append(prefix + line)
    return result

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from wiicon5.conversation.context import ConversationContext
from wiicon5.models import SemanticFilter, SkillContract
from wiicon5.query.parameterized_lookup import build_parameterized_lookup_params, missing_required_filter_roles
from wiicon5.query.query_builder import QueryBuildError, QueryBuilder
from wiicon5.query.query_draft import QueryDraft


class LearnedQueryBuilder(QueryBuilder):
    def build(self, skill: SkillContract, inputs: Dict[str, Any], context: ConversationContext) -> QueryDraft:
        spec = skill.implementation
        kind = str(spec.get("kind") or "")
        expected_fingerprint = str(spec.get("config_fingerprint") or "")
        actual_fingerprint = context.config_fingerprint or ""
        fingerprint_required = bool(expected_fingerprint) or kind == "semantic_query_template"
        if fingerprint_required and actual_fingerprint.strip().lower() in {"", "auto", "computed", "unknown", "unresolved"}:
            raise QueryBuildError(
                f"Learned skill {skill.skill_id} requires config fingerprint {expected_fingerprint or '<resolved>'}, "
                "but the current configuration fingerprint is unresolved."
            )
        if kind == "semantic_query_template" and not expected_fingerprint:
            raise QueryBuildError(f"Learned skill {skill.skill_id} has no configuration fingerprint.")
        if expected_fingerprint:
            if not actual_fingerprint:
                raise QueryBuildError(
                    f"Learned skill {skill.skill_id} requires config fingerprint {expected_fingerprint}, "
                    "but current config fingerprint is unknown."
                )
            if expected_fingerprint != actual_fingerprint:
                raise QueryBuildError(
                    f"Learned skill {skill.skill_id} was created for config {expected_fingerprint}, "
                    f"current config is {actual_fingerprint}."
                )
        if kind == "semantic_query_template":
            return build_semantic_query_template(skill, inputs)
        if kind == "period_metric_aggregate":
            return build_period_metric_aggregate(skill, inputs, context)
        if kind == "parameterized_lookup_query":
            return build_parameterized_lookup_query(skill, inputs)
        if kind == "fixed_query":
            query = str(spec.get("query") or "").strip()
            if not query:
                raise QueryBuildError(f"Learned skill {skill.skill_id} has no query.")
            params = dict(spec.get("params") or {})
            for key in list(params.keys()):
                if key in inputs:
                    params[key] = inputs[key]
            params = apply_semantic_period_params(params, inputs)
            return QueryDraft(
                query=query,
                params=params,
                limit=int(spec.get("limit") or inputs.get("limit") or 100),
                metadata_dependencies=[str(item) for item in spec.get("metadata_dependencies", []) or []],
                reasoning=f"Built from learned fixed query skill {skill.skill_id}.",
            )
        raise QueryBuildError(f"Unsupported learned query kind for {skill.skill_id}: {kind}")


def build_parameterized_lookup_query(skill: SkillContract, inputs: Dict[str, Any]) -> QueryDraft:
    spec = skill.implementation
    query = str(spec.get("query") or "").strip()
    if not query:
        raise QueryBuildError(f"Learned skill {skill.skill_id} has no query.")
    missing_roles = missing_required_filter_roles(spec, inputs)
    if missing_roles:
        raise QueryBuildError(
            f"Learned skill {skill.skill_id} requires semantic filters: {', '.join(missing_roles)}."
        )
    params = build_parameterized_lookup_params(spec, inputs)
    return QueryDraft(
        query=query,
        params=params,
        limit=int(inputs.get("limit") or spec.get("limit") or 100),
        metadata_dependencies=[str(item) for item in spec.get("metadata_dependencies", []) or []],
        reasoning=f"Built from learned parameterized lookup query skill {skill.skill_id}.",
    )


def build_semantic_query_template(skill: SkillContract, inputs: Dict[str, Any]) -> QueryDraft:
    spec = skill.implementation
    query = str(spec.get("query") or "").strip()
    if not query:
        raise QueryBuildError(f"Learned skill {skill.skill_id} has no query template.")
    missing_roles = missing_required_filter_roles(spec, inputs)
    if missing_roles:
        raise QueryBuildError(
            f"Learned skill {skill.skill_id} requires semantic filters: {', '.join(missing_roles)}."
        )
    params = build_parameterized_lookup_params(spec, inputs)
    return QueryDraft(
        query=query,
        params=params,
        limit=int(inputs.get("limit") or spec.get("limit") or 100),
        metadata_dependencies=[str(item) for item in spec.get("metadata_dependencies", []) or []],
        reasoning=f"Built from learned semantic query template {skill.skill_id}.",
    )


def build_period_metric_aggregate(skill: SkillContract, inputs: Dict[str, Any], context: ConversationContext) -> QueryDraft:
    spec = skill.implementation
    source = required_spec(spec, "source")
    alias = str(spec.get("alias") or "Источник")
    period_field = required_spec(spec, "period_field")
    metrics = spec.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        raise QueryBuildError(f"Learned skill {skill.skill_id} must define metrics.")
    compatibility_error = learned_period_metric_compatibility_error(
        skill=skill,
        source=source,
        metrics=metrics,
        context=context,
    )
    if compatibility_error:
        raise QueryBuildError(compatibility_error)

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


def learned_period_metric_compatibility_error(
    *,
    skill: SkillContract,
    source: str,
    metrics: List[Any],
    context: ConversationContext,
) -> str:
    question = latest_user_question(context).lower()
    metric_text = " ".join(
        str(metric.get("label", "")) + " " + str(metric.get("expression", ""))
        for metric in metrics
        if isinstance(metric, dict)
    ).lower()
    terms_text = " ".join(str(item) for item in skill.implementation.get("metric_terms", []) or []).lower()
    combined = " ".join([question, terms_text])
    if re.search(r"\bпервые\s+\d+\b", metric_text):
        return (
            f"Learned skill {skill.skill_id} is not a safe period_metric_aggregate: "
            "metric expression contains ПЕРВЫЕ. Rebuild it from the full query."
        )
    if "средн" in combined and any(marker in combined for marker in ["реализац", "заказ", "поступлен", "документ"]):
        if source.startswith("РегистрНакопления.") and "среднее(" in metric_text:
            if not any(marker in metric_text for marker in ["регистратор", ".документ", ".ссылка"]):
                return (
                    f"Learned skill {skill.skill_id} averages raw register rows for a document-level question. "
                    "Rebuild the query at document grain."
                )
    if top_sold_product_text(combined):
        explicit_money = any(marker in combined for marker in ["по выруч", "по сумм", "по стоимости", "деньг", "руб"])
        quantity_metric = any(marker in metric_text for marker in ["количество", "quantity", "count("])
        money_metric = any(marker in metric_text for marker in ["выруч", "суммапродаж", "суммавыруч", "сумма"])
        if money_metric and not quantity_metric and not explicit_money:
            return (
                f"Learned skill {skill.skill_id} ranks sold products by money, but the question implies quantity. "
                "Rebuild the query or ask for clarification."
            )
    return ""


def latest_user_question(context: ConversationContext) -> str:
    for message in reversed(context.messages):
        if message.role == "user":
            return message.content
    return ""


def top_sold_product_text(text: str) -> bool:
    return (
        any(marker in text for marker in ["сам", "больше всего", "наибольш", "топ", "top"])
        and any(marker in text for marker in ["продаваем", "продаж", "купил", "брали"])
        and any(marker in text for marker in ["товар", "номенклатур", "product"])
    )


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


def apply_semantic_period_params(params: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
    filters = semantic_filters_from_inputs(inputs)
    year = year_from_filters(filters)
    if year is None:
        return params
    result = dict(params)
    start_keys = [key for key in result if key.lower() in {"начпериода", "начало", "датаначала", "начальнаядата"}]
    end_keys = [key for key in result if key.lower() in {"конпериода", "конец", "датаконца", "конечнаядата"}]
    for key in start_keys:
        result[key] = f"{year}-01-01T00:00:00"
    for key in end_keys:
        result[key] = f"{year}-12-31T23:59:59"
    return result


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

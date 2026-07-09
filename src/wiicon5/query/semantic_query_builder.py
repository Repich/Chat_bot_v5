from __future__ import annotations

import re
from typing import Any, Dict, List

from wiicon5.conversation.context import ConversationContext
from wiicon5.knowledge.bindings import BindingResolver
from wiicon5.models import SemanticFilter, SkillBinding, SkillContract
from wiicon5.query.query_builder import QueryBuildError, QueryBuilder
from wiicon5.query.query_draft import QueryDraft
from wiicon5.semantic_roles import roles_match


class SemanticQueryBuilder(QueryBuilder):
    def __init__(self, binding_resolver: BindingResolver) -> None:
        self.binding_resolver = binding_resolver

    def build(self, skill: SkillContract, inputs: Dict[str, Any], context: ConversationContext) -> QueryDraft:
        binding = self.binding_resolver.resolve(skill, context)
        if not skill.outputs:
            raise QueryBuildError(f"Skill {skill.skill_id} has no outputs.")
        output_type = skill.outputs[0].type
        if output_type.endswith("RefList"):
            return build_entity_list_query(skill=skill, binding=binding, inputs=inputs)
        if output_type == "DocumentCountByPeriodTable":
            return build_document_count_by_period_query(skill=skill, binding=binding, inputs=inputs)
        if output_type.endswith("Table"):
            return build_measure_table_query(skill=skill, binding=binding, inputs=inputs)
        raise QueryBuildError(f"Unsupported semantic output type: {output_type}")


def build_entity_list_query(*, skill: SkillContract, binding: SkillBinding, inputs: Dict[str, Any]) -> QueryDraft:
    source = source_expression(binding)
    alias = alias_for_binding(binding)
    params: Dict[str, Any] = {}
    ref_field = binding.fields.get("ref", "Ссылка")
    name_field = required_field(binding, "name")
    select_lines = [
        f"    {alias}.{ref_field} КАК Ссылка",
        f"    {alias}.{name_field} КАК Наименование",
    ]
    filters = semantic_filters_from_inputs(inputs)
    where_lines = [compile_semantic_filter(alias, binding, item, params) for item in filters]
    query_lines = [f"ВЫБРАТЬ ПЕРВЫЕ {limit_from_inputs(inputs)}", *comma_terminated(select_lines), "ИЗ", f"    {source} КАК {alias}"]
    if where_lines:
        query_lines.append("ГДЕ")
        query_lines.extend(prefixed_conditions(where_lines))
    return QueryDraft(
        query="\n".join(query_lines),
        limit=limit_from_inputs(inputs),
        params=params,
        metadata_dependencies=[base_object_full_name(binding)],
        reasoning=f"Built from binding for {skill.skill_id}, not from hardcoded 1C names.",
    )


def build_measure_table_query(*, skill: SkillContract, binding: SkillBinding, inputs: Dict[str, Any]) -> QueryDraft:
    source = source_expression(binding)
    alias = alias_for_binding(binding)
    params: Dict[str, Any] = {}
    product_field = required_field(binding, "product")
    warehouse_field = required_field(binding, "warehouse")
    quantity_field = required_field(binding, "quantity")
    warehouse_name_expr = binding.fields.get("warehouse_name", f"{warehouse_field}.Наименование")
    select_lines = []
    if not input_has_value(inputs, "product") or column_required(inputs, "product", "номенклатура", "товар"):
        select_lines.append(f"    {alias}.{product_field} КАК Номенклатура")
    select_lines.extend(
        [
            f"    {alias}.{warehouse_name_expr} КАК Склад",
            f"    {alias}.{quantity_field} КАК Остаток",
        ]
    )
    where_lines = []
    if input_has_value(inputs, "product"):
        where_lines.append(compile_reference_input_filter(alias, product_field, inputs["product"], params, "product"))
    if input_has_value(inputs, "warehouses"):
        where_lines.append(f"{alias}.{warehouse_field} В {render_1c_value(inputs['warehouses'], params, 'warehouses')}")
    filters = semantic_filters_from_inputs(inputs)
    where_lines.extend(compile_semantic_filter(alias, binding, item, params) for item in filters)
    query_lines = [f"ВЫБРАТЬ ПЕРВЫЕ {limit_from_inputs(inputs)}", *comma_terminated(select_lines), "ИЗ", f"    {source} КАК {alias}"]
    if where_lines:
        query_lines.append("ГДЕ")
        query_lines.extend(prefixed_conditions(where_lines))
    return QueryDraft(
        query="\n".join(query_lines),
        limit=limit_from_inputs(inputs),
        params=params,
        metadata_dependencies=[base_object_full_name(binding)],
        reasoning=f"Built from binding for {skill.skill_id}, not from hardcoded 1C names.",
    )


def build_document_count_by_period_query(*, skill: SkillContract, binding: SkillBinding, inputs: Dict[str, Any]) -> QueryDraft:
    source = source_expression(binding)
    alias = alias_for_binding(binding)
    params: Dict[str, Any] = {}
    ref_field = binding.fields.get("ref", "Ссылка")
    date_field = required_field(binding, "date")
    period_expr = period_expression(alias, date_field, str(inputs.get("period_granularity") or "day"))
    select_lines = [
        f"    {period_expr} КАК День",
        f"    КОЛИЧЕСТВО({alias}.{ref_field}) КАК Количество",
    ]
    filters = semantic_filters_from_inputs(inputs)
    where_lines = [compile_semantic_filter(alias, binding, item, params) for item in filters]
    query_lines = [
        f"ВЫБРАТЬ ПЕРВЫЕ {limit_from_inputs(inputs)}",
        *comma_terminated(select_lines),
        "ИЗ",
        f"    {source} КАК {alias}",
    ]
    if where_lines:
        query_lines.append("ГДЕ")
        query_lines.extend(prefixed_conditions(where_lines))
    query_lines.extend(
        [
            "СГРУППИРОВАТЬ ПО",
            f"    {period_expr}",
            "УПОРЯДОЧИТЬ ПО",
            "    День",
        ]
    )
    return QueryDraft(
        query="\n".join(query_lines),
        limit=limit_from_inputs(inputs),
        params=params,
        metadata_dependencies=[base_object_full_name(binding)],
        reasoning=f"Built document count by period from binding for {skill.skill_id}.",
    )


def source_expression(binding: SkillBinding) -> str:
    data = binding.one_c_object
    full_name = base_object_full_name(binding)
    if not full_name:
        object_type = one_c_object_type(data.get("type", ""))
        name = data.get("name")
        if not object_type or not name:
            raise QueryBuildError("Binding one_c_object must contain full_name or type/name.")
        full_name = f"{object_type}.{name}"
    virtual_table = data.get("virtual_table")
    if virtual_table:
        return f"{full_name}.{virtual_table}()"
    table_part = data.get("table_part")
    if table_part:
        return f"{full_name}.{table_part}"
    return full_name


def base_object_full_name(binding: SkillBinding) -> str:
    return binding.one_c_object.get("full_name") or binding.one_c_object.get("fullname") or ""


def one_c_object_type(value: str) -> str:
    mapping = {
        "catalog": "Справочник",
        "справочник": "Справочник",
        "document": "Документ",
        "документ": "Документ",
        "accumulationregister": "РегистрНакопления",
        "accumulation_register": "РегистрНакопления",
        "регистрнакопления": "РегистрНакопления",
    }
    return mapping.get(value.replace(" ", "").lower(), value)


def alias_for_binding(binding: SkillBinding) -> str:
    alias = binding.one_c_object.get("alias")
    if alias:
        return sanitize_alias(alias)
    source = source_expression(binding)
    base = source.split(".")[-1].replace("()", "")
    return sanitize_alias(base or "Источник")


def sanitize_alias(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-zА-Яа-яЁё0-9_]", "", value)
    return cleaned or "Источник"


def required_field(binding: SkillBinding, semantic_field: str) -> str:
    field = binding.fields.get(semantic_field)
    if not field:
        raise QueryBuildError(f"Binding for {binding.skill_id} does not define semantic field: {semantic_field}")
    return field


def period_expression(alias: str, date_field: str, granularity: str) -> str:
    normalized = granularity.strip().lower()
    mapping = {
        "day": "ДЕНЬ",
        "день": "ДЕНЬ",
        "days": "ДЕНЬ",
        "по дням": "ДЕНЬ",
        "month": "МЕСЯЦ",
        "месяц": "МЕСЯЦ",
        "months": "МЕСЯЦ",
        "по месяцам": "МЕСЯЦ",
        "year": "ГОД",
        "год": "ГОД",
        "years": "ГОД",
        "по годам": "ГОД",
    }
    period = mapping.get(normalized)
    if period is None:
        raise QueryBuildError(f"Unsupported period granularity: {granularity}")
    return f"НАЧАЛОПЕРИОДА({alias}.{date_field}, {period})"


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


def compile_semantic_filter(alias: str, binding: SkillBinding, item: SemanticFilter, params: Dict[str, Any]) -> str:
    field = binding.fields.get(item.semantic_field)
    if not field and roles_match(binding.semantic_role, item.semantic_field):
        return compile_generic_entity_filter(alias, binding, item, params)
    if not field:
        field = required_field(binding, item.semantic_field)
    left = f"{alias}.{field}"
    operator = item.operator.lower()
    if item.semantic_field == "product" and operator in {"equals", "eq", "=", "равно", "contains", "substring"}:
        text_value = reference_text_search_value(item.value)
        if text_value:
            return compile_reference_text_search(alias, field, item.semantic_field, text_value, params)
    if operator in {"equals", "eq", "=", "равно"}:
        return f"{left} = {render_1c_value(item.value, params, item.semantic_field)}"
    if operator in {"contains", "substring"}:
        return f"{left} ПОДОБНО \"%\" + {render_1c_value(item.value, params, item.semantic_field)} + \"%\""
    if operator in {"starts_with", "prefix"}:
        return f"{left} ПОДОБНО {render_1c_value(item.value, params, item.semantic_field)} + \"%\""
    if operator in {"in", "in_list"}:
        return f"{left} В {render_1c_value(item.value, params, item.semantic_field)}"
    raise QueryBuildError(f"Unsupported semantic filter operator: {item.operator}")


def compile_reference_input_filter(
    alias: str,
    field: str,
    value: Any,
    params: Dict[str, Any],
    param_base: str,
) -> str:
    text_value = reference_text_search_value(value)
    if text_value:
        return compile_reference_text_search(alias, field, param_base, text_value, params)
    if isinstance(value, list):
        return f"{alias}.{field} В {render_1c_value(value, params, param_base)}"
    return f"{alias}.{field} = {render_1c_value(value, params, param_base)}"


def compile_reference_text_search(
    alias: str,
    field: str,
    param_base: str,
    value: str,
    params: Dict[str, Any],
) -> str:
    left = f"{alias}.{field}" if generic_field_is_text(field) else f"{alias}.{field}.Наименование"
    parameter_name = add_param(params, param_base, build_text_search_value(value))
    return f"{left} ПОДОБНО \"%\" + &{parameter_name} + \"%\""


def reference_text_search_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        if value.get("_objectRef") or value.get("Ссылка") or value.get("ref") or value.get("reference"):
            return ""
        presentation = value.get("Представление") or value.get("name") or value.get("Наименование")
        if isinstance(presentation, str):
            return presentation.strip()
    return ""


def build_text_search_value(value: str) -> str:
    normalized = " ".join(value.split()).strip()
    if not normalized:
        return value
    tokens = [token for token in re.split(r"[^0-9A-Za-zА-Яа-яЁё]+", normalized.lower()) if token]
    if not tokens:
        return normalized
    result = [stem_ru_search_token(token) for token in tokens]
    return " ".join(token for token in result if token) or normalized


def stem_ru_search_token(token: str) -> str:
    if not re.search(r"[А-Яа-яЁё]", token):
        return token
    endings = [
        "иями",
        "ями",
        "ами",
        "ого",
        "ему",
        "ыми",
        "ими",
        "ая",
        "яя",
        "ое",
        "ее",
        "ые",
        "ие",
        "ый",
        "ий",
        "ой",
        "ую",
        "юю",
        "ом",
        "ем",
        "ам",
        "ям",
        "ах",
        "ях",
        "ов",
        "ев",
        "ок",
        "ки",
        "ка",
        "ку",
        "а",
        "я",
        "ы",
        "и",
        "у",
        "ю",
        "е",
    ]
    for ending in endings:
        if token.endswith(ending) and len(token) - len(ending) >= 4:
            return token[: -len(ending)]
    return token


def compile_generic_entity_filter(alias: str, binding: SkillBinding, item: SemanticFilter, params: Dict[str, Any]) -> str:
    candidate_fields = generic_entity_filter_fields(binding)
    if not candidate_fields:
        raise QueryBuildError(
            f"Binding for {binding.skill_id} does not define searchable fields for semantic role: {item.semantic_field}"
        )
    operator = item.operator.lower()
    value = normalize_generic_search_value(binding, item)
    conditions = []
    for field in candidate_fields:
        conditions.append(generic_entity_field_condition(alias, field, item.semantic_field, operator, value, params))
    if len(conditions) == 1:
        return conditions[0]
    return "(" + " ИЛИ ".join(conditions) + ")"


def generic_entity_field_condition(
    alias: str,
    field: str,
    semantic_field: str,
    operator: str,
    value: Any,
    params: Dict[str, Any],
) -> str:
    parameter_expr = "&" + add_param(params, f"{semantic_field}_{field}", value)
    if generic_field_is_text(field):
        left = f"{alias}.{field}"
        if operator in {"equals", "eq", "=", "равно", "contains", "substring"}:
            return f"{left} ПОДОБНО \"%\" + {parameter_expr} + \"%\""
        if operator in {"starts_with", "prefix"}:
            return f"{left} ПОДОБНО {parameter_expr} + \"%\""
    else:
        left = f"{alias}.{field}"
        if operator in {"equals", "eq", "=", "равно", "contains", "substring", "starts_with", "prefix"}:
            return f"{left} = {parameter_expr}"
    raise QueryBuildError(f"Unsupported semantic filter operator for generic entity lookup: {operator}")


def normalize_generic_search_value(binding: SkillBinding, item: SemanticFilter) -> Any:
    value = item.value
    if not isinstance(value, str):
        return value
    normalized = " ".join(value.split())
    if not normalized:
        return value
    stop_words = generic_entity_stop_words(binding.semantic_role, item.semantic_field)
    tokens = [token for token in re.split(r"\s+", normalized) if token]
    meaningful = [token for token in tokens if token.lower().strip(".,;:()[]{}\"'") not in stop_words]
    if meaningful:
        return " ".join(meaningful)
    return normalized


def generic_entity_stop_words(*roles: str) -> set[str]:
    normalized_roles = {str(role or "").strip().lower() for role in roles}
    result = set()
    if "warehouse" in normalized_roles:
        result.update(
            {
                "склад",
                "склада",
                "складе",
                "складов",
                "склады",
                "warehouse",
                "warehouses",
            }
        )
    if "product" in normalized_roles:
        result.update({"товар", "товара", "товары", "номенклатура", "номенклатуры", "product", "products"})
    return result


def generic_entity_filter_fields(binding: SkillBinding) -> List[str]:
    result = []
    for role in ["name", "warehouse_type", "city"]:
        field = binding.fields.get(role)
        if field and field not in result:
            result.append(field)
    for role, field in binding.fields.items():
        if role == "ref" or field in result:
            continue
        result.append(field)
    return result[:4]


def generic_field_is_text(field: str) -> bool:
    return field.endswith(".Наименование") or field in {"Наименование", "Название"}


def column_required(inputs: Dict[str, Any], *names: str) -> bool:
    requested = [str(item).strip().lower() for item in inputs.get("required_columns", []) or []]
    if not requested:
        return False
    for requested_column in requested:
        if any(name.lower() in requested_column for name in names):
            return True
    return False


def input_has_value(inputs: Dict[str, Any], name: str) -> bool:
    return name in inputs and inputs[name] not in (None, "", [])


def render_1c_value(value: Any, params: Dict[str, Any], param_base: str) -> str:
    if isinstance(value, list):
        if not value:
            parameter_name = add_param(params, f"{param_base}_empty", None)
            return f"(&{parameter_name})"
        parameter_refs = []
        for index, item in enumerate(value, start=1):
            parameter_refs.append("&" + add_param(params, f"{param_base}_{index}", normalize_param_value(item)))
        return "(" + ", ".join(parameter_refs) + ")"
    parameter_name = add_param(params, param_base, normalize_param_value(value))
    return f"&{parameter_name}"


def normalize_param_value(value: Any) -> Any:
    if isinstance(value, list):
        return [normalize_param_value(item) for item in value]
    if isinstance(value, dict):
        if value.get("_objectRef"):
            return dict(value)
        ref = value.get("Ссылка") or value.get("ref") or value.get("reference")
        if ref is not None:
            return normalize_param_value(ref)
        presentation = value.get("Представление") or value.get("name")
        if presentation is not None:
            return normalize_param_value(presentation)
        return dict(value)
    return value


def add_param(params: Dict[str, Any], base: str, value: Any) -> str:
    name = sanitize_param_name(base)
    if name not in params:
        params[name] = value
        return name
    index = 2
    while f"{name}_{index}" in params:
        index += 1
    final_name = f"{name}_{index}"
    params[final_name] = value
    return final_name


def sanitize_param_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_]", "_", value).strip("_")
    if not cleaned:
        return "param"
    if cleaned[0].isdigit():
        return f"p_{cleaned}"
    return cleaned


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


def prefixed_conditions(lines: List[str]) -> List[str]:
    result = []
    for index, line in enumerate(lines):
        prefix = "    " if index == 0 else "    И "
        result.append(prefix + line)
    return result

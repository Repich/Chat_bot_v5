from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from typing import Any, Dict, List, Mapping, Optional, Sequence

from wiicon5.intent.models import IntentResult
from wiicon5.models import SkillContract, SkillKind, SkillStatus
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.query.one_c_query_review import parse_sources
from wiicon5.query.parameterized_lookup import constraints_from_goal_payload, infer_parameter_bindings
from wiicon5.skills.semantic_contract import (
    SEMANTIC_CONTRACT_SCHEMA_VERSION,
    SemanticMeasure,
    SemanticRanking,
    SemanticSkillContract,
    contract_from_goal,
    normalize_subject_term,
    semantic_contract_compatibility,
    subject_terms,
    unique,
)
from wiicon5.types import TypeSystem


LEARNED_QUERY_SCHEMA_VERSION = 2


def semantic_query_template_spec(
    *,
    query: str,
    params: Mapping[str, Any],
    limit: int,
    intent: IntentResult,
    goal: Optional[GoalDecomposition],
    trace: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    normalized_query = query.strip()
    if not reusable_read_query(normalized_query):
        return None
    sources = query_source_objects(normalized_query)
    if not sources:
        return None
    constraints = constraints_from_goal_payload(goal)
    parameter_bindings = infer_parameter_bindings(dict(params), constraints)
    bound_roles = unique(str(item.get("semantic_field") or "") for item in parameter_bindings)
    output_columns = output_columns_from_trace(trace) or output_columns_from_query(normalized_query)
    requested_contract = contract_from_goal(intent, goal)
    fixed_values = {
        role: value
        for role, value in requested_contract.fixed_filter_values.items()
        if role not in bound_roles
    }
    contract = replace(
        requested_contract,
        schema_version=SEMANTIC_CONTRACT_SCHEMA_VERSION,
        required_filter_roles=unique([*requested_contract.required_filter_roles, *bound_roles]),
        optional_filter_roles=unique([*requested_contract.optional_filter_roles, *bound_roles]),
        fixed_filter_values=fixed_values,
        result_columns=unique([*requested_contract.result_columns, *output_columns]),
        source_objects=sources,
        match_mode=template_match_mode(requested_contract, parameter_bindings, params),
        original_question=requested_contract.original_question or intent.business_goal,
        confidence=max(requested_contract.confidence, 0.75),
    )
    observed = observed_query_contract(
        query=normalized_query,
        output_columns=output_columns,
        source_objects=sources,
        requested_contract=contract,
    )
    metadata_contract = metadata_dependency_contract_from_query(normalized_query)
    return {
        "schema_version": LEARNED_QUERY_SCHEMA_VERSION,
        "kind": "semantic_query_template",
        "query": normalized_query,
        "params": dict(params),
        "limit": int(limit or 100),
        "parameter_bindings": parameter_bindings,
        "supported_filter_roles": bound_roles,
        "output_columns": output_columns,
        "metadata_dependencies": sources,
        "metadata_dependency_contract": metadata_contract,
        "semantic_contract": contract.to_dict(),
        "observed_query_contract": observed.to_dict(),
    }


def skill_from_semantic_template(
    spec: Mapping[str, Any],
    *,
    intent: IntentResult,
    goal: Optional[GoalDecomposition],
) -> SkillContract:
    contract = SemanticSkillContract.from_dict(spec.get("semantic_contract") if isinstance(spec, Mapping) else {})
    output_type = output_type_from_goal(goal)
    skill_id = semantic_template_skill_id(spec, output_type=output_type)
    capabilities = unique(
        [
            "learned_query",
            "semantic_query_template",
            f"operation:{contract.operation}" if contract.operation else "",
            *(f"measure:{item.role}" for item in contract.measures if item.role),
            *(f"aggregation:{item.aggregation}" for item in contract.measures if item.aggregation),
            *(f"subject:{item}" for item in contract.subject_terms[:8]),
            f"produce:{output_type}",
        ]
    )
    description = semantic_template_description(contract, fallback=intent.business_goal)
    accepted_filter_roles = unique(
        [
            *contract.required_filter_roles,
            *contract.optional_filter_roles,
        ]
    )
    return SkillContract.from_dict(
        {
            "skill_id": skill_id,
            "version": "0.2.0",
            "kind": SkillKind.DATA.value,
            "status": SkillStatus.VERIFIED.value,
            "description": description,
            "capabilities": capabilities,
            "inputs": [
                {
                    "name": "filters",
                    "type": "SemanticFilterList",
                    "required": bool(contract.required_filter_roles),
                    "description": "Semantic filters accepted by the verified query template.",
                },
                {
                    "name": "limit",
                    "type": "Integer",
                    "required": False,
                    "description": "Maximum rows to return",
                    "default": int(spec.get("limit") or 100),
                },
            ],
            "outputs": [
                {
                    "name": "table",
                    "type": output_type,
                    "required": True,
                    "description": "Result of the learned semantic query template.",
                }
            ],
            "tags": unique(["learned", "semantic-template", contract.operation, *contract.subject_terms[:8]]),
            "semantic_role": semantic_role_from_contract(contract),
            "semantic_contract": contract.to_dict(),
            "supported_filter_roles": accepted_filter_roles,
            "implementation_strategy": "learned_query",
            "implementation": dict(spec),
        }
    )


def semantic_template_positive_check(
    *,
    intent: IntentResult,
    goal: Optional[GoalDecomposition],
    spec: Mapping[str, Any],
) -> Dict[str, Any]:
    requested = contract_from_goal(intent, goal)
    available = SemanticSkillContract.from_dict(spec.get("semantic_contract") if isinstance(spec, Mapping) else {})
    compatibility = semantic_contract_compatibility(requested, available)
    return {
        "name": "original_goal_contract_compatible",
        "ok": compatibility.compatible,
        "details": compatibility.to_dict(),
    }


def semantic_template_negative_checks(spec: Mapping[str, Any]) -> List[Dict[str, Any]]:
    available = SemanticSkillContract.from_dict(spec.get("semantic_contract") if isinstance(spec, Mapping) else {})
    checks: List[Dict[str, Any]] = []
    aggregations = {item.aggregation for item in available.measures if item.aggregation}
    alternatives = [item for item in ["sum", "avg", "count", "min", "max"] if item not in aggregations]
    if aggregations and alternatives:
        mutated = replace(
            available,
            measures=[
                replace(item, aggregation=alternatives[0]) if item.aggregation else item
                for item in available.measures
            ],
            original_question="semantic negative aggregation probe",
        )
        compatibility = semantic_contract_compatibility(mutated, available)
        checks.append(
            {
                "name": "reject_different_aggregation",
                "ok": not compatibility.compatible,
                "details": compatibility.to_dict(),
            }
        )
    if available.ranking.enabled:
        mutated = replace(available, operation="aggregate", ranking=SemanticRanking())
        compatibility = semantic_contract_compatibility(mutated, available)
        checks.append(
            {
                "name": "reject_missing_ranking",
                "ok": not compatibility.compatible,
                "details": compatibility.to_dict(),
            }
        )
    for role, value in available.fixed_filter_values.items():
        mutated_values = dict(available.fixed_filter_values)
        mutated_values[role] = value + " другое"
        mutated = replace(available, fixed_filter_values=mutated_values)
        compatibility = semantic_contract_compatibility(mutated, available)
        checks.append(
            {
                "name": f"reject_different_fixed_filter:{role}",
                "ok": not compatibility.compatible,
                "details": compatibility.to_dict(),
            }
        )
    return checks


def observed_query_contract(
    *,
    query: str,
    output_columns: Sequence[str],
    source_objects: Sequence[str],
    requested_contract: SemanticSkillContract,
) -> SemanticSkillContract:
    expressions = select_expressions(query)
    measures: List[SemanticMeasure] = []
    for expression, label in expressions:
        aggregation = aggregation_from_expression(expression)
        if not aggregation:
            continue
        role = normalize_subject_term(label) or normalize_subject_term(expression)
        measures.append(
            SemanticMeasure(
                role=role,
                aggregation=aggregation,
                result_column=label,
            )
        )
    ranking = ranking_from_query(query, expressions)
    operation = "rank" if ranking.enabled else "aggregate" if measures else "balance" if ".остатки(" in query.lower() else "list"
    return SemanticSkillContract(
        subject_terms=list(requested_contract.subject_terms),
        operation=operation,
        measures=measures,
        grain=group_by_expressions(query),
        dimensions=group_by_expressions(query),
        result_columns=list(output_columns),
        ranking=ranking,
        source_objects=list(source_objects),
        match_mode="exact",
        original_question=requested_contract.original_question,
        confidence=0.9 if expressions else 0.5,
    )


def output_type_from_goal(goal: Optional[GoalDecomposition]) -> str:
    type_system = TypeSystem()
    if goal is not None:
        for requirement in goal.required_artifacts:
            if requirement.type == "UserAnswer" or type_system.is_abstract_artifact_type(requirement.type):
                continue
            if requirement.type.endswith("Table"):
                return requirement.type
    return "LearnedQueryTable"


def template_match_mode(
    contract: SemanticSkillContract,
    parameter_bindings: Sequence[Mapping[str, Any]],
    params: Mapping[str, Any],
) -> str:
    specific_measures = [
        item
        for item in contract.measures
        if item.role and normalize_subject_term(item.role) not in {"value", "значен", "сумм", "количеств"}
    ]
    if (not contract.subject_terms and not specific_measures) or not contract.operation:
        return "exact"
    bound_roles = {str(item.get("semantic_field") or "") for item in parameter_bindings}
    bound_parameters = {str(item.get("parameter") or "") for item in parameter_bindings}
    if any(str(parameter) not in bound_parameters for parameter in params):
        return "exact"
    variable_roles = set(contract.required_filter_roles) - set(contract.fixed_filter_values)
    if variable_roles - bound_roles:
        return "exact"
    return "generalized"


def query_contract_consistency_issues(spec: Mapping[str, Any]) -> List[str]:
    requested = SemanticSkillContract.from_dict(spec.get("semantic_contract") if isinstance(spec, Mapping) else {})
    observed = SemanticSkillContract.from_dict(spec.get("observed_query_contract") if isinstance(spec, Mapping) else {})
    issues: List[str] = []
    requested_aggregations = {item.aggregation for item in requested.measures if item.aggregation}
    observed_aggregations = {item.aggregation for item in observed.measures if item.aggregation}
    if requested_aggregations and not requested_aggregations.issubset(observed_aggregations):
        issues.append("query_aggregation_does_not_match_goal")
    if requested.ranking.enabled and not observed.ranking.enabled:
        issues.append("query_ranking_does_not_match_goal")
    if requested.ranking.enabled and observed.ranking.enabled:
        if requested.ranking.direction and requested.ranking.direction != observed.ranking.direction:
            issues.append("query_ranking_direction_does_not_match_goal")
        if requested.ranking.limit and requested.ranking.limit != observed.ranking.limit:
            issues.append("query_ranking_limit_does_not_match_goal")
        if requested.ranking.by_measure and observed.ranking.by_measure and not semantic_terms_match(
            requested.ranking.by_measure,
            observed.ranking.by_measure,
        ):
            issues.append("query_ranking_measure_does_not_match_goal")
    if requested.operation == "rank" and observed.operation != "rank":
        issues.append("query_operation_does_not_match_goal")
    return issues


def reusable_read_query(query: str) -> bool:
    normalized = " ".join(query.lower().split())
    return normalized.startswith("выбрать") and " из " in f" {normalized} " and "{{" not in query and "}}" not in query


def query_source_objects(query: str) -> List[str]:
    return unique(source.object_full_name for source in parse_sources(query) if source.object_full_name)


def metadata_dependency_contract_from_query(query: str) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for source in parse_sources(query):
        if not source.object_full_name:
            continue
        fields = unique(
            match.group(1)
            for match in re.finditer(
                rf"\b{re.escape(source.alias)}\.([A-Za-zА-Яа-яЁё0-9_]+)",
                query,
                flags=re.IGNORECASE,
            )
        )
        result.append(
            {
                "object": source.object_full_name,
                "required_fields": {field: "unknown" for field in fields},
                "virtual_table": source.virtual_table or None,
                "field_roles": {},
            }
        )
    return result


def output_columns_from_trace(trace: Mapping[str, Any]) -> List[str]:
    final_artifact = trace.get("final_artifact") if isinstance(trace.get("final_artifact"), Mapping) else {}
    value = final_artifact.get("value") if isinstance(final_artifact, Mapping) else {}
    if isinstance(value, Mapping) and isinstance(value.get("columns"), list):
        return unique(str(item) for item in value.get("columns", []) or [])
    for step in reversed(trace.get("successful_steps", []) or []):
        if isinstance(step, Mapping) and isinstance(step.get("columns"), list):
            return unique(str(item) for item in step.get("columns", []) or [])
    return []


def output_columns_from_query(query: str) -> List[str]:
    return unique(label for _, label in select_expressions(query) if label)


def select_expressions(query: str) -> List[tuple[str, str]]:
    match = re.search(r"\bВЫБРАТЬ\s+(?:РАЗЛИЧНЫЕ\s+)?(?:ПЕРВЫЕ\s+\d+\s+)?(?P<select>.*?)\s+\bИЗ\b", query, flags=re.IGNORECASE | re.DOTALL)
    if match is None:
        return []
    result: List[tuple[str, str]] = []
    for item in split_top_level(match.group("select")):
        alias_match = re.search(r"(?P<expression>.+?)\s+КАК\s+(?P<label>[A-Za-zА-Яа-яЁё0-9_]+)\s*$", item, flags=re.IGNORECASE | re.DOTALL)
        if alias_match is None:
            continue
        result.append((alias_match.group("expression").strip(), alias_match.group("label").strip()))
    return result


def aggregation_from_expression(expression: str) -> str:
    normalized = expression.lower()
    for aggregation, markers in [
        ("avg", ["среднее(", "average(", "avg("]),
        ("count", ["количество(", "count("]),
        ("sum", ["сумма(", "sum("]),
        ("min", ["минимум(", "min("]),
        ("max", ["максимум(", "max("]),
    ]:
        if any(marker in normalized for marker in markers):
            return aggregation
    return ""


def ranking_from_query(query: str, expressions: Sequence[tuple[str, str]]) -> SemanticRanking:
    limit_match = re.search(r"\bВЫБРАТЬ\s+(?:РАЗЛИЧНЫЕ\s+)?ПЕРВЫЕ\s+(\d+)", query, flags=re.IGNORECASE)
    order_match = re.search(r"\bУПОРЯДОЧИТЬ\s+ПО\s+(.+?)(?:\bИТОГИ\b|$)", query, flags=re.IGNORECASE | re.DOTALL)
    if limit_match is None or order_match is None:
        return SemanticRanking()
    order_text = order_match.group(1).strip()
    direction = "desc" if "УБЫВ" in order_text.upper() else "asc"
    by_measure = ""
    for _, label in expressions:
        if label.lower() in order_text.lower():
            by_measure = normalize_subject_term(label)
            break
    return SemanticRanking(enabled=True, direction=direction, limit=int(limit_match.group(1)), by_measure=by_measure)


def group_by_expressions(query: str) -> List[str]:
    match = re.search(
        r"\bСГРУППИРОВАТЬ\s+ПО\s+(?P<group>.*?)(?:\bУПОРЯДОЧИТЬ\s+ПО\b|\bИМЕЮЩИЕ\b|$)",
        query,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return []
    return unique(normalize_subject_term(item) for item in split_top_level(match.group("group")))


def split_top_level(text: str) -> List[str]:
    result: List[str] = []
    current: List[str] = []
    depth = 0
    in_string = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            if in_string and index + 1 < len(text) and text[index + 1] == '"':
                current.extend([char, text[index + 1]])
                index += 2
                continue
            in_string = not in_string
        elif not in_string:
            if char == "(":
                depth += 1
            elif char == ")" and depth > 0:
                depth -= 1
            elif char == "," and depth == 0:
                item = "".join(current).strip()
                if item:
                    result.append(item)
                current = []
                index += 1
                continue
        current.append(char)
        index += 1
    tail = "".join(current).strip()
    if tail:
        result.append(tail)
    return result


def semantic_template_skill_id(spec: Mapping[str, Any], *, output_type: str) -> str:
    contract = SemanticSkillContract.from_dict(spec.get("semantic_contract") if isinstance(spec, Mapping) else {})
    contract_payload = contract.to_dict()
    contract_payload.pop("original_question", None)
    contract_payload.pop("confidence", None)
    bound_params = {str(item.get("parameter") or "") for item in spec.get("parameter_bindings", []) or [] if isinstance(item, Mapping)}
    fixed_params = {key: value for key, value in (spec.get("params", {}) or {}).items() if key not in bound_params}
    payload = {
        "schema_version": LEARNED_QUERY_SCHEMA_VERSION,
        "output_type": output_type,
        "query": " ".join(str(spec.get("query") or "").split()),
        "contract": contract_payload,
        "bindings": [
            {
                "semantic_field": item.get("semantic_field"),
                "parameter": item.get("parameter"),
                "transform": item.get("transform"),
            }
            for item in spec.get("parameter_bindings", []) or []
            if isinstance(item, Mapping)
        ],
        "fixed_params": fixed_params,
    }
    digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
    return f"learned_semantic_{digest}"


def semantic_template_description(contract: SemanticSkillContract, *, fallback: str) -> str:
    operation_labels = {
        "aggregate": "Агрегирует",
        "balance": "Получает остатки",
        "list": "Получает список",
        "lookup": "Ищет данные",
        "rank": "Строит рейтинг",
    }
    operation = operation_labels.get(contract.operation, "Получает данные")
    subjects = ", ".join(contract.subject_terms[:4])
    measures = ", ".join(
        " ".join(item for item in [measure.aggregation, measure.role] if item)
        for measure in contract.measures
    )
    detail = "; ".join(item for item in [subjects, measures] if item)
    return f"{operation}: {detail}." if detail else fallback


def semantic_role_from_contract(contract: SemanticSkillContract) -> str:
    subject = contract.subject_terms[0] if contract.subject_terms else "data"
    return "_".join(item for item in [subject, contract.operation] if item)

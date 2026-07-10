from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from wiicon5.planner.goal import GoalDecomposition
from wiicon5.query_synthesis.semantic_review import semantic_issue
from wiicon5.query_synthesis.sufficiency import normalize_match_text, params_text, text_constraint_variants
from wiicon5.semantic_roles import canonical_role
from wiicon5.skills.semantic_contract import SemanticSkillContract


STRUCTURAL_CONSTRAINT_ROLES = {
    "aggregation",
    "group_by",
    "granularity",
    "limit",
    "measure",
    "metric",
    "operation",
    "order",
    "period_granularity",
    "ranking",
    "top",
    "top_n",
}

TEMPORAL_CONSTRAINT_ROLES = {"date", "date_range", "period", "year"}


def goal_filter_contract_issues(
    *,
    query: str,
    params: Dict[str, Any],
    original_params: Dict[str, Any],
    goal: Optional[GoalDecomposition],
) -> List[Dict[str, Any]]:
    if goal is None:
        return []
    contract = SemanticSkillContract.from_dict(goal.semantic_contract)
    if not contract.current or not contract.required_filter_roles:
        return []
    enforced_roles = set(contract.required_filter_roles)
    query_text = normalize_match_text(query)
    used_names = set(re.findall(r"&([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)", query))
    original_used_params = {name: value for name, value in original_params.items() if name in used_names}
    resolved_used_params = {name: value for name, value in params.items() if name in used_names}
    used_params = {**original_used_params, **resolved_used_params}
    parameter_text = normalize_match_text(
        params_text({"original": original_used_params, "resolved": resolved_used_params})
    )
    literal_text = query_filter_literal_text(query)
    issues: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for requirement in goal.required_artifacts:
        for constraint in requirement.constraints:
            role = canonical_role(constraint.semantic_field)
            if not role or role in STRUCTURAL_CONSTRAINT_ROLES or role not in enforced_roles:
                continue
            variants = constraint_match_variants(constraint.value, constraint.raw_user_text)
            if not variants:
                continue
            reflected_by_parameter = any(variant in parameter_text for variant in variants)
            reflected_by_parameter = reflected_by_parameter or any(
                canonical_role(name) == role for name in used_params
            )
            if role in TEMPORAL_CONSTRAINT_ROLES and temporal_parameter_present(used_params):
                reflected_by_parameter = True
            reflected_by_query = any(variant in query_text for variant in variants)
            if not reflected_by_parameter and not reflected_by_query:
                key = ("goal_filter_not_reflected", role)
                if key not in seen:
                    seen.add(key)
                    issues.append(
                        semantic_issue(
                            code=key[0],
                            message=f"Обязательный фильтр goal.constraints не отражен в запросе: {role}.",
                            repair_hint=(
                                "Добавь условие по этому фильтру и передай пользовательское значение через &Параметр/params."
                            ),
                        )
                    )
                continue
            if reflected_by_parameter or not any(variant in literal_text for variant in variants):
                continue
            key = ("goal_filter_literal_not_parameterized", role)
            if key in seen:
                continue
            seen.add(key)
            issues.append(
                semantic_issue(
                    code=key[0],
                    message=f"Пользовательское значение фильтра встроено литералом в query: {role}.",
                    repair_hint=(
                        "Замени литерал на &Параметр и передай значение в params; для периода используй параметры начала и конца."
                    ),
                )
            )
    return issues


def constraint_match_variants(value: Any, raw_user_text: Any) -> List[str]:
    result: List[str] = []
    for candidate in [value, raw_user_text]:
        if isinstance(candidate, (dict, list, tuple, set)):
            continue
        for variant in text_constraint_variants(str(candidate or "")):
            normalized = normalize_match_text(variant)
            if normalized and normalized not in result:
                result.append(normalized)
    return result


def query_filter_literal_text(query: str) -> str:
    quoted = [item.replace('""', '"') for item in re.findall(r'"((?:""|[^"])*)"', query)]
    numbers = re.findall(r"(?<![A-Za-zА-Яа-яЁё0-9_])[-+]?\d+(?:[.,]\d+)?(?![A-Za-zА-Яа-яЁё0-9_])", query)
    return normalize_match_text(" ".join([*quoted, *numbers]))


def temporal_parameter_present(params: Dict[str, Any]) -> bool:
    for value in params.values():
        for scalar in scalar_values(value):
            if re.search(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2})?\b", str(scalar)):
                return True
    return False


def scalar_values(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from scalar_values(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from scalar_values(item)
        return
    yield value

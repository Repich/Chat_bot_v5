from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from wiicon5.models import SemanticFilter
from wiicon5.semantic_roles import canonical_role


PARAMETER_ROLE_HINTS: Dict[str, Sequence[str]] = {
    "product": ("товар", "номенклат", "продукт", "издел", "product", "item"),
    "price_type": ("видцен", "видцены", "типцен", "типцены", "price_type", "pricekind"),
    "customer": ("клиент", "покупател", "контрагент", "customer", "client"),
    "supplier": ("поставщик", "контрагент", "supplier", "vendor"),
    "warehouse": ("склад", "warehouse"),
}


def parameterized_lookup_spec_from_query(
    *,
    query: str,
    params: Dict[str, Any],
    constraints: Sequence[SemanticFilter],
    limit: int,
    metadata_dependencies: Sequence[str],
) -> Optional[Dict[str, Any]]:
    query = query.strip()
    if not query or not params or not constraints:
        return None
    bindings = infer_parameter_bindings(params, constraints)
    if not bindings:
        return None
    bound_parameters = {binding["parameter"] for binding in bindings}
    unbound_parameters = [name for name in params if name not in bound_parameters]
    if unbound_parameters:
        return None
    roles = unique([str(binding["semantic_field"]) for binding in bindings])
    return {
        "kind": "parameterized_lookup_query",
        "query": query,
        "params": dict(params),
        "limit": int(limit or 100),
        "parameter_bindings": bindings,
        "supported_filter_roles": roles,
        "metadata_dependencies": unique([str(item) for item in metadata_dependencies if str(item or "").strip()]),
    }


def infer_parameter_bindings(params: Dict[str, Any], constraints: Sequence[SemanticFilter]) -> List[Dict[str, Any]]:
    available = [constraint for constraint in constraints if str(constraint.semantic_field or "").strip()]
    used_roles: set[str] = set()
    bindings: List[Dict[str, Any]] = []
    for parameter, parameter_value in params.items():
        period_binding = infer_period_parameter_binding(parameter, parameter_value, available)
        if period_binding is not None:
            bindings.append(period_binding)
            continue
        best: Optional[tuple[int, SemanticFilter]] = None
        for constraint in available:
            role = normalize_role(constraint.semantic_field)
            if role in used_roles:
                continue
            score = binding_score(parameter, parameter_value, constraint)
            if score <= 0:
                continue
            if best is None or score > best[0]:
                best = (score, constraint)
        if best is None:
            continue
        constraint = best[1]
        role = normalize_role(constraint.semantic_field)
        used_roles.add(role)
        bindings.append(
            {
                "semantic_field": role,
                "parameter": str(parameter),
                "operator": normalize_operator(constraint.operator),
                "transform": transform_for_parameter(parameter_value, constraint),
                "required": True,
                "source": "goal_constraint",
                "example_value": constraint.value,
                "example_raw_user_text": constraint.raw_user_text,
            }
        )
    return bindings


def binding_score(parameter: str, parameter_value: Any, constraint: SemanticFilter) -> int:
    role = normalize_role(constraint.semantic_field)
    parameter_norm = normalize_token(parameter)
    score = 0
    if any(hint in parameter_norm for hint in PARAMETER_ROLE_HINTS.get(role, ())):
        score += 5
    value_norm = normalize_token(parameter_value)
    constraint_norm = normalize_token(constraint.value)
    raw_norm = normalize_token(constraint.raw_user_text)
    if value_matches(value_norm, constraint_norm) or value_matches(value_norm, raw_norm):
        score += 4
    if role and role in parameter_norm:
        score += 2
    return score


def value_matches(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left in right or right in left:
        return True
    prefix = common_prefix_len(left, right)
    return prefix >= min(4, len(left), len(right))


def transform_for_parameter(parameter_value: Any, constraint: SemanticFilter) -> str:
    operator = normalize_operator(constraint.operator)
    value = str(parameter_value or "")
    if "%" in value or operator in {"contains", "like", "подобно"}:
        return "contains_like"
    return "raw"


def build_parameterized_lookup_params(spec: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(spec.get("params") or {})
    filters = semantic_filters_from_inputs(inputs)
    for binding in spec.get("parameter_bindings", []) or []:
        if not isinstance(binding, dict):
            continue
        role = normalize_role(binding.get("semantic_field"))
        parameter = str(binding.get("parameter") or "").strip()
        if not role or not parameter:
            continue
        value = semantic_filter_value(filters, role)
        if value is None:
            continue
        params[parameter] = transform_value(value, str(binding.get("transform") or "raw"))
    return params


def missing_required_filter_roles(spec: Dict[str, Any], inputs: Dict[str, Any]) -> List[str]:
    filters = semantic_filters_from_inputs(inputs)
    present = {normalize_role(item.semantic_field) for item in filters}
    missing: List[str] = []
    for binding in spec.get("parameter_bindings", []) or []:
        if not isinstance(binding, dict) or not binding.get("required", True):
            continue
        role = normalize_role(binding.get("semantic_field"))
        if role and role not in present:
            missing.append(role)
    return unique(missing)


def semantic_filter_value(filters: Sequence[SemanticFilter], role: str) -> Any:
    normalized_role = normalize_role(role)
    for item in filters:
        if normalize_role(item.semantic_field) != normalized_role:
            continue
        if item.value not in (None, ""):
            return item.value
        if item.raw_user_text:
            return item.raw_user_text
    return None


def transform_value(value: Any, transform: str) -> Any:
    if transform == "contains_like":
        text = str(value or "").strip()
        if not text:
            return "%%"
        if "%" in text:
            return text
        return f"%{text}%"
    if transform in {"year_start", "year_end"}:
        try:
            year = int(str(value).strip())
        except (TypeError, ValueError):
            return value
        if transform == "year_start":
            return f"{year:04d}-01-01T00:00:00"
        return f"{year:04d}-12-31T23:59:59"
    return value


def infer_period_parameter_binding(
    parameter: str,
    parameter_value: Any,
    constraints: Sequence[SemanticFilter],
) -> Optional[Dict[str, Any]]:
    parameter_norm = normalize_token(parameter)
    start_markers = ["нач", "start", "from"]
    end_markers = ["кон", "end", "to"]
    transform = ""
    if any(marker in parameter_norm for marker in start_markers):
        transform = "year_start"
    elif any(marker in parameter_norm for marker in end_markers):
        transform = "year_end"
    if not transform:
        return None
    for constraint in constraints:
        role = normalize_role(constraint.semantic_field)
        if role != "year":
            continue
        year = str(constraint.value or constraint.raw_user_text or "").strip()
        match = re.search(r"(?:19|20)\d{2}", year)
        if match is None:
            continue
        parameter_text = str(parameter_value or "")
        if match.group(0) not in parameter_text:
            continue
        return {
            "semantic_field": "year",
            "parameter": str(parameter),
            "operator": normalize_operator(constraint.operator),
            "transform": transform,
            "required": True,
            "source": "goal_constraint",
            "example_value": constraint.value,
            "example_raw_user_text": constraint.raw_user_text,
        }
    return None


def constraints_from_goal_payload(payload: Any) -> List[SemanticFilter]:
    if payload is None:
        return []
    if hasattr(payload, "required_artifacts"):
        result: List[SemanticFilter] = []
        for requirement in getattr(payload, "required_artifacts", []) or []:
            for constraint in getattr(requirement, "constraints", []) or []:
                if isinstance(constraint, SemanticFilter):
                    result.append(constraint)
        return result
    if isinstance(payload, dict):
        artifacts = payload.get("required_artifacts")
        if not isinstance(artifacts, list):
            return []
        result = []
        for requirement in artifacts:
            if not isinstance(requirement, dict):
                continue
            for constraint in requirement.get("constraints", []) or []:
                if isinstance(constraint, dict):
                    try:
                        result.append(SemanticFilter.from_dict(constraint))
                    except (KeyError, TypeError, ValueError):
                        continue
        return result
    return []


def semantic_filters_from_inputs(inputs: Dict[str, Any]) -> List[SemanticFilter]:
    result: List[SemanticFilter] = []
    for item in inputs.get("filters", []) or []:
        if isinstance(item, SemanticFilter):
            result.append(item)
        elif isinstance(item, dict):
            result.append(SemanticFilter.from_dict(item))
    return result


def normalize_role(value: Any) -> str:
    return canonical_role(value)


def normalize_operator(value: Any) -> str:
    return str(value or "equals").strip().lower()


def normalize_token(value: Any) -> str:
    text = str(value or "").lower().replace("%", "")
    return re.sub(r"[^0-9a-zа-яё]+", "", text)


def common_prefix_len(left: str, right: str) -> int:
    count = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        count += 1
    return count


def unique(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result

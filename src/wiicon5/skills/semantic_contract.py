from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from wiicon5.intent.models import IntentResult
from wiicon5.models import SemanticFilter
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.semantic_roles import canonical_role, roles_match


SEMANTIC_CONTRACT_SCHEMA_VERSION = 2

STRUCTURAL_FILTER_ROLES = {
    "aggregation",
    "group_by",
    "granularity",
    "measure",
    "metric",
    "operation",
    "order",
    "period_granularity",
    "ranking",
}

GENERIC_SUBJECT_WORDS = {
    "answer",
    "data",
    "get",
    "list",
    "result",
    "show",
    "table",
    "вывести",
    "данные",
    "значение",
    "значения",
    "найти",
    "получить",
    "показать",
    "покажи",
    "результат",
    "список",
    "таблица",
}

GENERIC_SUBJECT_PREFIXES = {
    "answer",
    "data",
    "find",
    "get",
    "list",
    "result",
    "show",
    "table",
    "вывест",
    "данн",
    "значен",
    "найт",
    "ответ",
    "покаж",
    "получ",
    "результат",
    "список",
    "таблиц",
    "тип",
}

GENERIC_MEASURE_TOKENS = {
    "amount",
    "count",
    "metric",
    "quantity",
    "value",
    "значен",
    "количеств",
    "метрик",
    "показател",
    "сумм",
}


@dataclass(frozen=True)
class SemanticMeasure:
    role: str
    aggregation: str = ""
    unit: str = ""
    result_column: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SemanticMeasure":
        return cls(
            role=normalize_semantic_text(payload.get("role")),
            aggregation=canonical_aggregation(payload.get("aggregation")),
            unit=normalize_semantic_text(payload.get("unit")),
            result_column=str(payload.get("result_column") or "").strip(),
        )

    def to_dict(self) -> Dict[str, str]:
        return {
            "role": self.role,
            "aggregation": self.aggregation,
            "unit": self.unit,
            "result_column": self.result_column,
        }


@dataclass(frozen=True)
class SemanticRanking:
    enabled: bool = False
    direction: str = ""
    limit: int = 0
    by_measure: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SemanticRanking":
        return cls(
            enabled=bool(payload.get("enabled")),
            direction=canonical_direction(payload.get("direction")),
            limit=max(0, int(payload.get("limit") or 0)),
            by_measure=normalize_semantic_text(payload.get("by_measure")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "direction": self.direction,
            "limit": self.limit,
            "by_measure": self.by_measure,
        }


@dataclass(frozen=True)
class SemanticSkillContract:
    schema_version: int = SEMANTIC_CONTRACT_SCHEMA_VERSION
    subject_terms: List[str] = field(default_factory=list)
    operation: str = ""
    measures: List[SemanticMeasure] = field(default_factory=list)
    grain: List[str] = field(default_factory=list)
    dimensions: List[str] = field(default_factory=list)
    required_filter_roles: List[str] = field(default_factory=list)
    optional_filter_roles: List[str] = field(default_factory=list)
    fixed_filter_values: Dict[str, str] = field(default_factory=dict)
    result_columns: List[str] = field(default_factory=list)
    ranking: SemanticRanking = field(default_factory=SemanticRanking)
    source_objects: List[str] = field(default_factory=list)
    match_mode: str = "generalized"
    original_question: str = ""
    confidence: float = 0.0

    @classmethod
    def from_dict(cls, payload: Optional[Mapping[str, Any]]) -> "SemanticSkillContract":
        data = payload or {}
        ranking = data.get("ranking") if isinstance(data.get("ranking"), Mapping) else {}
        return cls(
            schema_version=int(data.get("schema_version") or 0),
            subject_terms=unique(normalize_subject_term(item) for item in data.get("subject_terms", []) or []),
            operation=canonical_operation(data.get("operation")),
            measures=[SemanticMeasure.from_dict(item) for item in data.get("measures", []) or [] if isinstance(item, Mapping)],
            grain=unique(normalize_semantic_text(item) for item in data.get("grain", []) or []),
            dimensions=unique(normalize_semantic_text(item) for item in data.get("dimensions", []) or []),
            required_filter_roles=unique(canonical_role(item) for item in data.get("required_filter_roles", []) or []),
            optional_filter_roles=unique(canonical_role(item) for item in data.get("optional_filter_roles", []) or []),
            fixed_filter_values={
                canonical_role(key): normalize_semantic_text(value)
                for key, value in (data.get("fixed_filter_values", {}) or {}).items()
                if canonical_role(key) and normalize_semantic_text(value)
            }
            if isinstance(data.get("fixed_filter_values"), Mapping)
            else {},
            result_columns=unique(str(item).strip() for item in data.get("result_columns", []) or []),
            ranking=SemanticRanking.from_dict(ranking),
            source_objects=unique(str(item).strip() for item in data.get("source_objects", []) or []),
            match_mode=str(data.get("match_mode") or "generalized").strip().lower(),
            original_question=str(data.get("original_question") or "").strip(),
            confidence=float(data.get("confidence") or 0.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "subject_terms": list(self.subject_terms),
            "operation": self.operation,
            "measures": [item.to_dict() for item in self.measures],
            "grain": list(self.grain),
            "dimensions": list(self.dimensions),
            "required_filter_roles": list(self.required_filter_roles),
            "optional_filter_roles": list(self.optional_filter_roles),
            "fixed_filter_values": dict(self.fixed_filter_values),
            "result_columns": list(self.result_columns),
            "ranking": self.ranking.to_dict(),
            "source_objects": list(self.source_objects),
            "match_mode": self.match_mode,
            "original_question": self.original_question,
            "confidence": self.confidence,
        }

    @property
    def current(self) -> bool:
        return self.schema_version == SEMANTIC_CONTRACT_SCHEMA_VERSION


@dataclass(frozen=True)
class SemanticCompatibility:
    compatible: bool
    score: int = 0
    reasons: List[str] = field(default_factory=list)
    rejection_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "compatible": self.compatible,
            "score": self.score,
            "reasons": list(self.reasons),
            "rejection_reasons": list(self.rejection_reasons),
        }


def contract_from_goal(intent: Optional[IntentResult], goal: Optional[GoalDecomposition]) -> SemanticSkillContract:
    intent_business_goal = intent.business_goal if intent is not None else ""
    question = (goal.business_goal if goal is not None else "") or intent_business_goal
    explicit = getattr(goal, "semantic_contract", {}) if goal is not None else {}
    if isinstance(explicit, Mapping) and explicit:
        parsed = SemanticSkillContract.from_dict(explicit)
        if parsed.current:
            parsed = sanitize_explicit_subject_terms(parsed, explicit, goal_constraints(goal))
            return replace(
                parsed,
                original_question=parsed.original_question or question,
                confidence=parsed.confidence or (0.7 if question else 0.0),
            )

    intent_domain_terms = intent.domain_terms if intent is not None else []
    constraints = goal_constraints(goal)
    text_parts = [question, intent_business_goal, *intent_domain_terms]
    text_parts.extend(str(item.value or item.raw_user_text or "") for item in constraints)
    text = " ".join(text_parts)
    columns = goal_required_columns(goal)
    aggregations = aggregations_from_text_and_constraints(text, constraints)
    measures = measures_from_goal(text, constraints, columns, aggregations)
    ranking = ranking_from_text(text)
    operation = operation_from_text(text, aggregations=aggregations, ranking=ranking)
    filter_roles = unique(
        canonical_role(item.semantic_field)
        for item in constraints
        if canonical_role(item.semantic_field) not in STRUCTURAL_FILTER_ROLES
    )
    dimensions = dimensions_from_goal(constraints, columns)
    return SemanticSkillContract(
        subject_terms=subject_terms(text, constraints=constraints, measures=measures),
        operation=operation,
        measures=measures,
        grain=list(dimensions),
        dimensions=dimensions,
        required_filter_roles=filter_roles,
        fixed_filter_values=constraint_values_by_role(constraints),
        result_columns=columns,
        ranking=ranking,
        match_mode="generalized",
        original_question=question,
        confidence=0.7 if question else 0.0,
    )


def semantic_contract_compatibility(
    requested: SemanticSkillContract,
    available: SemanticSkillContract,
) -> SemanticCompatibility:
    rejected: List[str] = []
    reasons: List[str] = []
    score = 0

    if not available.current:
        rejected.append("skill_contract_schema_outdated")
    if available.match_mode == "exact":
        if normalize_question(requested.original_question) != normalize_question(available.original_question):
            rejected.append("exact_question_mismatch")
        else:
            reasons.append("exact_question_match")
            score += 100

    if requested.operation and available.operation:
        if requested.operation != available.operation:
            if requested.operation == "lookup" and available.operation == "list":
                reasons.append("lookup_satisfied_by_list")
                score += 15
            else:
                rejected.append(f"operation_mismatch:{requested.operation}!={available.operation}")
        else:
            reasons.append("operation_match")
            score += 20

    requested_aggregations = {item.aggregation for item in requested.measures if item.aggregation}
    available_aggregations = {item.aggregation for item in available.measures if item.aggregation}
    if requested_aggregations:
        if not available_aggregations or not requested_aggregations.issubset(available_aggregations):
            rejected.append("aggregation_mismatch")
        else:
            reasons.append("aggregation_match")
            score += 30

    requested_measure_roles = {normalize_semantic_text(item.role) for item in requested.measures if item.role}
    available_measure_roles = {normalize_semantic_text(item.role) for item in available.measures if item.role}
    if requested_measure_roles and available_measure_roles:
        unmatched = [
            role
            for role in requested_measure_roles
            if not any(semantic_measure_roles_match(role, candidate) for candidate in available_measure_roles)
        ]
        if unmatched:
            rejected.append("measure_mismatch:" + ",".join(sorted(unmatched)))
        else:
            reasons.append("measure_match")
            score += 20

    if requested.ranking.enabled:
        if not available.ranking.enabled:
            rejected.append("ranking_missing")
        else:
            if requested.ranking.direction and available.ranking.direction != requested.ranking.direction:
                rejected.append("ranking_direction_mismatch")
            if (
                requested.ranking.by_measure
                and available.ranking.by_measure
                and not semantic_ranking_measures_match(requested, available)
            ):
                rejected.append("ranking_measure_mismatch")
            if not rejected:
                reasons.append("ranking_match")
                score += 20
    elif available.ranking.enabled and requested.operation != "rank":
        rejected.append("unexpected_ranking")

    available_filter_roles = set(available.required_filter_roles) | set(available.optional_filter_roles)
    missing_filters = sorted(set(requested.required_filter_roles) - available_filter_roles)
    if missing_filters:
        rejected.append("unsupported_filters:" + ",".join(missing_filters))
    elif requested.required_filter_roles:
        reasons.append("filters_supported")
        score += 10

    absent_required_filters = sorted(set(available.required_filter_roles) - set(requested.required_filter_roles))
    if absent_required_filters:
        rejected.append("required_skill_filters_missing:" + ",".join(absent_required_filters))

    for role, expected_value in available.fixed_filter_values.items():
        requested_value = requested.fixed_filter_values.get(role, "")
        if not requested_value:
            if any(
                semantic_terms_match(expected_value, qualifier)
                for qualifier in semantic_subject_qualifiers(requested)
            ):
                reasons.append(f"fixed_filter_implied_by_subject:{role}")
                score += 5
            else:
                rejected.append(f"fixed_filter_missing:{role}")
            continue
        if not fixed_filter_values_match(requested_value, expected_value):
            rejected.append(f"fixed_filter_mismatch:{role}")
    if available.fixed_filter_values and not any(item.startswith("fixed_filter_") for item in rejected):
        reasons.append("fixed_filters_match")
        score += 10

    missing_columns = [
        column
        for column in requested.result_columns
        if not any(column_names_match(column, candidate) for candidate in available.result_columns)
    ]
    if missing_columns:
        rejected.append("result_columns_missing:" + ",".join(missing_columns))
    elif requested.result_columns:
        reasons.append("result_columns_match")
        score += 10

    requested_qualifiers = semantic_subject_qualifiers(requested)
    available_qualifiers = semantic_subject_qualifiers(available)
    if requested_qualifiers:
        unmatched_subjects = [
            term
            for term in requested_qualifiers
            if not any(semantic_terms_match(term, candidate) for candidate in available.subject_terms)
        ]
        if unmatched_subjects:
            rejected.append("subject_mismatch:" + ",".join(unmatched_subjects))
        else:
            reasons.append("subject_match")
            score += min(20, len(requested_qualifiers) * 5)
    unmatched_available_qualifiers = [
        term
        for term in available_qualifiers
        if not any(semantic_terms_match(term, candidate) for candidate in requested_qualifiers)
    ]
    if unmatched_available_qualifiers:
        rejected.append("unexpected_subject_qualifier:" + ",".join(unmatched_available_qualifiers))

    return SemanticCompatibility(
        compatible=not rejected,
        score=score if not rejected else 0,
        reasons=reasons,
        rejection_reasons=rejected,
    )


def goal_constraints(goal: Optional[GoalDecomposition]) -> List[SemanticFilter]:
    if goal is None:
        return []
    return [constraint for requirement in goal.required_artifacts for constraint in requirement.constraints]


def goal_required_columns(goal: Optional[GoalDecomposition]) -> List[str]:
    if goal is None:
        return []
    return unique(column for requirement in goal.required_artifacts for column in requirement.required_columns)


def constraint_values_by_role(constraints: Sequence[SemanticFilter]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in constraints:
        role = canonical_role(item.semantic_field)
        if not role or role in STRUCTURAL_FILTER_ROLES:
            continue
        value = normalize_semantic_text(item.value if item.value not in (None, "") else item.raw_user_text)
        if value:
            result[role] = value
    return result


def aggregations_from_text_and_constraints(text: str, constraints: Sequence[SemanticFilter]) -> List[str]:
    values = [text]
    values.extend(
        " ".join([item.semantic_field, str(item.value or ""), item.raw_user_text])
        for item in constraints
        if canonical_role(item.semantic_field) in {"aggregation", "measure", "metric", "operation"}
    )
    normalized = " ".join(values).lower()
    result: List[str] = []
    markers = [
        ("avg", ["средн", "average", "avg"]),
        ("count", ["сколько", "количество", "число ", "count"]),
        ("sum", ["сумм", "итого", "total", "sum"]),
        ("min", ["миним", "наименьш", "самый малень", "minimum", " min"]),
        ("max", ["максим", "наибольш", "самый больш", "maximum", " max"]),
    ]
    for aggregation, terms in markers:
        if any(term in normalized for term in terms):
            result.append(aggregation)
    return unique(result)


def measures_from_goal(
    text: str,
    constraints: Sequence[SemanticFilter],
    columns: Sequence[str],
    aggregations: Sequence[str],
) -> List[SemanticMeasure]:
    roles: List[str] = []
    for item in constraints:
        if canonical_role(item.semantic_field) not in {"measure", "metric"}:
            continue
        roles.extend(subject_terms(str(item.value or item.raw_user_text or "")))
    if not roles:
        roles.extend(measure_terms_from_columns(columns))
    if not roles:
        roles.extend(measure_terms_from_text(text))
    if not roles and aggregations:
        roles.append("value")
    aggregation = aggregations[0] if len(aggregations) == 1 else ""
    return [SemanticMeasure(role=role, aggregation=aggregation) for role in unique(roles)[:4]]


def measure_terms_from_columns(columns: Sequence[str]) -> List[str]:
    result: List[str] = []
    for column in columns:
        normalized = normalize_subject_term(column)
        if normalized and normalized not in {"год", "период", "дата", "наименование", "номер"}:
            result.append(normalized)
    return unique(result)


def measure_terms_from_text(text: str) -> List[str]:
    known = [
        "выручка",
        "прибыль",
        "себестоимость",
        "задолженность",
        "остаток",
        "количество",
        "стоимость",
        "цена",
        "сумма",
    ]
    lowered = text.lower()
    return [item for item in known if item[:5] in lowered]


def dimensions_from_goal(constraints: Sequence[SemanticFilter], columns: Sequence[str]) -> List[str]:
    values: List[str] = []
    for item in constraints:
        if canonical_role(item.semantic_field) not in {"group_by", "granularity", "period_granularity"}:
            continue
        values.extend(subject_terms(str(item.value or item.raw_user_text or "")))
    for column in columns:
        normalized = normalize_subject_term(column)
        if normalized and normalized not in {"сумма", "стоимость", "цена", "количество", "остаток"}:
            values.append(normalized)
    return unique(values)


def ranking_from_text(text: str) -> SemanticRanking:
    lowered = text.lower()
    enabled = any(term in lowered for term in ["топ", "top", "сам", "наибольш", "наименьш", "максим", "миним"])
    if not enabled:
        return SemanticRanking()
    direction = "asc" if any(term in lowered for term in ["наименьш", "миним", "самый малень"]) else "desc"
    limit_match = re.search(r"(?:топ|top)\s*(\d+)", lowered)
    limit = int(limit_match.group(1)) if limit_match else 1
    return SemanticRanking(enabled=True, direction=direction, limit=limit)


def operation_from_text(text: str, *, aggregations: Sequence[str], ranking: SemanticRanking) -> str:
    lowered = text.lower()
    if ranking.enabled:
        return "rank"
    if aggregations:
        return "aggregate"
    if any(term in lowered for term in ["остат", "balance", "в наличии"]):
        return "balance"
    if any(term in lowered for term in ["список", "все ", "перечень", "list"]):
        return "list"
    return "lookup"


def subject_terms(
    text: str,
    *,
    constraints: Sequence[SemanticFilter] = (),
    measures: Sequence[SemanticMeasure] = (),
) -> List[str]:
    excluded = {normalize_subject_term(item.role) for item in measures if item.role}
    for constraint in constraints:
        excluded.update(tokenized_subject_terms(constraint.value))
        excluded.update(tokenized_subject_terms(constraint.raw_user_text))
    result: List[str] = []
    for word in re.split(r"[^0-9A-Za-zА-Яа-яЁё]+", text.lower().replace("ё", "е")):
        normalized = normalize_subject_term(word)
        if (
            len(normalized) < 4
            or normalized.isdigit()
            or normalized in GENERIC_SUBJECT_WORDS
            or normalized in GENERIC_SUBJECT_PREFIXES
            or normalized in excluded
        ):
            continue
        if canonical_aggregation(normalized):
            continue
        result.append(normalized)
    return unique(result)[:16]


def tokenized_subject_terms(value: Any) -> List[str]:
    return unique(
        normalize_subject_term(item)
        for item in re.split(r"[^0-9A-Za-zА-Яа-яЁё]+", str(value or "").lower().replace("ё", "е"))
        if normalize_subject_term(item)
    )


def sanitize_explicit_subject_terms(
    contract: SemanticSkillContract,
    payload: Mapping[str, Any],
    constraints: Sequence[SemanticFilter],
) -> SemanticSkillContract:
    """Remove current parameter values that an LLM copied into the reusable subject."""

    excluded: set[str] = set()
    for constraint in constraints:
        excluded.update(tokenized_subject_terms(constraint.value))
        excluded.update(tokenized_subject_terms(constraint.raw_user_text))

    raw_terms = payload.get("subject_terms")
    if not excluded or not isinstance(raw_terms, list):
        return contract

    retained: List[str] = []
    for raw_term in raw_terms:
        tokens = tokenized_subject_terms(raw_term)
        if tokens and all(token in excluded for token in tokens):
            continue
        normalized = normalize_subject_term(raw_term)
        if normalized and not normalized.isdigit() and normalized not in GENERIC_SUBJECT_WORDS:
            retained.append(normalized)
    return replace(contract, subject_terms=unique(retained))


def canonical_aggregation(value: Any) -> str:
    normalized = normalize_semantic_text(value)
    aliases = {
        "average": "avg",
        "avg": "avg",
        "mean": "avg",
        "среднее": "avg",
        "средний": "avg",
        "count": "count",
        "количество": "count",
        "число": "count",
        "sum": "sum",
        "total": "sum",
        "итого": "sum",
        "сумма": "sum",
        "minimum": "min",
        "min": "min",
        "минимум": "min",
        "maximum": "max",
        "max": "max",
        "максимум": "max",
    }
    return aliases.get(normalized, "")


def canonical_operation(value: Any) -> str:
    normalized = normalize_semantic_text(value)
    aliases = {
        "aggregation": "aggregate",
        "aggregate": "aggregate",
        "balance": "balance",
        "list": "list",
        "lookup": "lookup",
        "rank": "rank",
        "ranking": "rank",
        "top": "rank",
    }
    return aliases.get(normalized, normalized)


def canonical_direction(value: Any) -> str:
    normalized = normalize_semantic_text(value)
    if normalized in {"asc", "ascending", "возр", "возрастание"}:
        return "asc"
    if normalized in {"desc", "descending", "убыв", "убывание"}:
        return "desc"
    return normalized


def normalize_semantic_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("ё", "е").split())


def normalize_subject_term(value: Any) -> str:
    normalized = re.sub(r"[^0-9a-zа-я]+", "", normalize_semantic_text(value))
    for ending in ["иями", "ями", "ами", "ение", "ений", "ского", "ого", "ему", "ами", "ями", "ов", "ев", "ая", "яя", "ое", "ее", "ые", "ие", "ый", "ий", "ой", "ам", "ям", "ах", "ях", "ы", "и", "а", "я", "у", "ю", "е"]:
        if normalized.endswith(ending) and len(normalized) - len(ending) >= 5:
            return normalized[: -len(ending)]
    return normalized


def semantic_terms_match(left: str, right: str) -> bool:
    left_norm = normalize_subject_term(left)
    right_norm = normalize_subject_term(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    return min(len(left_norm), len(right_norm)) >= 5 and (
        left_norm in right_norm or right_norm in left_norm or left_norm[:5] == right_norm[:5]
    )


def semantic_measure_roles_match(left: str, right: str) -> bool:
    left_tokens = tokenized_subject_terms(left)
    right_tokens = tokenized_subject_terms(right)
    if not left_tokens or not right_tokens:
        return False
    if left_tokens == right_tokens:
        return True
    left_specific = [item for item in left_tokens if item not in GENERIC_MEASURE_TOKENS]
    right_specific = [item for item in right_tokens if item not in GENERIC_MEASURE_TOKENS]
    if bool(left_specific) != bool(right_specific):
        return False
    if not left_specific:
        return semantic_terms_match(left, right)
    return all(
        any(semantic_terms_match(term, candidate) for candidate in right_specific)
        for term in left_specific
    ) and all(
        any(semantic_terms_match(term, candidate) for candidate in left_specific)
        for term in right_specific
    )


def semantic_ranking_measures_match(
    left: SemanticSkillContract,
    right: SemanticSkillContract,
) -> bool:
    if semantic_measure_roles_match(left.ranking.by_measure, right.ranking.by_measure):
        return True
    left_measures = ranking_measure_candidates(left)
    right_measures = ranking_measure_candidates(right)
    return any(
        semantic_measure_pair_matches(left_measure, right_measure)
        for left_measure in left_measures
        for right_measure in right_measures
    )


def ranking_measure_candidates(contract: SemanticSkillContract) -> List[SemanticMeasure]:
    key = contract.ranking.by_measure
    candidates = [
        measure
        for measure in contract.measures
        if semantic_measure_roles_match(key, measure.role)
        or semantic_terms_match(key, measure.result_column)
    ]
    if candidates:
        return candidates
    return list(contract.measures) if len(contract.measures) == 1 else []


def semantic_measure_pair_matches(left: SemanticMeasure, right: SemanticMeasure) -> bool:
    if left.aggregation and right.aggregation and left.aggregation != right.aggregation:
        return False
    return (
        semantic_measure_roles_match(left.role, right.role)
        or semantic_terms_match(left.result_column, right.result_column)
        or semantic_terms_match(left.role, right.result_column)
        or semantic_terms_match(left.result_column, right.role)
    )


def semantic_subject_qualifiers(contract: SemanticSkillContract) -> List[str]:
    structural_terms = unique(
        [
            *(item.role for item in contract.measures if item.role),
            *contract.result_columns,
            *contract.grain,
            *contract.dimensions,
        ]
    )
    filter_roles = {
        canonical_role(item)
        for item in [*contract.required_filter_roles, *contract.optional_filter_roles]
        if canonical_role(item)
    }
    return [
        term
        for term in contract.subject_terms
        if canonical_role(term) not in filter_roles
        and not any(semantic_terms_match(term, structural) for structural in structural_terms)
    ]


def fixed_filter_values_match(left: Any, right: Any) -> bool:
    left_norm = re.sub(r"[^0-9a-zа-я]+", "", normalize_semantic_text(left))
    right_norm = re.sub(r"[^0-9a-zа-я]+", "", normalize_semantic_text(right))
    return bool(left_norm and right_norm and left_norm == right_norm)


def column_names_match(left: str, right: str) -> bool:
    return semantic_terms_match(left, right) or roles_match(left, right)


def normalize_question(value: str) -> str:
    return re.sub(r"[^0-9a-zа-я]+", " ", normalize_semantic_text(value)).strip()


def unique(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result

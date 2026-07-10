from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from wiicon5.intent.models import IntentResult
from wiicon5.knowledge.metadata import MetadataObject
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.query.one_c_query_review import dimensions_for, metadata_for_source, parse_sources, resources_for
from wiicon5.query_synthesis.semantic_review import (
    SEVERITY_CLARIFICATION,
    SEVERITY_REPAIR_REQUIRED,
    semantic_issue,
)


EXPLICIT_MONEY_METRIC_MARKERS = [
    "по выруч",
    "по сумм",
    "по стоимости",
    "деньг",
    "руб",
    "по обороту",
    "по продажам в руб",
    "по доходу",
    "по сумме продаж",
    "по стоимости продаж",
]


def trade_ru_semantic_review_issues(
    *,
    query: str,
    params: Optional[Dict[str, Any]] = None,
    goal: Optional[GoalDecomposition] = None,
    message: str = "",
    intent: Optional[IntentResult] = None,
    metadata_objects: Optional[List[MetadataObject]] = None,
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    constraints = [constraint for item in (goal.required_artifacts if goal is not None else []) for constraint in item.constraints]
    haystack = normalized_semantic_text(query, params or {})
    for constraint in constraints:
        if constraint.semantic_field == "warehouse_type" and not warehouse_type_filter_reflected(constraint, haystack):
            result.append(
                semantic_issue(
                    code="required_filter_not_reflected",
                    message=(
                        "Запрос не отражает обязательный фильтр warehouse_type из цели. "
                        "Сохрани ограничение пользователя в запросе: получи подходящие склады или используй "
                        "проверенное условие по типу склада."
                    ),
                )
            )
    if top_product_aggregate_required(goal=goal, message=message, intent=intent):
        aggregate_issue = top_product_aggregate_grain_issue(
            query=query,
            goal=goal,
            message=message,
            intent=intent,
            metadata_objects=metadata_objects or [],
        )
        if aggregate_issue is not None:
            result.append(aggregate_issue)
    sold_metric_issue = top_sold_product_metric_issue(query=query, message=message, intent=intent)
    if sold_metric_issue is not None:
        result.append(sold_metric_issue)
    average_document_issue = average_document_metric_issue(query=query, message=message, intent=intent)
    if average_document_issue is not None:
        result.append(average_document_issue)
    return result


def top_sold_product_metric_issue(
    *,
    query: str,
    message: str = "",
    intent: Optional[IntentResult] = None,
) -> Optional[Dict[str, Any]]:
    text = semantic_text(message=message, intent=intent)
    if not any(marker in text for marker in ["сам", "больше всего", "наибольш", "топ", "top"]):
        return None
    if not any(marker in text for marker in ["продаваем", "продаж", "купил", "брали", "ходов", "лидер продаж"]):
        return None
    if not any(marker in text for marker in ["товар", "номенклатур", "product"]):
        return None
    if any(marker in text for marker in EXPLICIT_MONEY_METRIC_MARKERS):
        return None
    normalized_query = " ".join(query.lower().split())
    if any(marker in normalized_query for marker in ["количество", "quantity", "count("]):
        return None
    if any(marker in normalized_query for marker in ["выруч", "суммапродаж", "суммавыруч", "сумма"]):
        return semantic_issue(
            code="top_sold_product_metric_ambiguous",
            severity=SEVERITY_CLARIFICATION,
            message=(
                "Пользователь спросил самый продаваемый товар без уточнения метрики, "
                "а запрос ранжирует товары по денежной сумме."
            ),
            clarification_question="Считать самый продаваемый товар по количеству проданных единиц или по выручке?",
            clarification_options=["по количеству", "по выручке"],
            allowed_actions=["ask_clarification", "answer_with_assumption"],
        )
    return None


def average_document_metric_issue(
    *,
    query: str,
    message: str = "",
    intent: Optional[IntentResult] = None,
) -> Optional[Dict[str, Any]]:
    text = semantic_text(message=message, intent=intent)
    if "средн" not in text:
        return None
    if not any(marker in text for marker in ["реализац", "заказ", "поступлен", "документ"]):
        return None
    normalized_query = " ".join(query.lower().split())
    if "среднее(" not in normalized_query:
        return None
    if "регистрнакопления." not in normalized_query:
        return None
    if query_looks_document_grained(normalized_query):
        return None
    repair_hint = (
        "Сначала приведи данные к зерну документа: сгруппируй движения по Регистратор/Документ, "
        "посчитай сумму документа, затем посчитай среднее по этим суммам."
    )
    return semantic_issue(
        code="average_document_metric_needs_document_grain",
        severity=SEVERITY_REPAIR_REQUIRED,
        message=(
            "Пользователь спрашивает среднее значение по документам, а запрос считает СРЕДНЕЕ() "
            "по строкам сырого регистра."
        ),
        repair_hint=repair_hint,
        allowed_actions=["repair_query", "ask_clarification_if_repair_fails"],
    )


def semantic_text(*, message: str, intent: Optional[IntentResult]) -> str:
    return " ".join(
        [
            message,
            getattr(intent, "business_goal", "") if intent is not None else "",
            " ".join(getattr(intent, "domain_terms", []) or []) if intent is not None else "",
        ]
    ).lower()


def query_looks_document_grained(normalized_query: str) -> bool:
    if not any(marker in normalized_query for marker in ["регистратор", ".документ", ".ссылка"]):
        return False
    if "сгруппировать по" in normalized_query:
        return True
    # Some document tables already have one row per document and may expose a direct amount field.
    return "документ." in normalized_query


def top_product_aggregate_required(
    *,
    goal: Optional[GoalDecomposition],
    message: str = "",
    intent: Optional[IntentResult] = None,
) -> bool:
    if goal is not None and goal_requires_top_product_aggregate(goal):
        return True
    values = " ".join(
        [
            message,
            getattr(intent, "business_goal", "") if intent is not None else "",
            " ".join(getattr(intent, "domain_terms", []) or []) if intent is not None else "",
        ]
    ).lower()
    if not any(marker in values for marker in ["больше всего", "наибольш", "максим", "самый больш", "top", "max"]):
        return False
    if not any(marker in values for marker in ["товар", "номенклатур", "product"]):
        return False
    return any(marker in values for marker in ["остат", "в наличии", "колич", "stock", "quantity"])


def warehouse_type_filter_reflected(constraint: Any, haystack: str) -> bool:
    if "типсклада" in haystack:
        return True
    if "рознич" in haystack or "оптов" in haystack:
        return True
    value_terms = semantic_value_terms(str(constraint.value or "") + " " + constraint.raw_user_text)
    return bool(value_terms and any(term in haystack for term in value_terms))


def goal_requires_top_product_aggregate(goal: GoalDecomposition) -> bool:
    for requirement in goal.required_artifacts:
        if requirement.type not in {"AggregateTable", "TopNMetricTable", "RankedMetricTable", "RankedStockBalanceTable"}:
            continue
        values = " ".join(
            [requirement.name, requirement.type]
            + [constraint.semantic_field + " " + str(constraint.value or "") + " " + constraint.raw_user_text for constraint in requirement.constraints]
        ).lower()
        if not any(marker in values for marker in ["max", "top", "сам", "больше всего", "наибольш", "максим"]):
            continue
        if not any(marker in values for marker in ["product", "номенклат", "товар"]):
            continue
        if not any(marker in values for marker in ["stock", "остат", "quantity", "колич"]):
            continue
        return True
    return False


def top_product_aggregate_grain_issue(
    *,
    query: str,
    goal: Optional[GoalDecomposition],
    message: str = "",
    intent: Optional[IntentResult] = None,
    metadata_objects: List[MetadataObject],
) -> Optional[Dict[str, Any]]:
    normalized_query = " ".join(query.lower().split())
    if not ("первые" in normalized_query and "упорядочить по" in normalized_query):
        return None
    if not goal_has_warehouse_scope(goal) and not query_or_question_has_warehouse_scope(normalized_query, message, intent):
        return None
    metadata_by_name = {item.full_name: item for item in metadata_objects if item.full_name}
    for source in parse_sources(query):
        if source.object_type != "РегистрНакопления" or source.virtual_table != "Остатки":
            continue
        metadata = metadata_for_source(source, metadata_by_name)
        if metadata is None:
            continue
        dimensions = dimensions_for(metadata)
        resources = resources_for(metadata)
        if "Номенклатура" not in dimensions or "Склад" not in dimensions:
            continue
        if query_groups_product(query) and query_sums_balance_resource(query, resources):
            return None
        return semantic_issue(
            code="aggregate_grain_not_confirmed",
            message=(
                "Для top/max товара по остаткам запрос к Остатки() должен агрегировать строки регистра "
                "до зерна товара: СУММА(<Ресурс>Остаток), СГРУППИРОВАТЬ ПО Номенклатура, сортировка по агрегату. "
                "Нельзя отвечать ПЕРВЫЕ 1 по одной строке регистра, если у регистра есть дополнительные измерения."
            ),
        )
    return None


def goal_has_warehouse_scope(goal: Optional[GoalDecomposition]) -> bool:
    if goal is None:
        return False
    return any(
        constraint.semantic_field in {"warehouse_type", "warehouse", "warehouses"}
        for requirement in goal.required_artifacts
        for constraint in requirement.constraints
    )


def query_or_question_has_warehouse_scope(
    normalized_query: str,
    message: str = "",
    intent: Optional[IntentResult] = None,
) -> bool:
    text = " ".join(
        [
            normalized_query,
            message.lower(),
            getattr(intent, "business_goal", "").lower() if intent is not None else "",
            " ".join(getattr(intent, "domain_terms", []) or []).lower() if intent is not None else "",
        ]
    )
    return any(marker in text for marker in ["склад", "магазин", "warehouse"])


def query_groups_product(query: str) -> bool:
    normalized = " ".join(query.lower().split())
    return "сгруппировать по" in normalized and "номенклатура" in normalized.split("сгруппировать по", 1)[1]


def query_sums_balance_resource(query: str, resources: Set[str]) -> bool:
    normalized = " ".join(query.lower().split())
    if "сумма(" not in normalized:
        return False
    if not resources:
        return "остаток" in normalized
    return any((resource + "Остаток").lower() in normalized for resource in resources)


def normalized_semantic_text(query: str, params: Dict[str, Any]) -> str:
    return (query + " " + str(params)).replace("_", "").lower()


def semantic_value_terms(value: str) -> List[str]:
    return [token.lower() for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", value) if len(token) >= 4]

from __future__ import annotations

from typing import Any, Dict, List, Optional

from wiicon5.intent.models import IntentResult
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
    message: str = "",
    intent: Optional[IntentResult] = None,
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
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

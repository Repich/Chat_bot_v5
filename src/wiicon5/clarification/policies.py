from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from wiicon5.execution.artifacts import Artifact
from wiicon5.presentation.answer_formatter import format_cell


class ClarificationPolicy(Protocol):
    def resolve(self, message: str, clarification: Artifact) -> Optional[Artifact]:
        ...


class DocumentAmountClarificationPolicy:
    """Resolve the current document-amount clarification shape.

    This policy keeps the existing WIICON alpha behavior outside the core
    orchestrator. It should later be replaced by metadata-driven
    ClarificationOption actions.
    """

    def resolve(self, message: str, clarification: Artifact) -> Optional[Artifact]:
        if not isinstance(clarification.value, dict):
            return None
        value = clarification.value
        if not selects_document_amount_option(message, value):
            return None
        answer = document_amount_answer_from_clarification(value)
        if not answer:
            return None
        return Artifact(name="answer", type="UserAnswer", value=answer, provenance=["clarification_request"])


def selects_document_amount_option(message: str, clarification: Dict[str, Any]) -> bool:
    text = message.lower()
    if any(marker in text for marker in ["задолж", "долг", "долж", "фактичес"]):
        return False
    options = " ".join(str(item) for item in clarification.get("clarification_options", [])).lower()
    has_document_amount_option = "сумм" in options and ("документ" in options or "отгруз" in options)
    if not has_document_amount_option:
        return False
    if text.strip() in {"1", "первый", "первое", "первый вариант"}:
        return True
    return "сумм" in text and ("документ" in text or "отгруз" in text)


def document_amount_answer_from_clarification(clarification: Dict[str, Any]) -> str:
    partial = clarification.get("partial_result")
    if not isinstance(partial, dict):
        return ""
    rows = partial.get("rows")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return ""
    row = rows[0]
    amount_column = first_amount_column(row)
    if not amount_column:
        return ""
    amount = format_cell(row.get(amount_column))
    if not amount:
        return ""
    subject_column = first_subject_column(row)
    subject = format_cell(row.get(subject_column)) if subject_column else ""
    original_question = str(clarification.get("question") or "").lower()
    object_name = "последней отгрузки" if "отгруз" in original_question else "документа"
    if subject:
        return f"Сумма {object_name} по документу: {amount}. Контрагент: {subject}."
    return f"Сумма {object_name} по документу: {amount}."


def first_amount_column(row: Dict[str, Any]) -> str:
    preferred = ["СуммаДокумента", "Сумма", "СуммаОтгрузки", "Amount"]
    for column in preferred:
        if row.get(column) not in (None, ""):
            return column
    for column, value in row.items():
        if value not in (None, "") and ("сумм" in column.lower() or "amount" in column.lower()):
            return column
    return ""


def first_subject_column(row: Dict[str, Any]) -> str:
    for column in ["Контрагент", "Клиент", "Партнер", "Партнёр", "Поставщик"]:
        if row.get(column) not in (None, ""):
            return column
    return ""

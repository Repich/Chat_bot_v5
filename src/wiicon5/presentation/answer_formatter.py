from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional


def format_user_answer(*, question: str, columns: List[str], rows: List[Dict[str, Any]], max_rows: int = 10) -> str:
    if rows_effectively_empty(rows):
        return "Данных не найдено."

    effective_columns = columns or sorted({key for row in rows for key in row})
    if len(rows) == 1:
        summary = single_row_summary(question=question, row=rows[0], columns=effective_columns)
        if summary:
            return summary

    prefix = table_prefix(question=question, rows=rows)
    table = render_table_preview(columns=effective_columns, rows=rows, max_rows=max_rows)
    return f"{prefix}\n\n{table}" if prefix else table


def single_row_summary(*, question: str, row: Dict[str, Any], columns: List[str]) -> str:
    document_summary = document_row_summary(question=question, row=row)
    if document_summary:
        return document_summary

    count_summary = count_row_summary(question=question, row=row, columns=columns)
    if count_summary:
        return count_summary

    top_summary = top_metric_row_summary(question=question, row=row, columns=columns)
    if top_summary:
        return top_summary
    return ""


def count_row_summary(*, question: str, row: Dict[str, Any], columns: List[str]) -> str:
    if not question_requests_count(question):
        return ""
    if len(columns) != 1:
        return ""
    column = columns[0]
    value = row.get(column)
    if value in (None, ""):
        return ""
    return f"{column}: {format_cell(value)}."


def document_row_summary(*, question: str, row: Dict[str, Any]) -> str:
    number = first_value(row, ["Номер", "Number", "number"])
    date = first_value(row, ["Дата", "Date", "date", "Период"])
    amount_name, amount = first_named_value(row, amount_columns(row))
    document_ref = first_value(row, ["Ссылка", "Документ", "Document", "document"])

    if not (number or document_ref) or not (date or amount is not None):
        return ""

    subject = subject_from_question(question)
    intro = document_intro(question, subject, amount_name=amount_name)
    parts = []
    if number:
        parts.append(f"Это документ номер {format_cell(number)}")
    elif document_ref:
        parts.append(f"Это документ {format_cell(document_ref)}")

    formatted_date = format_date(date)
    if formatted_date:
        parts.append(f"от {formatted_date}")
    if amount is not None:
        parts.append(f"на сумму {format_cell(amount)}")
    if not parts:
        return ""
    return f"{intro} {' '.join(parts)}."


def top_metric_row_summary(*, question: str, row: Dict[str, Any], columns: List[str]) -> str:
    if not question_requests_top(question):
        return ""
    entity_column = first_existing_column(columns, ["Номенклатура", "Клиент", "Партнер", "Контрагент", "Склад", "Касса", "Документ"])
    metric_column = first_metric_column(columns, exclude={entity_column} if entity_column else set())
    if not entity_column or not metric_column:
        return ""
    entity = format_cell(row.get(entity_column, ""))
    metric = format_cell(row.get(metric_column, ""))
    if not entity or not metric:
        return ""
    return f"Найден результат с наибольшим значением показателя: {entity} — {metric}."


def table_prefix(*, question: str, rows: List[Dict[str, Any]]) -> str:
    count = len(rows)
    if question_requests_top(question):
        return "Нашел результаты, отсортированные по убыванию показателя:"
    if count == 1:
        return "Найдена одна строка:"
    return f"Найдено строк: {count}. Показываю первые {min(count, 10)}:"


def document_intro(question: str, subject: str, *, amount_name: str) -> str:
    lowered = question.lower()
    if amount_name and any(marker in lowered for marker in ["сам", "крупн", "больш", "максим"]):
        return f"Самый крупный по сумме {subject} найден в системе."
    return f"Найден {subject}."


def subject_from_question(question: str) -> str:
    lowered = question.lower()
    if "заказ" in lowered:
        return "заказ"
    if "поступлен" in lowered:
        return "документ поступления"
    if "реализац" in lowered:
        return "документ реализации"
    if "документ" in lowered:
        return "документ"
    return "документ"


def question_requests_top(question: str) -> bool:
    lowered = question.lower()
    return any(marker in lowered for marker in ["сам", "топ", "top", "крупн", "больш", "максим", "миним", "наибольш"])


def question_requests_count(question: str) -> bool:
    lowered = question.lower()
    return any(marker in lowered for marker in ["сколько", "количество", "число"])


def amount_columns(row: Dict[str, Any]) -> List[str]:
    result = []
    for column in row:
        lowered = column.lower()
        if "сумма" in lowered or "amount" in lowered:
            result.append(column)
    preferred = ["СуммаДокумента", "Сумма", "СуммаПродаж", "Amount"]
    return sorted(result, key=lambda item: preferred.index(item) if item in preferred else len(preferred))


def first_metric_column(columns: List[str], *, exclude: set[str]) -> str:
    preferred_markers = ["количество", "сумма", "остаток", "оборот", "выручка", "прибыль", "задолж"]
    for marker in preferred_markers:
        for column in columns:
            if column not in exclude and marker in column.lower():
                return column
    for column in columns:
        if column not in exclude:
            return column
    return ""


def first_existing_column(columns: List[str], candidates: List[str]) -> str:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return ""


def first_value(row: Dict[str, Any], keys: List[str]) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def first_named_value(row: Dict[str, Any], keys: List[str]) -> tuple[str, Any]:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return key, row[key]
    return "", None


def format_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = str(value)
    for pattern in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
        try:
            return datetime.strptime(text, pattern).strftime("%d.%m.%Y")
        except ValueError:
            continue
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return f"{match.group(3)}.{match.group(2)}.{match.group(1)}"
    return text


def render_table_preview(*, columns: List[str], rows: List[Dict[str, Any]], max_rows: int = 10) -> str:
    effective_columns = columns or sorted({key for row in rows for key in row})
    header = " | ".join(effective_columns)
    separator = " | ".join(["---"] * len(effective_columns))
    body = []
    for row in rows[:max_rows]:
        body.append(" | ".join(format_cell(row.get(column, "")) for column in effective_columns))
    return "\n".join([header, separator, *body])


def rows_effectively_empty(rows: List[Dict[str, Any]]) -> bool:
    if not rows:
        return True
    for row in rows:
        for value in row.values():
            if value not in (None, ""):
                return False
    return True


def format_cell(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("_objectRef"):
            return str(value.get("Представление") or value.get("УникальныйИдентификатор") or "")
        return "{" + ", ".join(f"{key}: {format_cell(item)}" for key, item in value.items()) + "}"
    if isinstance(value, list):
        return ", ".join(format_cell(item) for item in value)
    return str(value)

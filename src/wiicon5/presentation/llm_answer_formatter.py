from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping

from wiicon5.llm.client import LLMClient, LLMProviderError
from wiicon5.presentation.answer_formatter import format_cell


ANSWER_FORMAT_PROMPT = (
    "Ты формулируешь финальный ответ пользователю по уже полученным данным 1С. "
    "Не выполняй анализ заново и не меняй факты. Используй только user_question, query, columns, metric_hints и rows. "
    "Если число является агрегатом, объясни человеческим языком, что именно агрегировалось, опираясь на имя колонки и выражение в query "
    "(например СУММА(Количество) — суммарное количество единиц товара, КОЛИЧЕСТВО — количество строк/документов). "
    "Различай суммарное количество единиц товара, количество строк/документов и количество разных номенклатур. "
    "Если metric_hints содержит уточнение по колонке, используй его в формулировке ответа. "
    "Если смысл метрики неоднозначен, явно назови колонку и осторожно поясни, что это значение вернул запрос. "
    "Пиши кратко, по-русски, без markdown-таблицы для одной строки. Не добавляй данных, которых нет в rows. "
    "Верни строго JSON: answer (строка), reasoning (строка)."
)


@dataclass(frozen=True)
class LLMAnswerFormatResult:
    ok: bool
    answer: str = ""
    error: str = ""
    trace: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "answer": self.answer, "error": self.error, "trace": dict(self.trace)}


class LLMAnswerFormatter:
    def __init__(self, llm_client: LLMClient, *, max_rows: int = 10) -> None:
        self.llm_client = llm_client
        self.max_rows = max_rows

    def format(
        self,
        *,
        question: str,
        query: str,
        params: Mapping[str, Any],
        columns: List[str],
        rows: List[Dict[str, Any]],
        fallback_answer: str,
    ) -> LLMAnswerFormatResult:
        payload = {
            "user_question": question,
            "query": query,
            "params": dict(params),
            "columns": list(columns),
            "metric_hints": metric_hints_from_query(query, columns),
            "rows": normalize_rows(rows[: self.max_rows]),
            "fallback_answer": fallback_answer,
            "schema": {"answer": "short final user answer", "reasoning": "why this wording is correct"},
        }
        try:
            response = self.llm_client.complete_json(system_prompt=ANSWER_FORMAT_PROMPT, user_payload=payload)
        except LLMProviderError as exc:
            return LLMAnswerFormatResult(ok=False, error=f"LLM answer formatting failed: {exc}", trace={"request": payload})

        answer = str(response.get("answer") or "").strip()
        if not answer:
            return LLMAnswerFormatResult(
                ok=False,
                error="LLM answer formatting returned an empty answer.",
                trace={"request": payload, "response": response},
            )
        if not answer_mentions_result_fact(answer, rows):
            return LLMAnswerFormatResult(
                ok=False,
                error="LLM answer formatting did not mention any returned fact.",
                trace={"request": payload, "response": response},
            )
        return LLMAnswerFormatResult(ok=True, answer=answer, trace={"request": payload, "response": response})


def normalize_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    return [{str(key): format_cell(value) for key, value in row.items()} for row in rows]


def answer_mentions_result_fact(answer: str, rows: List[Dict[str, Any]]) -> bool:
    normalized_answer = answer.lower()
    for value in row_fact_values(rows):
        if value and value.lower() in normalized_answer:
            return True
    return False


def row_fact_values(rows: List[Dict[str, Any]]) -> List[str]:
    result: List[str] = []
    for row in rows[:3]:
        for value in row.values():
            formatted = format_cell(value).strip()
            if len(formatted) >= 2:
                result.append(formatted)
    return sorted(result, key=len, reverse=True)


def metric_hints_from_query(query: str, columns: List[str]) -> List[Dict[str, str]]:
    hints: List[Dict[str, str]] = []
    for column in columns:
        expression = expression_for_alias(query, column)
        if not expression:
            continue
        meaning = aggregate_meaning(expression)
        if meaning:
            hints.append({"column": column, "expression": expression, "meaning": meaning})
    return hints


def expression_for_alias(query: str, alias: str) -> str:
    pattern = re.compile(r"(?is)([^,\n]+?)\s+КАК\s+" + re.escape(alias) + r"\b")
    matches = [normalize_query_fragment(match.group(1)) for match in pattern.finditer(query)]
    aggregate_matches = [item for item in matches if contains_aggregate(item)]
    if aggregate_matches:
        return aggregate_matches[-1]
    return matches[-1] if matches else ""


def aggregate_meaning(expression: str) -> str:
    normalized = expression.lower()
    if "сумма(" in normalized:
        argument = aggregate_argument(expression, "СУММА")
        argument_lower = argument.lower()
        if "количество" in argument_lower:
            return (
                "суммарное количество единиц/штук по строкам запроса; "
                "это не количество разных номенклатур"
            )
        if "сумма" in argument_lower:
            return "суммарная денежная сумма по строкам запроса"
        return f"сумма значений выражения {argument}"
    if "количество(различные" in normalized:
        argument = aggregate_argument(expression, "КОЛИЧЕСТВО")
        argument = re.sub(r"(?is)^различные\s+", "", argument).strip()
        return f"количество разных уникальных значений {argument}"
    if "количество(" in normalized:
        argument = aggregate_argument(expression, "КОЛИЧЕСТВО")
        if argument == "*":
            return "количество строк результата до группировки"
        return f"количество непустых значений {argument}"
    if "максимум(" in normalized:
        return f"максимальное значение выражения {aggregate_argument(expression, 'МАКСИМУМ')}"
    if "минимум(" in normalized:
        return f"минимальное значение выражения {aggregate_argument(expression, 'МИНИМУМ')}"
    return ""


def aggregate_argument(expression: str, aggregate_name: str) -> str:
    match = re.search(re.escape(aggregate_name) + r"\s*\((.*)\)", expression, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return expression.strip()
    return normalize_query_fragment(match.group(1))


def contains_aggregate(expression: str) -> bool:
    lowered = expression.lower()
    return any(name in lowered for name in ["сумма(", "количество(", "максимум(", "минимум("])


def normalize_query_fragment(value: str) -> str:
    return " ".join(value.strip().split())

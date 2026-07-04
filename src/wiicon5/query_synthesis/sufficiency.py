from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from wiicon5.conversation.context import ConversationContext
from wiicon5.intent.models import IntentResult
from wiicon5.llm.client import LLMClient, LLMProviderError
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.presentation.answer_formatter import format_cell
from wiicon5.presentation.llm_answer_formatter import metric_hints_from_query


RESULT_SUFFICIENCY_PROMPT = (
    "Ты проверяешь, достаточно ли результата read-only запроса 1С для ответа на исходный вопрос пользователя. "
    "Не придумывай данные и не исправляй запрос. Нужно сравнить user_question/business_goal с columns/rows/current_query. "
    "Если результат содержит только промежуточный объект, ссылку, дату, список кандидатов или технический идентификатор, "
    "а в вопросе требуются другие факты, верни sufficient=false. "
    "Если reasoning текущего запроса говорит, что это только первый шаг, что дальше нужен другой запрос, или используются слова "
    "'сначала', 'далее потребуется', 'пока возвращаем', считай результат промежуточным. "
    "Если в вопросе спрашивают 'кому/кто' и 'сколько/какая сумма', ответ достаточен только когда результат содержит и субъект, "
    "и числовую сумму/количество/остаток, либо явно объясняет отсутствие данных. "
    "Если в вопросе спрашивают долг/задолженность/кому должны, сумма документа поставки сама по себе не равна задолженности, "
    "если это не подтверждено запросом или метаданными расчетов. "
    "Верни строго JSON: sufficient (bool), partial (bool), missing_facts (array of strings), "
    "next_query_goal (string), reasoning (string)."
)


@dataclass(frozen=True)
class ResultSufficiencyReview:
    sufficient: bool
    partial: bool = False
    missing_facts: List[str] = field(default_factory=list)
    next_query_goal: str = ""
    reasoning: str = ""
    error: str = ""
    trace: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sufficient": self.sufficient,
            "partial": self.partial,
            "missing_facts": list(self.missing_facts),
            "next_query_goal": self.next_query_goal,
            "reasoning": self.reasoning,
            "error": self.error,
            "trace": dict(self.trace),
        }


class ResultSufficiencyReviewer:
    def __init__(self, llm_client: LLMClient, *, max_rows: int = 5) -> None:
        self.llm_client = llm_client
        self.max_rows = max_rows

    def review(
        self,
        *,
        question: str,
        intent: IntentResult,
        goal: Optional[GoalDecomposition],
        context: ConversationContext,
        query: str,
        params: Mapping[str, Any],
        columns: List[str],
        rows: List[Dict[str, Any]],
        query_reasoning: str,
        previous_successful_steps: List[Dict[str, Any]],
    ) -> ResultSufficiencyReview:
        deterministic = deterministic_partial_review(
            question=question,
            columns=columns,
            rows=rows,
            query_reasoning=query_reasoning,
        )
        if deterministic is not None:
            return deterministic

        payload = {
            "user_question": question,
            "intent": intent.to_dict(),
            "goal": goal_to_payload(goal),
            "conversation_context": context.to_packet(),
            "current_query": query,
            "current_params": dict(params),
            "current_query_reasoning": query_reasoning,
            "columns": list(columns),
            "metric_hints": metric_hints_from_query(query, columns),
            "rows": normalize_rows_for_review(rows[: self.max_rows]),
            "previous_successful_steps": compact_steps(previous_successful_steps),
            "schema": {
                "sufficient": True,
                "partial": False,
                "missing_facts": ["fact"],
                "next_query_goal": "what to query next if insufficient",
                "reasoning": "short explanation",
            },
        }
        try:
            response = self.llm_client.complete_json(system_prompt=RESULT_SUFFICIENCY_PROMPT, user_payload=payload)
        except LLMProviderError as exc:
            return ResultSufficiencyReview(
                sufficient=True,
                error=f"LLM result sufficiency review failed: {exc}",
                trace={"request": payload},
            )

        sufficient = bool(response.get("sufficient"))
        partial = bool(response.get("partial")) or not sufficient
        missing = [str(item) for item in response.get("missing_facts", []) if str(item).strip()]
        next_goal = str(response.get("next_query_goal") or "").strip()
        reasoning = str(response.get("reasoning") or "").strip()
        return ResultSufficiencyReview(
            sufficient=sufficient,
            partial=partial,
            missing_facts=missing,
            next_query_goal=next_goal,
            reasoning=reasoning,
            trace={"request": payload, "response": response},
        )


def deterministic_partial_review(
    *,
    question: str,
    columns: List[str],
    rows: List[Dict[str, Any]],
    query_reasoning: str,
) -> Optional[ResultSufficiencyReview]:
    reasoning = query_reasoning.lower()
    partial_markers = [
        "пока возвращаем",
        "далее потребуется",
        "дальше потребуется",
        "потребуется дополнительный запрос",
        "в текущем запросе только",
        "только находим",
        "сначала нужно",
    ]
    if any(marker in reasoning for marker in partial_markers):
        return ResultSufficiencyReview(
            sufficient=False,
            partial=True,
            missing_facts=["Финальные факты из вопроса еще не получены."],
            next_query_goal="Построить следующий запрос по промежуточному результату и получить недостающие факты.",
            reasoning="Reasoning запроса явно описывает промежуточный шаг, а не финальный ответ.",
        )

    lowered_question = question.lower()
    lowered_columns = " ".join(columns).lower()
    if rows and asks_subject_and_amount(lowered_question):
        has_subject = any(marker in lowered_columns for marker in ["контрагент", "поставщик", "клиент", "партнер", "партнёр"])
        has_debt_metric = any(marker in lowered_columns for marker in ["задолж", "долг", "к оплате", "коплате"])
        has_amount = has_debt_metric or any(
            marker in lowered_columns for marker in ["сумма", "остаток", "количество", "amount", "balance"]
        )
        if has_subject and has_debt_metric:
            return ResultSufficiencyReview(
                sufficient=True,
                partial=False,
                reasoning=(
                    "Результат содержит субъект и долговую метрику. "
                    "Пустое значение долговой метрики является данными результата и может быть сформулировано как отсутствие найденного долга."
                ),
            )
        if asks_debt(lowered_question) and has_subject and has_amount and not has_debt_metric:
            return ResultSufficiencyReview(
                sufficient=False,
                partial=True,
                missing_facts=["Сумма задолженности/долга не получена; сумма документа не является долгом."],
                next_query_goal="Получить фактическую задолженность или долговую метрику по найденному субъекту/документу.",
                reasoning="Для долгового вопроса нужна долговая метрика, а не произвольная сумма.",
            )
        if not (has_subject and has_amount):
            return ResultSufficiencyReview(
                sufficient=False,
                partial=True,
                missing_facts=["Субъект и сумма/задолженность не получены в одном достаточном результате."],
                next_query_goal="Получить недостающий субъект и сумму/задолженность по найденному промежуточному объекту.",
                reasoning="Вопрос требует субъект и сумму, но текущие колонки не покрывают оба факта.",
            )
    return None


def asks_subject_and_amount(question: str) -> bool:
    subject_markers = ["кому", "кто", "контрагент", "поставщик", "клиент", "партнер", "партнёр"]
    amount_markers = ["сколько", "сумма", "долг", "долж", "задолж"]
    return any(marker in question for marker in subject_markers) and any(marker in question for marker in amount_markers)


def asks_debt(question: str) -> bool:
    return any(marker in question for marker in ["долг", "долж", "задолж"])


def normalize_rows_for_review(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{str(key): normalize_value(value) for key, value in row.items()} for row in rows]


def normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        if value.get("_objectRef"):
            return {
                "_objectRef": True,
                "ТипОбъекта": value.get("ТипОбъекта"),
                "УникальныйИдентификатор": value.get("УникальныйИдентификатор"),
                "Представление": value.get("Представление"),
            }
        return {str(key): normalize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_value(item) for item in value]
    return format_cell(value)


def compact_steps(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for step in steps[-3:]:
        result.append(
            {
                "step": step.get("step"),
                "query": step.get("query"),
                "params": step.get("params"),
                "columns": step.get("columns"),
                "rows": normalize_rows_for_review(list(step.get("rows") or [])[:5]),
                "sufficiency": step.get("sufficiency"),
            }
        )
    return result


def goal_to_payload(goal: Optional[GoalDecomposition]) -> Optional[Dict[str, Any]]:
    if goal is None:
        return None
    return {
        "business_goal": goal.business_goal,
        "final_artifact_type": goal.final_artifact_type,
        "expected_answer_type": goal.expected_answer_type,
        "required_artifacts": [item.to_dict() for item in goal.required_artifacts],
    }

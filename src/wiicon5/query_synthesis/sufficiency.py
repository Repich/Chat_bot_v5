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
    "Если пользователь спрашивает клиента/контрагента/поставщика, а результат в такой колонке содержит договор, объект расчетов "
    "или другой промежуточный объект вместо самой стороны расчетов, результат недостаточен. "
    "Если вопрос пользователя допускает два бизнес-смысла, а текущий результат покрывает только один из них, "
    "не выбирай смысл за пользователя: верни needs_clarification=true и короткий уточняющий вопрос с вариантами. "
    "Верни строго JSON: sufficient (bool), partial (bool), missing_facts (array of strings), "
    "next_query_goal (string), needs_clarification (bool), clarification_question (string), "
    "clarification_options (array of strings), reasoning (string)."
)


@dataclass(frozen=True)
class ResultSufficiencyReview:
    sufficient: bool
    partial: bool = False
    missing_facts: List[str] = field(default_factory=list)
    next_query_goal: str = ""
    needs_clarification: bool = False
    clarification_question: str = ""
    clarification_options: List[str] = field(default_factory=list)
    reasoning: str = ""
    error: str = ""
    trace: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sufficient": self.sufficient,
            "partial": self.partial,
            "missing_facts": list(self.missing_facts),
            "next_query_goal": self.next_query_goal,
            "needs_clarification": self.needs_clarification,
            "clarification_question": self.clarification_question,
            "clarification_options": list(self.clarification_options),
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
                "needs_clarification": False,
                "clarification_question": "question to user if ambiguous",
                "clarification_options": ["option 1", "option 2"],
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
        needs_clarification = bool(response.get("needs_clarification"))
        clarification_question = str(response.get("clarification_question") or "").strip()
        clarification_options = [
            str(item).strip()
            for item in response.get("clarification_options", []) or []
            if str(item).strip()
        ]
        reasoning = str(response.get("reasoning") or "").strip()
        return ResultSufficiencyReview(
            sufficient=sufficient,
            partial=partial,
            missing_facts=missing,
            next_query_goal=next_goal,
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
            clarification_options=clarification_options,
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
        subject_ref_mismatch = subject_reference_mismatch_review(
            question=lowered_question,
            columns=columns,
            rows=rows,
        )
        if subject_ref_mismatch is not None:
            return subject_ref_mismatch
        has_subject = has_subject_evidence(question=lowered_question, columns=columns, rows=rows)
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
            if needs_amount_vs_debt_clarification(lowered_question):
                return ResultSufficiencyReview(
                    sufficient=False,
                    partial=True,
                    missing_facts=[
                        "Неясно, пользователь хочет сумму документа или фактическую задолженность по расчетам."
                    ],
                    next_query_goal=(
                        "После уточнения либо вернуть найденную сумму документа, либо получить фактическую "
                        "задолженность по регистрам расчетов."
                    ),
                    needs_clarification=True,
                    clarification_question=(
                        "Уточните, что именно показать: сумму последней отгрузки по документу "
                        "или фактическую задолженность клиента после оплат и зачетов?"
                    ),
                    clarification_options=[
                        "Сумму последней отгрузки по документу",
                        "Фактическую задолженность клиента",
                    ],
                    reasoning=(
                        "Фраза с 'должен/должны за документ' может означать как сумму документа, "
                        "так и задолженность. Нельзя выбирать бизнес-смысл без пользователя."
                    ),
                )
            return ResultSufficiencyReview(
                sufficient=False,
                partial=True,
                missing_facts=["Сумма задолженности/долга не получена; сумма документа не является долгом."],
                next_query_goal="Получить фактическую задолженность или долговую метрику по найденному субъекту/документу.",
                reasoning="Для долгового вопроса нужна долговая метрика, а не произвольная сумма.",
            )
        if asks_debt(lowered_question) and has_subject and not has_amount and needs_amount_vs_debt_clarification(
            lowered_question
        ):
            return ResultSufficiencyReview(
                sufficient=False,
                partial=True,
                missing_facts=[
                    "Найден субъект или документ, но неясно, нужна сумма документа или фактическая задолженность."
                ],
                next_query_goal=(
                    "После уточнения либо получить/вернуть сумму документа, либо получить фактическую "
                    "задолженность по регистрам расчетов."
                ),
                needs_clarification=True,
                clarification_question=(
                    "Уточните, что именно показать: сумму последней отгрузки по документу "
                    "или фактическую задолженность клиента после оплат и зачетов?"
                ),
                clarification_options=[
                    "Сумму последней отгрузки по документу",
                    "Фактическую задолженность клиента",
                ],
                reasoning=(
                    "Фраза с 'должен/должны за документ' может означать сумму документа или задолженность. "
                    "Нельзя выбирать показатель без пользователя."
                ),
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


def has_subject_evidence(*, question: str, columns: List[str], rows: List[Dict[str, Any]]) -> bool:
    lowered_columns = " ".join(columns).lower()
    if any(marker in lowered_columns for marker in ["контрагент", "поставщик", "клиент", "партнер", "партнёр"]):
        return True
    if rows_have_subject_object_ref(question=question, rows=rows):
        return True
    return rows_have_party_requisites(question=question, columns=columns, rows=rows)


def subject_reference_mismatch_review(
    *,
    question: str,
    columns: List[str],
    rows: List[Dict[str, Any]],
) -> Optional[ResultSufficiencyReview]:
    if asks_intermediate_subject(question):
        return None
    subject_columns = party_subject_columns(question=question, columns=columns)
    if not subject_columns:
        return None

    expected_markers = subject_reference_markers(question)
    mismatches: List[str] = []
    for row in rows:
        for column in subject_columns:
            for ref in object_refs(row.get(column)):
                object_type = str(ref.get("ТипОбъекта") or "").lower()
                presentation = str(ref.get("Представление") or "").lower()
                if compatible_subject_ref(object_type=object_type, expected_markers=expected_markers):
                    continue
                if known_intermediate_subject_ref(object_type=object_type, presentation=presentation):
                    label = str(ref.get("Представление") or ref.get("ТипОбъекта") or "").strip()
                    mismatches.append(f"{column}: {label}")

    if not mismatches:
        return None

    return ResultSufficiencyReview(
        sufficient=False,
        partial=True,
        missing_facts=[
            "Получен промежуточный объект расчетов/договор, а не сам клиент/контрагент."
        ],
        next_query_goal=(
            "Построить запрос, который связывает найденную аналитику расчетов с фактическим клиентом, "
            "контрагентом или партнером, и вернуть эту сторону расчетов вместе с долговой метрикой."
        ),
        reasoning=(
            "Название колонки не является доказательством бизнес-сущности: значение в субъектной колонке "
            f"имеет несовместимый тип ссылки ({'; '.join(mismatches[:3])})."
        ),
        trace={"subject_reference_mismatches": mismatches[:5]},
    )


def asks_intermediate_subject(question: str) -> bool:
    return any(marker in question for marker in ["договор", "объект расчет", "объект расчёт", "аналитик"])


def party_subject_columns(*, question: str, columns: List[str]) -> List[str]:
    if not any(
        marker in question
        for marker in ["клиент", "контрагент", "поставщик", "покупател", "партнер", "партнёр", "кому", "кто"]
    ):
        return []
    column_markers = ["клиент", "контрагент", "поставщик", "покупател", "партнер", "партнёр"]
    return [column for column in columns if any(marker in column.lower() for marker in column_markers)]


def object_refs(value: Any):
    for item in walk_values(value):
        if isinstance(item, dict) and item.get("_objectRef"):
            yield item


def compatible_subject_ref(*, object_type: str, expected_markers: List[str]) -> bool:
    return any(marker in object_type for marker in expected_markers)


def known_intermediate_subject_ref(*, object_type: str, presentation: str) -> bool:
    combined = f"{object_type} {presentation}"
    return any(
        marker in combined
        for marker in [
            "договор",
            "объектырасчетов",
            "объектырасчётов",
            "объект расчет",
            "объект расчёт",
            "соглашение",
            "документссылка",
        ]
    )


def rows_have_subject_object_ref(*, question: str, rows: List[Dict[str, Any]]) -> bool:
    markers = subject_reference_markers(question)
    for row in rows:
        for value in walk_values(row):
            if not isinstance(value, dict) or not value.get("_objectRef"):
                continue
            object_type = str(value.get("ТипОбъекта") or "").lower()
            if "справочникссылка" not in object_type:
                continue
            if any(marker in object_type for marker in markers):
                return True
    return False


def subject_reference_markers(question: str) -> List[str]:
    markers: List[str] = []
    if any(marker in question for marker in ["клиент", "контрагент", "поставщик", "покупател"]):
        markers.extend(["контрагент", "партнер", "партнёр"])
    if any(marker in question for marker in ["партнер", "партнёр"]):
        markers.extend(["партнер", "партнёр", "контрагент"])
    if any(marker in question for marker in ["кому", "кто"]):
        markers.extend(["контрагент", "партнер", "партнёр", "организац", "физическ", "сотрудник"])
    if not markers:
        markers.extend(["контрагент", "партнер", "партнёр"])
    result: List[str] = []
    for marker in markers:
        if marker not in result:
            result.append(marker)
    return result


def rows_have_party_requisites(*, question: str, columns: List[str], rows: List[Dict[str, Any]]) -> bool:
    if not any(marker in question for marker in ["клиент", "контрагент", "поставщик", "партнер", "партнёр", "кому", "кто"]):
        return False
    name_columns = columns_matching(columns, ["наименование", "наименованиеполное"])
    party_id_columns = columns_matching(columns, ["инн", "кпп", "регистрационныйномер", "налоговыйномер"])
    if not (name_columns and party_id_columns):
        return False
    for row in rows:
        has_name_value = any(str(row.get(column) or "").strip() for column in name_columns)
        has_party_id_value = any(str(row.get(column) or "").strip() for column in party_id_columns)
        if has_name_value and has_party_id_value:
            return True
    return False


def columns_matching(columns: List[str], expected: List[str]) -> List[str]:
    lowered_expected = {item.lower() for item in expected}
    return [column for column in columns if column.lower() in lowered_expected]


def walk_values(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_values(item)


def asks_debt(question: str) -> bool:
    return any(marker in question for marker in ["долг", "долж", "задолж"])


def needs_amount_vs_debt_clarification(question: str) -> bool:
    explicit_debt_markers = ["задолж", "дебитор", "кредитор", "долг"]
    if any(marker in question for marker in explicit_debt_markers):
        return False
    return "долж" in question


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

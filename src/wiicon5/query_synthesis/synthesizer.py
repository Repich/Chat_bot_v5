from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from wiicon5.conversation.context import ConversationContext
from wiicon5.execution.artifacts import Artifact
from wiicon5.intent.models import IntentResult
from wiicon5.knowledge.metadata import MetadataObject, MetadataProvider
from wiicon5.llm.client import LLMClient, LLMProviderError
from wiicon5.mcp.client import McpClient
from wiicon5.mcp.contracts import McpQueryRequest, normalize_mcp_rows
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.presentation.answer_formatter import format_user_answer, rows_effectively_empty
from wiicon5.presentation.llm_answer_formatter import LLMAnswerFormatter
from wiicon5.query.one_c_query_safety import validate_read_only_query
from wiicon5.query.one_c_query_review import OneCQueryReviewer
from wiicon5.query.reference_value_resolver import ReferenceValueResolver


DISCOVERY_PROMPT = (
    "Ты агент WIICON ChatBot 5. Нужно ответить на вопрос пользователя по данным 1С неизвестной конфигурации. "
    "Сначала предложи план поиска метаданных и гипотезу запроса. Не пиши финальный ответ пользователю. "
    "Не подгоняй вопрос под существующие навыки или typed artifacts из failed planning; это диагностический контекст, "
    "а не источник истины. Если goal/gaps конфликтуют с текстом пользователя, доверяй тексту пользователя и метаданным. "
    "Верни строго JSON: metadata_search_terms (массив строк), hypothesis (строка), draft_query (строка, можно пусто). "
    "Термины должны помогать найти объекты метаданных 1С: регистры, документы, справочники, измерения, ресурсы."
)


QUERY_PROMPT = (
    "Ты составляешь read-only запрос на языке запросов 1С по вопросу пользователя. "
    "Конфигурация неизвестна, но тебе переданы найденные метаданные. "
    "Не подгоняй запрос под старые навыки или typed artifacts из failed planning; goal/gaps используй только как подсказку об ошибке. "
    "Если typed artifact противоречит пользовательскому вопросу, игнорируй artifact и строй запрос по смыслу вопроса. "
    "Используй только объекты и поля, подтвержденные metadata_objects. "
    "Для вопросов с рейтингом, топом, максимумом/минимумом, суммой, количеством или группировкой возвращай агрегирующий запрос, "
    "а не сырой список документов. "
    "Если используешь табличную часть документа, бери поля только из metadata_objects.table_parts или из отдельного metadata object "
    "полного имени Документ.<Имя>.<ТабличнаяЧасть>. "
    "Если previous_query_review сообщает source_not_confirmed_by_metadata, не повторяй этот источник; выбери другой источник "
    "из metadata_objects или перестрой запрос через подтвержденный документ/регистр. "
    "Если previous_query_review сообщает document_table_part_without_document_ref, соедини табличную часть с шапкой документа "
    "по <ТабличнаяЧасть>.Ссылка = <Документ>.Ссылка; для фактов продаж/движений обычно добавь фильтр <Документ>.Проведен. "
    "Если previous_query_review сообщает reference_filter_string_param, не сравнивай ссылочное поле со строкой. "
    "Либо сначала найди/передай ссылку, либо сравнивай реквизит ссылки, например <Алиас>.<Поле>.Наименование = &Параметр. "
    "Если previous_query_review сообщает enum_value_not_confirmed_by_metadata, не придумывай ЗНАЧЕНИЕ(Перечисление.X.Y); "
    "сначала получи реальные значения поля или перестрой запрос так, чтобы вернуть группировку по этому полю и его представлению. "
    "Можно использовать виртуальные таблицы регистров накопления, например .Остатки(), если объект является регистром накопления "
    "и в метаданных есть подходящие измерения/ресурсы. Для виртуальной таблицы Остатки ресурс Ресурс обычно читается как РесурсОстаток. "
    "Запрещены любые операции изменения данных. Запрос должен начинаться с ВЫБРАТЬ. "
    "Верни строго JSON: query (строка), params (объект), limit (число), reasoning (строка)."
)


METADATA_REPAIR_PROMPT = (
    "Предыдущий read-only запрос 1С не выполнился из-за отсутствующей таблицы или поля. "
    "Нужно не чинить запрос напрямую, а предложить дополнительные термины поиска метаданных. "
    "Используй текст пользователя, ошибку 1С, предыдущий запрос и уже найденные metadata_objects. "
    "Добавляй синонимы из типовой терминологии 1С, например для долгов клиентов ищи также расчеты с клиентами/контрагентами. "
    "Верни строго JSON: metadata_search_terms (массив строк), reasoning (строка)."
)

QUERYABLE_OBJECT_PREFIXES = (
    "РегистрНакопления.",
    "РегистрСведений.",
    "Документ.",
    "Справочник.",
)

NON_QUERY_SOURCE_PREFIXES = (
    "ОбщийМодуль.",
    "Обработка.",
    "Отчет.",
    "Константа.",
    "ОбщаяКоманда.",
    "ОбщаяФорма.",
    "ОбщаяКартинка.",
    "ОпределяемыйТип.",
)


@dataclass(frozen=True)
class QuerySynthesisResult:
    ok: bool
    final_artifact: Optional[Artifact] = None
    message: str = ""
    error: str = ""
    trace: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "error": self.error,
            "final_artifact": self.final_artifact.to_dict() if self.final_artifact else None,
            "trace": dict(self.trace),
        }


class QuerySynthesisEngine:
    def __init__(
        self,
        *,
        llm_client: LLMClient,
        metadata_provider: MetadataProvider,
        mcp_client: McpClient,
        query_reviewer: Optional[OneCQueryReviewer] = None,
        answer_formatter: Optional[LLMAnswerFormatter] = None,
        max_metadata_objects: int = 12,
        max_repair_attempts: int = 2,
    ) -> None:
        self.llm_client = llm_client
        self.metadata_provider = metadata_provider
        self.mcp_client = mcp_client
        self.query_reviewer = query_reviewer or OneCQueryReviewer()
        self.answer_formatter = answer_formatter
        self.max_metadata_objects = max_metadata_objects
        self.max_repair_attempts = max_repair_attempts

    def run(
        self,
        *,
        message: str,
        intent: IntentResult,
        goal: Optional[GoalDecomposition],
        context: ConversationContext,
        gaps: List[Dict[str, Any]],
    ) -> QuerySynthesisResult:
        trace: Dict[str, Any] = {"gaps": list(gaps)}
        reset_metadata_request_log(self.metadata_provider)
        try:
            discovery = self.llm_client.complete_json(
                system_prompt=DISCOVERY_PROMPT,
                user_payload={
                    "message": message,
                    "intent": intent.to_dict(),
                    "goal": goal_to_payload(goal),
                    "conversation_context": context.to_packet(),
                    "gaps": gaps,
                    "schema": {
                        "metadata_search_terms": ["term"],
                        "hypothesis": "short hypothesis",
                        "draft_query": "optional 1C query hypothesis",
                    },
                },
            )
        except LLMProviderError as exc:
            return QuerySynthesisResult(ok=False, error=f"LLM discovery failed: {exc}", trace=trace)

        trace["discovery_response"] = discovery
        search_terms = search_terms_from_discovery(discovery, intent, message)
        metadata_objects = collect_metadata_objects(
            self.metadata_provider,
            search_terms=search_terms,
            max_objects=self.max_metadata_objects,
        )
        trace["metadata_search_terms"] = search_terms
        trace["metadata_requests"] = getattr(self.metadata_provider, "last_requests", [])
        trace["metadata_objects"] = [metadata_object_summary(item) for item in metadata_objects]
        if not metadata_objects:
            return QuerySynthesisResult(ok=False, error="Metadata search returned no objects.", trace=trace)

        previous_error = ""
        previous_query = ""
        previous_review: Dict[str, Any] = {}
        query_review_guidance = self.query_reviewer.guidance()
        trace["query_review_guidance"] = query_review_guidance
        for attempt in range(1, self.max_repair_attempts + 2):
            try:
                query_response = self.llm_client.complete_json(
                    system_prompt=QUERY_PROMPT,
                    user_payload={
                        "message": message,
                        "intent": intent.to_dict(),
                        "goal": goal_to_payload(goal),
                        "conversation_context": context.to_packet(),
                        "metadata_objects": [metadata_object_summary(item) for item in metadata_objects],
                        "hypothesis": discovery.get("hypothesis"),
                        "draft_query": discovery.get("draft_query"),
                        "previous_error": previous_error,
                        "previous_query": previous_query,
                        "previous_query_review": previous_review,
                        "query_review_rules": query_review_guidance,
                        "attempt": attempt,
                        "schema": {"query": "1C query text", "params": {}, "limit": 100, "reasoning": "why this query"},
                    },
                )
            except LLMProviderError as exc:
                return QuerySynthesisResult(ok=False, error=f"LLM query synthesis failed: {exc}", trace=trace)

            raw_query = str(query_response.get("query") or "").strip()
            query = postprocess_1c_query(raw_query)
            params = query_response.get("params") if isinstance(query_response.get("params"), dict) else {}
            limit = limit_from_value(query_response.get("limit"))
            attempt_trace = {
                "attempt": attempt,
                "query_response": query_response,
                "raw_query": raw_query,
                "query": query,
                "params": dict(params),
                "limit": limit,
            }
            trace.setdefault("attempts", []).append(attempt_trace)

            validation = validate_read_only_query(query, params)
            attempt_trace["validation"] = validation.to_dict()
            if not validation.ok:
                previous_error = "Query validation failed: " + "; ".join(issue.message for issue in validation.issues)
                previous_query = query
                attempt_trace["error"] = previous_error
                continue

            reference_resolution = ReferenceValueResolver(self.mcp_client).resolve(
                query=query,
                params=params,
                metadata_objects=metadata_objects,
            )
            attempt_trace["reference_value_resolution"] = reference_resolution.to_dict()
            if reference_resolution.changed:
                query = reference_resolution.query
                params = reference_resolution.params
                attempt_trace["query"] = query
                attempt_trace["params"] = dict(params)
                validation = validate_read_only_query(query, params)
                attempt_trace["validation_after_reference_resolution"] = validation.to_dict()
                if not validation.ok:
                    previous_error = "Query validation failed after reference value resolution: " + "; ".join(
                        issue.message for issue in validation.issues
                    )
                    previous_query = query
                    attempt_trace["error"] = previous_error
                    continue

            query_review = self.query_reviewer.review(
                query=query,
                params=params,
                metadata_objects=metadata_objects,
            )
            attempt_trace["query_review"] = query_review.to_dict()
            if not query_review.ok:
                previous_error = "Query review failed: " + query_review.error_text()
                previous_query = query
                previous_review = query_review.to_dict()
                attempt_trace["error"] = previous_error
                extra_terms = metadata_terms_from_query_review(query_review)
                if extra_terms:
                    attempt_trace["metadata_repair_terms"] = extra_terms
                    combined_terms = merge_terms(trace["metadata_search_terms"], extra_terms)
                    metadata_objects = merge_metadata_objects(
                        metadata_objects,
                        collect_metadata_objects(
                            self.metadata_provider,
                            search_terms=extra_terms,
                            max_objects=self.max_metadata_objects,
                        ),
                    )
                    metadata_objects = rank_metadata_objects(
                        metadata_objects,
                        search_terms=combined_terms,
                        max_objects=self.max_metadata_objects,
                    )
                    trace["metadata_search_terms"] = combined_terms
                    trace["metadata_requests"] = getattr(self.metadata_provider, "last_requests", [])
                    trace["metadata_objects"] = [metadata_object_summary(item) for item in metadata_objects]
                continue
            previous_review = query_review.to_dict()

            response = self.mcp_client.execute_query(McpQueryRequest(query=query, params=params, limit=limit))
            rows = normalize_mcp_rows(response)
            attempt_trace["mcp_response"] = response.raw
            attempt_trace["row_count"] = len(rows)
            if not response.success:
                previous_error = response.error or "MCP query failed."
                previous_query = query
                attempt_trace["error"] = previous_error
                extra_terms = self._metadata_repair_terms(
                    message=message,
                    intent=intent,
                    goal=goal,
                    context=context,
                    metadata_objects=metadata_objects,
                    previous_query=previous_query,
                    previous_error=previous_error,
                    attempt=attempt,
                )
                if extra_terms:
                    attempt_trace["metadata_repair_terms"] = extra_terms
                    combined_terms = merge_terms(trace["metadata_search_terms"], extra_terms)
                    metadata_objects = merge_metadata_objects(
                        metadata_objects,
                        collect_metadata_objects(
                            self.metadata_provider,
                            search_terms=extra_terms,
                            max_objects=self.max_metadata_objects,
                        ),
                    )
                    metadata_objects = rank_metadata_objects(
                        metadata_objects,
                        search_terms=combined_terms,
                        max_objects=self.max_metadata_objects,
                    )
                    trace["metadata_search_terms"] = combined_terms
                    trace["metadata_requests"] = getattr(self.metadata_provider, "last_requests", [])
                    trace["metadata_objects"] = [metadata_object_summary(item) for item in metadata_objects]
                continue

            columns = columns_from_rows(rows)
            answer = "Данных не найдено." if rows_effectively_empty(rows) else format_user_answer(
                question=message,
                columns=columns,
                rows=rows,
            )
            if self.answer_formatter is not None and not rows_effectively_empty(rows):
                formatted = self.answer_formatter.format(
                    question=message,
                    query=query,
                    params=params,
                    columns=columns,
                    rows=rows,
                    fallback_answer=answer,
                )
                trace["answer_formatting"] = formatted.to_dict()
                if formatted.ok:
                    answer = formatted.answer
            artifact = Artifact(
                name="answer",
                type="UserAnswer",
                value=answer,
                provenance=["query_synthesis"],
            )
            trace["final_query"] = {"query": query, "params": dict(params), "limit": limit}
            trace["row_count"] = len(rows)
            return QuerySynthesisResult(ok=True, final_artifact=artifact, message=answer, trace=trace)

        return QuerySynthesisResult(ok=False, error=previous_error or "Query synthesis failed.", trace=trace)

    def _metadata_repair_terms(
        self,
        *,
        message: str,
        intent: IntentResult,
        goal: Optional[GoalDecomposition],
        context: ConversationContext,
        metadata_objects: List[MetadataObject],
        previous_query: str,
        previous_error: str,
        attempt: int,
    ) -> List[str]:
        if not should_expand_metadata(previous_error):
            return []
        try:
            response = self.llm_client.complete_json(
                system_prompt=METADATA_REPAIR_PROMPT,
                user_payload={
                    "message": message,
                    "intent": intent.to_dict(),
                    "goal": goal_to_payload(goal),
                    "conversation_context": context.to_packet(),
                    "metadata_objects": [metadata_object_summary(item) for item in metadata_objects],
                    "previous_query": previous_query,
                    "previous_error": previous_error,
                    "attempt": attempt,
                    "schema": {"metadata_search_terms": ["term"], "reasoning": "why these terms"},
                },
            )
        except LLMProviderError:
            return []
        terms: List[str] = []
        for item in response.get("metadata_search_terms", []) or []:
            add_unique(terms, str(item).strip())
        return terms[:8]


def collect_metadata_objects(
    metadata_provider: MetadataProvider,
    *,
    search_terms: List[str],
    max_objects: int,
) -> List[MetadataObject]:
    candidates: Dict[str, MetadataObject] = {}
    for term in search_terms:
        if looks_like_full_1c_name(term):
            direct = metadata_provider.get_object(term)
            if direct.raw:
                candidates[direct.full_name] = direct
        for item in metadata_provider.search_objects(term):
            if item.full_name and item.full_name not in candidates:
                candidates[item.full_name] = item

    queryable_candidates = {
        name: item
        for name, item in candidates.items()
        if name.startswith(QUERYABLE_OBJECT_PREFIXES)
    }
    if queryable_candidates:
        candidates = queryable_candidates

    ranked_names = [item.full_name for item in rank_metadata_objects(list(candidates.values()), search_terms, len(candidates))]
    result: List[MetadataObject] = []
    for name in ranked_names[:max_objects]:
        item = candidates[name]
        if item.raw and detailed_enough(item):
            result.append(item)
        else:
            detailed = metadata_provider.get_object(name)
            if detailed.raw:
                result.append(detailed)
    return result


def rank_metadata_objects(
    objects: List[MetadataObject],
    search_terms: List[str],
    max_objects: int,
) -> List[MetadataObject]:
    return sorted(
        objects,
        key=lambda item: (-metadata_candidate_score(item, search_terms), item.full_name),
    )[:max_objects]


def metadata_candidate_score(item: MetadataObject, search_terms: List[str]) -> int:
    full_name = item.full_name
    text = " ".join([full_name, item.synonym]).lower()
    score = 0
    if full_name.startswith("РегистрНакопления."):
        score += 100
    elif full_name.startswith("РегистрСведений."):
        score += 80
    elif full_name.startswith("Документ."):
        score += 70
    elif full_name.startswith("Справочник."):
        score += 60
    elif full_name.startswith(NON_QUERY_SOURCE_PREFIXES):
        score -= 100
    for term in search_terms:
        normalized = term.lower().strip()
        if not normalized:
            continue
        if normalized == full_name.lower():
            score += 120
        elif normalized in text:
            score += 15
        else:
            for word in normalized.split():
                if len(word) >= 4 and word in text:
                    score += 3
    return score


def looks_like_full_1c_name(term: str) -> bool:
    return term.startswith(QUERYABLE_OBJECT_PREFIXES)


def detailed_enough(item: MetadataObject) -> bool:
    return any(key in item.raw for key in ["Реквизиты", "Измерения", "Ресурсы", "СтандартныеРеквизиты", "ТабличныеЧасти"])


def merge_metadata_objects(left: List[MetadataObject], right: List[MetadataObject]) -> List[MetadataObject]:
    by_name: Dict[str, MetadataObject] = {}
    for item in [*left, *right]:
        if item.full_name and item.full_name not in by_name:
            by_name[item.full_name] = item
    return list(by_name.values())


def merge_terms(left: List[str], right: List[str]) -> List[str]:
    result = list(left)
    for item in right:
        add_unique(result, item)
    return result


def should_expand_metadata(error: str) -> bool:
    lowered = error.lower()
    return any(
        marker in lowered
        for marker in ["таблица не найдена", "поле не найдено", "не подтверждено метаданными", "field_not_confirmed"]
    )


def reset_metadata_request_log(metadata_provider: MetadataProvider) -> None:
    if hasattr(metadata_provider, "last_requests"):
        try:
            metadata_provider.last_requests = []  # type: ignore[attr-defined]
        except Exception:
            return


def search_terms_from_discovery(discovery: Dict[str, Any], intent: IntentResult, message: str) -> List[str]:
    terms: List[str] = []
    for item in intent.domain_terms:
        add_unique(terms, str(item).strip())
    for word in message.replace(",", " ").split():
        if len(word) >= 5:
            add_unique(terms, word.strip())
    for item in discovery.get("metadata_search_terms", []) or []:
        add_unique(terms, str(item).strip())
    return expand_metadata_search_terms(terms)[:30]


def expand_metadata_search_terms(terms: List[str]) -> List[str]:
    result = list(terms)
    text = " ".join(terms).lower()
    if "номенклатур" in text:
        add_unique(result, "Справочник.Номенклатура")
    if any(marker in text for marker in ["продаж", "прода", "реализац"]):
        add_unique(result, "реализация")
        add_unique(result, "Реализация товаров")
        add_unique(result, "РеализацияТоваровУслуг")
        add_unique(result, "Документ.РеализацияТоваровУслуг")
        add_unique(result, "ВыручкаИСебестоимостьПродаж")
        add_unique(result, "РегистрНакопления.ВыручкаИСебестоимостьПродаж")
    return result


def metadata_object_summary(item: MetadataObject) -> Dict[str, Any]:
    return {
        "full_name": item.full_name,
        "synonym": item.synonym,
        "fields": list(item.fields),
        "table_parts": table_parts_summary(item),
        "field_details": {
            name: {
                key: value
                for key, value in details.items()
                if key in {"Имя", "Синоним", "Тип", "_category", "name", "synonym", "type"}
            }
            for name, details in item.field_details.items()
        },
    }


def table_parts_summary(item: MetadataObject) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for name, details in item.field_details.items():
        if details.get("_category") != "table_part":
            continue
        nested = details.get("_nested_fields")
        result[name] = {
            "fields": list(nested) if isinstance(nested, list) else [],
        }
    return result


def metadata_terms_from_query_review(query_review) -> List[str]:
    terms: List[str] = []
    for source in getattr(query_review, "sources", []) or []:
        if getattr(source, "table_part", ""):
            add_unique(terms, source.source)
            add_unique(terms, f"{source.object_full_name}.{source.table_part}")
            add_unique(terms, f"{source.object_full_name} {source.table_part}")
        elif getattr(source, "object_full_name", ""):
            add_unique(terms, source.object_full_name)
    return terms[:8]


def goal_to_payload(goal: Optional[GoalDecomposition]) -> Optional[Dict[str, Any]]:
    if goal is None:
        return None
    return {
        "business_goal": goal.business_goal,
        "final_artifact_type": goal.final_artifact_type,
        "expected_answer_type": goal.expected_answer_type,
        "required_artifacts": [item.to_dict() for item in goal.required_artifacts],
    }


def columns_from_rows(rows: List[Dict[str, Any]]) -> List[str]:
    columns: List[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns


def limit_from_value(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 100
    return max(1, min(number, 1000))


def add_unique(items: List[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def postprocess_1c_query(query: str) -> str:
    text = query.strip()
    text = re.sub(r"\.Остатки\(\s*,\s*,\s*\)", ".Остатки()", text, flags=re.IGNORECASE)
    text = re.sub(r"\.Остатки\(\s*,\s*\)", ".Остатки()", text, flags=re.IGNORECASE)
    text = re.sub(
        r"(\bРегистрНакопления\.[A-Za-zА-Яа-яЁё0-9_]+)\.(ОстаткиИОбороты|Остатки|Обороты)(\s+КАК\b)",
        r"\1.\2()\3",
        text,
        flags=re.IGNORECASE,
    )
    text = remove_redundant_reference_joins(text)
    return text


def remove_redundant_reference_joins(query: str) -> str:
    pattern = re.compile(
        r"\s+(?:ВНУТРЕННЕЕ|ЛЕВОЕ)\s+СОЕДИНЕНИЕ\s+(?P<object>(?:Справочник|Документ)\.[A-Za-zА-Яа-яЁё0-9_]+)\s+КАК\s+"
        r"(?P<alias>[A-Za-zА-Яа-яЁё0-9_]+)\s+ПО\s+(?P<left>[A-Za-zА-Яа-яЁё0-9_]+\.[A-Za-zА-Яа-яЁё0-9_]+)\s*=\s*"
        r"(?P=alias)\.Ссылка",
        flags=re.IGNORECASE,
    )

    def replace_join(match: re.Match[str]) -> str:
        alias = match.group("alias")
        left = match.group("left")
        replacements.append((alias, left))
        return ""

    replacements: List[tuple[str, str]] = []
    result = pattern.sub(replace_join, query)
    for alias, left in replacements:
        result = re.sub(rf"\b{re.escape(alias)}\.Наименование\b", left, result)
        result = re.sub(rf"\b{re.escape(alias)}\.Представление\b", left, result)
    return result

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from wiicon5.bot_instance import BotInstanceConfig
from wiicon5.conversation.context import ConversationContext
from wiicon5.domain_packs.trade_ru.semantic_review import trade_ru_semantic_review_issues
from wiicon5.execution.artifacts import Artifact
from wiicon5.intent.models import IntentResult
from wiicon5.knowledge.metadata import (
    MetadataObject,
    MetadataProvider,
    confirmed_field_names,
    field_source,
    field_trust,
    is_field_confirmed,
    metadata_object_source,
    metadata_object_trust,
)
from wiicon5.knowledge.onboarding_evidence import OnboardingEvidenceProvider
from wiicon5.llm.client import LLMClient, LLMProviderError
from wiicon5.mcp.client import McpClient
from wiicon5.mcp.contracts import McpQueryRequest, normalize_mcp_rows
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.prompting import PromptCatalog
from wiicon5.presentation.answer_formatter import format_cell, format_user_answer, rows_effectively_empty
from wiicon5.presentation.llm_answer_formatter import LLMAnswerFormatter
from wiicon5.query.list_params import expand_in_list_parameters
from wiicon5.query.one_c_query_safety import validate_read_only_query
from wiicon5.query.one_c_query_review import (
    OneCQueryReviewer,
    matching_parenthesis_position,
    parse_sources,
    split_top_level_commas,
)
from wiicon5.query.reference_value_resolver import ReferenceValueResolver
from wiicon5.query_synthesis.failure_solver import (
    FailureSolver,
    FailureSolverDecision,
    failure_diagnostic_payload,
)
from wiicon5.query_synthesis.metadata_ranking import CompositeMetadataRankingPolicy, MetadataRankingPolicy
from wiicon5.query_synthesis.semantic_review import (
    clarification_issue,
    repair_required_issues,
    semantic_review_error,
    semantic_review_ok,
)
from wiicon5.query_synthesis.sufficiency import (
    ResultSufficiencyReview,
    ResultSufficiencyReviewer,
    deterministic_partial_review,
    deterministic_valid_empty_review,
)
from wiicon5.query_synthesis.term_expansion import (
    CompositeMetadataTermExpansionPolicy,
    MetadataTermExpansionPolicy,
)


_DEFAULT_PROMPT_CATALOG = PromptCatalog()
_DEFAULT_BOT_CONFIG = BotInstanceConfig.default()
DISCOVERY_PROMPT = _DEFAULT_PROMPT_CATALOG.discovery_prompt(_DEFAULT_BOT_CONFIG)
QUERY_PROMPT = _DEFAULT_PROMPT_CATALOG.query_prompt(_DEFAULT_BOT_CONFIG)
METADATA_REPAIR_PROMPT = _DEFAULT_PROMPT_CATALOG.metadata_repair_prompt(_DEFAULT_BOT_CONFIG)

QUERYABLE_OBJECT_PREFIXES = (
    "РегистрНакопления.",
    "РегистрСведений.",
    "Документ.",
    "Справочник.",
)

DIRECT_LOOKUP_OBJECT_PREFIXES = (
    "Справочник.",
    "Документ.",
    "РегистрНакопления.",
    "РегистрСведений.",
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
    context_artifacts: List[Artifact] = field(default_factory=list)
    message: str = ""
    error: str = ""
    needs_clarification: bool = False
    trace: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "error": self.error,
            "final_artifact": self.final_artifact.to_dict() if self.final_artifact else None,
            "context_artifacts": [artifact.to_dict() for artifact in self.context_artifacts],
            "needs_clarification": self.needs_clarification,
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
        result_reviewer: Optional[ResultSufficiencyReviewer] = None,
        max_metadata_objects: int = 12,
        max_repair_attempts: int = 2,
        max_successful_steps: int = 3,
        bot_config: Optional[BotInstanceConfig] = None,
        prompt_catalog: Optional[PromptCatalog] = None,
        term_expansion_policy: Optional[MetadataTermExpansionPolicy] = None,
        metadata_ranking_policy: Optional[MetadataRankingPolicy] = None,
        onboarding_evidence_provider: Optional[OnboardingEvidenceProvider] = None,
        failure_solver: Optional[FailureSolver] = None,
    ) -> None:
        self.llm_client = llm_client
        self.metadata_provider = metadata_provider
        self.mcp_client = mcp_client
        self.query_reviewer = query_reviewer or OneCQueryReviewer()
        self.answer_formatter = answer_formatter
        self.result_reviewer = result_reviewer
        self.max_metadata_objects = max_metadata_objects
        self.max_repair_attempts = max_repair_attempts
        self.max_successful_steps = max_successful_steps
        self.bot_config = bot_config or BotInstanceConfig.default()
        self.prompt_catalog = prompt_catalog or PromptCatalog()
        self.term_expansion_policy = term_expansion_policy or CompositeMetadataTermExpansionPolicy.from_bot_config(
            self.bot_config
        )
        self.metadata_ranking_policy = metadata_ranking_policy or CompositeMetadataRankingPolicy.from_bot_config(
            self.bot_config
        )
        self.onboarding_evidence_provider = onboarding_evidence_provider
        self.failure_solver = failure_solver

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
                system_prompt=self.prompt_catalog.discovery_prompt(self.bot_config),
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
        search_terms = search_terms_from_discovery(discovery, intent, message, self.term_expansion_policy)
        metadata_objects = collect_metadata_objects(
            self.metadata_provider,
            search_terms=search_terms,
            max_objects=self.max_metadata_objects,
            ranking_policy=self.metadata_ranking_policy,
        )
        trace["metadata_search_terms"] = search_terms
        trace["metadata_requests"] = getattr(self.metadata_provider, "last_requests", [])
        trace["metadata_objects"] = [metadata_object_summary(item) for item in metadata_objects]
        onboarding_evidence = self._onboarding_evidence(search_terms, metadata_objects)
        trace["onboarding_evidence"] = onboarding_evidence
        if not metadata_objects:
            return self._failed_result(
                message=message,
                intent=intent,
                goal=goal,
                context=context,
                gaps=gaps,
                error="Metadata search returned no objects.",
                trace=trace,
                metadata_objects=[],
                onboarding_evidence=onboarding_evidence,
                successful_steps=[],
            )

        previous_error = ""
        previous_query = ""
        previous_review: Dict[str, Any] = {}
        previous_result_insufficiency: Dict[str, Any] = {}
        successful_steps: List[Dict[str, Any]] = []
        query_review_guidance = self.query_reviewer.guidance()
        trace["query_review_guidance"] = query_review_guidance
        max_total_attempts = self.max_repair_attempts + self.max_successful_steps + 2
        trace["max_total_attempts"] = max_total_attempts
        for attempt in range(1, max_total_attempts + 1):
            try:
                query_response = self.llm_client.complete_json(
                    system_prompt=self.prompt_catalog.query_prompt(self.bot_config),
                    user_payload={
                        "message": message,
                        "intent": intent.to_dict(),
                        "goal": goal_to_payload(goal),
                        "conversation_context": context.to_packet(),
                        "metadata_objects": [metadata_object_summary(item) for item in metadata_objects],
                        "onboarding_evidence": onboarding_evidence,
                        "hypothesis": discovery.get("hypothesis"),
                        "draft_query": discovery.get("draft_query"),
                        "previous_error": previous_error,
                        "previous_query": previous_query,
                        "previous_query_review": previous_review,
                        "previous_successful_steps": compact_successful_steps(successful_steps),
                        "previous_result_insufficiency": previous_result_insufficiency,
                        "query_review_rules": query_review_guidance,
                        "attempt": attempt,
                        "schema": {"query": "1C query text", "params": {}, "limit": 100, "reasoning": "why this query"},
                    },
                )
            except LLMProviderError as exc:
                return self._failed_result(
                    message=message,
                    intent=intent,
                    goal=goal,
                    context=context,
                    gaps=gaps,
                    error=f"LLM query synthesis failed: {exc}",
                    trace=trace,
                    metadata_objects=metadata_objects,
                    onboarding_evidence=onboarding_evidence,
                    successful_steps=successful_steps,
                )

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

            if previous_result_insufficiency and repeats_partial_query(query, successful_steps):
                previous_error = (
                    "Repeated previous partial query after result insufficiency. "
                    "Build a different query that retrieves the missing facts instead of returning the same intermediate rows."
                )
                previous_query = query
                attempt_trace["error"] = previous_error
                attempt_trace["repeated_partial_query"] = True
                continue

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

            empty_list_params = used_empty_list_params(query, params)
            if empty_list_params:
                previous_error = (
                    "Query uses empty list parameter(s): "
                    + ", ".join("&" + name for name in empty_list_params)
                    + ". An empty list cannot identify business references and will filter out all rows. "
                    "Build a lookup query or one query with a verified subquery/condition that retrieves the referenced objects from 1C. "
                    "Do not ask the user for a concrete object when the question gives a category or attribute that can be resolved from data."
                )
                previous_query = query
                attempt_trace["error"] = previous_error
                attempt_trace["empty_list_params"] = empty_list_params
                continue

            list_param_expansion = expand_in_list_parameters(query, params)
            attempt_trace["list_param_expansion"] = list_param_expansion.to_dict()
            if list_param_expansion.changed:
                query = list_param_expansion.query
                params = list_param_expansion.params
                attempt_trace["query"] = query
                attempt_trace["params"] = dict(params)
                validation = validate_read_only_query(query, params)
                attempt_trace["validation_after_list_param_expansion"] = validation.to_dict()
                if not validation.ok:
                    previous_error = "Query validation failed after list parameter expansion: " + "; ".join(
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
                            ranking_policy=self.metadata_ranking_policy,
                        ),
                    )
                    metadata_objects = rank_metadata_objects(
                        metadata_objects,
                        search_terms=combined_terms,
                        max_objects=self.max_metadata_objects,
                        ranking_policy=self.metadata_ranking_policy,
                    )
                    trace["metadata_search_terms"] = combined_terms
                    trace["metadata_requests"] = getattr(self.metadata_provider, "last_requests", [])
                    trace["metadata_objects"] = [metadata_object_summary(item) for item in metadata_objects]
                    onboarding_evidence = self._onboarding_evidence(combined_terms, metadata_objects)
                    trace["onboarding_evidence"] = onboarding_evidence
                continue
            previous_review = query_review.to_dict()

            semantic_issues = goal_semantic_review_issues(
                query=query,
                params=params,
                goal=goal,
                message=message,
                intent=intent,
                metadata_objects=metadata_objects,
                domain_hint_packs=self.bot_config.domain_hint_packs,
            )
            attempt_trace["goal_semantic_review"] = {
                "ok": semantic_review_ok(semantic_issues),
                "issues": semantic_issues,
            }
            clarify_issue = clarification_issue(semantic_issues)
            if clarify_issue is not None:
                attempt_trace["clarification_issue"] = clarify_issue
                result = semantic_clarification_result(
                    question=message,
                    query=query,
                    params=params,
                    issue=clarify_issue,
                    trace=trace,
                    error="Clarification is required before continuing query synthesis.",
                )
                trace["clarification"] = result.context_artifacts[0].value if result.context_artifacts else {}
                return result
            repair_issues = repair_required_issues(semantic_issues)
            if repair_issues:
                previous_error = semantic_review_error("Query semantic review requires repair: ", repair_issues)
                previous_query = query
                attempt_trace["error"] = previous_error
                continue

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
                            ranking_policy=self.metadata_ranking_policy,
                        ),
                    )
                    metadata_objects = rank_metadata_objects(
                        metadata_objects,
                        search_terms=combined_terms,
                        max_objects=self.max_metadata_objects,
                        ranking_policy=self.metadata_ranking_policy,
                    )
                    trace["metadata_search_terms"] = combined_terms
                    trace["metadata_requests"] = getattr(self.metadata_provider, "last_requests", [])
                    trace["metadata_objects"] = [metadata_object_summary(item) for item in metadata_objects]
                    onboarding_evidence = self._onboarding_evidence(combined_terms, metadata_objects)
                    trace["onboarding_evidence"] = onboarding_evidence
                continue

            columns = columns_from_response(rows, response.schema)
            attempt_trace["columns"] = columns
            sufficiency = self._review_sufficiency(
                message=message,
                intent=intent,
                goal=goal,
                context=context,
                query=query,
                params=params,
                columns=columns,
                rows=rows,
                query_response=query_response,
                successful_steps=successful_steps,
            )
            attempt_trace["result_sufficiency"] = sufficiency.to_dict()
            if sufficiency.error:
                error = sufficiency.error
                attempt_trace["error"] = error
                trace["final_error"] = error
                return QuerySynthesisResult(ok=False, error=error, trace=trace)
            current_step = successful_step_payload(
                step=len(successful_steps) + 1,
                query=query,
                params=params,
                columns=columns,
                rows=rows,
                query_response=query_response,
                sufficiency=sufficiency,
            )
            if not sufficiency.sufficient:
                attempt_trace["partial_result"] = True
                successful_steps.append(current_step)
                trace["successful_steps"] = compact_successful_steps(successful_steps, include_rows=True)
                if sufficiency.needs_clarification:
                    artifact = clarification_artifact(
                        question=message,
                        query=query,
                        params=params,
                        columns=columns,
                        rows=rows,
                        sufficiency=sufficiency,
                    )
                    message_to_user = clarification_message(
                        sufficiency=sufficiency,
                        question=message,
                        columns=columns,
                        rows=rows,
                    )
                    trace["clarification"] = artifact.value
                    return QuerySynthesisResult(
                        ok=False,
                        context_artifacts=[artifact],
                        message=message_to_user,
                        error="Clarification is required before continuing query synthesis.",
                        needs_clarification=True,
                        trace=trace,
                    )
                previous_result_insufficiency = sufficiency.to_dict()
                previous_error = result_insufficiency_error(sufficiency)
                previous_query = query
                previous_review = query_review.to_dict()
                extra_terms = []
                if should_expand_metadata_after_insufficiency(sufficiency):
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
                            ranking_policy=self.metadata_ranking_policy,
                        ),
                    )
                    metadata_objects = rank_metadata_objects(
                        metadata_objects,
                        search_terms=combined_terms,
                        max_objects=self.max_metadata_objects,
                        ranking_policy=self.metadata_ranking_policy,
                    )
                    trace["metadata_search_terms"] = combined_terms
                    trace["metadata_requests"] = getattr(self.metadata_provider, "last_requests", [])
                    trace["metadata_objects"] = [metadata_object_summary(item) for item in metadata_objects]
                    onboarding_evidence = self._onboarding_evidence(combined_terms, metadata_objects)
                    trace["onboarding_evidence"] = onboarding_evidence
                if len(successful_steps) >= self.max_successful_steps:
                    return self._failed_result(
                        message=message,
                        intent=intent,
                        goal=goal,
                        context=context,
                        gaps=gaps,
                        error=previous_error or "Query synthesis produced only partial results.",
                        trace=trace,
                        metadata_objects=metadata_objects,
                        onboarding_evidence=onboarding_evidence,
                        successful_steps=successful_steps,
                    )
                continue

            answer = empty_result_answer(message, goal, columns) if rows_effectively_empty(rows) else format_user_answer(
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
            successful_steps.append(current_step)
            trace["successful_steps"] = compact_successful_steps(successful_steps, include_rows=True)
            trace["final_query"] = {"query": query, "params": dict(params), "limit": limit}
            trace["row_count"] = len(rows)
            return QuerySynthesisResult(
                ok=True,
                final_artifact=artifact,
                context_artifacts=[
                    Artifact(
                        name="query_result",
                        type="QueryResult",
                        value={
                            "question": message,
                            "answer": answer,
                            "query": query,
                            "params": dict(params),
                            "columns": columns,
                            "rows": rows[:50],
                            "steps": compact_successful_steps(successful_steps, include_rows=True),
                        },
                        provenance=["query_synthesis"],
                    )
                ],
                message=answer,
                trace=trace,
            )

        return self._failed_result(
            message=message,
            intent=intent,
            goal=goal,
            context=context,
            gaps=gaps,
            error=previous_error or "Query synthesis failed.",
            trace=trace,
            metadata_objects=metadata_objects,
            onboarding_evidence=onboarding_evidence,
            successful_steps=successful_steps,
        )

    def _failed_result(
        self,
        *,
        message: str,
        intent: IntentResult,
        goal: Optional[GoalDecomposition],
        context: ConversationContext,
        gaps: List[Dict[str, Any]],
        error: str,
        trace: Dict[str, Any],
        metadata_objects: List[MetadataObject],
        onboarding_evidence: Dict[str, Any],
        successful_steps: List[Dict[str, Any]],
    ) -> QuerySynthesisResult:
        trace["final_error"] = error
        diagnostic = failure_diagnostic_payload(
            message=message,
            intent=intent.to_dict(),
            goal=goal_to_payload(goal),
            conversation_context=context.to_packet(),
            gaps=gaps,
            failure_error=error,
            synthesis_trace=trace,
        )
        if self.failure_solver is None:
            trace["failure_solver"] = {"configured": False}
            return QuerySynthesisResult(ok=False, error=error, trace=trace)
        retry_error = error
        previous_retry_queries: List[str] = []
        for solver_attempt in range(2):
            if solver_attempt:
                diagnostic = failure_diagnostic_payload(
                    message=message,
                    intent=intent.to_dict(),
                    goal=goal_to_payload(goal),
                    conversation_context=context.to_packet(),
                    gaps=gaps,
                    failure_error=retry_error,
                    synthesis_trace=trace,
                )
            try:
                decision = self.failure_solver.solve(diagnostic)
            except Exception as exc:
                decision = FailureSolverDecision(action="unavailable", developer_note=str(exc))
            if solver_attempt:
                trace.setdefault("failure_solver_repair_decisions", []).append(decision.to_dict())
            else:
                trace["failure_solver"] = decision.to_dict()
            if decision.action != "retry_query":
                return QuerySynthesisResult(
                    ok=False,
                    error=merge_failure_solver_error(retry_error, decision),
                    trace=trace,
                )
            if not decision.query.strip():
                empty_query = FailureSolverDecision(
                    action="cannot_solve",
                    developer_note="Failure solver returned retry_query without query text.",
                    raw=decision.raw,
                )
                trace.setdefault("failure_solver_empty_retry_query", []).append(empty_query.to_dict())
                return QuerySynthesisResult(
                    ok=False,
                    error=merge_failure_solver_error(retry_error, empty_query),
                    trace=trace,
                )
            retry_query_key = normalized_query_for_comparison(postprocess_1c_query(decision.query.strip()))
            if retry_query_key in previous_retry_queries:
                repeated = FailureSolverDecision(
                    action="cannot_solve",
                    developer_note="Failure solver repeated the same failed retry query.",
                    raw=decision.raw,
                )
                trace.setdefault("failure_solver_repeated_retry_query", []).append(repeated.to_dict())
                return QuerySynthesisResult(
                    ok=False,
                    error=merge_failure_solver_error(retry_error, repeated),
                    trace=trace,
                )
            previous_retry_queries.append(retry_query_key)
            retry_result = self._execute_failure_solver_retry(
                message=message,
                intent=intent,
                goal=goal,
                context=context,
                trace=trace,
                decision=decision,
                metadata_objects=metadata_objects,
                onboarding_evidence=onboarding_evidence,
                successful_steps=successful_steps,
            )
            if retry_result.ok or retry_result.needs_clarification:
                return retry_result
            retry_error = retry_result.error or retry_error
            trace["failure_solver_retry_error"] = retry_error
        return QuerySynthesisResult(ok=False, error=retry_error, trace=trace)

    def _execute_failure_solver_retry(
        self,
        *,
        message: str,
        intent: IntentResult,
        goal: Optional[GoalDecomposition],
        context: ConversationContext,
        trace: Dict[str, Any],
        decision: FailureSolverDecision,
        metadata_objects: List[MetadataObject],
        onboarding_evidence: Dict[str, Any],
        successful_steps: List[Dict[str, Any]],
    ) -> QuerySynthesisResult:
        query_response = {
            "query": decision.query,
            "params": dict(decision.params),
            "limit": decision.limit,
            "reasoning": decision.reasoning or "Failure solver retry query.",
            "answer_guidance": decision.answer_guidance,
        }
        raw_query = decision.query.strip()
        query = postprocess_1c_query(raw_query)
        params = dict(decision.params)
        limit = limit_from_value(decision.limit)
        attempt_trace: Dict[str, Any] = {
            "source": "failure_solver",
            "query_response": query_response,
            "raw_query": raw_query,
            "query": query,
            "params": dict(params),
            "limit": limit,
            "onboarding_evidence": onboarding_evidence,
        }
        trace.setdefault("failure_solver_attempts", []).append(attempt_trace)

        if repeats_partial_query(query, successful_steps):
            error = (
                "Failure solver repeated previous partial query after result insufficiency. "
                "It must build a different query that retrieves the missing facts."
            )
            attempt_trace["error"] = error
            return QuerySynthesisResult(ok=False, error=error, trace=trace)

        validation = validate_read_only_query(query, params)
        attempt_trace["validation"] = validation.to_dict()
        if not validation.ok:
            error = "Failure solver query validation failed: " + "; ".join(issue.message for issue in validation.issues)
            attempt_trace["error"] = error
            return QuerySynthesisResult(ok=False, error=error, trace=trace)

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
                error = "Failure solver query validation failed after reference resolution: " + "; ".join(
                    issue.message for issue in validation.issues
                )
                attempt_trace["error"] = error
                return QuerySynthesisResult(ok=False, error=error, trace=trace)

        empty_list_params = used_empty_list_params(query, params)
        if empty_list_params:
            error = (
                "Failure solver query uses empty list parameter(s): "
                + ", ".join("&" + name for name in empty_list_params)
            )
            attempt_trace["error"] = error
            attempt_trace["empty_list_params"] = empty_list_params
            return QuerySynthesisResult(ok=False, error=error, trace=trace)

        list_param_expansion = expand_in_list_parameters(query, params)
        attempt_trace["list_param_expansion"] = list_param_expansion.to_dict()
        if list_param_expansion.changed:
            query = list_param_expansion.query
            params = list_param_expansion.params
            attempt_trace["query"] = query
            attempt_trace["params"] = dict(params)
            validation = validate_read_only_query(query, params)
            attempt_trace["validation_after_list_param_expansion"] = validation.to_dict()
            if not validation.ok:
                error = "Failure solver query validation failed after list expansion: " + "; ".join(
                    issue.message for issue in validation.issues
                )
                attempt_trace["error"] = error
                return QuerySynthesisResult(ok=False, error=error, trace=trace)

        query_review = self.query_reviewer.review(
            query=query,
            params=params,
            metadata_objects=metadata_objects,
        )
        attempt_trace["query_review"] = query_review.to_dict()
        if not query_review.ok:
            error = "Failure solver query review failed: " + query_review.error_text()
            attempt_trace["error"] = error
            return QuerySynthesisResult(ok=False, error=error, trace=trace)

        semantic_issues = goal_semantic_review_issues(
            query=query,
            params=params,
            goal=goal,
            message=message,
            intent=intent,
            metadata_objects=metadata_objects,
            domain_hint_packs=self.bot_config.domain_hint_packs,
        )
        attempt_trace["goal_semantic_review"] = {
            "ok": semantic_review_ok(semantic_issues),
            "issues": semantic_issues,
        }
        clarify_issue = clarification_issue(semantic_issues)
        if clarify_issue is not None:
            attempt_trace["clarification_issue"] = clarify_issue
            result = semantic_clarification_result(
                question=message,
                query=query,
                params=params,
                issue=clarify_issue,
                trace=trace,
                error="Clarification is required after failure solver semantic review.",
            )
            trace["clarification"] = result.context_artifacts[0].value if result.context_artifacts else {}
            return result
        repair_issues = repair_required_issues(semantic_issues)
        if repair_issues:
            error = semantic_review_error("Failure solver query semantic review requires repair: ", repair_issues)
            attempt_trace["error"] = error
            return QuerySynthesisResult(ok=False, error=error, trace=trace)

        response = self.mcp_client.execute_query(McpQueryRequest(query=query, params=params, limit=limit))
        rows = normalize_mcp_rows(response)
        attempt_trace["mcp_response"] = response.raw
        attempt_trace["row_count"] = len(rows)
        if not response.success:
            error = response.error or "Failure solver MCP query failed."
            attempt_trace["error"] = error
            return QuerySynthesisResult(ok=False, error=error, trace=trace)

        columns = columns_from_response(rows, response.schema)
        attempt_trace["columns"] = columns
        sufficiency = self._review_sufficiency(
            message=message,
            intent=intent,
            goal=goal,
            context=context,
            query=query,
            params=params,
            columns=columns,
            rows=rows,
            query_response=query_response,
            successful_steps=successful_steps,
        )
        attempt_trace["result_sufficiency"] = sufficiency.to_dict()
        if sufficiency.error:
            error = sufficiency.error
            attempt_trace["error"] = error
            trace["final_error"] = error
            return QuerySynthesisResult(ok=False, error=error, trace=trace)
        current_step = successful_step_payload(
            step=len(successful_steps) + 1,
            query=query,
            params=params,
            columns=columns,
            rows=rows,
            query_response=query_response,
            sufficiency=sufficiency,
        )
        if not sufficiency.sufficient:
            attempt_trace["partial_result"] = True
            if sufficiency.needs_clarification:
                artifact = clarification_artifact(
                    question=message,
                    query=query,
                    params=params,
                    columns=columns,
                    rows=rows,
                    sufficiency=sufficiency,
                )
                trace["clarification"] = artifact.value
                return QuerySynthesisResult(
                    ok=False,
                    context_artifacts=[artifact],
                    message=clarification_message(
                        sufficiency=sufficiency,
                        question=message,
                        columns=columns,
                        rows=rows,
                    ),
                    error="Clarification is required after failure solver retry.",
                    needs_clarification=True,
                    trace=trace,
                )
            error = "Failure solver retry result insufficient. " + result_insufficiency_error(sufficiency)
            attempt_trace["error"] = error
            return QuerySynthesisResult(ok=False, error=error, trace=trace)

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
            provenance=["query_synthesis", "failure_solver"],
        )
        successful_steps.append(current_step)
        trace["successful_steps"] = compact_successful_steps(successful_steps, include_rows=True)
        trace["final_query"] = {"query": query, "params": dict(params), "limit": limit, "source": "failure_solver"}
        trace["row_count"] = len(rows)
        return QuerySynthesisResult(
            ok=True,
            final_artifact=artifact,
            context_artifacts=[
                Artifact(
                    name="query_result",
                    type="QueryResult",
                    value={
                        "question": message,
                        "answer": answer,
                        "query": query,
                        "params": dict(params),
                        "columns": columns,
                        "rows": rows[:50],
                        "steps": compact_successful_steps(successful_steps, include_rows=True),
                    },
                    provenance=["query_synthesis", "failure_solver"],
                )
            ],
            message=answer,
            trace=trace,
        )

    def _review_sufficiency(
        self,
        *,
        message: str,
        intent: IntentResult,
        goal: Optional[GoalDecomposition],
        context: ConversationContext,
        query: str,
        params: Dict[str, Any],
        columns: List[str],
        rows: List[Dict[str, Any]],
        query_response: Dict[str, Any],
        successful_steps: List[Dict[str, Any]],
    ) -> ResultSufficiencyReview:
        query_reasoning = str(query_response.get("reasoning") or "")
        if self.result_reviewer is not None:
            return self.result_reviewer.review(
                question=message,
                intent=intent,
                goal=goal,
                context=context,
                query=query,
                params=params,
                columns=columns,
                rows=rows,
                query_reasoning=query_reasoning,
                previous_successful_steps=successful_steps,
            )
        deterministic = deterministic_partial_review(
            question=message,
            columns=columns,
            rows=rows,
            query_reasoning=query_reasoning,
            domain_hint_packs=self.bot_config.domain_hint_packs,
            goal=goal,
            query=query,
            params=params,
        )
        if deterministic is not None:
            return deterministic
        empty_result = deterministic_valid_empty_review(
            question=message,
            columns=columns,
            rows=rows,
            query=query,
            params=params,
            goal=goal,
        )
        return empty_result or ResultSufficiencyReview(sufficient=True)

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
                system_prompt=self.prompt_catalog.metadata_repair_prompt(self.bot_config),
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

    def _onboarding_evidence(
        self,
        search_terms: List[str],
        metadata_objects: List[MetadataObject],
    ) -> Dict[str, Any]:
        if self.onboarding_evidence_provider is None:
            return {"available": False}
        return self.onboarding_evidence_provider.evidence_for(
            search_terms=search_terms,
            metadata_objects=metadata_objects,
        )


def collect_metadata_objects(
    metadata_provider: MetadataProvider,
    *,
    search_terms: List[str],
    max_objects: int,
    ranking_policy: Optional[MetadataRankingPolicy] = None,
) -> List[MetadataObject]:
    candidates: Dict[str, MetadataObject] = {}
    for term in search_terms:
        if looks_like_full_1c_name(term):
            direct = metadata_provider.get_object(term)
            if direct.raw:
                candidates[direct.full_name] = direct
        for full_name in direct_queryable_names_from_term(term):
            if full_name in candidates:
                continue
            direct = metadata_provider.get_object(full_name)
            if direct.raw and direct.full_name:
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

    ranked_names = [
        item.full_name
        for item in rank_metadata_objects(
            list(candidates.values()),
            search_terms,
            len(candidates),
            ranking_policy=ranking_policy,
        )
    ]
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
    ranking_policy: Optional[MetadataRankingPolicy] = None,
) -> List[MetadataObject]:
    effective_policy = ranking_policy or CompositeMetadataRankingPolicy.from_bot_config()
    return sorted(
        objects,
        key=lambda item: (-metadata_candidate_score(item, search_terms, effective_policy), item.full_name),
    )[:max_objects]


def metadata_candidate_score(
    item: MetadataObject,
    search_terms: List[str],
    ranking_policy: MetadataRankingPolicy,
) -> int:
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
        elif normalized == full_name.rsplit(".", 1)[-1].lower():
            score += 120
        elif normalized in text:
            score += 15
        else:
            for word in normalized.split():
                if len(word) >= 4 and word in text:
                    score += 3
    score += ranking_policy.score(item, search_terms)
    return score


def looks_like_full_1c_name(term: str) -> bool:
    return term.startswith(QUERYABLE_OBJECT_PREFIXES)


def direct_queryable_names_from_term(term: str) -> List[str]:
    normalized = term.strip().strip(".,!?;:()[]{}\"'")
    if not normalized or looks_like_full_1c_name(normalized):
        return []
    if not normalized[:1].isupper():
        return []
    if not re.fullmatch(r"[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*", normalized):
        return []
    return [prefix + normalized for prefix in DIRECT_LOOKUP_OBJECT_PREFIXES]


def detailed_enough(item: MetadataObject) -> bool:
    return (
        any(key in item.raw for key in ["Реквизиты", "Измерения", "Ресурсы", "СтандартныеРеквизиты", "ТабличныеЧасти"])
        or metadata_object_source(item) == "metadata_xml"
    )


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
        for marker in [
            "таблица не найдена",
            "поле не найдено",
            "не подтверждено метаданными",
            "не подтвержден структурой метаданных",
            "field_not_confirmed",
            "source_not_confirmed_by_verified_metadata",
            "result insufficiency",
            "missing facts",
        ]
    )


def reset_metadata_request_log(metadata_provider: MetadataProvider) -> None:
    if hasattr(metadata_provider, "last_requests"):
        try:
            metadata_provider.last_requests = []  # type: ignore[attr-defined]
        except Exception:
            return
    primary = getattr(metadata_provider, "primary", None)
    if primary is not None and hasattr(primary, "last_requests"):
        try:
            primary.last_requests = []  # type: ignore[attr-defined]
        except Exception:
            return


def search_terms_from_discovery(
    discovery: Dict[str, Any],
    intent: IntentResult,
    message: str,
    term_expansion_policy: Optional[MetadataTermExpansionPolicy] = None,
) -> List[str]:
    terms: List[str] = []
    for item in intent.domain_terms:
        add_unique(terms, str(item).strip())
    for word in message.replace(",", " ").split():
        if len(word) >= 5:
            add_unique(terms, word.strip())
    for item in discovery.get("metadata_search_terms", []) or []:
        add_unique(terms, str(item).strip())
    return expand_metadata_search_terms(terms, term_expansion_policy)[:30]


def expand_metadata_search_terms(
    terms: List[str],
    term_expansion_policy: Optional[MetadataTermExpansionPolicy] = None,
) -> List[str]:
    policy = term_expansion_policy or CompositeMetadataTermExpansionPolicy.from_bot_config()
    return policy.expand(terms)


def metadata_object_summary(item: MetadataObject) -> Dict[str, Any]:
    confirmed_fields = confirmed_field_names(item)
    hint_fields = [field for field in item.fields if field not in confirmed_fields]
    return {
        "full_name": item.full_name,
        "synonym": item.synonym,
        "source": metadata_object_source(item),
        "trust": metadata_object_trust(item),
        "confidence": item.raw.get("_confidence"),
        "fields": confirmed_fields,
        "field_hints": hint_fields,
        "table_parts": table_parts_summary(item),
        "field_details": {
            name: {
                key: value
                for key, value in details.items()
                if key
                in {
                    "Имя",
                    "Синоним",
                    "Тип",
                    "_category",
                    "_source",
                    "_trust",
                    "_confidence",
                    "name",
                    "synonym",
                    "type",
                }
            }
            for name, details in item.field_details.items()
            if is_field_confirmed(details)
        },
        "field_hint_details": {
            name: {
                "name": name,
                "category": details.get("_category"),
                "source": field_source(details),
                "trust": field_trust(details),
                "confidence": details.get("_confidence"),
            }
            for name, details in item.field_details.items()
            if not is_field_confirmed(details)
        },
    }


def table_parts_summary(item: MetadataObject) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for name, details in item.field_details.items():
        if details.get("_category") != "table_part" or not is_field_confirmed(details):
            continue
        nested = details.get("_nested_fields")
        nested_details = details.get("_nested_field_details")
        if isinstance(nested_details, dict):
            nested = [field for field in (nested or []) if is_field_confirmed(nested_details.get(str(field), {}))]
        result[name] = {
            "fields": list(nested) if isinstance(nested, list) else [],
        }
    return result


def metadata_terms_from_query_review(query_review) -> List[str]:
    terms: List[str] = []
    for issue in getattr(query_review, "issues", []) or []:
        for term in metadata_terms_from_issue_message(getattr(issue, "message", "")):
            add_unique(terms, term)
    for source in getattr(query_review, "sources", []) or []:
        if getattr(source, "table_part", ""):
            add_unique(terms, source.source)
            add_unique(terms, f"{source.object_full_name}.{source.table_part}")
            add_unique(terms, f"{source.object_full_name} {source.table_part}")
        elif getattr(source, "object_full_name", ""):
            add_unique(terms, source.object_full_name)
    return terms[:8]


def metadata_terms_from_issue_message(message: str) -> List[str]:
    result: List[str] = []
    for kind, name in re.findall(
        r"\b(Справочник|Документ|Перечисление)Ссылка\.([A-Za-zА-Яа-яЁё0-9_]+)",
        message,
        flags=re.IGNORECASE,
    ):
        canonical_kind = canonical_reference_owner_type(kind)
        add_unique(result, f"{canonical_kind}.{name}")
    return result


def canonical_reference_owner_type(kind: str) -> str:
    lowered = kind.lower()
    if lowered == "справочник":
        return "Справочник"
    if lowered == "документ":
        return "Документ"
    if lowered == "перечисление":
        return "Перечисление"
    return kind


def goal_to_payload(goal: Optional[GoalDecomposition]) -> Optional[Dict[str, Any]]:
    if goal is None:
        return None
    return {
        "business_goal": goal.business_goal,
        "final_artifact_type": goal.final_artifact_type,
        "expected_answer_type": goal.expected_answer_type,
        "required_artifacts": [item.to_dict() for item in goal.required_artifacts],
        "semantic_contract": dict(goal.semantic_contract),
    }


def columns_from_rows(rows: List[Dict[str, Any]]) -> List[str]:
    columns: List[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns


def columns_from_response(rows: List[Dict[str, Any]], schema: Dict[str, Any]) -> List[str]:
    columns = columns_from_rows(rows)
    if columns:
        return columns
    schema_columns = schema.get("columns") if isinstance(schema, dict) else None
    if not isinstance(schema_columns, list):
        return []
    result: List[str] = []
    for item in schema_columns:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name and name not in result:
            result.append(name)
    return result


def empty_result_answer(question: str, goal: Optional[GoalDecomposition], columns: List[str]) -> str:
    lowered = " ".join([question, " ".join(columns), goal.business_goal if goal is not None else ""]).lower()
    if any(marker in lowered for marker in ["остат", "в наличии", "наличии"]):
        return "Остатков по заданному условию не найдено."
    if any(marker in lowered for marker in ["цена", "стоимость"]):
        return "Цен по заданному условию не найдено."
    return "Данных не найдено."


def successful_step_payload(
    *,
    step: int,
    query: str,
    params: Dict[str, Any],
    columns: List[str],
    rows: List[Dict[str, Any]],
    query_response: Dict[str, Any],
    sufficiency: ResultSufficiencyReview,
) -> Dict[str, Any]:
    return {
        "step": step,
        "query": query,
        "params": dict(params),
        "columns": list(columns),
        "rows": rows[:50],
        "query_reasoning": str(query_response.get("reasoning") or ""),
        "sufficiency": sufficiency.to_dict(),
    }


def clarification_artifact(
    *,
    question: str,
    query: str,
    params: Dict[str, Any],
    columns: List[str],
    rows: List[Dict[str, Any]],
    sufficiency: ResultSufficiencyReview,
) -> Artifact:
    return Artifact(
        name="clarification_request",
        type="ClarificationRequest",
        value={
            "question": question,
            "clarification_question": sufficiency.clarification_question,
            "clarification_options": list(sufficiency.clarification_options),
            "reasoning": sufficiency.reasoning,
            "missing_facts": list(sufficiency.missing_facts),
            "next_query_goal": sufficiency.next_query_goal,
            "partial_result": {
                "query": query,
                "params": dict(params),
                "columns": list(columns),
                "rows": rows[:10],
            },
        },
        provenance=["query_synthesis"],
    )


def semantic_clarification_result(
    *,
    question: str,
    query: str,
    params: Dict[str, Any],
    issue: Dict[str, Any],
    trace: Dict[str, Any],
    error: str,
) -> QuerySynthesisResult:
    sufficiency = ResultSufficiencyReview(
        sufficient=False,
        partial=False,
        needs_clarification=True,
        clarification_question=str(issue.get("clarification_question") or "Уточните, какой показатель нужно показать?"),
        clarification_options=[str(item) for item in issue.get("clarification_options", []) or []],
        reasoning=str(issue.get("message") or ""),
        missing_facts=[str(issue.get("code") or "semantic_clarification")],
    )
    artifact = clarification_artifact(
        question=question,
        query=query,
        params=params,
        columns=[],
        rows=[],
        sufficiency=sufficiency,
    )
    return QuerySynthesisResult(
        ok=False,
        context_artifacts=[artifact],
        message=clarification_message(
            sufficiency=sufficiency,
            question=question,
            columns=[],
            rows=[],
        ),
        error=error,
        needs_clarification=True,
        trace=trace,
    )


def clarification_message(
    *,
    sufficiency: ResultSufficiencyReview,
    question: str,
    columns: List[str],
    rows: List[Dict[str, Any]],
) -> str:
    question_text = sufficiency.clarification_question or "Уточните, какой показатель нужно показать?"
    parts = []
    partial_summary = humanized_partial_result(question=question, rows=rows)
    if partial_summary:
        parts.append(partial_summary)
    parts.append(question_text)
    if sufficiency.clarification_options:
        parts.append("Можно ответить: " + "; ".join(sufficiency.clarification_options) + ".")
    elif rows and not rows_effectively_empty(rows):
        parts.append(format_user_answer(question=question, columns=columns, rows=rows[:1]))
    return "\n\n".join(parts)


def humanized_partial_result(*, question: str, rows: List[Dict[str, Any]]) -> str:
    if not rows or not isinstance(rows[0], dict) or rows_effectively_empty(rows[:1]):
        return ""
    row = rows[0]
    subject_column = first_present_column(row, ["Контрагент", "Клиент", "Партнер", "Партнёр", "Поставщик"])
    amount_column = first_amount_column(row)
    subject = format_cell(row.get(subject_column))
    document_column = first_present_column(row, ["Ссылка", "Документ", "Document", "document"])
    document = format_cell(row.get(document_column)) if document_column else ""
    if subject_column and document and "отгруз" in question.lower() and not amount_column:
        return f"Я нашел последнюю отгрузку: {document}. Контрагент: {subject}."
    if not subject_column or not amount_column:
        return ""
    amount = format_cell(row.get(amount_column))
    if not subject or not amount:
        return ""
    subject_label = subject_column.lower()
    amount_label = "сумма документа" if amount_column == "СуммаДокумента" else amount_column.lower()
    if "отгруз" in question.lower():
        return f"Я нашел последнюю отгрузку: {subject_label} {subject}, {amount_label} {amount}."
    return f"Я нашел данные: {subject_label} {subject}, {amount_label} {amount}."


def first_present_column(row: Dict[str, Any], columns: List[str]) -> str:
    for column in columns:
        if row.get(column) not in (None, ""):
            return column
    return ""


def first_amount_column(row: Dict[str, Any]) -> str:
    preferred = ["СуммаДокумента", "Сумма", "СуммаОтгрузки", "Amount"]
    for column in preferred:
        if row.get(column) not in (None, ""):
            return column
    for column, value in row.items():
        if value not in (None, "") and ("сумм" in column.lower() or "amount" in column.lower()):
            return column
    return ""


def compact_successful_steps(steps: List[Dict[str, Any]], *, include_rows: bool = False) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for step in steps[-3:]:
        item = {
            "step": step.get("step"),
            "query": step.get("query"),
            "params": step.get("params"),
            "columns": step.get("columns"),
            "query_reasoning": step.get("query_reasoning"),
            "sufficiency": step.get("sufficiency"),
        }
        rows = list(step.get("rows") or [])
        item["rows"] = rows[:10] if include_rows else rows[:5]
        result.append(item)
    return result


def result_insufficiency_error(sufficiency: ResultSufficiencyReview) -> str:
    parts = ["Result insufficiency."]
    if sufficiency.missing_facts:
        parts.append("Missing facts: " + "; ".join(sufficiency.missing_facts))
    if sufficiency.next_query_goal:
        parts.append("Next query goal: " + sufficiency.next_query_goal)
    if sufficiency.reasoning:
        parts.append("Reasoning: " + sufficiency.reasoning)
    return " ".join(parts)


def merge_failure_solver_error(error: str, decision: FailureSolverDecision) -> str:
    base = error or "Query synthesis failed."
    detail = decision.developer_note or decision.reasoning
    if not detail:
        return base
    return f"{base} Failure solver {decision.action}: {detail}"


def should_expand_metadata_after_insufficiency(sufficiency: ResultSufficiencyReview) -> bool:
    text = " ".join(
        [
            *sufficiency.missing_facts,
            sufficiency.next_query_goal,
            sufficiency.reasoning,
        ]
    ).lower()
    if "финальные факты" in text and "промежуточ" in text:
        return False
    return any(
        marker in text
        for marker in [
            "метадан",
            "не получен",
            "не найден",
            "отсутств",
            "не подтвержден",
            "не подтверждён",
        ]
    )


def goal_semantic_review_issues(
    *,
    query: str,
    params: Dict[str, Any],
    goal: Optional[GoalDecomposition],
    message: str = "",
    intent: Optional[IntentResult] = None,
    metadata_objects: List[MetadataObject],
    domain_hint_packs: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    packs = domain_hint_packs if domain_hint_packs is not None else BotInstanceConfig.default().domain_hint_packs
    if "trade_ru" in packs:
        issues.extend(trade_ru_semantic_review_issues(
            query=query,
            params=params,
            goal=goal,
            message=message,
            intent=intent,
            metadata_objects=metadata_objects,
        ))
    return issues


def repeats_partial_query(query: str, successful_steps: List[Dict[str, Any]]) -> bool:
    current = normalized_query_for_comparison(query)
    if not current:
        return False
    for step in successful_steps:
        sufficiency = step.get("sufficiency")
        if not isinstance(sufficiency, dict) or sufficiency.get("sufficient"):
            continue
        previous = normalized_query_for_comparison(str(step.get("query") or ""))
        if previous and previous == current:
            return True
    return False


def used_empty_list_params(query: str, params: Dict[str, Any]) -> List[str]:
    used_names = set(re.findall(r"&([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)", query))
    return sorted(
        name
        for name, value in params.items()
        if name in used_names and isinstance(value, list) and not value
    )


def normalized_query_for_comparison(query: str) -> str:
    return " ".join(query.lower().split())


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
    text = normalize_1c_query_keywords(text)
    text = re.sub(r"\.Остатки\(\s*,\s*,\s*\)", ".Остатки()", text, flags=re.IGNORECASE)
    text = re.sub(r"\.Остатки\(\s*,\s*\)", ".Остатки()", text, flags=re.IGNORECASE)
    text = re.sub(
        r"(\bРегистрНакопления\.[A-Za-zА-Яа-яЁё0-9_]+)\.(ОстаткиИОбороты|Остатки|Обороты)(\s+КАК\b)",
        r"\1.\2()\3",
        text,
        flags=re.IGNORECASE,
    )
    text = normalize_direct_parameter_in_list_operator(text)
    text = move_virtual_balance_in_list_param_filters_to_where(text)
    text = rename_ambiguous_source_aliases(text)
    text = remove_redundant_reference_joins(text)
    return text


def rename_ambiguous_source_aliases(query: str) -> str:
    from_match = re.search(r"\bИЗ\b", query, flags=re.IGNORECASE)
    if from_match is None:
        return query
    selected_aliases = {
        item.lower()
        for item in re.findall(
            r"\bКАК\s+([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)\b",
            query[: from_match.start()],
            flags=re.IGNORECASE,
        )
    }
    result = query
    used_aliases = {source.alias.lower() for source in parse_sources(query)} | selected_aliases
    for source in parse_sources(query):
        if source.alias.lower() not in selected_aliases:
            continue
        replacement = unique_source_alias(source.alias, used_aliases)
        source_pattern = r"\s+".join(re.escape(part) for part in source.source.split())
        declaration = re.compile(
            rf"(\b(?:ИЗ|СОЕДИНЕНИЕ)\s+{source_pattern}\s+КАК\s+){re.escape(source.alias)}\b",
            flags=re.IGNORECASE,
        )
        result, changed = declaration.subn(rf"\g<1>{replacement}", result, count=1)
        if not changed:
            continue
        result = re.sub(
            rf"\b{re.escape(source.alias)}\s*\.",
            f"{replacement}.",
            result,
            flags=re.IGNORECASE,
        )
        used_aliases.add(replacement.lower())
    return result


def unique_source_alias(alias: str, used_aliases: set[str]) -> str:
    base = f"{alias}Источник"
    candidate = base
    index = 2
    while candidate.lower() in used_aliases:
        candidate = f"{base}{index}"
        index += 1
    return candidate


def normalize_direct_parameter_in_list_operator(query: str) -> str:
    return re.sub(
        r"\bВ\s+&(?P<param>[A-Za-zА-Яа-яЁё0-9_]+)",
        r"В (&\g<param>)",
        query,
        flags=re.IGNORECASE,
    )


def move_virtual_balance_in_list_param_filters_to_where(query: str) -> str:
    pattern = re.compile(
        r"РегистрНакопления\.[A-Za-zА-Яа-яЁё0-9_]+\.Остатки\s*\(",
        flags=re.IGNORECASE,
    )
    result_parts: List[str] = []
    moved_conditions: List[str] = []
    position = 0
    for match in pattern.finditer(query):
        open_position = query.find("(", match.start(), match.end())
        if open_position < 0:
            continue
        close_position = matching_parenthesis_position(query, open_position)
        if close_position is None:
            continue
        alias_match = re.match(
            r"\s+КАК\s+(?P<alias>[A-Za-zА-Яа-яЁё0-9_]+)",
            query[close_position + 1 :],
            flags=re.IGNORECASE,
        )
        if alias_match is None:
            continue
        args = split_top_level_commas(query[open_position + 1 : close_position])
        if len(args) < 2:
            continue
        remaining_condition, external_conditions = split_virtual_in_list_param_conditions(
            args[1],
            alias=alias_match.group("alias"),
        )
        if not external_conditions:
            continue
        result_parts.append(query[position:match.start()])
        result_parts.append(query[match.start() : open_position])
        result_parts.append(render_balance_virtual_args(args[0], remaining_condition))
        position = close_position + 1
        moved_conditions.extend(external_conditions)
    if not moved_conditions:
        return query
    result_parts.append(query[position:])
    return add_where_conditions("".join(result_parts), moved_conditions)


def split_virtual_in_list_param_conditions(condition: str, *, alias: str) -> tuple[str, List[str]]:
    remaining: List[str] = []
    external: List[str] = []
    for part in split_top_level_and(condition):
        match = re.fullmatch(
            r"(?:[A-Za-zА-Яа-яЁё0-9_]+\.)?(?P<field>[A-Za-zА-Яа-яЁё0-9_]+)\s+В\s*\(\s*&(?P<param>[A-Za-zА-Яа-яЁё0-9_]+)\s*\)",
            part.strip(),
            flags=re.IGNORECASE,
        )
        if match is None:
            remaining.append(part.strip())
            continue
        external.append(f"{alias}.{match.group('field')} В (&{match.group('param')})")
    return " И ".join(item for item in remaining if item), external


def split_top_level_and(condition: str) -> List[str]:
    result: List[str] = []
    current: List[str] = []
    depth = 0
    position = 0
    while position < len(condition):
        char = condition[position]
        if char == "(":
            depth += 1
            current.append(char)
            position += 1
            continue
        if char == ")" and depth:
            depth -= 1
            current.append(char)
            position += 1
            continue
        if depth == 0:
            match = re.match(r"\s+И\s+", condition[position:], flags=re.IGNORECASE)
            if match is not None:
                result.append("".join(current).strip())
                current = []
                position += len(match.group(0))
                continue
        current.append(char)
        position += 1
    result.append("".join(current).strip())
    return [item for item in result if item]


def render_balance_virtual_args(period: str, condition: str) -> str:
    clean_period = period.strip()
    clean_condition = condition.strip()
    if clean_condition:
        return f"({clean_period}, {clean_condition})" if clean_period else f"(, {clean_condition})"
    return f"({clean_period})" if clean_period else "()"


def add_where_conditions(query: str, conditions: List[str]) -> str:
    if not conditions:
        return query
    boundary = query_clause_boundary(query)
    before = query[:boundary].rstrip()
    after = query[boundary:]
    suffix = "\n" + after.lstrip() if after.strip() else ""
    condition_text = "\n    И ".join(conditions)
    where_match = re.search(r"\bГДЕ\b", before, flags=re.IGNORECASE)
    if where_match is not None:
        return f"{before}\n    И {condition_text}{suffix}"
    return f"{before}\nГДЕ\n    {condition_text}{suffix}"


def query_clause_boundary(query: str) -> int:
    boundaries = []
    for pattern in (
        r"\bСГРУППИРОВАТЬ\s+ПО\b",
        r"\bУПОРЯДОЧИТЬ\s+ПО\b",
        r"\bИТОГИ\b",
        r"\bОБЪЕДИНИТЬ\b",
    ):
        match = re.search(pattern, query, flags=re.IGNORECASE)
        if match is not None:
            boundaries.append(match.start())
    return min(boundaries) if boundaries else len(query)


def normalize_1c_query_keywords(query: str) -> str:
    replacements = {
        "УБЫВЬ": "УБЫВ",
        "УБЫВАНИЕ": "УБЫВ",
        "ВОЗРАСТАНИЕ": "ВОЗР",
    }
    result = query
    for wrong, correct in replacements.items():
        result = re.sub(rf"\b{wrong}\b", correct, result, flags=re.IGNORECASE)
    return result


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
        if not reference_join_can_be_removed(query, match, alias):
            return match.group(0)
        replacements.append((alias, left))
        return ""

    replacements: List[tuple[str, str]] = []
    result = pattern.sub(replace_join, query)
    for alias, left in replacements:
        result = re.sub(rf"\b{re.escape(alias)}\.Наименование\b", left, result)
        result = re.sub(rf"\b{re.escape(alias)}\.Представление\b", left, result)
    return result


def reference_join_can_be_removed(query: str, match: re.Match[str], alias: str) -> bool:
    query_without_join = query[: match.start()] + query[match.end() :]
    from_match = re.search(r"\bИЗ\b", query_without_join, flags=re.IGNORECASE)
    from_position = from_match.start() if from_match is not None else 0
    alias_pattern = re.compile(rf"\b{re.escape(alias)}\.(?P<field>[A-Za-zА-Яа-яЁё0-9_]+)\b", flags=re.IGNORECASE)
    for alias_match in alias_pattern.finditer(query_without_join):
        field = alias_match.group("field")
        if alias_match.start() > from_position:
            return False
        if field.lower() not in {"наименование", "представление"}:
            return False
    return True

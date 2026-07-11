from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from wiicon5.audit.trace_writer import RunTrace, TraceWriter
from wiicon5.clarification import ClarificationResolver
from wiicon5.conversation.context import ConversationContext
from wiicon5.conversation.memory import ConversationMemory
from wiicon5.execution.artifacts import Artifact
from wiicon5.execution.runtime import SkillPlanExecutionResult, SkillPlanExecutor
from wiicon5.intent.decomposer import GoalDecomposer
from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.intent.relevance_gate import RelevanceGate
from wiicon5.instance_knowledge.answer import KnowledgeAnswerService
from wiicon5.models import GapResolution, SkillGap, SkillPlan
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.policies import BaselineIntentPolicy, DomainPolicy
from wiicon5.query_synthesis import QuerySynthesisEngine, QuerySynthesisResult
from wiicon5.query_synthesis.reuse_review import SkillExecutionPostReview, SkillExecutionPostReviewer
from wiicon5.skills.composer import SkillComposer
from wiicon5.skills.learned import LearnedSkillRuntimeHealthStore, LearnedSkillStore, LearnedSkillWriteResult
from wiicon5.skills.lifecycle import SkillEvolutionDecision, SkillEvolutionPolicy
from wiicon5.skills.registry import SkillRegistry
from wiicon5.skills.semantic_contract import column_names_match
from wiicon5.types import TypeSystem
from wiicon5.workbench.synthesis_candidates import SynthesisCandidateStore


@dataclass(frozen=True)
class AgentRunResult:
    source: str
    message: str
    intent: IntentResult
    goal: Optional[GoalDecomposition] = None
    plan: Optional[SkillPlan] = None
    final_artifact: Optional[Artifact] = None
    context_artifacts: List[Artifact] = field(default_factory=list)
    gaps: List[SkillGap] = field(default_factory=list)
    evolution_decisions: List[SkillEvolutionDecision] = field(default_factory=list)
    trace_path: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "source": self.source,
            "message": self.message,
            "intent": self.intent.to_dict(),
            "goal": self.goal_to_dict(),
            "plan": self.plan.to_dict() if self.plan else None,
            "final_artifact": self.final_artifact.to_dict() if self.final_artifact else None,
            "context_artifacts": [artifact.to_dict() for artifact in self.context_artifacts],
            "gaps": [gap.to_dict() for gap in self.gaps],
            "evolution_decisions": [decision.to_dict() for decision in self.evolution_decisions],
            "trace_path": self.trace_path,
        }

    def goal_to_dict(self) -> Optional[Dict[str, object]]:
        if self.goal is None:
            return None
        return {
            "business_goal": self.goal.business_goal,
            "final_artifact_type": self.goal.final_artifact_type,
            "expected_answer_type": self.goal.expected_answer_type,
            "required_artifacts": [item.to_dict() for item in self.goal.required_artifacts],
            "semantic_contract": dict(self.goal.semantic_contract),
        }


class AgentOrchestrator:
    def __init__(
        self,
        *,
        registry: SkillRegistry,
        decomposer: GoalDecomposer,
        memory: Optional[ConversationMemory] = None,
        trace_root: Optional[Path] = None,
        relevance_gate: Optional[RelevanceGate] = None,
        evolution_policy: Optional[SkillEvolutionPolicy] = None,
        plan_executor: Optional[SkillPlanExecutor] = None,
        query_synthesizer: Optional[QuerySynthesisEngine] = None,
        learned_skill_store: Optional[LearnedSkillStore] = None,
        synthesis_candidate_store: Optional[SynthesisCandidateStore] = None,
        clarification_resolver: Optional[ClarificationResolver] = None,
        domain_policy: Optional[DomainPolicy] = None,
        baseline_intent_policy: Optional[BaselineIntentPolicy] = None,
        skill_execution_reviewer: Optional[SkillExecutionPostReviewer] = None,
        learned_health_store: Optional[LearnedSkillRuntimeHealthStore] = None,
        knowledge_answerer: Optional[KnowledgeAnswerService] = None,
    ) -> None:
        self.registry = registry
        self.decomposer = decomposer
        self.memory = memory or ConversationMemory()
        self.composer = SkillComposer(registry)
        self.domain_policy = domain_policy or DomainPolicy()
        self.relevance_gate = relevance_gate or RelevanceGate(self.domain_policy)
        self.baseline_intent_policy = baseline_intent_policy or BaselineIntentPolicy(self.domain_policy)
        self.evolution_policy = evolution_policy or SkillEvolutionPolicy()
        self.plan_executor = plan_executor
        self.query_synthesizer = query_synthesizer
        self.learned_skill_store = learned_skill_store
        self.synthesis_candidate_store = synthesis_candidate_store
        self.clarification_resolver = clarification_resolver or ClarificationResolver()
        self.skill_execution_reviewer = skill_execution_reviewer
        self.learned_health_store = learned_health_store
        self.knowledge_answerer = knowledge_answerer
        self.trace_writer = TraceWriter(trace_root or Path("runs"))

    def handle(self, message: str, *, session_id: str = "") -> AgentRunResult:
        context = self.memory.get_or_create(session_id)
        user_message = context.append_message("user", message)
        run_trace = self.trace_writer.new_run(prefix="agent")
        self._write_input_trace(run_trace, message, context)

        clarification_resolution = self.clarification_resolver.resolve(message, context)
        if clarification_resolution is not None:
            intent = IntentResult(
                intent_type=IntentType.CLARIFICATION,
                business_goal=message,
                requires_1c_data=False,
                expected_output="short_answer",
                domain_terms=["clarification"],
                relevant=True,
                reasoning=clarification_resolution.reasoning,
            )
            result = AgentRunResult(
                source="clarification_resolved",
                message=str(clarification_resolution.artifact.value),
                intent=intent,
                final_artifact=clarification_resolution.artifact,
                trace_path=str(run_trace.path),
            )
            run_trace.write_json(
                "clarification/resolution.json",
                {"message": message, "resolution": clarification_resolution.trace},
            )
            run_trace.write_json("result/result.json", result.to_dict())
            self._record_assistant_and_save(context, result)
            return result

        baseline_intent = self.baseline_intent_policy.detect(message)
        if baseline_intent is not None:
            run_trace.write_json("intent/intent_response.json", {"intent": baseline_intent.to_dict(), "source": "baseline"})
            result = AgentRunResult(
                source="general_answer",
                message=self.domain_policy.general_answer(baseline_intent),
                intent=baseline_intent,
                trace_path=str(run_trace.path),
            )
            run_trace.write_json("result/result.json", result.to_dict())
            self._record_assistant_and_save(context, result)
            return result

        decomposition = self.decomposer.decompose(message, context)
        run_trace.write_json("intent/intent_response.json", {"intent": decomposition.intent.to_dict()})
        decomposition_knowledge = getattr(self.decomposer, "last_knowledge_evidence", None)
        if isinstance(decomposition_knowledge, dict):
            run_trace.write_json("knowledge/decomposition_evidence.json", decomposition_knowledge)

        if is_llm_unavailable_intent(decomposition.intent):
            result = AgentRunResult(
                source="llm_unavailable",
                message=llm_unavailable_message(decomposition.intent),
                intent=decomposition.intent,
                trace_path=str(run_trace.path),
            )
            run_trace.write_json("result/result.json", result.to_dict())
            self._record_assistant_and_save(context, result)
            return result

        if self.knowledge_answerer is not None and not decomposition.intent.requires_1c_data:
            knowledge_result = self.knowledge_answerer.answer(message, context)
            run_trace.write_json("knowledge/answer.json", knowledge_result.to_dict())
            if knowledge_result.answerable:
                artifact = Artifact(
                    name="knowledge_answer",
                    type="UserAnswer",
                    value=knowledge_result.answer,
                    provenance=[f"instance_knowledge:{item}" for item in knowledge_result.used_chunk_ids],
                )
                result = AgentRunResult(
                    source="instance_knowledge",
                    message=knowledge_result.answer,
                    intent=decomposition.intent,
                    goal=decomposition.goal,
                    final_artifact=artifact,
                    trace_path=str(run_trace.path),
                )
                run_trace.write_json("result/result.json", result.to_dict())
                self._record_assistant_and_save(context, result)
                return result

        if not self.relevance_gate.is_relevant(decomposition.intent):
            result = AgentRunResult(
                source="out_of_scope",
                message=self.relevance_gate.out_of_scope_message(decomposition.intent),
                intent=decomposition.intent,
                trace_path=str(run_trace.path),
            )
            run_trace.write_json("result/result.json", result.to_dict())
            self._record_assistant_and_save(context, result)
            return result

        if decomposition.intent.intent_type == IntentType.GENERAL_QUESTION:
            result = AgentRunResult(
                source="general_answer",
                message=self.domain_policy.general_answer(decomposition.intent),
                intent=decomposition.intent,
                trace_path=str(run_trace.path),
            )
            run_trace.write_json("result/result.json", result.to_dict())
            self._record_assistant_and_save(context, result)
            return result

        if decomposition.goal is None:
            result = AgentRunResult(
                source="needs_goal_decomposition",
                message="Не удалось разложить вопрос на проверяемую цель.",
                intent=decomposition.intent,
                trace_path=str(run_trace.path),
            )
            run_trace.write_json("result/result.json", result.to_dict())
            self._record_assistant_and_save(context, result)
            return result

        run_trace.write_json("intent/goal_decomposition.json", result_goal_to_dict(decomposition.goal))
        compose_result = self.composer.compose(decomposition.goal)
        if compose_result.search_trace:
            run_trace.write_json("skill_search/composer_trace.json", {"items": compose_result.search_trace})
        if compose_result.plan is not None:
            run_trace.write_json("skill_plan/plan_graph.json", compose_result.plan.to_dict())
            if self.plan_executor is not None:
                execution_result = self.plan_executor.execute(compose_result.plan, context)
                run_trace.write_json("skill_invocations/execution_result.json", execution_result_to_dict(execution_result))
                if execution_result.ok and execution_result.final_artifact is not None:
                    post_review = self._review_skill_execution(
                        message=message,
                        intent=decomposition.intent,
                        goal=decomposition.goal,
                        plan=compose_result.plan,
                        execution_result=execution_result,
                        context=context,
                    )
                    if post_review is not None:
                        run_trace.write_json("skill_invocations/post_execution_review.json", post_review.to_dict())
                    sufficiency_gap = skill_execution_requirement_gap(decomposition.goal, execution_result)
                    if sufficiency_gap is None and post_review is not None and not post_review.ok:
                        sufficiency_gap = skill_post_review_gap(decomposition.goal, execution_result, post_review)
                    if sufficiency_gap is not None:
                        self._record_learned_health(
                            plan=compose_result.plan,
                            execution_result=execution_result,
                            context=context,
                            accepted=False,
                            error=post_review.error if post_review is not None else sufficiency_gap.reason,
                        )
                        run_trace.write_json(
                            "skill_invocations/sufficiency_review.json",
                            {"ok": False, "gap": sufficiency_gap.to_dict()},
                        )
                        synthesis_result = self._try_query_synthesis(
                            message=message,
                            intent=decomposition.intent,
                            goal=decomposition.goal,
                            context=context,
                            run_trace=run_trace,
                            gaps=[sufficiency_gap.to_dict()],
                            source="skill_execution_insufficient",
                        )
                        if synthesis_result is not None and synthesis_result.needs_clarification:
                            result = AgentRunResult(
                                source="needs_clarification",
                                message=synthesis_result.message,
                                intent=decomposition.intent,
                                goal=decomposition.goal,
                                plan=compose_result.plan,
                                context_artifacts=synthesis_result.context_artifacts,
                                gaps=[sufficiency_gap],
                                trace_path=str(run_trace.path),
                            )
                            run_trace.write_json("result/result.json", result.to_dict())
                            self._record_assistant_and_save(context, result)
                            return result
                        if synthesis_result is not None and synthesis_result.ok and synthesis_result.final_artifact is not None:
                            self._learn_from_synthesis(
                                intent=decomposition.intent,
                                goal=decomposition.goal,
                                synthesis_result=synthesis_result,
                                run_trace=run_trace,
                                context=context,
                            )
                            result = AgentRunResult(
                                source="query_synthesis_ok",
                                message=synthesis_result.message,
                                intent=decomposition.intent,
                                goal=decomposition.goal,
                                plan=compose_result.plan,
                                final_artifact=synthesis_result.final_artifact,
                                context_artifacts=synthesis_result.context_artifacts,
                                gaps=[sufficiency_gap],
                                trace_path=str(run_trace.path),
                            )
                            run_trace.write_json("result/result.json", result.to_dict())
                            self._record_assistant_and_save(context, result)
                            return result
                        if synthesis_result is not None and not synthesis_result.ok:
                            result = self._query_synthesis_failed_result(
                                synthesis_result=synthesis_result,
                                intent=decomposition.intent,
                                goal=decomposition.goal,
                                plan=compose_result.plan,
                                gaps=[sufficiency_gap],
                                trace_path=str(run_trace.path),
                            )
                            run_trace.write_json("result/result.json", result.to_dict())
                            self._record_assistant_and_save(context, result)
                            return result
                        result = AgentRunResult(
                            source="skill_execution_insufficient",
                            message="Существующий навык выполнился, но результат не содержит всех данных, запрошенных пользователем.",
                            intent=decomposition.intent,
                            goal=decomposition.goal,
                            plan=compose_result.plan,
                            gaps=[sufficiency_gap],
                            trace_path=str(run_trace.path),
                        )
                        run_trace.write_json("result/result.json", result.to_dict())
                        self._record_assistant_and_save(context, result)
                        return result
                    self._record_learned_health(
                        plan=compose_result.plan,
                        execution_result=execution_result,
                        context=context,
                        accepted=True,
                    )
                    result = AgentRunResult(
                        source="skill_execution_ok",
                        message=str(execution_result.final_artifact.value),
                        intent=decomposition.intent,
                        goal=decomposition.goal,
                        plan=compose_result.plan,
                        final_artifact=execution_result.final_artifact,
                        context_artifacts=execution_context_artifacts(execution_result),
                        trace_path=str(run_trace.path),
                    )
                    run_trace.write_json("result/result.json", result.to_dict())
                    self._record_assistant_and_save(context, result)
                    return result
                self._record_learned_health(
                    plan=compose_result.plan,
                    execution_result=execution_result,
                    context=context,
                    accepted=False,
                    error=execution_result.error,
                )
                synthesis_result = self._try_query_synthesis(
                    message=message,
                    intent=decomposition.intent,
                    goal=decomposition.goal,
                    context=context,
                    run_trace=run_trace,
                    gaps=[],
                    source="skill_execution_failed",
                    source_diagnostic={
                        "skill_plan": compose_result.plan.to_dict(),
                        "skill_execution": execution_result_to_dict(execution_result),
                    },
                )
                if synthesis_result is not None and synthesis_result.needs_clarification:
                    result = AgentRunResult(
                        source="needs_clarification",
                        message=synthesis_result.message,
                        intent=decomposition.intent,
                        goal=decomposition.goal,
                        plan=compose_result.plan,
                        context_artifacts=synthesis_result.context_artifacts,
                        trace_path=str(run_trace.path),
                    )
                    run_trace.write_json("result/result.json", result.to_dict())
                    self._record_assistant_and_save(context, result)
                    return result
                if synthesis_result is not None and synthesis_result.ok and synthesis_result.final_artifact is not None:
                    self._learn_from_synthesis(
                        intent=decomposition.intent,
                        goal=decomposition.goal,
                        synthesis_result=synthesis_result,
                        run_trace=run_trace,
                        context=context,
                    )
                    result = AgentRunResult(
                        source="query_synthesis_ok",
                        message=synthesis_result.message,
                        intent=decomposition.intent,
                        goal=decomposition.goal,
                        plan=compose_result.plan,
                        final_artifact=synthesis_result.final_artifact,
                        context_artifacts=synthesis_result.context_artifacts,
                        trace_path=str(run_trace.path),
                    )
                    run_trace.write_json("result/result.json", result.to_dict())
                    self._record_assistant_and_save(context, result)
                    return result
                if synthesis_result is not None and not synthesis_result.ok:
                    result = self._query_synthesis_failed_result(
                        synthesis_result=synthesis_result,
                        intent=decomposition.intent,
                        goal=decomposition.goal,
                        plan=compose_result.plan,
                        trace_path=str(run_trace.path),
                    )
                    run_trace.write_json("result/result.json", result.to_dict())
                    self._record_assistant_and_save(context, result)
                    return result
                result = AgentRunResult(
                    source="skill_execution_failed",
                    message=f"Не удалось выполнить план навыков: {execution_result.error}",
                    intent=decomposition.intent,
                    goal=decomposition.goal,
                    plan=compose_result.plan,
                    trace_path=str(run_trace.path),
                )
                run_trace.write_json("result/result.json", result.to_dict())
                self._record_assistant_and_save(context, result)
                return result
            result = AgentRunResult(
                source="skill_plan_ready",
                message="План навыков построен, выполнение будет подключено следующим этапом.",
                intent=decomposition.intent,
                goal=decomposition.goal,
                plan=compose_result.plan,
                trace_path=str(run_trace.path),
            )
            run_trace.write_json("result/result.json", result.to_dict())
            self._record_assistant_and_save(context, result)
            return result

        decisions = [self.evolution_policy.decide(gap) for gap in compose_result.gaps]
        run_trace.write_json("skill_search/skill_gaps.json", {"gaps": [gap.to_dict() for gap in compose_result.gaps]})
        run_trace.write_json("learning/evolution_decision.json", {"decisions": [decision.to_dict() for decision in decisions]})
        synthesis_result = self._try_query_synthesis(
            message=message,
            intent=decomposition.intent,
            goal=decomposition.goal,
            context=context,
            run_trace=run_trace,
            gaps=[gap.to_dict() for gap in compose_result.gaps],
            source="skill_gap",
        )
        if synthesis_result is not None and synthesis_result.needs_clarification:
            result = AgentRunResult(
                source="needs_clarification",
                message=synthesis_result.message,
                intent=decomposition.intent,
                goal=decomposition.goal,
                context_artifacts=synthesis_result.context_artifacts,
                gaps=compose_result.gaps,
                evolution_decisions=decisions,
                trace_path=str(run_trace.path),
            )
            run_trace.write_json("result/result.json", result.to_dict())
            self._record_assistant_and_save(context, result)
            return result
        if synthesis_result is not None and synthesis_result.ok and synthesis_result.final_artifact is not None:
            self._learn_from_synthesis(
                intent=decomposition.intent,
                goal=decomposition.goal,
                synthesis_result=synthesis_result,
                run_trace=run_trace,
                context=context,
            )
            result = AgentRunResult(
                source="query_synthesis_ok",
                message=synthesis_result.message,
                intent=decomposition.intent,
                goal=decomposition.goal,
                final_artifact=synthesis_result.final_artifact,
                context_artifacts=synthesis_result.context_artifacts,
                gaps=compose_result.gaps,
                evolution_decisions=decisions,
                trace_path=str(run_trace.path),
            )
            run_trace.write_json("result/result.json", result.to_dict())
            self._record_assistant_and_save(context, result)
            return result
        if synthesis_result is not None and not synthesis_result.ok:
            result = self._query_synthesis_failed_result(
                synthesis_result=synthesis_result,
                intent=decomposition.intent,
                goal=decomposition.goal,
                gaps=compose_result.gaps,
                evolution_decisions=decisions,
                trace_path=str(run_trace.path),
            )
            run_trace.write_json("result/result.json", result.to_dict())
            self._record_assistant_and_save(context, result)
            return result
        result = AgentRunResult(
            source="skill_gap",
            message="Найден разрыв в навыках; требуется развитие существующего навыка или binding.",
            intent=decomposition.intent,
            goal=decomposition.goal,
            gaps=compose_result.gaps,
            evolution_decisions=decisions,
            trace_path=str(run_trace.path),
        )
        run_trace.write_json("result/result.json", result.to_dict())
        self._record_assistant_and_save(context, result)
        return result

    def _review_skill_execution(
        self,
        *,
        message: str,
        intent: IntentResult,
        goal: GoalDecomposition,
        plan: SkillPlan,
        execution_result: SkillPlanExecutionResult,
        context: ConversationContext,
    ) -> Optional[SkillExecutionPostReview]:
        if self.skill_execution_reviewer is None:
            return None
        return self.skill_execution_reviewer.review(
            message=message,
            intent=intent,
            goal=goal,
            plan=plan,
            execution_result=execution_result,
            context=context,
        )

    def _record_learned_health(
        self,
        *,
        plan: SkillPlan,
        execution_result: SkillPlanExecutionResult,
        context: ConversationContext,
        accepted: bool,
        error: str = "",
    ) -> None:
        if self.learned_health_store is None:
            return
        self.learned_health_store.record_plan_outcome(
            plan=plan,
            execution_result=execution_result,
            context=context,
            accepted=accepted,
            error=error,
        )

    def _write_input_trace(self, run_trace: RunTrace, message: str, context: ConversationContext) -> None:
        run_trace.write_json("input/user_message.json", {"message": message})
        run_trace.write_json("input/conversation_packet.json", context.to_packet())

    def _record_assistant_and_save(self, context: ConversationContext, result: AgentRunResult) -> None:
        context.append_message("assistant", result.message)
        if result.final_artifact is not None:
            context.add_artifact(result.final_artifact)
        for artifact in result.context_artifacts:
            context.add_artifact(artifact)
        self.memory.save(context)

    def _try_query_synthesis(
        self,
        *,
        message: str,
        intent: IntentResult,
        goal: Optional[GoalDecomposition],
        context: ConversationContext,
        run_trace: RunTrace,
        gaps: List[Dict[str, object]],
        source: str,
        source_diagnostic: Optional[Dict[str, object]] = None,
    ) -> Optional[QuerySynthesisResult]:
        if self.query_synthesizer is None:
            return None
        synthesis_result = self.query_synthesizer.run(
            message=message,
            intent=intent,
            goal=goal,
            context=context,
            gaps=gaps,
        )
        run_trace.write_json(
            "query_synthesis/result.json",
            {"source": source, "synthesis": synthesis_result.to_dict()},
        )
        if not synthesis_result.ok and not synthesis_result.needs_clarification:
            self._write_query_synthesis_failure_diagnostic(
                run_trace=run_trace,
                source=source,
                message=message,
                intent=intent,
                goal=goal,
                context=context,
                gaps=gaps,
                synthesis_result=synthesis_result,
                source_diagnostic=source_diagnostic,
            )
        return synthesis_result

    def _write_query_synthesis_failure_diagnostic(
        self,
        *,
        run_trace: RunTrace,
        source: str,
        message: str,
        intent: IntentResult,
        goal: Optional[GoalDecomposition],
        context: ConversationContext,
        gaps: List[Dict[str, object]],
        synthesis_result: QuerySynthesisResult,
        source_diagnostic: Optional[Dict[str, object]] = None,
    ) -> Path:
        return run_trace.write_json(
            "diagnostics/query_synthesis_failure.json",
            {
                "kind": "query_synthesis_failure",
                "developer_handoff": (
                    "Агент не смог построить корректный запрос самостоятельно. "
                    "Проверьте synthesis.trace, attempts, raw MCP responses, failure_solver and final_error. "
                    "Код бота автоматически не изменялся."
                ),
                "source": source,
                "message": message,
                "intent": intent.to_dict(),
                "goal": result_goal_to_dict(goal) if goal is not None else None,
                "conversation_context": context.to_packet(),
                "gaps": list(gaps),
                "source_diagnostic": dict(source_diagnostic or {}),
                "synthesis_result": synthesis_result.to_dict(),
            },
        )

    def _query_synthesis_failed_result(
        self,
        *,
        synthesis_result: QuerySynthesisResult,
        intent: IntentResult,
        goal: Optional[GoalDecomposition],
        trace_path: str,
        plan: Optional[SkillPlan] = None,
        gaps: Optional[List[SkillGap]] = None,
        evolution_decisions: Optional[List[SkillEvolutionDecision]] = None,
    ) -> AgentRunResult:
        message = query_synthesis_failure_message(synthesis_result.error)
        diagnostic_path = Path(trace_path) / "diagnostics" / "query_synthesis_failure.json"
        if diagnostic_path.exists():
            message += (
                "\n\nК сожалению, агент не смог сам восстановить запрос. "
                f"Передайте разработчику файл диагностики: {diagnostic_path}"
            )
        return AgentRunResult(
            source="query_synthesis_failed",
            message=message,
            intent=intent,
            goal=goal,
            plan=plan,
            context_artifacts=synthesis_result.context_artifacts,
            gaps=list(gaps or []),
            evolution_decisions=list(evolution_decisions or []),
            trace_path=trace_path,
        )

    def _learn_from_synthesis(
        self,
        *,
        intent: IntentResult,
        goal: Optional[GoalDecomposition],
        synthesis_result: QuerySynthesisResult,
        run_trace: RunTrace,
        context: ConversationContext,
    ) -> None:
        learned: Optional[LearnedSkillWriteResult] = None
        if self.learned_skill_store is not None:
            learned = self.learned_skill_store.learn_from_synthesis(
                intent=intent,
                goal=goal,
                synthesis_result=synthesis_result,
                created_from_trace=str(run_trace.path),
                config_fingerprint=context.config_fingerprint or "",
            )
            if learned is not None:
                run_trace.write_json("learning/learned_skill.json", learned.to_dict())
            gate = self.learned_skill_store.last_gate_result
            if gate is not None:
                run_trace.write_json("learning/learning_gate.json", gate.to_dict())
        if self.synthesis_candidate_store is not None:
            if learned_synthesis_replaces_workbench_candidate(learned):
                run_trace.write_json(
                    "workbench/synthesis_candidate_skipped.json",
                    {
                        "reason": "reusable_learned_skill_created",
                        "learned_skill_id": learned.skill.skill_id if learned else "",
                        "learned_skill_created": bool(learned.created) if learned else False,
                        "implementation_kind": str(learned.skill.implementation.get("kind") or "") if learned else "",
                    },
                )
                return
            candidate = self.synthesis_candidate_store.record_from_synthesis(
                question=intent.business_goal,
                intent=intent,
                goal=goal,
                synthesis_result=synthesis_result,
                trace_path=str(run_trace.path),
            )
            if candidate is not None:
                run_trace.write_json("workbench/synthesis_candidate.json", candidate.to_dict())


def learned_synthesis_replaces_workbench_candidate(learned: Optional[LearnedSkillWriteResult]) -> bool:
    if learned is None:
        return False
    if learned.skill.implementation_strategy != "learned_query":
        return False
    return str(learned.skill.implementation.get("kind") or "") in {
        "semantic_query_template",
        "parameterized_lookup_query",
        "period_metric_aggregate",
    }


def result_goal_to_dict(goal: GoalDecomposition) -> Dict[str, object]:
    return {
        "business_goal": goal.business_goal,
        "final_artifact_type": goal.final_artifact_type,
        "expected_answer_type": goal.expected_answer_type,
        "required_artifacts": [item.to_dict() for item in goal.required_artifacts],
        "semantic_contract": dict(goal.semantic_contract),
    }


def skill_execution_requirement_gap(
    goal: GoalDecomposition,
    execution_result: SkillPlanExecutionResult,
) -> Optional[SkillGap]:
    type_system = TypeSystem()
    for requirement in goal.required_artifacts:
        if not requirement.required_columns:
            continue
        artifact = first_artifact_for_requirement(execution_result, requirement.type, type_system)
        if artifact is None:
            continue
        columns = artifact_columns(artifact.value)
        missing = [column for column in requirement.required_columns if not column_present(column, columns)]
        if missing:
            return SkillGap(
                required_capability=f"result_columns:{requirement.type}",
                required_output=requirement.type,
                reason=(
                    "Skill execution returned a table, but it does not contain columns or dimensions "
                    "explicitly requested by the user."
                ),
                nearest_skill_ids=list(artifact.provenance),
                recommended_resolution=GapResolution.CREATE_NEW,
                missing=[f"column:{column}" for column in missing],
            )
    return None


def skill_post_review_gap(
    goal: GoalDecomposition,
    execution_result: SkillPlanExecutionResult,
    review: SkillExecutionPostReview,
) -> SkillGap:
    missing = list(review.sufficiency.missing_facts) if review.sufficiency is not None else []
    if not missing:
        missing = ["semantic_result_review"]
    provenance: List[str] = []
    for artifact in execution_result.artifacts.values():
        for skill_id in artifact.provenance:
            if skill_id not in provenance:
                provenance.append(skill_id)
    return SkillGap(
        required_capability="semantic_result_sufficiency",
        required_output=goal.final_artifact_type,
        reason=review.error or "Skill result is not semantically sufficient for the user goal.",
        nearest_skill_ids=provenance,
        recommended_resolution=GapResolution.CREATE_NEW,
        missing=missing,
    )


def execution_context_artifacts(execution_result: SkillPlanExecutionResult) -> List[Artifact]:
    result: List[Artifact] = []
    seen = set()
    for artifact in execution_result.artifacts.values():
        if artifact.type == "UserAnswer" or artifact == execution_result.final_artifact:
            continue
        key = (artifact.name, artifact.type, repr(artifact.value), tuple(artifact.provenance))
        if key in seen:
            continue
        seen.add(key)
        result.append(artifact)
    return result


def first_artifact_for_requirement(
    execution_result: SkillPlanExecutionResult,
    artifact_type: str,
    type_system: TypeSystem,
) -> Optional[Artifact]:
    for artifact in execution_result.artifacts.values():
        if type_system.is_assignable(artifact.type, artifact_type):
            return artifact
    return None


def artifact_columns(value: object) -> List[str]:
    if isinstance(value, dict):
        columns = value.get("columns")
        if isinstance(columns, list) and columns:
            return [str(item) for item in columns]
        rows = value.get("rows")
        if isinstance(rows, list):
            return columns_from_rows(rows)
    return []


def columns_from_rows(rows: List[object]) -> List[str]:
    result: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in row:
            key_text = str(key)
            if key_text not in result:
                result.append(key_text)
    return result


def column_present(required: str, columns: List[str]) -> bool:
    required_key = normalize_column_name(required)
    column_keys = {normalize_column_name(column) for column in columns}
    if required_key in column_keys:
        return True
    if any(column_names_match(required, column) for column in columns):
        return True
    aliases = {
        "номенклатура": {"товар", "продукт", "наименованиеноменклатуры", "номенклатура"},
        "склад": {"склад", "местохранения", "складнаименование", "наименованиесклада"},
    }
    return bool(aliases.get(required_key, set()) & column_keys)


def normalize_column_name(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def is_llm_unavailable_intent(intent: IntentResult) -> bool:
    return intent.intent_type == IntentType.UNKNOWN and "llm unavailable" in intent.reasoning.lower()


def llm_unavailable_message(intent: IntentResult) -> str:
    details = intent.reasoning.removeprefix("LLM unavailable:").strip()
    if details:
        return f"Сервис модели сейчас недоступен, поэтому я не могу обработать запрос. Детали: {details}"
    return "Сервис модели сейчас недоступен, поэтому я не могу обработать запрос."


def execution_result_to_dict(execution_result) -> Dict[str, object]:
    return {
        "ok": execution_result.ok,
        "error": execution_result.error,
        "failed_invocation_id": execution_result.failed_invocation_id,
        "final_artifact": execution_result.final_artifact.to_dict() if execution_result.final_artifact else None,
        "artifacts": {key: artifact.to_dict() for key, artifact in execution_result.artifacts.items()},
        "trace": execution_result.trace,
    }


def query_synthesis_failure_message(error: str) -> str:
    normalized = " ".join((error or "").split())
    if len(normalized) > 420:
        normalized = normalized[:417].rstrip() + "..."
    if normalized:
        return f"Не удалось построить корректный запрос к данным. Причина: {normalized}"
    return "Не удалось построить корректный запрос к данным. Подробности сохранены в trace."

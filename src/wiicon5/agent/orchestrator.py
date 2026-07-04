from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from wiicon5.audit.trace_writer import RunTrace, TraceWriter
from wiicon5.clarification import ClarificationResolver
from wiicon5.conversation.context import ConversationContext
from wiicon5.conversation.memory import ConversationMemory
from wiicon5.execution.artifacts import Artifact
from wiicon5.execution.runtime import SkillPlanExecutor
from wiicon5.intent.decomposer import GoalDecomposer
from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.intent.relevance_gate import RelevanceGate
from wiicon5.models import SkillGap, SkillPlan
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.policies import BaselineIntentPolicy, DomainPolicy
from wiicon5.query_synthesis import QuerySynthesisEngine, QuerySynthesisResult
from wiicon5.skills.composer import SkillComposer
from wiicon5.skills.learned import LearnedSkillStore
from wiicon5.skills.lifecycle import SkillEvolutionDecision, SkillEvolutionPolicy
from wiicon5.skills.registry import SkillRegistry


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
        clarification_resolver: Optional[ClarificationResolver] = None,
        domain_policy: Optional[DomainPolicy] = None,
        baseline_intent_policy: Optional[BaselineIntentPolicy] = None,
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
        self.clarification_resolver = clarification_resolver or ClarificationResolver()
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
                    result = AgentRunResult(
                        source="skill_execution_ok",
                        message=str(execution_result.final_artifact.value),
                        intent=decomposition.intent,
                        goal=decomposition.goal,
                        plan=compose_result.plan,
                        final_artifact=execution_result.final_artifact,
                        trace_path=str(run_trace.path),
                    )
                    run_trace.write_json("result/result.json", result.to_dict())
                    self._record_assistant_and_save(context, result)
                    return result
                synthesis_result = self._try_query_synthesis(
                    message=message,
                    intent=decomposition.intent,
                    goal=decomposition.goal,
                    context=context,
                    run_trace=run_trace,
                    gaps=[],
                    source="skill_execution_failed",
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
        return synthesis_result

    def _learn_from_synthesis(
        self,
        *,
        intent: IntentResult,
        goal: Optional[GoalDecomposition],
        synthesis_result: QuerySynthesisResult,
        run_trace: RunTrace,
        context: ConversationContext,
    ) -> None:
        if self.learned_skill_store is None:
            return
        learned = self.learned_skill_store.learn_from_synthesis(
            intent=intent,
            goal=goal,
            synthesis_result=synthesis_result,
            created_from_trace=str(run_trace.path),
            config_fingerprint=context.config_fingerprint or "",
        )
        if learned is not None:
            run_trace.write_json("learning/learned_skill.json", learned.to_dict())


def result_goal_to_dict(goal: GoalDecomposition) -> Dict[str, object]:
    return {
        "business_goal": goal.business_goal,
        "final_artifact_type": goal.final_artifact_type,
        "expected_answer_type": goal.expected_answer_type,
        "required_artifacts": [item.to_dict() for item in goal.required_artifacts],
    }


def execution_result_to_dict(execution_result) -> Dict[str, object]:
    return {
        "ok": execution_result.ok,
        "error": execution_result.error,
        "failed_invocation_id": execution_result.failed_invocation_id,
        "final_artifact": execution_result.final_artifact.to_dict() if execution_result.final_artifact else None,
        "artifacts": {key: artifact.to_dict() for key, artifact in execution_result.artifacts.items()},
        "trace": execution_result.trace,
    }

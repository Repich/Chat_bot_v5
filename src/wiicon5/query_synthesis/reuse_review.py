from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from wiicon5.conversation.context import ConversationContext
from wiicon5.execution.artifacts import Artifact
from wiicon5.execution.runtime import SkillPlanExecutionResult
from wiicon5.intent.models import IntentResult
from wiicon5.models import SkillPlan
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.query_synthesis.sufficiency import ResultSufficiencyReview, ResultSufficiencyReviewer
from wiicon5.skills.registry import SkillRegistry
from wiicon5.skills.semantic_contract import SemanticSkillContract, contract_from_goal, semantic_contract_compatibility
from wiicon5.types import TypeSystem


@dataclass(frozen=True)
class SkillExecutionPostReview:
    ok: bool
    sufficiency: Optional[ResultSufficiencyReview] = None
    error: str = ""
    trace: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "error": self.error,
            "sufficiency": self.sufficiency.to_dict() if self.sufficiency is not None else None,
            "trace": dict(self.trace),
        }


class SkillExecutionPostReviewer:
    def __init__(self, result_reviewer: ResultSufficiencyReviewer, registry: SkillRegistry) -> None:
        self.result_reviewer = result_reviewer
        self.registry = registry
        self.type_system = TypeSystem()

    def review(
        self,
        *,
        message: str,
        intent: IntentResult,
        goal: GoalDecomposition,
        plan: SkillPlan,
        execution_result: SkillPlanExecutionResult,
        context: ConversationContext,
    ) -> SkillExecutionPostReview:
        learned_contract_checks = self._learned_contract_checks(intent=intent, goal=goal, plan=plan)
        rejected = [item for item in learned_contract_checks if not item.get("compatible")]
        if rejected:
            return SkillExecutionPostReview(
                ok=False,
                error="Learned skill semantic contract is incompatible with the current goal.",
                trace={"learned_contract_checks": learned_contract_checks},
            )

        artifact = result_table_artifact(execution_result, goal, self.type_system)
        if artifact is None:
            if learned_contract_checks:
                return SkillExecutionPostReview(
                    ok=False,
                    error="Learned skill execution produced no table artifact for semantic review.",
                    trace={"learned_contract_checks": learned_contract_checks},
                )
            return SkillExecutionPostReview(ok=True, trace={"skipped": "no_table_artifact"})

        columns, rows = table_parts(artifact)
        query_payloads = invocation_query_payloads(execution_result.trace)
        query = "\n\n".join(item["query"] for item in query_payloads if item.get("query"))
        params = merged_params(query_payloads)
        reasoning = "\n".join(item["reasoning"] for item in query_payloads if item.get("reasoning"))
        sufficiency = self.result_reviewer.review(
            question=message,
            intent=intent,
            goal=goal,
            context=context,
            query=query,
            params=params,
            columns=columns,
            rows=rows,
            query_reasoning=reasoning,
            previous_successful_steps=[],
        )
        return SkillExecutionPostReview(
            ok=sufficiency.sufficient and not sufficiency.error,
            sufficiency=sufficiency,
            error=sufficiency.error or ("Skill result is insufficient for the user goal." if not sufficiency.sufficient else ""),
            trace={
                "artifact": artifact.to_dict(),
                "query_payloads": query_payloads,
                "learned_contract_checks": learned_contract_checks,
            },
        )

    def _learned_contract_checks(
        self,
        *,
        intent: IntentResult,
        goal: GoalDecomposition,
        plan: SkillPlan,
    ) -> List[Dict[str, Any]]:
        requested = contract_from_goal(intent, goal)
        result: List[Dict[str, Any]] = []
        for invocation in plan.nodes:
            skill = self.registry.get(invocation.skill_id)
            if skill is None or skill.implementation_strategy != "learned_query":
                continue
            compatibility = semantic_contract_compatibility(
                requested,
                SemanticSkillContract.from_dict(skill.semantic_contract),
            )
            result.append({"skill_id": skill.skill_id, **compatibility.to_dict()})
        return result


def result_table_artifact(
    execution_result: SkillPlanExecutionResult,
    goal: GoalDecomposition,
    type_system: TypeSystem,
) -> Optional[Artifact]:
    required_types = [item.type for item in goal.required_artifacts if type_system.is_assignable(item.type, "TypedTable")]
    artifacts = list(execution_result.artifacts.values())
    for required_type in required_types:
        for artifact in reversed(artifacts):
            if type_system.is_assignable(artifact.type, required_type):
                return artifact
    for artifact in reversed(artifacts):
        if type_system.is_assignable(artifact.type, "TypedTable"):
            return artifact
    return None


def table_parts(artifact: Artifact) -> tuple[List[str], List[Dict[str, Any]]]:
    value = artifact.value
    if not isinstance(value, Mapping):
        return [], []
    columns = [str(item) for item in value.get("columns", []) or []]
    rows = [dict(item) for item in value.get("rows", []) or [] if isinstance(item, Mapping)]
    if not columns:
        for row in rows:
            for key in row:
                if str(key) not in columns:
                    columns.append(str(key))
    return columns, rows


def invocation_query_payloads(trace: Mapping[str, Any]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for invocation in trace.get("invocations", []) or []:
        if not isinstance(invocation, Mapping):
            continue
        invocation_trace = invocation.get("trace") if isinstance(invocation.get("trace"), Mapping) else {}
        draft = invocation_trace.get("query_draft") if isinstance(invocation_trace.get("query_draft"), Mapping) else {}
        query = str(draft.get("query") or "")
        if not query:
            continue
        result.append(
            {
                "invocation_id": str(invocation.get("invocation_id") or ""),
                "skill_id": str(invocation.get("skill_id") or ""),
                "query": query,
                "params": dict(draft.get("params") or {}),
                "reasoning": str(draft.get("reasoning") or ""),
            }
        )
    return result


def merged_params(payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for payload in payloads:
        for key, value in (payload.get("params") or {}).items():
            result[str(key)] = value
    return result

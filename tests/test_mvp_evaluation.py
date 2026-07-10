from __future__ import annotations

import unittest

from wiicon5.agent.orchestrator import AgentRunResult
from wiicon5.evaluation.mvp import MvpEvaluationCase, run_mvp_evaluation
from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.models import SkillContract, SkillInvocation, SkillPlan
from wiicon5.skills.registry import SkillRegistry


class MvpEvaluationTests(unittest.TestCase):
    def test_reports_cold_creation_and_warm_reuse(self) -> None:
        agent = ScriptedLearningAgent(reuse=True)
        case = MvpEvaluationCase(
            case_id="reuse",
            cold_question="cold",
            warm_question="warm",
            warm_expectation="reuse_new_skill",
        )

        result = run_mvp_evaluation([case], agent)

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(result.case_results[0].created_skill_ids, ["learned_test"])
        self.assertEqual(result.case_results[0].reused_created_skill_ids, ["learned_test"])
        self.assertEqual(result.to_dict()["summary"]["created_skill_reuse_rate"], 1.0)

    def test_detects_false_reuse_for_semantically_different_warm_question(self) -> None:
        agent = ScriptedLearningAgent(reuse=True)
        case = MvpEvaluationCase(
            case_id="negative",
            cold_question="cold",
            warm_question="warm",
            warm_expectation="do_not_reuse_new_skill",
        )

        result = run_mvp_evaluation([case], agent)

        self.assertFalse(result.ok)
        self.assertIn("false_reuse_of_cold_skill", result.case_results[0].issues)

    def test_accepts_reuse_of_preexisting_skill_without_requiring_learning(self) -> None:
        agent = ScriptedExistingSkillAgent()
        case = MvpEvaluationCase(
            case_id="existing",
            cold_question="cold",
            warm_question="warm",
            warm_expectation="reuse_any_skill",
        )

        result = run_mvp_evaluation([case], agent)

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(result.case_results[0].created_skill_ids, [])
        self.assertEqual(result.to_dict()["summary"]["warm_skill_plan_rate"], 1.0)


class ScriptedLearningAgent:
    def __init__(self, *, reuse: bool) -> None:
        self.registry = SkillRegistry()
        self.reuse = reuse
        self.calls = 0

    def handle(self, question: str, *, session_id: str) -> AgentRunResult:
        self.calls += 1
        intent = IntentResult(
            intent_type=IntentType.DATA_QUESTION,
            business_goal=question,
            requires_1c_data=True,
            relevant=True,
        )
        if self.calls == 1:
            self.registry.add(learned_skill())
            return AgentRunResult(source="query_synthesis_ok", message="ok", intent=intent)
        plan = None
        if self.reuse:
            plan = SkillPlan(
                plan_id="p1",
                business_goal=question,
                expected_answer_type="table",
                nodes=[SkillInvocation(invocation_id="n1", skill_id="learned_test")],
                edges=[],
            )
        return AgentRunResult(
            source="skill_execution_ok" if self.reuse else "query_synthesis_ok",
            message="ok",
            intent=intent,
            plan=plan,
        )


class ScriptedExistingSkillAgent:
    def __init__(self) -> None:
        self.registry = SkillRegistry()

    def handle(self, question: str, *, session_id: str) -> AgentRunResult:
        intent = IntentResult(
            intent_type=IntentType.DATA_QUESTION,
            business_goal=question,
            requires_1c_data=True,
            relevant=True,
        )
        plan = SkillPlan(
            plan_id="p-existing",
            business_goal=question,
            expected_answer_type="table",
            nodes=[SkillInvocation(invocation_id="n1", skill_id="seed_existing")],
            edges=[],
        )
        return AgentRunResult(
            source="skill_execution_ok",
            message="ok",
            intent=intent,
            plan=plan,
        )


def learned_skill() -> SkillContract:
    return SkillContract.from_dict(
        {
            "skill_id": "learned_test",
            "kind": "data_acquisition",
            "status": "verified",
            "description": "test",
            "outputs": [{"name": "table", "type": "LearnedQueryTable"}],
            "implementation_strategy": "learned_query",
            "semantic_contract": {"schema_version": 2, "operation": "list"},
            "implementation": {"kind": "semantic_query_template", "schema_version": 2},
        }
    )


if __name__ == "__main__":
    unittest.main()

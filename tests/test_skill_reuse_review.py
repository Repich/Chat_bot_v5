from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.conversation.context import ConversationContext
from wiicon5.execution.artifacts import Artifact
from wiicon5.execution.runtime import SkillPlanExecutionResult
from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.llm.client import LLMProviderError, ScriptedLLMClient
from wiicon5.models import ArtifactRequirement, SkillInvocation, SkillPlan
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.query_synthesis.reuse_review import SkillExecutionPostReviewer
from wiicon5.query_synthesis.sufficiency import ResultSufficiencyReviewer
from wiicon5.skills.learned import LearnedSkillRuntimeHealthStore
from wiicon5.skills.registry import SkillRegistry
from wiicon5.skills.semantic_contract import SemanticMeasure, SemanticSkillContract
from tests.test_semantic_skill_contract import learned_skill


class SkillReuseReviewTests(unittest.TestCase):
    def test_nonempty_but_wrong_result_is_rejected(self) -> None:
        question = "Покажи сумму реализаций за 2024 год"
        contract = SemanticSkillContract(
            subject_terms=["реализация"],
            operation="aggregate",
            measures=[SemanticMeasure(role="стоимость", aggregation="sum", result_column="Сумма")],
            required_filter_roles=["year"],
            optional_filter_roles=["year"],
            result_columns=["Сумма"],
            original_question=question,
        )
        skill = learned_skill("learned_sum", contract)
        registry = SkillRegistry([skill])
        reviewer = SkillExecutionPostReviewer(
            ResultSufficiencyReviewer(
                ScriptedLLMClient(
                    [
                        {
                            "sufficient": False,
                            "partial": True,
                            "missing_facts": ["Получена средняя стоимость вместо суммы."],
                            "next_query_goal": "Получить сумму реализаций.",
                            "reasoning": "Число есть, но показатель не соответствует вопросу.",
                        }
                    ]
                )
            ),
            registry,
        )
        plan, execution = plan_and_execution(skill.skill_id, {"СредняяСтоимость": 7547.9})

        review = reviewer.review(
            message=question,
            intent=data_intent(question),
            goal=aggregate_goal(question, contract),
            plan=plan,
            execution_result=execution,
            context=ConversationContext(session_id="s1", config_fingerprint="cfg_test"),
        )

        self.assertFalse(review.ok)
        assert review.sufficiency is not None
        self.assertIn("вместо суммы", review.sufficiency.missing_facts[0])

    def test_sufficiency_provider_failure_is_fail_closed(self) -> None:
        reviewer = ResultSufficiencyReviewer(FailingLLMClient([]))

        review = reviewer.review(
            question="Покажи продажи",
            intent=data_intent("Покажи продажи"),
            goal=GoalDecomposition(
                business_goal="Покажи продажи",
                final_artifact_type="UserAnswer",
                required_artifacts=[ArtifactRequirement(name="sales", type="LearnedQueryTable")],
            ),
            context=ConversationContext(session_id="s1", config_fingerprint="cfg_test"),
            query="ВЫБРАТЬ Продажи.Сумма КАК Сумма ИЗ РегистрНакопления.Продажи КАК Продажи",
            params={},
            columns=["Сумма"],
            rows=[{"Сумма": 100}],
            query_reasoning="",
            previous_successful_steps=[],
        )

        self.assertFalse(review.sufficient)
        self.assertTrue(review.error)

    def test_rejected_semantic_result_counts_as_health_failure(self) -> None:
        contract = SemanticSkillContract(subject_terms=["реализация"], operation="list")
        skill = learned_skill("learned_health", contract)
        with TemporaryDirectory() as temp_dir:
            skills_dir = Path(temp_dir) / "skills"
            active_dir = skills_dir / "learned" / "active"
            active_dir.mkdir(parents=True)
            path = active_dir / f"{skill.skill_id}.json"
            payload = skill.to_dict()
            payload["implementation"]["runtime_health"] = {
                "reuse_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "consecutive_failures": 0,
                "auto_blocked": False,
            }
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            registry = SkillRegistry([skill])
            store = LearnedSkillRuntimeHealthStore(skills_dir=skills_dir, registry=registry, failure_threshold=3)
            plan, execution = plan_and_execution(skill.skill_id, {"Сумма": 100})
            context = ConversationContext(session_id="s1", config_fingerprint="cfg_test")
            context.append_message("user", "Покажи продажи")

            store.record_plan_outcome(
                plan=plan,
                execution_result=execution,
                context=context,
                accepted=False,
                error="semantic result rejected",
            )

            health = json.loads(path.read_text(encoding="utf-8"))["implementation"]["runtime_health"]

        self.assertEqual(health["reuse_count"], 1)
        self.assertEqual(health["success_count"], 0)
        self.assertEqual(health["failure_count"], 1)

    def test_downstream_failure_does_not_penalize_successful_learned_query(self) -> None:
        contract = SemanticSkillContract(subject_terms=["реализация"], operation="list")
        skill = learned_skill("learned_health", contract)
        with TemporaryDirectory() as temp_dir:
            skills_dir = Path(temp_dir) / "skills"
            active_dir = skills_dir / "learned" / "active"
            active_dir.mkdir(parents=True)
            path = active_dir / f"{skill.skill_id}.json"
            payload = skill.to_dict()
            payload["implementation"]["runtime_health"] = {
                "reuse_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "consecutive_failures": 0,
                "auto_blocked": False,
            }
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            registry = SkillRegistry([skill])
            store = LearnedSkillRuntimeHealthStore(skills_dir=skills_dir, registry=registry, failure_threshold=3)
            plan, execution = plan_and_execution(skill.skill_id, {"Сумма": 100})
            execution = SkillPlanExecutionResult(
                ok=False,
                artifacts=execution.artifacts,
                error="renderer failed",
                failed_invocation_id="n2",
                trace={
                    "invocations": [
                        *execution.trace["invocations"],
                        {"invocation_id": "n2", "skill_id": "renderer", "ok": False, "error": "renderer failed"},
                    ]
                },
            )
            context = ConversationContext(session_id="s1", config_fingerprint="cfg_test")

            store.record_plan_outcome(
                plan=plan,
                execution_result=execution,
                context=context,
                accepted=False,
                error=execution.error,
            )

            health = json.loads(path.read_text(encoding="utf-8"))["implementation"]["runtime_health"]

        self.assertEqual(health["reuse_count"], 0)
        self.assertEqual(health["failure_count"], 0)


class FailingLLMClient(ScriptedLLMClient):
    def complete_json(self, *, system_prompt: str, user_payload: dict) -> dict:
        raise LLMProviderError("HTTP 503")


def plan_and_execution(skill_id: str, row: dict) -> tuple[SkillPlan, SkillPlanExecutionResult]:
    plan = SkillPlan(
        plan_id="plan_test",
        business_goal="test",
        expected_answer_type="table",
        nodes=[
            SkillInvocation(
                invocation_id="n1",
                skill_id=skill_id,
                inputs={"filters": []},
                expected_outputs={"table": "AggregateTable"},
            )
        ],
        edges=[],
    )
    table = Artifact(
        name="table",
        type="AggregateTable",
        value={"columns": list(row), "rows": [row]},
        provenance=[skill_id],
    )
    execution = SkillPlanExecutionResult(
        ok=True,
        artifacts={"n1.table": table},
        final_artifact=table,
        trace={
            "invocations": [
                {
                    "invocation_id": "n1",
                    "skill_id": skill_id,
                    "ok": True,
                    "inputs": {"filters": []},
                    "trace": {
                        "query_draft": {
                            "query": "ВЫБРАТЬ СУММА(Продажи.Сумма) КАК Сумма ИЗ РегистрНакопления.Продажи КАК Продажи",
                            "params": {},
                            "reasoning": "learned template",
                        }
                    },
                }
            ]
        },
    )
    return plan, execution


def data_intent(question: str) -> IntentResult:
    return IntentResult(
        intent_type=IntentType.DATA_QUESTION,
        business_goal=question,
        requires_1c_data=True,
        expected_output="table",
        domain_terms=["реализации"],
        relevant=True,
    )


def aggregate_goal(question: str, contract: SemanticSkillContract) -> GoalDecomposition:
    return GoalDecomposition(
        business_goal=question,
        final_artifact_type="UserAnswer",
        expected_answer_type="table",
        required_artifacts=[
            ArtifactRequirement(name="metrics", type="AggregateTable", required_columns=["Сумма"])
        ],
        semantic_contract=contract.to_dict(),
    )


if __name__ == "__main__":
    unittest.main()

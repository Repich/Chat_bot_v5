from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.agent.orchestrator import AgentOrchestrator
from wiicon5.conversation.memory import ConversationMemory
from wiicon5.execution.artifacts import Artifact
from wiicon5.execution.runtime import SkillPlanExecutor, StaticSkillRunner, default_runners
from wiicon5.intent.decomposer import DecompositionResult
from wiicon5.intent.models import ContextDependency, IntentResult, IntentType
from wiicon5.models import ArtifactRequirement, SemanticFilter, SkillContract
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.policies.domain_policy import DomainPolicy
from wiicon5.bot_instance import BotInstanceConfig
from wiicon5.skills.registry import SkillRegistry
from wiicon5.testing.scripted_decomposer import ScriptedGoalDecomposer


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AgentOrchestratorTests(unittest.TestCase):
    def test_agent_builds_skill_plan_and_writes_trace(self) -> None:
        question = "Покажи остатки товара на оптовых складах"
        with TemporaryDirectory() as temp_dir:
            orchestrator = AgentOrchestrator(
                registry=SkillRegistry.load_from_dir(PROJECT_ROOT / "skills"),
                decomposer=ScriptedGoalDecomposer({question: stock_question_decomposition()}),
                trace_root=Path(temp_dir),
            )

            result = orchestrator.handle(question, session_id="s1")

            self.assertEqual(result.source, "skill_plan_ready")
            self.assertIsNotNone(result.plan)
            assert result.plan is not None
            self.assertEqual(
                [node.skill_id for node in result.plan.nodes],
                [
                    "resolve_product_from_dialog_context",
                    "get_warehouses",
                    "get_stock_balances",
                    "render_table_answer",
                ],
            )
            trace_path = Path(result.trace_path or "")
            self.assertTrue((trace_path / "input/conversation_packet.json").exists())
            self.assertTrue((trace_path / "intent/goal_decomposition.json").exists())
            self.assertTrue((trace_path / "skill_plan/plan_graph.json").exists())
            self.assertTrue((trace_path / "skill_search/composer_trace.json").exists())
            plan_payload = json.loads((trace_path / "skill_plan/plan_graph.json").read_text(encoding="utf-8"))
            composer_trace = json.loads((trace_path / "skill_search/composer_trace.json").read_text(encoding="utf-8"))
            self.assertEqual(plan_payload["nodes"][1]["skill_id"], "get_warehouses")
            selected = [item["selected"] for item in composer_trace["items"]]
            self.assertIn("get_warehouses", selected)

    def test_agent_executes_skill_plan_when_executor_is_configured(self) -> None:
        question = "Покажи остатки товара на оптовых складах"
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        memory = ConversationMemory()
        context = memory.get_or_create("s1")
        context.add_artifact(Artifact(name="product", type="ProductRef", value={"ref": "product-1"}, provenance=["test"]))
        data_runner = StaticSkillRunner(
            {
                "get_warehouses": [
                    Artifact(
                        name="warehouses",
                        type="WarehouseRefList",
                        value=[{"ref": "warehouse-1", "name": "Оптовый склад"}],
                        provenance=["test"],
                    )
                ],
                "get_stock_balances": [
                    Artifact(
                        name="stock_table",
                        type="StockBalanceTable",
                        value={"columns": ["Склад", "Остаток"], "rows": [{"Склад": "Оптовый склад", "Остаток": 42}]},
                        provenance=["test"],
                    )
                ],
            }
        )
        runners = default_runners()
        runners["semantic_binding_query"] = data_runner
        runners["semantic_measure_query"] = data_runner
        with TemporaryDirectory() as temp_dir:
            orchestrator = AgentOrchestrator(
                registry=registry,
                decomposer=ScriptedGoalDecomposer({question: stock_question_decomposition()}),
                memory=memory,
                plan_executor=SkillPlanExecutor(registry, runners),
                trace_root=Path(temp_dir),
            )

            result = orchestrator.handle(question, session_id="s1")

            self.assertEqual(result.source, "skill_execution_ok")
            self.assertIsNotNone(result.final_artifact)
            self.assertIn("Оптовый склад", result.message)
            self.assertIn("42", result.message)
            trace_path = Path(result.trace_path or "")
            self.assertTrue((trace_path / "skill_invocations/execution_result.json").exists())

    def test_agent_returns_gap_and_evolution_decision_for_missing_filter_support(self) -> None:
        question = "Покажи остатки товара на оптовых складах"
        base_registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        warehouse_skill = base_registry.get("get_warehouses")
        assert warehouse_skill is not None
        narrow_warehouse_skill = SkillContract.from_dict(
            {**warehouse_skill.to_dict(), "supported_filter_roles": ["city"]}
        )
        registry = SkillRegistry(
            [
                skill if skill.skill_id != "get_warehouses" else narrow_warehouse_skill
                for skill in base_registry.all()
            ]
        )
        with TemporaryDirectory() as temp_dir:
            orchestrator = AgentOrchestrator(
                registry=registry,
                decomposer=ScriptedGoalDecomposer({question: stock_question_decomposition()}),
                trace_root=Path(temp_dir),
            )

            result = orchestrator.handle(question, session_id="s1")

            self.assertEqual(result.source, "skill_gap")
            self.assertEqual(result.gaps[0].recommended_resolution.value, "extend_existing_skill")
            self.assertEqual(result.evolution_decisions[0].decision.value, "extend_existing_skill")
            self.assertTrue(result.evolution_decisions[0].forbidden_new_skill)
            trace_path = Path(result.trace_path or "")
            self.assertTrue((trace_path / "learning/evolution_decision.json").exists())

    def test_agent_rejects_out_of_scope_question_before_skill_search(self) -> None:
        question = "Какая сегодня погода?"
        with TemporaryDirectory() as temp_dir:
            orchestrator = AgentOrchestrator(
                registry=SkillRegistry.load_from_dir(PROJECT_ROOT / "skills"),
                decomposer=ScriptedGoalDecomposer(
                    {
                        question: DecompositionResult(
                            intent=IntentResult(
                                intent_type=IntentType.OUT_OF_SCOPE,
                                business_goal=question,
                                requires_1c_data=False,
                                relevant=False,
                            )
                        )
                    }
                ),
                trace_root=Path(temp_dir),
            )

            result = orchestrator.handle(question, session_id="s1")

            self.assertEqual(result.source, "out_of_scope")
            self.assertIn("синоптиком", result.message)
            self.assertIsNone(result.plan)
            self.assertEqual(result.gaps, [])

    def test_agent_answers_general_question_without_skill_plan(self) -> None:
        question = "Привет, кто ты?"
        decomposer = ScriptedGoalDecomposer({})
        with TemporaryDirectory() as temp_dir:
            orchestrator = AgentOrchestrator(
                registry=SkillRegistry.load_from_dir(PROJECT_ROOT / "skills"),
                decomposer=decomposer,
                trace_root=Path(temp_dir),
            )

            result = orchestrator.handle(question, session_id="s1")

        self.assertEqual(result.source, "general_answer")
        self.assertIn("WIICON ChatBot 5", result.message)
        self.assertIsNone(result.plan)
        self.assertEqual(decomposer.calls, [])

    def test_agent_uses_bot_instance_domain_policy_for_general_answer(self) -> None:
        question = "Привет"
        decomposer = ScriptedGoalDecomposer({})
        domain_policy = DomainPolicy(
            BotInstanceConfig(
                bot_id="custom",
                bot_name="Custom Agent",
                domain_label="тестовая 1С",
                intro_answer="Я Custom Agent для тестовой 1С.",
            )
        )
        with TemporaryDirectory() as temp_dir:
            orchestrator = AgentOrchestrator(
                registry=SkillRegistry.load_from_dir(PROJECT_ROOT / "skills"),
                decomposer=decomposer,
                domain_policy=domain_policy,
                trace_root=Path(temp_dir),
            )

            result = orchestrator.handle(question, session_id="s1")

        self.assertEqual(result.source, "general_answer")
        self.assertEqual(result.message, "Я Custom Agent для тестовой 1С.")
        self.assertEqual(decomposer.calls, [])


def stock_question_decomposition() -> DecompositionResult:
    return DecompositionResult(
        intent=IntentResult(
            intent_type=IntentType.DATA_QUESTION,
            business_goal="Показать остатки ранее найденного товара на оптовых складах",
            requires_1c_data=True,
            expected_output="table",
            domain_terms=["остатки", "товар", "оптовые склады"],
            context_dependencies=[
                ContextDependency(
                    role="product",
                    artifact_type="ProductRef",
                    source="dialog_context",
                )
            ],
        ),
        goal=GoalDecomposition(
            business_goal="Показать остатки ранее найденного товара на оптовых складах",
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[
                ArtifactRequirement(name="product", type="ProductRef", source="dialog_context"),
                ArtifactRequirement(
                    name="warehouses",
                    type="WarehouseRefList",
                    constraints=[
                        SemanticFilter(
                            semantic_field="warehouse_type",
                            operator="equals",
                            value="wholesale",
                            raw_user_text="оптовые",
                        )
                    ],
                ),
                ArtifactRequirement(name="stock_table", type="StockBalanceTable"),
            ],
        ),
    )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path

from wiicon5.conversation.context import ConversationContext
from wiicon5.execution.artifacts import Artifact
from wiicon5.execution.runtime import SkillPlanExecutor, StaticSkillRunner, default_runners
from wiicon5.models import ArtifactRequirement, SemanticFilter
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.skills.composer import SkillComposer
from wiicon5.skills.registry import SkillRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SkillRuntimeTests(unittest.TestCase):
    def test_executor_runs_composed_plan_with_typed_artifacts(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        plan = build_stock_plan(registry)
        context = ConversationContext(session_id="s1")
        context.add_artifact(
            Artifact(
                name="product",
                type="ProductRef",
                value={"ref": "product-abc"},
                provenance=["test"],
            )
        )
        scripted_data_runner = StaticSkillRunner(
            {
                "get_warehouses": [
                    Artifact(
                        name="warehouses",
                        type="WarehouseRefList",
                        value=[{"ref": "wh-1", "name": "Оптовый склад"}],
                        provenance=["mock_mcp"],
                    )
                ],
                "get_stock_balances": [
                    Artifact(
                        name="stock_table",
                        type="StockBalanceTable",
                        value={
                            "columns": ["Склад", "Остаток"],
                            "rows": [{"Склад": "Оптовый склад", "Остаток": 42}],
                        },
                        provenance=["mock_mcp"],
                    )
                ],
            }
        )
        runners = default_runners()
        runners["semantic_binding_query"] = scripted_data_runner
        runners["semantic_measure_query"] = scripted_data_runner
        executor = SkillPlanExecutor(registry, runners)

        result = executor.execute(plan, context)

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.final_artifact)
        assert result.final_artifact is not None
        self.assertEqual(result.final_artifact.type, "UserAnswer")
        self.assertIn("Оптовый склад", result.final_artifact.value)
        self.assertIn("42", result.final_artifact.value)
        stock_call = next(call for call in scripted_data_runner.calls if call["skill_id"] == "get_stock_balances")
        self.assertEqual(stock_call["inputs"]["product"]["ref"], "product-abc")
        self.assertEqual(stock_call["inputs"]["warehouses"][0]["ref"], "wh-1")

    def test_executor_fails_when_context_artifact_is_missing(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        plan = build_stock_plan(registry)
        executor = SkillPlanExecutor(registry, default_runners())

        result = executor.execute(plan, ConversationContext(session_id="s1"))

        self.assertFalse(result.ok)
        self.assertEqual(result.failed_invocation_id, "inv_001")
        self.assertIn("Missing context artifact", result.error)

    def test_executor_renders_entity_list_answer(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        goal = GoalDecomposition(
            business_goal="Показать склады",
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[ArtifactRequirement(name="warehouses", type="WarehouseRefList")],
        )
        compose_result = SkillComposer(registry).compose(goal)
        assert compose_result.plan is not None
        scripted_data_runner = StaticSkillRunner(
            {
                "get_warehouses": [
                    Artifact(
                        name="warehouses",
                        type="WarehouseRefList",
                        value=[{"Ссылка": "wh-1", "Наименование": "Основной склад"}],
                        provenance=["mock_mcp"],
                    )
                ]
            }
        )
        runners = default_runners()
        runners["semantic_binding_query"] = scripted_data_runner
        executor = SkillPlanExecutor(registry, runners)
        context = ConversationContext(session_id="s1")
        context.append_message("user", "Показать склады")

        result = executor.execute(compose_result.plan, context)

        self.assertTrue(result.ok)
        assert result.final_artifact is not None
        self.assertEqual(result.final_artifact.type, "UserAnswer")
        self.assertIn("Основной склад", result.final_artifact.value)

    def test_entity_list_renderer_formats_one_c_object_refs(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        goal = GoalDecomposition(
            business_goal="Показать склады",
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[ArtifactRequirement(name="warehouses", type="WarehouseRefList")],
        )
        compose_result = SkillComposer(registry).compose(goal)
        assert compose_result.plan is not None
        scripted_data_runner = StaticSkillRunner(
            {
                "get_warehouses": [
                    Artifact(
                        name="warehouses",
                        type="WarehouseRefList",
                        value=[
                            {
                                "Ссылка": {
                                    "_objectRef": True,
                                    "УникальныйИдентификатор": "wh-1",
                                    "Представление": "Основной склад",
                                },
                                "Наименование": "Основной склад",
                            }
                        ],
                        provenance=["mock_mcp"],
                    )
                ]
            }
        )
        runners = default_runners()
        runners["semantic_binding_query"] = scripted_data_runner
        executor = SkillPlanExecutor(registry, runners)
        context = ConversationContext(session_id="s1")
        context.append_message("user", "Показать склады")

        result = executor.execute(compose_result.plan, context)

        self.assertTrue(result.ok)
        assert result.final_artifact is not None
        self.assertIn("Основной склад", result.final_artifact.value)
        self.assertNotIn("_objectRef", result.final_artifact.value)

    def test_executor_counts_filtered_entity_list_with_generic_transform(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        goal = GoalDecomposition(
            business_goal="Сколько в системе розничных складов?",
            final_artifact_type="UserAnswer",
            expected_answer_type="short_answer",
            required_artifacts=[
                ArtifactRequirement(
                    name="warehouse_count",
                    type="AggregateTable",
                    constraints=[SemanticFilter(semantic_field="warehouse_type", operator="equals", value="розничный")],
                )
            ],
        )
        compose_result = SkillComposer(registry).compose(goal)
        assert compose_result.plan is not None
        scripted_data_runner = StaticSkillRunner(
            {
                "get_warehouses": [
                    Artifact(
                        name="warehouses",
                        type="WarehouseRefList",
                        value=[
                            {"Ссылка": "wh-1", "Наименование": "Магазин 1"},
                            {"Ссылка": "wh-2", "Наименование": "Магазин 2"},
                        ],
                        provenance=["mock_mcp"],
                    )
                ]
            }
        )
        runners = default_runners()
        runners["semantic_binding_query"] = scripted_data_runner
        executor = SkillPlanExecutor(registry, runners)
        context = ConversationContext(session_id="s1")
        context.append_message("user", "Сколько в системе розничных складов?")

        result = executor.execute(compose_result.plan, context)

        self.assertTrue(result.ok)
        assert result.final_artifact is not None
        self.assertEqual(result.final_artifact.type, "UserAnswer")
        self.assertIn("Количество: 2", result.final_artifact.value)


def build_stock_plan(registry: SkillRegistry):
    goal = GoalDecomposition(
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
    )
    result = SkillComposer(registry).compose(goal)
    assert result.plan is not None
    return result.plan


if __name__ == "__main__":
    unittest.main()

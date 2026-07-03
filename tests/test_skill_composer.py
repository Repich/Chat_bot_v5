from __future__ import annotations

import unittest
from pathlib import Path

from wiicon5.models import ArtifactRequirement, SemanticFilter, SkillContract
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.skills.composer import SkillComposer
from wiicon5.skills.registry import SkillRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SkillComposerTests(unittest.TestCase):
    def test_composer_builds_stock_on_filtered_warehouses_dag(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        composer = SkillComposer(registry)
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

        result = composer.compose(goal)

        self.assertEqual(result.gaps, [])
        self.assertIsNotNone(result.plan)
        assert result.plan is not None
        skill_ids = [node.skill_id for node in result.plan.nodes]
        self.assertEqual(
            skill_ids,
            [
                "resolve_product_from_dialog_context",
                "get_warehouses",
                "get_stock_balances",
                "render_table_answer",
            ],
        )
        self.assertNotIn("get_wholesale_warehouses", skill_ids)
        warehouse_node = next(node for node in result.plan.nodes if node.skill_id == "get_warehouses")
        self.assertEqual(warehouse_node.inputs["filters"][0]["semantic_field"], "warehouse_type")
        stock_node = next(node for node in result.plan.nodes if node.skill_id == "get_stock_balances")
        self.assertEqual(stock_node.inputs["product"], "${inv_001.product}")
        self.assertEqual(stock_node.inputs["warehouses"], "${inv_002.warehouses}")

    def test_composer_does_not_require_product_when_goal_only_filters_stock_by_warehouse(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        composer = SkillComposer(registry)
        goal = GoalDecomposition(
            business_goal="Показать остатки по выбранному складу",
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[
                ArtifactRequirement(
                    name="warehouses",
                    type="WarehouseRefList",
                    constraints=[SemanticFilter(semantic_field="name", operator="equals", value="Центральный склад")],
                ),
                ArtifactRequirement(name="stock_table", type="StockBalanceTable"),
            ],
        )

        result = composer.compose(goal)

        self.assertEqual(result.gaps, [])
        self.assertIsNotNone(result.plan)
        assert result.plan is not None
        skill_ids = [node.skill_id for node in result.plan.nodes]
        self.assertEqual(skill_ids, ["get_warehouses", "get_stock_balances", "render_table_answer"])
        stock_node = next(node for node in result.plan.nodes if node.skill_id == "get_stock_balances")
        self.assertNotIn("product", stock_node.inputs)
        self.assertTrue(str(stock_node.inputs["warehouses"]).startswith("${"))

    def test_composer_reports_gap_when_existing_skill_needs_filter_extension(self) -> None:
        base_registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        warehouse_skill = base_registry.get("get_warehouses")
        assert warehouse_skill is not None
        narrow_warehouse_skill = SkillContract.from_dict(
            {
                **warehouse_skill.to_dict(),
                "supported_filter_roles": ["city"],
            }
        )
        registry = SkillRegistry(
            [
                skill if skill.skill_id != "get_warehouses" else narrow_warehouse_skill
                for skill in base_registry.all()
            ]
        )
        composer = SkillComposer(registry)
        goal = GoalDecomposition(
            business_goal="Показать остатки ранее найденного товара на оптовых складах",
            final_artifact_type="UserAnswer",
            required_artifacts=[
                ArtifactRequirement(name="product", type="ProductRef", source="dialog_context"),
                ArtifactRequirement(
                    name="warehouses",
                    type="WarehouseRefList",
                    constraints=[SemanticFilter(semantic_field="warehouse_type", operator="equals", value="wholesale")],
                ),
                ArtifactRequirement(name="stock_table", type="StockBalanceTable"),
            ],
        )

        result = composer.compose(goal)

        self.assertIsNone(result.plan)
        self.assertEqual(len(result.gaps), 1)
        self.assertEqual(result.gaps[0].recommended_resolution.value, "extend_existing_skill")
        self.assertEqual(result.gaps[0].nearest_skill_ids, ["get_warehouses"])
        self.assertIn("filter:warehouse_type", result.gaps[0].missing)

    def test_composer_builds_entity_list_answer_for_warehouses(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        composer = SkillComposer(registry)
        goal = GoalDecomposition(
            business_goal="Показать склады",
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[
                ArtifactRequirement(name="warehouses", type="WarehouseRefList"),
            ],
        )

        result = composer.compose(goal)

        self.assertEqual(result.gaps, [])
        self.assertIsNotNone(result.plan)
        assert result.plan is not None
        self.assertEqual([node.skill_id for node in result.plan.nodes], ["get_warehouses", "render_entity_list_answer"])

    def test_composer_builds_document_count_by_period_plan(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        composer = SkillComposer(registry)
        goal = GoalDecomposition(
            business_goal="Показать количество перемещений по дням",
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[
                ArtifactRequirement(name="document_counts", type="DocumentCountByPeriodTable"),
            ],
        )

        result = composer.compose(goal)

        self.assertEqual(result.gaps, [])
        self.assertIsNotNone(result.plan)
        assert result.plan is not None
        self.assertEqual(
            [node.skill_id for node in result.plan.nodes],
            ["count_transfer_documents_by_day", "render_table_answer"],
        )

    def test_composer_treats_matching_document_type_as_domain_selector_not_runtime_filter(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        composer = SkillComposer(registry)
        goal = GoalDecomposition(
            business_goal="Показать количество документов выбранного домена по дням",
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[
                ArtifactRequirement(
                    name="document_counts",
                    type="DocumentCountByPeriodTable",
                    constraints=[
                        SemanticFilter(
                            semantic_field="document_type",
                            operator="equals",
                            value="Перемещение товаров",
                            raw_user_text="перемещений",
                        ),
                        SemanticFilter(
                            semantic_field="period_granularity",
                            operator="equals",
                            value="day",
                            raw_user_text="по дням",
                        ),
                    ],
                ),
            ],
        )

        result = composer.compose(goal)

        self.assertEqual(result.gaps, [])
        self.assertIsNotNone(result.plan)
        assert result.plan is not None
        data_node = result.plan.nodes[0]
        self.assertEqual(data_node.skill_id, "count_transfer_documents_by_day")
        self.assertEqual(data_node.inputs["period_granularity"], "day")
        self.assertNotIn("filters", data_node.inputs)

    def test_composer_rejects_abstract_entity_list_goal_instead_of_reusing_concrete_skill(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        composer = SkillComposer(registry)
        goal = GoalDecomposition(
            business_goal="Показать список объектов неизвестного бизнес-домена",
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[
                ArtifactRequirement(
                    name="items",
                    type="EntityRefList",
                    constraints=[SemanticFilter(semantic_field="foreign_domain", operator="equals", value="x")],
                ),
            ],
        )

        result = composer.compose(goal)

        self.assertIsNone(result.plan)
        self.assertEqual(len(result.gaps), 1)
        self.assertEqual(result.gaps[0].required_output, "EntityRefList")
        self.assertIn("concrete_artifact_type", result.gaps[0].missing)
        self.assertNotIn("get_warehouses", result.gaps[0].nearest_skill_ids)

    def test_composer_reports_missing_concrete_table_artifact_without_reusing_other_table_skill(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        composer = SkillComposer(registry)
        goal = GoalDecomposition(
            business_goal="Показать строки документов неизвестного вида",
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[
                ArtifactRequirement(name="document_lines", type="DocumentLineTable"),
            ],
        )

        result = composer.compose(goal)

        self.assertIsNone(result.plan)
        self.assertEqual(len(result.gaps), 1)
        self.assertEqual(result.gaps[0].required_output, "DocumentLineTable")
        self.assertEqual(result.gaps[0].recommended_resolution.value, "create_new_atomic_skill")
        self.assertNotIn("get_stock_balances", result.gaps[0].nearest_skill_ids)
        self.assertNotIn("count_transfer_documents_by_day", result.gaps[0].nearest_skill_ids)

    def test_composer_builds_generic_document_list_plan_from_concrete_artifact(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        composer = SkillComposer(registry)
        goal = GoalDecomposition(
            business_goal="Показать документы заданного вида за заданный год",
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[
                ArtifactRequirement(
                    name="documents",
                    type="DocumentListTable",
                    constraints=[
                        SemanticFilter(semantic_field="document_type", operator="equals", value="Сервисный акт"),
                        SemanticFilter(semantic_field="year", operator="equals", value="2024"),
                    ],
                ),
            ],
        )

        result = composer.compose(goal)

        self.assertEqual(result.gaps, [])
        self.assertIsNotNone(result.plan)
        assert result.plan is not None
        self.assertEqual(
            [node.skill_id for node in result.plan.nodes],
            ["get_documents_by_type_and_period", "render_table_answer"],
        )
        data_node = result.plan.nodes[0]
        self.assertEqual(data_node.inputs["filters"][0]["semantic_field"], "document_type")
        self.assertEqual(data_node.inputs["filters"][1]["semantic_field"], "year")

    def test_composer_rejects_document_list_for_aggregate_goal(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        composer = SkillComposer(registry)
        goal = GoalDecomposition(
            business_goal="Показать самую продающуюся номенклатуру",
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[
                ArtifactRequirement(
                    name="documents",
                    type="DocumentListTable",
                    constraints=[
                        SemanticFilter(semantic_field="document_type", operator="equals", value="РеализацияТоваровУслуг")
                    ],
                ),
            ],
        )

        result = composer.compose(goal)

        self.assertIsNone(result.plan)
        self.assertEqual(len(result.gaps), 1)
        self.assertEqual(result.gaps[0].required_output, "AggregateTable")
        self.assertIn("not_document_list", result.gaps[0].missing)

    def test_composer_rejects_foreign_filter_for_concrete_skill_contract(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        composer = SkillComposer(registry)
        goal = GoalDecomposition(
            business_goal="Показать склады с чужим доменным ограничением",
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[
                ArtifactRequirement(
                    name="warehouses",
                    type="WarehouseRefList",
                    constraints=[SemanticFilter(semantic_field="foreign_domain", operator="equals", value="x")],
                ),
            ],
        )

        result = composer.compose(goal)

        self.assertIsNone(result.plan)
        self.assertEqual(len(result.gaps), 1)
        self.assertEqual(result.gaps[0].recommended_resolution.value, "extend_existing_skill")
        self.assertEqual(result.gaps[0].nearest_skill_ids, ["get_warehouses"])
        self.assertIn("filter:foreign_domain", result.gaps[0].missing)

    def test_composer_maps_requirement_constraint_to_matching_skill_input_not_filter(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        composer = SkillComposer(registry)
        goal = GoalDecomposition(
            business_goal="Показать агрегат документов с месячной группировкой",
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[
                ArtifactRequirement(
                    name="document_counts",
                    type="DocumentCountByPeriodTable",
                    constraints=[SemanticFilter(semantic_field="period_granularity", operator="equals", value="month")],
                ),
            ],
        )

        result = composer.compose(goal)

        self.assertEqual(result.gaps, [])
        self.assertIsNotNone(result.plan)
        assert result.plan is not None
        data_node = next(node for node in result.plan.nodes if node.skill_id == "count_transfer_documents_by_day")
        self.assertEqual(data_node.inputs["period_granularity"], "month")
        self.assertNotIn("filters", data_node.inputs)

    def test_composer_rejects_stock_skill_when_goal_domain_is_cash(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        composer = SkillComposer(registry)
        goal = GoalDecomposition(
            business_goal="Показать остаток наличных в кассах",
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[
                ArtifactRequirement(
                    name="warehouses",
                    type="WarehouseRefList",
                    constraints=[
                        SemanticFilter(
                            semantic_field="warehouse_type",
                            operator="equals",
                            value="Касса",
                            raw_user_text="касса",
                        )
                    ],
                ),
                ArtifactRequirement(
                    name="cash_balances",
                    type="StockBalanceTable",
                    constraints=[
                        SemanticFilter(
                            semantic_field="product",
                            operator="equals",
                            value="Наличные",
                            raw_user_text="наличные",
                        ),
                        SemanticFilter(
                            semantic_field="warehouse",
                            operator="in_list",
                            value="from warehouses",
                            raw_user_text="кассы",
                        ),
                    ],
                ),
            ],
        )

        result = composer.compose(goal)

        self.assertIsNone(result.plan)
        self.assertEqual(len(result.gaps), 1)
        self.assertEqual(result.gaps[0].required_output, "StockBalanceTable")
        self.assertIn("domain:StockBalanceTable", result.gaps[0].missing)
        self.assertIn("get_stock_balances", result.gaps[0].nearest_skill_ids)

    def test_composer_does_not_bind_context_placeholder_as_literal_skill_input(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        composer = SkillComposer(registry)
        goal = GoalDecomposition(
            business_goal="Показать склады с наибольшими остатками товаров",
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[
                ArtifactRequirement(
                    name="stock_table",
                    type="StockBalanceTable",
                    constraints=[
                        SemanticFilter(
                            semantic_field="product",
                            operator="equals",
                            value="context_product",
                            raw_user_text="",
                        ),
                        SemanticFilter(
                            semantic_field="warehouse",
                            operator="in_list",
                            value="all_warehouses",
                            raw_user_text="склады",
                        ),
                    ],
                ),
                ArtifactRequirement(name="warehouses", type="WarehouseRefList"),
                ArtifactRequirement(name="product", type="ProductRef", source="dialog_context"),
            ],
        )

        result = composer.compose(goal)

        self.assertEqual(result.gaps, [])
        self.assertIsNotNone(result.plan)
        assert result.plan is not None
        stock_node = next(node for node in result.plan.nodes if node.skill_id == "get_stock_balances")
        self.assertNotEqual(stock_node.inputs["product"], "context_product")
        self.assertTrue(str(stock_node.inputs["product"]).startswith("${"))
        self.assertTrue(str(stock_node.inputs["warehouses"]).startswith("${"))

    def test_composer_does_not_bind_unknown_placeholder_as_literal_skill_input(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        composer = SkillComposer(registry)
        goal = GoalDecomposition(
            business_goal="Показать склады с наибольшими остатками",
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[
                ArtifactRequirement(
                    name="stock_table",
                    type="StockBalanceTable",
                    constraints=[
                        SemanticFilter(
                            semantic_field="product",
                            operator="equals",
                            value="unknown",
                            raw_user_text="",
                        )
                    ],
                ),
                ArtifactRequirement(name="warehouses", type="WarehouseRefList"),
            ],
        )

        result = composer.compose(goal)

        self.assertEqual(result.gaps, [])
        self.assertIsNotNone(result.plan)
        assert result.plan is not None
        stock_node = next(node for node in result.plan.nodes if node.skill_id == "get_stock_balances")
        self.assertNotIn("product", stock_node.inputs)


if __name__ == "__main__":
    unittest.main()

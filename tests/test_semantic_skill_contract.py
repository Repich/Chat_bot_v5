from __future__ import annotations

import unittest

from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.models import ArtifactRequirement, SemanticFilter
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.skills.semantic_contract import (
    SEMANTIC_CONTRACT_SCHEMA_VERSION,
    SemanticMeasure,
    SemanticRanking,
    SemanticSkillContract,
    contract_from_goal,
    semantic_contract_compatibility,
)
from wiicon5.skills.composer import SkillComposer
from wiicon5.skills.registry import SkillRegistry
from wiicon5.models import SkillContract


class SemanticSkillContractTests(unittest.TestCase):
    def test_contract_distinguishes_sum_from_average(self) -> None:
        sum_contract = contract_from_goal(
            data_intent("Получить сумму реализаций за 2024 год"),
            aggregate_goal("Получить сумму реализаций за 2024 год", metric="сумма", column="Сумма"),
        )
        average_contract = SemanticSkillContract(
            subject_terms=["реализация"],
            operation="aggregate",
            measures=[SemanticMeasure(role="стоимость", aggregation="avg", result_column="СредняяСтоимость")],
            required_filter_roles=["year"],
            result_columns=["СредняяСтоимость"],
            original_question="Получить среднюю стоимость реализаций за 2024 год",
        )

        compatibility = semantic_contract_compatibility(sum_contract, average_contract)

        self.assertFalse(compatibility.compatible)
        self.assertIn("aggregation_mismatch", compatibility.rejection_reasons)

    def test_contract_accepts_same_metric_for_another_year(self) -> None:
        requested = contract_from_goal(
            data_intent("Получить сумму реализаций за 2025 год"),
            aggregate_goal("Получить сумму реализаций за 2025 год", metric="сумма", column="Сумма"),
        )
        available = contract_from_goal(
            data_intent("Получить сумму реализаций за 2024 год"),
            aggregate_goal("Получить сумму реализаций за 2024 год", metric="сумма", column="Сумма"),
        )
        available = SemanticSkillContract.from_dict(
            {
                **available.to_dict(),
                "optional_filter_roles": ["year"],
                "required_filter_roles": ["year"],
            }
        )

        compatibility = semantic_contract_compatibility(requested, available)

        self.assertTrue(compatibility.compatible, compatibility.rejection_reasons)
        self.assertIn("aggregation_match", compatibility.reasons)

    def test_contract_rejects_ranked_skill_for_plain_aggregate(self) -> None:
        requested = SemanticSkillContract(
            subject_terms=["продажи", "товар"],
            operation="aggregate",
            measures=[SemanticMeasure(role="выручка", aggregation="sum")],
        )
        ranked = SemanticSkillContract(
            subject_terms=["продажи", "товар"],
            operation="rank",
            measures=[SemanticMeasure(role="выручка", aggregation="sum")],
            ranking=SemanticRanking(enabled=True, direction="desc", limit=1, by_measure="выручка"),
        )

        compatibility = semantic_contract_compatibility(requested, ranked)

        self.assertFalse(compatibility.compatible)
        self.assertIn("operation_mismatch:aggregate!=rank", compatibility.rejection_reasons)

    def test_document_amount_does_not_match_debt_measure(self) -> None:
        requested = SemanticSkillContract(
            subject_terms=["отгрузка", "задолженность"],
            operation="lookup",
            measures=[SemanticMeasure(role="сумма задолженности", unit="currency")],
        )
        available = SemanticSkillContract(
            subject_terms=["отгрузка", "сумма документа"],
            operation="lookup",
            measures=[SemanticMeasure(role="сумма документа", unit="currency")],
        )

        compatibility = semantic_contract_compatibility(requested, available)

        self.assertFalse(compatibility.compatible)
        self.assertIn("measure_mismatch:сумма задолженности", compatibility.rejection_reasons)

    def test_outdated_contract_is_never_compatible(self) -> None:
        requested = SemanticSkillContract(subject_terms=["остатки"], operation="balance")
        outdated = SemanticSkillContract.from_dict(
            {
                "schema_version": SEMANTIC_CONTRACT_SCHEMA_VERSION - 1,
                "subject_terms": ["остатки"],
                "operation": "balance",
            }
        )

        compatibility = semantic_contract_compatibility(requested, outdated)

        self.assertFalse(compatibility.compatible)
        self.assertIn("skill_contract_schema_outdated", compatibility.rejection_reasons)

    def test_subject_terms_exclude_commands_years_and_variable_filter_values(self) -> None:
        goal = GoalDecomposition(
            business_goal="Покажи розничные цены на пальто за 2025 год",
            final_artifact_type="UserAnswer",
            required_artifacts=[
                ArtifactRequirement(
                    name="prices",
                    type="PriceTable",
                    constraints=[
                        SemanticFilter("product", "contains", "пальто", "пальто"),
                        SemanticFilter("price_type", "equals", "розничная", "розничные"),
                        SemanticFilter("year", "equals", "2025", "2025 год"),
                    ],
                )
            ],
        )

        contract = contract_from_goal(data_intent(goal.business_goal), goal)

        self.assertNotIn("покаж", contract.subject_terms)
        self.assertNotIn("2025", contract.subject_terms)
        self.assertNotIn("пальто", contract.subject_terms)
        self.assertNotIn("розничн", contract.subject_terms)

    def test_parameterized_price_contract_matches_another_product(self) -> None:
        available_goal = GoalDecomposition(
            business_goal="Покажи розничные цены на пальто",
            final_artifact_type="UserAnswer",
            required_artifacts=[
                ArtifactRequirement(
                    name="prices",
                    type="PriceTable",
                    constraints=[
                        SemanticFilter("product", "contains", "пальто", "пальто"),
                        SemanticFilter("price_type", "equals", "розничная", "розничные"),
                    ],
                )
            ],
        )
        requested_goal = GoalDecomposition(
            business_goal="Покажи розничные цены на куртки",
            final_artifact_type="UserAnswer",
            required_artifacts=[
                ArtifactRequirement(
                    name="prices",
                    type="PriceTable",
                    constraints=[
                        SemanticFilter("product", "contains", "куртки", "куртки"),
                        SemanticFilter("price_type", "equals", "розничная", "розничные"),
                    ],
                )
            ],
        )
        available = contract_from_goal(data_intent(available_goal.business_goal), available_goal)
        available = SemanticSkillContract.from_dict(
            {
                **available.to_dict(),
                "required_filter_roles": ["product", "price_type"],
                "optional_filter_roles": ["product", "price_type"],
                "fixed_filter_values": {},
            }
        )

        compatibility = semantic_contract_compatibility(
            contract_from_goal(data_intent(requested_goal.business_goal), requested_goal),
            available,
        )

        self.assertTrue(compatibility.compatible, compatibility.rejection_reasons)

    def test_contract_rejects_different_fixed_document_type(self) -> None:
        sales = SemanticSkillContract(
            subject_terms=["реализация"],
            operation="list",
            required_filter_roles=["document_type"],
            fixed_filter_values={"document_type": "Реализация товаров и услуг"},
        )
        purchases = SemanticSkillContract(
            subject_terms=["приобретение"],
            operation="list",
            required_filter_roles=["document_type"],
            fixed_filter_values={"document_type": "Приобретение товаров и услуг"},
        )

        compatibility = semantic_contract_compatibility(purchases, sales)

        self.assertFalse(compatibility.compatible)
        self.assertIn("fixed_filter_mismatch:document_type", compatibility.rejection_reasons)

    def test_fixed_filter_comparison_is_not_substring_based(self) -> None:
        available = SemanticSkillContract(
            subject_terms=["реализация"],
            operation="list",
            required_filter_roles=["document_type"],
            fixed_filter_values={"document_type": "Реализация товаров и услуг"},
        )
        negative_probe = SemanticSkillContract.from_dict(
            {
                **available.to_dict(),
                "fixed_filter_values": {"document_type": "Реализация товаров и услуг другое"},
            }
        )

        compatibility = semantic_contract_compatibility(negative_probe, available)

        self.assertFalse(compatibility.compatible)
        self.assertIn("fixed_filter_mismatch:document_type", compatibility.rejection_reasons)

    def test_fixed_filter_comparison_ignores_case_and_spacing_only(self) -> None:
        available = SemanticSkillContract(
            subject_terms=["реализация"],
            operation="list",
            required_filter_roles=["document_type"],
            fixed_filter_values={"document_type": "Реализация товаров и услуг"},
        )
        requested = SemanticSkillContract.from_dict(
            {
                **available.to_dict(),
                "fixed_filter_values": {"document_type": "  реализация   ТОВАРОВ и услуг "},
            }
        )

        compatibility = semantic_contract_compatibility(requested, available)

        self.assertTrue(compatibility.compatible, compatibility.rejection_reasons)

    def test_explicit_contract_drops_filter_values_from_subject(self) -> None:
        explicit = SemanticSkillContract(
            subject_terms=["остатки", "куртки", "розничный склад"],
            operation="balance",
            required_filter_roles=["product", "warehouse_type"],
        ).to_dict()
        explicit["subject_terms"] = ["остатки", "куртки", "розничный склад"]
        goal = GoalDecomposition(
            business_goal="Покажи остатки курток на розничном складе",
            final_artifact_type="UserAnswer",
            required_artifacts=[
                ArtifactRequirement(
                    name="stock",
                    type="StockTable",
                    constraints=[
                        SemanticFilter("product", "contains", "куртки", "куртки"),
                        SemanticFilter("warehouse_type", "equals", "розничный склад", "розничный склад"),
                    ],
                )
            ],
            semantic_contract=explicit,
        )

        parsed = contract_from_goal(data_intent(goal.business_goal), goal)

        self.assertEqual(parsed.subject_terms, ["остатк"])

    def test_explicit_contract_from_decomposer_is_preserved(self) -> None:
        explicit = SemanticSkillContract(
            subject_terms=["касса"],
            operation="balance",
            measures=[SemanticMeasure(role="остаток", aggregation="sum", unit="currency")],
            required_filter_roles=["organization"],
            result_columns=["Касса", "Остаток"],
            confidence=0.95,
        )
        goal = GoalDecomposition(
            business_goal="Показать остатки наличных",
            final_artifact_type="UserAnswer",
            required_artifacts=[ArtifactRequirement(name="cash", type="CashBalanceTable")],
            semantic_contract=explicit.to_dict(),
        )

        parsed = contract_from_goal(data_intent(goal.business_goal), goal)

        self.assertEqual(parsed, explicit)

    def test_composer_selects_sum_skill_and_rejects_average_with_same_output_type(self) -> None:
        requested_goal = aggregate_goal(
            "Получить сумму реализаций за 2024 год",
            metric="сумма",
            column="Сумма",
        )
        sum_contract = contract_from_goal(data_intent(requested_goal.business_goal), requested_goal)
        average_contract = SemanticSkillContract(
            subject_terms=list(sum_contract.subject_terms),
            operation="aggregate",
            measures=[SemanticMeasure(role="стоимость", aggregation="avg", result_column="СредняяСтоимость")],
            required_filter_roles=["year"],
            optional_filter_roles=["year"],
            result_columns=["СредняяСтоимость"],
            original_question="Получить среднюю стоимость реализаций за 2024 год",
        )
        sum_skill = learned_skill("learned_sum", sum_contract)
        average_skill = learned_skill("learned_average", average_contract)
        renderer = SkillContract.from_dict(
            {
                "skill_id": "render_table_answer",
                "kind": "presentation",
                "status": "stable",
                "description": "Render table",
                "capabilities": ["produce:UserAnswer"],
                "inputs": [{"name": "table", "type": "TypedTable"}],
                "outputs": [{"name": "answer", "type": "UserAnswer"}],
                "implementation_strategy": "deterministic_table_renderer",
            }
        )

        result = SkillComposer(SkillRegistry([average_skill, sum_skill, renderer])).compose(requested_goal)

        self.assertIsNotNone(result.plan)
        assert result.plan is not None
        self.assertEqual(result.plan.nodes[0].skill_id, "learned_sum")
        trace = next(item for item in result.search_trace if item["required_artifact"] == "AggregateTable")
        average_trace = next(item for item in trace["candidates"] if item["skill_id"] == "learned_average")
        self.assertFalse(average_trace["semantic_contract"]["compatible"])
        self.assertIn("aggregation_mismatch", average_trace["semantic_contract"]["rejection_reasons"])


def aggregate_goal(question: str, *, metric: str, column: str) -> GoalDecomposition:
    return GoalDecomposition(
        business_goal=question,
        final_artifact_type="UserAnswer",
        expected_answer_type="table",
        required_artifacts=[
            ArtifactRequirement(
                name="metrics",
                type="AggregateTable",
                constraints=[
                    SemanticFilter(semantic_field="year", operator="equals", value="2024", raw_user_text="2024 год"),
                    SemanticFilter(semantic_field="metric", operator="equals", value=metric, raw_user_text=metric),
                ],
                required_columns=[column],
            )
        ],
    )


def data_intent(question: str) -> IntentResult:
    return IntentResult(
        intent_type=IntentType.DATA_QUESTION,
        business_goal=question,
        requires_1c_data=True,
        expected_output="table",
        domain_terms=["реализации"],
        relevant=True,
    )


def learned_skill(skill_id: str, contract: SemanticSkillContract) -> SkillContract:
    return SkillContract.from_dict(
        {
            "skill_id": skill_id,
            "kind": "data_acquisition",
            "status": "verified",
            "description": skill_id,
            "capabilities": ["learned_query", "produce:AggregateTable"],
            "inputs": [{"name": "filters", "type": "SemanticFilterList", "required": True}],
            "outputs": [{"name": "table", "type": "AggregateTable"}],
            "supported_filter_roles": ["year", "metric", "aggregation"],
            "implementation_strategy": "learned_query",
            "semantic_contract": contract.to_dict(),
            "implementation": {"kind": "semantic_query_template", "schema_version": 2},
        }
    )


if __name__ == "__main__":
    unittest.main()

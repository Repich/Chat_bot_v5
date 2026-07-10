from __future__ import annotations

import unittest

from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.models import ArtifactRequirement
from wiicon5.models import SemanticFilter
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.query.parameterized_lookup import build_parameterized_lookup_params, infer_parameter_bindings
from wiicon5.query_synthesis import QuerySynthesisResult
from wiicon5.skills.learning_gate import evaluate_learning_gate
from wiicon5.skills.query_template_learning import semantic_query_template_spec, skill_from_semantic_template


class SemanticQueryTemplateTests(unittest.TestCase):
    def test_year_filter_binds_both_period_boundaries(self) -> None:
        constraints = [
            SemanticFilter(
                semantic_field="year",
                operator="equals",
                value="2024",
                raw_user_text="2024 год",
            )
        ]
        params = {
            "НачПериода": "2024-01-01T00:00:00",
            "КонПериода": "2024-12-31T23:59:59",
        }

        bindings = infer_parameter_bindings(params, constraints)
        spec = {"params": params, "parameter_bindings": bindings}
        rebound = build_parameterized_lookup_params(
            spec,
            {"filters": [{"semantic_field": "year", "operator": "equals", "value": "2025"}]},
        )

        self.assertEqual(len(bindings), 2)
        self.assertEqual(rebound["НачПериода"], "2025-01-01T00:00:00")
        self.assertEqual(rebound["КонПериода"], "2025-12-31T23:59:59")

    def test_learning_preserves_full_join_filter_grouping_and_order(self) -> None:
        query = (
            "ВЫБРАТЬ ПЕРВЫЕ 10 Продажи.Номенклатура КАК Номенклатура, "
            "СУММА(Продажи.Количество) КАК Количество "
            "ИЗ РегистрНакопления.Продажи КАК Продажи "
            "ЛЕВОЕ СОЕДИНЕНИЕ Справочник.Номенклатура КАК Номенклатура "
            "ПО Продажи.Номенклатура = Номенклатура.Ссылка "
            "ГДЕ Продажи.Период МЕЖДУ &НачПериода И &КонПериода "
            "И Продажи.Активность И НЕ Номенклатура.ПометкаУдаления "
            "СГРУППИРОВАТЬ ПО Продажи.Номенклатура "
            "УПОРЯДОЧИТЬ ПО Количество УБЫВ"
        )
        intent = data_intent("Показать топ 10 товаров по количеству продаж за 2024 год")
        goal = GoalDecomposition(
            business_goal=intent.business_goal,
            final_artifact_type="UserAnswer",
            required_artifacts=[
                ArtifactRequirement(
                    name="top_products",
                    type="TopNMetricTable",
                    constraints=[
                        SemanticFilter("year", "equals", "2024", "2024 год"),
                        SemanticFilter("metric", "equals", "количество", "по количеству"),
                    ],
                    required_columns=["Номенклатура", "Количество"],
                )
            ],
        )

        spec = semantic_query_template_spec(
            query=query,
            params={"НачПериода": "2024-01-01T00:00:00", "КонПериода": "2024-12-31T23:59:59"},
            limit=10,
            intent=intent,
            goal=goal,
            trace={"successful_steps": [{"columns": ["Номенклатура", "Количество"]}]},
        )

        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec["query"], query)
        self.assertIn("ЛЕВОЕ СОЕДИНЕНИЕ", spec["query"])
        self.assertIn("НЕ Номенклатура.ПометкаУдаления", spec["query"])
        self.assertIn("РегистрНакопления.Продажи", spec["metadata_dependencies"])
        self.assertEqual({item["semantic_field"] for item in spec["parameter_bindings"]}, {"year"})
        skill = skill_from_semantic_template(spec, intent=intent, goal=goal)
        self.assertEqual(skill.outputs[0].type, "TopNMetricTable")
        self.assertEqual(skill.implementation["kind"], "semantic_query_template")
        self.assertEqual(skill.semantic_contract["operation"], "rank")

    def test_table_part_is_recorded_as_its_own_metadata_dependency(self) -> None:
        query = (
            "ВЫБРАТЬ Товары.Номенклатура КАК Номенклатура, "
            "Товары.Количество КАК Количество "
            "ИЗ Документ.РеализацияТоваровУслуг.Товары КАК Товары "
            "ВНУТРЕННЕЕ СОЕДИНЕНИЕ Документ.РеализацияТоваровУслуг КАК Реализация "
            "ПО Товары.Ссылка = Реализация.Ссылка"
        )
        intent = data_intent("Показать товары последней реализации")
        goal = GoalDecomposition(
            business_goal=intent.business_goal,
            final_artifact_type="UserAnswer",
            required_artifacts=[ArtifactRequirement(name="items", type="LearnedQueryTable")],
        )
        trace = successful_trace(query, ["Номенклатура", "Количество"], [{"Номенклатура": "Товар", "Количество": 1}])

        spec = semantic_query_template_spec(
            query=query,
            params={},
            limit=100,
            intent=intent,
            goal=goal,
            trace=trace,
        )

        assert spec is not None
        self.assertIn("Документ.РеализацияТоваровУслуг.Товары", spec["metadata_dependencies"])
        table_part = next(
            item
            for item in spec["metadata_dependency_contract"]
            if item["object"] == "Документ.РеализацияТоваровУслуг.Товары"
        )
        self.assertEqual(table_part["parent_object"], "Документ.РеализацияТоваровУслуг")
        self.assertEqual(table_part["table_part"], "Товары")
        self.assertEqual(set(table_part["required_fields"]), {"Номенклатура", "Количество", "Ссылка"})

    def test_learning_gate_requires_sufficient_exact_success_evidence(self) -> None:
        query = "ВЫБРАТЬ СУММА(Продажи.Сумма) КАК Сумма ИЗ РегистрНакопления.Продажи КАК Продажи"
        intent = data_intent("Показать сумму продаж")
        goal = GoalDecomposition(
            business_goal=intent.business_goal,
            final_artifact_type="UserAnswer",
            required_artifacts=[
                ArtifactRequirement(
                    name="sales",
                    type="AggregateTable",
                    constraints=[SemanticFilter("metric", "equals", "сумма", "сумма")],
                    required_columns=["Сумма"],
                )
            ],
        )
        trace = {
            "final_query": {"query": query, "params": {}, "limit": 1},
            "successful_steps": [
                {
                    "query": query,
                    "params": {},
                    "columns": ["Сумма"],
                    "rows": [{"Сумма": 100}],
                    "sufficiency": {"sufficient": True, "error": ""},
                }
            ],
            "attempts": [{"result_sufficiency": {"sufficient": True, "error": ""}}],
        }
        spec = semantic_query_template_spec(
            query=query,
            params={},
            limit=1,
            intent=intent,
            goal=goal,
            trace=trace,
        )
        assert spec is not None

        accepted = evaluate_learning_gate(
            intent=intent,
            goal=goal,
            synthesis_result=QuerySynthesisResult(ok=True, trace=trace),
            spec=spec,
            config_fingerprint="cfg_test",
        )
        missing_evidence = evaluate_learning_gate(
            intent=intent,
            goal=goal,
            synthesis_result=QuerySynthesisResult(
                ok=True,
                trace={"final_query": {"query": query, "params": {}, "limit": 1}},
            ),
            spec=spec,
            config_fingerprint="cfg_test",
        )

        self.assertTrue(accepted.ok, accepted.errors)
        self.assertFalse(missing_evidence.ok)
        self.assertIn("successful_result_sufficient", missing_evidence.errors)
        self.assertIn("exact_success_evidence", missing_evidence.errors)

    def test_unbound_query_parameter_forces_exact_match_mode(self) -> None:
        question = "Покажи выручку за 2025 год"
        intent = data_intent(question)
        goal = GoalDecomposition(
            business_goal=question,
            final_artifact_type="UserAnswer",
            required_artifacts=[ArtifactRequirement(name="metrics", type="AggregateTable")],
        )
        query = (
            "ВЫБРАТЬ СУММА(Продажи.Сумма) КАК Выручка "
            "ИЗ РегистрНакопления.Продажи КАК Продажи "
            "ГДЕ Продажи.Период МЕЖДУ &НачПериода И &КонПериода"
        )
        trace = successful_trace(query, ["Выручка"], [{"Выручка": 100}])

        spec = semantic_query_template_spec(
            query=query,
            params={"НачПериода": "2025-01-01T00:00:00", "КонПериода": "2025-12-31T23:59:59"},
            limit=100,
            intent=intent,
            goal=goal,
            trace=trace,
        )

        assert spec is not None
        self.assertEqual(spec["semantic_contract"]["match_mode"], "exact")

    def test_ranked_query_passes_learning_gate(self) -> None:
        question = "Покажи топ 10 товаров по количеству продаж за 2024 год"
        intent = data_intent(question)
        goal = GoalDecomposition(
            business_goal=question,
            final_artifact_type="UserAnswer",
            required_artifacts=[
                ArtifactRequirement(
                    name="top_products",
                    type="TopNMetricTable",
                    constraints=[SemanticFilter("year", "equals", "2024", "2024 год")],
                    required_columns=["Номенклатура", "Количество"],
                )
            ],
        )
        query = (
            "ВЫБРАТЬ ПЕРВЫЕ 10 Продажи.Номенклатура КАК Номенклатура, "
            "СУММА(Продажи.Количество) КАК Количество "
            "ИЗ РегистрНакопления.Продажи КАК Продажи "
            "СГРУППИРОВАТЬ ПО Продажи.Номенклатура "
            "УПОРЯДОЧИТЬ ПО Количество УБЫВ"
        )
        trace = successful_trace(query, ["Номенклатура", "Количество"], [{"Номенклатура": "Товар", "Количество": 10}])
        spec = semantic_query_template_spec(
            query=query,
            params={},
            limit=10,
            intent=intent,
            goal=goal,
            trace=trace,
        )
        assert spec is not None

        gate = evaluate_learning_gate(
            intent=intent,
            goal=goal,
            synthesis_result=QuerySynthesisResult(ok=True, trace=trace),
            spec=spec,
            config_fingerprint="cfg_test",
        )

        self.assertTrue(gate.ok, gate.errors)


def data_intent(question: str) -> IntentResult:
    return IntentResult(
        intent_type=IntentType.DATA_QUESTION,
        business_goal=question,
        requires_1c_data=True,
        expected_output="table",
        domain_terms=["товары", "продажи"],
        relevant=True,
    )


def successful_trace(query: str, columns: list[str], rows: list[dict]) -> dict:
    sufficiency = {"sufficient": True, "partial": False, "error": ""}
    return {
        "final_query": {"query": query, "params": {}, "limit": 100},
        "final_artifact": {"value": {"columns": columns, "rows": rows}},
        "successful_steps": [
            {
                "query": query,
                "params": {},
                "columns": columns,
                "rows": rows,
                "sufficiency": sufficiency,
            }
        ],
        "attempts": [{"result_sufficiency": sufficiency}],
    }


if __name__ == "__main__":
    unittest.main()

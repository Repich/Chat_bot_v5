from __future__ import annotations

import unittest
from pathlib import Path

from wiicon5.conversation.context import ConversationContext
from wiicon5.execution.artifacts import Artifact
from wiicon5.execution.runtime import SkillPlanExecutor, default_runners
from wiicon5.knowledge.bindings import BindingResolver, InMemoryBindingStore
from wiicon5.mcp.client import McpClient
from wiicon5.mcp.contracts import McpMetadataRequest, McpMetadataResponse, McpQueryRequest, McpQueryResponse
from wiicon5.models import ArtifactRequirement, SemanticFilter
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.query.semantic_query_builder import SemanticQueryBuilder
from wiicon5.skill_runtime.data_skill_runner import DataSkillRunner
from wiicon5.skills.composer import SkillComposer
from wiicon5.skills.registry import SkillRegistry
from wiicon5.testing.bindings import custom_stock_binding, custom_warehouse_binding


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SemanticRuntimeIntegrationTests(unittest.TestCase):
    def test_full_stock_plan_executes_with_binding_driven_queries(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        composer_result = SkillComposer(registry).compose(stock_goal())
        assert composer_result.plan is not None
        context = ConversationContext(session_id="s1", config_fingerprint="cfg_custom")
        context.add_artifact(
            Artifact(
                name="product",
                type="ProductRef",
                value={"ref": "product-ref-1"},
                provenance=["test_context"],
            )
        )
        mcp = QueueMcpClient(
            [
                {
                    "success": True,
                    "data": [{"Ссылка": "warehouse-ref-1", "Наименование": "Оптовый склад"}],
                },
                {
                    "success": True,
                    "data": [{"Склад": "Оптовый склад", "Остаток": 42}],
                },
            ]
        )
        binding_store = InMemoryBindingStore([custom_warehouse_binding(), custom_stock_binding()])
        semantic_data_runner = DataSkillRunner(
            query_builder=SemanticQueryBuilder(BindingResolver(binding_store)),
            mcp_client=mcp,
        )
        runners = default_runners()
        runners["semantic_binding_query"] = semantic_data_runner
        runners["semantic_measure_query"] = semantic_data_runner
        executor = SkillPlanExecutor(registry, runners)

        result = executor.execute(composer_result.plan, context)

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.final_artifact)
        assert result.final_artifact is not None
        self.assertIn("Оптовый склад", result.final_artifact.value)
        self.assertIn("42", result.final_artifact.value)
        self.assertEqual(len(mcp.query_calls), 2)
        self.assertIn("Справочник.МестаХранения", mcp.query_calls[0].query)
        self.assertIn("РегистрНакопления.ОстаткиТоваров.Остатки()", mcp.query_calls[1].query)
        self.assertIn("Остатки.МестоХранения В (&warehouses_1)", mcp.query_calls[1].query)
        self.assertEqual(mcp.query_calls[1].params["warehouses_1"], "warehouse-ref-1")
        self.assertNotIn("ТоварыНаСкладах", mcp.query_calls[1].query)


def stock_goal() -> GoalDecomposition:
    return GoalDecomposition(
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


class QueueMcpClient(McpClient):
    def __init__(self, responses):
        self.responses = list(responses)
        self.query_calls = []

    def execute_query(self, request: McpQueryRequest) -> McpQueryResponse:
        self.query_calls.append(request)
        if not self.responses:
            return McpQueryResponse(success=False, error="No queued MCP response")
        return McpQueryResponse.from_dict(self.responses.pop(0))

    def get_metadata(self, request: McpMetadataRequest) -> McpMetadataResponse:
        return McpMetadataResponse(success=True, data=[])


if __name__ == "__main__":
    unittest.main()

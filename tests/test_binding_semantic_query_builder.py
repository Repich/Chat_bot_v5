from __future__ import annotations

import unittest
from pathlib import Path

from wiicon5.conversation.context import ConversationContext
from typing import Any, Dict, List

from wiicon5.knowledge.bindings import BindingResolver, InMemoryBindingStore, ScriptedBindingDiscoverer
from wiicon5.knowledge.metadata import MetadataProvider, metadata_object_from_payload
from wiicon5.mcp.client import DictMcpClient, McpClient
from wiicon5.mcp.contracts import McpMetadataRequest, McpMetadataResponse, McpQueryRequest, McpQueryResponse
from wiicon5.models import SkillBinding
from wiicon5.query.semantic_query_builder import SemanticQueryBuilder
from wiicon5.skill_runtime.data_skill_runner import DataSkillRunner
from wiicon5.skills.registry import SkillRegistry
from wiicon5.testing.bindings import custom_stock_binding, custom_warehouse_binding


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class BindingSemanticQueryBuilderTests(unittest.TestCase):
    def test_warehouse_query_uses_binding_object_and_fields(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_warehouses")
        assert skill is not None
        store = InMemoryBindingStore([custom_warehouse_binding()])
        builder = SemanticQueryBuilder(BindingResolver(store))
        context = ConversationContext(session_id="s1", config_fingerprint="cfg_custom")

        draft = builder.build(
            skill,
            {
                "filters": [
                    {
                        "semantic_field": "warehouse_type",
                        "operator": "equals",
                        "value": "wholesale",
                    }
                ],
                "limit": 25,
            },
            context,
        )

        self.assertIn("Справочник.МестаХранения КАК Места", draft.query)
        self.assertIn("Места.Название КАК Наименование", draft.query)
        self.assertIn("Места.Категория = &warehouse_type", draft.query)
        self.assertEqual(draft.params["warehouse_type"], "wholesale")
        self.assertIn("ВЫБРАТЬ ПЕРВЫЕ 25", draft.query)
        self.assertNotIn("Справочник.Склады", draft.query)

    def test_data_runner_discovers_binding_and_saves_it_before_query(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_warehouses")
        assert skill is not None
        store = InMemoryBindingStore()
        discoverer = ScriptedBindingDiscoverer({"get_warehouses": custom_warehouse_binding()})
        builder = SemanticQueryBuilder(BindingResolver(store, discoverer))
        mcp = DictMcpClient(
            {
                "success": True,
                "data": [{"Ссылка": "w1", "Наименование": "Оптовый склад"}],
            }
        )
        runner = DataSkillRunner(query_builder=builder, mcp_client=mcp)
        context = ConversationContext(session_id="s1", config_fingerprint="cfg_custom")

        result = runner.run(skill, {"filters": [], "limit": 5}, context)

        self.assertTrue(result.ok)
        self.assertEqual(discoverer.calls, ["get_warehouses"])
        self.assertIsNotNone(store.get("get_warehouses", "cfg_custom"))
        self.assertEqual(len(mcp.query_calls), 1)
        self.assertIn("Справочник.МестаХранения", mcp.query_calls[0].query)
        self.assertEqual(result.artifacts[0].value[0]["Ссылка"], "w1")

    def test_data_runner_returns_controlled_error_when_semantic_filter_has_no_binding_field(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_warehouses")
        assert skill is not None
        incomplete = SkillBinding(
            skill_id="get_warehouses",
            config_fingerprint="cfg_custom",
            semantic_role="warehouse",
            one_c_object={"full_name": "Справочник.МестаХранения", "alias": "Места"},
            fields={"ref": "Ссылка", "name": "Название"},
            confidence=0.9,
        )
        builder = SemanticQueryBuilder(BindingResolver(InMemoryBindingStore([incomplete])))
        mcp = DictMcpClient({"success": True, "data": []})
        runner = DataSkillRunner(query_builder=builder, mcp_client=mcp)

        result = runner.run(
            skill,
            {"filters": [{"semantic_field": "warehouse_type", "operator": "equals", "value": "wholesale"}]},
            ConversationContext(session_id="s1", config_fingerprint="cfg_custom"),
        )

        self.assertFalse(result.ok)
        self.assertEqual(len(mcp.query_calls), 0)
        self.assertIn("warehouse_type", result.error)

    def test_stock_query_uses_measure_binding_not_known_register_names(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_stock_balances")
        assert skill is not None
        store = InMemoryBindingStore([custom_stock_binding()])
        builder = SemanticQueryBuilder(BindingResolver(store))

        draft = builder.build(
            skill,
            {
                "product": {"ref": "product-ref-1"},
                "warehouses": [{"ref": "warehouse-ref-1"}],
                "limit": 10,
            },
            ConversationContext(session_id="s1", config_fingerprint="cfg_custom"),
        )

        self.assertIn("РегистрНакопления.ОстаткиТоваров.Остатки() КАК Остатки", draft.query)
        self.assertIn("Остатки.МестоХранения.Наименование КАК Склад", draft.query)
        self.assertIn("СУММА(Остатки.ДоступноОстаток) КАК Остаток", draft.query)
        self.assertIn("СГРУППИРОВАТЬ ПО", draft.query)
        self.assertIn("Остатки.МестоХранения.Наименование", draft.query)
        self.assertIn("Остатки.Товар = &product", draft.query)
        self.assertIn("Остатки.МестоХранения В (&warehouses_1)", draft.query)
        self.assertEqual(draft.params["product"], "product-ref-1")
        self.assertEqual(draft.params["warehouses_1"], "warehouse-ref-1")
        self.assertNotIn("ТоварыНаСкладах", draft.query)
        self.assertNotIn("Номенклатура", draft.query)

    def test_stock_query_keeps_product_column_when_user_requests_product_detail(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_stock_balances")
        assert skill is not None
        store = InMemoryBindingStore([custom_stock_binding()])
        builder = SemanticQueryBuilder(BindingResolver(store))

        draft = builder.build(
            skill,
            {
                "product": {"ref": "product-ref-1"},
                "required_columns": ["Номенклатура"],
                "limit": 10,
            },
            ConversationContext(session_id="s1", config_fingerprint="cfg_custom"),
        )

        self.assertIn("Остатки.Товар КАК Номенклатура", draft.query)
        self.assertIn("Остатки.Товар = &product", draft.query)
        self.assertNotIn("СУММА(", draft.query)

    def test_stock_query_uses_name_search_when_product_input_is_text(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_stock_balances")
        assert skill is not None
        store = InMemoryBindingStore([custom_stock_binding()])
        builder = SemanticQueryBuilder(BindingResolver(store))

        draft = builder.build(
            skill,
            {
                "product": "курток",
                "required_columns": ["Номенклатура", "Остаток"],
                "limit": 10,
            },
            ConversationContext(session_id="s1", config_fingerprint="cfg_custom"),
        )

        self.assertIn("Остатки.Товар.Наименование ПОДОБНО", draft.query)
        self.assertNotIn("Остатки.Товар = &product", draft.query)
        self.assertEqual(draft.params["product"], "курт")

    def test_entity_query_can_search_by_generic_entity_role(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_warehouses")
        assert skill is not None
        store = InMemoryBindingStore([custom_warehouse_binding()])
        builder = SemanticQueryBuilder(BindingResolver(store))

        draft = builder.build(
            skill,
            {
                "filters": [
                    {
                        "semantic_field": "warehouse",
                        "operator": "contains",
                        "value": "розничный",
                    }
                ],
                "limit": 10,
            },
            ConversationContext(session_id="s1", config_fingerprint="cfg_custom"),
        )

        self.assertIn("Места.Название ПОДОБНО", draft.query)
        self.assertIn("Места.Категория = &warehouse_Категория", draft.query)
        self.assertNotIn("ПРЕДСТАВЛЕНИЕ(Места.Категория)", draft.query)
        self.assertEqual(draft.params["warehouse_Название"], "розничный")
        self.assertEqual(draft.params["warehouse_Категория"], "розничный")

    def test_data_runner_resolves_generic_reference_filter_before_mcp_query(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_warehouses")
        assert skill is not None
        store = InMemoryBindingStore([custom_warehouse_binding()])
        builder = SemanticQueryBuilder(BindingResolver(store))
        mcp = SequentialMcpClient(
            [
                {
                    "success": True,
                    "data": [
                        {
                            "Значение": {
                                "_objectRef": True,
                                "УникальныйИдентификатор": "retail",
                                "ТипОбъекта": "ПеречислениеСсылка.ТипыСкладов",
                                "Представление": "Розничный магазин",
                            },
                            "Представление": "Розничный магазин",
                        }
                    ],
                },
                {
                    "success": True,
                    "data": [{"Ссылка": "w-retail", "Наименование": "Торговый зал"}],
                },
            ]
        )
        runner = DataSkillRunner(
            query_builder=builder,
            mcp_client=mcp,
            metadata_provider=SingleObjectMetadataProvider(
                {
                    "ПолноеИмя": "Справочник.МестаХранения",
                    "Синоним": "Места хранения",
                    "Реквизиты": [
                        {"Имя": "Ссылка", "Тип": "СправочникСсылка.МестаХранения"},
                        {"Имя": "Название", "Тип": "Строка(100)"},
                        {"Имя": "Категория", "Тип": "ПеречислениеСсылка.ТипыСкладов"},
                    ],
                }
            ),
        )

        result = runner.run(
            skill,
            {
                "filters": [
                    {
                        "semantic_field": "warehouse",
                        "operator": "contains",
                        "value": "розничный склад",
                    }
                ],
                "limit": 10,
            },
            ConversationContext(session_id="s1", config_fingerprint="cfg_custom"),
        )

        self.assertTrue(result.ok)
        self.assertEqual(len(mcp.query_calls), 2)
        final_call = mcp.query_calls[1]
        self.assertNotIn("ПРЕДСТАВЛЕНИЕ(Места.Категория) ПОДОБНО", final_call.query)
        self.assertIn("Места.Категория = &warehouse_Категория", final_call.query)
        self.assertEqual(final_call.params["warehouse_Категория"]["УникальныйИдентификатор"], "retail")
        self.assertEqual(result.artifacts[0].value[0]["Наименование"], "Торговый зал")

    def test_generic_entity_equals_uses_text_search_not_strict_reference_comparison(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_warehouses")
        assert skill is not None
        store = InMemoryBindingStore([custom_warehouse_binding()])
        builder = SemanticQueryBuilder(BindingResolver(store))

        draft = builder.build(
            skill,
            {
                "filters": [
                    {
                        "semantic_field": "warehouse",
                        "operator": "equals",
                        "value": "розничный склад",
                    }
                ],
                "limit": 10,
            },
            ConversationContext(session_id="s1", config_fingerprint="cfg_custom"),
        )

        self.assertIn("Места.Название ПОДОБНО", draft.query)
        self.assertIn("Места.Категория = &warehouse_Категория", draft.query)
        self.assertNotIn("ПРЕДСТАВЛЕНИЕ(Места.Категория)", draft.query)
        self.assertEqual(draft.params["warehouse_Название"], "розничный")
        self.assertEqual(draft.params["warehouse_Категория"], "розничный")

    def test_stock_query_without_product_returns_product_column_instead_of_requiring_context(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_stock_balances")
        assert skill is not None
        store = InMemoryBindingStore([custom_stock_binding()])
        builder = SemanticQueryBuilder(BindingResolver(store))

        draft = builder.build(
            skill,
            {
                "warehouses": [{"ref": "warehouse-ref-1"}],
                "limit": 10,
            },
            ConversationContext(session_id="s1", config_fingerprint="cfg_custom"),
        )

        self.assertIn("Остатки.Товар КАК Номенклатура", draft.query)
        self.assertIn("Остатки.МестоХранения.Наименование КАК Склад", draft.query)
        self.assertIn("Остатки.ДоступноОстаток КАК Остаток", draft.query)
        self.assertNotIn("Остатки.Товар = &product", draft.query)
        self.assertIn("Остатки.МестоХранения В (&warehouses_1)", draft.query)
        self.assertEqual(draft.metadata_dependencies, ["РегистрНакопления.ОстаткиТоваров"])

    def test_document_count_query_uses_binding_document_and_fields(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("count_transfer_documents_by_day")
        assert skill is not None
        binding = SkillBinding(
            skill_id="count_transfer_documents_by_day",
            config_fingerprint="cfg_custom",
            semantic_role="transfer_document_count",
            one_c_object={"full_name": "Документ.ДвижениеТоваров", "alias": "Движения"},
            fields={"ref": "Ссылка", "date": "Дата"},
            confidence=0.9,
        )
        builder = SemanticQueryBuilder(BindingResolver(InMemoryBindingStore([binding])))

        draft = builder.build(
            skill,
            {"period_granularity": "day", "limit": 50},
            ConversationContext(session_id="s1", config_fingerprint="cfg_custom"),
        )

        self.assertIn("Документ.ДвижениеТоваров КАК Движения", draft.query)
        self.assertIn("НАЧАЛОПЕРИОДА(Движения.Дата, ДЕНЬ) КАК День", draft.query)
        self.assertIn("КОЛИЧЕСТВО(Движения.Ссылка) КАК Количество", draft.query)
        self.assertIn("СГРУППИРОВАТЬ ПО", draft.query)
        self.assertIn("УПОРЯДОЧИТЬ ПО", draft.query)
        self.assertNotIn("Документ.ПеремещениеТоваров", draft.query)

class SingleObjectMetadataProvider(MetadataProvider):
    def __init__(self, payload: Dict[str, Any]) -> None:
        self.object = metadata_object_from_payload(payload)

    def search_objects(self, term: str):
        return [self.object]

    def get_object(self, full_name: str):
        return self.object


class SequentialMcpClient(McpClient):
    def __init__(self, query_responses: List[Dict[str, object]]) -> None:
        self.query_responses = list(query_responses)
        self.query_calls: List[McpQueryRequest] = []

    def execute_query(self, request: McpQueryRequest) -> McpQueryResponse:
        self.query_calls.append(request)
        if not self.query_responses:
            return McpQueryResponse(success=False, error="No scripted MCP query response.")
        return McpQueryResponse.from_dict(self.query_responses.pop(0))

    def get_metadata(self, request: McpMetadataRequest) -> McpMetadataResponse:
        return McpMetadataResponse(success=False, error="Metadata is not scripted for this test.")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path

from wiicon5.conversation.context import ConversationContext
from wiicon5.knowledge.bindings import BindingResolver, InMemoryBindingStore, ScriptedBindingDiscoverer
from wiicon5.mcp.client import DictMcpClient
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
        self.assertIn("Остатки.ДоступноОстаток КАК Остаток", draft.query)
        self.assertIn("Остатки.Товар = &product", draft.query)
        self.assertIn("Остатки.МестоХранения В (&warehouses_1)", draft.query)
        self.assertEqual(draft.params["product"], "product-ref-1")
        self.assertEqual(draft.params["warehouses_1"], "warehouse-ref-1")
        self.assertNotIn("ТоварыНаСкладах", draft.query)
        self.assertNotIn("Номенклатура", draft.query)

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

if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, Dict

from wiicon5.conversation.context import ConversationContext
from wiicon5.knowledge.metadata import MetadataProvider, metadata_object_from_payload
from wiicon5.mcp.client import DictMcpClient
from wiicon5.models import SkillContract
from wiicon5.query.query_builder import QueryBuilder
from wiicon5.query.query_draft import QueryDraft
from wiicon5.skill_runtime.data_skill_runner import DataSkillRunner
from wiicon5.skills.registry import SkillRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DataSkillRunnerTests(unittest.TestCase):
    def test_data_runner_validates_and_executes_query_through_mcp(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_warehouses")
        assert skill is not None
        mcp = DictMcpClient(
            {
                "success": True,
                "data": [{"Ссылка": "wh-1", "Наименование": "Оптовый склад"}],
                "schema": {"columns": ["Ссылка", "Наименование"]},
            }
        )
        runner = DataSkillRunner(
            query_builder=StaticQueryBuilder(
                QueryDraft(
                    query=(
                        "ВЫБРАТЬ\n"
                        "    Склады.Ссылка КАК Ссылка,\n"
                        "    Склады.Наименование КАК Наименование\n"
                        "ИЗ\n"
                        "    Справочник.Склады КАК Склады"
                    ),
                    metadata_dependencies=["Справочник.Склады"],
                )
            ),
            mcp_client=mcp,
        )

        result = runner.run(skill, {"filters": []}, ConversationContext(session_id="s1"))

        self.assertTrue(result.ok)
        self.assertEqual(len(mcp.query_calls), 1)
        self.assertEqual(result.artifacts[0].type, "WarehouseRefList")
        self.assertEqual(result.artifacts[0].value[0]["Ссылка"], "wh-1")
        self.assertEqual(result.trace["row_count"], 1)

    def test_data_runner_rejects_unsafe_query_before_mcp(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_warehouses")
        assert skill is not None
        mcp = DictMcpClient({"success": True, "data": []})
        runner = DataSkillRunner(
            query_builder=StaticQueryBuilder(QueryDraft(query="УДАЛИТЬ ИЗ Справочник.Склады")),
            mcp_client=mcp,
        )

        result = runner.run(skill, {}, ConversationContext(session_id="s1"))

        self.assertFalse(result.ok)
        self.assertEqual(len(mcp.query_calls), 0)
        self.assertEqual(result.error, "Query safety validation failed.")
        self.assertFalse(result.trace["validation"]["ok"])

    def test_data_runner_returns_table_artifact_for_table_output(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_stock_balances")
        assert skill is not None
        mcp = DictMcpClient(
            {
                "success": True,
                "result": [{"Склад": "Оптовый склад", "Остаток": 42}],
            }
        )
        runner = DataSkillRunner(
            query_builder=StaticQueryBuilder(
                QueryDraft(
                    query=(
                        "ВЫБРАТЬ\n"
                        "    Остатки.Склад КАК Склад,\n"
                        "    Остатки.КоличествоОстаток КАК Остаток\n"
                        "ИЗ\n"
                        "    РегистрНакопления.ТоварыНаСкладах.Остатки() КАК Остатки"
                    )
                )
            ),
            mcp_client=mcp,
        )

        result = runner.run(skill, {"product": {"ref": "p1"}, "warehouses": [{"ref": "w1"}]}, ConversationContext(session_id="s1"))

        self.assertTrue(result.ok)
        self.assertEqual(result.artifacts[0].type, "StockBalanceTable")
        self.assertEqual(result.artifacts[0].value["columns"], ["Склад", "Остаток"])
        self.assertEqual(result.artifacts[0].value["rows"][0]["Остаток"], 42)

    def test_data_runner_keeps_schema_columns_for_empty_table_output(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_stock_balances")
        assert skill is not None
        mcp = DictMcpClient(
            {
                "success": True,
                "data": [],
                "schema": {
                    "columns": [
                        {"name": "Номенклатура", "types": ["СправочникСсылка.Номенклатура"]},
                        {"name": "Остаток", "types": ["Число"]},
                    ]
                },
            }
        )
        runner = DataSkillRunner(
            query_builder=StaticQueryBuilder(
                QueryDraft(
                    query=(
                        "ВЫБРАТЬ\n"
                        "    Остатки.Номенклатура КАК Номенклатура,\n"
                        "    Остатки.ВНаличииОстаток КАК Остаток\n"
                        "ИЗ\n"
                        "    РегистрНакопления.ТоварыНаСкладах.Остатки() КАК Остатки"
                    )
                )
            ),
            mcp_client=mcp,
        )

        result = runner.run(skill, {"product": "курток"}, ConversationContext(session_id="s1"))

        self.assertTrue(result.ok)
        self.assertEqual(result.artifacts[0].value["columns"], ["Номенклатура", "Остаток"])
        self.assertEqual(result.artifacts[0].value["rows"], [])

    def test_data_runner_expands_list_param_before_mcp(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_stock_balances")
        assert skill is not None
        mcp = DictMcpClient({"success": True, "data": [{"Склад": "Ларек", "Остаток": 15}]})
        runner = DataSkillRunner(
            query_builder=StaticQueryBuilder(
                QueryDraft(
                    query=(
                        "ВЫБРАТЬ\n"
                        "    Остатки.Склад КАК Склад,\n"
                        "    Остатки.ВНаличииОстаток КАК Остаток\n"
                        "ИЗ\n"
                        "    РегистрНакопления.ТоварыНаСкладах.Остатки() КАК Остатки\n"
                        "ГДЕ\n"
                        "    Остатки.Склад В (&Склады)"
                    ),
                    params={"Склады": [{"_objectRef": True, "Представление": "Ларек"}]},
                )
            ),
            mcp_client=mcp,
        )

        result = runner.run(skill, {}, ConversationContext(session_id="s1"))

        self.assertTrue(result.ok)
        self.assertEqual(len(mcp.query_calls), 1)
        self.assertIn("Остатки.Склад В (&Склады_1)", mcp.query_calls[0].query)
        self.assertNotIn("Склады", mcp.query_calls[0].params)
        self.assertEqual(mcp.query_calls[0].params["Склады_1"]["Представление"], "Ларек")
        self.assertTrue(result.trace["list_param_expansion"]["changed"])

    def test_data_runner_rejects_learned_skill_when_metadata_contract_changed(self) -> None:
        skill = SkillContract.from_dict(
            {
                "skill_id": "learned_test",
                "kind": "data_acquisition",
                "status": "candidate",
                "outputs": [{"name": "table", "type": "LearnedMetricsTable"}],
                "implementation_strategy": "learned_query",
                "implementation": {
                    "metadata_dependency_contract": [
                        {
                            "object": "РегистрНакопления.Тест",
                            "required_fields": {"Период": "unknown", "Сумма": "unknown"},
                        }
                    ]
                },
            }
        )
        mcp = DictMcpClient({"success": True, "data": []})
        runner = DataSkillRunner(
            query_builder=StaticQueryBuilder(
                QueryDraft(
                    query="ВЫБРАТЬ 1 КАК Значение",
                    metadata_dependencies=["РегистрНакопления.Тест"],
                )
            ),
            mcp_client=mcp,
            metadata_provider=SingleObjectMetadataProvider(
                {
                    "ПолноеИмя": "РегистрНакопления.Тест",
                    "Измерения": [{"Имя": "Период"}],
                }
            ),
        )

        result = runner.run(skill, {}, ConversationContext(session_id="s1"))

        self.assertFalse(result.ok)
        self.assertIn("metadata dependency changed", result.error)
        self.assertEqual(len(mcp.query_calls), 0)

    def test_learned_table_part_fields_are_validated_against_table_part_metadata(self) -> None:
        skill = learned_skill_with_dependency(
            {
                "object": "Документ.РеализацияТоваровУслуг.Товары",
                "parent_object": "Документ.РеализацияТоваровУслуг",
                "source": "Документ.РеализацияТоваровУслуг.Товары",
                "object_type": "Документ",
                "table_part": "Товары",
                "required_fields": {"Ссылка": "unknown", "Номенклатура": "unknown", "Количество": "unknown"},
            }
        )
        query = (
            "ВЫБРАТЬ Товары.Номенклатура КАК Номенклатура, Товары.Количество КАК Количество "
            "ИЗ Документ.РеализацияТоваровУслуг.Товары КАК Товары"
        )
        mcp = DictMcpClient({"success": True, "data": [{"Номенклатура": "Товар", "Количество": 1}]})
        provider = MappingMetadataProvider(
            {
                "Документ.РеализацияТоваровУслуг.Товары": {
                    "ПолноеИмя": "Документ.РеализацияТоваровУслуг.Товары",
                    "Реквизиты": [
                        {"Имя": "Номенклатура", "Тип": "СправочникСсылка.Номенклатура"},
                        {"Имя": "Количество", "Тип": "Число"},
                    ],
                    "СтандартныеРеквизиты": [{"Имя": "Ссылка", "Тип": "ДокументСсылка.РеализацияТоваровУслуг"}],
                }
            }
        )
        runner = DataSkillRunner(
            query_builder=StaticQueryBuilder(
                QueryDraft(
                    query=query,
                    metadata_dependencies=["Документ.РеализацияТоваровУслуг.Товары"],
                )
            ),
            mcp_client=mcp,
            metadata_provider=provider,
        )

        result = runner.run(skill, {}, ConversationContext(session_id="s1"))

        self.assertTrue(result.ok, result.error)
        self.assertEqual(len(mcp.query_calls), 1)

    def test_learned_virtual_table_fields_are_derived_from_dimensions_and_resources(self) -> None:
        skill = learned_skill_with_dependency(
            {
                "object": "РегистрНакопления.ТоварыНаСкладах",
                "parent_object": "РегистрНакопления.ТоварыНаСкладах",
                "source": "РегистрНакопления.ТоварыНаСкладах.Остатки()",
                "object_type": "РегистрНакопления",
                "virtual_table": "Остатки",
                "required_fields": {"Номенклатура": "unknown", "КоличествоОстаток": "unknown"},
            }
        )
        query = (
            "ВЫБРАТЬ Остатки.Номенклатура КАК Номенклатура, Остатки.КоличествоОстаток КАК Остаток "
            "ИЗ РегистрНакопления.ТоварыНаСкладах.Остатки() КАК Остатки"
        )
        mcp = DictMcpClient({"success": True, "data": [{"Номенклатура": "Товар", "Остаток": 1}]})
        provider = MappingMetadataProvider(
            {
                "РегистрНакопления.ТоварыНаСкладах": {
                    "ПолноеИмя": "РегистрНакопления.ТоварыНаСкладах",
                    "Измерения": [{"Имя": "Номенклатура"}],
                    "Ресурсы": [{"Имя": "Количество"}],
                }
            }
        )
        runner = DataSkillRunner(
            query_builder=StaticQueryBuilder(
                QueryDraft(query=query, metadata_dependencies=["РегистрНакопления.ТоварыНаСкладах"])
            ),
            mcp_client=mcp,
            metadata_provider=provider,
        )

        result = runner.run(skill, {}, ConversationContext(session_id="s1"))

        self.assertTrue(result.ok, result.error)
        self.assertEqual(len(mcp.query_calls), 1)


class StaticQueryBuilder(QueryBuilder):
    def __init__(self, draft: QueryDraft) -> None:
        self.draft = draft
        self.calls = []

    def build(self, skill: SkillContract, inputs: Dict[str, Any], context: ConversationContext) -> QueryDraft:
        self.calls.append({"skill_id": skill.skill_id, "inputs": inputs})
        return self.draft


class SingleObjectMetadataProvider(MetadataProvider):
    def __init__(self, payload: Dict[str, Any]) -> None:
        self.object = metadata_object_from_payload(payload)

    def search_objects(self, term: str):
        return [self.object]

    def get_object(self, full_name: str):
        return self.object


class MappingMetadataProvider(MetadataProvider):
    def __init__(self, payloads: Dict[str, Dict[str, Any]]) -> None:
        self.objects = {key: metadata_object_from_payload(value) for key, value in payloads.items()}

    def search_objects(self, term: str):
        return list(self.objects.values())

    def get_object(self, full_name: str):
        return self.objects.get(full_name, metadata_object_from_payload({"ПолноеИмя": full_name}))


def learned_skill_with_dependency(dependency: Dict[str, Any]) -> SkillContract:
    return SkillContract.from_dict(
        {
            "skill_id": "learned_dependency_test",
            "kind": "data_acquisition",
            "status": "verified",
            "outputs": [{"name": "table", "type": "LearnedQueryTable"}],
            "implementation_strategy": "learned_query",
            "implementation": {"metadata_dependency_contract": [dependency]},
        }
    )


if __name__ == "__main__":
    unittest.main()

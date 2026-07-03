from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, Dict

from wiicon5.conversation.context import ConversationContext
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


class StaticQueryBuilder(QueryBuilder):
    def __init__(self, draft: QueryDraft) -> None:
        self.draft = draft
        self.calls = []

    def build(self, skill: SkillContract, inputs: Dict[str, Any], context: ConversationContext) -> QueryDraft:
        self.calls.append({"skill_id": skill.skill_id, "inputs": inputs})
        return self.draft


if __name__ == "__main__":
    unittest.main()


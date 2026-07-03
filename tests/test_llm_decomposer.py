from __future__ import annotations

import unittest
from pathlib import Path

from wiicon5.agent.orchestrator import AgentOrchestrator
from wiicon5.conversation.context import ConversationContext
from wiicon5.intent.llm_decomposer import LLMGoalDecomposer, available_artifact_types, skill_catalog
from wiicon5.intent.models import IntentType
from wiicon5.llm.client import LLMProviderError, ScriptedLLMClient, extract_json_object
from wiicon5.skills.registry import SkillRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LLMDecomposerTests(unittest.TestCase):
    def test_llm_decomposer_parses_stock_goal_without_query_or_metadata(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        llm = ScriptedLLMClient([stock_decomposition_response()])
        decomposer = LLMGoalDecomposer(llm_client=llm, registry=registry)

        result = decomposer.decompose("Покажи остатки товара на оптовых складах", ConversationContext(session_id="s1"))

        self.assertEqual(result.intent.intent_type, IntentType.DATA_QUESTION)
        self.assertIsNotNone(result.goal)
        assert result.goal is not None
        self.assertEqual(result.goal.final_artifact_type, "UserAnswer")
        warehouse = next(item for item in result.goal.required_artifacts if item.type == "WarehouseRefList")
        self.assertEqual(warehouse.constraints[0].semantic_field, "warehouse_type")
        self.assertEqual(warehouse.constraints[0].value, "wholesale")
        self.assertEqual(len(llm.calls), 1)
        self.assertIn("Не пиши запросы 1С", llm.calls[0]["system_prompt"])
        self.assertIn("available_skills", llm.calls[0]["user_payload"])

    def test_orchestrator_can_use_llm_decomposer_to_build_skill_plan(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        decomposer = LLMGoalDecomposer(llm_client=ScriptedLLMClient([stock_decomposition_response()]), registry=registry)
        orchestrator = AgentOrchestrator(registry=registry, decomposer=decomposer)

        result = orchestrator.handle("Покажи остатки товара на оптовых складах", session_id="s1")

        self.assertEqual(result.source, "skill_plan_ready")
        self.assertIsNotNone(result.plan)
        assert result.plan is not None
        self.assertEqual([node.skill_id for node in result.plan.nodes][1], "get_warehouses")

    def test_llm_decomposer_returns_out_of_scope_without_goal(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        decomposer = LLMGoalDecomposer(
            llm_client=ScriptedLLMClient(
                [
                    {
                        "intent": {
                            "intent_type": "out_of_scope",
                            "business_goal": "Узнать погоду",
                            "requires_1c_data": False,
                            "relevant": False,
                        },
                        "goal": None,
                    }
                ]
            ),
            registry=registry,
        )

        result = decomposer.decompose("Какая сегодня погода?", ConversationContext(session_id="s1"))

        self.assertEqual(result.intent.intent_type, IntentType.OUT_OF_SCOPE)
        self.assertIsNone(result.goal)

    def test_llm_decomposer_handles_provider_error_as_unknown_intent(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        decomposer = LLMGoalDecomposer(llm_client=FailingLLMClient(), registry=registry)

        result = decomposer.decompose("Покажи остатки", ConversationContext(session_id="s1"))

        self.assertEqual(result.intent.intent_type, IntentType.UNKNOWN)
        self.assertFalse(result.intent.relevant)
        self.assertIn("LLM unavailable", result.intent.reasoning)

    def test_llm_decomposer_completes_missing_data_artifact_from_skill_catalog(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        decomposer = LLMGoalDecomposer(
            llm_client=ScriptedLLMClient([stock_decomposition_without_stock_table_response()]),
            registry=registry,
        )

        result = decomposer.decompose("Покажи остатки товара", ConversationContext(session_id="s1"))

        self.assertIsNotNone(result.goal)
        assert result.goal is not None
        self.assertIn("StockBalanceTable", [item.type for item in result.goal.required_artifacts])

    def test_llm_decomposer_completes_transfer_count_artifact_from_skill_catalog(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        decomposer = LLMGoalDecomposer(
            llm_client=ScriptedLLMClient([transfer_count_response_without_data_artifact()]),
            registry=registry,
        )

        result = decomposer.decompose("Покажи количество перемещений по дням", ConversationContext(session_id="s1"))

        self.assertIsNotNone(result.goal)
        assert result.goal is not None
        self.assertIn("DocumentCountByPeriodTable", [item.type for item in result.goal.required_artifacts])

    def test_llm_catalog_exposes_concrete_goal_artifacts_not_technical_base_types(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")

        artifact_types = available_artifact_types(registry)
        catalog = skill_catalog(registry)

        self.assertIn("AggregateTable", artifact_types)
        self.assertIn("WarehouseRefList", artifact_types)
        self.assertIn("DocumentListTable", artifact_types)
        self.assertIn("DocumentRefList", artifact_types)
        self.assertNotIn("EntityRefList", artifact_types)
        self.assertNotIn("TypedTable", artifact_types)
        self.assertNotIn("SemanticFilterList", artifact_types)
        self.assertNotIn("Integer", artifact_types)
        self.assertNotIn("render_table_answer", [item["skill_id"] for item in catalog])
        self.assertNotIn("render_entity_list_answer", [item["skill_id"] for item in catalog])

    def test_llm_decomposer_preserves_unresolved_concrete_artifact_instead_of_adding_nearest_skill(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        decomposer = LLMGoalDecomposer(
            llm_client=ScriptedLLMClient([missing_document_table_response()]),
            registry=registry,
        )

        result = decomposer.decompose("Показать табличный список документов заданного вида", ConversationContext(session_id="s1"))

        self.assertIsNotNone(result.goal)
        assert result.goal is not None
        requirement_types = [item.type for item in result.goal.required_artifacts]
        self.assertIn("DocumentListTable", requirement_types)
        self.assertNotIn("DocumentCountByPeriodTable", requirement_types)
        self.assertNotIn("StockBalanceTable", requirement_types)

    def test_llm_decomposer_preserves_abstract_artifact_for_deterministic_gap(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        decomposer = LLMGoalDecomposer(
            llm_client=ScriptedLLMClient([abstract_entity_list_response()]),
            registry=registry,
        )

        result = decomposer.decompose("Показать список объектов неизвестного бизнес-домена", ConversationContext(session_id="s1"))

        self.assertIsNotNone(result.goal)
        assert result.goal is not None
        self.assertEqual([item.type for item in result.goal.required_artifacts], ["EntityRefList"])

    def test_llm_decomposer_repairs_document_list_used_for_aggregate_question(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        decomposer = LLMGoalDecomposer(
            llm_client=ScriptedLLMClient([selling_nomenclature_as_document_list_response()]),
            registry=registry,
        )

        result = decomposer.decompose("Покажи самую продающуюся номенклатуру", ConversationContext(session_id="s1"))

        self.assertIsNotNone(result.goal)
        assert result.goal is not None
        requirement_types = [item.type for item in result.goal.required_artifacts]
        self.assertIn("AggregateTable", requirement_types)
        self.assertNotIn("DocumentListTable", requirement_types)
        self.assertNotIn("StockBalanceTable", requirement_types)

    def test_extract_json_object_handles_text_wrapped_json(self) -> None:
        parsed = extract_json_object('```json\n{"ok": true}\n```')

        self.assertEqual(parsed, {"ok": True})


class FailingLLMClient(ScriptedLLMClient):
    def __init__(self) -> None:
        super().__init__([])

    def complete_json(self, *, system_prompt, user_payload):  # type: ignore[no-untyped-def]
        raise LLMProviderError("HTTP 503")


def stock_decomposition_response():
    return {
        "intent": {
            "intent_type": "data_question",
            "business_goal": "Показать остатки ранее найденного товара на оптовых складах",
            "requires_1c_data": True,
            "expected_output": "table",
            "domain_terms": ["остатки", "товар", "оптовые склады"],
            "context_dependencies": [
                {
                    "role": "product",
                    "artifact_type": "ProductRef",
                    "source": "dialog_context",
                    "required": True,
                }
            ],
            "relevant": True,
        },
        "goal": {
            "business_goal": "Показать остатки ранее найденного товара на оптовых складах",
            "final_artifact_type": "UserAnswer",
            "expected_answer_type": "table",
            "required_artifacts": [
                {"name": "product", "type": "ProductRef", "source": "dialog_context", "required": True},
                {
                    "name": "warehouses",
                    "type": "WarehouseRefList",
                    "source": "skill",
                    "required": True,
                    "constraints": [
                        {
                            "semantic_field": "warehouse_type",
                            "operator": "equals",
                            "value": "wholesale",
                            "raw_user_text": "оптовые",
                        }
                    ],
                },
                {"name": "stock_table", "type": "StockBalanceTable", "source": "skill", "required": True},
            ],
        },
    }


def stock_decomposition_without_stock_table_response():
    return {
        "intent": {
            "intent_type": "data_question",
            "business_goal": "Показать остатки товара",
            "requires_1c_data": True,
            "expected_output": "table",
            "domain_terms": ["остатки", "товар"],
            "context_dependencies": [
                {
                    "role": "product",
                    "artifact_type": "ProductRef",
                    "source": "dialog_context",
                    "required": True,
                }
            ],
            "relevant": True,
        },
        "goal": {
            "business_goal": "Показать остатки товара",
            "final_artifact_type": "UserAnswer",
            "expected_answer_type": "table",
            "required_artifacts": [
                {"name": "product", "type": "ProductRef", "source": "dialog_context", "required": True},
            ],
        },
    }


def transfer_count_response_without_data_artifact():
    return {
        "intent": {
            "intent_type": "data_question",
            "business_goal": "Показать количество перемещений по дням",
            "requires_1c_data": True,
            "expected_output": "table",
            "domain_terms": ["количество", "перемещения", "по дням"],
            "context_dependencies": [],
            "relevant": True,
        },
        "goal": {
            "business_goal": "Показать количество перемещений по дням",
            "final_artifact_type": "UserAnswer",
            "expected_answer_type": "table",
            "required_artifacts": [
                {"name": "answer", "type": "UserAnswer", "source": "skill", "required": True},
            ],
        },
    }


def missing_document_table_response():
    return {
        "intent": {
            "intent_type": "data_question",
            "business_goal": "Показать табличный список документов заданного вида",
            "requires_1c_data": True,
            "expected_output": "table",
            "domain_terms": ["документы", "список"],
            "context_dependencies": [],
            "relevant": True,
        },
        "goal": {
            "business_goal": "Показать табличный список документов заданного вида",
            "final_artifact_type": "UserAnswer",
            "expected_answer_type": "table",
            "required_artifacts": [
                {"name": "document_rows", "type": "DocumentListTable", "source": "skill", "required": True},
            ],
        },
    }


def abstract_entity_list_response():
    return {
        "intent": {
            "intent_type": "data_question",
            "business_goal": "Показать список объектов неизвестного бизнес-домена",
            "requires_1c_data": True,
            "expected_output": "table",
            "domain_terms": ["объекты", "список"],
            "context_dependencies": [],
            "relevant": True,
        },
        "goal": {
            "business_goal": "Показать список объектов неизвестного бизнес-домена",
            "final_artifact_type": "UserAnswer",
            "expected_answer_type": "table",
            "required_artifacts": [
                {"name": "items", "type": "EntityRefList", "source": "skill", "required": True},
            ],
        },
    }


def selling_nomenclature_as_document_list_response():
    return {
        "intent": {
            "intent_type": "data_question",
            "business_goal": "Получить список самой продающейся номенклатуры",
            "requires_1c_data": True,
            "expected_output": "table",
            "domain_terms": ["номенклатура", "продажи", "самая продающаяся"],
            "context_dependencies": [],
            "relevant": True,
            "reasoning": "Нужно агрегировать продажи по номенклатуре.",
        },
        "goal": {
            "business_goal": "Получить список номенклатуры, отсортированный по объему продаж",
            "final_artifact_type": "UserAnswer",
            "expected_answer_type": "table",
            "required_artifacts": [
                {
                    "name": "documents",
                    "type": "DocumentListTable",
                    "source": "skill",
                    "required": True,
                    "constraints": [
                        {
                            "semantic_field": "document_type",
                            "operator": "equals",
                            "value": "РеализацияТоваровУслуг",
                            "raw_user_text": "продажи",
                        }
                    ],
                },
            ],
        },
    }


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List

from wiicon5.agent.orchestrator import AgentOrchestrator
from wiicon5.conversation.context import ConversationContext
from wiicon5.execution.runtime import SkillPlanExecutor, default_runners
from wiicon5.intent.decomposer import DecompositionResult
from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.knowledge.metadata import MetadataObject, MetadataProvider, metadata_object_from_payload
from wiicon5.llm.client import ScriptedLLMClient
from wiicon5.mcp.client import DictMcpClient
from wiicon5.models import ArtifactRequirement, SemanticFilter
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.query.learned_query_builder import LearnedQueryBuilder
from wiicon5.query_synthesis import QuerySynthesisEngine, QuerySynthesisResult
from wiicon5.query_synthesis.synthesizer import (
    collect_metadata_objects,
    expand_metadata_search_terms,
    postprocess_1c_query,
    search_terms_from_discovery,
)
from wiicon5.skill_runtime.data_skill_runner import DataSkillRunner
from wiicon5.skills.learned import LearnedSkillStore
from wiicon5.skills.registry import SkillRegistry
from wiicon5.testing.scripted_decomposer import ScriptedGoalDecomposer


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class QuerySynthesisTests(unittest.TestCase):
    def test_synthesis_uses_metadata_llm_query_and_mcp_rows(self) -> None:
        llm = ScriptedLLMClient(
            [
                discovery_response(["денежные средства", "касса"]),
                query_response(
                    """
                    ВЫБРАТЬ ПЕРВЫЕ 10
                        Остатки.Касса КАК Касса,
                        Остатки.СуммаОстаток КАК Остаток
                    ИЗ
                        РегистрНакопления.ДенежныеСредства.Остатки() КАК Остатки
                    ГДЕ
                        Остатки.СуммаОстаток <> 0
                    """
                ),
            ]
        )
        engine = QuerySynthesisEngine(
            llm_client=llm,
            metadata_provider=FakeMetadataProvider(),
            mcp_client=DictMcpClient({"success": True, "data": [{"Касса": "Основная касса", "Остаток": 1250}]}),
        )

        result = engine.run(
            message="Показать остаток денежных средств по местам хранения наличных",
            intent=data_intent("Показать остаток денежных средств"),
            goal=GoalDecomposition(
                business_goal="Показать остаток денежных средств",
                final_artifact_type="UserAnswer",
                required_artifacts=[ArtifactRequirement(name="balance", type="UnknownBalanceTable")],
            ),
            context=ConversationContext(session_id="s1"),
            gaps=[],
        )

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.final_artifact)
        self.assertIn("Основная касса", result.message)
        self.assertIn("1250", result.message)
        self.assertIn("metadata_objects", result.trace)
        self.assertEqual(len(llm.calls), 2)

    def test_synthesis_treats_empty_aggregate_row_as_no_data(self) -> None:
        llm = ScriptedLLMClient(
            [
                discovery_response(["выручка"]),
                query_response(
                    """
                    ВЫБРАТЬ
                        СУММА(Р.СуммаВыручкиБезНДС) КАК Выручка,
                        СУММА(Р.СуммаВыручкиБезНДС - Р.СтоимостьБезНДС) КАК Прибыль
                    ИЗ
                        РегистрНакопления.ВыручкаИСебестоимостьПродаж КАК Р
                    ГДЕ
                        Р.Активность
                    """
                ),
            ]
        )
        engine = QuerySynthesisEngine(
            llm_client=llm,
            metadata_provider=FinancialMetadataProvider(),
            mcp_client=DictMcpClient({"success": True, "data": [{"Выручка": "", "Прибыль": ""}]}),
        )

        result = engine.run(
            message="Показать выручку за 2025",
            intent=data_intent("Показать выручку за 2025"),
            goal=None,
            context=ConversationContext(session_id="s1"),
            gaps=[],
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.message, "Данных не найдено.")

    def test_synthesis_repairs_query_after_query_review_error(self) -> None:
        llm = ScriptedLLMClient(
            [
                discovery_response(["денежные средства"]),
                query_response(
                    """
                    ВЫБРАТЬ
                        СУММА(Движения.Сумма) КАК Сумма
                    ИЗ
                        РегистрНакопления.ДенежныеСредства КАК Движения
                    """
                ),
                query_response(
                    """
                    ВЫБРАТЬ
                        СУММА(Движения.Сумма) КАК Сумма
                    ИЗ
                        РегистрНакопления.ДенежныеСредства КАК Движения
                    ГДЕ
                        Движения.Активность
                    """
                ),
            ]
        )
        mcp = DictMcpClient({"success": True, "data": [{"Сумма": 100}]})
        engine = QuerySynthesisEngine(
            llm_client=llm,
            metadata_provider=FakeMetadataProvider(),
            mcp_client=mcp,
        )

        result = engine.run(
            message="Показать сумму движений денежных средств",
            intent=data_intent("Показать сумму движений денежных средств"),
            goal=None,
            context=ConversationContext(session_id="s1"),
            gaps=[],
        )

        self.assertTrue(result.ok)
        self.assertEqual(len(mcp.query_calls), 1)
        self.assertIn("Движения.Активность", mcp.query_calls[0].query)
        self.assertIn("Query review failed", llm.calls[2]["user_payload"]["previous_error"])
        self.assertFalse(result.trace["attempts"][0]["query_review"]["ok"])
        self.assertTrue(result.trace["attempts"][1]["query_review"]["ok"])

    def test_synthesis_repairs_reference_field_string_filter_before_mcp(self) -> None:
        llm = ScriptedLLMClient(
            [
                discovery_response(["остатки", "склад"]),
                query_response(
                    """
                    ВЫБРАТЬ
                        Остатки.Номенклатура КАК Номенклатура,
                        Остатки.КоличествоОстаток КАК Остаток
                    ИЗ
                        РегистрНакопления.ТоварыНаСкладах.Остатки() КАК Остатки
                    ГДЕ
                        Остатки.Склад = &Склад
                    """,
                    params={"Склад": "Центральный склад"},
                ),
                query_response(
                    """
                    ВЫБРАТЬ
                        Остатки.Номенклатура КАК Номенклатура,
                        Остатки.КоличествоОстаток КАК Остаток
                    ИЗ
                        РегистрНакопления.ТоварыНаСкладах.Остатки() КАК Остатки
                    ГДЕ
                        Остатки.Склад.Наименование = &Склад
                    """,
                    params={"Склад": "Центральный склад"},
                ),
            ]
        )
        mcp = DictMcpClient({"success": True, "data": [{"Номенклатура": "Товар 1", "Остаток": 5}]})
        engine = QuerySynthesisEngine(
            llm_client=llm,
            metadata_provider=StockMetadataProvider(),
            mcp_client=mcp,
        )

        result = engine.run(
            message="Покажи остатки по Центральному складу",
            intent=data_intent("Показать остатки по складу"),
            goal=None,
            context=ConversationContext(session_id="s1"),
            gaps=[],
        )

        self.assertTrue(result.ok)
        self.assertIn("Товар 1", result.message)
        self.assertEqual(len(mcp.query_calls), 1)
        self.assertIn("Склад.Наименование", mcp.query_calls[0].query)
        self.assertFalse(result.trace["attempts"][0]["query_review"]["ok"])
        self.assertIn(
            "reference_filter_string_param",
            [issue["code"] for issue in result.trace["attempts"][0]["query_review"]["issues"]],
        )
        self.assertTrue(result.trace["attempts"][1]["query_review"]["ok"])

    def test_synthesis_expands_document_table_part_metadata_after_review_error(self) -> None:
        sales_query = """
            ВЫБРАТЬ ПЕРВЫЕ 10
                Товары.Номенклатура КАК Номенклатура,
                СУММА(Товары.Количество) КАК КоличествоПродано,
                СУММА(Товары.Сумма) КАК СуммаПродаж
            ИЗ
                Документ.РеализацияТоваровУслуг КАК Реализация
                ЛЕВОЕ СОЕДИНЕНИЕ Документ.РеализацияТоваровУслуг.Товары КАК Товары
                ПО Реализация.Ссылка = Товары.Ссылка
            ГДЕ
                Реализация.Проведен
            СГРУППИРОВАТЬ ПО
                Товары.Номенклатура
            УПОРЯДОЧИТЬ ПО
                СуммаПродаж УБЫВ
        """
        llm = ScriptedLLMClient(
            [
                discovery_response(["РеализацияТоваровУслуг", "номенклатура", "продажи"]),
                query_response(sales_query),
                query_response(sales_query),
            ]
        )
        mcp = DictMcpClient(
            {
                "success": True,
                "data": [{"Номенклатура": "Товар 1", "КоличествоПродано": 5, "СуммаПродаж": 1500}],
            }
        )
        provider = TablePartMetadataProvider()
        engine = QuerySynthesisEngine(
            llm_client=llm,
            metadata_provider=provider,
            mcp_client=mcp,
        )

        result = engine.run(
            message="Покажи самую продающуюся номенклатуру",
            intent=IntentResult(
                intent_type=IntentType.DATA_QUESTION,
                business_goal="Показать самую продающуюся номенклатуру",
                requires_1c_data=True,
                expected_output="table",
                domain_terms=["номенклатура", "продажи", "самая продающаяся"],
                relevant=True,
            ),
            goal=None,
            context=ConversationContext(session_id="s1"),
            gaps=[],
        )

        self.assertTrue(result.ok)
        self.assertIn("Товар 1", result.message)
        self.assertEqual(len(mcp.query_calls), 1)
        self.assertFalse(result.trace["attempts"][0]["query_review"]["ok"])
        self.assertTrue(result.trace["attempts"][1]["query_review"]["ok"])
        self.assertIn("Документ.РеализацияТоваровУслуг.Товары", result.trace["attempts"][0]["metadata_repair_terms"])
        self.assertIn("Документ.РеализацияТоваровУслуг.Товары", [req["full_name"] for req in provider.requested_objects])

    def test_synthesis_repairs_query_after_safety_validation_error(self) -> None:
        llm = ScriptedLLMClient(
            [
                discovery_response(["денежные средства"]),
                query_response("УДАЛИТЬ ИЗ РегистрНакопления.ДенежныеСредства"),
                query_response(
                    """
                    ВЫБРАТЬ
                        Остатки.Касса КАК Касса,
                        Остатки.СуммаОстаток КАК Остаток
                    ИЗ
                        РегистрНакопления.ДенежныеСредства.Остатки() КАК Остатки
                    """
                ),
            ]
        )
        mcp = DictMcpClient({"success": True, "data": [{"Касса": "Касса 1", "Остаток": 10}]})
        engine = QuerySynthesisEngine(
            llm_client=llm,
            metadata_provider=FakeMetadataProvider(),
            mcp_client=mcp,
        )

        result = engine.run(
            message="Показать остаток",
            intent=data_intent("Показать остаток"),
            goal=None,
            context=ConversationContext(session_id="s1"),
            gaps=[],
        )

        self.assertTrue(result.ok)
        self.assertEqual(len(mcp.query_calls), 1)
        self.assertIn("Query validation failed", llm.calls[2]["user_payload"]["previous_error"])
        self.assertIn("Касса 1", result.message)

    def test_orchestrator_uses_query_synthesis_when_skill_planning_has_gap(self) -> None:
        question = "Показать остаток денежных средств"
        llm = ScriptedLLMClient(
            [
                discovery_response(["денежные средства", "касса"]),
                query_response(
                    """
                    ВЫБРАТЬ
                        Остатки.Касса КАК Касса,
                        Остатки.СуммаОстаток КАК Остаток
                    ИЗ
                        РегистрНакопления.ДенежныеСредства.Остатки() КАК Остатки
                    """
                ),
            ]
        )
        mcp = DictMcpClient({"success": True, "data": [{"Касса": "Касса 1", "Остаток": 10}]})
        with TemporaryDirectory() as temp_dir:
            orchestrator = AgentOrchestrator(
                registry=SkillRegistry.load_from_dir(PROJECT_ROOT / "skills"),
                decomposer=ScriptedGoalDecomposer({question: cash_balance_decomposition(question)}),
                query_synthesizer=QuerySynthesisEngine(
                    llm_client=llm,
                    metadata_provider=FakeMetadataProvider(),
                    mcp_client=mcp,
                ),
                trace_root=Path(temp_dir),
            )

            result = orchestrator.handle(question, session_id="s1")

            trace_path = Path(result.trace_path or "")
            synthesis_payload = json.loads((trace_path / "query_synthesis/result.json").read_text(encoding="utf-8"))

        self.assertEqual(result.source, "query_synthesis_ok")
        self.assertIn("Касса 1", result.message)
        self.assertTrue(synthesis_payload["synthesis"]["ok"])

    def test_orchestrator_synthesizes_query_when_llm_mislabels_cash_as_stock(self) -> None:
        question = "Показать остаток наличных в кассах"
        llm = ScriptedLLMClient(
            [
                discovery_response(["денежные средства", "касса"]),
                query_response(
                    """
                    ВЫБРАТЬ
                        Остатки.Касса КАК Касса,
                        Остатки.СуммаОстаток КАК Остаток
                    ИЗ
                        РегистрНакопления.ДенежныеСредства.Остатки() КАК Остатки
                    """
                ),
            ]
        )
        mcp = DictMcpClient({"success": True, "data": [{"Касса": "Основная касса", "Остаток": 331111.74}]})
        with TemporaryDirectory() as temp_dir:
            orchestrator = AgentOrchestrator(
                registry=SkillRegistry.load_from_dir(PROJECT_ROOT / "skills"),
                decomposer=ScriptedGoalDecomposer({question: cash_as_stock_decomposition(question)}),
                query_synthesizer=QuerySynthesisEngine(
                    llm_client=llm,
                    metadata_provider=FakeMetadataProvider(),
                    mcp_client=mcp,
                ),
                trace_root=Path(temp_dir),
            )

            result = orchestrator.handle(question, session_id="s1")

            trace_path = Path(result.trace_path or "")
            gap_payload = json.loads((trace_path / "skill_search/skill_gaps.json").read_text(encoding="utf-8"))

        self.assertEqual(result.source, "query_synthesis_ok")
        self.assertIn("Основная касса", result.message)
        self.assertIn("domain:StockBalanceTable", gap_payload["gaps"][0]["missing"])

    def test_orchestrator_persists_and_reuses_learned_period_metric_skill(self) -> None:
        first_question = "Покажи выручку и прибыль за 2025 год"
        second_question = "Покажи выручку и прибыль за все годы по годам"
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills" / "atomic")
        llm = ScriptedLLMClient(
            [
                discovery_response(["выручка", "прибыль"]),
                query_response(
                    """
                    ВЫБРАТЬ
                        СУММА(Р.СуммаВыручкиБезНДС) КАК Выручка,
                        СУММА(Р.СуммаВыручкиБезНДС - Р.СтоимостьБезНДС) КАК Прибыль
                    ИЗ
                        РегистрНакопления.ВыручкаИСебестоимостьПродаж КАК Р
                    ГДЕ
                        Р.Период МЕЖДУ &НачПериода И &КонПериода
                        И Р.Активность
                    """
                )
                | {"params": {"НачПериода": "2025-01-01T00:00:00", "КонПериода": "2025-12-31T23:59:59"}},
            ]
        )
        mcp = DictMcpClient({"success": True, "data": [{"Год": 2024, "Выручка": 100, "Прибыль": 25}]})
        runners = default_runners()
        runners["learned_query"] = DataSkillRunner(query_builder=LearnedQueryBuilder(), mcp_client=mcp)
        with TemporaryDirectory() as temp_dir:
            skills_dir = Path(temp_dir) / "skills"
            skills_dir.mkdir()
            orchestrator = AgentOrchestrator(
                registry=registry,
                decomposer=ScriptedGoalDecomposer(
                    {
                        first_question: financial_gap_decomposition(first_question),
                        second_question: financial_by_year_decomposition(second_question),
                    }
                ),
                plan_executor=SkillPlanExecutor(registry, runners),
                query_synthesizer=QuerySynthesisEngine(
                    llm_client=llm,
                    metadata_provider=FinancialMetadataProvider(),
                    mcp_client=mcp,
                ),
                learned_skill_store=LearnedSkillStore(skills_dir=skills_dir, registry=registry),
                trace_root=Path(temp_dir) / "runs",
            )

            first = orchestrator.handle(first_question, session_id="s1")
            second = orchestrator.handle(second_question, session_id="s1")

            learned_path = skills_dir / "learned" / "learned_financial_metrics.json"
            learned_exists = learned_path.exists()

        self.assertEqual(first.source, "query_synthesis_ok")
        self.assertTrue(learned_exists)
        self.assertIsNotNone(registry.get("learned_financial_metrics"))
        self.assertEqual(second.source, "skill_execution_ok")
        assert second.plan is not None
        self.assertIn("learned_financial_metrics", [node.skill_id for node in second.plan.nodes])
        self.assertIn("ГОД(", mcp.query_calls[-1].query)
        self.assertEqual(len(llm.calls), 2)

    def test_learned_store_does_not_persist_non_generalized_fixed_query(self) -> None:
        registry = SkillRegistry([])
        with TemporaryDirectory() as temp_dir:
            store = LearnedSkillStore(skills_dir=Path(temp_dir), registry=registry)

            result = store.learn_from_synthesis(
                intent=data_intent("Показать произвольный агрегат"),
                goal=None,
                synthesis_result=QuerySynthesisResult(
                    ok=True,
                    trace={
                        "final_query": {
                            "query": "ВЫБРАТЬ 1 КАК Значение",
                            "params": {},
                            "limit": 10,
                        },
                        "metadata_objects": [],
                    },
                ),
            )

            learned_dir_exists = (Path(temp_dir) / "learned").exists()

        self.assertIsNone(result)
        self.assertFalse(learned_dir_exists)

    def test_postprocess_removes_redundant_reference_join_and_empty_balance_args(self) -> None:
        query = (
            "ВЫБРАТЬ Касса.Наименование КАК Касса, Остатки.СуммаОстаток КАК Остаток "
            "ИЗ РегистрНакопления.ДенежныеСредстваНаличные.Остатки(, , ) КАК Остатки "
            "ВНУТРЕННЕЕ СОЕДИНЕНИЕ Справочник.Кассы КАК Касса ПО Остатки.Касса = Касса.Ссылка"
        )

        result = postprocess_1c_query(query)

        self.assertIn("Остатки()", result)
        self.assertIn("Остатки.Касса КАК Касса", result)
        self.assertNotIn("ВНУТРЕННЕЕ СОЕДИНЕНИЕ", result)
        self.assertNotIn("Касса.Ссылка", result)

    def test_postprocess_removes_left_reference_join_too(self) -> None:
        query = (
            "ВЫБРАТЬ Касса.Наименование КАК Касса, Остатки.СуммаОстаток КАК Остаток "
            "ИЗ РегистрНакопления.ДенежныеСредстваНаличные.Остатки() КАК Остатки "
            "ЛЕВОЕ СОЕДИНЕНИЕ Справочник.Кассы КАК Касса ПО Остатки.Касса = Касса.Ссылка"
        )

        result = postprocess_1c_query(query)

        self.assertIn("Остатки.Касса КАК Касса", result)
        self.assertNotIn("ЛЕВОЕ СОЕДИНЕНИЕ", result)
        self.assertNotIn("Касса.Ссылка", result)

    def test_postprocess_adds_empty_parentheses_to_accumulation_virtual_table(self) -> None:
        query = (
            "ВЫБРАТЬ Продажи.Номенклатура КАК Номенклатура "
            "ИЗ РегистрНакопления.Продажи.Обороты КАК Продажи"
        )

        result = postprocess_1c_query(query)

        self.assertIn("РегистрНакопления.Продажи.Обороты() КАК Продажи", result)

    def test_search_terms_keep_user_domain_terms_when_discovery_returns_many_terms(self) -> None:
        terms = search_terms_from_discovery(
            {
                "metadata_search_terms": [
                    "term01",
                    "term02",
                    "term03",
                    "term04",
                    "term05",
                    "term06",
                    "term07",
                    "term08",
                    "term09",
                    "term10",
                ]
            },
            IntentResult(
                intent_type=IntentType.DATA_QUESTION,
                business_goal="Показать продажи",
                requires_1c_data=True,
                domain_terms=["номенклатура", "продажи"],
                relevant=True,
            ),
            "Покажи самую продающуюся номенклатуру",
        )

        self.assertIn("номенклатура", terms)
        self.assertIn("продажи", terms)

    def test_metadata_search_terms_expand_common_1c_business_vocabulary(self) -> None:
        terms = expand_metadata_search_terms(["номенклатура", "продажи"])

        self.assertIn("Справочник.Номенклатура", terms)
        self.assertIn("Документ.РеализацияТоваровУслуг", terms)
        self.assertIn("РегистрНакопления.ВыручкаИСебестоимостьПродаж", terms)

    def test_metadata_collection_prioritizes_queryable_objects_before_modules(self) -> None:
        provider = RankingMetadataProvider()

        result = collect_metadata_objects(provider, search_terms=["денежные средства"], max_objects=1)

        self.assertEqual([item.full_name for item in result], ["РегистрНакопления.ДенежныеСредстваНаличные"])
        self.assertIn("Сумма", result[0].fields)


class FakeMetadataProvider(MetadataProvider):
    def __init__(self) -> None:
        self.object = metadata_object_from_payload(
            {
                "ПолноеИмя": "РегистрНакопления.ДенежныеСредства",
                "Синоним": "Денежные средства",
                "Измерения": [
                    {"Имя": "Касса", "Тип": "СправочникСсылка.Кассы"},
                    {"Имя": "Организация", "Тип": "СправочникСсылка.Организации"},
                ],
                "Ресурсы": [{"Имя": "Сумма", "Тип": "Число(15, 2)"}],
            }
        )
        self.last_requests: List[Dict[str, object]] = []

    def search_objects(self, term: str) -> List[MetadataObject]:
        self.last_requests.append({"operation": "search_objects", "term": term})
        return [self.object]

    def get_object(self, full_name: str) -> MetadataObject:
        self.last_requests.append({"operation": "get_object", "full_name": full_name})
        return self.object


class RankingMetadataProvider(MetadataProvider):
    def search_objects(self, term: str) -> List[MetadataObject]:
        return [
            metadata_object_from_payload(
                {
                    "ПолноеИмя": "ОбщийМодуль.ДенежныеСредстваСервер",
                    "Синоним": "Денежные средства сервер",
                }
            ),
            metadata_object_from_payload(
                {
                    "ПолноеИмя": "Отчет.ОстаткиИДвиженияДенежныхСредствВКассахККМ",
                    "Синоним": "Денежные средства в кассах ККМ",
                }
            ),
            metadata_object_from_payload(
                {
                    "ПолноеИмя": "РегистрНакопления.ДенежныеСредстваНаличные",
                    "Синоним": "Денежные средства наличные",
                }
            ),
        ]

    def get_object(self, full_name: str) -> MetadataObject:
        if full_name == "РегистрНакопления.ДенежныеСредстваНаличные":
            return metadata_object_from_payload(
                {
                    "ПолноеИмя": full_name,
                    "Синоним": "Денежные средства наличные",
                    "Измерения": [{"Имя": "Касса", "Тип": "СправочникСсылка.Кассы"}],
                    "Ресурсы": [{"Имя": "Сумма", "Тип": "Число"}],
                }
            )
        return metadata_object_from_payload({"ПолноеИмя": full_name})


class FinancialMetadataProvider(MetadataProvider):
    def __init__(self) -> None:
        self.object = metadata_object_from_payload(
            {
                "ПолноеИмя": "РегистрНакопления.ВыручкаИСебестоимостьПродаж",
                "Синоним": "Выручка и себестоимость продаж",
                "Ресурсы": [
                    {"Имя": "СуммаВыручкиБезНДС", "Тип": "Число"},
                    {"Имя": "СтоимостьБезНДС", "Тип": "Число"},
                ],
            }
        )
        self.last_requests: List[Dict[str, object]] = []

    def search_objects(self, term: str) -> List[MetadataObject]:
        self.last_requests.append({"operation": "search_objects", "term": term})
        return [self.object]

    def get_object(self, full_name: str) -> MetadataObject:
        self.last_requests.append({"operation": "get_object", "full_name": full_name})
        return self.object


class StockMetadataProvider(MetadataProvider):
    def __init__(self) -> None:
        self.object = metadata_object_from_payload(
            {
                "ПолноеИмя": "РегистрНакопления.ТоварыНаСкладах",
                "Синоним": "Товары на складах",
                "Измерения": [
                    {"Имя": "Номенклатура", "Тип": "СправочникСсылка.Номенклатура"},
                    {"Имя": "Склад", "Тип": "СправочникСсылка.Склады"},
                ],
                "Ресурсы": [{"Имя": "Количество", "Тип": "Число"}],
            }
        )
        self.last_requests: List[Dict[str, object]] = []

    def search_objects(self, term: str) -> List[MetadataObject]:
        self.last_requests.append({"operation": "search_objects", "term": term})
        return [self.object]

    def get_object(self, full_name: str) -> MetadataObject:
        self.last_requests.append({"operation": "get_object", "full_name": full_name})
        return self.object


class TablePartMetadataProvider(MetadataProvider):
    def __init__(self) -> None:
        self.parent = metadata_object_from_payload(
            {
                "ПолноеИмя": "Документ.РеализацияТоваровУслуг",
                "Синоним": "Реализация товаров и услуг",
                "Реквизиты": [{"Имя": "Проведен", "Тип": "Булево"}],
                "ТабличныеЧасти": [{"Имя": "Товары"}],
            }
        )
        self.table_part = metadata_object_from_payload(
            {
                "ПолноеИмя": "Документ.РеализацияТоваровУслуг.Товары",
                "Синоним": "Товары",
                "Реквизиты": [
                    {"Имя": "Номенклатура", "Тип": "СправочникСсылка.Номенклатура"},
                    {"Имя": "Количество", "Тип": "Число"},
                    {"Имя": "Сумма", "Тип": "Число"},
                ],
                "СтандартныеРеквизиты": [{"Имя": "Ссылка", "Тип": "ДокументСсылка.РеализацияТоваровУслуг"}],
            }
        )
        self.requested_objects: List[Dict[str, str]] = []
        self.last_requests: List[Dict[str, object]] = []

    def search_objects(self, term: str) -> List[MetadataObject]:
        self.last_requests.append({"operation": "search_objects", "term": term})
        if "РеализацияТоваровУслуг.Товары" in term:
            return [self.table_part]
        return [self.parent]

    def get_object(self, full_name: str) -> MetadataObject:
        self.last_requests.append({"operation": "get_object", "full_name": full_name})
        self.requested_objects.append({"full_name": full_name})
        if full_name == "Документ.РеализацияТоваровУслуг.Товары":
            return self.table_part
        return self.parent


def discovery_response(terms: List[str]) -> Dict[str, object]:
    return {
        "metadata_search_terms": terms,
        "hypothesis": "Нужно найти регистр накопления денежных средств с остатками по кассе.",
        "draft_query": "",
    }


def query_response(query: str, params=None) -> Dict[str, object]:
    return {"query": query.strip(), "params": dict(params or {}), "limit": 10, "reasoning": "read-only balance query"}


def data_intent(goal: str) -> IntentResult:
    return IntentResult(
        intent_type=IntentType.DATA_QUESTION,
        business_goal=goal,
        requires_1c_data=True,
        expected_output="table",
        domain_terms=["остаток", "денежные средства"],
        relevant=True,
    )


def cash_balance_decomposition(question: str) -> DecompositionResult:
    return DecompositionResult(
        intent=data_intent(question),
        goal=GoalDecomposition(
            business_goal=question,
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[ArtifactRequirement(name="cash_balances", type="CashBalanceTable")],
        ),
    )


def cash_as_stock_decomposition(question: str) -> DecompositionResult:
    return DecompositionResult(
        intent=data_intent(question),
        goal=GoalDecomposition(
            business_goal=question,
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
        ),
    )


def financial_gap_decomposition(question: str) -> DecompositionResult:
    return DecompositionResult(
        intent=IntentResult(
            intent_type=IntentType.DATA_QUESTION,
            business_goal=question,
            requires_1c_data=True,
            expected_output="table",
            domain_terms=["выручка", "прибыль", "2025 год"],
            relevant=True,
        ),
        goal=GoalDecomposition(
            business_goal=question,
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[ArtifactRequirement(name="metrics", type="FinancialMetricsTable")],
        ),
    )


def financial_by_year_decomposition(question: str) -> DecompositionResult:
    return DecompositionResult(
        intent=IntentResult(
            intent_type=IntentType.DATA_QUESTION,
            business_goal=question,
            requires_1c_data=True,
            expected_output="table",
            domain_terms=["выручка", "прибыль", "по годам"],
            relevant=True,
        ),
        goal=GoalDecomposition(
            business_goal=question,
            final_artifact_type="UserAnswer",
            expected_answer_type="table",
            required_artifacts=[
                ArtifactRequirement(
                    name="metrics",
                    type="FinancialMetricsTable",
                    constraints=[
                        SemanticFilter(
                            semantic_field="period_granularity",
                            operator="equals",
                            value="year",
                            raw_user_text="по годам",
                        )
                    ],
                )
            ],
        ),
    )


if __name__ == "__main__":
    unittest.main()

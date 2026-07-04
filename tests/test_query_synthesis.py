from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List

from wiicon5.agent.orchestrator import AgentOrchestrator
from wiicon5.bot_instance import BotInstanceConfig
from wiicon5.conversation.context import ConversationContext
from wiicon5.conversation.memory import ConversationMemory
from wiicon5.execution.artifacts import Artifact
from wiicon5.execution.runtime import SkillPlanExecutor, default_runners
from wiicon5.intent.decomposer import DecompositionResult
from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.knowledge.metadata import MetadataObject, MetadataProvider, metadata_object_from_payload
from wiicon5.llm.client import ScriptedLLMClient
from wiicon5.mcp.client import DictMcpClient, McpClient
from wiicon5.mcp.contracts import McpMetadataRequest, McpMetadataResponse, McpQueryRequest, McpQueryResponse
from wiicon5.models import ArtifactRequirement, SemanticFilter, SkillContract
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.query.learned_query_builder import LearnedQueryBuilder
from wiicon5.query.query_builder import QueryBuildError
from wiicon5.query.reference_value_resolver import best_reference_match
from wiicon5.query_synthesis import QuerySynthesisEngine, QuerySynthesisResult
from wiicon5.query_synthesis.synthesizer import (
    collect_metadata_objects,
    expand_metadata_search_terms,
    postprocess_1c_query,
    search_terms_from_discovery,
    should_expand_metadata,
)
from wiicon5.query_synthesis.sufficiency import deterministic_partial_review
from wiicon5.query_synthesis.term_expansion import CompositeMetadataTermExpansionPolicy
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
            onboarding_evidence_provider=FakeOnboardingEvidenceProvider(),
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
        self.assertEqual(
            llm.calls[1]["user_payload"]["onboarding_evidence"]["query_patterns"][0]["pattern_id"],
            "evidence_query",
        )
        self.assertEqual(len(llm.calls), 2)

    def test_synthesis_continues_after_partial_document_reference_result(self) -> None:
        document_ref = document_object_ref(
            guid="bf22af7c-fbc6-11ee-90c8-90004ef3f886",
            presentation="Приобретение товаров и услуг 0000-000019 от 16.04.2024 11:03:50",
        )
        supplier_ref = {
            "_objectRef": True,
            "УникальныйИдентификатор": "307a3bac-1966-11e4-bb59-000d884fd00d",
            "ТипОбъекта": "СправочникСсылка.Контрагенты",
            "Представление": "Электротовары",
        }
        llm = ScriptedLLMClient(
            [
                discovery_response(["ПриобретениеТоваровУслуг", "поставка", "контрагент", "сумма"]),
                query_response(
                    """
                    ВЫБРАТЬ ПЕРВЫЕ 1
                        Поступление.Ссылка КАК СсылкаПоследнегоПоступления
                    ИЗ
                        Документ.ПриобретениеТоваровУслуг КАК Поступление
                    ГДЕ
                        Поступление.Проведен
                    УПОРЯДОЧИТЬ ПО
                        Поступление.Дата УБЫВ
                    """
                )
                | {
                    "reasoning": (
                        "Сначала нужно найти последний документ поступления. "
                        "В текущем запросе только находим последнюю поставку."
                    )
                },
                query_response(
                    """
                    ВЫБРАТЬ
                        Поступление.Контрагент КАК Контрагент,
                        Поступление.Долг КАК Долг
                    ИЗ
                        Документ.ПриобретениеТоваровУслуг КАК Поступление
                    ГДЕ
                        Поступление.Ссылка = &Ссылка
                    """,
                    params={"Ссылка": document_ref},
                ),
            ]
        )
        mcp = SequentialMcpClient(
            [
                {"success": True, "data": [{"СсылкаПоследнегоПоступления": document_ref}]},
                {"success": True, "data": [{"Контрагент": supplier_ref, "Долг": 43800}]},
            ]
        )
        engine = QuerySynthesisEngine(
            llm_client=llm,
            metadata_provider=PurchaseDocumentMetadataProvider(),
            mcp_client=mcp,
        )

        result = engine.run(
            message="Кому мы должны должны за последнюю поставку и сколько?",
            intent=IntentResult(
                intent_type=IntentType.DATA_QUESTION,
                business_goal="Узнать задолженность перед поставщиком за последнюю поставку",
                requires_1c_data=True,
                expected_output="short_answer",
                domain_terms=["поставщик", "задолженность", "поставка", "долг"],
                relevant=True,
            ),
            goal=None,
            context=ConversationContext(session_id="s1"),
            gaps=[],
        )

        self.assertTrue(result.ok)
        self.assertIn("Электротовары", result.message)
        self.assertIn("43800", result.message)
        self.assertEqual(len(mcp.query_calls), 2)
        self.assertEqual(mcp.query_calls[1].params["Ссылка"]["УникальныйИдентификатор"], document_ref["УникальныйИдентификатор"])
        self.assertFalse(result.trace["attempts"][0]["result_sufficiency"]["sufficient"])
        self.assertEqual(
            llm.calls[2]["user_payload"]["previous_successful_steps"][0]["rows"][0]["СсылкаПоследнегоПоступления"][
                "УникальныйИдентификатор"
            ],
            document_ref["УникальныйИдентификатор"],
        )
        self.assertTrue(result.context_artifacts)
        self.assertEqual(result.context_artifacts[0].type, "QueryResult")

    def test_reference_match_does_not_confuse_similar_document_numbers(self) -> None:
        wanted = "Приобретение товаров и услуг 0000-000019 от 16.04.2024 11:03:50"
        wrong_ref = document_object_ref(
            guid="f00b59bd-afa6-11ee-a8ec-90004ef3f886",
            presentation="Приобретение товаров и услуг 0000-000001 от 08.01.2024 12:00:00",
        )
        right_ref = document_object_ref(
            guid="bf22af7c-fbc6-11ee-90c8-90004ef3f886",
            presentation=wanted,
        )

        no_match = best_reference_match(wanted, [{"Значение": wrong_ref, "Представление": wrong_ref["Представление"]}])
        match = best_reference_match(
            wanted,
            [
                {"Значение": wrong_ref, "Представление": wrong_ref["Представление"]},
                {"Значение": right_ref, "Представление": right_ref["Представление"]},
            ],
        )

        self.assertIsNone(no_match)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.value["УникальныйИдентификатор"], right_ref["УникальныйИдентификатор"])

    def test_sufficiency_accepts_empty_debt_metric_as_found_no_debt_result(self) -> None:
        review = deterministic_partial_review(
            question="Кому мы должны за последнюю поставку и сколько?",
            columns=["Контрагент", "Долг"],
            rows=[{"Контрагент": "Электротовары", "Долг": ""}],
            query_reasoning="",
        )

        self.assertIsNotNone(review)
        assert review is not None
        self.assertTrue(review.sufficient)

    def test_sufficiency_rejects_document_amount_for_debt_question(self) -> None:
        review = deterministic_partial_review(
            question="Кто имеет дебиторскую задолженность по последней отгрузке и сколько?",
            columns=["Контрагент", "СуммаДокумента"],
            rows=[{"Контрагент": "Омега", "СуммаДокумента": 461000}],
            query_reasoning="",
        )

        self.assertIsNotNone(review)
        assert review is not None
        self.assertFalse(review.sufficient)
        self.assertIn("Сумма задолженности", review.missing_facts[0])
        self.assertFalse(review.needs_clarification)

    def test_sufficiency_requests_clarification_for_ambiguous_debt_or_document_amount(self) -> None:
        review = deterministic_partial_review(
            question="Кто нам должен за последнюю отгрузку и сколько?",
            columns=["Контрагент", "СуммаДокумента"],
            rows=[{"Контрагент": "Омега", "СуммаДокумента": 96900}],
            query_reasoning="",
        )

        self.assertIsNotNone(review)
        assert review is not None
        self.assertFalse(review.sufficient)
        self.assertTrue(review.needs_clarification)
        self.assertIn("сумму последней отгрузки", review.clarification_question)
        self.assertGreaterEqual(len(review.clarification_options), 2)

    def test_sufficiency_requests_clarification_for_ambiguous_debt_after_document_ref_only(self) -> None:
        review = deterministic_partial_review(
            question="Кто нам должен за последнюю отгрузку и сколько?",
            columns=["Ссылка", "Контрагент"],
            rows=[{"Ссылка": "Реализация 0000-000024", "Контрагент": "Омега"}],
            query_reasoning="",
        )

        self.assertIsNotNone(review)
        assert review is not None
        self.assertFalse(review.sufficient)
        self.assertTrue(review.needs_clarification)
        self.assertIn("сумму последней отгрузки", review.clarification_question)

    def test_synthesis_returns_clarification_for_ambiguous_debt_or_shipment_amount(self) -> None:
        customer_ref = {
            "_objectRef": True,
            "УникальныйИдентификатор": "customer-1",
            "ТипОбъекта": "СправочникСсылка.Контрагенты",
            "Представление": "Омега",
        }
        llm = ScriptedLLMClient(
            [
                discovery_response(["отгрузка", "реализация", "контрагент", "сумма"]),
                query_response(
                    """
                    ВЫБРАТЬ ПЕРВЫЕ 1
                        Реализация.Контрагент КАК Контрагент,
                        Реализация.СуммаДокумента КАК СуммаДокумента
                    ИЗ
                        Документ.РеализацияТоваровУслуг КАК Реализация
                    ГДЕ
                        Реализация.Проведен
                    УПОРЯДОЧИТЬ ПО
                        Реализация.Дата УБЫВ
                    """
                ),
            ]
        )
        mcp = SequentialMcpClient(
            [{"success": True, "data": [{"Контрагент": customer_ref, "СуммаДокумента": 96900}]}]
        )
        engine = QuerySynthesisEngine(
            llm_client=llm,
            metadata_provider=SalesDocumentMetadataProvider(),
            mcp_client=mcp,
        )

        result = engine.run(
            message="Кто нам должен за последнюю отгрузку и сколько?",
            intent=IntentResult(
                intent_type=IntentType.DATA_QUESTION,
                business_goal="Уточнить сумму по последней отгрузке или задолженность",
                requires_1c_data=True,
                expected_output="short_answer",
                domain_terms=["отгрузка", "должен", "сумма"],
                relevant=True,
            ),
            goal=None,
            context=ConversationContext(session_id="s1"),
            gaps=[],
        )

        self.assertFalse(result.ok)
        self.assertTrue(result.needs_clarification)
        self.assertIn("Уточните", result.message)
        self.assertIn("Сумму последней отгрузки", result.message)
        self.assertIn("Омега", result.message)
        self.assertIn("Я нашел последнюю отгрузку", result.message)
        self.assertNotIn("Контрагент | СуммаДокумента", result.message)
        self.assertEqual(len(mcp.query_calls), 1)
        self.assertEqual(result.context_artifacts[0].type, "ClarificationRequest")
        self.assertEqual(result.context_artifacts[0].value["partial_result"]["rows"][0]["СуммаДокумента"], 96900)

    def test_orchestrator_returns_clarification_instead_of_skill_gap(self) -> None:
        question = "Кто нам должен за последнюю отгрузку и сколько?"
        customer_ref = {
            "_objectRef": True,
            "УникальныйИдентификатор": "customer-1",
            "ТипОбъекта": "СправочникСсылка.Контрагенты",
            "Представление": "Омега",
        }
        llm = ScriptedLLMClient(
            [
                discovery_response(["отгрузка", "реализация", "контрагент", "сумма"]),
                query_response(
                    """
                    ВЫБРАТЬ ПЕРВЫЕ 1
                        Реализация.Контрагент КАК Контрагент,
                        Реализация.СуммаДокумента КАК СуммаДокумента
                    ИЗ
                        Документ.РеализацияТоваровУслуг КАК Реализация
                    ГДЕ
                        Реализация.Проведен
                    УПОРЯДОЧИТЬ ПО
                        Реализация.Дата УБЫВ
                    """
                ),
            ]
        )
        mcp = SequentialMcpClient(
            [{"success": True, "data": [{"Контрагент": customer_ref, "СуммаДокумента": 96900}]}]
        )
        with TemporaryDirectory() as temp_dir:
            orchestrator = AgentOrchestrator(
                registry=SkillRegistry.load_from_dir(PROJECT_ROOT / "skills"),
                decomposer=ScriptedGoalDecomposer({question: debt_question_decomposition(question)}),
                query_synthesizer=QuerySynthesisEngine(
                    llm_client=llm,
                    metadata_provider=SalesDocumentMetadataProvider(),
                    mcp_client=mcp,
                ),
                trace_root=Path(temp_dir),
            )

            result = orchestrator.handle(question, session_id="s1")
            trace_path = Path(result.trace_path or "")
            result_payload = json.loads((trace_path / "result/result.json").read_text(encoding="utf-8"))

        self.assertEqual(result.source, "needs_clarification")
        self.assertIn("Уточните", result.message)
        self.assertEqual(result.context_artifacts[0].type, "ClarificationRequest")
        self.assertEqual(result_payload["source"], "needs_clarification")

    def test_orchestrator_resolves_document_amount_clarification_without_new_query(self) -> None:
        question = "Покажи сумму отгрузки по документу"
        memory = ConversationMemory()
        context = memory.get_or_create("s1")
        context.add_artifact(
            Artifact(
                name="clarification_request",
                type="ClarificationRequest",
                value={
                    "question": "Кто нам должен за последнюю отгрузку и сколько?",
                    "clarification_question": (
                        "Уточните, что именно показать: сумму последней отгрузки по документу "
                        "или фактическую задолженность клиента после оплат и зачетов?"
                    ),
                    "clarification_options": [
                        "Сумму последней отгрузки по документу",
                        "Фактическую задолженность клиента",
                    ],
                    "partial_result": {
                        "query": "ВЫБРАТЬ ...",
                        "params": {},
                        "columns": ["Контрагент", "СуммаДокумента"],
                        "rows": [
                            {
                                "Контрагент": {
                                    "_objectRef": True,
                                    "УникальныйИдентификатор": "customer-1",
                                    "ТипОбъекта": "СправочникСсылка.Контрагенты",
                                    "Представление": "Омега",
                                },
                                "СуммаДокумента": 96900,
                            }
                        ],
                    },
                },
                provenance=["test"],
            )
        )
        decomposer = ScriptedGoalDecomposer({})
        with TemporaryDirectory() as temp_dir:
            orchestrator = AgentOrchestrator(
                registry=SkillRegistry.load_from_dir(PROJECT_ROOT / "skills"),
                decomposer=decomposer,
                memory=memory,
                trace_root=Path(temp_dir),
            )

            result = orchestrator.handle(question, session_id="s1")

        self.assertEqual(result.source, "clarification_resolved")
        self.assertIn("96900", result.message)
        self.assertIn("Омега", result.message)
        self.assertEqual(decomposer.calls, [])

    def test_synthesis_rejects_repeated_partial_query_and_asks_for_new_query(self) -> None:
        document_ref = document_object_ref(
            guid="bf22af7c-fbc6-11ee-90c8-90004ef3f886",
            presentation="Приобретение товаров и услуг 0000-000019 от 16.04.2024 11:03:50",
        )
        partial_query = """
            ВЫБРАТЬ ПЕРВЫЕ 1
                Поступление.Ссылка КАК Документ
            ИЗ
                Документ.ПриобретениеТоваровУслуг КАК Поступление
            ГДЕ
                Поступление.Проведен
            УПОРЯДОЧИТЬ ПО
                Поступление.Дата УБЫВ
        """
        llm = ScriptedLLMClient(
            [
                discovery_response(["ПриобретениеТоваровУслуг", "поставка", "контрагент", "сумма"]),
                query_response(partial_query)
                | {"reasoning": "Сначала найдем последний документ. В текущем запросе только находим поставку."},
                query_response(partial_query)
                | {"reasoning": "Теперь нужно получить сумму, но query случайно повторен."},
                query_response(
                    """
                    ВЫБРАТЬ
                        Поступление.Контрагент КАК Контрагент,
                        Поступление.Долг КАК Долг
                    ИЗ
                        Документ.ПриобретениеТоваровУслуг КАК Поступление
                    ГДЕ
                        Поступление.Ссылка = &Ссылка
                    """,
                    params={"Ссылка": document_ref},
                ),
            ]
        )
        mcp = SequentialMcpClient(
            [
                {"success": True, "data": [{"Документ": document_ref}]},
                {
                    "success": True,
                    "data": [
                        {
                            "Контрагент": {
                                "_objectRef": True,
                                "УникальныйИдентификатор": "supplier-1",
                                "ТипОбъекта": "СправочникСсылка.Контрагенты",
                                "Представление": "Электротовары",
                            },
                            "Долг": 43800,
                        }
                    ],
                },
            ]
        )
        engine = QuerySynthesisEngine(
            llm_client=llm,
            metadata_provider=PurchaseDocumentMetadataProvider(),
            mcp_client=mcp,
        )

        result = engine.run(
            message="Кому мы должны должны за последнюю поставку и сколько?",
            intent=data_intent("Узнать поставщика и сумму последней поставки"),
            goal=None,
            context=ConversationContext(session_id="s1"),
            gaps=[],
        )

        self.assertTrue(result.ok)
        self.assertEqual(len(mcp.query_calls), 2)
        self.assertTrue(result.trace["attempts"][1]["repeated_partial_query"])
        self.assertIn("Repeated previous partial query", llm.calls[3]["user_payload"]["previous_error"])
        self.assertIn("Электротовары", result.message)

    def test_synthesis_rejects_empty_list_param_before_mcp_and_repairs(self) -> None:
        retail_type_ref = {
            "_objectRef": True,
            "УникальныйИдентификатор": "РозничныйМагазин",
            "ТипОбъекта": "ПеречислениеСсылка.ТипыСкладов",
            "Представление": "Розничный магазин",
        }
        llm = ScriptedLLMClient(
            [
                discovery_response(["остатки", "склад"]),
                query_response(
                    """
                    ВЫБРАТЬ ПЕРВЫЕ 1
                        Остатки.Номенклатура КАК Номенклатура,
                        СУММА(Остатки.КоличествоОстаток) КАК Остаток
                    ИЗ
                        РегистрНакопления.ТоварыНаСкладах.Остатки(, Склад В (&РозничныеСклады)) КАК Остатки
                    СГРУППИРОВАТЬ ПО
                        Остатки.Номенклатура
                    УПОРЯДОЧИТЬ ПО
                        Остаток УБЫВ
                    """,
                    params={"РозничныеСклады": []},
                ),
                query_response(
                    """
                    ВЫБРАТЬ ПЕРВЫЕ 1
                        Остатки.Номенклатура КАК Номенклатура,
                        СУММА(Остатки.КоличествоОстаток) КАК Остаток
                    ИЗ
                        РегистрНакопления.ТоварыНаСкладах.Остатки() КАК Остатки
                    СГРУППИРОВАТЬ ПО
                        Остатки.Номенклатура
                    УПОРЯДОЧИТЬ ПО
                        Остаток УБЫВ
                    """
                ),
                query_response(
                    """
                    ВЫБРАТЬ ПЕРВЫЕ 1
                        Остатки.Номенклатура КАК Номенклатура,
                        Остатки.КоличествоОстаток КАК Остаток
                    ИЗ
                        РегистрНакопления.ТоварыНаСкладах.Остатки(
                            ,
                            Склад В (
                                ВЫБРАТЬ
                                    Склады.Ссылка
                                ИЗ
                                    Справочник.Склады КАК Склады
                                ГДЕ
                                    Склады.ТипСклада = &ТипСклада
                            )
                        ) КАК Остатки
                    УПОРЯДОЧИТЬ ПО
                        Остатки.КоличествоОстаток УБЫВ
                    """,
                    params={"ТипСклада": retail_type_ref},
                ),
                query_response(
                    """
                    ВЫБРАТЬ ПЕРВЫЕ 1
                        Остатки.Номенклатура КАК Номенклатура,
                        СУММА(Остатки.КоличествоОстаток) КАК Остаток
                    ИЗ
                        РегистрНакопления.ТоварыНаСкладах.Остатки(
                            ,
                            Склад В (
                                ВЫБРАТЬ
                                    Склады.Ссылка
                                ИЗ
                                    Справочник.Склады КАК Склады
                                ГДЕ
                                    Склады.ТипСклада = &ТипСклада
                            )
                        ) КАК Остатки
                    СГРУППИРОВАТЬ ПО
                        Остатки.Номенклатура
                    УПОРЯДОЧИТЬ ПО
                        Остаток УБЫВ
                    """,
                    params={"ТипСклада": retail_type_ref},
                ),
            ]
        )
        mcp = DictMcpClient({"success": True, "data": [{"Номенклатура": "Кондиционер", "Остаток": 30}]})
        engine = QuerySynthesisEngine(
            llm_client=llm,
            metadata_provider=StockAndWarehouseMetadataProvider(),
            mcp_client=mcp,
        )

        result = engine.run(
            message="Покажи какого товара больше всего в розничном магазине?",
            intent=data_intent("Показать товар с максимальным остатком"),
            goal=top_stock_by_retail_goal(),
            context=ConversationContext(session_id="s1"),
            gaps=[],
        )

        self.assertTrue(result.ok)
        self.assertEqual(len(mcp.query_calls), 1)
        self.assertEqual(result.trace["attempts"][0]["empty_list_params"], ["РозничныеСклады"])
        self.assertIn("empty list parameter", llm.calls[2]["user_payload"]["previous_error"])
        self.assertEqual(
            result.trace["attempts"][1]["goal_semantic_review"]["issues"][0]["code"],
            "required_filter_not_reflected",
        )
        self.assertEqual(
            result.trace["attempts"][2]["goal_semantic_review"]["issues"][0]["code"],
            "aggregate_grain_not_confirmed",
        )
        final_query = mcp.query_calls[0].query
        self.assertIn("Справочник.Склады", final_query)
        self.assertIn("ТипСклада", final_query)
        self.assertIn("СУММА", final_query)
        self.assertIn("СГРУППИРОВАТЬ ПО", final_query)
        self.assertIn("Кондиционер", result.message)

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

    def test_synthesis_repairs_metadata_after_mcp_error(self) -> None:
        llm = ScriptedLLMClient(
            [
                discovery_response(["денежные средства"]),
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
                {"metadata_search_terms": ["ДенежныеСредстваНаличные"], "reasoning": "Нужно проверить другой регистр."},
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
        mcp = SequentialMcpClient(
            [
                {"success": False, "error": "Поле не найдено: Сумма"},
                {"success": True, "data": [{"Сумма": 100}]},
            ]
        )
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
        self.assertEqual(len(mcp.query_calls), 2)
        self.assertEqual(result.trace["attempts"][0]["metadata_repair_terms"], ["ДенежныеСредстваНаличные"])

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
        self.assertGreaterEqual(len(mcp.query_calls), 1)
        self.assertIn("Склад.Наименование", mcp.query_calls[-1].query)
        self.assertFalse(result.trace["attempts"][0]["query_review"]["ok"])
        self.assertIn(
            "reference_filter_string_param",
            [issue["code"] for issue in result.trace["attempts"][0]["query_review"]["issues"]],
        )
        self.assertTrue(result.trace["attempts"][1]["query_review"]["ok"])

    def test_synthesis_resolves_unconfirmed_enum_literal_before_main_mcp_query(self) -> None:
        llm = ScriptedLLMClient(
            [
                discovery_response(["склад", "тип склада"]),
                query_response(
                    """
                    ВЫБРАТЬ
                        КОЛИЧЕСТВО(Склады.Ссылка) КАК Количество
                    ИЗ
                        Справочник.Склады КАК Склады
                    ГДЕ
                        Склады.ТипСклада = ЗНАЧЕНИЕ(Перечисление.ТипыСкладов.Розничный)
                    """
                ),
            ]
        )
        retail_ref = {
            "_objectRef": True,
            "УникальныйИдентификатор": "РозничныйМагазин",
            "ТипОбъекта": "ПеречислениеСсылка.ТипыСкладов",
            "Представление": "Розничный магазин",
        }
        mcp = SequentialMcpClient(
            [
                {"success": True, "data": [{"Значение": retail_ref, "Представление": "Розничный магазин"}]},
                {"success": True, "data": [{"Количество": 4}]},
            ]
        )
        engine = QuerySynthesisEngine(
            llm_client=llm,
            metadata_provider=WarehouseMetadataProvider(),
            mcp_client=mcp,
        )

        result = engine.run(
            message="Сколько в системе розничных складов?",
            intent=IntentResult(
                intent_type=IntentType.DATA_QUESTION,
                business_goal="Узнать количество розничных складов",
                requires_1c_data=True,
                expected_output="short_answer",
                domain_terms=["склад", "розничный склад", "количество"],
                relevant=True,
            ),
            goal=None,
            context=ConversationContext(session_id="s1"),
            gaps=[],
        )

        self.assertTrue(result.ok)
        self.assertIn("4", result.message)
        self.assertEqual(len(mcp.query_calls), 2)
        self.assertIn("ПРЕДСТАВЛЕНИЕ(Склады.ТипСклада)", mcp.query_calls[0].query)
        self.assertIn("Склады.ТипСклада = &ТипСклада_resolved", mcp.query_calls[1].query)
        self.assertEqual(mcp.query_calls[1].params["ТипСклада_resolved"]["УникальныйИдентификатор"], "РозничныйМагазин")
        self.assertTrue(result.trace["attempts"][0]["reference_value_resolution"]["changed"])

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
            memory = ConversationMemory(default_config_fingerprint="cfg")
            orchestrator = AgentOrchestrator(
                registry=registry,
                decomposer=ScriptedGoalDecomposer(
                    {
                        first_question: financial_gap_decomposition(first_question),
                        second_question: financial_by_year_decomposition(second_question),
                    }
                ),
                memory=memory,
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

            learned_path = skills_dir / "learned" / "candidates" / "learned_financial_metrics.json"
            learned_exists = learned_path.exists()
            learned_payload = json.loads(learned_path.read_text(encoding="utf-8")) if learned_exists else {}
            evidence_path = skills_dir / "learned" / "evidence" / "learned_financial_metrics" / "creation_trace.json"
            evidence_exists = evidence_path.exists()

        self.assertEqual(first.source, "query_synthesis_ok")
        self.assertTrue(learned_exists)
        self.assertTrue(evidence_exists)
        self.assertEqual(learned_payload["status"], "candidate")
        self.assertIn("metadata_dependency_contract", learned_payload["implementation"])
        self.assertEqual(
            learned_payload["implementation"]["metadata_dependency_contract"][0]["object"],
            "РегистрНакопления.ВыручкаИСебестоимостьПродаж",
        )
        self.assertEqual(learned_payload["implementation"]["evidence"]["successful_runs"], 1)
        self.assertFalse(learned_payload["implementation"]["evidence"]["human_confirmed"])
        self.assertEqual(learned_payload["implementation"]["config_fingerprint"], "cfg")
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

    def test_learned_query_rejects_different_config_fingerprint(self) -> None:
        skill = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills").get("learned_financial_metrics")
        assert skill is not None
        skill = SkillContract.from_dict(
            {
                **skill.to_dict(),
                "implementation": {**skill.implementation, "config_fingerprint": "cfg_a"},
            }
        )

        with self.assertRaises(QueryBuildError) as exc:
            LearnedQueryBuilder().build(
                skill,
                inputs={},
                context=ConversationContext(session_id="s1", config_fingerprint="cfg_b"),
            )

        self.assertIn("cfg_a", str(exc.exception))
        self.assertIn("cfg_b", str(exc.exception))

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

    def test_postprocess_normalizes_1c_sort_direction_typos(self) -> None:
        query = (
            "ВЫБРАТЬ ПЕРВЫЕ 1 Поступление.Ссылка "
            "ИЗ Документ.ПриобретениеТоваровУслуг КАК Поступление "
            "УПОРЯДОЧИТЬ ПО Поступление.Дата УБЫВЬ"
        )

        result = postprocess_1c_query(query)

        self.assertIn("Поступление.Дата УБЫВ", result)
        self.assertNotIn("УБЫВЬ", result)

    def test_synthesis_sends_normalized_sort_direction_to_mcp(self) -> None:
        llm = ScriptedLLMClient(
            [
                discovery_response(["ПриобретениеТоваровУслуг", "закупка"]),
                query_response(
                    """
                    ВЫБРАТЬ ПЕРВЫЕ 1
                        Поступление.Ссылка КАК Ссылка
                    ИЗ
                        Документ.ПриобретениеТоваровУслуг КАК Поступление
                    ГДЕ
                        Поступление.Проведен
                    УПОРЯДОЧИТЬ ПО
                        Поступление.Дата УБЫВЬ
                    """
                ),
            ]
        )
        mcp = SequentialMcpClient(
            [
                {
                    "success": True,
                    "data": [{"Ссылка": "Приобретение товаров и услуг 0000-000019 от 16.04.2024"}],
                }
            ]
        )
        engine = QuerySynthesisEngine(
            llm_client=llm,
            metadata_provider=PurchaseDocumentMetadataProvider(),
            mcp_client=mcp,
        )

        result = engine.run(
            message="Покажи последнее приобретение",
            intent=IntentResult(
                intent_type=IntentType.DATA_QUESTION,
                business_goal="Показать последнее приобретение",
                requires_1c_data=True,
                expected_output="table",
                domain_terms=["приобретение", "последнее"],
                relevant=True,
            ),
            goal=None,
            context=ConversationContext(session_id="s1"),
            gaps=[],
        )

        self.assertTrue(result.ok)
        self.assertEqual(len(mcp.query_calls), 1)
        self.assertIn("УБЫВ", mcp.query_calls[0].query)
        self.assertNotIn("УБЫВЬ", mcp.query_calls[0].query)

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

    def test_metadata_search_terms_expand_customer_debt_vocabulary(self) -> None:
        terms = expand_metadata_search_terms(["кто нам должен за последнюю отгрузку"])

        self.assertIn("РегистрНакопления.РасчетыСКлиентами", terms)
        self.assertIn("РегистрНакопления.РасчетыСКлиентамиПоДокументам", terms)

    def test_metadata_search_terms_expand_supply_to_purchase_documents(self) -> None:
        terms = expand_metadata_search_terms(["последняя поставка", "поступление товаров"])

        self.assertIn("Документ.ПриобретениеТоваровУслуг", terms)
        self.assertIn("ПриобретениеТоваровУслуг", terms)
        self.assertIn("РасчетыСПоставщиками", terms)

    def test_metadata_search_terms_can_disable_trade_domain_pack(self) -> None:
        policy = CompositeMetadataTermExpansionPolicy.from_bot_config(
            BotInstanceConfig(bot_id="clean", domain_hint_packs=["one_c_standard"])
        )

        terms = expand_metadata_search_terms(["последняя поставка", "поступление товаров"], policy)

        self.assertNotIn("Документ.ПриобретениеТоваровУслуг", terms)
        self.assertNotIn("РасчетыСПоставщиками", terms)

    def test_metadata_collection_prioritizes_queryable_objects_before_modules(self) -> None:
        provider = RankingMetadataProvider()

        result = collect_metadata_objects(provider, search_terms=["денежные средства"], max_objects=1)

        self.assertEqual([item.full_name for item in result], ["РегистрНакопления.ДенежныеСредстваНаличные"])
        self.assertIn("Сумма", result[0].fields)

    def test_metadata_collection_tries_direct_queryable_name_for_object_terms(self) -> None:
        provider = NoisyWarehouseSearchMetadataProvider()

        result = collect_metadata_objects(provider, search_terms=["Склады"], max_objects=1)

        self.assertEqual([item.full_name for item in result], ["Справочник.Склады"])
        self.assertIn("ТипСклада", result[0].fields)
        self.assertIn("Справочник.Склады", provider.get_calls)

    def test_should_expand_metadata_for_unverified_onboarding_source(self) -> None:
        self.assertTrue(
            should_expand_metadata(
                "Источник РегистрНакопления.ДенежныеСредства найден только по эвристике onboarding "
                "и не подтвержден структурой метаданных из MCP или XML выгрузки конфигурации."
            )
        )


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


class FakeOnboardingEvidenceProvider:
    def evidence_for(self, *, search_terms: List[str], metadata_objects: List[MetadataObject]) -> Dict[str, object]:
        return {
            "available": True,
            "terms": list(search_terms),
            "query_patterns": [{"pattern_id": "evidence_query", "query": "ВЫБРАТЬ ..."}],
            "register_usage": [],
        }


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


class NoisyWarehouseSearchMetadataProvider(MetadataProvider):
    def __init__(self) -> None:
        self.get_calls: List[str] = []

    def search_objects(self, term: str) -> List[MetadataObject]:
        return [
            metadata_object_from_payload(
                {
                    "ПолноеИмя": "ОбщийМодуль.СкладыСервер",
                    "Синоним": "Склады сервер",
                }
            ),
            metadata_object_from_payload(
                {
                    "ПолноеИмя": "РегистрСведений.РетроБонусыПоставщиковСклады",
                    "Синоним": "Ретро-бонусы поставщиков: склады",
                }
            ),
        ]

    def get_object(self, full_name: str) -> MetadataObject:
        self.get_calls.append(full_name)
        if full_name == "Справочник.Склады":
            return metadata_object_from_payload(
                {
                    "ПолноеИмя": "Справочник.Склады",
                    "Синоним": "Склады",
                    "Реквизиты": [
                        {"Имя": "Ссылка", "Тип": "СправочникСсылка.Склады"},
                        {"Имя": "Наименование", "Тип": "Строка"},
                        {"Имя": "ТипСклада", "Тип": "ПеречислениеСсылка.ТипыСкладов"},
                    ],
                }
            )
        return MetadataObject(full_name=full_name)


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


class WarehouseMetadataProvider(MetadataProvider):
    def __init__(self) -> None:
        self.object = metadata_object_from_payload(
            {
                "ПолноеИмя": "Справочник.Склады",
                "Синоним": "Склады",
                "Реквизиты": [
                    {"Имя": "Ссылка", "Тип": "СправочникСсылка.Склады"},
                    {"Имя": "Наименование", "Тип": "Строка(50)"},
                    {"Имя": "ТипСклада", "Тип": "ПеречислениеСсылка.ТипыСкладов"},
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


class StockAndWarehouseMetadataProvider(MetadataProvider):
    def __init__(self) -> None:
        self.stock = metadata_object_from_payload(
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
        self.warehouse = metadata_object_from_payload(
            {
                "ПолноеИмя": "Справочник.Склады",
                "Синоним": "Склады",
                "Реквизиты": [
                    {"Имя": "Ссылка", "Тип": "СправочникСсылка.Склады"},
                    {"Имя": "Наименование", "Тип": "Строка(50)"},
                    {"Имя": "ТипСклада", "Тип": "ПеречислениеСсылка.ТипыСкладов"},
                ],
            }
        )
        self.last_requests: List[Dict[str, object]] = []

    def search_objects(self, term: str) -> List[MetadataObject]:
        self.last_requests.append({"operation": "search_objects", "term": term})
        return [self.stock, self.warehouse]

    def get_object(self, full_name: str) -> MetadataObject:
        self.last_requests.append({"operation": "get_object", "full_name": full_name})
        if full_name == "Справочник.Склады":
            return self.warehouse
        if full_name == "РегистрНакопления.ТоварыНаСкладах":
            return self.stock
        return MetadataObject(full_name=full_name)


class PurchaseDocumentMetadataProvider(MetadataProvider):
    def __init__(self) -> None:
        self.object = metadata_object_from_payload(
            {
                "ПолноеИмя": "Документ.ПриобретениеТоваровУслуг",
                "Синоним": "Приобретение товаров и услуг",
                "Реквизиты": [
                    {"Имя": "Контрагент", "Тип": "СправочникСсылка.Контрагенты"},
                    {"Имя": "СуммаДокумента", "Тип": "Число"},
                    {"Имя": "Долг", "Тип": "Число"},
                    {"Имя": "Проведен", "Тип": "Булево"},
                    {"Имя": "ПометкаУдаления", "Тип": "Булево"},
                    {"Имя": "Дата", "Тип": "Дата"},
                ],
                "СтандартныеРеквизиты": [
                    {"Имя": "Ссылка", "Тип": "ДокументСсылка.ПриобретениеТоваровУслуг"},
                    {"Имя": "Номер", "Тип": "Строка"},
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


class SalesDocumentMetadataProvider(MetadataProvider):
    def __init__(self) -> None:
        self.object = metadata_object_from_payload(
            {
                "ПолноеИмя": "Документ.РеализацияТоваровУслуг",
                "Синоним": "Реализация товаров и услуг",
                "Реквизиты": [
                    {"Имя": "Контрагент", "Тип": "СправочникСсылка.Контрагенты"},
                    {"Имя": "СуммаДокумента", "Тип": "Число"},
                    {"Имя": "Проведен", "Тип": "Булево"},
                    {"Имя": "ПометкаУдаления", "Тип": "Булево"},
                    {"Имя": "Дата", "Тип": "Дата"},
                ],
                "СтандартныеРеквизиты": [
                    {"Имя": "Ссылка", "Тип": "ДокументСсылка.РеализацияТоваровУслуг"},
                    {"Имя": "Номер", "Тип": "Строка"},
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


def discovery_response(terms: List[str]) -> Dict[str, object]:
    return {
        "metadata_search_terms": terms,
        "hypothesis": "Нужно найти регистр накопления денежных средств с остатками по кассе.",
        "draft_query": "",
    }


def query_response(query: str, params=None) -> Dict[str, object]:
    return {"query": query.strip(), "params": dict(params or {}), "limit": 10, "reasoning": "read-only balance query"}


def document_object_ref(*, guid: str, presentation: str) -> Dict[str, object]:
    return {
        "_objectRef": True,
        "УникальныйИдентификатор": guid,
        "ТипОбъекта": "ДокументСсылка.ПриобретениеТоваровУслуг",
        "Представление": presentation,
    }


def data_intent(goal: str) -> IntentResult:
    return IntentResult(
        intent_type=IntentType.DATA_QUESTION,
        business_goal=goal,
        requires_1c_data=True,
        expected_output="table",
        domain_terms=["остаток", "денежные средства"],
        relevant=True,
    )


def top_stock_by_retail_goal() -> GoalDecomposition:
    return GoalDecomposition(
        business_goal="Определить товар с максимальным остатком в розничном магазине",
        final_artifact_type="UserAnswer",
        expected_answer_type="table",
        required_artifacts=[
            ArtifactRequirement(
                name="stock_balances",
                type="StockBalanceTable",
                constraints=[
                    SemanticFilter(
                        semantic_field="warehouse_type",
                        operator="equals",
                        value="Розничный магазин",
                        raw_user_text="розничный магазин",
                    )
                ],
            ),
            ArtifactRequirement(
                name="aggregate_result",
                type="AggregateTable",
                source="question",
                constraints=[
                    SemanticFilter(
                        semantic_field="aggregation",
                        operator="equals",
                        value="max",
                        raw_user_text="больше всего",
                    ),
                    SemanticFilter(
                        semantic_field="group_by",
                        operator="equals",
                        value="product",
                        raw_user_text="товара",
                    ),
                    SemanticFilter(
                        semantic_field="measure",
                        operator="equals",
                        value="stock_balance",
                        raw_user_text="остаток",
                    ),
                ],
            ),
        ],
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


def debt_question_decomposition(question: str) -> DecompositionResult:
    return DecompositionResult(
        intent=IntentResult(
            intent_type=IntentType.DATA_QUESTION,
            business_goal="Узнать контрагента и сумму по последней отгрузке",
            requires_1c_data=True,
            expected_output="short_answer",
            domain_terms=["отгрузка", "должен", "сумма"],
            relevant=True,
        ),
        goal=GoalDecomposition(
            business_goal="Узнать контрагента и сумму по последней отгрузке",
            final_artifact_type="UserAnswer",
            expected_answer_type="short_answer",
            required_artifacts=[
                ArtifactRequirement(name="last_shipment", type="DocumentRef"),
                ArtifactRequirement(name="debt_balance", type="DebtBalanceTable"),
            ],
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

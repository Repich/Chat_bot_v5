from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.workbench import (
    ApprovalStore,
    CalculationRecipe,
    CandidatePublisher,
    DataSourceRef,
    DraftEvidence,
    FieldMapping,
    HumanSkillDraft,
    HumanSkillDraftStore,
    MeasureRecipe,
    MetadataExplorerService,
    McpSmokeTestService,
    QueryPreviewResult,
    QueryPreviewService,
    SkillCatalogService,
    SkillLifecycleService,
    SortRecipe,
    draft_from_trace,
)
from wiicon5.knowledge.metadata import MetadataObject, MetadataProvider
from wiicon5.mcp.client import DictMcpClient
from wiicon5.models import Port, SkillContract, SkillKind, SkillStatus
from wiicon5.regression.replay import RegressionCaseReplayResult, RegressionReplayResult, save_replay_result
from wiicon5.workbench.audit import utc_now
from wiicon5.workbench.publish import skill_from_draft
from wiicon5.workbench.trace import WorkbenchTraceWriter


class WorkbenchModelTests(unittest.TestCase):
    def test_human_skill_draft_roundtrip_preserves_unknown_fields(self) -> None:
        draft = HumanSkillDraft.from_dict(
            {
                "draft_id": "draft_1",
                "title": "Остатки по складу",
                "example_questions": ["Покажи остатки по Центральному складу"],
                "data_sources": [
                    {
                        "alias": "Остатки",
                        "object_name": "РегистрНакопления.ТоварыНаСкладах.Остатки",
                        "trust": "verified",
                        "evidence": [{"source": "mcp", "reference": "metadata:ТоварыНаСкладах"}],
                    }
                ],
                "field_mappings": [
                    {
                        "role": "warehouse",
                        "source_alias": "Остатки",
                        "field_name": "Склад",
                        "confirmed": True,
                    }
                ],
                "calculation": {
                    "kind": "top_n_by_metric",
                    "source_alias": "Остатки",
                    "measures": [{"role": "stock_balance", "expression": "ВНаличииОстаток"}],
                    "limit": 10,
                },
                "consultant_note": "Проверить роль розничного склада вручную",
            }
        )
        restored = HumanSkillDraft.from_dict(draft.to_dict())

        self.assertEqual(restored.draft_id, "draft_1")
        self.assertEqual(restored.data_sources[0].evidence[0].source, "mcp")
        self.assertEqual(restored.field_mappings[0].role, "warehouse")
        self.assertEqual(restored.calculation.measures[0].expression, "ВНаличииОстаток")
        self.assertEqual(restored.extras["consultant_note"], "Проверить роль розничного склада вручную")

    def test_human_skill_draft_accepts_programmatic_nested_objects(self) -> None:
        draft = HumanSkillDraft(
            draft_id="draft_2",
            title="Топ клиентов",
            data_sources=[
                DataSourceRef(
                    alias="Продажи",
                    object_name="РегистрНакопления.ВыручкаИСебестоимостьПродаж.Обороты",
                    evidence=[DraftEvidence(source="xml", reference="AccumulationRegisters/Продажи.xml")],
                )
            ],
            field_mappings=[FieldMapping(role="customer", source_alias="Продажи", field_name="Клиент")],
            calculation=CalculationRecipe(
                kind="top_n_by_metric",
                source_alias="Продажи",
                measures=[MeasureRecipe(role="revenue", expression="ВыручкаОборот")],
            ),
        )

        payload = draft.to_dict()

        self.assertEqual(payload["data_sources"][0]["evidence"][0]["source"], "xml")
        self.assertEqual(payload["calculation"]["measures"][0]["role"], "revenue")


class WorkbenchStoreTests(unittest.TestCase):
    def test_store_creates_draft_under_bot_instance_and_writes_audit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot_instances" / "client_a"
            store = HumanSkillDraftStore(bot_instance_root=bot, bot_id="client_a")

            draft = store.new_draft(
                title="Остатки по складу",
                description="Показывает остатки по выбранному складу",
                example_questions=["Покажи остатки по Центральному складу"],
                actor="consultant",
            )
            restored = store.get_draft(draft.draft_id)
            events = store.audit.read()

        self.assertIsNotNone(restored)
        self.assertEqual(restored.title if restored else "", "Остатки по складу")
        self.assertTrue(draft.draft_id)
        self.assertEqual(events[0].event_type, "workbench.draft.created")
        self.assertEqual(events[0].bot_id, "client_a")
        self.assertEqual(events[0].actor, "consultant")
        self.assertEqual(events[0].object_id, draft.draft_id)
        self.assertTrue(events[0].after_hash)

    def test_store_update_preserves_creation_fields_and_records_before_after_hashes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot_instances" / "client_a"
            store = HumanSkillDraftStore(bot_instance_root=bot, bot_id="client_a")

            created = store.new_draft(title="Список номенклатуры", actor="author")
            updated = store.update_draft(
                created.draft_id,
                {"description": "Ищет номенклатуру по пользовательскому условию"},
                actor="editor",
            )
            events = store.audit.read()

        self.assertEqual(updated.created_at, created.created_at)
        self.assertEqual(updated.created_by, "author")
        self.assertEqual(updated.updated_by, "editor")
        self.assertEqual(updated.description, "Ищет номенклатуру по пользовательскому условию")
        self.assertEqual(events[-1].event_type, "workbench.draft.updated")
        self.assertTrue(events[-1].before_hash)
        self.assertTrue(events[-1].after_hash)
        self.assertNotEqual(events[-1].before_hash, events[-1].after_hash)

    def test_store_skips_corrupt_json_when_listing_drafts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot_instances" / "client_a"
            store = HumanSkillDraftStore(bot_instance_root=bot, bot_id="client_a")
            draft = store.new_draft(title="Корректный черновик")
            corrupt = bot / "workbench" / "drafts" / "broken.json"
            corrupt.write_text("{not json", encoding="utf-8")

            drafts = store.list_drafts()

        self.assertEqual([item.draft_id for item in drafts], [draft.draft_id])

    def test_store_uses_distinct_ids_for_duplicate_titles(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot_instances" / "client_a"
            store = HumanSkillDraftStore(bot_instance_root=bot, bot_id="client_a")

            first = store.new_draft(title="Остатки")
            second = store.new_draft(title="Остатки")
            paths = sorted((bot / "workbench" / "drafts").glob("*.json"))

        self.assertNotEqual(first.draft_id, second.draft_id)
        self.assertTrue(first.draft_id.startswith("draft_"))
        self.assertTrue(first.draft_id.isascii())
        self.assertEqual(len(paths), 2)

    def test_store_delete_removes_file_and_audits_event(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot_instances" / "client_a"
            store = HumanSkillDraftStore(bot_instance_root=bot, bot_id="client_a")
            draft = store.new_draft(title="Удаляемый")

            deleted = store.delete_draft(draft.draft_id, actor="admin")
            restored = store.get_draft(draft.draft_id)
            events = store.audit.read()

        self.assertTrue(deleted)
        self.assertIsNone(restored)
        self.assertEqual(events[-1].event_type, "workbench.draft.deleted")
        self.assertEqual(events[-1].actor, "admin")


class SkillCatalogServiceTests(unittest.TestCase):
    def test_catalog_lists_global_and_bot_specific_skill_contracts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            global_skills = root / "skills"
            bot = root / "bot_instances" / "client_a"
            write_skill(global_skills / "atomic" / "data" / "global_stock.json", skill_contract("global_stock"))
            write_skill(
                bot / "skills" / "candidates" / "bot_cash.json",
                skill_contract("bot_cash", status=SkillStatus.CANDIDATE),
            )
            (global_skills / "not_a_skill.json").write_text('{"hello": "world"}', encoding="utf-8")

            snapshot = SkillCatalogService(global_skills_dir=global_skills, bot_instance_root=bot).snapshot()
            payload = snapshot.to_dict()

        self.assertEqual(payload["summary"]["total"], 2)
        self.assertEqual(payload["summary"]["by_source"]["global_atomic"], 1)
        self.assertEqual(payload["summary"]["by_source"]["bot_candidate"], 1)
        self.assertEqual(snapshot.get("bot_cash").skill.status, SkillStatus.CANDIDATE)
        self.assertFalse(snapshot.get("bot_cash").runtime_active_by_default)

    def test_catalog_reports_broken_skill_json_without_stopping_scan(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            global_skills = root / "skills"
            bot = root / "bot_instances" / "client_a"
            write_skill(global_skills / "atomic" / "data" / "valid.json", skill_contract("valid"))
            broken = global_skills / "atomic" / "data" / "broken.json"
            broken.parent.mkdir(parents=True, exist_ok=True)
            broken.write_text("{not json", encoding="utf-8")

            snapshot = SkillCatalogService(global_skills_dir=global_skills, bot_instance_root=bot).snapshot()

        self.assertEqual([item.skill.skill_id for item in snapshot.items], ["valid"])
        self.assertEqual(len(snapshot.errors), 1)
        self.assertIn("broken.json", snapshot.errors[0].path)


class MetadataExplorerServiceTests(unittest.TestCase):
    def test_metadata_explorer_returns_confirmed_and_hint_fields(self) -> None:
        provider = StaticMetadataProvider(
            [
                MetadataObject(
                    full_name="Справочник.Склады",
                    synonym="Склады",
                    fields=["Ссылка", "Наименование", "ТипСклада"],
                    field_details={
                        "Ссылка": {"name": "Ссылка", "_category": "standard_attribute", "_source": "mcp", "_trust": "verified"},
                        "Наименование": {
                            "name": "Наименование",
                            "_category": "standard_attribute",
                            "_source": "mcp",
                            "_trust": "verified",
                        },
                        "ТипСклада": {
                            "name": "ТипСклада",
                            "_category": "attribute",
                            "_source": "onboarding_index",
                            "_trust": "hint",
                            "type": "ПеречислениеСсылка.ТипыСкладов",
                        },
                    },
                    raw={"_source": "mcp", "_trust": "verified", "kind": "Справочник"},
                )
            ]
        )

        service = MetadataExplorerService(provider=provider)
        result = service.search("склад")
        details = service.get_object("Справочник.Склады")

        self.assertTrue(result["available"])
        self.assertEqual(result["objects"][0]["full_name"], "Справочник.Склады")
        fields = {item["name"]: item for item in details["object"]["fields"]}
        hints = {item["name"]: item for item in details["object"]["field_hints"]}
        all_fields = {item["name"]: item for item in details["object"]["all_fields"]}
        self.assertTrue(fields["Ссылка"]["confirmed"])
        self.assertFalse(hints["ТипСклада"]["confirmed"])
        self.assertEqual(hints["ТипСклада"]["source"], "onboarding_index")
        self.assertIn("ТипСклада", all_fields)


class TraceDraftImportTests(unittest.TestCase):
    def test_trace_import_creates_human_draft_with_query_evidence(self) -> None:
        with TemporaryDirectory() as temp_dir:
            trace = Path(temp_dir) / "runs" / "agent_001"
            write_trace(
                trace,
                question="Покажи товар с самым большим остатком",
                query="""
                ВЫБРАТЬ ПЕРВЫЕ 1
                    Остатки.Номенклатура КАК Номенклатура,
                    Остатки.ВНаличииОстаток КАК Количество
                ИЗ
                    РегистрНакопления.ТоварыНаСкладах.Остатки(&Период) КАК Остатки
                УПОРЯДОЧИТЬ ПО
                    Количество УБЫВ
                """,
            )

            draft = draft_from_trace(trace)

        self.assertEqual(draft.title, "Покажи товар с самым большим остатком")
        self.assertEqual(draft.source_kind, "trace")
        self.assertEqual(draft.data_sources[0].alias, "Остатки")
        self.assertEqual(draft.data_sources[0].trust, "verified")
        self.assertEqual(draft.calculation.kind, "trace_query")
        self.assertIn("РегистрНакопления.ТоварыНаСкладах", draft.calculation.raw["query"])
        mappings = {item.field_name: item for item in draft.field_mappings}
        self.assertTrue(mappings["Номенклатура"].confirmed)
        self.assertTrue(mappings["ВНаличииОстаток"].confirmed)
        self.assertEqual(draft.presentation.columns, ["Номенклатура", "Количество"])


class QueryPreviewServiceTests(unittest.TestCase):
    def test_preview_builds_read_only_top_n_by_metric_query(self) -> None:
        draft = top_n_stock_draft()

        preview = verified_preview_service().preview(draft)

        self.assertTrue(preview.ok, preview.to_dict())
        self.assertIn("ВЫБРАТЬ ПЕРВЫЕ 5", preview.query)
        self.assertIn("РегистрНакопления.ТоварыНаСкладах.Остатки() КАК Остатки", preview.query)
        self.assertIn("СУММА(Остатки.ВНаличииОстаток) КАК Количество", preview.query)
        self.assertIn("СГРУППИРОВАТЬ ПО", preview.query)
        self.assertEqual(preview.issues, [])

    def test_preview_uses_real_metadata_lookup_when_available(self) -> None:
        draft = top_n_stock_draft()
        metadata = MetadataObject(
            full_name="РегистрНакопления.ТоварыНаСкладах",
            fields=["Номенклатура", "Количество"],
            field_details={
                "Номенклатура": {
                    "name": "Номенклатура",
                    "_category": "dimension",
                    "_source": "metadata_xml",
                    "_trust": "verified",
                },
                "Количество": {
                    "name": "Количество",
                    "_category": "resource",
                    "_source": "metadata_xml",
                    "_trust": "verified",
                },
            },
            raw={"_source": "metadata_xml", "_trust": "verified"},
        )

        preview = QueryPreviewService(metadata_lookup=lambda _: metadata).preview(draft)

        self.assertFalse(preview.ok)
        self.assertIn("field_not_confirmed_by_metadata", [issue.code for issue in preview.issues])

    def test_preview_does_not_trust_draft_confirmed_fields_without_metadata(self) -> None:
        draft = top_n_stock_draft()

        preview = QueryPreviewService().preview(draft)

        self.assertFalse(preview.ok)
        self.assertIn("source_not_confirmed_by_verified_metadata", [issue.code for issue in preview.issues])

    def test_preview_reports_actionable_issue_for_unsupported_recipe(self) -> None:
        draft = HumanSkillDraft(title="Unsupported draft", calculation=CalculationRecipe(kind="unknown_recipe"))

        preview = QueryPreviewService().preview(draft)

        self.assertFalse(preview.ok)
        self.assertEqual(preview.issues[0].code, "unsupported_calculation_kind")

    def test_preview_can_review_trace_query_with_verified_metadata(self) -> None:
        draft = HumanSkillDraft(
            title="Trace fixed query",
            data_sources=[
                DataSourceRef(alias="Остатки", object_name="РегистрНакопления.ТоварыНаСкладах.Остатки")
            ],
            calculation=CalculationRecipe(
                kind="trace_query",
                raw={
                    "query": """
                    ВЫБРАТЬ ПЕРВЫЕ 5
                        Остатки.Номенклатура КАК Номенклатура,
                        Остатки.ВНаличииОстаток КАК Количество
                    ИЗ
                        РегистрНакопления.ТоварыНаСкладах.Остатки() КАК Остатки
                    УПОРЯДОЧИТЬ ПО
                        Количество УБЫВ
                    """,
                    "params": {},
                    "limit": 5,
                },
            ),
        )

        preview = verified_preview_service().preview(draft)

        self.assertTrue(preview.ok, preview.to_dict())
        self.assertIn("РегистрНакопления.ТоварыНаСкладах.Остатки()", preview.query)


class McpSmokeTestServiceTests(unittest.TestCase):
    def test_smoke_runs_preview_query_through_mcp_and_persists_result(self) -> None:
        with TemporaryDirectory() as temp_dir:
            draft = HumanSkillDraft.from_dict({**top_n_stock_draft().to_dict(), "draft_id": "draft_stock"})
            mcp = DictMcpClient({"success": True, "data": [{"Номенклатура": "Телевизор", "Количество": 10}]})
            service = McpSmokeTestService(
                bot_instance_root=Path(temp_dir) / "bot",
                mcp_client=mcp,
                preview_service=verified_preview_service(),
            )

            result = service.run(draft)
            result_path_exists = Path(result.path).exists()

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(result.row_count, 1)
        self.assertEqual(mcp.query_calls[0].limit, 5)
        self.assertIn("ВЫБРАТЬ ПЕРВЫЕ 5", mcp.query_calls[0].query)
        self.assertTrue(result.draft_hash)
        self.assertTrue(result.preview_hash)
        self.assertTrue(result_path_exists)

    def test_smoke_requires_parameter_values_before_mcp(self) -> None:
        with TemporaryDirectory() as temp_dir:
            draft = HumanSkillDraft.from_dict({**filtered_stock_draft().to_dict(), "draft_id": "draft_stock_filtered"})
            mcp = DictMcpClient({"success": True, "data": [{"Номенклатура": "Телевизор", "Количество": 10}]})
            service = McpSmokeTestService(
                bot_instance_root=Path(temp_dir) / "bot",
                mcp_client=mcp,
                preview_service=filtered_preview_service(),
            )

            missing = service.run(draft)
            ok = service.run(draft, params={"Склад": "Основной"})

        self.assertFalse(missing.ok)
        self.assertEqual(missing.issues[0].code, "missing_smoke_param")
        self.assertEqual(mcp.query_calls[0].params["Склад"], "Основной")
        self.assertTrue(ok.ok, ok.to_dict())


class ApprovalStoreTests(unittest.TestCase):
    def test_approval_store_appends_decisions_and_writes_audit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot"
            draft_store = HumanSkillDraftStore(bot_instance_root=bot, bot_id="client_a")
            store = ApprovalStore(bot_instance_root=bot, bot_id="client_a", audit_log=draft_store.audit)

            rejected = store.reject("draft_stock", actor="consultant", comment="Нужно уточнить смысл показателя")
            approved = store.approve("draft_stock", actor="consultant", comment="Проверено на smoke")
            history = store.history_for_draft("draft_stock")
            latest = store.latest_candidate_approval("draft_stock")
            events = draft_store.audit.read()

        self.assertEqual(rejected.decision, "rejected")
        self.assertEqual(approved.decision, "approved")
        self.assertEqual([item.decision for item in history], ["rejected", "approved"])
        self.assertEqual(latest.approval_id if latest else "", approved.approval_id)
        self.assertEqual([item.event_type for item in events], ["workbench.approval.recorded", "workbench.approval.recorded"])
        self.assertEqual(events[-1].object_id, "draft_stock")

    def test_approval_requires_actor(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = ApprovalStore(bot_instance_root=Path(temp_dir) / "bot")

            with self.assertRaises(ValueError):
                store.approve("draft_stock", actor="", comment="Checked.")


class WorkbenchTraceWriterTests(unittest.TestCase):
    def test_trace_writer_persists_compact_json_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            writer = WorkbenchTraceWriter(bot_instance_root=Path(temp_dir) / "bot")
            run = writer.start(
                action="draft.preview",
                actor="consultant",
                object_type="human_skill_draft",
                object_id="draft_1",
                request={"secret": "x" * 3000},
            )
            path = run.write_json("query_preview", {"ok": True, "rows": [{"value": "A"}]})
            request_payload = json.loads((run.path / "request.json").read_text(encoding="utf-8"))
            preview_payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertTrue(run.run_id.startswith("workbench_draft.preview_"))
        self.assertEqual(request_payload["action"], "draft.preview")
        self.assertIn("<truncated>", request_payload["request"]["secret"])
        self.assertTrue(preview_payload["ok"])


class CandidatePublisherTests(unittest.TestCase):
    def test_publish_requires_successful_smoke_approval_and_writes_candidate_skill(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot"
            draft = HumanSkillDraft.from_dict(
                {
                    **top_n_stock_draft().to_dict(),
                    "draft_id": "draft_stock",
                    "example_questions": ["Покажи товар с самым большим остатком"],
                }
            )
            approval_store = ApprovalStore(bot_instance_root=bot)
            publisher = CandidatePublisher(
                bot_instance_root=bot,
                approval_store=approval_store,
                preview_service=verified_preview_service(),
            )
            before_smoke = publisher.publish(draft)
            mcp = DictMcpClient({"success": True, "data": [{"Номенклатура": "Телевизор", "Количество": 10}]})
            smoke = McpSmokeTestService(
                bot_instance_root=bot,
                mcp_client=mcp,
                preview_service=verified_preview_service(),
            ).run(draft)
            before_approval = publisher.publish(draft)
            approval = approval_store.approve(
                draft.draft_id,
                actor="consultant",
                comment="Sample reviewed.",
                smoke_id=smoke.smoke_id,
                draft_hash=smoke.draft_hash,
                preview_hash=smoke.preview_hash,
                query_hash=smoke.query_hash,
            )

            published = publisher.publish(draft)
            skill_path_exists = Path(published.path).exists()
            evidence_path_exists = Path(published.evidence_path).exists()

        self.assertFalse(before_smoke.ok)
        self.assertEqual([item.code for item in before_smoke.issues][-2:], ["missing_successful_smoke", "missing_human_approval"])
        self.assertFalse(before_approval.ok)
        self.assertEqual(before_approval.issues[-1].code, "missing_human_approval")
        self.assertEqual(approval.decision, "approved")
        self.assertTrue(published.ok, published.to_dict())
        self.assertEqual(published.skill.status, SkillStatus.CANDIDATE)
        self.assertEqual(published.skill.implementation_strategy, "learned_query")
        self.assertEqual(published.skill.implementation["kind"], "fixed_query")
        self.assertEqual(published.skill.outputs[0].type, "TopNMetricTable")
        self.assertEqual(published.approval.approval_id, approval.approval_id)
        self.assertTrue(skill_path_exists)
        self.assertTrue(evidence_path_exists)

    def test_query_synthesis_draft_publishes_as_parameterized_lookup_when_params_match_constraints(self) -> None:
        draft = HumanSkillDraft.from_dict(
            {
                "draft_id": "draft_price",
                "title": "Получить цены с типом себестоимость по курткам",
                "description": "Получить цены по номенклатуре и виду цены.",
                "example_questions": ["Покажи цены с типом себестоимость по курткам"],
                "calculation": {
                    "kind": "trace_query",
                    "raw": {
                        "query": price_lookup_query(),
                        "params": {"ТоварПоиск": "%куртк%", "ВидЦеныПоиск": "%себестоимость%"},
                        "limit": 100,
                    },
                },
                "presentation": {"columns": ["Номенклатура", "ВидЦены", "Цена"]},
                "source_kind": "query_synthesis_candidate",
                "source_trace": "/runs/agent_1",
                "synthesis_candidate": {
                    "candidate_id": "syn_price",
                    "payload": {
                        "goal": {
                            "business_goal": "Показать цены с типом себестоимость по курткам",
                            "final_artifact_type": "UserAnswer",
                            "required_artifacts": [
                                {
                                    "name": "prices",
                                    "type": "PriceTable",
                                    "constraints": [
                                        {
                                            "semantic_field": "product",
                                            "operator": "contains",
                                            "value": "куртка",
                                            "raw_user_text": "курткам",
                                        },
                                        {
                                            "semantic_field": "price_type",
                                            "operator": "equals",
                                            "value": "себестоимость",
                                            "raw_user_text": "себестоимость",
                                        },
                                    ],
                                }
                            ],
                        }
                    },
                },
            }
        )
        preview = QueryPreviewResult(
            ok=True,
            query=price_lookup_query(),
            params={"ТоварПоиск": "%куртк%", "ВидЦеныПоиск": "%себестоимость%"},
            limit=100,
            review={
                "sources": [
                    {"object_full_name": "РегистрСведений.ЦеныНоменклатуры"},
                    {"object_full_name": "Справочник.Номенклатура"},
                    {"object_full_name": "Справочник.ВидыЦен"},
                ]
            },
        )

        skill = skill_from_draft(draft, preview)

        self.assertEqual(skill.implementation_strategy, "learned_query")
        self.assertEqual(skill.implementation["kind"], "parameterized_lookup_query")
        self.assertEqual(skill.outputs[0].type, "PriceTable")
        self.assertEqual(set(skill.supported_filter_roles), {"product", "price_type"})
        self.assertEqual(skill.inputs[0].type, "SemanticFilterList")
        self.assertEqual(
            {item["semantic_field"]: item["parameter"] for item in skill.implementation["parameter_bindings"]},
            {"product": "ТоварПоиск", "price_type": "ВидЦеныПоиск"},
        )

    def test_publish_rejects_latest_rejected_approval(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot"
            draft = HumanSkillDraft.from_dict(
                {
                    **top_n_stock_draft().to_dict(),
                    "draft_id": "draft_stock",
                    "example_questions": ["Покажи товар с самым большим остатком"],
                }
            )
            approval_store = ApprovalStore(bot_instance_root=bot)
            mcp = DictMcpClient({"success": True, "data": [{"Номенклатура": "Телевизор", "Количество": 10}]})
            McpSmokeTestService(
                bot_instance_root=bot,
                mcp_client=mcp,
                preview_service=verified_preview_service(),
            ).run(draft)
            approval_store.reject(draft.draft_id, actor="consultant", comment="Wrong business meaning.")

            published = CandidatePublisher(
                bot_instance_root=bot,
                approval_store=approval_store,
                preview_service=verified_preview_service(),
            ).publish(draft)

        self.assertFalse(published.ok)
        self.assertEqual(published.issues[-1].code, "approval_rejected")

    def test_publish_rejects_smoke_and_approval_from_old_draft_hash(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot"
            draft = HumanSkillDraft.from_dict(
                {
                    **top_n_stock_draft().to_dict(),
                    "draft_id": "draft_stock",
                    "example_questions": ["Покажи товар с самым большим остатком"],
                }
            )
            changed = HumanSkillDraft.from_dict({**draft.to_dict(), "description": "Changed after smoke."})
            approval_store = ApprovalStore(bot_instance_root=bot)
            mcp = DictMcpClient({"success": True, "data": [{"Номенклатура": "Телевизор", "Количество": 10}]})
            smoke = McpSmokeTestService(
                bot_instance_root=bot,
                mcp_client=mcp,
                preview_service=verified_preview_service(),
            ).run(draft)
            approval_store.approve(
                draft.draft_id,
                actor="consultant",
                comment="Sample reviewed.",
                smoke_id=smoke.smoke_id,
                draft_hash=smoke.draft_hash,
                preview_hash=smoke.preview_hash,
                query_hash=smoke.query_hash,
            )

            published = CandidatePublisher(
                bot_instance_root=bot,
                approval_store=approval_store,
                preview_service=verified_preview_service(),
            ).publish(changed)

        self.assertFalse(published.ok)
        issue_codes = [issue.code for issue in published.issues]
        self.assertIn("missing_successful_smoke", issue_codes)
        self.assertIn("approval_draft_hash_mismatch", issue_codes)


class SkillLifecycleWorkbenchTests(unittest.TestCase):
    def test_lifecycle_promotes_candidate_to_verified_with_evidence(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot"
            draft = HumanSkillDraft.from_dict(
                {
                    **top_n_stock_draft().to_dict(),
                    "draft_id": "draft_stock",
                    "example_questions": ["Покажи товар с самым большим остатком"],
                }
            )
            approval_store = ApprovalStore(bot_instance_root=bot)
            mcp = DictMcpClient({"success": True, "data": [{"Номенклатура": "Телевизор", "Количество": 10}]})
            smoke = McpSmokeTestService(
                bot_instance_root=bot,
                mcp_client=mcp,
                preview_service=verified_preview_service(),
            ).run(draft)
            approval_store.approve(
                draft.draft_id,
                actor="consultant",
                comment="Sample reviewed.",
                smoke_id=smoke.smoke_id,
                draft_hash=smoke.draft_hash,
                preview_hash=smoke.preview_hash,
                query_hash=smoke.query_hash,
                regression_case_id="reg_stock_top",
            )
            published = CandidatePublisher(
                bot_instance_root=bot,
                approval_store=approval_store,
                preview_service=verified_preview_service(),
            ).publish(draft)
            before_replay = SkillLifecycleService(bot_instance_root=bot).promote(
                published.skill.skill_id,
                actor="consultant",
                reason="Regression case id exists but has not been replayed yet.",
            )
            write_successful_replay(bot, "reg_stock_top")

            result = SkillLifecycleService(bot_instance_root=bot).promote(
                published.skill.skill_id,
                actor="consultant",
                reason="Regression case covers the accepted smoke result.",
            )
            snapshot = SkillCatalogService(global_skills_dir=Path(temp_dir) / "global", bot_instance_root=bot).snapshot()
            item = snapshot.get(published.skill.skill_id)
            events = SkillLifecycleService(bot_instance_root=bot).audit.read()

        self.assertFalse(before_replay.ok)
        self.assertIn("missing_successful_regression_replay", [issue.code for issue in before_replay.issues])
        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(result.before_status, "candidate")
        self.assertEqual(result.after_status, "verified")
        self.assertEqual(result.skill.status, SkillStatus.VERIFIED)
        self.assertTrue(result.path.endswith("/skills/verified/workbench_draft_stock.json"))
        self.assertFalse(Path(result.previous_path).exists())
        self.assertIsNotNone(item)
        self.assertEqual(item.source_kind if item else "", "bot_verified")
        self.assertTrue(item.runtime_active_by_default if item else False)
        self.assertIn("workbench.skill.promoted", [event.event_type for event in events])

    def test_lifecycle_blocks_unsafe_transitions_and_supports_block_rollback(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot"
            candidate = skill_contract("manual_candidate", status=SkillStatus.CANDIDATE)
            write_skill(bot / "skills" / "candidates" / "manual_candidate.json", candidate)
            service = SkillLifecycleService(bot_instance_root=bot)

            direct_stable = service.promote(
                "manual_candidate",
                actor="consultant",
                reason="Trying to skip verification.",
                target_status="stable",
                admin_approval=True,
            )
            missing_regression = service.promote(
                "manual_candidate",
                actor="consultant",
                reason="Smoke was checked.",
            )
            blocked = service.block(
                "manual_candidate",
                actor="consultant",
                reason="Wrong result on live data.",
            )
            rollback_without_approval = service.rollback(
                "manual_candidate",
                actor="consultant",
                reason="Reviewed after fix.",
                target_status="candidate",
            )
            rollback = service.rollback(
                "manual_candidate",
                actor="consultant",
                reason="Reviewed after fix.",
                target_status="candidate",
                admin_approval=True,
            )

        self.assertFalse(direct_stable.ok)
        self.assertEqual(direct_stable.issues[0].code, "unsupported_transition")
        self.assertFalse(missing_regression.ok)
        self.assertIn("missing_human_approval", [issue.code for issue in missing_regression.issues])
        self.assertIn("missing_regression_case", [issue.code for issue in missing_regression.issues])
        self.assertTrue(blocked.ok, blocked.to_dict())
        self.assertEqual(blocked.after_status, "blocked")
        self.assertFalse(rollback_without_approval.ok)
        self.assertIn("missing_admin_approval", [issue.code for issue in rollback_without_approval.issues])
        self.assertTrue(rollback.ok, rollback.to_dict())
        self.assertEqual(rollback.after_status, "candidate")


class StaticMetadataProvider(MetadataProvider):
    def __init__(self, objects: list[MetadataObject]) -> None:
        self.objects = {item.full_name: item for item in objects}
        self.last_requests = []

    def search_objects(self, term: str) -> list[MetadataObject]:
        self.last_requests.append({"operation": "search_objects", "term": term})
        lowered = term.lower()
        return [
            item
            for item in self.objects.values()
            if lowered in item.full_name.lower() or lowered in item.synonym.lower()
        ]

    def get_object(self, full_name: str) -> MetadataObject:
        self.last_requests.append({"operation": "get_object", "full_name": full_name})
        return self.objects.get(full_name, MetadataObject(full_name=full_name))


def skill_contract(skill_id: str, *, status: SkillStatus = SkillStatus.VERIFIED) -> SkillContract:
    return SkillContract(
        skill_id=skill_id,
        version="0.1.0",
        kind=SkillKind.DATA,
        status=status,
        description=f"Test skill {skill_id}",
        capabilities=[skill_id],
        inputs=[Port(name="period", type="Period", required=False)],
        outputs=[Port(name="rows", type="TypedTable")],
        implementation_strategy="test",
    )


def write_skill(path: Path, contract: SkillContract) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(contract.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def write_successful_replay(bot: Path, case_id: str) -> None:
    ts = utc_now()
    save_replay_result(
        RegressionReplayResult(
            run_id=f"run_{case_id}",
            ok=True,
            count=1,
            passed=1,
            failed=0,
            started_at=ts,
            finished_at=ts,
            case_results=[
                RegressionCaseReplayResult(
                    case_id=case_id,
                    question="Покажи товар с самым большим остатком",
                    ok=True,
                    source="skill_execution_ok",
                    artifact_type="TypedTable",
                )
            ],
        ),
        bot / "regression" / "results",
    )


def top_n_stock_draft() -> HumanSkillDraft:
    return HumanSkillDraft(
        title="Топ остатков",
        data_sources=[
            DataSourceRef(
                alias="Остатки",
                object_name="РегистрНакопления.ТоварыНаСкладах.Остатки",
                trust="verified",
            )
        ],
        field_mappings=[
            FieldMapping(role="product", source_alias="Остатки", field_name="Номенклатура", confirmed=True),
            FieldMapping(role="quantity", source_alias="Остатки", field_name="ВНаличииОстаток", confirmed=True),
        ],
        calculation=CalculationRecipe(
            kind="top_n_by_metric",
            source_alias="Остатки",
            group_by=["product"],
            measures=[MeasureRecipe(role="stock_balance", expression="quantity", aggregate="sum", label="Количество")],
            sort=[SortRecipe(field="Количество", direction="desc")],
            limit=5,
        ),
    )


def top_n_stock_metadata() -> MetadataObject:
    return MetadataObject(
        full_name="РегистрНакопления.ТоварыНаСкладах",
        fields=["Номенклатура", "ВНаличии"],
        field_details={
            "Номенклатура": {
                "name": "Номенклатура",
                "_category": "dimension",
                "_source": "metadata_xml",
                "_trust": "verified",
            },
            "ВНаличии": {
                "name": "ВНаличии",
                "_category": "resource",
                "_source": "metadata_xml",
                "_trust": "verified",
            },
        },
        raw={"_source": "metadata_xml", "_trust": "verified"},
    )


def verified_preview_service() -> QueryPreviewService:
    return QueryPreviewService(metadata_lookup=lambda _: top_n_stock_metadata())


def filtered_stock_draft() -> HumanSkillDraft:
    return HumanSkillDraft.from_dict(
        {
            **top_n_stock_draft().to_dict(),
            "field_mappings": [
                *[item.to_dict() for item in top_n_stock_draft().field_mappings],
                {"role": "warehouse", "source_alias": "Остатки", "field_name": "Склад", "confirmed": True},
            ],
            "calculation": {
                **top_n_stock_draft().calculation.to_dict(),
                "filters": [
                    {
                        "role": "warehouse",
                        "operator": "equals",
                        "value_source": "input",
                        "parameter": "Склад",
                        "required": True,
                    }
                ],
            },
        }
    )


def filtered_stock_metadata() -> MetadataObject:
    base = top_n_stock_metadata()
    field_details = dict(base.field_details)
    field_details["Склад"] = {
        "name": "Склад",
        "_category": "dimension",
        "_source": "metadata_xml",
        "_trust": "verified",
    }
    return MetadataObject(
        full_name=base.full_name,
        synonym=base.synonym,
        fields=[*base.fields, "Склад"],
        field_details=field_details,
        raw=dict(base.raw),
    )


def filtered_preview_service() -> QueryPreviewService:
    return QueryPreviewService(metadata_lookup=lambda _: filtered_stock_metadata())


def write_trace(trace: Path, *, question: str, query: str) -> None:
    (trace / "input").mkdir(parents=True, exist_ok=True)
    (trace / "intent").mkdir(parents=True, exist_ok=True)
    (trace / "query_synthesis").mkdir(parents=True, exist_ok=True)
    (trace / "result").mkdir(parents=True, exist_ok=True)
    (trace / "input" / "user_message.json").write_text(
        json.dumps({"message": question}, ensure_ascii=False),
        encoding="utf-8",
    )
    (trace / "intent" / "goal_decomposition.json").write_text(
        json.dumps(
            {
                "business_goal": question,
                "final_artifact_type": "TypedTable",
                "expected_answer_type": "table",
                "required_artifacts": [{"name": "stock", "type": "StockBalanceTable"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    synthesis = {
        "source": "skill_gap",
        "synthesis": {
            "ok": True,
            "final_artifact": {
                "name": "answer",
                "type": "TypedTable",
                "value": {
                    "columns": ["Номенклатура", "Количество"],
                    "rows": [{"Номенклатура": "Телевизор", "Количество": 10}],
                },
            },
            "trace": {
                "metadata_objects": [
                    {
                        "full_name": "РегистрНакопления.ТоварыНаСкладах",
                        "source": "metadata_xml",
                        "trust": "verified",
                        "fields": ["Номенклатура", "Склад", "ВНаличииОстаток"],
                        "field_hints": [],
                    }
                ],
                "final_query": {"query": query, "params": {"Период": "2026-07-05T00:00:00"}, "limit": 1},
            },
        },
    }
    (trace / "query_synthesis" / "result.json").write_text(
        json.dumps(synthesis, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (trace / "result" / "result.json").write_text(
        json.dumps({"source": "query_synthesis_ok", "message": "Найден результат."}, ensure_ascii=False),
        encoding="utf-8",
    )


def price_lookup_query() -> str:
    return (
        "ВЫБРАТЬ\n"
        "    Ном.Наименование КАК Номенклатура,\n"
        "    ВЦ.Наименование КАК ВидЦены,\n"
        "    РЦ.Цена КАК Цена\n"
        "ИЗ\n"
        "    РегистрСведений.ЦеныНоменклатуры КАК РЦ\n"
        "        ВНУТРЕННЕЕ СОЕДИНЕНИЕ Справочник.Номенклатура КАК Ном\n"
        "        ПО РЦ.Номенклатура = Ном.Ссылка\n"
        "        ВНУТРЕННЕЕ СОЕДИНЕНИЕ Справочник.ВидыЦен КАК ВЦ\n"
        "        ПО РЦ.ВидЦены = ВЦ.Ссылка\n"
        "ГДЕ\n"
        "    Ном.Наименование ПОДОБНО &ТоварПоиск\n"
        "    И ВЦ.Наименование ПОДОБНО &ВидЦеныПоиск\n"
        "УПОРЯДОЧИТЬ ПО\n"
        "    Ном.Наименование,\n"
        "    ВЦ.Наименование"
    )


if __name__ == "__main__":
    unittest.main()

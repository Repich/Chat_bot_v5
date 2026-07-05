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
    QueryPreviewService,
    SkillCatalogService,
    SortRecipe,
    draft_from_trace,
)
from wiicon5.knowledge.metadata import MetadataObject, MetadataProvider
from wiicon5.mcp.client import DictMcpClient
from wiicon5.models import Port, SkillContract, SkillKind, SkillStatus


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
        self.assertTrue(fields["Ссылка"]["confirmed"])
        self.assertFalse(fields["ТипСклада"]["confirmed"])
        self.assertEqual(fields["ТипСклада"]["source"], "onboarding_index")


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

        preview = QueryPreviewService().preview(draft)

        self.assertTrue(preview.ok, preview.to_dict())
        self.assertIn("ВЫБРАТЬ ПЕРВЫЕ 5", preview.query)
        self.assertIn("РегистрНакопления.ТоварыНаСкладах.Остатки() КАК Остатки", preview.query)
        self.assertIn("СУММА(Остатки.ВНаличииОстаток) КАК Количество", preview.query)
        self.assertIn("СГРУППИРОВАТЬ ПО", preview.query)
        self.assertEqual(preview.issues, [])

    def test_preview_reports_actionable_issue_for_unsupported_recipe(self) -> None:
        draft = HumanSkillDraft(title="Trace draft", calculation=CalculationRecipe(kind="trace_query"))

        preview = QueryPreviewService().preview(draft)

        self.assertFalse(preview.ok)
        self.assertEqual(preview.issues[0].code, "unsupported_calculation_kind")


class McpSmokeTestServiceTests(unittest.TestCase):
    def test_smoke_runs_preview_query_through_mcp_and_persists_result(self) -> None:
        with TemporaryDirectory() as temp_dir:
            draft = HumanSkillDraft.from_dict({**top_n_stock_draft().to_dict(), "draft_id": "draft_stock"})
            mcp = DictMcpClient({"success": True, "data": [{"Номенклатура": "Телевизор", "Количество": 10}]})
            service = McpSmokeTestService(bot_instance_root=Path(temp_dir) / "bot", mcp_client=mcp)

            result = service.run(draft)
            result_path_exists = Path(result.path).exists()

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(result.row_count, 1)
        self.assertEqual(mcp.query_calls[0].limit, 5)
        self.assertIn("ВЫБРАТЬ ПЕРВЫЕ 5", mcp.query_calls[0].query)
        self.assertTrue(result_path_exists)


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
            publisher = CandidatePublisher(bot_instance_root=bot, approval_store=approval_store)
            before_smoke = publisher.publish(draft)
            mcp = DictMcpClient({"success": True, "data": [{"Номенклатура": "Телевизор", "Количество": 10}]})
            McpSmokeTestService(bot_instance_root=bot, mcp_client=mcp).run(draft)
            before_approval = publisher.publish(draft)
            approval = approval_store.approve(draft.draft_id, actor="consultant", comment="Sample reviewed.")

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
        self.assertEqual(published.approval.approval_id, approval.approval_id)
        self.assertTrue(skill_path_exists)
        self.assertTrue(evidence_path_exists)

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
            McpSmokeTestService(bot_instance_root=bot, mcp_client=mcp).run(draft)
            approval_store.reject(draft.draft_id, actor="consultant", comment="Wrong business meaning.")

            published = CandidatePublisher(bot_instance_root=bot, approval_store=approval_store).publish(draft)

        self.assertFalse(published.ok)
        self.assertEqual(published.issues[-1].code, "approval_rejected")


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


if __name__ == "__main__":
    unittest.main()

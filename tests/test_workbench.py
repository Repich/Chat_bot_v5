from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.workbench import (
    CalculationRecipe,
    DataSourceRef,
    DraftEvidence,
    FieldMapping,
    HumanSkillDraft,
    HumanSkillDraftStore,
    MeasureRecipe,
)


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


if __name__ == "__main__":
    unittest.main()

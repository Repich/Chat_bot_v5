from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wiicon5.instance_knowledge.importers import JsonKnowledgeImporter, html_to_markdown
from wiicon5.instance_knowledge.index import InstanceKnowledgeBase
from wiicon5.instance_knowledge.models import KnowledgePage
from wiicon5.instance_knowledge.storage import KnowledgeRepository
from wiicon5.instance_knowledge.sync import KnowledgeSyncService, knowledge_auth_headers


class InstanceKnowledgeTests(unittest.TestCase):
    def test_html_converter_preserves_headings_lists_and_table_content(self) -> None:
        result = html_to_markdown(
            "<h2>Оформление требования</h2><p>Откройте документ.</p>"
            "<ul><li>Заполните склад</li><li>Проведите документ</li></ul>"
            "<table><tr><th>Ошибка</th><th>Причина</th></tr><tr><td>Нет статуса</td><td>Не заполнен код</td></tr></table>"
        )
        self.assertIn("## Оформление требования", result)
        self.assertIn("- Заполните склад", result)
        self.assertIn("Ошибка", result)
        self.assertIn("Не заполнен код", result)

    def test_json_confluence_export_keeps_hierarchy_and_provenance(self) -> None:
        payload = {
            "pages": [
                {
                    "id": "20",
                    "title": "Создание требования",
                    "body": {"storage": {"value": "<h1>Инструкция</h1><p>Создайте требование.</p>"}},
                    "ancestors": [{"id": "10", "title": "1C WIIC"}],
                    "version": {"number": 7, "when": "2026-07-01T10:00:00Z"},
                    "space": {"key": "BRIT"},
                    "_links": {"webui": "/pages/viewpage.action?pageId=20"},
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "export.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            pages = JsonKnowledgeImporter().load(path, base_url="https://bwiki.example")
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].parent_id, "10")
        self.assertEqual(pages[0].ancestor_titles, ["1C WIIC"])
        self.assertEqual(pages[0].version, 7)
        self.assertEqual(pages[0].space_key, "BRIT")
        self.assertEqual(pages[0].source_url, "https://bwiki.example/pages/viewpage.action?pageId=20")

    def test_sync_creates_immutable_snapshots_and_supports_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = KnowledgeRepository(root / "knowledge")
            first_export = root / "first.json"
            second_export = root / "second.json"
            first_export.write_text(
                json.dumps({"pages": [page_payload("1", "ПВЗ", "Старый адрес ПВЗ")]}), encoding="utf-8"
            )
            second_export.write_text(
                json.dumps(
                    {
                        "pages": [
                            page_payload("1", "ПВЗ", "Новый адрес ПВЗ"),
                            page_payload("2", "Требования", "Правила создания требований"),
                        ]
                    }
                ),
                encoding="utf-8",
            )
            service = KnowledgeSyncService(
                repository=repository,
                source_kind="confluence",
                base_url="https://bwiki.example",
                root_page_id="1",
            )
            first = service.sync(input_json=first_export)
            second = service.sync(input_json=second_export)
            self.assertTrue(first.ok)
            self.assertTrue(second.ok)
            assert first.manifest is not None
            assert second.manifest is not None
            self.assertNotEqual(first.manifest.snapshot_id, second.manifest.snapshot_id)
            self.assertEqual(second.manifest.added, 1)
            self.assertEqual(second.manifest.updated, 1)
            self.assertEqual(len(repository.list_manifests()), 2)
            repository.activate(first.manifest.snapshot_id)
            self.assertEqual(repository.pages()[0].content, "Старый адрес ПВЗ")

    def test_search_uses_title_heading_content_and_reports_staleness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            export = root / "pages.json"
            export.write_text(
                json.dumps(
                    {
                        "pages": [
                            page_payload(
                                "1",
                                "Ошибки интеграции 3PL",
                                "# Успешная интеграция в 3PL\nЕсли статус не поступил, проверьте очередь обмена.",
                                updated_at="2020-01-01T00:00:00Z",
                            ),
                            page_payload("2", "Пункты самовывоза", "Адрес ПВЗ хранится в карточке пункта."),
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            repository = KnowledgeRepository(root / "knowledge")
            result = KnowledgeSyncService(
                repository=repository,
                source_kind="confluence",
                base_url="https://bwiki.example",
                root_page_id="1",
            ).sync(input_json=export)
            self.assertTrue(result.ok)
            hits = InstanceKnowledgeBase(repository, stale_after_days=365).search(
                "Почему не поступил статус успешной интеграции в 3PL?"
            )
            self.assertTrue(hits)
            self.assertEqual(hits[0].page_id, "1")
            self.assertTrue(hits[0].stale)
            self.assertIn("очередь обмена", hits[0].content)

    def test_auth_headers_prefer_bearer_and_do_not_require_credentials(self) -> None:
        self.assertEqual(knowledge_auth_headers({}), {})
        self.assertEqual(
            knowledge_auth_headers({"WIICON5_KNOWLEDGE_BEARER_TOKEN": "secret", "WIICON5_KNOWLEDGE_COOKIE": "sid=x"}),
            {"Authorization": "Bearer secret"},
        )


def page_payload(page_id: str, title: str, content: str, *, updated_at: str = "2026-07-01T00:00:00Z"):
    return {
        "page_id": page_id,
        "title": title,
        "content": content,
        "source_url": f"https://bwiki.example/pages/{page_id}",
        "source_kind": "confluence",
        "updated_at": updated_at,
        "version": 1,
    }


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from wiicon5.agent.orchestrator import AgentOrchestrator
from wiicon5.bot_instance import BotInstanceConfig
from wiicon5.conversation.memory import ConversationMemory
from wiicon5.instance_knowledge.answer import KnowledgeAnswerService
from wiicon5.instance_knowledge.importers import ConfluenceClient, JsonKnowledgeImporter, html_to_markdown
from wiicon5.instance_knowledge.index import InstanceKnowledgeBase
from wiicon5.instance_knowledge.models import KnowledgePage
from wiicon5.instance_knowledge.storage import KnowledgeRepository
from wiicon5.instance_knowledge.sync import KnowledgeSyncService, knowledge_auth_headers
from wiicon5.intent.decomposer import DecompositionResult
from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.llm.client import ScriptedLLMClient
from wiicon5.skills.registry import SkillRegistry
from wiicon5.testing.scripted_decomposer import ScriptedGoalDecomposer


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

    def test_confluence_client_walks_descendants_with_same_origin_rest(self) -> None:
        payloads = {
            "/rest/api/content/10?": confluence_payload("10", "1C WIIC", "<p>Корень</p>", []),
            "/rest/api/content/10/child/page?": {
                "results": [confluence_payload("20", "Требования", "<p>Инструкция</p>", [{"id": "10", "title": "1C WIIC"}])],
                "limit": 100,
            },
            "/rest/api/content/20/child/page?": {"results": [], "limit": 100},
        }

        def fake_urlopen(request, timeout=0):
            for marker, payload in payloads.items():
                if marker in request.full_url:
                    return FakeHttpResponse(payload)
            raise AssertionError(request.full_url)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            pages = ConfluenceClient(base_url="https://bwiki.example", headers={"Cookie": "hidden"}).fetch_tree("10")
        self.assertEqual([page.page_id for page in pages], ["10", "20"])
        self.assertEqual(pages[1].parent_id, "10")
        self.assertEqual(pages[1].ancestor_titles, ["1C WIIC"])

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

    def test_bot_instance_parses_knowledge_configuration(self) -> None:
        config = BotInstanceConfig.from_mapping(
            {
                "bot": {"id": "wiic"},
                "knowledge": {
                    "enabled": True,
                    "base_url": "https://bwiki.example",
                    "root_page_id": "177957241",
                    "stale_after_days": "365",
                    "search_top_k": "6",
                },
            }
        )
        self.assertTrue(config.knowledge.enabled)
        self.assertEqual(config.knowledge.root_page_id, "177957241")
        self.assertEqual(config.knowledge.stale_after_days, 365)
        self.assertEqual(config.knowledge.search_top_k, 6)

    def test_grounded_answer_adds_verified_source_and_stale_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = prepared_repository(Path(temp_dir), updated_at="2020-01-01T00:00:00Z")
            knowledge_base = InstanceKnowledgeBase(repository, stale_after_days=365)
            hit = knowledge_base.search("Как исправить ошибку статуса 3PL?")[0]
            llm = ScriptedLLMClient(
                [
                    {
                        "answerable": True,
                        "answer": "Проверьте очередь обмена и повторите отправку.",
                        "used_chunk_ids": [hit.chunk_id],
                        "confidence": "high",
                        "needs_live_data": False,
                        "contradictions": [],
                    }
                ]
            )
            result = KnowledgeAnswerService(knowledge_base=knowledge_base, llm_client=llm).answer(
                "Как исправить ошибку статуса 3PL?",
                ConversationMemory().get_or_create("s1"),
            )
        self.assertTrue(result.answerable)
        self.assertIn("Проверьте очередь обмена", result.answer)
        self.assertIn("давно не обновлялся", result.answer)
        self.assertIn("[Ошибки интеграции 3PL](https://bwiki.example/pages/1)", result.answer)

    def test_grounded_answer_rejects_unknown_source_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            knowledge_base = InstanceKnowledgeBase(prepared_repository(Path(temp_dir)))
            llm = ScriptedLLMClient(
                [
                    {
                        "answerable": True,
                        "answer": "Ответ",
                        "used_chunk_ids": ["invented"],
                        "confidence": "high",
                        "needs_live_data": False,
                        "contradictions": [],
                    }
                ]
            )
            result = KnowledgeAnswerService(knowledge_base=knowledge_base, llm_client=llm).answer(
                "Как исправить ошибку статуса 3PL?",
                ConversationMemory().get_or_create("s1"),
            )
        self.assertFalse(result.answerable)
        self.assertIn("unknown evidence", result.error)

    def test_orchestrator_answers_documentation_question_without_skill_or_mcp(self) -> None:
        question = "Почему не поступил статус успешной интеграции в 3PL?"
        decomposition = DecompositionResult(
            intent=IntentResult(
                intent_type=IntentType.GENERAL_QUESTION,
                business_goal=question,
                requires_1c_data=False,
                expected_output="answer",
                domain_terms=["3PL", "статус"],
                relevant=True,
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            knowledge_base = InstanceKnowledgeBase(prepared_repository(root))
            hit = knowledge_base.search(question)[0]
            answerer = KnowledgeAnswerService(
                knowledge_base=knowledge_base,
                llm_client=ScriptedLLMClient(
                    [
                        {
                            "answerable": True,
                            "answer": "Проверьте очередь обмена.",
                            "used_chunk_ids": [hit.chunk_id],
                            "confidence": "high",
                            "needs_live_data": False,
                            "contradictions": [],
                        }
                    ]
                ),
            )
            orchestrator = AgentOrchestrator(
                registry=SkillRegistry(),
                decomposer=ScriptedGoalDecomposer({question: decomposition}),
                knowledge_answerer=answerer,
                trace_root=root / "runs",
            )
            result = orchestrator.handle(question, session_id="s1")
            trace = Path(result.trace_path or "")
            answer_trace_exists = (trace / "knowledge/answer.json").exists()
        self.assertEqual(result.source, "instance_knowledge")
        self.assertIn("Проверьте очередь обмена", result.message)
        self.assertTrue(answer_trace_exists)


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


def prepared_repository(root: Path, *, updated_at: str = "2026-07-01T00:00:00Z") -> KnowledgeRepository:
    export = root / "knowledge-export.json"
    export.write_text(
        json.dumps(
            {
                "pages": [
                    page_payload(
                        "1",
                        "Ошибки интеграции 3PL",
                        "# Успешная интеграция в 3PL\nЕсли статус не поступил, проверьте очередь обмена.",
                        updated_at=updated_at,
                    )
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
    if not result.ok:
        raise AssertionError(result.error)
    return repository


def confluence_payload(page_id: str, title: str, body: str, ancestors):
    return {
        "id": page_id,
        "title": title,
        "body": {"storage": {"value": body}},
        "ancestors": ancestors,
        "version": {"number": 1, "when": "2026-07-01T00:00:00Z"},
        "space": {"key": "BRIT"},
        "_links": {"webui": f"/pages/viewpage.action?pageId={page_id}"},
    }


class FakeHttpResponse:
    def __init__(self, payload) -> None:
        self.status = 200
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


if __name__ == "__main__":
    unittest.main()

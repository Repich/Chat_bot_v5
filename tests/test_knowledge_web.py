from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.parse
from http.server import HTTPServer
from pathlib import Path

from wiicon5.agent.orchestrator import AgentOrchestrator
from wiicon5.instance_knowledge.index import InstanceKnowledgeBase
from wiicon5.instance_knowledge.storage import KnowledgeRepository
from wiicon5.instance_knowledge.sync import KnowledgeSyncService
from wiicon5.onboarding.status import OnboardingManager
from wiicon5.skills.registry import SkillRegistry
from wiicon5.testing.scripted_decomposer import ScriptedGoalDecomposer
from wiicon5.web.server import make_handler


class KnowledgeWebTests(unittest.TestCase):
    def test_status_search_and_page_endpoints_use_instance_snapshot(self) -> None:
        agent = AgentOrchestrator(registry=SkillRegistry(), decomposer=ScriptedGoalDecomposer({}))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bot_root = root / "bot"
            bot_root.mkdir(parents=True)
            (bot_root / "bot.yaml").write_text(
                """bot:
  id: wiic_test
  name: WIIC Test
knowledge:
  enabled: true
  base_url: https://bwiki.example
  root_page_id: 1
  stale_after_days: 365
""",
                encoding="utf-8",
            )
            export = root / "export.json"
            export.write_text(
                json.dumps(
                    {
                        "pages": [
                            {
                                "page_id": "1",
                                "title": "Пункты самовывоза",
                                "content": "# Адрес ПВЗ\nАдрес пункта самовывоза хранится в карточке ПВЗ.",
                                "source_url": "https://bwiki.example/pages/1",
                                "updated_at": "2026-07-01T00:00:00Z",
                                "version": 3,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            repository = KnowledgeRepository(bot_root / "knowledge")
            synced = KnowledgeSyncService(
                repository=repository,
                source_kind="confluence",
                base_url="https://bwiki.example",
                root_page_id="1",
            ).sync(input_json=export)
            self.assertTrue(synced.ok)
            server = HTTPServer(
                ("127.0.0.1", 0),
                make_handler(
                    agent,
                    onboarding_manager=OnboardingManager(bot_instance_root=bot_root),
                    instance_knowledge=InstanceKnowledgeBase(repository, stale_after_days=365),
                ),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                status = fetch_json(f"http://{host}:{port}/api/knowledge/status")
                search_term = urllib.parse.quote("адрес ПВЗ")
                search = fetch_json(f"http://{host}:{port}/api/knowledge/search?q={search_term}")
                page = fetch_json(f"http://{host}:{port}/api/knowledge/page?page_id=1")
                ui_config = fetch_json(f"http://{host}:{port}/api/ui/config")
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertTrue(status["status"]["available"])
        self.assertEqual(status["status"]["current"]["page_count"], 1)
        self.assertEqual(search["hits"][0]["page_id"], "1")
        self.assertNotIn("content", search["hits"][0])
        self.assertIn("карточке ПВЗ", page["page"]["content"])
        self.assertEqual(ui_config["config"]["bot"]["id"], "wiic_test")
        self.assertTrue(ui_config["config"]["knowledge"]["enabled"])

    def test_static_client_contains_knowledge_workspace(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        html = (project_root / "src/wiicon5/web/static/index.html").read_text(encoding="utf-8")
        javascript = (project_root / "src/wiicon5/web/static/app.js").read_text(encoding="utf-8")
        self.assertIn('data-view="knowledge"', html)
        self.assertIn('id="knowledgeSearchInput"', html)
        self.assertIn('id="knowledgeSyncButton"', html)
        self.assertIn("loadKnowledgeStatus", javascript)
        self.assertIn("/api/knowledge/search", javascript)
        self.assertIn("/api/admin/knowledge/sync", javascript)


def fetch_json(url: str):
    return json.loads(urllib.request.urlopen(url, timeout=5).read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()

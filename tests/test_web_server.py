from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from http.server import HTTPServer
from pathlib import Path

from wiicon5.agent.orchestrator import AgentOrchestrator
from wiicon5.intent.decomposer import DecompositionResult
from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.skills.registry import SkillRegistry
from wiicon5.testing.scripted_decomposer import ScriptedGoalDecomposer
from wiicon5.web.server import make_handler


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WebServerTests(unittest.TestCase):
    def test_health_and_chat_return_json(self) -> None:
        question = "Привет"
        agent = AgentOrchestrator(
            registry=SkillRegistry.load_from_dir(PROJECT_ROOT / "skills"),
            decomposer=ScriptedGoalDecomposer(
                {
                    question: DecompositionResult(
                        intent=IntentResult(
                            intent_type=IntentType.OUT_OF_SCOPE,
                            business_goal=question,
                            requires_1c_data=False,
                            relevant=False,
                        )
                    )
                }
            ),
        )
        server = HTTPServer(("127.0.0.1", 0), make_handler(agent))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            health = json.loads(urllib.request.urlopen(f"http://{host}:{port}/health", timeout=5).read().decode("utf-8"))
            version = json.loads(
                urllib.request.urlopen(f"http://{host}:{port}/api/version", timeout=5).read().decode("utf-8")
            )
            chat_page_response = urllib.request.urlopen(f"http://{host}:{port}/chat", timeout=5)
            chat_page = chat_page_response.read().decode("utf-8")
            request = urllib.request.Request(
                f"http://{host}:{port}/chat",
                data=json.dumps({"message": question, "session_id": "s1"}, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            chat = json.loads(urllib.request.urlopen(request, timeout=5).read().decode("utf-8"))
            conversation = json.loads(
                urllib.request.urlopen(
                    f"http://{host}:{port}/api/conversation?session_id=s1",
                    timeout=5,
                )
                .read()
                .decode("utf-8")
            )
            backend_history = urllib.request.urlopen(f"http://{host}:{port}/history/backend", timeout=5).read().decode("utf-8")
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertTrue(health["ok"])
        self.assertEqual(version["version"], (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip())
        self.assertIn("text/html", chat_page_response.headers["Content-Type"])
        self.assertIn("WIICON ChatBot 5", chat_page)
        self.assertIn("chatForm", chat_page)
        self.assertIn("appVersion", chat_page)
        self.assertIn("reloadHistoryButton", chat_page)
        self.assertIn('input.addEventListener("keydown"', chat_page)
        self.assertIn("form.requestSubmit()", chat_page)
        self.assertIn("startTitleBlink", chat_page)
        self.assertIn("Новое сообщение", chat_page)
        self.assertTrue(chat["ok"])
        self.assertEqual(chat["result"]["source"], "general_answer")
        self.assertEqual([item["role"] for item in conversation["messages"]], ["user", "assistant"])
        self.assertIn("5.0.0-alpha.2", backend_history)


if __name__ == "__main__":
    unittest.main()

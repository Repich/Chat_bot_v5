from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, Tuple

from wiicon5.agent.orchestrator import AgentOrchestrator
from wiicon5.intent.decomposer import DecompositionResult
from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.onboarding.status import OnboardingManager
from wiicon5.skills.registry import SkillRegistry
from wiicon5.testing.scripted_decomposer import ScriptedGoalDecomposer
from wiicon5.web.admin_security import AdminSecurityConfig
from wiicon5.web.server import make_handler


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AdminSecurityTests(unittest.TestCase):
    def test_admin_endpoint_requires_token_when_configured_but_chat_does_not(self) -> None:
        with running_server(admin_security=AdminSecurityConfig(token="secret")) as base_url:
            denied_status, denied_payload = request_json(f"{base_url}/api/admin/onboarding/status")
            allowed_status, allowed_payload = request_json(
                f"{base_url}/api/admin/onboarding/status",
                headers={"Authorization": "Bearer secret"},
            )
            chat_status, chat_payload = request_json(
                f"{base_url}/chat",
                method="POST",
                payload={"message": "Привет", "session_id": "s1"},
            )

        self.assertEqual(denied_status, 401)
        self.assertEqual(denied_payload["error"], "admin_token_required")
        self.assertEqual(allowed_status, 200)
        self.assertTrue(allowed_payload["ok"])
        self.assertEqual(chat_status, 200)
        self.assertTrue(chat_payload["ok"])

    def test_admin_token_header_is_accepted(self) -> None:
        with running_server(admin_security=AdminSecurityConfig(token="secret")) as base_url:
            status, payload = request_json(
                f"{base_url}/api/admin/onboarding/status",
                headers={"X-WIICON5-Admin-Token": "secret"},
            )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

    def test_admin_disabled_rejects_admin_endpoint(self) -> None:
        with running_server(admin_security=AdminSecurityConfig(enabled=False)) as base_url:
            admin_status, admin_payload = request_json(f"{base_url}/api/admin/onboarding/status")
            health_status, health_payload = request_json(f"{base_url}/health")

        self.assertEqual(admin_status, 403)
        self.assertEqual(admin_payload["error"], "admin_disabled")
        self.assertEqual(health_status, 200)
        self.assertTrue(health_payload["ok"])

    def test_onboarding_config_dump_must_be_inside_allowlist(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            allowed = root / "allowed"
            outside = root / "outside" / "config"
            with running_server(
                admin_security=AdminSecurityConfig(allowed_config_roots=(allowed,)),
                bot_root=root / "bot",
            ) as base_url:
                status, payload = request_json(
                    f"{base_url}/api/admin/onboarding/run",
                    method="POST",
                    payload={"config_dump": str(outside)},
                )

        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "config_dump_not_allowed")


class running_server:
    def __init__(self, *, admin_security: AdminSecurityConfig, bot_root: Path | None = None) -> None:
        self.temp_dir = TemporaryDirectory()
        self.bot_root = bot_root or Path(self.temp_dir.name) / "bot"
        self.admin_security = admin_security
        self.server: HTTPServer | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> str:
        agent = AgentOrchestrator(
            registry=SkillRegistry.load_from_dir(PROJECT_ROOT / "skills"),
            decomposer=ScriptedGoalDecomposer(
                {
                    "Привет": DecompositionResult(
                        intent=IntentResult(
                            intent_type=IntentType.OUT_OF_SCOPE,
                            business_goal="Привет",
                            requires_1c_data=False,
                            relevant=False,
                        )
                    )
                }
            ),
        )
        self.server = HTTPServer(
            ("127.0.0.1", 0),
            make_handler(
                agent,
                onboarding_manager=OnboardingManager(bot_instance_root=self.bot_root),
                admin_security=self.admin_security,
            ),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.server is not None:
            self.server.shutdown()
        if self.thread is not None:
            self.thread.join(timeout=2)
        if self.server is not None:
            self.server.server_close()
        self.temp_dir.cleanup()


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: Dict[str, Any] | None = None,
    headers: Dict[str, str] | None = None,
) -> Tuple[int, Dict[str, Any]]:
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))
    return response.status, json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()

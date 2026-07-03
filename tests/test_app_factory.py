from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.app.config import Settings
from wiicon5.app.factory import build_agent
from wiicon5.llm.client import ScriptedLLMClient
from wiicon5.mcp.client import DictMcpClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AppFactoryTests(unittest.TestCase):
    def test_settings_from_env_uses_project_paths_and_defaults(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings.from_env(
                {
                    "WIICON5_LLM_API_BASE": "https://llm.example/api/v1",
                    "WIICON5_LLM_API_KEY": "secret",
                    "WIICON5_MCP_URL": "http://127.0.0.1:6003",
                    "WIICON5_CONFIG_FINGERPRINT": "cfg_test",
                },
                root=root,
            )

        self.assertEqual(settings.llm_model, "deepseek-chat")
        self.assertEqual(settings.config_fingerprint, "cfg_test")
        self.assertEqual(settings.skills_dir, root / "skills")
        self.assertEqual(settings.bindings_dir, root / "skills" / "bindings")

    def test_settings_validate_for_llm_reports_missing_keys(self) -> None:
        settings = Settings.from_env({}, root=PROJECT_ROOT)

        with self.assertRaises(ValueError) as exc:
            settings.validate_for_llm()

        self.assertIn("WIICON5_LLM_API_BASE", str(exc.exception))
        self.assertIn("WIICON5_LLM_API_KEY", str(exc.exception))

    def test_settings_loads_env_file_and_deepseek_fallbacks(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env.wiicon5").write_text(
                "\n".join(
                    [
                        "DEEPSEEK_API_BASE=https://api.deepseek.com",
                        "DEEPSEEK_API_KEY=secret",
                        "DEEPSEEK_MODEL=deepseek-chat",
                    ]
                ),
                encoding="utf-8",
            )

            settings = Settings.from_env({}, root=root)

        self.assertEqual(settings.llm_api_base, "https://api.deepseek.com")
        self.assertEqual(settings.llm_api_key, "secret")
        self.assertEqual(settings.llm_model, "deepseek-chat")

    def test_settings_accepts_wiicon4_llm_fallbacks(self) -> None:
        settings = Settings.from_env(
            {
                "WIICON4_LLM_API_BASE": "https://api.deepseek.com",
                "WIICON4_LLM_API_KEY": "secret",
                "WIICON4_LLM_MODEL": "deepseek-chat",
                "WIICON4_LLM_TIMEOUT_SECONDS": "90",
            },
            root=PROJECT_ROOT,
        )

        self.assertEqual(settings.llm_api_base, "https://api.deepseek.com")
        self.assertEqual(settings.llm_api_key, "secret")
        self.assertEqual(settings.llm_model, "deepseek-chat")
        self.assertEqual(settings.llm_timeout_seconds, 90)

    def test_build_agent_accepts_test_clients_without_real_network(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = Settings.from_env(
                {
                    "WIICON5_SKILLS_DIR": str(PROJECT_ROOT / "skills"),
                    "WIICON5_BINDINGS_DIR": str(Path(temp_dir) / "bindings"),
                    "WIICON5_RUNS_DIR": str(Path(temp_dir) / "runs"),
                },
                root=PROJECT_ROOT,
            )
            agent = build_agent(
                settings,
                llm_client=ScriptedLLMClient(
                    [
                        {
                            "intent": {
                                "intent_type": "out_of_scope",
                                "business_goal": "weather",
                                "requires_1c_data": False,
                                "relevant": False,
                            },
                            "goal": None,
                        }
                    ]
                ),
                mcp_client=DictMcpClient({"success": True, "data": []}),
            )

            result = agent.handle("Какая погода?", session_id="s1")

        self.assertEqual(result.source, "out_of_scope")

    def test_build_agent_seeds_conversation_context_with_config_fingerprint(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = Settings.from_env(
                {
                    "WIICON5_SKILLS_DIR": str(PROJECT_ROOT / "skills"),
                    "WIICON5_BINDINGS_DIR": str(Path(temp_dir) / "bindings"),
                    "WIICON5_RUNS_DIR": str(Path(temp_dir) / "runs"),
                    "WIICON5_CONFIG_FINGERPRINT": "cfg_local",
                },
                root=PROJECT_ROOT,
            )
            agent = build_agent(
                settings,
                llm_client=ScriptedLLMClient([]),
                mcp_client=DictMcpClient({"success": True, "data": []}),
            )

            context = agent.memory.get_or_create("s1")

        self.assertEqual(context.config_fingerprint, "cfg_local")


if __name__ == "__main__":
    unittest.main()

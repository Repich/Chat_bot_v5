from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.app.config import Settings
from wiicon5.app.factory import build_agent, build_failure_solver, learned_skill_root, skill_registry_roots
from wiicon5.query_synthesis.failure_solver import UnavailableFailureSolver
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
        self.assertEqual(settings.llm_trust_zone, "external")
        self.assertEqual(settings.internal_llm_allowed_hosts, ())
        self.assertEqual(settings.config_fingerprint, "cfg_test")
        self.assertEqual(settings.skills_dir, root / "skills")
        self.assertEqual(settings.bindings_dir, root / "skills" / "bindings")
        self.assertEqual(settings.bot_instance.bot_id, "local")
        self.assertEqual(settings.bot_context.root, root / "bot_instances" / "local")
        self.assertTrue(settings.admin_enabled)
        self.assertEqual(settings.admin_token, "")
        self.assertTrue(settings.admin_bind_local_only)
        self.assertIn(root, settings.admin_allowed_config_roots)
        self.assertFalse(settings.workbench_allow_raw_query_edit)
        self.assertFalse(settings.failure_solver_enabled)
        self.assertEqual(settings.failure_solver_provider, "openai_compatible")
        self.assertEqual(settings.diagnostics_dir, root / "bot_instances" / "local" / "diagnostics")
        self.assertFalse(settings.offline_updates_enabled)

    def test_settings_loads_offline_deployment_paths(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            install_root = root / "installed"
            settings = Settings.from_env(
                {
                    "WIICON5_INSTALL_ROOT": str(install_root),
                    "WIICON5_DIAGNOSTICS_DIR": str(install_root / "data" / "diagnostics"),
                    "WIICON5_SERVICE_LOG": str(install_root / "logs" / "service.log"),
                },
                root=root,
            )

        self.assertTrue(settings.offline_updates_enabled)
        self.assertEqual(settings.install_root, install_root)
        self.assertEqual(settings.update_inbox_dir, install_root / "updates" / "inbox")
        self.assertEqual(settings.update_request_file, install_root / "updates" / "apply-request.json")
        self.assertEqual(settings.diagnostics_dir, install_root / "data" / "diagnostics")
        self.assertIn(install_root / "data", settings.admin_allowed_config_roots)

    def test_settings_default_to_automatic_configuration_fingerprint(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = Settings.from_env({}, root=Path(temp_dir))

        self.assertEqual(settings.config_fingerprint, "auto")

    def test_settings_loads_admin_security_options(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            allowed_a = root / "config_a"
            allowed_b = root / "config_b"
            settings = Settings.from_env(
                {
                    "WIICON5_ADMIN_ENABLED": "false",
                    "WIICON5_ADMIN_TOKEN": "secret",
                    "WIICON5_ADMIN_BIND_LOCAL_ONLY": "false",
                    "WIICON5_ADMIN_ALLOWED_CONFIG_ROOTS": os.pathsep.join([str(allowed_a), str(allowed_b)]),
                    "WIICON5_WORKBENCH_ALLOW_RAW_QUERY_EDIT": "true",
                },
                root=root,
            )

        self.assertFalse(settings.admin_enabled)
        self.assertEqual(settings.admin_token, "secret")
        self.assertFalse(settings.admin_bind_local_only)
        self.assertEqual(settings.admin_allowed_config_roots, (allowed_a, allowed_b))
        self.assertTrue(settings.workbench_allow_raw_query_edit)

    def test_settings_loads_failure_solver_options(self) -> None:
        settings = Settings.from_env(
            {
                "WIICON5_FAILURE_SOLVER_ENABLED": "true",
                "WIICON5_FAILURE_SOLVER_PROVIDER": "codex_cli",
                "WIICON5_FAILURE_SOLVER_API_BASE": "https://api.openai.example/v1",
                "WIICON5_FAILURE_SOLVER_API_KEY": "solver-secret",
                "WIICON5_FAILURE_SOLVER_MODEL": "gpt-test",
                "WIICON5_FAILURE_SOLVER_TIMEOUT_SECONDS": "180",
                "WIICON5_FAILURE_SOLVER_CODEX_COMMAND": "python3 scripts/codex_failure_solver.py",
                "WIICON5_FAILURE_SOLVER_TRUST_ZONE": "internal",
                "WIICON5_FAILURE_SOLVER_INTERNAL_ALLOWED_HOSTS": "glm.internal.example",
            },
            root=PROJECT_ROOT,
        )

        self.assertTrue(settings.failure_solver_enabled)
        self.assertEqual(settings.failure_solver_provider, "codex_cli")
        self.assertEqual(settings.failure_solver_api_base, "https://api.openai.example/v1")
        self.assertEqual(settings.failure_solver_api_key, "solver-secret")
        self.assertEqual(settings.failure_solver_model, "gpt-test")
        self.assertEqual(settings.failure_solver_timeout_seconds, 180)
        self.assertEqual(settings.failure_solver_codex_command, "python3 scripts/codex_failure_solver.py")
        self.assertEqual(settings.failure_solver_trust_zone, "internal")
        self.assertEqual(settings.failure_solver_internal_allowed_hosts, ("glm.internal.example",))

    def test_codex_failure_solver_is_disabled_by_confidential_data_boundary(self) -> None:
        settings = Settings.from_env(
            {
                "WIICON5_FAILURE_SOLVER_ENABLED": "true",
                "WIICON5_FAILURE_SOLVER_PROVIDER": "codex_cli",
                "WIICON5_FAILURE_SOLVER_CODEX_COMMAND": "codex exec",
            },
            root=PROJECT_ROOT,
        )

        solver = build_failure_solver(settings)

        self.assertIsInstance(solver, UnavailableFailureSolver)
        self.assertIn("confidential-data boundary", solver.reason)

    def test_settings_loads_internal_llm_boundary_configuration(self) -> None:
        settings = Settings.from_env(
            {
                "WIICON5_LLM_API_BASE": "https://glm.internal.example/v1",
                "WIICON5_LLM_API_KEY": "secret",
                "WIICON5_LLM_MODEL": "glm-5.2",
                "WIICON5_LLM_TRUST_ZONE": "internal",
                "WIICON5_INTERNAL_LLM_ALLOWED_HOSTS": "glm.internal.example; backup.internal.example",
            },
            root=PROJECT_ROOT,
        )

        settings.validate_for_llm()
        self.assertEqual(settings.llm_trust_zone, "internal")
        self.assertEqual(
            settings.internal_llm_allowed_hosts,
            ("glm.internal.example", "backup.internal.example"),
        )

    def test_settings_loads_auto_learned_skill_options(self) -> None:
        settings = Settings.from_env(
            {
                "WIICON5_AUTO_LEARNED_SKILLS_ENABLED": "false",
                "WIICON5_AUTO_LEARNED_SKILLS_ACTIVATE": "false",
                "WIICON5_AUTO_LEARNED_SKILLS_SCOPE": "global",
                "WIICON5_AUTO_LEARNED_SKILLS_FAILURE_THRESHOLD": "5",
            },
            root=PROJECT_ROOT,
        )

        self.assertFalse(settings.auto_learned_skills_enabled)
        self.assertFalse(settings.auto_learned_skills_activate)
        self.assertEqual(settings.auto_learned_skills_scope, "global")
        self.assertEqual(settings.auto_learned_skills_failure_threshold, 5)

    def test_settings_loads_bot_instance_yaml(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bot_root = root / "bot_instances" / "custom"
            bot_root.mkdir(parents=True)
            (bot_root / "bot.yaml").write_text(
                "\n".join(
                    [
                        "bot:",
                        "  id: custom",
                        "  name: Custom 1C Agent",
                        "  domain_label: тестовая база 1С",
                        "  domain_hint_packs:",
                        "    - one_c_standard",
                        "baseline:",
                        "  general_markers:",
                        "    - hello",
                        "  data_markers:",
                        "    - data",
                        "answers:",
                        "  intro: Я Custom 1C Agent.",
                        "  out_of_scope_default: Это не мой домен.",
                    ]
                ),
                encoding="utf-8",
            )

            settings = Settings.from_env({"WIICON5_BOT_ID": "custom"}, root=root)

        self.assertEqual(settings.bot_instance.bot_id, "custom")
        self.assertEqual(settings.bot_instance.bot_name, "Custom 1C Agent")
        self.assertEqual(settings.bot_instance.domain_label, "тестовая база 1С")
        self.assertEqual(settings.bot_instance.general_markers, ["hello"])
        self.assertEqual(settings.bot_instance.data_markers, ["data"])
        self.assertEqual(settings.bot_instance.intro_answer, "Я Custom 1C Agent.")

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

    def test_build_agent_can_compute_config_fingerprint_from_metadata(self) -> None:
        metadata_response = {
            "success": True,
            "data": [
                {
                    "ПолноеИмя": "Справочник.Склады",
                    "Синоним": "Склады",
                    "Реквизиты": [{"Имя": "ТипСклада", "Тип": "ПеречислениеСсылка.ТипыСкладов"}],
                }
            ],
        }
        with TemporaryDirectory() as temp_dir:
            settings = Settings.from_env(
                {
                    "WIICON5_SKILLS_DIR": str(PROJECT_ROOT / "skills"),
                    "WIICON5_BINDINGS_DIR": str(Path(temp_dir) / "bindings"),
                    "WIICON5_RUNS_DIR": str(Path(temp_dir) / "runs"),
                    "WIICON5_BOT_ROOT": str(Path(temp_dir) / "bot"),
                    "WIICON5_CONFIG_FINGERPRINT": "auto",
                },
                root=PROJECT_ROOT,
            )
            mcp = DictMcpClient({"success": True, "data": []}, metadata_response=metadata_response)
            agent = build_agent(
                settings,
                llm_client=ScriptedLLMClient([]),
                mcp_client=mcp,
            )

            context = agent.memory.get_or_create("s1")

        self.assertNotEqual(context.config_fingerprint, "auto")
        self.assertTrue(str(context.config_fingerprint).startswith("cfg_"))
        self.assertGreaterEqual(len(mcp.metadata_calls), 1)

    def test_empty_metadata_does_not_produce_a_reusable_configuration_fingerprint(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = Settings.from_env(
                {
                    "WIICON5_SKILLS_DIR": str(PROJECT_ROOT / "skills"),
                    "WIICON5_BINDINGS_DIR": str(Path(temp_dir) / "bindings"),
                    "WIICON5_RUNS_DIR": str(Path(temp_dir) / "runs"),
                    "WIICON5_BOT_ROOT": str(Path(temp_dir) / "bot"),
                    "WIICON5_CONFIG_FINGERPRINT": "auto",
                },
                root=PROJECT_ROOT,
            )
            agent = build_agent(
                settings,
                llm_client=ScriptedLLMClient([]),
                mcp_client=DictMcpClient({"success": True, "data": []}, metadata_response={"success": True, "data": []}),
            )

            context = agent.memory.get_or_create("s1")

        self.assertEqual(context.config_fingerprint, "unresolved")

    def test_learned_skill_root_is_bot_specific_by_default(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings.from_env({}, root=root)

        self.assertEqual(learned_skill_root(settings), root / "bot_instances" / "local" / "skills")
        self.assertIn(root / "bot_instances" / "local" / "skills", skill_registry_roots(settings))
        self.assertNotIn(root / "skills" / "learned", skill_registry_roots(settings))

    def test_global_learned_scope_is_explicit_and_loaded_on_restart(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings.from_env(
                {"WIICON5_AUTO_LEARNED_SKILLS_SCOPE": "global"},
                root=root,
            )

        self.assertEqual(learned_skill_root(settings), root / "skills")
        self.assertIn(root / "skills" / "learned", skill_registry_roots(settings))


if __name__ == "__main__":
    unittest.main()

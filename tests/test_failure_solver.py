from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.query_synthesis.failure_solver import CodexCliFailureSolver, compact_diagnostic_payload


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FailureSolverTests(unittest.TestCase):
    def test_codex_cli_solver_sends_compact_diagnostic_to_external_command(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            capture_path = temp_path / "stdin.json"
            fake_solver = temp_path / "fake_solver.py"
            fake_solver.write_text(
                "\n".join(
                    [
                        "import json, pathlib, sys",
                        "payload = json.loads(sys.stdin.read())",
                        f"pathlib.Path({str(capture_path)!r}).write_text(json.dumps(payload), encoding='utf-8')",
                        "print(json.dumps({'action':'cannot_solve','reasoning':'checked','developer_note':'no data'}))",
                    ]
                ),
                encoding="utf-8",
            )

            solver = CodexCliFailureSolver(command=f"{sys.executable} {fake_solver}", timeout_seconds=10)
            decision = solver.solve(sample_diagnostic_payload())

            captured = json.loads(capture_path.read_text(encoding="utf-8"))

        self.assertEqual(decision.action, "cannot_solve")
        self.assertIn("system_prompt", captured)
        self.assertIn("diagnostic", captured)
        self.assertEqual(captured["diagnostic"]["message"], "Покажи цены")
        self.assertIn("attempts", captured["diagnostic"]["synthesis_trace"])
        self.assertNotIn("answer_md", json.dumps(captured, ensure_ascii=False))

    def test_compact_diagnostic_keeps_failure_essentials(self) -> None:
        compact = compact_diagnostic_payload(sample_diagnostic_payload())

        self.assertEqual(compact["failure_error"], "MCP failed")
        self.assertEqual(compact["synthesis_trace"]["attempts"][0]["error"], "bad date")
        self.assertEqual(compact["synthesis_trace"]["metadata_objects"][0]["full_name"], "Справочник.Номенклатура")
        self.assertNotIn("answer_md", json.dumps(compact, ensure_ascii=False))

    def test_codex_failure_solver_adapter_uses_supported_codex_exec_arguments(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            args_path = temp_path / "args.json"
            schema_capture_path = temp_path / "schema.json"
            fake_codex = temp_path / "codex"
            fake_codex.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json, os, pathlib, sys",
                        "args = sys.argv[1:]",
                        "sys.stdin.read()",
                        "pathlib.Path(os.environ['WIICON5_FAKE_CODEX_ARGS']).write_text(json.dumps(args), encoding='utf-8')",
                        "schema_path = pathlib.Path(args[args.index('--output-schema') + 1])",
                        "pathlib.Path(os.environ['WIICON5_FAKE_CODEX_SCHEMA']).write_text(schema_path.read_text(), encoding='utf-8')",
                        "output_path = pathlib.Path(args[args.index('--output-last-message') + 1])",
                        "output_path.write_text(json.dumps({"
                        "'action':'retry_query',"
                        "'query':'ВЫБРАТЬ Ссылка ИЗ Справочник.Номенклатура ГДЕ Наименование = &Наименование',"
                        "'params':[{'name':'Наименование','value':'Пиво','value_json':''}],"
                        "'limit':100,"
                        "'reasoning':'fake checked',"
                        "'answer_guidance':'show rows',"
                        "'developer_note':''"
                        "}), encoding='utf-8')",
                    ]
                ),
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            env = dict(os.environ)
            env["WIICON5_CODEX_BIN"] = str(fake_codex)
            env["WIICON5_FAKE_CODEX_ARGS"] = str(args_path)
            env["WIICON5_FAKE_CODEX_SCHEMA"] = str(schema_capture_path)
            completed = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "scripts" / "codex_failure_solver.py")],
                input=json.dumps({"diagnostic": sample_diagnostic_payload()}, ensure_ascii=False),
                text=True,
                capture_output=True,
                env=env,
                timeout=10,
                check=False,
            )
            output = json.loads(completed.stdout)
            args = json.loads(args_path.read_text(encoding="utf-8"))
            schema = json.loads(schema_capture_path.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(output["action"], "retry_query")
        self.assertEqual(output["params"], {"Наименование": "Пиво"})
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(schema["properties"]["params"]["items"]["additionalProperties"])
        self.assertIn("--ephemeral", args)
        self.assertIn("--output-schema", args)
        self.assertIn("--output-last-message", args)
        self.assertNotIn("--ask-for-approval", args)


def sample_diagnostic_payload() -> dict:
    return {
        "message": "Покажи цены",
        "intent": {"business_goal": "Показать цены"},
        "goal": {"business_goal": "Показать цены"},
        "conversation_context": {
            "session_id": "s1",
            "config_fingerprint": "cfg",
            "messages": [{"role": "user", "content": "Покажи цены"}],
            "artifacts": [],
        },
        "gaps": [],
        "failure_error": "MCP failed",
        "synthesis_trace": {
            "final_error": "MCP failed",
            "metadata_search_terms": ["цены"],
            "metadata_requests": [{"operation": "search_objects", "term": "цены", "success": True, "returned": 1}],
            "metadata_objects": [
                {
                    "full_name": "Справочник.Номенклатура",
                    "synonym": "Номенклатура",
                    "fields": ["Ссылка", "Наименование"],
                    "field_details": {
                        "Ссылка": {"Тип": "СправочникСсылка.Номенклатура", "_category": "attribute"},
                        "Наименование": {"Тип": "Строка", "_category": "attribute"},
                    },
                }
            ],
            "onboarding_evidence": {
                "available": True,
                "answer_md": "large wiki block must not be sent to codex",
                "query_patterns": [{"query": "ВЫБРАТЬ ..."}],
            },
            "attempts": [
                {
                    "attempt": 1,
                    "query": "ВЫБРАТЬ Ссылка ИЗ Справочник.Номенклатура ГДЕ Дата <= &Дата",
                    "params": {"Дата": "9999-12-31T23:59:59"},
                    "error": "bad date",
                    "mcp_response": {"success": False, "error": "bad date"},
                }
            ],
        },
    }


if __name__ == "__main__":
    unittest.main()

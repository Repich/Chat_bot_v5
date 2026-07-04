from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.regression.cases import case_from_trace, load_cases, run_regression_cases, save_case


class RegressionCaseTests(unittest.TestCase):
    def test_creates_case_from_trace_and_validates_it(self) -> None:
        with TemporaryDirectory() as temp_dir:
            trace = Path(temp_dir) / "runs" / "agent_001"
            (trace / "input").mkdir(parents=True)
            (trace / "result").mkdir()
            (trace / "input" / "user_message.json").write_text(
                json.dumps({"message": "Покажи склады"}, ensure_ascii=False),
                encoding="utf-8",
            )
            (trace / "result" / "result.json").write_text(
                json.dumps(
                    {
                        "source": "query_synthesis_ok",
                        "final_artifact": {"type": "WarehouseRefList"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            case = case_from_trace(trace, expected_ok=True)
            case_path = Path(temp_dir) / "cases" / "case.json"
            save_case(case, case_path)

            result = run_regression_cases(load_cases(case_path))

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)

    def test_regression_validation_reports_invalid_ok_case(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "case.json"
            path.write_text(
                json.dumps(
                    {
                        "question": "Покажи данные",
                        "expected_behavior": "ok",
                        "expected_source": "skill_gap",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_regression_cases(load_cases(path))

        self.assertFalse(result["ok"])
        self.assertIn("expected ok", result["failures"][0]["issues"][0])


if __name__ == "__main__":
    unittest.main()

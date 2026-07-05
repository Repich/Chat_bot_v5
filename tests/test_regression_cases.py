from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.agent.orchestrator import AgentRunResult
from wiicon5.execution.artifacts import Artifact
from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.regression.cases import case_from_trace, load_cases, run_regression_cases, save_case
from wiicon5.regression.replay import has_successful_replay, run_regression_replay, save_replay_result


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

    def test_replay_runs_cases_through_agent_and_saves_successful_result(self) -> None:
        case = {
            "case_id": "case_stock",
            "question": "Покажи остатки",
            "expected_behavior": "uses_skills_or_synthesis",
            "expected_source": "skill_execution_ok",
            "expected_artifact_type": "StockBalanceTable",
            "expected_columns_any_of": [["Номенклатура", "Остаток"]],
        }
        agent = StaticAgent(
            {
                "Покажи остатки": agent_result(
                    source="skill_execution_ok",
                    artifact=Artifact(
                        name="stock",
                        type="StockBalanceTable",
                        value={"columns": ["Номенклатура", "Остаток"], "rows": [{"Номенклатура": "Товар", "Остаток": 1}]},
                    ),
                )
            }
        )
        with TemporaryDirectory() as temp_dir:
            case_path = Path(temp_dir) / "case.json"
            case_path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")

            result = run_regression_replay(load_cases(case_path), agent)
            saved = save_replay_result(result, Path(temp_dir) / "results")
            saved_exists = saved.exists()
            has_replay = has_successful_replay(saved.parent, ["case_stock"])

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(result.passed, 1)
        self.assertTrue(saved_exists)
        self.assertTrue(has_replay)

    def test_replay_reports_artifact_and_forbidden_object_failures(self) -> None:
        with TemporaryDirectory() as temp_dir:
            trace = Path(temp_dir) / "runs" / "agent_1"
            trace.mkdir(parents=True)
            (trace / "query.json").write_text(
                json.dumps({"query": "ИЗ РегистрНакопления.Запрещенный"}, ensure_ascii=False),
                encoding="utf-8",
            )
            case_path = Path(temp_dir) / "case.json"
            case_path.write_text(
                json.dumps(
                    {
                        "case_id": "case_forbidden",
                        "question": "Покажи данные",
                        "expected_behavior": "ok",
                        "expected_source": "query_synthesis_ok",
                        "expected_artifact_type": "TypedTable",
                        "must_not_use_objects": ["РегистрНакопления.Запрещенный"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            agent = StaticAgent(
                {
                    "Покажи данные": agent_result(
                        source="query_synthesis_ok",
                        artifact=Artifact(name="answer", type="OtherTable", value={"rows": [{"A": 1}]}),
                        trace_path=str(trace),
                    )
                }
            )

            result = run_regression_replay(load_cases(case_path), agent)

        self.assertFalse(result.ok)
        issues = result.case_results[0].issues
        self.assertTrue(any("expected artifact" in issue for issue in issues))
        self.assertTrue(any("forbidden object" in issue for issue in issues))


class StaticAgent:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def handle(self, question: str, *, session_id: str):
        self.calls.append({"question": question, "session_id": session_id})
        return self.results[question]


def agent_result(*, source: str, artifact: Artifact | None = None, trace_path: str = "") -> AgentRunResult:
    return AgentRunResult(
        source=source,
        message="ok",
        intent=IntentResult(
            intent_type=IntentType.DATA_QUESTION,
            business_goal="test",
            requires_1c_data=True,
            relevant=True,
        ),
        final_artifact=artifact,
        trace_path=trace_path,
    )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.agent.orchestrator import AgentOrchestrator
from wiicon5.execution.artifacts import Artifact
from wiicon5.intent.decomposer import DecompositionResult
from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.models import ArtifactRequirement
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.query_synthesis import QuerySynthesisResult
from wiicon5.skills.registry import SkillRegistry
from wiicon5.testing.scripted_decomposer import ScriptedGoalDecomposer
from wiicon5.workbench import HumanSkillDraftStore, SynthesisCandidateStore


class WorkbenchSynthesisCandidateTests(unittest.TestCase):
    def test_successful_synthesis_creates_candidate_with_trace_path(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SynthesisCandidateStore(bot_instance_root=Path(temp_dir) / "bot")

            candidate = store.record_from_synthesis(
                question="Покажи выручку за 2025 год",
                intent=data_intent("Покажи выручку за 2025 год"),
                goal=None,
                synthesis_result=successful_synthesis_result(),
                trace_path="/runs/agent_1",
            )
            candidates = store.list_candidates()

        self.assertIsNotNone(candidate)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].trace_path, "/runs/agent_1")
        self.assertEqual(candidates[0].row_count, 1)
        self.assertIn("ВЫБРАТЬ", candidates[0].query)

    def test_failed_or_empty_synthesis_does_not_create_candidate(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SynthesisCandidateStore(bot_instance_root=Path(temp_dir) / "bot")

            failed = store.record_from_synthesis(
                question="Покажи выручку",
                intent=data_intent("Покажи выручку"),
                goal=None,
                synthesis_result=QuerySynthesisResult(ok=False, error="failed", trace={}),
                trace_path="/runs/failed",
            )
            empty = store.record_from_synthesis(
                question="Покажи выручку",
                intent=data_intent("Покажи выручку"),
                goal=None,
                synthesis_result=successful_synthesis_result(rows=[]),
                trace_path="/runs/empty",
            )

        self.assertIsNone(failed)
        self.assertIsNone(empty)
        self.assertEqual(store.list_candidates(), [])

    def test_duplicate_question_and_query_are_deduplicated(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SynthesisCandidateStore(bot_instance_root=Path(temp_dir) / "bot")

            first = store.record_from_synthesis(
                question="Покажи выручку за 2025 год",
                intent=data_intent("Покажи выручку за 2025 год"),
                goal=None,
                synthesis_result=successful_synthesis_result(),
                trace_path="/runs/agent_1",
            )
            second = store.record_from_synthesis(
                question="Покажи выручку за 2025 год",
                intent=data_intent("Покажи выручку за 2025 год"),
                goal=None,
                synthesis_result=successful_synthesis_result(),
                trace_path="/runs/agent_2",
            )
            candidates = store.list_candidates()

        self.assertEqual(first.candidate_id if first else "", second.candidate_id if second else "different")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].seen_count, 2)
        self.assertEqual(candidates[0].trace_path, "/runs/agent_2")

    def test_candidate_can_be_rejected_ignored_and_converted_to_draft(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot"
            draft_store = HumanSkillDraftStore(bot_instance_root=bot, bot_id="client_a")
            store = SynthesisCandidateStore(bot_instance_root=bot, draft_store=draft_store)
            candidate = store.record_from_synthesis(
                question="Покажи выручку за 2025 год",
                intent=data_intent("Покажи выручку за 2025 год"),
                goal=None,
                synthesis_result=successful_synthesis_result(),
                trace_path="/runs/agent_1",
            )

            draft = store.create_draft(candidate.candidate_id, actor="expert")
            same_draft = store.create_draft(candidate.candidate_id, actor="expert")
            linked_candidate = store.get_candidate(candidate.candidate_id)
            draft_count = len(draft_store.list_drafts())
            rejected = store.reject_candidate(candidate.candidate_id, actor="expert", comment="Слишком частный запрос")
            ignored = store.ignore_similar(candidate.candidate_id, actor="expert", comment="Не создавать похожие")
            after_ignore = store.record_from_synthesis(
                question="Покажи выручку за 2025 год",
                intent=data_intent("Покажи выручку за 2025 год"),
                goal=None,
                synthesis_result=successful_synthesis_result(),
                trace_path="/runs/agent_2",
            )

        self.assertEqual(draft.source_kind, "query_synthesis_candidate")
        self.assertEqual(same_draft.draft_id, draft.draft_id)
        self.assertEqual(draft_count, 1)
        self.assertEqual(linked_candidate.payload["draft_id"], draft.draft_id)
        self.assertEqual(draft.example_questions, ["Покажи выручку за 2025 год"])
        self.assertEqual(draft.source_trace, "/runs/agent_1")
        self.assertEqual(draft.extras["synthesis_candidate"]["candidate_id"], candidate.candidate_id)
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(ignored.status, "ignored_similar")
        self.assertIsNone(after_ignore)

    def test_candidate_draft_conversion_reuses_legacy_draft_without_payload_link(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot"
            draft_store = HumanSkillDraftStore(bot_instance_root=bot, bot_id="client_a")
            store = SynthesisCandidateStore(bot_instance_root=bot, draft_store=draft_store)
            candidate = store.record_from_synthesis(
                question="Покажи выручку за 2025 год",
                intent=data_intent("Покажи выручку за 2025 год"),
                goal=None,
                synthesis_result=successful_synthesis_result(),
                trace_path="/runs/agent_1",
            )
            first = store.create_draft(candidate.candidate_id, actor="expert")

            candidate_path = bot / "workbench" / "candidates" / "synthesis" / f"{candidate.candidate_id}.json"
            raw = json.loads(candidate_path.read_text(encoding="utf-8"))
            raw["payload"].pop("draft_id", None)
            raw["payload"].pop("draft", None)
            candidate_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            reloaded = SynthesisCandidateStore(bot_instance_root=bot, draft_store=draft_store)
            listed = reloaded.list_candidates()
            second = reloaded.create_draft(candidate.candidate_id, actor="expert")
            linked_candidate = reloaded.get_candidate(candidate.candidate_id)
            draft_count = len(draft_store.list_drafts())

        self.assertEqual(listed[0].payload["draft_id"], first.draft_id)
        self.assertEqual(second.draft_id, first.draft_id)
        self.assertEqual(linked_candidate.payload["draft_id"], first.draft_id)
        self.assertEqual(draft_count, 1)

    def test_orchestrator_records_synthesis_candidate_on_success(self) -> None:
        question = "Покажи выручку за 2025 год"
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot"
            store = SynthesisCandidateStore(bot_instance_root=bot)
            orchestrator = AgentOrchestrator(
                registry=SkillRegistry(),
                decomposer=ScriptedGoalDecomposer({question: DecompositionResult(intent=data_intent(question), goal=data_goal(question))}),
                query_synthesizer=SuccessfulQuerySynthesizer(),
                synthesis_candidate_store=store,
                trace_root=Path(temp_dir) / "runs",
            )

            result = orchestrator.handle(question, session_id="s1")
            candidates = store.list_candidates()

        self.assertEqual(result.source, "query_synthesis_ok")
        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0].trace_path)


class SuccessfulQuerySynthesizer:
    def run(self, **kwargs) -> QuerySynthesisResult:
        return successful_synthesis_result()


def data_intent(question: str) -> IntentResult:
    return IntentResult(
        intent_type=IntentType.DATA_QUESTION,
        business_goal=question,
        requires_1c_data=True,
        expected_output="table",
        domain_terms=["выручка"],
        relevant=True,
    )


def data_goal(question: str) -> GoalDecomposition:
    return GoalDecomposition(
        business_goal=question,
        final_artifact_type="TypedTable",
        expected_answer_type="table",
        required_artifacts=[ArtifactRequirement(name="answer", type="TypedTable")],
    )


def successful_synthesis_result(rows=None) -> QuerySynthesisResult:
    data_rows = [{"Год": 2025, "Выручка": 1000}] if rows is None else rows
    return QuerySynthesisResult(
        ok=True,
        final_artifact=Artifact(
            name="answer",
            type="TypedTable",
            value={"columns": ["Год", "Выручка"], "rows": data_rows},
            provenance=["query_synthesis"],
        ),
        message="Выручка за 2025 год: 1000.",
        trace={
            "final_query": {
                "query": "ВЫБРАТЬ ГОД(Продажи.Период) КАК Год, СУММА(Продажи.Выручка) КАК Выручка ИЗ РегистрНакопления.Продажи.Обороты() КАК Продажи СГРУППИРОВАТЬ ПО ГОД(Продажи.Период)",
                "params": {},
                "limit": 100,
            },
            "row_count": len(data_rows),
            "metadata_objects": [
                {
                    "full_name": "РегистрНакопления.Продажи",
                    "fields": ["Период", "Выручка"],
                    "_source": "metadata_xml",
                    "_trust": "verified",
                }
            ],
        },
    )


if __name__ == "__main__":
    unittest.main()

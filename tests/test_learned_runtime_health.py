from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.conversation.context import ConversationContext
from wiicon5.execution.artifacts import Artifact
from wiicon5.execution.runtime import SkillRunResult
from wiicon5.models import SkillContract
from wiicon5.skills.learned import LearnedSkillRuntimeHealthStore, auto_learning_report
from wiicon5.skills.registry import SkillRegistry


class LearnedRuntimeHealthTests(unittest.TestCase):
    def test_runtime_health_auto_blocks_learned_skill_after_repeated_failures(self) -> None:
        with TemporaryDirectory() as temp_dir:
            skills_dir = Path(temp_dir) / "skills"
            active_dir = skills_dir / "learned" / "active"
            active_dir.mkdir(parents=True)
            skill = learned_skill("learned_empty_stock")
            skill_path = active_dir / "learned_empty_stock.json"
            skill_path.write_text(json.dumps(skill.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            registry = SkillRegistry([skill])
            tracker = LearnedSkillRuntimeHealthStore(skills_dir=skills_dir, registry=registry, failure_threshold=2)
            context = ConversationContext(session_id="s1", config_fingerprint="cfg")
            context.append_message("user", "Покажи остатки товара")
            empty_result = SkillRunResult(
                ok=True,
                skill_id=skill.skill_id,
                artifacts=[Artifact(name="table", type="StockBalanceTable", value={"columns": ["Склад"], "rows": []})],
            )

            tracker.record(skill, empty_result, context, invocation_id="n1", inputs={"limit": 10})
            tracker.record(skill, empty_result, context, invocation_id="n2", inputs={"limit": 10})

            payload = json.loads(skill_path.read_text(encoding="utf-8"))
            health = payload["implementation"]["runtime_health"]

        self.assertEqual(health["reuse_count"], 2)
        self.assertEqual(health["failure_count"], 2)
        self.assertTrue(health["auto_blocked"])
        self.assertNotIn(skill.skill_id, [item.skill_id for item in registry.active()])

    def test_runtime_health_records_success_and_learning_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            skills_dir = Path(temp_dir) / "skills"
            active_dir = skills_dir / "learned" / "active"
            active_dir.mkdir(parents=True)
            skill = learned_skill("learned_price_lookup")
            skill_path = active_dir / "learned_price_lookup.json"
            skill_path.write_text(json.dumps(skill.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            registry = SkillRegistry([skill])
            tracker = LearnedSkillRuntimeHealthStore(skills_dir=skills_dir, registry=registry, failure_threshold=3)
            context = ConversationContext(session_id="s1", config_fingerprint="cfg")
            context.append_message("user", "Покажи розничные цены на куртки")
            result = SkillRunResult(
                ok=True,
                skill_id=skill.skill_id,
                artifacts=[
                    Artifact(
                        name="table",
                        type="PriceTable",
                        value={"columns": ["Номенклатура", "Цена"], "rows": [{"Номенклатура": "Куртка", "Цена": 34000}]},
                    )
                ],
            )

            tracker.record(skill, result, context, invocation_id="n1", inputs={"limit": 10})
            report = auto_learning_report(skills_dir)

        self.assertEqual(report["summary"]["auto_learned_created_total"], 1)
        self.assertEqual(report["summary"]["auto_learned_reused_total"], 1)
        self.assertEqual(report["summary"]["auto_learned_failed_total"], 0)
        self.assertEqual(report["skills"][0]["runtime_health"]["success_count"], 1)
        self.assertEqual(report["skills"][0]["reused_for"], ["Покажи розничные цены на куртки"])


def learned_skill(skill_id: str) -> SkillContract:
    return SkillContract.from_dict(
        {
            "skill_id": skill_id,
            "version": "0.1.0",
            "kind": "data_acquisition",
            "status": "verified",
            "description": "Learned query for tests.",
            "capabilities": ["learned_query", "produce:StockBalanceTable"],
            "inputs": [{"name": "filters", "type": "SemanticFilterList", "required": False}],
            "outputs": [{"name": "table", "type": "StockBalanceTable"}],
            "implementation_strategy": "learned_query",
            "implementation": {
                "kind": "parameterized_lookup_query",
                "query": "ВЫБРАТЬ 1 КАК Значение",
                "params": {},
                "activation_mode": "auto_active",
                "created_by": "agent",
                "runtime_health": {
                    "reuse_count": 0,
                    "success_count": 0,
                    "failure_count": 0,
                    "consecutive_failures": 0,
                    "last_used_at": "",
                    "last_error": "",
                    "auto_blocked": False,
                },
                "evidence": {
                    "question": "Тестовый вопрос",
                    "human_confirmed": False,
                    "created_by": "agent",
                },
            },
        }
    )


if __name__ == "__main__":
    unittest.main()

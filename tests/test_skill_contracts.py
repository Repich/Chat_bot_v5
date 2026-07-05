from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.models import Port, SkillContract, SkillKind, SkillStatus
from wiicon5.skills.registry import SkillRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def test_seed_skills_load_from_files(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")

        skill = registry.get("get_warehouses")

        self.assertIsNotNone(skill)
        self.assertEqual(skill.kind, SkillKind.DATA)
        self.assertEqual(skill.status, SkillStatus.VERIFIED)
        self.assertTrue(skill.produces("WarehouseRefList"))
        self.assertIn("warehouse_type", skill.supported_filter_roles)
        self.assertNotIn("*", skill.supported_filter_roles)

    def test_registry_finds_compatible_output_candidates(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")

        candidates = registry.by_output_type("WarehouseRefList")

        self.assertEqual([skill.skill_id for skill in candidates], ["get_warehouses"])

    def test_registry_does_not_plan_candidate_skills_by_default(self) -> None:
        registry = SkillRegistry(
            [
                SkillContract(
                    skill_id="candidate_stock",
                    version="0.1.0",
                    kind=SkillKind.DATA,
                    status=SkillStatus.CANDIDATE,
                    description="Candidate skill",
                    capabilities=["candidate_stock"],
                    inputs=[],
                    outputs=[Port(name="rows", type="StockBalanceTable")],
                ),
                SkillContract(
                    skill_id="verified_stock",
                    version="0.1.0",
                    kind=SkillKind.DATA,
                    status=SkillStatus.VERIFIED,
                    description="Verified skill",
                    capabilities=["verified_stock"],
                    inputs=[],
                    outputs=[Port(name="rows", type="StockBalanceTable")],
                ),
            ]
        )

        candidates = registry.by_output_type("StockBalanceTable")

        self.assertEqual([skill.skill_id for skill in candidates], ["verified_stock"])

    def test_transfer_document_count_skill_loads(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")

        skill = registry.get("count_transfer_documents_by_day")

        self.assertIsNotNone(skill)
        assert skill is not None
        self.assertEqual(skill.kind, SkillKind.DATA)
        self.assertTrue(skill.produces("DocumentCountByPeriodTable"))
        self.assertEqual(skill.implementation_strategy, "semantic_document_count_query")

    def test_registry_ignores_non_skill_json_under_skills(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "skill.json").write_text(
                """
                {
                  "skill_id": "test_skill",
                  "kind": "presentation",
                  "status": "stable",
                  "outputs": [{"name": "answer", "type": "UserAnswer"}]
                }
                """,
                encoding="utf-8",
            )
            (root / "bindings").mkdir()
            (root / "bindings" / "binding.json").write_text('{"skill_id":"test_skill","fields":{}}', encoding="utf-8")

            registry = SkillRegistry.load_from_dir(root)

        self.assertIsNotNone(registry.get("test_skill"))
        self.assertEqual(len(registry.all()), 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from wiicon5.models import GapResolution, SkillGap
from wiicon5.skills.lifecycle import SkillEvolutionPolicy


class SkillLifecycleTests(unittest.TestCase):
    def test_policy_rejects_new_narrow_skill_when_gap_is_filter_extension(self) -> None:
        gap = SkillGap(
            required_capability="filter:WarehouseRefList",
            required_output="WarehouseRefList",
            reason="Need one more semantic filter.",
            nearest_skill_ids=["get_warehouses"],
            recommended_resolution=GapResolution.EXTEND_EXISTING,
            missing=["filter:warehouse_type"],
        )
        policy = SkillEvolutionPolicy()

        decision = policy.decide(gap)

        self.assertEqual(decision.decision, GapResolution.EXTEND_EXISTING)
        self.assertTrue(decision.forbidden_new_skill)
        self.assertTrue(policy.rejects_new_skill_for_gap(gap, "get_wholesale_warehouses"))
        self.assertFalse(policy.rejects_new_skill_for_gap(gap, "get_warehouses"))


if __name__ == "__main__":
    unittest.main()


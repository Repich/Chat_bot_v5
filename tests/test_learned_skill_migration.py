from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.skills.migration import quarantine_legacy_learned_skills
from wiicon5.skills.registry import SkillRegistry


class LearnedSkillMigrationTests(unittest.TestCase):
    def test_legacy_active_skill_is_quarantined_and_not_loaded(self) -> None:
        with TemporaryDirectory() as temp_dir:
            skills_dir = Path(temp_dir) / "skills"
            active_dir = skills_dir / "learned" / "active"
            active_dir.mkdir(parents=True)
            legacy_path = active_dir / "legacy.json"
            legacy_path.write_text(json.dumps(skill_payload("legacy", "period_metric_aggregate", 0)), encoding="utf-8")

            result = quarantine_legacy_learned_skills(skills_dir)
            registry = SkillRegistry.load_from_dir(skills_dir)

            self.assertFalse(legacy_path.exists())
            self.assertEqual(len(result.moved), 1)
            self.assertIsNone(registry.get("legacy"))
            self.assertTrue(Path(result.moved[0]["destination"]).exists())

    def test_current_semantic_template_remains_active(self) -> None:
        with TemporaryDirectory() as temp_dir:
            skills_dir = Path(temp_dir) / "skills"
            active_dir = skills_dir / "learned" / "active"
            active_dir.mkdir(parents=True)
            current_path = active_dir / "current.json"
            current_path.write_text(json.dumps(skill_payload("current", "semantic_query_template", 2)), encoding="utf-8")

            result = quarantine_legacy_learned_skills(skills_dir)
            registry = SkillRegistry.load_from_dir(skills_dir)

            self.assertTrue(current_path.exists())
            self.assertFalse(result.moved)
            self.assertIsNotNone(registry.get("current"))

    def test_registry_never_loads_skill_contract_from_quarantine(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "skills"
            path = root / "learned" / "quarantine" / "old.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(skill_payload("old", "semantic_query_template", 2)), encoding="utf-8")

            registry = SkillRegistry.load_from_dir(root)

            self.assertIsNone(registry.get("old"))


def skill_payload(skill_id: str, implementation_kind: str, schema_version: int) -> dict:
    return {
        "skill_id": skill_id,
        "kind": "data_acquisition",
        "status": "verified",
        "description": skill_id,
        "outputs": [{"name": "table", "type": "LearnedQueryTable"}],
        "implementation_strategy": "learned_query",
        "semantic_contract": {
            "schema_version": schema_version,
            "subject_terms": ["данные"],
            "operation": "list",
        },
        "implementation": {
            "kind": implementation_kind,
            "schema_version": schema_version,
            "query": "ВЫБРАТЬ 1 КАК Значение ИЗ Справочник.Номенклатура КАК Номенклатура",
        },
    }


if __name__ == "__main__":
    unittest.main()

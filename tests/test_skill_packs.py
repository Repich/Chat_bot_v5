from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.models import Port, SkillBinding, SkillContract, SkillKind, SkillStatus
from wiicon5.skills.packs import export_skill_pack, import_skill_pack, save_skill_pack
from wiicon5.workbench.audit import WorkbenchAuditLog


class SkillPackTests(unittest.TestCase):
    def test_export_and_import_skill_pack_as_candidate(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            global_skills = root / "skills"
            source_bot = root / "bot_instances" / "source"
            target_bot = root / "bot_instances" / "target"
            bindings = root / "bindings"
            write_skill(global_skills / "atomic" / "data" / "cash.json", skill_contract("cash_balance"))
            write_binding(bindings / "local" / "cash_balance.binding.json", skill_binding("cash_balance"))

            pack = export_skill_pack(
                skill_ids=["cash_balance"],
                global_skills_dir=global_skills,
                bot_instance_root=source_bot,
                include_bindings=True,
                bindings_dirs=[bindings],
            )
            pack_path = root / "cash_pack.json"
            save_skill_pack(pack, pack_path)
            imported = import_skill_pack(
                pack_path=pack_path,
                bot_instance_root=target_bot,
                include_bindings=True,
                actor="consultant",
            )
            imported_skill_path = target_bot / "skills" / "candidates" / "cash_balance.json"
            imported_binding_path = target_bot / "skills" / "bindings" / "local" / "cash_balance.binding.json"
            imported_skill = json.loads(imported_skill_path.read_text(encoding="utf-8"))
            binding_exists = imported_binding_path.exists()
            events = WorkbenchAuditLog(
                target_bot / "workbench" / "audit" / "events.jsonl",
                bot_id="target",
            ).read()
            skipped = import_skill_pack(pack_path=pack_path, bot_instance_root=target_bot)

        self.assertEqual(pack["summary"]["skills"], 1)
        self.assertEqual(pack["summary"]["bindings"], 1)
        self.assertTrue(imported["ok"], imported)
        self.assertEqual(imported_skill["status"], "candidate")
        self.assertIn("imported_pack", imported_skill["tags"])
        self.assertEqual(imported_skill["implementation"]["imported_pack"]["original_status"], "stable")
        self.assertTrue(binding_exists)
        self.assertIn("skill_pack.imported_skill", [event.event_type for event in events])
        self.assertFalse(skipped["ok"])
        self.assertEqual(skipped["skipped"][0]["reason"], "already_exists")

    def test_export_reports_missing_skill_ids(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            pack = export_skill_pack(
                skill_ids=["missing_skill"],
                global_skills_dir=root / "skills",
                bot_instance_root=root / "bot_instances" / "local",
            )

        self.assertEqual(pack["summary"]["missing"], 1)
        self.assertEqual(pack["missing_skill_ids"], ["missing_skill"])


def skill_contract(skill_id: str) -> SkillContract:
    return SkillContract(
        skill_id=skill_id,
        version="1.0.0",
        kind=SkillKind.DATA,
        status=SkillStatus.STABLE,
        description="Cash balance",
        capabilities=["cash", "balance"],
        inputs=[],
        outputs=[Port(name="rows", type="TypedTable")],
        tags=["finance"],
        implementation_strategy="workbench_preview_query",
        implementation={"query": "ВЫБРАТЬ 1 КАК Остаток"},
    )


def skill_binding(skill_id: str) -> SkillBinding:
    return SkillBinding(
        skill_id=skill_id,
        config_fingerprint="local",
        semantic_role="cash_balance",
        one_c_object={"full_name": "РегистрНакопления.ДенежныеСредства"},
        fields={"cashbox": "Касса", "amount": "СуммаОстаток"},
        confidence=1.0,
        evidence=["test"],
    )


def write_skill(path: Path, skill: SkillContract) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(skill.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def write_binding(path: Path, binding: SkillBinding) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(binding.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

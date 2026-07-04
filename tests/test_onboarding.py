from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.onboarding import run_onboarding
from wiicon5.onboarding.config_dump_reader import read_config_dump
from wiicon5.onboarding.metadata_index_builder import extract_metadata_objects
from wiicon5.onboarding.query_pattern_extractor import extract_query_patterns


class OnboardingTests(unittest.TestCase):
    def test_onboarding_writes_candidates_without_creating_skills(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dump = root / "config_dump"
            bot = root / "bot_instances" / "client_a"
            module = dump / "Documents" / "РеализацияТоваровУслуг" / "Module.bsl"
            module.parent.mkdir(parents=True)
            module.write_text(
                """
                // Документ.РеализацияТоваровУслуг
                Движения.ВыручкаИСебестоимостьПродаж.Записывать = Истина;
                Запрос.Текст =
                "ВЫБРАТЬ
                    Реализация.Ссылка КАК Ссылка
                 ИЗ
                    Документ.РеализацияТоваровУслуг КАК Реализация";
                """,
                encoding="utf-8",
            )
            catalog = dump / "Catalogs" / "Склады" / "metadata.txt"
            catalog.parent.mkdir(parents=True)
            catalog.write_text("Справочник.Склады\nРеквизит.ТипСклада\n", encoding="utf-8")

            result = run_onboarding(config_dump=dump, bot_instance=bot, mcp_url="http://127.0.0.1:6003")

            onboarding_dir = bot / "onboarding"
            bindings = json.loads((onboarding_dir / "candidate_bindings.json").read_text(encoding="utf-8"))
            register_usage = json.loads((onboarding_dir / "register_usage_map.json").read_text(encoding="utf-8"))
            query_patterns = (onboarding_dir / "candidate_query_patterns.jsonl").read_text(encoding="utf-8")
            report = (onboarding_dir / "onboarding_report.md").read_text(encoding="utf-8")
            with sqlite3.connect(onboarding_dir / "metadata_index.sqlite") as connection:
                object_count = connection.execute("SELECT COUNT(*) FROM objects").fetchone()[0]

        self.assertEqual(result.files_read, 2)
        self.assertGreaterEqual(result.objects_count, 2)
        self.assertGreaterEqual(object_count, 2)
        self.assertIn("warehouse", json.dumps(bindings, ensure_ascii=False))
        self.assertIn("РегистрНакопления.ВыручкаИСебестоимостьПродаж", json.dumps(register_usage, ensure_ascii=False))
        self.assertIn("Документ.РеализацияТоваровУслуг", query_patterns)
        self.assertIn("candidates only", report)
        self.assertFalse((bot / "skills").exists())

    def test_dump_reader_and_extractors_are_deterministic(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dump = Path(temp_dir)
            (dump / "object.bsl").write_text(
                "Справочник.Номенклатура\nВЫБРАТЬ Номенклатура.Ссылка КАК Ссылка ИЗ Справочник.Номенклатура КАК Номенклатура;",
                encoding="utf-8",
            )

            files = read_config_dump(dump)
            objects = extract_metadata_objects(files)
            queries = extract_query_patterns(files)

        self.assertEqual([item.relative_path for item in files], ["object.bsl"])
        self.assertEqual([item.full_name for item in objects], ["Справочник.Номенклатура"])
        self.assertEqual(len(queries), 1)


if __name__ == "__main__":
    unittest.main()

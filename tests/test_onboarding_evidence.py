from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.knowledge.metadata import MetadataObject
from wiicon5.knowledge.onboarding_evidence import OnboardingEvidenceProvider


class OnboardingEvidenceProviderTests(unittest.TestCase):
    def test_returns_matching_register_usage_and_query_patterns(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "register_usage_map.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "document": "Документ.РеализацияТоваровУслуг",
                                "registers": ["РегистрНакопления.ВыручкаИСебестоимостьПродаж"],
                                "source_file": "Documents/РеализацияТоваровУслуг/Module.bsl",
                            },
                            {
                                "document": "Документ.ПриобретениеТоваровУслуг",
                                "registers": ["РегистрНакопления.РасчетыСПоставщиками"],
                                "source_file": "Documents/ПриобретениеТоваровУслуг/Module.bsl",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "candidate_query_patterns.jsonl").write_text(
                json.dumps(
                    {
                        "pattern_id": "q1",
                        "source_file": "Reports/Продажи.bsl",
                        "query": "ВЫБРАТЬ Продажи.Выручка ИЗ РегистрНакопления.ВыручкаИСебестоимостьПродаж.Обороты КАК Продажи",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            evidence = OnboardingEvidenceProvider(root).evidence_for(
                search_terms=["выручка"],
                metadata_objects=[MetadataObject(full_name="РегистрНакопления.ВыручкаИСебестоимостьПродаж")],
            )

        self.assertTrue(evidence["available"])
        self.assertEqual(
            evidence["register_usage"][0]["document"],
            "Документ.РеализацияТоваровУслуг",
        )
        self.assertEqual(evidence["query_patterns"][0]["pattern_id"], "q1")

    def test_large_register_usage_is_bounded_and_reports_truncation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registers = [f"РегистрНакопления.Тестовый{index:03d}" for index in range(100)]
            registers.append("РегистрНакопления.ДоставкаЗаказов")
            (root / "register_usage_map.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "document": "Документ.ЗаказТребование",
                                "registers": registers,
                                "source_file": "Documents/ЗаказТребование/Module.bsl",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            evidence = OnboardingEvidenceProvider(root).evidence_for(
                search_terms=["доставка"],
                metadata_objects=[MetadataObject(full_name="Документ.ЗаказТребование")],
            )

        row = evidence["register_usage"][0]
        self.assertEqual(len(row["registers"]), 10)
        self.assertEqual(row["registers"][0], "РегистрНакопления.ДоставкаЗаказов")
        self.assertEqual(row["registers_total"], 101)
        self.assertTrue(row["registers_truncated"])


if __name__ == "__main__":
    unittest.main()

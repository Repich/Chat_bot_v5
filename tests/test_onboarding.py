from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.onboarding import run_onboarding
from wiicon5.onboarding.config_dump_reader import read_config_dump
from wiicon5.onboarding.metadata_index_builder import extract_metadata_objects
from wiicon5.mcp.client import DictMcpClient
from wiicon5.onboarding.binding_candidate_verifier import verify_binding_candidates
from wiicon5.onboarding.onec_xml_parser import parse_metadata_xml
from wiicon5.onboarding.query_pattern_extractor import extract_query_patterns
from wiicon5.onboarding.status import OnboardingManager


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

    def test_xml_metadata_parser_extracts_verified_register_structure(self) -> None:
        parsed = parse_metadata_xml(
            """
            <MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses">
              <AccumulationRegister>
                <Properties>
                  <Name>ДенежныеСредства</Name>
                  <Synonym><item><lang>ru</lang><content>Денежные средства</content></item></Synonym>
                </Properties>
                <ChildObjects>
                  <Dimension>
                    <Properties>
                      <Name>Касса</Name>
                      <Synonym><item><lang>ru</lang><content>Касса</content></item></Synonym>
                      <Type>cfg:CatalogRef.Кассы</Type>
                    </Properties>
                  </Dimension>
                  <Resource>
                    <Properties>
                      <Name>Сумма</Name>
                      <Type>xs:decimal</Type>
                    </Properties>
                  </Resource>
                </ChildObjects>
              </AccumulationRegister>
            </MetaDataObject>
            """,
            relative_path="AccumulationRegisters/ДенежныеСредства.xml",
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.full_name, "РегистрНакопления.ДенежныеСредства")
        self.assertEqual([field.name for field in parsed.fields], ["Касса", "Сумма"])
        self.assertEqual(parsed.fields[0].category, "dimension")
        self.assertEqual(parsed.fields[0].type_text, "СправочникСсылка.Кассы")

    def test_metadata_index_marks_xml_fields_as_verified_and_bsl_fields_as_hints(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dump = Path(temp_dir)
            (dump / "Catalogs" / "Склады.xml").parent.mkdir(parents=True)
            (dump / "Catalogs" / "Склады.xml").write_text(
                """
                <MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses">
                  <Catalog>
                    <Properties><Name>Склады</Name></Properties>
                    <ChildObjects>
                      <Attribute><Properties><Name>ТипСклада</Name><Type>cfg:EnumRef.ТипыСкладов</Type></Properties></Attribute>
                    </ChildObjects>
                  </Catalog>
                </MetaDataObject>
                """,
                encoding="utf-8",
            )
            (dump / "Documents" / "Заказ" / "Module.bsl").parent.mkdir(parents=True)
            (dump / "Documents" / "Заказ" / "Module.bsl").write_text(
                "Документ.Заказ\nРеквизит.СуммаДокумента\n",
                encoding="utf-8",
            )

            objects = {item.full_name: item for item in extract_metadata_objects(read_config_dump(dump))}

        self.assertEqual(objects["Справочник.Склады"].trust, "verified")
        self.assertEqual(objects["Справочник.Склады"].field_details["ТипСклада"].source, "metadata_xml")
        self.assertEqual(objects["Документ.Заказ"].trust, "hint")
        self.assertEqual(objects["Документ.Заказ"].field_details["СуммаДокумента"].trust, "hint")

    def test_onboarding_manager_tracks_training_status(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dump = root / "config_dump"
            bot = root / "bot_instances" / "client_a"
            (dump / "Catalogs" / "Номенклатура" / "metadata.txt").parent.mkdir(parents=True)
            (dump / "Catalogs" / "Номенклатура" / "metadata.txt").write_text(
                "Справочник.Номенклатура\nРеквизит.Артикул\n",
                encoding="utf-8",
            )
            manager = OnboardingManager(bot_instance_root=bot, mcp_url="http://127.0.0.1:6003")

            before = manager.status()
            after = manager.start(config_dump=dump, background=False)
            restored = OnboardingManager(bot_instance_root=bot).status()

        self.assertFalse(before.trained)
        self.assertEqual(after.state, "completed")
        self.assertTrue(after.trained)
        self.assertGreaterEqual(after.objects_count, 1)
        self.assertTrue(restored.trained)

    def test_binding_candidate_verifier_checks_candidates_against_mcp_metadata(self) -> None:
        mcp = DictMcpClient(
            {"success": True, "data": []},
            metadata_response={
                "success": True,
                "data": {
                    "ПолноеИмя": "Справочник.Склады",
                    "Реквизиты": [{"Имя": "ТипСклада", "Тип": "ПеречислениеСсылка.ТипыСкладов"}],
                },
                "returned": 1,
            },
        )

        result = verify_binding_candidates(
            [{"semantic_role": "warehouse", "object": "Справочник.Склады", "required_fields": ["ТипСклада"]}],
            mcp,
        )

        self.assertEqual(result[0].status, "verified_by_mcp")
        self.assertEqual(mcp.metadata_calls[0].filter, "Справочник.Склады")

    def test_binding_candidate_verifier_reuses_metadata_request_per_object(self) -> None:
        mcp = DictMcpClient(
            {"success": True, "data": []},
            metadata_response={
                "success": True,
                "data": {"ПолноеИмя": "Справочник.Склады", "Реквизиты": [{"Имя": "ТипСклада"}]},
                "returned": 1,
            },
        )

        result = verify_binding_candidates(
            [
                {"semantic_role": "warehouse", "object": "Справочник.Склады"},
                {"semantic_role": "warehouse_city", "object": "Справочник.Склады", "required_fields": ["ТипСклада"]},
            ],
            mcp,
        )

        self.assertEqual([item.status for item in result], ["verified_by_mcp", "verified_by_mcp"])
        self.assertEqual(len(mcp.metadata_calls), 1)


if __name__ == "__main__":
    unittest.main()

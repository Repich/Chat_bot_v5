from __future__ import annotations

import json
import unittest

from wiicon5.audit.trace_writer import TraceWriter
from wiicon5.query.one_c_query_safety import validate_read_only_query


class DeterministicPolicyTests(unittest.TestCase):
    def test_read_only_query_validator_accepts_select(self) -> None:
        result = validate_read_only_query(
            "ВЫБРАТЬ\n"
            "    Номенклатура.Ссылка КАК Ссылка\n"
            "ИЗ\n"
            "    Справочник.Номенклатура КАК Номенклатура"
        )

        self.assertTrue(result.ok)

    def test_read_only_query_validator_rejects_unsafe_query(self) -> None:
        result = validate_read_only_query("УДАЛИТЬ ИЗ Справочник.Номенклатура")

        self.assertFalse(result.ok)
        self.assertIn("not_select", [issue.code for issue in result.issues])
        self.assertIn("mutating_keyword", [issue.code for issue in result.issues])

    def test_read_only_query_validator_accepts_declared_parameters(self) -> None:
        result = validate_read_only_query(
            "ВЫБРАТЬ Ссылка ИЗ Справочник.Номенклатура ГДЕ Код = &Код",
            {"Код": "001"},
        )

        self.assertTrue(result.ok)

    def test_read_only_query_validator_rejects_undeclared_parameters(self) -> None:
        result = validate_read_only_query("ВЫБРАТЬ Ссылка ИЗ Справочник.Номенклатура ГДЕ Код = &Код")

        self.assertFalse(result.ok)
        self.assertIn("undeclared_parameter", [issue.code for issue in result.issues])

    def test_read_only_query_validator_rejects_date_parameter_outside_1c_range(self) -> None:
        result = validate_read_only_query(
            "ВЫБРАТЬ Ссылка ИЗ Справочник.Номенклатура ГДЕ ДатаИзменения <= &Дата",
            {"Дата": "9999-12-31T23:59:59"},
        )

        self.assertFalse(result.ok)
        self.assertIn("date_year_out_of_range", [issue.code for issue in result.issues])

    def test_read_only_query_validator_rejects_date_literal_outside_1c_range(self) -> None:
        result = validate_read_only_query(
            "ВЫБРАТЬ Ссылка ИЗ Справочник.Номенклатура ГДЕ ДатаИзменения <= ДАТАВРЕМЯ(9999, 12, 31)"
        )

        self.assertFalse(result.ok)
        self.assertIn("date_year_out_of_range", [issue.code for issue in result.issues])

    def test_read_only_query_validator_rejects_empty_guid_reference_parameter(self) -> None:
        result = validate_read_only_query(
            "ВЫБРАТЬ Ссылка ИЗ Справочник.Номенклатура ГДЕ ВидЦены = &ВидЦены",
            {"ВидЦены": "00000000-0000-0000-0000-000000000000"},
        )

        self.assertFalse(result.ok)
        self.assertIn("empty_reference_parameter", [issue.code for issue in result.issues])

    def test_read_only_query_validator_rejects_ambiguous_source_and_field_alias(self) -> None:
        result = validate_read_only_query(
            "ВЫБРАТЬ\n"
            "    Цены.Номенклатура КАК Номенклатура,\n"
            "    Цены.Цена КАК Цена\n"
            "ИЗ\n"
            "    РегистрСведений.ЦеныНоменклатуры КАК Цены\n"
            "        ВНУТРЕННЕЕ СОЕДИНЕНИЕ Справочник.Номенклатура КАК Номенклатура\n"
            "        ПО Цены.Номенклатура = Номенклатура.Ссылка\n"
            "ГДЕ\n"
            "    Номенклатура.Наименование ПОДОБНО \"%пиво%\""
        )

        self.assertFalse(result.ok)
        self.assertIn("ambiguous_alias", [issue.code for issue in result.issues])

    def test_trace_writer_records_structured_json(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as temp_dir:
            trace = TraceWriter(Path(temp_dir)).new_run(prefix="test")
            path = trace.write_json("skill_search/selected_skill_plan.json", {"ok": True})

            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["run_id"], trace.run_id)
        self.assertIn("ts", payload)


if __name__ == "__main__":
    unittest.main()

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

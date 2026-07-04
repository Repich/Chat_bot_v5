from __future__ import annotations

import unittest

from wiicon5.query.list_params import expand_in_list_parameters


class QueryListParameterTests(unittest.TestCase):
    def test_expands_single_array_param_in_in_operator_to_scalar_params(self) -> None:
        result = expand_in_list_parameters(
            query="ВЫБРАТЬ Склад.Ссылка ИЗ Справочник.Склады КАК Склад ГДЕ Склад.Ссылка В (&Склады)",
            params={"Склады": [{"_objectRef": True, "Представление": "Ларек"}]},
        )

        self.assertTrue(result.changed)
        self.assertIn("Склад.Ссылка В (&Склады_1)", result.query)
        self.assertNotIn("Склады", result.params)
        self.assertEqual(result.params["Склады_1"]["Представление"], "Ларек")

    def test_expands_multi_value_array_param_in_in_operator_to_scalar_params(self) -> None:
        result = expand_in_list_parameters(
            query="ГДЕ Остатки.Склад В (&Склады)",
            params={"Склады": ["warehouse-1", "warehouse-2"]},
        )

        self.assertEqual(result.query, "ГДЕ Остатки.Склад В (&Склады_1, &Склады_2)")
        self.assertEqual(result.params, {"Склады_1": "warehouse-1", "Склады_2": "warehouse-2"})

    def test_keeps_empty_array_param_for_existing_empty_list_guard(self) -> None:
        result = expand_in_list_parameters(
            query="ГДЕ Остатки.Склад В (&Склады)",
            params={"Склады": []},
        )

        self.assertFalse(result.changed)
        self.assertEqual(result.query, "ГДЕ Остатки.Склад В (&Склады)")
        self.assertEqual(result.params, {"Склады": []})


if __name__ == "__main__":
    unittest.main()

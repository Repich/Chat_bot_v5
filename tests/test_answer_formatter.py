from __future__ import annotations

import unittest

from wiicon5.llm.client import ScriptedLLMClient
from wiicon5.presentation.answer_formatter import format_user_answer
from wiicon5.presentation.llm_answer_formatter import LLMAnswerFormatter, metric_hints_from_query


class AnswerFormatterTests(unittest.TestCase):
    def test_formats_largest_document_row_as_readable_sentence(self) -> None:
        answer = format_user_answer(
            question="Покажи самый крупный заказ на продажу",
            columns=["Ссылка", "Номер", "Дата", "СуммаДокумента"],
            rows=[
                {
                    "Ссылка": "Заказ клиента 0000-000005 от 20.02.2024 12:12:12",
                    "Номер": "0000-000005",
                    "Дата": "2024-02-20T12:12:12Z",
                    "СуммаДокумента": 355243.19,
                }
            ],
        )

        self.assertEqual(
            answer,
            "Самый крупный по сумме заказ найден в системе. "
            "Это документ номер 0000-000005 от 20.02.2024 на сумму 355243.19.",
        )

    def test_keeps_table_for_multiple_rows_with_short_intro(self) -> None:
        answer = format_user_answer(
            question="Покажи остатки по складам",
            columns=["Склад", "Остаток"],
            rows=[
                {"Склад": "Основной склад", "Остаток": 10},
                {"Склад": "Резервный склад", "Остаток": 5},
            ],
        )

        self.assertIn("Найдено строк: 2.", answer)
        self.assertIn("Склад | Остаток", answer)
        self.assertIn("Основной склад | 10", answer)

    def test_formats_top_single_metric_without_raw_table(self) -> None:
        answer = format_user_answer(
            question="Покажи самую продающуюся номенклатуру",
            columns=["Номенклатура", "КоличествоПродаж"],
            rows=[{"Номенклатура": "Телевизор Темп", "КоличествоПродаж": 31}],
        )

        self.assertEqual(answer, "Найден результат с наибольшим значением показателя: Телевизор Темп — 31.")

    def test_formats_single_aggregate_metric_as_readable_sentence(self) -> None:
        answer = format_user_answer(
            question="Покажи суммы всех реализаций за 2024 год",
            columns=["Сумма"],
            rows=[{"Сумма": 1592608.73}],
        )

        self.assertEqual(answer, "Сумма реализаций: 1592608.73.")

    def test_rounds_single_average_metric(self) -> None:
        answer = format_user_answer(
            question="Покажи среднюю стоимость реализаций за 2024 год",
            columns=["СредняяСтоимость"],
            rows=[{"СредняяСтоимость": 7547.908673}],
        )

        self.assertEqual(answer, "Средняя стоимость реализаций: 7547.91.")

    def test_llm_formatter_can_explain_query_metric_semantics(self) -> None:
        llm = ScriptedLLMClient(
            [
                {
                    "answer": "В 2024 году больше всего товаров взял клиент Альфа — 58 единиц товара по проведенным реализациям.",
                    "reasoning": "КоличествоТоваров is СУММА(Товары.Количество), so it means total item units.",
                }
            ]
        )
        formatter = LLMAnswerFormatter(llm)

        result = formatter.format(
            question="Какой клиент брал больше всего товаров в 2024 году?",
            query=(
                "ВЫБРАТЬ ПЕРВЫЕ 1 Реализация.Контрагент КАК Клиент, "
                "СУММА(Товары.Количество) КАК КоличествоТоваров "
                "ИЗ Документ.РеализацияТоваровУслуг КАК Реализация "
                "ЛЕВОЕ СОЕДИНЕНИЕ Документ.РеализацияТоваровУслуг.Товары КАК Товары "
                "ПО Товары.Ссылка = Реализация.Ссылка"
            ),
            params={},
            columns=["Клиент", "КоличествоТоваров"],
            rows=[{"Клиент": "Альфа", "КоличествоТоваров": 58}],
            fallback_answer="Найден результат с наибольшим значением показателя: Альфа — 58.",
        )

        self.assertTrue(result.ok)
        self.assertIn("58 единиц товара", result.answer)
        self.assertIn("СУММА(Товары.Количество)", llm.calls[0]["user_payload"]["query"])
        self.assertEqual(
            llm.calls[0]["user_payload"]["metric_hints"],
            [
                {
                    "column": "КоличествоТоваров",
                    "expression": "СУММА(Товары.Количество)",
                    "meaning": (
                        "суммарное количество единиц/штук по строкам запроса; "
                        "это не количество разных номенклатур"
                    ),
                }
            ],
        )

    def test_llm_formatter_rejects_answer_without_returned_facts(self) -> None:
        llm = ScriptedLLMClient([{"answer": "Данные успешно найдены.", "reasoning": "Too generic."}])
        formatter = LLMAnswerFormatter(llm)

        result = formatter.format(
            question="Какой клиент брал больше всего товаров в 2024 году?",
            query="ВЫБРАТЬ Клиент, КоличествоТоваров",
            params={},
            columns=["Клиент", "КоличествоТоваров"],
            rows=[{"Клиент": "Альфа", "КоличествоТоваров": 58}],
            fallback_answer="Найден результат с наибольшим значением показателя: Альфа — 58.",
        )

        self.assertFalse(result.ok)
        self.assertIn("did not mention", result.error)

    def test_metric_hints_distinguish_total_quantity_from_distinct_items(self) -> None:
        query = (
            "ВЫБРАТЬ\n"
            "    ЗаказТовары.Номенклатура КАК Номенклатура,\n"
            "    СУММА(ЗаказТовары.Количество) КАК КоличествоТоваров,\n"
            "    КОЛИЧЕСТВО(РАЗЛИЧНЫЕ ЗаказТовары.Номенклатура) КАК РазныхНоменклатур\n"
            "ИЗ Документ.ЗаказКлиента.Товары КАК ЗаказТовары"
        )

        hints = metric_hints_from_query(query, ["Номенклатура", "КоличествоТоваров", "РазныхНоменклатур"])

        self.assertEqual(
            hints,
            [
                {
                    "column": "КоличествоТоваров",
                    "expression": "СУММА(ЗаказТовары.Количество)",
                    "meaning": (
                        "суммарное количество единиц/штук по строкам запроса; "
                        "это не количество разных номенклатур"
                    ),
                },
                {
                    "column": "РазныхНоменклатур",
                    "expression": "КОЛИЧЕСТВО(РАЗЛИЧНЫЕ ЗаказТовары.Номенклатура)",
                    "meaning": "количество разных уникальных значений ЗаказТовары.Номенклатура",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from wiicon5.knowledge.metadata import metadata_object_from_payload
from wiicon5.knowledge.one_c_wiki import EmbeddedOneCWiki
from wiicon5.query.one_c_query_review import OneCQueryReviewer


class EmbeddedOneCWikiTests(unittest.TestCase):
    def test_embedded_wiki_search_uses_packaged_pages(self) -> None:
        wiki = EmbeddedOneCWiki()

        hits = wiki.search("регистры накопления Активность Остатки Обороты", top_k=3)

        self.assertTrue(hits)
        self.assertTrue(any("accumulation-register-query-review" in hit.path for hit in hits))
        self.assertTrue(all("WorkAssistant4.0" not in hit.path for hit in hits))


class OneCQueryReviewerTests(unittest.TestCase):
    def test_rejects_raw_accumulation_register_without_activity(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                СУММА(Движения.Сумма) КАК Сумма
            ИЗ
                РегистрНакопления.ДенежныеСредства КАК Движения
            """,
            params={},
            metadata_objects=[money_register_metadata()],
        )

        self.assertFalse(result.ok)
        self.assertIn("raw_accumulation_register_without_activity", [issue.code for issue in result.issues])
        self.assertTrue(result.evidence_pack["wiki_hits"])

    def test_accepts_raw_accumulation_register_with_activity(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                СУММА(Движения.Сумма) КАК Сумма
            ИЗ
                РегистрНакопления.ДенежныеСредства КАК Движения
            ГДЕ
                Движения.Активность
            """,
            params={},
            metadata_objects=[money_register_metadata()],
        )

        self.assertTrue(result.ok)

    def test_rejects_activity_filter_on_accumulation_virtual_table(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                Остатки.Касса КАК Касса,
                Остатки.СуммаОстаток КАК Остаток
            ИЗ
                РегистрНакопления.ДенежныеСредства.Остатки() КАК Остатки
            ГДЕ
                Остатки.Активность
            """,
            params={},
            metadata_objects=[money_register_metadata()],
        )

        self.assertFalse(result.ok)
        self.assertIn("activity_filter_on_virtual_table", [issue.code for issue in result.issues])

    def test_accepts_accumulation_virtual_table_without_explicit_parentheses(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                Обороты.Касса КАК Касса,
                Обороты.СуммаОборот КАК Оборот
            ИЗ
                РегистрНакопления.ДенежныеСредства.Обороты КАК Обороты
            """,
            params={},
            metadata_objects=[money_register_metadata()],
        )

        self.assertTrue(result.ok)

    def test_rejects_reference_field_compared_to_plain_string_param(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                Остатки.Касса КАК Касса,
                Остатки.СуммаОстаток КАК Остаток
            ИЗ
                РегистрНакопления.ДенежныеСредства.Остатки() КАК Остатки
            ГДЕ
                Остатки.Касса = &Касса
            """,
            params={"Касса": "Основная касса"},
            metadata_objects=[money_register_metadata()],
        )

        self.assertFalse(result.ok)
        self.assertIn("reference_filter_string_param", [issue.code for issue in result.issues])

    def test_accepts_reference_field_name_attribute_compared_to_string_param(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                Остатки.Касса КАК Касса,
                Остатки.СуммаОстаток КАК Остаток
            ИЗ
                РегистрНакопления.ДенежныеСредства.Остатки() КАК Остатки
            ГДЕ
                Остатки.Касса.Наименование = &Касса
            """,
            params={"Касса": "Основная касса"},
            metadata_objects=[money_register_metadata()],
        )

        self.assertTrue(result.ok)

    def test_rejects_source_not_confirmed_by_metadata(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                Продажи.Номенклатура КАК Номенклатура
            ИЗ
                РегистрНакопления.Продажи.Обороты() КАК Продажи
            """,
            params={},
            metadata_objects=[money_register_metadata()],
        )

        self.assertFalse(result.ok)
        self.assertIn("source_not_confirmed_by_metadata", [issue.code for issue in result.issues])

    def test_rejects_document_table_part_without_document_link(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                Товары.Номенклатура КАК Номенклатура,
                СУММА(Товары.Количество) КАК Количество
            ИЗ
                Документ.РеализацияТоваровУслуг.Товары КАК Товары
            СГРУППИРОВАТЬ ПО
                Товары.Номенклатура
            """,
            params={},
            metadata_objects=[sales_document_metadata()],
        )

        self.assertFalse(result.ok)
        self.assertIn("document_table_part_without_document_ref", [issue.code for issue in result.issues])


def money_register_metadata():
    return metadata_object_from_payload(
        {
            "ПолноеИмя": "РегистрНакопления.ДенежныеСредства",
            "Синоним": "Денежные средства",
            "Измерения": [{"Имя": "Касса", "Тип": "СправочникСсылка.Кассы"}],
            "Ресурсы": [{"Имя": "Сумма", "Тип": "Число(15, 2)"}],
        }
    )


def sales_document_metadata():
    return metadata_object_from_payload(
        {
            "ПолноеИмя": "Документ.РеализацияТоваровУслуг",
            "Синоним": "Реализация товаров и услуг",
            "ТабличныеЧасти": [
                {
                    "Имя": "Товары",
                    "Реквизиты": [
                        {"Имя": "Номенклатура", "Тип": "СправочникСсылка.Номенклатура"},
                        {"Имя": "Количество", "Тип": "Число"},
                    ],
                }
            ],
        }
    )


if __name__ == "__main__":
    unittest.main()

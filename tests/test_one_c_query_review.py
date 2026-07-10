from __future__ import annotations

import unittest

from wiicon5.knowledge.metadata import MetadataObject
from wiicon5.knowledge.metadata import metadata_object_from_payload
from wiicon5.knowledge.one_c_wiki import EmbeddedOneCWiki
from wiicon5.mcp.client import DictMcpClient
from wiicon5.query.one_c_query_review import OneCQueryReviewer, parse_sources
from wiicon5.query.reference_value_resolver import ReferenceValueResolver


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

    def test_rejects_raw_accumulation_register_with_inactive_filter(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                СУММА(Движения.Сумма) КАК Сумма
            ИЗ
                РегистрНакопления.ДенежныеСредства КАК Движения
            ГДЕ
                НЕ Движения.Активность
            """,
            params={},
            metadata_objects=[money_register_metadata()],
        )

        self.assertFalse(result.ok)
        self.assertIn("raw_accumulation_register_inactive_filter", [issue.code for issue in result.issues])

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

    def test_parse_sources_keeps_virtual_table_with_nested_subquery(self) -> None:
        query = """
        ВЫБРАТЬ ПЕРВЫЕ 1
            Остатки.Номенклатура КАК Номенклатура,
            Остатки.ВНаличииОстаток КАК Остаток
        ИЗ
            РегистрНакопления.ТоварыНаСкладах.Остатки(
                ,
                Склад В (
                    ВЫБРАТЬ
                        Склады.Ссылка
                    ИЗ
                        Справочник.Склады КАК Склады
                    ГДЕ
                        Склады.ТипСклада = &ТипСклада
                )
            ) КАК Остатки
        """

        sources = parse_sources(query)

        self.assertEqual([item.source for item in sources], [
            (
                "РегистрНакопления.ТоварыНаСкладах.Остатки( , Склад В ( "
                "ВЫБРАТЬ Склады.Ссылка ИЗ Справочник.Склады КАК Склады "
                "ГДЕ Склады.ТипСклада = &ТипСклада ) )"
            ),
            "Справочник.Склады",
        ])
        self.assertEqual(sources[0].object_full_name, "РегистрНакопления.ТоварыНаСкладах")
        self.assertEqual(sources[0].virtual_table, "Остатки")

    def test_rejects_balance_virtual_table_third_parameter(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                Остатки.Касса КАК Касса,
                Остатки.СуммаОстаток КАК Остаток
            ИЗ
                РегистрНакопления.ДенежныеСредства.Остатки(, , Касса = &Касса) КАК Остатки
            """,
            params={"Касса": {"_objectRef": True}},
            metadata_objects=[money_register_metadata()],
        )

        self.assertFalse(result.ok)
        self.assertIn("accumulation_balance_invalid_parameters", [issue.code for issue in result.issues])

    def test_rejects_balance_virtual_table_condition_by_non_dimension(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                Остатки.Касса КАК Касса,
                Остатки.СуммаОстаток КАК Остаток
            ИЗ
                РегистрНакопления.ДенежныеСредства.Остатки(, Регистратор = &Документ) КАК Остатки
            """,
            params={"Документ": {"_objectRef": True}},
            metadata_objects=[money_register_metadata()],
        )

        self.assertFalse(result.ok)
        self.assertIn("virtual_table_filter_field_not_dimension", [issue.code for issue in result.issues])

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

    def test_rejects_reference_string_param_inside_balance_virtual_condition(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                Остатки.Номенклатура КАК Номенклатура,
                СУММА(Остатки.КоличествоОстаток) КАК Остаток
            ИЗ
                РегистрНакопления.ТоварыНаСкладах.Остатки(, Склад = &Склад) КАК Остатки
            СГРУППИРОВАТЬ ПО
                Остатки.Номенклатура
            """,
            params={"Склад": "Розничный магазин"},
            metadata_objects=[stock_register_metadata()],
        )

        self.assertFalse(result.ok)
        self.assertIn("reference_filter_string_param", [issue.code for issue in result.issues])

    def test_rejects_reference_string_list_param_inside_balance_virtual_condition(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                Остатки.Номенклатура КАК Номенклатура,
                СУММА(Остатки.КоличествоОстаток) КАК Остаток
            ИЗ
                РегистрНакопления.ТоварыНаСкладах.Остатки(, Склад В (&Склады)) КАК Остатки
            СГРУППИРОВАТЬ ПО
                Остатки.Номенклатура
            """,
            params={"Склады": ["Розничный магазин"]},
            metadata_objects=[stock_register_metadata()],
        )

        self.assertFalse(result.ok)
        self.assertIn("reference_filter_string_param", [issue.code for issue in result.issues])

    def test_rejects_reference_string_list_param_inside_balance_virtual_condition_direct_syntax(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                Остатки.Номенклатура КАК Номенклатура,
                СУММА(Остатки.КоличествоОстаток) КАК Остаток
            ИЗ
                РегистрНакопления.ТоварыНаСкладах.Остатки(, Склад В &Склады) КАК Остатки
            СГРУППИРОВАТЬ ПО
                Остатки.Номенклатура
            """,
            params={"Склады": ["Розничный магазин"]},
            metadata_objects=[stock_register_metadata()],
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

    def test_rejects_source_confirmed_only_by_onboarding_hint(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                Остатки.Касса КАК Касса,
                Остатки.СуммаОстаток КАК Остаток
            ИЗ
                РегистрНакопления.ДенежныеСредства.Остатки() КАК Остатки
            """,
            params={},
            metadata_objects=[
                MetadataObject(
                    full_name="РегистрНакопления.ДенежныеСредства",
                    fields=["Касса", "Сумма"],
                    field_details={
                        "Касса": {"Имя": "Касса", "_category": "indexed", "_source": "bsl_regex", "_trust": "hint"},
                        "Сумма": {"Имя": "Сумма", "_category": "indexed", "_source": "bsl_regex", "_trust": "hint"},
                    },
                    raw={"source": "onboarding_index", "_source": "source_path", "_trust": "hint"},
                )
            ],
        )

        self.assertFalse(result.ok)
        self.assertIn("source_not_confirmed_by_verified_metadata", [issue.code for issue in result.issues])

    def test_accepts_source_confirmed_by_xml_metadata(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                Остатки.Касса КАК Касса,
                Остатки.СуммаОстаток КАК Остаток
            ИЗ
                РегистрНакопления.ДенежныеСредства.Остатки() КАК Остатки
            """,
            params={},
            metadata_objects=[
                MetadataObject(
                    full_name="РегистрНакопления.ДенежныеСредства",
                    fields=["Касса", "Сумма"],
                    field_details={
                        "Касса": {
                            "Имя": "Касса",
                            "Тип": "СправочникСсылка.Кассы",
                            "_category": "dimension",
                            "_source": "metadata_xml",
                            "_trust": "verified",
                        },
                        "Сумма": {
                            "Имя": "Сумма",
                            "Тип": "Число",
                            "_category": "resource",
                            "_source": "metadata_xml",
                            "_trust": "verified",
                        },
                    },
                    raw={"source": "onboarding_index", "_source": "metadata_xml", "_trust": "verified"},
                )
            ],
        )

        self.assertTrue(result.ok)

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

    def test_verified_parent_table_part_schema_wins_over_heuristic_direct_hint(self) -> None:
        reviewer = OneCQueryReviewer()
        direct_hint = MetadataObject(
            full_name="Документ.РеализацияТоваровУслуг.Товары",
            fields=["Номенклатура", "Количество", "Ссылка"],
            field_details={
                "Номенклатура": {"_source": "bsl_regex", "_trust": "hint"},
                "Количество": {"_source": "bsl_regex", "_trust": "hint"},
                "Ссылка": {"_source": "bsl_regex", "_trust": "hint"},
            },
            raw={"_source": "source_path", "_trust": "hint"},
        )

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                Товары.Номенклатура КАК Номенклатура,
                СУММА(Товары.Количество) КАК Количество
            ИЗ
                Документ.РеализацияТоваровУслуг.Товары КАК Товары
                ВНУТРЕННЕЕ СОЕДИНЕНИЕ Документ.РеализацияТоваровУслуг КАК Реализация
                ПО Товары.Ссылка = Реализация.Ссылка
            ГДЕ
                Реализация.Проведен
            СГРУППИРОВАТЬ ПО
                Товары.Номенклатура
            """,
            params={},
            metadata_objects=[direct_hint, sales_document_metadata()],
        )

        self.assertTrue(result.ok, result.error_text())

    def test_rejects_unconfirmed_enum_literal(self) -> None:
        reviewer = OneCQueryReviewer()

        result = reviewer.review(
            query="""
            ВЫБРАТЬ
                КОЛИЧЕСТВО(Склады.Ссылка) КАК Количество
            ИЗ
                Справочник.Склады КАК Склады
            ГДЕ
                Склады.ТипСклада = ЗНАЧЕНИЕ(Перечисление.ТипыСкладов.Розничный)
            """,
            params={},
            metadata_objects=[warehouse_metadata()],
        )

        self.assertFalse(result.ok)
        self.assertIn("enum_value_not_confirmed_by_metadata", [issue.code for issue in result.issues])

    def test_reference_value_resolver_replaces_string_enum_filter_with_object_ref(self) -> None:
        mcp = DictMcpClient(
            {
                "success": True,
                "data": [
                    {
                        "Значение": {
                            "_objectRef": True,
                            "УникальныйИдентификатор": "РозничныйМагазин",
                            "ТипОбъекта": "ПеречислениеСсылка.ТипыСкладов",
                            "Представление": "Розничный магазин",
                        },
                        "Представление": "Розничный магазин",
                    },
                    {
                        "Значение": {
                            "_objectRef": True,
                            "УникальныйИдентификатор": "ОптовыйСклад",
                            "ТипОбъекта": "ПеречислениеСсылка.ТипыСкладов",
                            "Представление": "Оптовый склад",
                        },
                        "Представление": "Оптовый склад",
                    },
                ],
            }
        )

        result = ReferenceValueResolver(mcp).resolve(
            query="""
            ВЫБРАТЬ
                Склады.Ссылка КАК Ссылка
            ИЗ
                Справочник.Склады КАК Склады
            ГДЕ
                Склады.ТипСклада = &warehouse_type
            """,
            params={"warehouse_type": "розничный"},
            metadata_objects=[warehouse_metadata()],
        )

        self.assertTrue(result.changed)
        self.assertEqual(result.params["warehouse_type"]["УникальныйИдентификатор"], "РозничныйМагазин")
        self.assertEqual(len(mcp.query_calls), 1)
        self.assertIn("ПРЕДСТАВЛЕНИЕ(Склады.ТипСклада)", mcp.query_calls[0].query)

    def test_reference_value_resolver_does_not_replace_like_pattern_param_with_object_ref(self) -> None:
        mcp = DictMcpClient(
            {
                "success": True,
                "data": [
                    {
                        "Значение": {
                            "_objectRef": True,
                            "УникальныйИдентификатор": "retail-price",
                            "ТипОбъекта": "СправочникСсылка.ВидыЦен",
                            "Представление": "Розничная",
                        },
                        "Представление": "Розничная",
                    },
                    {
                        "Значение": {
                            "_objectRef": True,
                            "УникальныйИдентификатор": "coat",
                            "ТипОбъекта": "СправочникСсылка.Номенклатура",
                            "Представление": "Женское полупальто из меха норки с металлической молнией",
                        },
                        "Представление": "Женское полупальто из меха норки с металлической молнией",
                    },
                ],
            }
        )

        result = ReferenceValueResolver(mcp).resolve(
            query="""
            ВЫБРАТЬ
                Цены.Номенклатура КАК Номенклатура,
                Цены.Цена КАК Цена
            ИЗ
                РегистрСведений.ЦеныНоменклатуры КАК Цены
            ГДЕ
                Цены.ВидЦены = &ВидЦены
                И Цены.Номенклатура В (
                    ВЫБРАТЬ
                        Ном.Ссылка
                    ИЗ
                        Справочник.Номенклатура КАК Ном
                    ГДЕ
                        Ном.Наименование ПОДОБНО &Пальто
                )
            """,
            params={"ВидЦены": "Розничная", "Пальто": "%пальто%"},
            metadata_objects=[price_register_metadata()],
        )

        self.assertTrue(result.changed)
        self.assertEqual(result.params["ВидЦены"]["УникальныйИдентификатор"], "retail-price")
        self.assertEqual(result.params["Пальто"], "%пальто%")
        self.assertEqual([item["param"] for item in result.resolutions], ["ВидЦены"])

    def test_reference_value_resolver_replaces_unconfirmed_enum_literal_with_object_param(self) -> None:
        mcp = DictMcpClient(
            {
                "success": True,
                "data": [
                    {
                        "Значение": {
                            "_objectRef": True,
                            "УникальныйИдентификатор": "РозничныйМагазин",
                            "ТипОбъекта": "ПеречислениеСсылка.ТипыСкладов",
                            "Представление": "Розничный магазин",
                        },
                        "Представление": "Розничный магазин",
                    }
                ],
            }
        )

        result = ReferenceValueResolver(mcp).resolve(
            query="""
            ВЫБРАТЬ
                КОЛИЧЕСТВО(Склады.Ссылка) КАК Количество
            ИЗ
                Справочник.Склады КАК Склады
            ГДЕ
                Склады.ТипСклада = ЗНАЧЕНИЕ(Перечисление.ТипыСкладов.Розничный)
            """,
            params={},
            metadata_objects=[warehouse_metadata()],
        )

        self.assertTrue(result.changed)
        self.assertIn("Склады.ТипСклада = &ТипСклада_resolved", result.query)
        self.assertEqual(result.params["ТипСклада_resolved"]["УникальныйИдентификатор"], "РозничныйМагазин")

    def test_reference_value_resolver_replaces_virtual_condition_string_param(self) -> None:
        mcp = DictMcpClient(
            {
                "success": True,
                "data": [
                    {
                        "Значение": {
                            "_objectRef": True,
                            "УникальныйИдентификатор": "warehouse-retail",
                            "ТипОбъекта": "СправочникСсылка.Склады",
                            "Представление": "Розничный магазин",
                        },
                        "Представление": "Розничный магазин",
                    }
                ],
            }
        )

        result = ReferenceValueResolver(mcp).resolve(
            query="""
            ВЫБРАТЬ
                Остатки.Номенклатура КАК Номенклатура,
                СУММА(Остатки.КоличествоОстаток) КАК Остаток
            ИЗ
                РегистрНакопления.ТоварыНаСкладах.Остатки(, Склад = &СкладРозничный) КАК Остатки
            СГРУППИРОВАТЬ ПО
                Остатки.Номенклатура
            """,
            params={"СкладРозничный": "СправочникСсылка.Склады"},
            metadata_objects=[stock_register_metadata()],
        )

        self.assertTrue(result.changed)
        self.assertEqual(result.params["СкладРозничный"]["УникальныйИдентификатор"], "warehouse-retail")
        self.assertEqual(result.resolutions[0]["search_text"], "СкладРозничный")
        self.assertEqual(len(mcp.query_calls), 1)
        self.assertIn("РегистрНакопления.ТоварыНаСкладах.Остатки() КАК Остатки", mcp.query_calls[0].query)
        self.assertNotIn("Склад = &СкладРозничный", mcp.query_calls[0].query)

    def test_reference_value_resolver_replaces_virtual_condition_empty_list_param(self) -> None:
        mcp = DictMcpClient(
            {
                "success": True,
                "data": [
                    {
                        "Значение": {
                            "_objectRef": True,
                            "УникальныйИдентификатор": "warehouse-retail",
                            "ТипОбъекта": "СправочникСсылка.Склады",
                            "Представление": "Ларек Розница",
                        },
                        "Представление": "Ларек Розница",
                    }
                ],
            }
        )

        result = ReferenceValueResolver(mcp).resolve(
            query="""
            ВЫБРАТЬ
                Остатки.Номенклатура КАК Номенклатура,
                СУММА(Остатки.КоличествоОстаток) КАК Остаток
            ИЗ
                РегистрНакопления.ТоварыНаСкладах.Остатки(, Склад В (&РозничныеСклады)) КАК Остатки
            СГРУППИРОВАТЬ ПО
                Остатки.Номенклатура
            """,
            params={"РозничныеСклады": []},
            metadata_objects=[stock_register_metadata()],
        )

        self.assertTrue(result.changed)
        self.assertEqual(result.params["РозничныеСклады"][0]["УникальныйИдентификатор"], "warehouse-retail")
        self.assertEqual(result.resolutions[0]["kind"], "empty_list_param")
        self.assertEqual(result.resolutions[0]["search_text"], "РозничныеСклады")

    def test_reference_value_resolver_replaces_virtual_condition_direct_empty_list_param(self) -> None:
        mcp = DictMcpClient(
            {
                "success": True,
                "data": [
                    {
                        "Значение": {
                            "_objectRef": True,
                            "УникальныйИдентификатор": "warehouse-retail",
                            "ТипОбъекта": "СправочникСсылка.Склады",
                            "Представление": "Ларек Розница",
                        },
                        "Представление": "Ларек Розница",
                    }
                ],
            }
        )

        result = ReferenceValueResolver(mcp).resolve(
            query="""
            ВЫБРАТЬ
                Остатки.Номенклатура КАК Номенклатура,
                СУММА(Остатки.КоличествоОстаток) КАК Остаток
            ИЗ
                РегистрНакопления.ТоварыНаСкладах.Остатки(, Склад В &РозничныеСклады) КАК Остатки
            СГРУППИРОВАТЬ ПО
                Остатки.Номенклатура
            """,
            params={"РозничныеСклады": []},
            metadata_objects=[stock_register_metadata()],
        )

        self.assertTrue(result.changed)
        self.assertEqual(result.params["РозничныеСклады"][0]["УникальныйИдентификатор"], "warehouse-retail")
        self.assertEqual(result.resolutions[0]["kind"], "empty_list_param")
        self.assertEqual(result.resolutions[0]["search_text"], "РозничныеСклады")


def money_register_metadata():
    return metadata_object_from_payload(
        {
            "ПолноеИмя": "РегистрНакопления.ДенежныеСредства",
            "Синоним": "Денежные средства",
            "Измерения": [{"Имя": "Касса", "Тип": "СправочникСсылка.Кассы"}],
            "Ресурсы": [{"Имя": "Сумма", "Тип": "Число(15, 2)"}],
        }
    )


def stock_register_metadata():
    return metadata_object_from_payload(
        {
            "ПолноеИмя": "РегистрНакопления.ТоварыНаСкладах",
            "Синоним": "Товары на складах",
            "Измерения": [
                {"Имя": "Номенклатура", "Тип": "СправочникСсылка.Номенклатура"},
                {"Имя": "Склад", "Тип": "СправочникСсылка.Склады"},
            ],
            "Ресурсы": [{"Имя": "Количество", "Тип": "Число"}],
        }
    )


def price_register_metadata():
    return metadata_object_from_payload(
        {
            "ПолноеИмя": "РегистрСведений.ЦеныНоменклатуры",
            "Синоним": "Цены номенклатуры",
            "Измерения": [
                {"Имя": "Номенклатура", "Тип": "СправочникСсылка.Номенклатура"},
                {"Имя": "ВидЦены", "Тип": "СправочникСсылка.ВидыЦен"},
            ],
            "Ресурсы": [{"Имя": "Цена", "Тип": "Число"}],
        }
    )


def warehouse_metadata():
    return metadata_object_from_payload(
        {
            "ПолноеИмя": "Справочник.Склады",
            "Синоним": "Склады",
            "Реквизиты": [
                {"Имя": "Ссылка", "Тип": "СправочникСсылка.Склады"},
                {"Имя": "Наименование", "Тип": "Строка(50)"},
                {"Имя": "ТипСклада", "Тип": "ПеречислениеСсылка.ТипыСкладов"},
            ],
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

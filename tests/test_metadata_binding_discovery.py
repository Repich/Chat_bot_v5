from __future__ import annotations

import unittest
from pathlib import Path
from typing import Dict, List

from wiicon5.conversation.context import ConversationContext
from wiicon5.knowledge.bindings import BindingResolver, InMemoryBindingStore
from wiicon5.knowledge.discovery import MetadataBindingDiscoverer, discover_binding_candidates
from wiicon5.knowledge.metadata import MetadataObject, MetadataProvider, metadata_object_from_payload
from wiicon5.query.semantic_query_builder import SemanticQueryBuilder
from wiicon5.skills.registry import SkillRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MetadataBindingDiscoveryTests(unittest.TestCase):
    def test_discovers_warehouse_binding_from_metadata(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_warehouses")
        assert skill is not None
        provider = FakeMetadataProvider(
            {
                "склад": [
                    metadata_object_from_payload(
                        {
                            "ПолноеИмя": "Справочник.МестаХранения",
                            "Синоним": "Места хранения",
                            "Реквизиты": [
                                {"Имя": "Название"},
                                {"Имя": "Категория"},
                                {"Имя": "Город"},
                            ],
                        }
                    ),
                    metadata_object_from_payload(
                        {
                            "ПолноеИмя": "Справочник.ВидыСкладов",
                            "Синоним": "Виды складов",
                            "Реквизиты": [{"Имя": "Описание"}],
                        }
                    ),
                ]
            }
        )
        discoverer = MetadataBindingDiscoverer(provider)

        binding = discoverer.discover(skill, ConversationContext(session_id="s1", config_fingerprint="cfg_meta"))

        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.skill_id, "get_warehouses")
        self.assertEqual(binding.config_fingerprint, "cfg_meta")
        self.assertEqual(binding.one_c_object["full_name"], "Справочник.МестаХранения")
        self.assertEqual(binding.fields["name"], "Название")
        self.assertEqual(binding.fields["warehouse_type"], "Категория")
        self.assertEqual(binding.fields["city"], "Город")
        self.assertGreaterEqual(binding.confidence, 0.45)

    def test_warehouse_discovery_rejects_false_city_and_price_type_fields(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_warehouses")
        assert skill is not None
        provider = FakeMetadataProvider(
            {
                "склад": [
                    metadata_object_from_payload(
                        {
                            "ПолноеИмя": "Справочник.Склады",
                            "Синоним": "Склады",
                            "Реквизиты": [
                                {
                                    "Имя": "ИспользоватьАдресноеХранение",
                                    "Синоним": "Использовать адресное хранение",
                                    "Тип": "Булево",
                                },
                                {
                                    "Имя": "РозничныйВидЦены",
                                    "Синоним": "Розничный вид цены",
                                    "Тип": "СправочникСсылка.ВидыЦен",
                                },
                                {
                                    "Имя": "ТипСклада",
                                    "Синоним": "Тип склада",
                                    "Тип": "ПеречислениеСсылка.ТипыСкладов",
                                },
                            ],
                        }
                    )
                ]
            }
        )
        discoverer = MetadataBindingDiscoverer(provider)

        binding = discoverer.discover(skill, ConversationContext(session_id="s1", config_fingerprint="cfg_meta"))

        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.fields["warehouse_type"], "ТипСклада")
        self.assertNotIn("city", binding.fields)

    def test_discovered_warehouse_binding_builds_query_without_scripted_binding(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_warehouses")
        assert skill is not None
        provider = FakeMetadataProvider(
            {
                "склад": [
                    metadata_object_from_payload(
                        {
                            "ПолноеИмя": "Справочник.МестаХранения",
                            "Синоним": "Склады и места хранения",
                            "Реквизиты": [{"Имя": "Название"}, {"Имя": "Категория"}],
                        }
                    )
                ]
            }
        )
        store = InMemoryBindingStore()
        builder = SemanticQueryBuilder(BindingResolver(store, MetadataBindingDiscoverer(provider)))

        draft = builder.build(
            skill,
            {"filters": [{"semantic_field": "warehouse_type", "operator": "equals", "value": "wholesale"}]},
            ConversationContext(session_id="s1", config_fingerprint="cfg_meta"),
        )

        self.assertIn("Справочник.МестаХранения", draft.query)
        self.assertIn("Склады.Категория = &warehouse_type", draft.query)
        self.assertEqual(draft.params["warehouse_type"], "wholesale")
        self.assertIsNotNone(store.get("get_warehouses", "cfg_meta"))

    def test_discovers_stock_binding_from_accumulation_register_metadata(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_stock_balances")
        assert skill is not None
        provider = FakeMetadataProvider(
            {
                "остатки": [
                    metadata_object_from_payload(
                        {
                            "ПолноеИмя": "РегистрНакопления.ОстаткиТоваров",
                            "Синоним": "Остатки товаров",
                            "Измерения": [{"Имя": "Товар"}, {"Имя": "МестоХранения"}],
                            "Ресурсы": [{"Имя": "ДоступноОстаток"}],
                        }
                    )
                ],
                "товары на складах": [],
            }
        )
        discoverer = MetadataBindingDiscoverer(provider)

        binding = discoverer.discover(skill, ConversationContext(session_id="s1", config_fingerprint="cfg_meta"))

        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.one_c_object["full_name"], "РегистрНакопления.ОстаткиТоваров")
        self.assertEqual(binding.one_c_object["virtual_table"], "Остатки")
        self.assertEqual(binding.fields["product"], "Товар")
        self.assertEqual(binding.fields["warehouse"], "МестоХранения")
        self.assertEqual(binding.fields["quantity"], "ДоступноОстаток")

    def test_stock_discovery_requires_balance_compatible_register_type(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_stock_balances")
        assert skill is not None
        provider = FakeMetadataProvider(
            {
                "остатки товаров": [
                    metadata_object_from_payload(
                        {
                            "ПолноеИмя": "РегистрСведений.ДоступныеОстаткиТоваров",
                            "Синоним": "Доступные остатки товаров",
                            "Измерения": [{"Имя": "Номенклатура"}, {"Имя": "Склад"}],
                            "Ресурсы": [{"Имя": "ВНаличии", "Синоним": "В наличии", "Тип": "Число(15, 3)"}],
                        }
                    )
                ],
                "товары на складах": [
                    metadata_object_from_payload(
                        {
                            "ПолноеИмя": "РегистрСведений.ТоварыНаСкладахТорговыхПлощадокЗаДень",
                            "Синоним": "Товары на складах торговых площадок за день",
                            "Измерения": [{"Имя": "Номенклатура"}, {"Имя": "ИдентификаторСкладаТорговойПлощадки"}],
                            "Ресурсы": [{"Имя": "ВНаличии", "Синоним": "В наличии", "Тип": "Число(20, 3)"}],
                            "Реквизиты": [{"Имя": "НаименованиеСкладаТорговойПлощадки", "Синоним": "Наименование склада торговой площадки"}],
                        }
                    ),
                    metadata_object_from_payload(
                        {
                            "ПолноеИмя": "РегистрНакопления.ТоварыНаСкладах",
                            "Синоним": "Товары на складах",
                            "Измерения": [{"Имя": "Номенклатура"}, {"Имя": "Склад"}],
                            "Ресурсы": [{"Имя": "ВНаличии", "Синоним": "В наличии", "Тип": "Число(15, 3)"}],
                        }
                    ),
                ],
            }
        )
        discoverer = MetadataBindingDiscoverer(provider)

        binding = discoverer.discover(skill, ConversationContext(session_id="s1", config_fingerprint="cfg_meta"))

        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.one_c_object["full_name"], "РегистрНакопления.ТоварыНаСкладах")
        self.assertEqual(binding.fields["quantity"], "ВНаличииОстаток")

    def test_discovery_returns_none_when_required_metadata_fields_are_missing(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_stock_balances")
        assert skill is not None
        provider = FakeMetadataProvider(
            {
                "остатки": [
                    metadata_object_from_payload(
                        {
                            "ПолноеИмя": "РегистрНакопления.ОстаткиТоваров",
                            "Синоним": "Остатки товаров",
                            "Измерения": [{"Имя": "Товар"}],
                            "Ресурсы": [],
                        }
                    )
                ]
            }
        )
        discoverer = MetadataBindingDiscoverer(provider)

        binding = discoverer.discover(skill, ConversationContext(session_id="s1", config_fingerprint="cfg_meta"))

        self.assertIsNone(binding)

    def test_discovers_transfer_document_count_binding_from_metadata(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("count_transfer_documents_by_day")
        assert skill is not None
        provider = FakeMetadataProvider(
            {
                "перемещение товаров": [
                    metadata_object_from_payload(
                        {
                            "ПолноеИмя": "Документ.ОрдерНаПеремещениеТоваров",
                            "Синоним": "Ордер на перемещение товаров",
                            "Реквизиты": [
                                {"Имя": "Ссылка", "Тип": "ДокументСсылка.ОрдерНаПеремещениеТоваров"},
                                {"Имя": "Дата", "Тип": "Дата(ДатаВремя)"},
                            ],
                        }
                    ),
                    metadata_object_from_payload(
                        {
                            "ПолноеИмя": "Документ.ПеремещениеТоваров",
                            "Синоним": "Перемещение товаров",
                            "Реквизиты": [
                                {"Имя": "Ссылка", "Тип": "ДокументСсылка.ПеремещениеТоваров"},
                                {"Имя": "Дата", "Тип": "Дата(ДатаВремя)"},
                            ],
                        }
                    ),
                ],
                "перемещения товаров": [],
                "товары перемещение": [],
            }
        )
        discoverer = MetadataBindingDiscoverer(provider)

        binding = discoverer.discover(skill, ConversationContext(session_id="s1", config_fingerprint="cfg_meta"))

        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.one_c_object["full_name"], "Документ.ПеремещениеТоваров")
        self.assertEqual(binding.fields["date"], "Дата")
        self.assertEqual(binding.fields["ref"], "Ссылка")


class FakeMetadataProvider(MetadataProvider):
    def __init__(self, search_results: Dict[str, List[MetadataObject]]) -> None:
        self.search_results = search_results
        self.objects = {item.full_name: item for items in search_results.values() for item in items}
        self.search_calls: List[str] = []
        self.get_calls: List[str] = []

    def search_objects(self, term: str) -> List[MetadataObject]:
        self.search_calls.append(term)
        return list(self.search_results.get(term, []))

    def get_object(self, full_name: str) -> MetadataObject:
        self.get_calls.append(full_name)
        return self.objects[full_name]


if __name__ == "__main__":
    unittest.main()

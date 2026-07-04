from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.knowledge.metadata import MetadataObject, MetadataProvider, is_field_confirmed, is_metadata_object_verified
from wiicon5.knowledge.onboarding_index import IndexedMetadataProvider, OnboardingMetadataIndex
from wiicon5.onboarding.metadata_index_builder import IndexedField, IndexedObject, write_metadata_index


class EmptyMetadataProvider(MetadataProvider):
    def __init__(self) -> None:
        self.last_requests = []

    def search_objects(self, term: str):
        self.last_requests.append({"operation": "search_objects", "term": term, "source": "mcp"})
        return []

    def get_object(self, full_name: str):
        self.last_requests.append({"operation": "get_object", "full_name": full_name, "source": "mcp"})
        return MetadataObject(full_name=full_name)


class OnboardingIndexTests(unittest.TestCase):
    def test_indexed_provider_uses_onboarding_index_as_fallback(self) -> None:
        with TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "metadata_index.sqlite"
            write_metadata_index(
                index_path,
                [
                    IndexedObject(
                        full_name="РегистрНакопления.ДенежныеСредстваВКассахККМ",
                        kind="РегистрНакопления",
                        source_files=["AccumulationRegisters/ДенежныеСредстваВКассахККМ.xml"],
                        fields=["КассаККМ", "Организация", "Сумма"],
                    )
                ],
            )
            provider = IndexedMetadataProvider(EmptyMetadataProvider(), OnboardingMetadataIndex(index_path))

            found = provider.search_objects("кассах")
            detailed = provider.get_object("РегистрНакопления.ДенежныеСредстваВКассахККМ")

        self.assertEqual([item.full_name for item in found], ["РегистрНакопления.ДенежныеСредстваВКассахККМ"])
        self.assertIn("Сумма", detailed.fields)
        self.assertFalse(is_metadata_object_verified(detailed))
        self.assertFalse(is_field_confirmed(detailed.field_details["Сумма"]))
        self.assertTrue(any(item.get("source") == "onboarding_index" for item in provider.last_requests))

    def test_indexed_provider_preserves_xml_verification_evidence(self) -> None:
        with TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "metadata_index.sqlite"
            write_metadata_index(
                index_path,
                [
                    IndexedObject(
                        full_name="РегистрНакопления.ДенежныеСредства",
                        kind="РегистрНакопления",
                        source_files=["AccumulationRegisters/ДенежныеСредства.xml"],
                        fields=["Касса", "Сумма"],
                        field_details={
                            "Касса": IndexedField(
                                name="Касса",
                                category="dimension",
                                source="metadata_xml",
                                trust="verified",
                                type_text="СправочникСсылка.Кассы",
                            ),
                            "Сумма": IndexedField(
                                name="Сумма",
                                category="resource",
                                source="metadata_xml",
                                trust="verified",
                                type_text="Число",
                            ),
                        },
                        source="metadata_xml",
                        trust="verified",
                        confidence=0.95,
                    )
                ],
            )
            provider = IndexedMetadataProvider(EmptyMetadataProvider(), OnboardingMetadataIndex(index_path))

            detailed = provider.get_object("РегистрНакопления.ДенежныеСредства")

        self.assertTrue(is_metadata_object_verified(detailed))
        self.assertTrue(is_field_confirmed(detailed.field_details["Касса"]))
        self.assertEqual(detailed.field_details["Касса"]["Тип"], "СправочникСсылка.Кассы")


if __name__ == "__main__":
    unittest.main()

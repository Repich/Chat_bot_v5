from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.knowledge.metadata import MetadataObject, MetadataProvider
from wiicon5.knowledge.onboarding_index import IndexedMetadataProvider, OnboardingMetadataIndex
from wiicon5.onboarding.metadata_index_builder import IndexedObject, write_metadata_index


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
        self.assertTrue(any(item.get("source") == "onboarding_index" for item in provider.last_requests))


if __name__ == "__main__":
    unittest.main()

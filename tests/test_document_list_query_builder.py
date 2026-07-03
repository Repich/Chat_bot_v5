from __future__ import annotations

import unittest
from pathlib import Path
from typing import Dict, List

from wiicon5.conversation.context import ConversationContext
from wiicon5.knowledge.metadata import MetadataObject, MetadataProvider, metadata_object_from_payload
from wiicon5.query.document_list_query_builder import DocumentListQueryBuilder, document_object_score
from wiicon5.skills.registry import SkillRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DocumentListQueryBuilderTests(unittest.TestCase):
    def test_document_list_query_discovers_document_object_and_builds_year_filter(self) -> None:
        registry = SkillRegistry.load_from_dir(PROJECT_ROOT / "skills")
        skill = registry.get("get_documents_by_type_and_period")
        assert skill is not None
        provider = FakeMetadataProvider(
            {
                "Сервисные акты": [
                    metadata_object_from_payload(
                        {
                            "ПолноеИмя": "Справочник.СервисныеОбъекты",
                            "Синоним": "Сервисные объекты",
                        }
                    ),
                    metadata_object_from_payload(
                        {
                            "ПолноеИмя": "Документ.СервисныйАкт",
                            "Синоним": "Сервисный акт",
                            "СтандартныеРеквизиты": [
                                {"Имя": "Ссылка"},
                                {"Имя": "Номер"},
                                {"Имя": "Дата"},
                                {"Имя": "Проведен"},
                            ],
                        }
                    ),
                ]
            }
        )
        builder = DocumentListQueryBuilder(provider)

        draft = builder.build(
            skill,
            {
                "filters": [
                    {"semantic_field": "document_type", "operator": "equals", "value": "Сервисные акты"},
                    {"semantic_field": "year", "operator": "equals", "value": "2024"},
                ],
                "limit": 25,
            },
            ConversationContext(session_id="s1", config_fingerprint="cfg"),
        )

        self.assertIn("ВЫБРАТЬ ПЕРВЫЕ 25", draft.query)
        self.assertIn("Документ.СервисныйАкт КАК Документы", draft.query)
        self.assertIn("Документы.Ссылка КАК Ссылка", draft.query)
        self.assertIn("Документы.Номер КАК Номер", draft.query)
        self.assertIn("Документы.Дата КАК Дата", draft.query)
        self.assertIn("Документы.Дата >= ДАТАВРЕМЯ(2024, 1, 1)", draft.query)
        self.assertIn("Документы.Дата < ДАТАВРЕМЯ(2025, 1, 1)", draft.query)
        self.assertNotIn("Справочник.СервисныеОбъекты", draft.query)
        self.assertEqual(draft.metadata_dependencies, ["Документ.СервисныйАкт"])

    def test_document_object_score_handles_light_russian_inflection(self) -> None:
        metadata_object = metadata_object_from_payload(
            {
                "ПолноеИмя": "Документ.ПлановыйОтчет",
                "Синоним": "Плановый отчет",
            }
        )

        score = document_object_score("плановые отчеты", metadata_object)

        self.assertGreaterEqual(score, 0.5)


class FakeMetadataProvider(MetadataProvider):
    def __init__(self, search_results: Dict[str, List[MetadataObject]]) -> None:
        self.search_results = search_results
        self.objects = {item.full_name: item for items in search_results.values() for item in items}
        self.last_requests = []

    def search_objects(self, term: str) -> List[MetadataObject]:
        self.last_requests.append({"operation": "search_objects", "term": term})
        return list(self.search_results.get(term, []))

    def get_object(self, full_name: str) -> MetadataObject:
        self.last_requests.append({"operation": "get_object", "full_name": full_name})
        return self.objects[full_name]


if __name__ == "__main__":
    unittest.main()

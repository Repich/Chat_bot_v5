from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.workbench import HumanSkillDraftStore, OnboardingCandidateService


class WorkbenchOnboardingCandidateTests(unittest.TestCase):
    def test_service_reads_candidates_from_all_onboarding_sources(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot"
            write_onboarding_sources(bot)
            service = OnboardingCandidateService(bot_instance_root=bot)

            candidates = service.list_candidates(limit=20)
            by_type = {item.type for item in candidates}
            binding = next(item for item in candidates if item.type == "binding")

        self.assertIn("binding", by_type)
        self.assertIn("register_usage", by_type)
        self.assertIn("query_pattern", by_type)
        self.assertIn("semantic_dictionary", by_type)
        self.assertEqual(binding.status, "verified_by_mcp")
        self.assertIn("verified_by_mcp", binding.evidence)

    def test_candidate_can_be_rejected_and_status_is_persisted(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot"
            write_onboarding_sources(bot)
            service = OnboardingCandidateService(bot_instance_root=bot)
            candidate = next(item for item in service.list_candidates() if item.type == "binding")

            rejection = service.reject_candidate(candidate.candidate_id, actor="expert", comment="Не тот бизнес-смысл")
            restored = service.get_candidate(candidate.candidate_id)

        self.assertEqual(rejection["candidate_id"], candidate.candidate_id)
        self.assertEqual(rejection["actor"], "expert")
        self.assertEqual(restored.status if restored else "", "rejected")

    def test_candidate_can_be_converted_to_human_draft_without_verified_skill(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bot = Path(temp_dir) / "bot"
            write_onboarding_sources(bot)
            draft_store = HumanSkillDraftStore(bot_instance_root=bot, bot_id="client_a")
            service = OnboardingCandidateService(bot_instance_root=bot, draft_store=draft_store)
            candidate = next(item for item in service.list_candidates() if item.type == "binding")

            draft = service.create_draft(candidate.candidate_id, actor="expert")
            restored = draft_store.get_draft(draft.draft_id)
            events = draft_store.audit.read()

        self.assertIsNotNone(restored)
        self.assertEqual(restored.source_kind if restored else "", "onboarding_candidate")
        self.assertEqual(restored.data_sources[0].object_name if restored else "", "РегистрНакопления.ТоварыНаСкладах")
        self.assertEqual(restored.data_sources[0].trust if restored else "", "hint")
        self.assertEqual(restored.extras["onboarding_candidate"]["candidate_id"], candidate.candidate_id)
        self.assertIn("workbench.onboarding_candidate.draft_created", [item.event_type for item in events])

    def test_missing_candidate_files_return_empty_list(self) -> None:
        with TemporaryDirectory() as temp_dir:
            service = OnboardingCandidateService(bot_instance_root=Path(temp_dir) / "bot")

            candidates = service.list_candidates()

        self.assertEqual(candidates, [])


def write_onboarding_sources(bot: Path) -> None:
    onboarding = bot / "onboarding"
    onboarding.mkdir(parents=True, exist_ok=True)
    (onboarding / "candidate_bindings.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "semantic_role": "stock_balance",
                        "object": "РегистрНакопления.ТоварыНаСкладах",
                        "confidence": 0.72,
                        "evidence": ["object has Номенклатура", "object has Склад"],
                        "status": "candidate",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (onboarding / "verified_binding_candidates.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "candidate": {
                            "semantic_role": "stock_balance",
                            "object": "РегистрНакопления.ТоварыНаСкладах",
                        },
                        "status": "verified_by_mcp",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (onboarding / "register_usage_map.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "document": "Документ.РеализацияТоваровУслуг",
                        "registers": ["РегистрНакопления.ТоварыНаСкладах"],
                        "source_file": "Documents/РеализацияТоваровУслуг/Ext/ObjectModule.bsl",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (onboarding / "candidate_semantic_roles.json").write_text(
        json.dumps({"dictionary": {"склад": ["Справочник.Склады"]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (onboarding / "candidate_query_patterns.jsonl").write_text(
        json.dumps(
            {
                "pattern_id": "query_stock",
                "source_file": "Reports/Stock/Ext/ObjectModule.bsl",
                "query": "ВЫБРАТЬ Остатки.Номенклатура ИЗ РегистрНакопления.ТоварыНаСкладах.Остатки() КАК Остатки",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()

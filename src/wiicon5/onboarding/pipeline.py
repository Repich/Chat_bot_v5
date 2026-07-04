from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from wiicon5.onboarding.binding_candidate_generator import generate_binding_candidates
from wiicon5.onboarding.config_dump_reader import read_config_dump
from wiicon5.onboarding.metadata_index_builder import extract_metadata_objects, write_metadata_index
from wiicon5.onboarding.onboarding_report import render_onboarding_report
from wiicon5.onboarding.query_pattern_extractor import extract_query_patterns
from wiicon5.onboarding.register_usage_analyzer import analyze_register_usage
from wiicon5.onboarding.semantic_dictionary_builder import build_semantic_dictionary


@dataclass(frozen=True)
class OnboardingResult:
    output_dir: Path
    files_read: int
    objects_count: int
    query_patterns_count: int
    register_usage_count: int
    binding_candidates_count: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "output_dir": str(self.output_dir),
            "files_read": self.files_read,
            "objects_count": self.objects_count,
            "query_patterns_count": self.query_patterns_count,
            "register_usage_count": self.register_usage_count,
            "binding_candidates_count": self.binding_candidates_count,
        }


def run_onboarding(*, config_dump: Path, bot_instance: Path, mcp_url: str = "") -> OnboardingResult:
    files = read_config_dump(config_dump)
    objects = extract_metadata_objects(files)
    query_patterns = extract_query_patterns(files)
    register_usage = analyze_register_usage(files)
    semantic_dictionary = build_semantic_dictionary(objects)
    binding_candidates = generate_binding_candidates(objects)

    output_dir = bot_instance / "onboarding"
    output_dir.mkdir(parents=True, exist_ok=True)
    write_metadata_index(output_dir / "metadata_index.sqlite", objects)
    write_json(output_dir / "candidate_semantic_roles.json", {"dictionary": semantic_dictionary})
    write_json(output_dir / "candidate_bindings.json", {"candidates": binding_candidates})
    write_json(output_dir / "register_usage_map.json", {"items": [item.to_dict() for item in register_usage]})
    write_jsonl(output_dir / "candidate_query_patterns.jsonl", [item.to_dict() for item in query_patterns])
    write_json(
        output_dir / "onboarding_manifest.json",
        {
            "config_dump": str(config_dump),
            "bot_instance": str(bot_instance),
            "mcp_url": mcp_url,
            "files_read": len(files),
        },
    )
    (output_dir / "onboarding_report.md").write_text(
        render_onboarding_report(
            objects=objects,
            query_patterns=query_patterns,
            register_usage=register_usage,
            binding_candidates=binding_candidates,
        ),
        encoding="utf-8",
    )
    return OnboardingResult(
        output_dir=output_dir,
        files_read=len(files),
        objects_count=len(objects),
        query_patterns_count=len(query_patterns),
        register_usage_count=len(register_usage),
        binding_candidates_count=len(binding_candidates),
    )


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")

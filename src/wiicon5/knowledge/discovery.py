from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from wiicon5.conversation.context import ConversationContext
from wiicon5.knowledge.bindings import BindingDiscoverer
from wiicon5.knowledge.metadata import MetadataObject, MetadataProvider
from wiicon5.knowledge.semantic_profiles import FieldRoleProfile, SemanticRoleProfile, profile_for_skill
from wiicon5.models import SkillBinding, SkillContract


@dataclass(frozen=True)
class BindingCandidate:
    binding: SkillBinding
    score: float
    missing_required_fields: List[str]


class MetadataBindingDiscoverer(BindingDiscoverer):
    def __init__(self, metadata_provider: MetadataProvider, min_confidence: float = 0.45, max_search_terms: int = 5) -> None:
        self.metadata_provider = metadata_provider
        self.min_confidence = min_confidence
        self.max_search_terms = max_search_terms
        self.calls: List[Dict[str, str]] = []
        self.last_diagnostics: Dict[str, object] = {}

    def discover(self, skill: SkillContract, context: ConversationContext) -> Optional[SkillBinding]:
        profile = profile_for_skill(skill.skill_id)
        if profile is None:
            return None
        self.calls.append({"skill_id": skill.skill_id, "semantic_role": profile.semantic_role})
        candidates = discover_binding_candidates(
            skill=skill,
            profile=profile,
            context=context,
            metadata_provider=self.metadata_provider,
            max_search_terms=self.max_search_terms,
        )
        self.last_diagnostics = {
            "skill_id": skill.skill_id,
            "semantic_role": profile.semantic_role,
            "candidate_count": len(candidates),
            "candidates": [
                {
                    "full_name": candidate.binding.one_c_object.get("full_name"),
                    "score": candidate.score,
                    "missing_required_fields": list(candidate.missing_required_fields),
                    "fields": dict(candidate.binding.fields),
                }
                for candidate in candidates[:5]
            ],
            "metadata_requests": getattr(self.metadata_provider, "last_requests", []),
        }
        usable = [candidate for candidate in candidates if not candidate.missing_required_fields]
        if not usable:
            return None
        best = usable[0]
        if best.score < self.min_confidence:
            return None
        return best.binding


def discover_binding_candidates(
    *,
    skill: SkillContract,
    profile: SemanticRoleProfile,
    context: ConversationContext,
    metadata_provider: MetadataProvider,
    max_search_terms: int = 5,
) -> List[BindingCandidate]:
    objects = [
        item
        for item in discover_objects(profile, metadata_provider, max_search_terms=max_search_terms)
        if object_is_compatible(item, profile)
    ]
    candidates = [
        build_candidate(skill=skill, profile=profile, context=context, metadata_object=item)
        for item in objects
        if item.full_name
    ]
    return sorted(candidates, key=lambda item: (-item.score, item.binding.one_c_object.get("full_name", "")))


def discover_objects(profile: SemanticRoleProfile, metadata_provider: MetadataProvider, max_search_terms: int = 5) -> List[MetadataObject]:
    by_full_name: Dict[str, MetadataObject] = {}
    for term in profile.object_terms[:max_search_terms]:
        for item in metadata_provider.search_objects(term):
            if item.full_name:
                by_full_name[item.full_name] = metadata_provider.get_object(item.full_name)
    return list(by_full_name.values())


def build_candidate(
    *,
    skill: SkillContract,
    profile: SemanticRoleProfile,
    context: ConversationContext,
    metadata_object: MetadataObject,
) -> BindingCandidate:
    object_score = score_object(metadata_object, profile)
    field_score, fields, missing = match_fields(metadata_object, profile)
    config_fingerprint = context.config_fingerprint or "default"
    full_name = metadata_object.full_name
    one_c_object = {
        "full_name": full_name,
        "alias": profile.alias or alias_from_full_name(full_name),
    }
    if profile.virtual_table:
        one_c_object["virtual_table"] = profile.virtual_table
    confidence = round(min(1.0, object_score * 0.55 + field_score * 0.45), 4)
    evidence = [
        f"object:{full_name}",
        f"object_score:{object_score:.3f}",
        f"field_score:{field_score:.3f}",
    ]
    for role, field in sorted(fields.items()):
        evidence.append(f"field:{role}->{field}")
    binding = SkillBinding(
        skill_id=skill.skill_id,
        config_fingerprint=config_fingerprint,
        semantic_role=profile.semantic_role,
        one_c_object=one_c_object,
        fields=fields,
        confidence=confidence,
        evidence=evidence,
    )
    return BindingCandidate(binding=binding, score=confidence, missing_required_fields=missing)


def score_object(metadata_object: MetadataObject, profile: SemanticRoleProfile) -> float:
    if not object_is_compatible(metadata_object, profile):
        return 0.0
    haystack = normalized_words(" ".join([metadata_object.full_name, metadata_object.synonym]))
    term_score = max((term_similarity(term, haystack) for term in profile.object_terms), default=0.0)
    type_score = 0.0
    if profile.object_type_terms:
        type_score = max((term_similarity(term, haystack) for term in profile.object_type_terms), default=0.0)
    return min(1.0, term_score * 0.8 + type_score * 0.2)


def object_is_compatible(metadata_object: MetadataObject, profile: SemanticRoleProfile) -> bool:
    normalized_name = metadata_object.full_name.replace(" ", "").lower()
    if profile.allowed_object_prefixes and not any(
        normalized_name.startswith(prefix.replace(" ", "").lower()) for prefix in profile.allowed_object_prefixes
    ):
        return False
    haystack = normalized_words(" ".join([metadata_object.full_name, metadata_object.synonym]))
    if any(term_similarity(term, haystack) >= 1.0 for term in profile.rejected_object_terms):
        return False
    return True


def match_fields(metadata_object: MetadataObject, profile: SemanticRoleProfile) -> Tuple[float, Dict[str, str], List[str]]:
    fields: Dict[str, str] = {}
    missing: List[str] = []
    field_scores: List[float] = []
    available = list(metadata_object.fields)
    for field_profile in profile.field_roles:
        best_field, score = best_field_match_with_details(field_profile, available, metadata_object.field_details)
        if best_field is not None and score >= field_profile.min_score:
            fields[field_profile.role] = field_name_for_binding(profile, best_field, metadata_object.field_details.get(best_field, {}))
            field_scores.append(score)
            continue
        if field_profile.default:
            fields[field_profile.role] = field_profile.default
            field_scores.append(0.62)
            continue
        if field_profile.required:
            missing.append(field_profile.role)
            field_scores.append(0.0)
        else:
            field_scores.append(0.0)
    if not field_scores:
        return 0.0, fields, missing
    return sum(field_scores) / len(field_scores), fields, missing


def best_field_match(field_profile: FieldRoleProfile, available_fields: List[str]) -> Tuple[Optional[str], float]:
    return best_field_match_with_details(field_profile, available_fields, {})


def best_field_match_with_details(
    field_profile: FieldRoleProfile,
    available_fields: List[str],
    field_details: Dict[str, Dict[str, object]],
) -> Tuple[Optional[str], float]:
    best_field = None
    best_score = 0.0
    for field in available_fields:
        details = field_details.get(field, {})
        score = score_field(field_profile, field, details)
        if score > best_score:
            best_score = score
            best_field = field
    return best_field, best_score


def score_field(field_profile: FieldRoleProfile, field: str, details: Dict[str, object]) -> float:
    field_words = normalized_words(" ".join([field, str(details.get("Синоним") or details.get("synonym") or "")]))
    type_words = normalized_words(str(details.get("Тип") or details.get("type") or ""))
    if any(term_similarity(term, field_words) >= 1.0 for term in field_profile.rejected_field_terms):
        return 0.0
    if any(term_similarity(term, type_words) >= 1.0 for term in field_profile.rejected_type_terms):
        return 0.0

    score = max((term_similarity(term, field_words) for term in field_profile.terms), default=0.0)
    category = str(details.get("_category") or "")
    if field_profile.preferred_categories:
        if category in field_profile.preferred_categories:
            score = min(1.0, score + 0.12)
        elif category:
            score *= 0.65

    if field_profile.preferred_type_terms:
        type_score = max((term_similarity(term, type_words) for term in field_profile.preferred_type_terms), default=0.0)
        if type_score:
            score = min(1.0, score * 0.82 + type_score * 0.18 + 0.05)
        elif type_words:
            score *= 0.9
    return score


def field_name_for_binding(profile: SemanticRoleProfile, field: str, details: Dict[str, object]) -> str:
    if profile.virtual_table == "Остатки" and details.get("_category") == "resource" and not field.endswith("Остаток"):
        return f"{field}Остаток"
    return field


def term_similarity(term: str, haystack_words: List[str]) -> float:
    term_words = normalized_words(term)
    if not term_words or not haystack_words:
        return 0.0
    matches = 0
    for word in term_words:
        if word in haystack_words:
            matches += 1
            continue
        if any(word in haystack or haystack in word for haystack in haystack_words if len(word) >= 4 and len(haystack) >= 4):
            matches += 1
    return matches / len(term_words)


def normalized_words(value: str) -> List[str]:
    compact = re.sub(r"([a-zа-яё])([A-ZА-ЯЁ])", r"\1 \2", value)
    return [item for item in re.split(r"[^0-9A-Za-zА-Яа-яЁё]+", compact.lower()) if item]


def alias_from_full_name(full_name: str) -> str:
    tail = full_name.rsplit(".", 1)[-1]
    alias = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_]", "", tail)
    return alias or "Источник"

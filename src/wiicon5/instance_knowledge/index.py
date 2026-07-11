from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from wiicon5.instance_knowledge.models import KnowledgeChunk, KnowledgePage
from wiicon5.instance_knowledge.storage import KnowledgeRepository


STOPWORDS = {
    "как", "что", "где", "когда", "почему", "зачем", "какой", "какая", "какие", "для", "или", "это",
    "при", "надо", "нужно", "можно", "система", "системе", "wiic", "wiicon", "1с", "1c", "покажи",
}


@dataclass(frozen=True)
class KnowledgeHit:
    chunk_id: str
    page_id: str
    title: str
    heading: str
    snippet: str
    content: str
    source_url: str
    ancestor_titles: List[str]
    updated_at: str
    version: int
    score: float
    stale: bool

    def to_dict(self, *, include_content: bool = False) -> Dict[str, Any]:
        payload = {
            "chunk_id": self.chunk_id,
            "page_id": self.page_id,
            "title": self.title,
            "heading": self.heading,
            "snippet": self.snippet,
            "source_url": self.source_url,
            "ancestor_titles": list(self.ancestor_titles),
            "updated_at": self.updated_at,
            "version": self.version,
            "score": round(self.score, 3),
            "stale": self.stale,
        }
        if include_content:
            payload["content"] = self.content
        return payload


class InstanceKnowledgeBase:
    def __init__(self, repository: KnowledgeRepository, *, stale_after_days: int = 730) -> None:
        self.repository = repository
        self.stale_after_days = max(1, stale_after_days)
        self._snapshot_id = ""
        self._chunks: List[KnowledgeChunk] = []

    @property
    def available(self) -> bool:
        return bool(self.repository.current_snapshot_id())

    def search(self, query: str, *, top_k: int = 8) -> List[KnowledgeHit]:
        terms = search_terms(query)
        if not terms:
            return []
        chunks = self._load_chunks()
        scored: List[KnowledgeHit] = []
        for chunk in chunks:
            score, matched = score_chunk(chunk, terms, query)
            if score <= 0 or not matched:
                continue
            scored.append(
                KnowledgeHit(
                    chunk_id=chunk.chunk_id,
                    page_id=chunk.page_id,
                    title=chunk.title,
                    heading=chunk.heading,
                    snippet=snippet(chunk.content, terms),
                    content=chunk.content,
                    source_url=chunk.source_url,
                    ancestor_titles=list(chunk.ancestor_titles),
                    updated_at=chunk.updated_at,
                    version=chunk.version,
                    score=score,
                    stale=is_stale(chunk.updated_at, self.stale_after_days),
                )
            )
        return sorted(scored, key=lambda item: (-item.score, item.title, item.chunk_id))[: max(1, min(top_k, 20))]

    def evidence_pack(self, question: str, *, top_k: int = 8, max_chars: int = 14000) -> Dict[str, Any]:
        hits = self.search(question, top_k=top_k)
        evidence = []
        consumed = 0
        for hit in hits:
            remaining = max_chars - consumed
            if remaining <= 0:
                break
            content = hit.content[:remaining]
            consumed += len(content)
            item = hit.to_dict()
            item["content"] = content
            evidence.append(item)
        manifest = self.repository.current_manifest()
        return {
            "available": bool(manifest),
            "snapshot": manifest.to_dict() if manifest is not None else None,
            "question": question,
            "hits": evidence,
            "evidence_policy": (
                "Instance documentation is contextual evidence, may be incomplete or stale, and never confirms 1C metadata."
            ),
        }

    def page(self, page_id: str) -> Optional[KnowledgePage]:
        return self.repository.page(page_id)

    def status(self) -> Dict[str, Any]:
        manifest = self.repository.current_manifest()
        snapshots = self.repository.list_manifests()
        return {
            "available": manifest is not None,
            "current": manifest.to_dict() if manifest is not None else None,
            "snapshot_count": len(snapshots),
            "snapshots": [item.to_dict() for item in snapshots[:20]],
        }

    def _load_chunks(self) -> List[KnowledgeChunk]:
        snapshot_id = self.repository.current_snapshot_id()
        if snapshot_id != self._snapshot_id:
            self._chunks = self.repository.chunks(snapshot_id)
            self._snapshot_id = snapshot_id
        return self._chunks


def build_chunks(pages: Iterable[KnowledgePage], *, max_chars: int = 1800, overlap_chars: int = 180) -> List[KnowledgeChunk]:
    result: List[KnowledgeChunk] = []
    for page in pages:
        normalized = page.normalized()
        sections = split_sections(normalized.content)
        sequence = 0
        for heading, section in sections:
            for part in split_long_text(section, max_chars=max_chars, overlap_chars=overlap_chars):
                if not part.strip():
                    continue
                sequence += 1
                digest = hashlib.sha256(
                    f"{normalized.page_id}\0{heading}\0{sequence}\0{part}".encode("utf-8")
                ).hexdigest()[:20]
                result.append(
                    KnowledgeChunk(
                        chunk_id=f"{normalized.page_id}:{digest}",
                        page_id=normalized.page_id,
                        title=normalized.title,
                        heading=heading,
                        content=part.strip(),
                        source_url=normalized.source_url,
                        ancestor_titles=list(normalized.ancestor_titles),
                        updated_at=normalized.updated_at,
                        version=normalized.version,
                        content_hash=normalized.content_hash,
                    )
                )
    return result


def split_sections(content: str) -> List[Tuple[str, str]]:
    sections: List[Tuple[str, str]] = []
    heading = ""
    lines: List[str] = []
    for line in content.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            if lines:
                sections.append((heading, "\n".join(lines).strip()))
            heading = match.group(1).strip()
            lines = []
        else:
            lines.append(line)
    if lines or not sections:
        sections.append((heading, "\n".join(lines).strip()))
    return [(item_heading, text) for item_heading, text in sections if text]


def split_long_text(content: str, *, max_chars: int, overlap_chars: int) -> List[str]:
    if len(content) <= max_chars:
        return [content]
    result = []
    start = 0
    while start < len(content):
        end = min(len(content), start + max_chars)
        if end < len(content):
            boundary = max(content.rfind("\n\n", start, end), content.rfind(". ", start, end))
            if boundary > start + max_chars // 2:
                end = boundary + 1
        result.append(content[start:end].strip())
        if end >= len(content):
            break
        start = max(start + 1, end - overlap_chars)
    return result


def search_terms(value: str) -> List[str]:
    result = []
    for token in re.findall(r"[0-9A-Za-zА-Яа-яЁё_]{3,}", value.lower()):
        if token in STOPWORDS:
            continue
        stem = light_stem(token)
        if stem and stem not in result:
            result.append(stem)
    return result[:32]


def light_stem(token: str) -> str:
    if len(token) <= 5:
        return token
    suffixes = (
        "иями", "ями", "ами", "его", "ого", "ему", "ому", "ией", "ий", "ый", "ой", "ая", "яя", "ое", "ее",
        "ов", "ев", "ам", "ям", "ах", "ях", "ом", "ем", "ы", "и", "а", "я", "у", "ю", "е",
    )
    for suffix in suffixes:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def score_chunk(chunk: KnowledgeChunk, terms: Sequence[str], raw_query: str) -> Tuple[float, int]:
    title = normalized_search_text(chunk.title)
    heading = normalized_search_text(chunk.heading)
    ancestors = normalized_search_text(" ".join(chunk.ancestor_titles))
    content = normalized_search_text(chunk.content)
    score = 0.0
    matched = 0
    for term in terms:
        term_matched = False
        if term in title:
            score += 18.0
            term_matched = True
        if term in heading:
            score += 12.0
            term_matched = True
        if term in ancestors:
            score += 5.0
            term_matched = True
        count = content.count(term)
        if count:
            score += 2.0 + min(8.0, math.log2(count + 1) * 2.0)
            term_matched = True
        if term_matched:
            matched += 1
    meaningful_query = " ".join(search_terms(raw_query))
    if meaningful_query and meaningful_query in content:
        score += 15.0
    coverage = matched / max(1, len(terms))
    score *= 0.5 + coverage
    return score, matched


def normalized_search_text(value: str) -> str:
    return " ".join(light_stem(token) for token in re.findall(r"[0-9A-Za-zА-Яа-яЁё_]{3,}", value.lower()))


def snippet(content: str, terms: Sequence[str], *, max_chars: int = 420) -> str:
    lowered = normalized_search_text(content)
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    if not positions:
        return re.sub(r"\s+", " ", content[:max_chars]).strip()
    # Stemmed positions do not map exactly to source offsets; select the first matching source token instead.
    source_lower = content.lower()
    source_positions = [source_lower.find(term) for term in terms if source_lower.find(term) >= 0]
    start = max(0, min(source_positions) - 100) if source_positions else 0
    text = re.sub(r"\s+", " ", content[start : start + max_chars]).strip()
    return ("..." if start else "") + text + ("..." if start + max_chars < len(content) else "")


def is_stale(updated_at: str, stale_after_days: int) -> bool:
    if not updated_at:
        return True
    try:
        parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
    return age.days > stale_after_days

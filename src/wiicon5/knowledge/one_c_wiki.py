from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


STOPWORDS = {
    "как",
    "что",
    "для",
    "или",
    "это",
    "если",
    "при",
    "чем",
    "надо",
    "нужно",
    "можно",
    "где",
    "когда",
    "the",
    "and",
    "with",
    "from",
    "1с",
    "1c",
    "предприятие",
}


@dataclass(frozen=True)
class OneCWikiHit:
    path: str
    title: str
    category: str
    status: str
    snippet: str
    score: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "title": self.title,
            "category": self.category,
            "status": self.status,
            "snippet": self.snippet,
            "score": self.score,
        }


@dataclass(frozen=True)
class OneCWikiDocument:
    path: str
    title: str
    category: str
    status: str
    content: str
    tokens: List[str]


class EmbeddedOneCWiki:
    def __init__(self, *, root: Optional[Path] = None) -> None:
        self.root = root
        self._documents: Optional[List[OneCWikiDocument]] = None

    def search(self, query: str, *, top_k: int = 5) -> List[OneCWikiHit]:
        terms = query_terms(query)
        if not terms:
            return []
        scored: List[OneCWikiHit] = []
        for document in self._load_documents():
            score = score_document(document, terms)
            if score <= 0:
                continue
            scored.append(
                OneCWikiHit(
                    path=document.path,
                    title=document.title,
                    category=document.category,
                    status=document.status,
                    snippet=snippet_for_terms(document.content, terms),
                    score=score,
                )
            )
        return sorted(scored, key=lambda item: (-item.score, item.path))[: max(1, min(top_k, 20))]

    def answer_pack(self, question: str, *, top_k: int = 5) -> Dict[str, Any]:
        hits = self.search(question, top_k=top_k)
        confidence = "high" if any(hit.status == "answer-ready" for hit in hits[:2]) else "medium" if hits else "none"
        return {
            "question": question,
            "confidence": confidence,
            "needs_curation": confidence != "high",
            "wiki_hits": [hit.to_dict() for hit in hits],
            "answer_md": answer_markdown(question, hits, confidence),
        }

    def get_page(self, path: str) -> Dict[str, Any]:
        normalized = path.strip().lstrip("/")
        for document in self._load_documents():
            if document.path == normalized:
                return {
                    "path": document.path,
                    "title": document.title,
                    "category": document.category,
                    "status": document.status,
                    "content": document.content,
                }
        raise FileNotFoundError(f"Embedded 1C wiki page not found: {path}")

    def _load_documents(self) -> List[OneCWikiDocument]:
        if self._documents is not None:
            return self._documents
        documents = []
        for path, content in iter_markdown_files(self.root):
            relative_path = path.as_posix()
            documents.append(
                OneCWikiDocument(
                    path=relative_path,
                    title=extract_title(content, fallback=path.stem),
                    category=category_for(relative_path),
                    status=extract_status(content),
                    content=content,
                    tokens=query_terms(content, include_stopwords=True),
                )
            )
        self._documents = documents
        return documents


def default_wiki_root() -> Path:
    return Path(str(resources.files("wiicon5.knowledge") / "one_c_wiki"))


def iter_markdown_files(root: Optional[Path]) -> Iterable[tuple[Path, str]]:
    base = root or default_wiki_root()
    for file_path in sorted(base.rglob("*.md")):
        if not file_path.is_file():
            continue
        relative_path = file_path.relative_to(base)
        yield relative_path, file_path.read_text(encoding="utf-8", errors="replace")


def query_terms(text: str, *, include_stopwords: bool = False) -> List[str]:
    terms: List[str] = []
    for token in re.findall(r"[0-9A-Za-zА-Яа-яЁё_]{2,}", text.lower()):
        if not include_stopwords and token in STOPWORDS:
            continue
        if token not in terms:
            terms.append(token)
    return terms[:256 if include_stopwords else 32]


def score_document(document: OneCWikiDocument, terms: List[str]) -> int:
    title = document.title.lower()
    path = document.path.lower()
    content = document.content.lower()
    score = 0
    for term in terms:
        if term in title:
            score += 40
        if term in path:
            score += 15
        score += min(content.count(term), 12)
    if document.status == "answer-ready":
        score += 20
    return score


def snippet_for_terms(content: str, terms: List[str], *, max_len: int = 360) -> str:
    lowered = content.lower()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    start = max(0, min(positions) - 80) if positions else 0
    snippet = re.sub(r"\s+", " ", content[start : start + max_len]).strip()
    if start > 0:
        snippet = "..." + snippet
    if start + max_len < len(content):
        snippet += "..."
    return snippet


def extract_title(text: str, *, fallback: str) -> str:
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return fallback


def extract_status(text: str) -> str:
    match = re.search(r"(?im)^status:\s*`?([^`\n]+)`?", text)
    if match:
        return match.group(1).strip()
    if "## TODO" in text:
        return "overview"
    return "unknown"


def category_for(path: str) -> str:
    parts = path.split("/")
    if parts and parts[0] == "pages" and len(parts) > 1:
        return f"pages/{parts[1]}"
    return parts[0] if parts else "wiki"


def answer_markdown(question: str, hits: List[OneCWikiHit], confidence: str) -> str:
    lines = [
        "# Embedded Wiki 1C answer pack",
        "",
        f"Question: {question}",
        "",
        f"Confidence: `{confidence}`",
    ]
    if not hits:
        lines.extend(["", "No local wiki evidence found."])
        return "\n".join(lines)
    lines.extend(["", "## Evidence"])
    for hit in hits:
        lines.extend(
            [
                "",
                f"### {hit.title}",
                f"- Path: `one_c_wiki/{hit.path}`",
                f"- Status: `{hit.status}`",
                "",
                hit.snippet,
            ]
        )
    return "\n".join(lines)

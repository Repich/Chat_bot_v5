from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from wiicon5.instance_knowledge.models import KnowledgePage, utc_now_iso


class KnowledgeImportError(RuntimeError):
    pass


class ConfluenceClient:
    def __init__(
        self,
        *,
        base_url: str,
        headers: Optional[Mapping[str, str]] = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {str(key): str(value) for key, value in (headers or {}).items() if str(value)}
        self.timeout_seconds = timeout_seconds

    def fetch_tree(self, root_page_id: str, *, max_pages: int = 5000) -> List[KnowledgePage]:
        root_payload = self._get_content(root_page_id)
        pages = [confluence_page(root_payload, self.base_url)]
        queue = [root_page_id]
        seen = {root_page_id}
        while queue:
            parent_id = queue.pop(0)
            for payload in self._children(parent_id):
                page_id = str(payload.get("id") or "")
                if not page_id or page_id in seen:
                    continue
                seen.add(page_id)
                pages.append(confluence_page(payload, self.base_url))
                queue.append(page_id)
                if len(pages) > max_pages:
                    raise KnowledgeImportError(f"Confluence tree exceeds configured limit of {max_pages} pages.")
        return pages

    def _get_content(self, page_id: str) -> Dict[str, Any]:
        path = f"/rest/api/content/{urllib.parse.quote(page_id)}"
        payload = self._get_json(path, {"expand": confluence_expand()})
        if not isinstance(payload, dict):
            raise KnowledgeImportError(f"Confluence page response is not an object: {page_id}")
        return payload

    def _children(self, page_id: str) -> Iterable[Dict[str, Any]]:
        start = 0
        while True:
            path = f"/rest/api/content/{urllib.parse.quote(page_id)}/child/page"
            payload = self._get_json(path, {"expand": confluence_expand(), "limit": "100", "start": str(start)})
            if not isinstance(payload, dict):
                raise KnowledgeImportError(f"Confluence child response is not an object: {page_id}")
            results = payload.get("results") or []
            for item in results:
                if isinstance(item, dict):
                    yield item
            if not results or len(results) < int(payload.get("limit") or 100):
                break
            start += len(results)

    def _get_json(self, path: str, query: Mapping[str, str]) -> Any:
        url = self.base_url + path + "?" + urllib.parse.urlencode(query)
        request_headers = {"Accept": "application/json", "User-Agent": "WIICON-ChatBot-5-Knowledge-Sync/1"}
        request_headers.update(self.headers)
        request = urllib.request.Request(url, headers=request_headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise KnowledgeImportError(f"Confluence HTTP {exc.code} for {path}") from exc
        except OSError as exc:
            raise KnowledgeImportError(f"Confluence connection failed for {path}: {exc}") from exc
        try:
            return json.loads(body)
        except ValueError as exc:
            raise KnowledgeImportError(f"Confluence returned non-JSON content for {path}") from exc


class JsonKnowledgeImporter:
    def load(self, path: Path, *, base_url: str = "") -> List[KnowledgePage]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_pages = payload.get("pages") if isinstance(payload, dict) else payload
        if not isinstance(raw_pages, list):
            raise KnowledgeImportError("Knowledge JSON export must be a list or an object with a pages list.")
        pages = []
        for item in raw_pages:
            if not isinstance(item, dict):
                continue
            if "body" in item or "_links" in item:
                pages.append(confluence_page(item, base_url))
            else:
                pages.append(KnowledgePage.from_dict(item))
        return validate_pages(pages)


class DirectoryKnowledgeImporter:
    def load(self, root: Path, *, base_url: str = "") -> List[KnowledgePage]:
        if not root.is_dir():
            raise KnowledgeImportError(f"Knowledge import directory not found: {root}")
        pages = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".md", ".txt", ".html", ".htm"}:
                continue
            relative = path.relative_to(root)
            raw = path.read_text(encoding="utf-8", errors="replace")
            content = html_to_markdown(raw) if path.suffix.lower() in {".html", ".htm"} else raw.strip()
            page_id = relative.as_posix()
            parent = relative.parent.as_posix() if relative.parent != Path(".") else ""
            ancestors = list(relative.parent.parts) if relative.parent != Path(".") else []
            pages.append(
                KnowledgePage(
                    page_id=page_id,
                    title=markdown_title(content, path.stem),
                    content=content,
                    source_url=(base_url.rstrip("/") + "/" + urllib.parse.quote(relative.as_posix())) if base_url else "",
                    parent_id=parent,
                    ancestor_titles=ancestors,
                    source_kind="directory_export",
                    retrieved_at=utc_now_iso(),
                ).normalized()
            )
        return validate_pages(pages)


def confluence_page(payload: Mapping[str, Any], base_url: str) -> KnowledgePage:
    page_id = str(payload.get("id") or "")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    storage = body.get("storage") if isinstance(body.get("storage"), dict) else {}
    version_payload = payload.get("version") if isinstance(payload.get("version"), dict) else {}
    history = payload.get("history") if isinstance(payload.get("history"), dict) else {}
    ancestors_payload = payload.get("ancestors") if isinstance(payload.get("ancestors"), list) else []
    ancestors = [item for item in ancestors_payload if isinstance(item, dict)]
    links = payload.get("_links") if isinstance(payload.get("_links"), dict) else {}
    web_ui = str(links.get("webui") or "")
    source_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", web_ui.lstrip("/")) if web_ui else ""
    space = payload.get("space") if isinstance(payload.get("space"), dict) else {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    labels_payload = metadata.get("labels") if isinstance(metadata.get("labels"), dict) else {}
    labels = [str(item.get("name") or "") for item in labels_payload.get("results", []) or [] if isinstance(item, dict)]
    return KnowledgePage(
        page_id=page_id,
        title=str(payload.get("title") or page_id),
        content=html_to_markdown(str(storage.get("value") or "")),
        source_url=source_url,
        parent_id=str(ancestors[-1].get("id") or "") if ancestors else "",
        ancestor_ids=[str(item.get("id") or "") for item in ancestors],
        ancestor_titles=[str(item.get("title") or "") for item in ancestors],
        source_kind="confluence",
        space_key=str(space.get("key") or ""),
        version=int(version_payload.get("number") or 0),
        created_at=str(history.get("createdDate") or ""),
        updated_at=str(version_payload.get("when") or ""),
        retrieved_at=utc_now_iso(),
        labels=labels,
    ).normalized()


def confluence_expand() -> str:
    return "body.storage,version,ancestors,space,history,metadata.labels"


def validate_pages(pages: Iterable[KnowledgePage]) -> List[KnowledgePage]:
    result = []
    seen = set()
    for raw_page in pages:
        page = raw_page.normalized()
        if not page.page_id:
            raise KnowledgeImportError("Knowledge page has no id.")
        if page.page_id in seen:
            raise KnowledgeImportError(f"Duplicate knowledge page id: {page.page_id}")
        seen.add(page.page_id)
        result.append(page)
    if not result:
        raise KnowledgeImportError("Knowledge import returned no pages.")
    return result


class StorageHtmlToMarkdown(HTMLParser):
    BLOCK_TAGS = {"p", "div", "section", "article", "tr", "table", "ul", "ol", "blockquote", "pre"}
    SKIP_TAGS = {"script", "style", "ac:parameter"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.skip_depth = 0
        self.link_stack: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        lowered = tag.lower()
        if lowered in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if re.fullmatch(r"h[1-6]", lowered):
            self.parts.append("\n" + "#" * int(lowered[1]) + " ")
        elif lowered == "li":
            self.parts.append("\n- ")
        elif lowered == "br":
            self.parts.append("\n")
        elif lowered in {"td", "th"}:
            self.parts.append(" | ")
        elif lowered in self.BLOCK_TAGS:
            self.parts.append("\n")
        elif lowered == "a":
            href = dict(attrs).get("href") or ""
            self.link_stack.append(href)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if lowered == "a" and self.link_stack:
            href = self.link_stack.pop()
            if href:
                self.parts.append(f" ({href})")
        elif lowered in self.BLOCK_TAGS or re.fullmatch(r"h[1-6]", lowered):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def markdown(self) -> str:
        text = unescape("".join(self.parts))
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_markdown(value: str) -> str:
    parser = StorageHtmlToMarkdown()
    parser.feed(value)
    parser.close()
    return parser.markdown()


def markdown_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return fallback.replace("_", " ").replace("-", " ").strip()

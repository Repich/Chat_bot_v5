# AGENTS.md — Wiki Язык 1С

Schema and workflow for maintaining the `Wiki Язык 1С` knowledge base.

## Role

- Maintain a Markdown wiki about 1C development language and related `1С:Предприятие 8.3.27` platform mechanics.
- Write wiki content in Russian.
- Preserve official 1C terms exactly when they matter.
- Treat this wiki as a synthesis layer, not as a copy of official documentation or books.

## Source Policy

- Raw sources are immutable.
- Official 1C documentation and books are source-of-truth references, not content to be reproduced wholesale.
- Store source metadata, links, page/chapter references, short summaries, and synthesized explanations.
- Full raw text may be captured only after explicit user approval for the bounded scope.
- Store protected full raw text outside Nextcloud under the WorkAssistant runtime tree; keep only manifests, hashes, and local paths in this wiki.
- Do not store credentials, session cookies, or private access tokens in this wiki.
- Do not log in to ITS or download protected content unless the user explicitly confirms that step.
- Use short quotes only when necessary; prefer paraphrase plus source reference.

## Directory Layout

- `raw/` — manifests and metadata for immutable source captures; protected full text is stored outside Nextcloud.
- `sources/manifest.md` — source catalog and access notes.
- `pages/concepts/` — conceptual pages, e.g. modules, contexts, data types.
- `pages/syntax/` — language syntax pages.
- `pages/runtime/` — execution model and runtime behavior.
- `pages/query-language/` — 1C query language.
- `pages/platform/` — platform mechanisms that affect language behavior.
- `index.md` — content-oriented catalog.
- `log.md` — append-only operation log.

## Page Format

Each content page should use this structure:

```markdown
# <Название>

## Коротко

<2-5 sentences>

## Когда используется

<practical usage>

## Как работает

<mechanics and constraints>

## Примеры

<small examples, preferably original>

## Связанные страницы

- [[...]]

## Источники

- <source id>, <chapter/page/link>
```

## Ingest Workflow

- Read one source or one bounded source section at a time.
- If the source is official/protected and the user approved raw capture, save full HTML/TXT to runtime raw storage before synthesis.
- Extract key claims, definitions, examples, and caveats.
- Create or update relevant wiki pages.
- Assign a quality status from `quality.md`: `raw-only`, `overview`, `answer-ready`, or `verified`.
- A practical topic is not done until its page can answer control questions without raw source lookup.
- Update `index.md`.
- Update raw/source manifests with paths, checksums, byte sizes, and capture timestamp.
- Update `sources/coverage-map.md` and `sources/control-questions.md` when coverage changes.
- Append an entry to `log.md`.
- Note contradictions, version-specific behavior, or unclear points.

## Answer-Ready On Demand

- Do not pre-generate `answer-ready` pages for the whole source corpus.
- Create or promote `answer-ready` pages when a real user question exposes a practical topic.
- A question about 1C should usually produce two outputs:
  - a concise answer to the user;
  - a reusable wiki page, if no sufficient `answer-ready` page exists yet.
- Merge related methodology/Q&A source documents into one practical topic page instead of creating one page per raw document.
- Prefer high-value topic clusters: query language and optimization, virtual tables, transactions, locks, forms, dynamic lists, registers, common modules, integration/exchange, diagnostics.
- After creating or promoting a page, update `sources/coverage-map.md`, `sources/control-questions.md`, `index.md`, `viewer.html`, `log.md`, thread memory, and action-log.

## Query Workflow

- Start from `index.md`.
- Read the relevant wiki pages before answering.
- If the wiki lacks evidence, search raw sources before answering.
- If raw sources contain the answer, create or update the covering `answer-ready` page first, then answer from that page.
- If neither wiki nor raw sources contain the answer, say that explicitly and propose the next source to ingest.

## Local Service Workflow

- Other Codex threads should query this wiki through `tools/wiki_1c_query.py` or the MCP wrapper `tools/wiki_1c_mcp.py`.
- The service may return evidence and short raw snippets, but it must not copy full raw text into the project.
- If another thread needs a reusable answer and the service returns `needs_curation=true`, it should create a queue item with `request-curation`.
- Curation queue path: `data/wiki_1c_service/curation_queue/`.
- The `wiki-1c-language` thread remains the normal writer for `answer-ready` pages and must update coverage, viewer, memory, and action-log after curation.

## Lint Workflow

Periodically check:

- orphan pages;
- pages without sources;
- source sections without wiki coverage;
- `overview` pages that should be promoted to `answer-ready`;
- duplicated concepts;
- stale claims after new source ingest;
- missing cross-links;
- unfilled TODOs;
- overlong pages that should be split.

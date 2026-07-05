from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Type
from urllib.parse import parse_qs, unquote, urlparse

from wiicon5.agent.orchestrator import AgentOrchestrator
from wiicon5.conversation.context import ResolvedEntity
from wiicon5.execution.artifacts import Artifact
from wiicon5.onboarding.status import OnboardingManager
from wiicon5.workbench.metadata_explorer import MetadataExplorerService
from wiicon5.workbench.models import HumanSkillDraft
from wiicon5.workbench.skill_catalog import SkillCatalogService
from wiicon5.workbench.store import HumanSkillDraftStore


PROJECT_ROOT = Path(__file__).resolve().parents[3]
VERSION_FILE = PROJECT_ROOT / "VERSION"
BACKEND_HISTORY_FILE = PROJECT_ROOT / "docs" / "backend" / "history.txt"
FRONTEND_HISTORY_FILE = PROJECT_ROOT / "docs" / "frontend" / "history.txt"


def make_handler(
    agent: AgentOrchestrator,
    onboarding_manager: OnboardingManager | None = None,
    skill_catalog: SkillCatalogService | None = None,
    metadata_explorer: MetadataExplorerService | None = None,
    draft_store: HumanSkillDraftStore | None = None,
) -> Type[BaseHTTPRequestHandler]:
    effective_onboarding_manager = onboarding_manager or OnboardingManager(
        bot_instance_root=PROJECT_ROOT / "bot_instances" / "local"
    )
    effective_skill_catalog = skill_catalog or SkillCatalogService(
        global_skills_dir=PROJECT_ROOT / "skills",
        bot_instance_root=effective_onboarding_manager.bot_instance_root,
    )
    effective_metadata_explorer = metadata_explorer or MetadataExplorerService.from_bot_instance(
        effective_onboarding_manager.bot_instance_root
    )
    effective_draft_store = draft_store or HumanSkillDraftStore(
        bot_instance_root=effective_onboarding_manager.bot_instance_root,
        bot_id=effective_onboarding_manager.bot_instance_root.name or "local",
    )

    class Wiicon5Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if path == "/health":
                self._send_json(200, {"ok": True, "service": "wiicon5"})
                return
            if path == "/api/version":
                self._send_json(200, {"ok": True, "service": "wiicon5", "version": current_version()})
                return
            if path == "/api/conversation":
                session_id = first_query_value(query, "session_id") or "default"
                context = agent.memory.get_or_create(session_id)
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "session_id": context.session_id,
                        "messages": [message.to_dict() for message in context.messages],
                    },
                )
                return
            if path == "/api/conversations":
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "sessions": [conversation_summary(context) for context in agent.memory.list_contexts()],
                    },
                )
                return
            if path == "/api/admin/onboarding/status":
                self._send_json(200, {"ok": True, "status": effective_onboarding_manager.status().to_dict()})
                return
            if path == "/api/admin/workbench/drafts":
                self._send_json(
                    200,
                    {"ok": True, "drafts": [draft.to_dict() for draft in effective_draft_store.list_drafts()]},
                )
                return
            if path.startswith("/api/admin/workbench/drafts/"):
                draft_id = unquote(path.rsplit("/", 1)[-1])
                draft = effective_draft_store.get_draft(draft_id)
                if draft is None:
                    self._send_json(404, {"ok": False, "error": "draft_not_found", "draft_id": draft_id})
                    return
                self._send_json(200, {"ok": True, "draft": draft.to_dict()})
                return
            if path == "/api/admin/workbench/audit":
                object_id = first_query_value(query, "object_id")
                events = (
                    effective_draft_store.audit.filter_by_object(object_id)
                    if object_id
                    else effective_draft_store.audit.read()
                )
                self._send_json(200, {"ok": True, "events": [event.to_dict() for event in events]})
                return
            if path == "/api/admin/skills/catalog":
                snapshot = effective_skill_catalog.snapshot()
                self._send_json(200, {"ok": True, **snapshot.to_dict()})
                return
            if path.startswith("/api/admin/skills/catalog/"):
                skill_id = unquote(path.rsplit("/", 1)[-1])
                item = effective_skill_catalog.snapshot().get(skill_id)
                if item is None:
                    self._send_json(404, {"ok": False, "error": "skill_not_found", "skill_id": skill_id})
                    return
                self._send_json(200, {"ok": True, "skill": item.to_dict()})
                return
            if path == "/api/admin/metadata/search":
                term = first_query_value(query, "q") or first_query_value(query, "term")
                limit = int_or_default(first_query_value(query, "limit"), 20)
                self._send_json(200, {"ok": True, **effective_metadata_explorer.search(term, limit=limit)})
                return
            if path == "/api/admin/metadata/object":
                full_name = first_query_value(query, "full_name") or first_query_value(query, "name")
                result = effective_metadata_explorer.get_object(full_name)
                if not result.get("found"):
                    self._send_json(404, {"ok": False, "error": "metadata_object_not_found", **result})
                    return
                self._send_json(200, {"ok": True, **result})
                return
            if path == "/history/backend":
                self._send_text(200, read_text_file(BACKEND_HISTORY_FILE))
                return
            if path == "/history/frontend":
                self._send_text(200, read_text_file(FRONTEND_HISTORY_FILE))
                return
            if path in {"/", "/chat"}:
                self._send_html(200, CHAT_HTML)
                return
            self._send_json(404, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/admin/onboarding/run":
                try:
                    payload = self._read_json()
                    config_dump = str(payload.get("config_dump") or "").strip()
                    if not config_dump:
                        self._send_json(400, {"ok": False, "error": "config_dump is required"})
                        return
                    status = effective_onboarding_manager.start(
                        config_dump=Path(config_dump).expanduser(),
                        mcp_url=str(payload.get("mcp_url") or "").strip() or None,
                        background=True,
                    )
                    self._send_json(202, {"ok": True, "status": status.to_dict()})
                except Exception as exc:
                    self._send_json(500, {"ok": False, "error": str(exc)})
                return
            if parsed.path != "/chat":
                if parsed.path == "/api/admin/workbench/drafts":
                    self._create_draft()
                    return
                self._send_json(404, {"ok": False, "error": "not_found"})
                return
            try:
                payload = self._read_json()
                message = str(payload.get("message") or "").strip()
                if not message:
                    self._send_json(400, {"ok": False, "error": "message is required"})
                    return
                session_id = str(payload.get("session_id") or "default")
                seed_context_from_payload(agent, session_id, payload)
                result = agent.handle(message, session_id=session_id)
                self._send_json(200, {"ok": True, "result": result.to_dict()})
            except Exception as exc:  # Keep HTTP layer diagnostic rather than crashing the server.
                self._send_json(500, {"ok": False, "error": str(exc)})

        def do_PATCH(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/admin/workbench/drafts/"):
                draft_id = unquote(parsed.path.rsplit("/", 1)[-1])
                self._update_draft(draft_id)
                return
            self._send_json(404, {"ok": False, "error": "not_found"})

        def do_PUT(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/admin/workbench/drafts/"):
                draft_id = unquote(parsed.path.rsplit("/", 1)[-1])
                self._update_draft(draft_id)
                return
            self._send_json(404, {"ok": False, "error": "not_found"})

        def do_DELETE(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/admin/workbench/drafts/"):
                draft_id = unquote(parsed.path.rsplit("/", 1)[-1])
                actor = first_query_value(parse_qs(parsed.query), "actor") or "admin"
                if not effective_draft_store.delete_draft(draft_id, actor=actor):
                    self._send_json(404, {"ok": False, "error": "draft_not_found", "draft_id": draft_id})
                    return
                self._send_json(200, {"ok": True, "draft_id": draft_id})
                return
            self._send_json(404, {"ok": False, "error": "not_found"})

        def _create_draft(self) -> None:
            try:
                payload = self._read_json()
                actor = str(payload.get("actor") or "admin")
                draft_payload = payload.get("draft") if isinstance(payload.get("draft"), dict) else payload
                draft = HumanSkillDraft.from_dict(draft_payload)
                created = effective_draft_store.create_draft(draft, actor=actor)
                self._send_json(201, {"ok": True, "draft": created.to_dict()})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def _update_draft(self, draft_id: str) -> None:
            try:
                payload = self._read_json()
                actor = str(payload.get("actor") or "admin")
                changes = payload.get("draft") if isinstance(payload.get("draft"), dict) else dict(payload)
                changes.pop("actor", None)
                updated = effective_draft_store.update_draft(draft_id, changes, actor=actor)
                self._send_json(200, {"ok": True, "draft": updated.to_dict()})
            except KeyError:
                self._send_json(404, {"ok": False, "error": "draft_not_found", "draft_id": draft_id})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def _read_json(self) -> Dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length).decode("utf-8", errors="replace")
            data = json.loads(raw or "{}")
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object.")
            return data

        def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_text(self, status_code: int, text: str) -> None:
            raw = text.encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_html(self, status_code: int, html: str) -> None:
            raw = html.encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: Any) -> None:
            return None

    return Wiicon5Handler


def current_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip() + "\n"
    except OSError:
        return "История изменений пока не найдена.\n"


def first_query_value(query: Dict[str, list[str]], name: str) -> str:
    values = query.get(name) or []
    return values[0].strip() if values else ""


def int_or_default(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def conversation_summary(context) -> Dict[str, Any]:
    latest = context.messages[-1] if context.messages else None
    preview = latest.content if latest else ""
    return {
        "session_id": context.session_id,
        "message_count": len(context.messages),
        "updated_at": latest.ts if latest else "",
        "preview": preview[:140],
    }


def seed_context_from_payload(agent: AgentOrchestrator, session_id: str, payload: Dict[str, Any]) -> None:
    product_ref = payload.get("product_ref")
    if not product_ref:
        return
    context = agent.memory.get_or_create(session_id)
    value = {"ref": product_ref} if isinstance(product_ref, str) else product_ref
    context.add_artifact(Artifact(name="product", type="ProductRef", value=value, provenance=["http_payload"]))
    context.add_resolved_entity(
        ResolvedEntity(role="product", artifact_type="ProductRef", value=value, source="http_payload", confidence=1.0)
    )


def run_http_server(
    agent: AgentOrchestrator,
    *,
    host: str,
    port: int,
    onboarding_manager: OnboardingManager | None = None,
) -> None:
    server = HTTPServer((host, port), make_handler(agent, onboarding_manager=onboarding_manager))
    try:
        server.serve_forever()
    finally:
        server.server_close()


CHAT_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WIICON ChatBot 5</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f8;
      --panel: #ffffff;
      --line: #d7dce0;
      --text: #1b1f23;
      --muted: #5b6670;
      --accent: #0f766e;
      --accent-strong: #0b5f59;
      --danger: #b42318;
      --warning-bg: #fff7ed;
      --warning-line: #fed7aa;
      --ok-bg: #ecfdf5;
      --ok-line: #a7f3d0;
      --code: #111827;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      overflow: hidden;
    }
    .app {
      height: 100vh;
      min-height: 0;
      display: grid;
      grid-template-rows: auto auto minmax(0, 1fr);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 18px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    .training-banner {
      display: none;
      border-bottom: 1px solid var(--warning-line);
      background: var(--warning-bg);
      padding: 6px 18px;
      color: #7c2d12;
      font-size: 12px;
      line-height: 1.35;
      min-height: 30px;
      align-items: center;
    }
    .training-banner.visible {
      display: flex;
    }
    .training-banner.trained {
      border-color: var(--ok-line);
      background: var(--ok-bg);
      color: #064e3b;
    }
    h1 {
      margin: 0;
      font-size: 18px;
      line-height: 1.2;
      font-weight: 650;
      letter-spacing: 0;
    }
    .title {
      display: flex;
      align-items: baseline;
      gap: 10px;
      min-width: 0;
    }
    .version {
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--accent);
    }
    main {
      width: 100%;
      max-width: 1680px;
      margin: 0 auto;
      padding: 12px 16px 16px;
      min-height: 0;
      height: 100%;
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      gap: 12px;
    }
    aside, .dialog {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    aside {
      padding: 12px;
      align-self: stretch;
      max-height: 100%;
      overflow: auto;
      display: grid;
      gap: 12px;
      align-content: start;
    }
    .sidebar-section {
      display: grid;
      gap: 8px;
    }
    .sidebar-title {
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .session-actions {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
    }
    .session-list {
      display: grid;
      gap: 6px;
      max-height: 36vh;
      overflow: auto;
      padding-right: 2px;
    }
    .session-button {
      width: 100%;
      min-width: 0;
      min-height: 0;
      display: grid;
      gap: 3px;
      justify-items: start;
      text-align: left;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      padding: 8px 9px;
      font-weight: 500;
      cursor: pointer;
    }
    .session-button:hover { background: #f2f5f5; }
    .session-button.active {
      border-color: #8bc8c0;
      background: #eef8f6;
    }
    .session-name {
      width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 13px;
      font-weight: 650;
    }
    .session-meta {
      width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.25;
    }
    .settings-panel {
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }
    .settings-panel > summary {
      cursor: pointer;
      color: var(--text);
      font-size: 13px;
      font-weight: 650;
      list-style: none;
    }
    .settings-panel > summary::-webkit-details-marker { display: none; }
    .settings-panel > summary::before {
      content: "▸";
      display: inline-block;
      width: 14px;
      color: var(--muted);
    }
    .settings-panel[open] > summary::before { content: "▾"; }
    .settings-content {
      display: grid;
      gap: 12px;
      padding-top: 10px;
    }
    .tools {
      display: grid;
      gap: 8px;
    }
    .tool-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    label {
      display: grid;
      gap: 6px;
      font-size: 13px;
      color: var(--muted);
    }
    input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      font: inherit;
      font-size: 14px;
      line-height: 1.35;
      padding: 9px 10px;
    }
    textarea {
      min-height: 94px;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }
    .dialog {
      min-height: 0;
      height: 100%;
      display: grid;
      grid-template-rows: minmax(0, 1fr) auto;
      overflow: hidden;
    }
    .messages {
      padding: 18px;
      overflow: auto;
      display: grid;
      align-content: start;
      gap: 12px;
    }
    .empty {
      color: var(--muted);
      font-size: 14px;
      padding: 12px 0;
    }
    .message {
      max-width: 88%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      background: #fff;
    }
    .message.user {
      justify-self: end;
      border-color: #b8d7d3;
      background: #eef8f6;
    }
    .message.error {
      border-color: #f0b5ae;
      background: #fff4f2;
    }
    .meta {
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 12px;
    }
    .content {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font-size: 14px;
      line-height: 1.45;
    }
    details {
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
    }
    pre {
      margin: 8px 0 0;
      max-height: 260px;
      overflow: auto;
      padding: 10px;
      border-radius: 6px;
      background: var(--code);
      color: #f9fafb;
      font-size: 12px;
      line-height: 1.4;
    }
    form {
      border-top: 1px solid var(--line);
      padding: 12px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      background: #fbfbfc;
      position: sticky;
      bottom: 0;
      z-index: 2;
    }
    form textarea {
      min-height: 48px;
      max-height: 170px;
      font-family: inherit;
      font-size: 14px;
    }
    button {
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: #fff;
      font: inherit;
      font-weight: 600;
      padding: 0 18px;
      min-width: 110px;
      cursor: pointer;
    }
    button:hover { background: var(--accent-strong); }
    button.secondary {
      min-width: 0;
      min-height: 36px;
      padding: 0 10px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      font-weight: 550;
    }
    button.secondary:hover { background: #f2f5f5; }
    button:disabled {
      cursor: wait;
      opacity: 0.65;
    }
    .history-panel {
      display: none;
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }
    .history-panel.visible { display: block; }
    .history-title {
      margin: 0 0 8px;
      font-size: 13px;
      color: var(--muted);
      font-weight: 650;
    }
    .history-panel pre {
      max-height: 280px;
      white-space: pre-wrap;
      background: #f8fafc;
      color: var(--text);
      border: 1px solid var(--line);
    }
    .danger { color: var(--danger); }
    .admin-panel {
      display: grid;
      gap: 8px;
      padding-top: 0;
      border-top: 1px solid var(--line);
    }
    .admin-title {
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      font-weight: 650;
    }
    .admin-status {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      white-space: pre-wrap;
    }
    @media (max-width: 760px) {
      body { overflow: hidden; }
      header { align-items: flex-start; flex-direction: column; }
      main {
        grid-template-columns: 1fr;
        grid-template-rows: auto minmax(0, 1fr);
        padding: 12px;
        overflow: hidden;
      }
      aside {
        max-height: 32vh;
      }
      .session-list {
        max-height: 16vh;
      }
      form { grid-template-columns: 1fr; }
      button { min-height: 42px; }
      .message { max-width: 100%; }
    }
  </style>
</head>
<body>
  <div class="app">
    <header>
      <div class="title">
        <h1>WIICON ChatBot 5</h1>
        <span class="version">v<span id="appVersion">...</span></span>
      </div>
      <div class="status"><span class="dot"></span><span id="status">готов</span></div>
    </header>
    <div id="trainingBanner" class="training-banner"></div>
    <main>
      <aside>
        <div class="sidebar-section">
          <label>Session ID
            <input id="sessionId" value="web-test" autocomplete="off">
          </label>
          <div class="session-actions">
            <button id="newSessionButton" class="secondary" type="button">Новая сессия</button>
          </div>
        </div>
        <div class="sidebar-section">
          <p class="sidebar-title">Сессии</p>
          <div id="sessionList" class="session-list"></div>
          <div id="sessionListEmpty" class="empty">Сохраненных сессий пока нет.</div>
        </div>
        <details id="settingsDetails" class="settings-panel">
          <summary>Настройки</summary>
          <div class="settings-content">
            <div class="tools">
              <button id="reloadHistoryButton" class="secondary" type="button">Обновить диалог</button>
              <div class="tool-row">
                <button id="backendHistoryButton" class="secondary" type="button">Backend</button>
                <button id="frontendHistoryButton" class="secondary" type="button">Frontend</button>
              </div>
            </div>
            <div id="historyPanel" class="history-panel">
              <p id="historyTitle" class="history-title"></p>
              <pre id="historyText"></pre>
            </div>
            <div class="admin-panel">
              <p class="admin-title">Первоначальное обучение</p>
              <label>Выгрузка конфигурации
                <input id="configDumpPath" placeholder="/path/to/1c/config">
              </label>
              <button id="startOnboardingButton" class="secondary" type="button">Запустить обучение</button>
              <div id="onboardingStatus" class="admin-status">Статус не загружен.</div>
            </div>
            <label>ProductRef JSON
              <textarea id="productRef" spellcheck="false"></textarea>
            </label>
          </div>
        </details>
      </aside>
      <section class="dialog" aria-label="chat">
        <div id="messages" class="messages">
          <div class="empty">Добрый день. Задайте вопрос по WIICON или WIIC.</div>
        </div>
        <form id="chatForm">
          <textarea id="messageInput" placeholder="Введите сообщение" required autofocus></textarea>
          <button id="sendButton" type="submit">Отправить</button>
        </form>
      </section>
    </main>
  </div>
  <script>
    const SESSION_STORAGE_KEY = "wiicon5.sessionId";
    const SESSION_LIST_STORAGE_KEY = "wiicon5.sessionList";
    const form = document.getElementById("chatForm");
    const input = document.getElementById("messageInput");
    const sendButton = document.getElementById("sendButton");
    const messages = document.getElementById("messages");
    const statusText = document.getElementById("status");
    const sessionId = document.getElementById("sessionId");
    const newSessionButton = document.getElementById("newSessionButton");
    const sessionList = document.getElementById("sessionList");
    const sessionListEmpty = document.getElementById("sessionListEmpty");
    const productRef = document.getElementById("productRef");
    const appVersion = document.getElementById("appVersion");
    const reloadHistoryButton = document.getElementById("reloadHistoryButton");
    const backendHistoryButton = document.getElementById("backendHistoryButton");
    const frontendHistoryButton = document.getElementById("frontendHistoryButton");
    const historyPanel = document.getElementById("historyPanel");
    const historyTitle = document.getElementById("historyTitle");
    const historyText = document.getElementById("historyText");
    const settingsDetails = document.getElementById("settingsDetails");
    const trainingBanner = document.getElementById("trainingBanner");
    const configDumpPath = document.getElementById("configDumpPath");
    const startOnboardingButton = document.getElementById("startOnboardingButton");
    const onboardingStatus = document.getElementById("onboardingStatus");
    let pending = false;
    let onboardingPollTimer = null;
    const baseTitle = document.title;
    let unreadCount = 0;
    let titleBlinkTimer = null;
    let titleBlinkOn = false;

    const savedSessionId = localStorage.getItem(SESSION_STORAGE_KEY);
    if (savedSessionId) sessionId.value = savedSessionId;

    function effectiveSessionId() {
      return sessionId.value.trim() || "web-test";
    }

    function readLocalSessions() {
      try {
        const parsed = JSON.parse(localStorage.getItem(SESSION_LIST_STORAGE_KEY) || "[]");
        return Array.isArray(parsed) ? parsed.filter(item => item && item.session_id) : [];
      } catch (error) {
        return [];
      }
    }

    function writeLocalSessions(items) {
      localStorage.setItem(SESSION_LIST_STORAGE_KEY, JSON.stringify(items.slice(0, 30)));
    }

    function rememberSession(id, patch = {}) {
      const session = String(id || "").trim();
      if (!session) return;
      localStorage.setItem(SESSION_STORAGE_KEY, session);
      const now = new Date().toISOString();
      const items = readLocalSessions();
      const existingIndex = items.findIndex(item => item.session_id === session);
      const existing = existingIndex >= 0 ? items.splice(existingIndex, 1)[0] : {};
      items.unshift({
        session_id: session,
        updated_at: patch.updated_at || now,
        message_count: patch.message_count ?? existing.message_count ?? 0,
        preview: patch.preview || existing.preview || "",
        local: true
      });
      writeLocalSessions(items);
    }

    function mergeSessions(localItems, serverItems) {
      const byId = new Map();
      for (const item of localItems) {
        byId.set(item.session_id, {...item, local: true});
      }
      for (const item of serverItems) {
        if (!item || !item.session_id) continue;
        const existing = byId.get(item.session_id) || {};
        byId.set(item.session_id, {
          ...existing,
          ...item,
          local: Boolean(existing.local),
          server: true
        });
      }
      return Array.from(byId.values()).sort((left, right) => {
        return String(right.updated_at || "").localeCompare(String(left.updated_at || ""));
      });
    }

    function renderSessionList(items) {
      sessionList.replaceChildren();
      const active = effectiveSessionId();
      sessionListEmpty.style.display = items.length ? "none" : "block";
      for (const item of items) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "session-button" + (item.session_id === active ? " active" : "");
        const name = document.createElement("span");
        name.className = "session-name";
        name.textContent = item.session_id;
        const meta = document.createElement("span");
        meta.className = "session-meta";
        const count = Number(item.message_count || 0);
        const source = item.server ? "в памяти" : "локально";
        meta.textContent = count ? `${count} сообщ. · ${source}` : source;
        const preview = document.createElement("span");
        preview.className = "session-meta";
        preview.textContent = item.preview || "Нет сообщений в текущем процессе.";
        button.append(name, meta, preview);
        button.addEventListener("click", () => {
          sessionId.value = item.session_id;
          rememberSession(item.session_id);
          loadConversation();
        });
        sessionList.append(button);
      }
    }

    async function loadSessionList() {
      let serverSessions = [];
      try {
        const response = await fetch("/api/conversations", {cache: "no-store"});
        const data = await response.json();
        if (response.ok && data.ok && Array.isArray(data.sessions)) {
          serverSessions = data.sessions;
        }
      } catch (error) {
        serverSessions = [];
      }
      const localSessions = readLocalSessions();
      renderSessionList(mergeSessions(localSessions, serverSessions));
    }

    function clearEmpty() {
      const empty = messages.querySelector(".empty");
      if (empty) empty.remove();
    }

    function setStatus(text) {
      statusText.textContent = text;
    }

    function shouldMarkUnread() {
      return document.hidden || !document.hasFocus();
    }

    function startTitleBlink() {
      if (titleBlinkTimer) return;
      titleBlinkTimer = window.setInterval(() => {
        titleBlinkOn = !titleBlinkOn;
        document.title = titleBlinkOn ? `(${unreadCount}) Новое сообщение` : baseTitle;
      }, 900);
    }

    function markUnread() {
      unreadCount += 1;
      startTitleBlink();
    }

    function clearUnread() {
      unreadCount = 0;
      titleBlinkOn = false;
      if (titleBlinkTimer) {
        window.clearInterval(titleBlinkTimer);
        titleBlinkTimer = null;
      }
      document.title = baseTitle;
    }

    function appendMessage(kind, title, text, raw, scroll = true) {
      clearEmpty();
      const node = document.createElement("article");
      node.className = "message " + kind;
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = title;
      const content = document.createElement("div");
      content.className = "content";
      content.textContent = text || "";
      node.append(meta, content);
      if (raw) {
        const details = document.createElement("details");
        const summary = document.createElement("summary");
        summary.textContent = "details";
        const pre = document.createElement("pre");
        pre.textContent = JSON.stringify(raw, null, 2);
        details.append(summary, pre);
        node.append(details);
      }
      messages.append(node);
      if (scroll) messages.scrollTop = messages.scrollHeight;
      if ((kind === "assistant" || kind === "error") && shouldMarkUnread()) {
        markUnread();
      }
    }

    function showEmpty(text) {
      messages.replaceChildren();
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = text;
      messages.append(empty);
    }

    async function loadVersion() {
      try {
        const response = await fetch("/api/version", {cache: "no-store"});
        const data = await response.json();
        appVersion.textContent = data.version || "unknown";
      } catch (error) {
        appVersion.textContent = "unknown";
      }
    }

    function renderOnboardingStatus(status) {
      const state = status && status.state ? status.state : "unknown";
      const trained = Boolean(status && status.trained);
      const running = Boolean(status && status.running);
      const message = status && status.message ? status.message : "Статус обучения неизвестен.";
      if (status && status.config_dump && !configDumpPath.value.trim()) {
        configDumpPath.value = status.config_dump;
      }
      startOnboardingButton.disabled = running;
      const details = [];
      details.push(message);
      if (status && status.objects_count) details.push("Объектов: " + status.objects_count);
      if (status && status.query_patterns_count) details.push("Шаблонов запросов: " + status.query_patterns_count);
      if (status && status.binding_candidates_count) details.push("Кандидатов binding: " + status.binding_candidates_count);
      if (status && status.error) details.push("Ошибка: " + status.error);
      onboardingStatus.textContent = details.join("\\n");

      trainingBanner.classList.add("visible");
      trainingBanner.classList.toggle("trained", trained);
      if (trained) {
        const objects = status && status.objects_count ? status.objects_count : 0;
        const patterns = status && status.query_patterns_count ? status.query_patterns_count : 0;
        trainingBanner.textContent = `Обучение выполнено: ${objects} объектов, ${patterns} шаблонов.`;
      } else if (running) {
        trainingBanner.textContent = "Идет первоначальное обучение. До завершения агент может отвечать медленнее и ошибаться в выборе объектов конфигурации.";
      } else {
        trainingBanner.textContent = "Первоначальное обучение еще не выполнено. Возможны неверные ответы: агент пока опирается только на MCP-поиск и текущий диалог.";
      }
      setStatus(running ? "обучение" : "готов");
      return {state, running};
    }

    async function loadOnboardingStatus() {
      try {
        const response = await fetch("/api/admin/onboarding/status", {cache: "no-store"});
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "HTTP " + response.status);
        const rendered = renderOnboardingStatus(data.status || {});
        if (rendered.running && !onboardingPollTimer) {
          onboardingPollTimer = window.setInterval(loadOnboardingStatus, 3000);
        }
        if (!rendered.running && onboardingPollTimer) {
          window.clearInterval(onboardingPollTimer);
          onboardingPollTimer = null;
        }
      } catch (error) {
        trainingBanner.classList.add("visible");
        trainingBanner.textContent = "Статус первоначального обучения не удалось загрузить.";
        onboardingStatus.textContent = String(error && error.message ? error.message : error);
      }
    }

    async function startOnboarding() {
      const path = configDumpPath.value.trim();
      if (!path) {
        onboardingStatus.textContent = "Укажите путь к файловой выгрузке конфигурации.";
        configDumpPath.focus();
        return;
      }
      startOnboardingButton.disabled = true;
      setStatus("запуск обучения");
      try {
        const response = await fetch("/api/admin/onboarding/run", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({config_dump: path})
        });
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "HTTP " + response.status);
        renderOnboardingStatus(data.status || {});
        if (!onboardingPollTimer) onboardingPollTimer = window.setInterval(loadOnboardingStatus, 3000);
      } catch (error) {
        onboardingStatus.textContent = String(error && error.message ? error.message : error);
        startOnboardingButton.disabled = false;
        setStatus("готов");
      }
    }

    async function loadConversation() {
      const currentId = effectiveSessionId();
      rememberSession(currentId);
      setStatus("загрузка истории");
      try {
        const response = await fetch("/api/conversation?session_id=" + encodeURIComponent(currentId), {
          cache: "no-store"
        });
        const data = await response.json();
        if (!response.ok || !data.ok) {
          showEmpty("Историю сессии не удалось загрузить.");
          return;
        }
        messages.replaceChildren();
        const items = Array.isArray(data.messages) ? data.messages : [];
        if (!items.length) {
          showEmpty("Добрый день. Задайте вопрос по WIICON или WIIC.");
          rememberSession(currentId, {message_count: 0, preview: ""});
          await loadSessionList();
          return;
        }
        for (const item of items) {
          const role = item.role || "assistant";
          appendMessage(
            role === "user" ? "user" : "assistant",
            role === "user" ? "Вы" : "Агент",
            item.content || "",
            null,
            false
          );
        }
        const latest = items[items.length - 1] || {};
        rememberSession(currentId, {
          message_count: items.length,
          preview: latest.content || "",
          updated_at: latest.ts || new Date().toISOString()
        });
        await loadSessionList();
        messages.scrollTop = messages.scrollHeight;
      } catch (error) {
        showEmpty("Историю сессии не удалось загрузить.");
        await loadSessionList();
      } finally {
        setStatus("готов");
      }
    }

    async function showHistory(kind) {
      const title = kind === "backend" ? "Backend history.txt" : "Frontend history.txt";
      const url = kind === "backend" ? "/history/backend" : "/history/frontend";
      historyPanel.classList.add("visible");
      historyTitle.textContent = title;
      historyText.textContent = "Загрузка...";
      try {
        const response = await fetch(url, {cache: "no-store"});
        historyText.textContent = await response.text();
      } catch (error) {
        historyText.textContent = "Не удалось загрузить историю изменений.";
      }
    }

    function payloadProductRef() {
      const value = productRef.value.trim();
      if (!value) return undefined;
      if (value.startsWith("{")) return JSON.parse(value);
      return value;
    }

    function createNewSession() {
      const suffix = Date.now().toString(36);
      sessionId.value = "web-" + suffix;
      rememberSession(effectiveSessionId(), {message_count: 0, preview: ""});
      showEmpty("Новая сессия создана. Задайте вопрос по WIICON или WIIC.");
      loadSessionList();
      input.focus();
    }

    input.addEventListener("keydown", (event) => {
      if (event.isComposing) return;
      if (event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) return;
      event.preventDefault();
      if (pending) return;
      form.requestSubmit();
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (pending) return;
      const message = input.value.trim();
      if (!message) return;
      const currentId = effectiveSessionId();
      rememberSession(currentId, {preview: message});
      appendMessage("user", "Вы", message);
      input.value = "";
      pending = true;
      sendButton.disabled = true;
      setStatus("выполняется");
      try {
        const payload = {
          session_id: currentId,
          message
        };
        const ref = payloadProductRef();
        if (ref !== undefined) payload.product_ref = ref;
        const response = await fetch("/chat", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok || !data.ok) {
          appendMessage("error", "Ошибка", data.error || "HTTP " + response.status, data);
          rememberSession(currentId, {preview: data.error || "Ошибка"});
        } else {
          appendMessage("assistant", data.result.source || "agent", data.result.message, data.result);
          rememberSession(currentId, {preview: data.result.message || message});
        }
      } catch (error) {
        appendMessage("error", "Ошибка", String(error && error.message ? error.message : error));
        rememberSession(currentId, {preview: String(error && error.message ? error.message : error)});
      } finally {
        pending = false;
        sendButton.disabled = false;
        setStatus("готов");
        loadSessionList();
        input.focus();
      }
    });

    newSessionButton.addEventListener("click", createNewSession);
    reloadHistoryButton.addEventListener("click", () => loadConversation());
    backendHistoryButton.addEventListener("click", () => showHistory("backend"));
    frontendHistoryButton.addEventListener("click", () => showHistory("frontend"));
    startOnboardingButton.addEventListener("click", () => startOnboarding());
    sessionId.addEventListener("change", () => loadConversation());
    sessionId.addEventListener("blur", () => {
      rememberSession(effectiveSessionId());
      loadSessionList();
    });
    window.addEventListener("focus", clearUnread);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) clearUnread();
    });

    loadVersion();
    loadOnboardingStatus();
    rememberSession(effectiveSessionId());
    loadSessionList();
    loadConversation();
  </script>
</body>
</html>
"""

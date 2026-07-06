from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Type
from urllib.parse import parse_qs, unquote, urlparse

from wiicon5.agent.orchestrator import AgentOrchestrator
from wiicon5.conversation.context import ResolvedEntity
from wiicon5.execution.artifacts import Artifact
from wiicon5.onboarding.status import OnboardingManager
from wiicon5.regression import load_cases, run_regression_replay, save_replay_result
from wiicon5.workbench.approval import ApprovalStore
from wiicon5.workbench.fingerprints import draft_hash, preview_fingerprint_payload
from wiicon5.workbench.lifecycle import SkillLifecycleService
from wiicon5.workbench.metadata_explorer import MetadataExplorerService
from wiicon5.workbench.models import HumanSkillDraft
from wiicon5.workbench.onboarding_candidates import OnboardingCandidateService
from wiicon5.workbench.preview import QueryPreviewService
from wiicon5.workbench.publish import APPROVAL_GATE_CODES, CandidatePublisher, latest_successful_smoke
from wiicon5.workbench.skill_catalog import SkillCatalogService
from wiicon5.workbench.smoke import McpSmokeTestService
from wiicon5.workbench.store import HumanSkillDraftStore
from wiicon5.workbench.synthesis_candidates import SynthesisCandidateStore
from wiicon5.workbench.trace import WorkbenchTraceWriter
from wiicon5.workbench.trace_import import TraceDraftImporter
from wiicon5.web.admin_security import AdminSecurityConfig


PROJECT_ROOT = Path(__file__).resolve().parents[3]
VERSION_FILE = PROJECT_ROOT / "VERSION"
DOCS_ROOT = PROJECT_ROOT / "docs"
BACKEND_HISTORY_FILE = PROJECT_ROOT / "docs" / "backend" / "history.txt"
FRONTEND_HISTORY_FILE = PROJECT_ROOT / "docs" / "frontend" / "history.txt"
STATIC_ROOT = Path(__file__).resolve().parent / "static"


def make_handler(
    agent: AgentOrchestrator,
    onboarding_manager: OnboardingManager | None = None,
    skill_catalog: SkillCatalogService | None = None,
    metadata_explorer: MetadataExplorerService | None = None,
    draft_store: HumanSkillDraftStore | None = None,
    trace_importer: TraceDraftImporter | None = None,
    preview_service: QueryPreviewService | None = None,
    smoke_service: McpSmokeTestService | None = None,
    approval_store: ApprovalStore | None = None,
    candidate_publisher: CandidatePublisher | None = None,
    admin_security: AdminSecurityConfig | None = None,
    onboarding_candidate_service: OnboardingCandidateService | None = None,
    synthesis_candidate_store: SynthesisCandidateStore | None = None,
    skill_lifecycle: SkillLifecycleService | None = None,
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
    effective_trace_importer = trace_importer or TraceDraftImporter(runs_root=PROJECT_ROOT / "runs")
    effective_preview_service = preview_service or QueryPreviewService(
        metadata_lookup=effective_metadata_explorer.metadata_object
    )
    effective_approval_store = approval_store or ApprovalStore(
        bot_instance_root=effective_onboarding_manager.bot_instance_root,
        bot_id=effective_onboarding_manager.bot_instance_root.name or "local",
        audit_log=effective_draft_store.audit,
    )
    effective_candidate_publisher = candidate_publisher or CandidatePublisher(
        bot_instance_root=effective_onboarding_manager.bot_instance_root,
        preview_service=effective_preview_service,
        approval_store=effective_approval_store,
    )
    effective_admin_security = admin_security or AdminSecurityConfig()
    effective_onboarding_candidate_service = onboarding_candidate_service or OnboardingCandidateService(
        bot_instance_root=effective_onboarding_manager.bot_instance_root,
        draft_store=effective_draft_store,
    )
    effective_synthesis_candidate_store = synthesis_candidate_store or SynthesisCandidateStore(
        bot_instance_root=effective_onboarding_manager.bot_instance_root,
        draft_store=effective_draft_store,
        audit_log=effective_draft_store.audit,
    )
    effective_workbench_trace = WorkbenchTraceWriter(
        bot_instance_root=effective_onboarding_manager.bot_instance_root
    )
    effective_skill_lifecycle = skill_lifecycle or SkillLifecycleService(
        bot_instance_root=effective_onboarding_manager.bot_instance_root,
        audit_log=effective_draft_store.audit,
    )

    class Wiicon5Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if self._reject_admin_if_needed(path):
                return
            if path == "/health":
                self._send_json(200, {"ok": True, "service": "wiicon5"})
                return
            if path == "/api/version":
                self._send_json(200, {"ok": True, "service": "wiicon5", "version": current_version()})
                return
            if path == "/api/ui/config":
                self._send_json(200, {"ok": True, "config": ui_config(effective_admin_security)})
                return
            if path == "/api/docs":
                self._send_json(200, {"ok": True, "docs": documentation_index()})
                return
            if path == "/api/docs/content":
                doc_path = first_query_value(query, "path")
                doc_file = documentation_file(doc_path)
                if doc_file is None:
                    self._send_json(404, {"ok": False, "error": "doc_not_found", "path": doc_path})
                    return
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "doc": documentation_item(doc_file),
                        "content": read_text_file(doc_file),
                    },
                )
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
            if path == "/api/admin/workbench/onboarding/candidates":
                limit = int_or_default(first_query_value(query, "limit"), 200)
                type_filter = first_query_value(query, "type")
                term = first_query_value(query, "q") or first_query_value(query, "term")
                candidates = effective_onboarding_candidate_service.list_candidates(
                    limit=limit,
                    type_filter=type_filter,
                    term=term,
                )
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "candidates": [item.to_dict() for item in candidates],
                        "summary": onboarding_candidate_summary(candidates),
                    },
                )
                return
            if path == "/api/admin/workbench/synthesis/candidates":
                limit = int_or_default(first_query_value(query, "limit"), 200)
                raw_status = first_query_value(query, "status")
                status = "" if raw_status == "all" else raw_status or "candidate"
                term = first_query_value(query, "q") or first_query_value(query, "term")
                candidates = effective_synthesis_candidate_store.list_candidates(
                    limit=limit,
                    status=status,
                    term=term,
                )
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "candidates": [item.to_dict() for item in candidates],
                        "summary": synthesis_candidate_summary(candidates),
                    },
                )
                return
            if path == "/api/admin/workbench/drafts":
                self._send_json(
                    200,
                    {"ok": True, "drafts": [draft.to_dict() for draft in effective_draft_store.list_drafts()]},
                )
                return
            if path.startswith("/api/admin/workbench/drafts/") and path.endswith("/approvals"):
                draft_id = unquote(path.split("/")[-2])
                draft = effective_draft_store.get_draft(draft_id)
                if draft is None:
                    self._send_json(404, {"ok": False, "error": "draft_not_found", "draft_id": draft_id})
                    return
                approvals = effective_approval_store.history_for_draft(draft_id)
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "draft_id": draft_id,
                        "approvals": [item.to_dict() for item in approvals],
                        "latest": approvals[-1].to_dict() if approvals else None,
                    },
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
            if path.startswith("/static/"):
                static_file = static_file_from_path(path)
                if static_file is None:
                    self._send_json(404, {"ok": False, "error": "static_not_found"})
                    return
                self._send_static_file(200, static_file)
                return
            if path in {"/", "/chat"}:
                self._send_static_file(200, STATIC_ROOT / "index.html")
                return
            self._send_json(404, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if self._reject_admin_if_needed(parsed.path):
                return
            if parsed.path == "/api/admin/onboarding/run":
                try:
                    payload = self._read_json()
                    config_dump = str(payload.get("config_dump") or "").strip()
                    if not config_dump:
                        self._send_json(400, {"ok": False, "error": "config_dump is required"})
                        return
                    config_dump_path = Path(config_dump).expanduser()
                    if not effective_admin_security.config_dump_allowed(config_dump_path):
                        self._audit_admin_denied(
                            path=parsed.path,
                            error="config_dump_not_allowed",
                            status_code=403,
                            payload={"config_dump": str(config_dump_path)},
                        )
                        self._send_json(
                            403,
                            {
                                "ok": False,
                                "error": "config_dump_not_allowed",
                                "message": "Configuration dump path is outside WIICON5_ADMIN_ALLOWED_CONFIG_ROOTS.",
                            },
                        )
                        return
                    status = effective_onboarding_manager.start(
                        config_dump=config_dump_path,
                        mcp_url=str(payload.get("mcp_url") or "").strip() or None,
                        background=True,
                    )
                    self._send_json(202, {"ok": True, "status": status.to_dict()})
                except Exception as exc:
                    self._send_json(500, {"ok": False, "error": str(exc)})
                return
            if parsed.path == "/api/admin/regression/run":
                self._run_regression_replay()
                return
            if parsed.path != "/chat":
                if parsed.path == "/api/admin/workbench/drafts/from-trace":
                    self._create_draft_from_trace()
                    return
                if parsed.path.startswith("/api/admin/workbench/onboarding/candidates/") and parsed.path.endswith("/create-draft"):
                    candidate_id = unquote(parsed.path.split("/")[-2])
                    self._create_draft_from_onboarding_candidate(candidate_id)
                    return
                if parsed.path.startswith("/api/admin/workbench/onboarding/candidates/") and parsed.path.endswith("/reject"):
                    candidate_id = unquote(parsed.path.split("/")[-2])
                    self._reject_onboarding_candidate(candidate_id)
                    return
                if parsed.path.startswith("/api/admin/workbench/synthesis/candidates/") and parsed.path.endswith("/create-draft"):
                    candidate_id = unquote(parsed.path.split("/")[-2])
                    self._create_draft_from_synthesis_candidate(candidate_id)
                    return
                if parsed.path.startswith("/api/admin/workbench/synthesis/candidates/") and parsed.path.endswith("/reject"):
                    candidate_id = unquote(parsed.path.split("/")[-2])
                    self._reject_synthesis_candidate(candidate_id)
                    return
                if parsed.path.startswith("/api/admin/workbench/synthesis/candidates/") and parsed.path.endswith("/ignore-similar"):
                    candidate_id = unquote(parsed.path.split("/")[-2])
                    self._ignore_similar_synthesis_candidate(candidate_id)
                    return
                if parsed.path.startswith("/api/admin/workbench/drafts/") and parsed.path.endswith("/preview"):
                    draft_id = unquote(parsed.path.split("/")[-2])
                    self._preview_draft(draft_id)
                    return
                if parsed.path.startswith("/api/admin/workbench/drafts/") and parsed.path.endswith("/smoke"):
                    draft_id = unquote(parsed.path.split("/")[-2])
                    self._smoke_draft(draft_id)
                    return
                if parsed.path.startswith("/api/admin/workbench/drafts/") and parsed.path.endswith("/approve"):
                    draft_id = unquote(parsed.path.split("/")[-2])
                    self._approve_draft(draft_id)
                    return
                if parsed.path.startswith("/api/admin/workbench/drafts/") and parsed.path.endswith("/reject"):
                    draft_id = unquote(parsed.path.split("/")[-2])
                    self._reject_draft(draft_id)
                    return
                if parsed.path.startswith("/api/admin/workbench/drafts/") and parsed.path.endswith("/publish-candidate"):
                    draft_id = unquote(parsed.path.split("/")[-2])
                    self._publish_candidate(draft_id)
                    return
                if parsed.path.startswith("/api/admin/skills/"):
                    self._change_skill_lifecycle(parsed.path)
                    return
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
            if self._reject_admin_if_needed(parsed.path):
                return
            if parsed.path.startswith("/api/admin/workbench/drafts/"):
                draft_id = unquote(parsed.path.rsplit("/", 1)[-1])
                self._update_draft(draft_id)
                return
            self._send_json(404, {"ok": False, "error": "not_found"})

        def do_PUT(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if self._reject_admin_if_needed(parsed.path):
                return
            if parsed.path.startswith("/api/admin/workbench/drafts/"):
                draft_id = unquote(parsed.path.rsplit("/", 1)[-1])
                self._update_draft(draft_id)
                return
            self._send_json(404, {"ok": False, "error": "not_found"})

        def do_DELETE(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if self._reject_admin_if_needed(parsed.path):
                return
            if parsed.path.startswith("/api/admin/workbench/drafts/"):
                draft_id = unquote(parsed.path.rsplit("/", 1)[-1])
                actor = first_query_value(parse_qs(parsed.query), "actor") or "admin"
                draft = effective_draft_store.get_draft(draft_id)
                if draft is None:
                    self._send_json(404, {"ok": False, "error": "draft_not_found", "draft_id": draft_id})
                    return
                trace = effective_workbench_trace.start(
                    action="draft.delete",
                    actor=actor,
                    object_type="human_skill_draft",
                    object_id=draft_id,
                    request={"query": dict(parse_qs(parsed.query))},
                )
                trace.write_json("draft_before", draft.to_dict())
                if not effective_draft_store.delete_draft(draft_id, actor=actor):
                    self._send_json(404, {"ok": False, "error": "draft_not_found", "draft_id": draft_id})
                    return
                trace.write_json("delete_result", {"ok": True, "draft_id": draft_id})
                self._send_json(200, {"ok": True, "draft_id": draft_id, "trace_path": str(trace.path)})
                return
            self._send_json(404, {"ok": False, "error": "not_found"})

        def _create_draft(self) -> None:
            try:
                payload = self._read_json()
                actor = str(payload.get("actor") or "admin")
                draft_payload = payload.get("draft") if isinstance(payload.get("draft"), dict) else payload
                if raw_query_edit_requested(draft_payload) and not effective_admin_security.allow_raw_query_edit:
                    self._send_json(403, {"ok": False, "error": "raw_query_edit_disabled"})
                    return
                trace = effective_workbench_trace.start(
                    action="draft.create",
                    actor=actor,
                    object_type="human_skill_draft",
                    request=payload,
                )
                draft = HumanSkillDraft.from_dict(draft_payload)
                created = effective_draft_store.create_draft(draft, actor=actor)
                trace.write_json("draft_after", created.to_dict())
                self._send_json(201, {"ok": True, "draft": created.to_dict(), "trace_path": str(trace.path)})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def _update_draft(self, draft_id: str) -> None:
            try:
                payload = self._read_json()
                actor = str(payload.get("actor") or "admin")
                changes = payload.get("draft") if isinstance(payload.get("draft"), dict) else dict(payload)
                changes.pop("actor", None)
                if raw_query_edit_requested(changes) and not effective_admin_security.allow_raw_query_edit:
                    self._send_json(403, {"ok": False, "error": "raw_query_edit_disabled"})
                    return
                before = effective_draft_store.require_draft(draft_id)
                trace = effective_workbench_trace.start(
                    action="draft.update",
                    actor=actor,
                    object_type="human_skill_draft",
                    object_id=draft_id,
                    request=payload,
                )
                trace.write_json("draft_before", before.to_dict())
                updated = effective_draft_store.update_draft(draft_id, changes, actor=actor)
                trace.write_json("draft_after", updated.to_dict())
                self._send_json(200, {"ok": True, "draft": updated.to_dict(), "trace_path": str(trace.path)})
            except KeyError:
                self._send_json(404, {"ok": False, "error": "draft_not_found", "draft_id": draft_id})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def _create_draft_from_trace(self) -> None:
            try:
                payload = self._read_json()
                actor = str(payload.get("actor") or "admin")
                trace_path = str(payload.get("trace_path") or "").strip()
                if not trace_path:
                    self._send_json(400, {"ok": False, "error": "trace_path is required"})
                    return
                draft = effective_trace_importer.draft_from_trace(Path(trace_path))
                created = effective_draft_store.create_draft(draft, actor=actor)
                self._send_json(201, {"ok": True, "draft": created.to_dict()})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def _create_draft_from_onboarding_candidate(self, candidate_id: str) -> None:
            try:
                payload = self._read_json()
                actor = str(payload.get("actor") or "admin")
                draft = effective_onboarding_candidate_service.create_draft(candidate_id, actor=actor)
                self._send_json(201, {"ok": True, "draft": draft.to_dict()})
            except KeyError:
                self._send_json(
                    404,
                    {"ok": False, "error": "onboarding_candidate_not_found", "candidate_id": candidate_id},
                )
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def _reject_onboarding_candidate(self, candidate_id: str) -> None:
            try:
                payload = self._read_json()
                actor = str(payload.get("actor") or "admin")
                record = effective_onboarding_candidate_service.reject_candidate(
                    candidate_id,
                    actor=actor,
                    comment=str(payload.get("comment") or ""),
                )
                self._send_json(200, {"ok": True, "rejection": record})
            except KeyError:
                self._send_json(
                    404,
                    {"ok": False, "error": "onboarding_candidate_not_found", "candidate_id": candidate_id},
                )
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def _create_draft_from_synthesis_candidate(self, candidate_id: str) -> None:
            try:
                payload = self._read_json()
                actor = str(payload.get("actor") or "admin")
                draft = effective_synthesis_candidate_store.create_draft(candidate_id, actor=actor)
                self._send_json(201, {"ok": True, "draft": draft.to_dict()})
            except KeyError:
                self._send_json(
                    404,
                    {"ok": False, "error": "synthesis_candidate_not_found", "candidate_id": candidate_id},
                )
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def _reject_synthesis_candidate(self, candidate_id: str) -> None:
            try:
                payload = self._read_json()
                actor = str(payload.get("actor") or "admin")
                candidate = effective_synthesis_candidate_store.reject_candidate(
                    candidate_id,
                    actor=actor,
                    comment=str(payload.get("comment") or ""),
                )
                self._send_json(200, {"ok": True, "candidate": candidate.to_dict()})
            except KeyError:
                self._send_json(
                    404,
                    {"ok": False, "error": "synthesis_candidate_not_found", "candidate_id": candidate_id},
                )
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def _ignore_similar_synthesis_candidate(self, candidate_id: str) -> None:
            try:
                payload = self._read_json()
                actor = str(payload.get("actor") or "admin")
                candidate = effective_synthesis_candidate_store.ignore_similar(
                    candidate_id,
                    actor=actor,
                    comment=str(payload.get("comment") or ""),
                )
                self._send_json(200, {"ok": True, "candidate": candidate.to_dict()})
            except KeyError:
                self._send_json(
                    404,
                    {"ok": False, "error": "synthesis_candidate_not_found", "candidate_id": candidate_id},
                )
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def _preview_draft(self, draft_id: str) -> None:
            try:
                payload = self._read_json()
                actor = str(payload.get("actor") or "admin")
                draft = effective_draft_store.require_draft(draft_id)
                trace = effective_workbench_trace.start(
                    action="draft.preview",
                    actor=actor,
                    object_type="human_skill_draft",
                    object_id=draft_id,
                    request=payload,
                )
                trace.write_json("draft_before", draft.to_dict())
                preview = effective_preview_service.preview(draft)
                trace.write_json("query_preview", preview.to_dict())
                effective_draft_store.audit.append(
                    event_type="workbench.query.previewed",
                    actor=actor,
                    object_type="human_skill_draft",
                    object_id=draft_id,
                    payload={
                        "ok": preview.ok,
                        "issue_codes": [issue.code for issue in preview.issues],
                        "query_present": bool(preview.query),
                        "trace_path": str(trace.path),
                    },
                )
                self._send_json(200, {"ok": True, "preview": preview.to_dict(), "trace_path": str(trace.path)})
            except KeyError:
                self._send_json(404, {"ok": False, "error": "draft_not_found", "draft_id": draft_id})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def _smoke_draft(self, draft_id: str) -> None:
            if smoke_service is None:
                self._send_json(503, {"ok": False, "error": "smoke_test_not_configured"})
                return
            try:
                payload = self._read_json()
                actor = str(payload.get("actor") or "admin")
                draft = effective_draft_store.require_draft(draft_id)
                trace = effective_workbench_trace.start(
                    action="draft.smoke",
                    actor=actor,
                    object_type="human_skill_draft",
                    object_id=draft_id,
                    request=payload,
                )
                trace.write_json("draft_before", draft.to_dict())
                effective_draft_store.audit.append(
                    event_type="workbench.smoke.started",
                    actor=actor,
                    object_type="human_skill_draft",
                    object_id=draft_id,
                    payload={"trace_path": str(trace.path)},
                )
                smoke_params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
                smoke = smoke_service.run(draft, params=smoke_params)
                trace.write_json("smoke_result", smoke.to_dict())
                effective_draft_store.audit.append(
                    event_type="workbench.smoke.completed",
                    actor=actor,
                    object_type="human_skill_draft",
                    object_id=draft_id,
                    payload={
                        "ok": smoke.ok,
                        "row_count": smoke.row_count,
                        "smoke_id": smoke.smoke_id,
                        "draft_hash": smoke.draft_hash,
                        "preview_hash": smoke.preview_hash,
                        "trace_path": str(trace.path),
                    },
                )
                self._send_json(200, {"ok": True, "smoke": smoke.to_dict(), "trace_path": str(trace.path)})
            except KeyError:
                self._send_json(404, {"ok": False, "error": "draft_not_found", "draft_id": draft_id})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def _approve_draft(self, draft_id: str) -> None:
            try:
                payload = self._read_json()
                actor = str(payload.get("actor") or "").strip()
                comment = str(payload.get("comment") or "").strip()
                requested_smoke_id = str(payload.get("smoke_id") or "").strip()
                if not actor:
                    self._send_json(400, {"ok": False, "error": "actor_required"})
                    return
                if not comment:
                    self._send_json(400, {"ok": False, "error": "approval_comment_required"})
                    return
                draft = effective_draft_store.require_draft(draft_id)
                preview = effective_preview_service.preview(draft)
                if not preview.ok:
                    self._send_json(400, {"ok": False, "error": "preview_failed", "preview": preview.to_dict()})
                    return
                fingerprints = preview_fingerprint_payload(preview)
                smoke = latest_successful_smoke(
                    effective_candidate_publisher.smoke_root / draft_id,
                    draft_hash=draft_hash(draft),
                    preview_hash=fingerprints["preview_hash"],
                )
                smoke_id = str((smoke or {}).get("smoke_id") or "")
                if smoke is None or (requested_smoke_id and smoke_id != requested_smoke_id):
                    self._send_json(400, {"ok": False, "error": "current_successful_smoke_required"})
                    return
                approval = effective_approval_store.approve(
                    draft_id,
                    actor=actor,
                    approval_level=str(payload.get("approval_level") or "candidate"),
                    comment=comment,
                    smoke_id=smoke_id,
                    draft_hash=draft_hash(draft),
                    preview_hash=fingerprints["preview_hash"],
                    query_hash=fingerprints["query_hash"],
                    regression_case_id=str(payload.get("regression_case_id") or ""),
                    evidence=payload.get("evidence") if isinstance(payload.get("evidence"), dict) else None,
                )
                self._send_json(200, {"ok": True, "approval": approval.to_dict()})
            except KeyError:
                self._send_json(404, {"ok": False, "error": "draft_not_found", "draft_id": draft_id})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def _reject_draft(self, draft_id: str) -> None:
            try:
                payload = self._read_json()
                actor = str(payload.get("actor") or "").strip()
                comment = str(payload.get("comment") or "").strip()
                if not actor:
                    self._send_json(400, {"ok": False, "error": "actor_required"})
                    return
                if not comment:
                    self._send_json(400, {"ok": False, "error": "approval_comment_required"})
                    return
                effective_draft_store.require_draft(draft_id)
                approval = effective_approval_store.reject(
                    draft_id,
                    actor=actor,
                    approval_level=str(payload.get("approval_level") or "candidate"),
                    comment=comment,
                    evidence=payload.get("evidence") if isinstance(payload.get("evidence"), dict) else None,
                )
                self._send_json(200, {"ok": True, "approval": approval.to_dict()})
            except KeyError:
                self._send_json(404, {"ok": False, "error": "draft_not_found", "draft_id": draft_id})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def _publish_candidate(self, draft_id: str) -> None:
            try:
                payload = self._read_json()
                actor = str(payload.get("actor") or "").strip()
                comment = str(payload.get("comment") or "").strip()
                requested_smoke_id = str(payload.get("smoke_id") or "").strip()
                if not actor:
                    self._send_json(400, {"ok": False, "error": "actor_required"})
                    return
                if payload.get("approve") is not True:
                    self._send_json(400, {"ok": False, "error": "publish_approval_required"})
                    return
                if not comment:
                    self._send_json(400, {"ok": False, "error": "approval_comment_required"})
                    return
                draft = effective_draft_store.require_draft(draft_id)
                trace = effective_workbench_trace.start(
                    action="draft.publish_candidate",
                    actor=actor,
                    object_type="human_skill_draft",
                    object_id=draft_id,
                    request=payload,
                )
                trace.write_json("draft_before", draft.to_dict())
                preflight = effective_candidate_publisher.validate(draft)
                trace.write_json("validation_result", preflight.to_dict())
                blocking_issues = [
                    issue for issue in preflight.issues if issue.code not in APPROVAL_GATE_CODES
                ]
                if blocking_issues:
                    trace.write_json("publish_result", preflight.to_dict())
                    self._send_json(
                        200,
                        {"ok": True, "publication": preflight.to_dict(), "trace_path": str(trace.path)},
                    )
                    return
                rejected = [issue for issue in preflight.issues if issue.code == "approval_rejected"]
                if rejected and payload.get("override_previous_rejection") is not True:
                    trace.write_json("publish_result", preflight.to_dict())
                    self._send_json(
                        409,
                        {
                            "ok": False,
                            "error": "previous_approval_rejected",
                            "publication": preflight.to_dict(),
                            "trace_path": str(trace.path),
                        },
                    )
                    return
                preview = preflight.preview or effective_preview_service.preview(draft)
                fingerprints = preview_fingerprint_payload(preview)
                smoke = preflight.smoke or latest_successful_smoke(
                    effective_candidate_publisher.smoke_root / draft_id,
                    draft_hash=draft_hash(draft),
                    preview_hash=fingerprints["preview_hash"],
                )
                smoke_id = str((smoke or {}).get("smoke_id") or "")
                if smoke is None or (requested_smoke_id and smoke_id != requested_smoke_id):
                    self._send_json(400, {"ok": False, "error": "current_successful_smoke_required"})
                    return
                effective_approval_store.approve(
                    draft_id,
                    actor=actor,
                    approval_level="candidate",
                    comment=comment,
                    smoke_id=smoke_id,
                    draft_hash=draft_hash(draft),
                    preview_hash=fingerprints["preview_hash"],
                    query_hash=fingerprints["query_hash"],
                    regression_case_id=str(payload.get("regression_case_id") or ""),
                    evidence=payload.get("evidence") if isinstance(payload.get("evidence"), dict) else None,
                )
                published = effective_candidate_publisher.publish(draft)
                trace.write_json("publish_result", published.to_dict())
                if published.ok:
                    effective_draft_store.audit.append(
                        event_type="workbench.skill.published_candidate",
                        actor=actor,
                        object_type="human_skill_draft",
                        object_id=draft_id,
                        payload={
                            "skill_id": published.skill.skill_id if published.skill else "",
                            "path": published.path,
                            "evidence_path": published.evidence_path,
                            "trace_path": str(trace.path),
                        },
                    )
                self._send_json(200, {"ok": True, "publication": published.to_dict(), "trace_path": str(trace.path)})
            except KeyError:
                self._send_json(404, {"ok": False, "error": "draft_not_found", "draft_id": draft_id})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def _run_regression_replay(self) -> None:
            try:
                payload = self._read_json()
                cases_value = str(payload.get("cases") or "").strip()
                cases_path = (
                    Path(cases_value).expanduser()
                    if cases_value
                    else effective_onboarding_manager.bot_instance_root / "regression"
                )
                if not effective_admin_security.config_dump_allowed(cases_path):
                    self._audit_admin_denied(
                        path="/api/admin/regression/run",
                        error="regression_cases_not_allowed",
                        status_code=403,
                        payload={"cases": str(cases_path)},
                    )
                    self._send_json(
                        403,
                        {
                            "ok": False,
                            "error": "regression_cases_not_allowed",
                            "message": "Regression cases path is outside WIICON5_ADMIN_ALLOWED_CONFIG_ROOTS.",
                        },
                    )
                    return
                cases = load_cases(cases_path)
                result = run_regression_replay(
                    cases,
                    agent,
                    session_prefix=str(payload.get("session_prefix") or "regression"),
                )
                result_path = save_replay_result(
                    result,
                    effective_onboarding_manager.bot_instance_root / "regression" / "results",
                )
                effective_draft_store.audit.append(
                    event_type="workbench.regression.replayed",
                    actor=str(payload.get("actor") or "admin"),
                    object_type="regression",
                    object_id=result.run_id,
                    payload={"ok": result.ok, "count": result.count, "path": str(result_path)},
                )
                self._send_json(200, {"ok": result.ok, "regression": result.to_dict(), "path": str(result_path)})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def _change_skill_lifecycle(self, path: str) -> None:
            parts = path.strip("/").split("/")
            if len(parts) != 5 or parts[:3] != ["api", "admin", "skills"]:
                self._send_json(404, {"ok": False, "error": "not_found"})
                return
            skill_id = unquote(parts[3])
            requested_action = parts[4]
            action = ""
            if requested_action == "promote":
                action = "promote"
            elif requested_action == "deprecate":
                action = "deprecate"
            elif requested_action == "block":
                action = "block"
            elif requested_action == "rollback":
                action = "rollback"
            else:
                self._send_json(404, {"ok": False, "error": "not_found"})
                return
            try:
                payload = self._read_json()
                actor = str(payload.get("actor") or "")
                reason = str(payload.get("reason") or payload.get("comment") or "")
                if action == "promote":
                    result = effective_skill_lifecycle.promote(
                        skill_id,
                        actor=actor,
                        reason=reason,
                        target_status=str(payload.get("target_status") or ""),
                        regression_case_ids=[
                            str(item)
                            for item in payload.get("regression_case_ids", [])
                            if str(item).strip()
                        ]
                        if isinstance(payload.get("regression_case_ids"), list)
                        else [],
                        successful_runs=int_or_default(payload.get("successful_runs"), 0),
                        admin_approval=bool(payload.get("admin_approval", False)),
                    )
                elif action == "deprecate":
                    result = effective_skill_lifecycle.deprecate(skill_id, actor=actor, reason=reason)
                elif action == "block":
                    result = effective_skill_lifecycle.block(skill_id, actor=actor, reason=reason)
                else:
                    result = effective_skill_lifecycle.rollback(
                        skill_id,
                        actor=actor,
                        reason=reason,
                        target_status=str(payload.get("target_status") or ""),
                        admin_approval=bool(payload.get("admin_approval", False)),
                    )
                status_code = 200 if result.ok else lifecycle_error_status(result)
                self._send_json(status_code, {"ok": result.ok, "lifecycle": result.to_dict()})
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

        def _send_static_file(self, status_code: int, path: Path) -> None:
            try:
                raw = path.read_bytes()
            except OSError:
                self._send_json(404, {"ok": False, "error": "static_not_found"})
                return
            content_type = static_content_type(path)
            self.send_response(status_code)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _reject_admin_if_needed(self, path: str) -> bool:
            result = effective_admin_security.authorize(
                path=path,
                headers=self.headers,
                client_host=str(self.client_address[0]) if self.client_address else "",
            )
            if result.ok:
                return False
            self._audit_admin_denied(path=path, error=result.error, status_code=result.status_code)
            self._send_json(
                result.status_code,
                {"ok": False, "error": result.error, "message": result.message},
            )
            return True

        def _audit_admin_denied(
            self,
            *,
            path: str,
            error: str,
            status_code: int,
            payload: Dict[str, Any] | None = None,
        ) -> None:
            try:
                effective_draft_store.audit.append(
                    event_type="workbench.admin.denied",
                    actor="http",
                    object_type="http_request",
                    object_id=path,
                    payload={
                        "error": error,
                        "status_code": status_code,
                        "client_host": str(self.client_address[0]) if self.client_address else "",
                        **(payload or {}),
                    },
                )
            except Exception:
                return None

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


def ui_config(admin_security: AdminSecurityConfig) -> Dict[str, Any]:
    return {
        "version": current_version(),
        "admin": {
            "enabled": admin_security.enabled,
            "token_required": bool(admin_security.token),
            "local_only": admin_security.bind_local_only,
            "raw_query_edit_allowed": admin_security.allow_raw_query_edit,
        },
        "bot": {"id": "local", "name": "WIICON ChatBot 5"},
    }


def static_file_from_path(path: str) -> Path | None:
    requested = unquote(path.removeprefix("/static/")).strip("/")
    if not requested:
        return None
    candidate = (STATIC_ROOT / requested).resolve()
    static_root = STATIC_ROOT.resolve()
    try:
        candidate.relative_to(static_root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def static_content_type(path: Path) -> str:
    if path.suffix == ".js":
        return "application/javascript; charset=utf-8"
    if path.suffix == ".css":
        return "text/css; charset=utf-8"
    if path.suffix in {".html", ".htm"}:
        return "text/html; charset=utf-8"
    guessed = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    if guessed.startswith("text/"):
        return f"{guessed}; charset=utf-8"
    return guessed


def documentation_index() -> list[Dict[str, str]]:
    if not DOCS_ROOT.exists():
        return []
    result: list[Dict[str, str]] = []
    for path in sorted(DOCS_ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        result.append(documentation_item(path))
    return result


def documentation_file(value: str) -> Path | None:
    requested = value.strip()
    if not requested:
        return None
    if requested.startswith("docs/"):
        requested = requested[len("docs/") :]
    candidate = (DOCS_ROOT / requested).resolve()
    docs_root = DOCS_ROOT.resolve()
    try:
        candidate.relative_to(docs_root)
    except ValueError:
        return None
    if not candidate.is_file() or candidate.suffix.lower() not in {".md", ".txt"}:
        return None
    return candidate


def documentation_item(path: Path) -> Dict[str, str]:
    relative = path.relative_to(PROJECT_ROOT)
    return {
        "path": str(relative),
        "title": documentation_title(path),
        "section": documentation_section(relative),
        "format": path.suffix.lower().lstrip("."),
    }


def documentation_title(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[:40]:
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip() or path.stem
    except OSError:
        pass
    return path.stem.replace("_", " ").replace("-", " ").strip().title()


def documentation_section(relative: Path) -> str:
    parts = relative.parts
    if len(parts) >= 3 and parts[1] == "workbench":
        return "Skill Workbench"
    if len(parts) >= 3 and parts[1] == "architecture":
        return "Архитектура"
    if len(parts) >= 3 and parts[1] == "backend":
        return "Backend"
    if len(parts) >= 3 and parts[1] == "frontend":
        return "Frontend"
    return "Проект"


def first_query_value(query: Dict[str, list[str]], name: str) -> str:
    values = query.get(name) or []
    return values[0].strip() if values else ""


def int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def lifecycle_error_status(result) -> int:
    codes = {issue.code for issue in result.issues}
    if "skill_not_found" in codes:
        return 404
    if "missing_actor" in codes or "missing_reason" in codes:
        return 400
    return 409


def raw_query_edit_requested(payload: Dict[str, Any]) -> bool:
    calculation = payload.get("calculation")
    if not isinstance(calculation, dict):
        return False
    kind = str(calculation.get("kind") or "").strip()
    raw = calculation.get("raw") if isinstance(calculation.get("raw"), dict) else {}
    if kind in {"trace_query", "raw_query"}:
        return True
    return bool(raw.get("query"))


def conversation_summary(context) -> Dict[str, Any]:
    latest = context.messages[-1] if context.messages else None
    preview = latest.content if latest else ""
    return {
        "session_id": context.session_id,
        "message_count": len(context.messages),
        "updated_at": latest.ts if latest else "",
        "preview": preview[:140],
    }


def onboarding_candidate_summary(candidates) -> Dict[str, Any]:
    by_type: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    for candidate in candidates:
        by_type[candidate.type] = by_type.get(candidate.type, 0) + 1
        by_status[candidate.status] = by_status.get(candidate.status, 0) + 1
    return {"total": len(candidates), "by_type": by_type, "by_status": by_status}


def synthesis_candidate_summary(candidates) -> Dict[str, Any]:
    by_status: Dict[str, int] = {}
    for candidate in candidates:
        by_status[candidate.status] = by_status.get(candidate.status, 0) + 1
    return {"total": len(candidates), "by_status": by_status}


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
    metadata_explorer: MetadataExplorerService | None = None,
    preview_service: QueryPreviewService | None = None,
    smoke_service: McpSmokeTestService | None = None,
    admin_security: AdminSecurityConfig | None = None,
) -> None:
    server = HTTPServer(
        (host, port),
        make_handler(
            agent,
            onboarding_manager=onboarding_manager,
            metadata_explorer=metadata_explorer,
            preview_service=preview_service,
            smoke_service=smoke_service,
            admin_security=admin_security,
        ),
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()

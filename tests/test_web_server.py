from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from wiicon5.agent.orchestrator import AgentOrchestrator
from wiicon5.intent.decomposer import DecompositionResult
from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.knowledge.metadata import MetadataObject, MetadataProvider
from wiicon5.mcp.client import DictMcpClient
from wiicon5.onboarding.status import OnboardingManager
from wiicon5.skills.registry import SkillRegistry
from wiicon5.testing.scripted_decomposer import ScriptedGoalDecomposer
from wiicon5.web.admin_security import AdminSecurityConfig
from wiicon5.web.server import make_handler, run_http_server
from wiicon5.workbench.metadata_explorer import MetadataExplorerService
from wiicon5.workbench.preview import QueryPreviewService
from wiicon5.workbench.smoke import McpSmokeTestService
from wiicon5.workbench.trace_import import TraceDraftImporter


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WebServerTests(unittest.TestCase):
    def assertStaticRequiredElementsExist(self, html: str, *scripts: str) -> None:
        ids = set(re.findall(r'id="([^"]+)"', html))
        required_ids = set()
        for script in scripts:
            required_ids.update(re.findall(r'requiredElement\("([^"]+)"\)', script))
        self.assertFalse(required_ids - ids, f"Missing required DOM ids: {sorted(required_ids - ids)}")

    def assertButtonBindings(self, html: str, script: str, button_ids: list[str]) -> None:
        ids = set(re.findall(r'id="([^"]+)"', html))
        for button_id in button_ids:
            self.assertIn(button_id, ids)
            self.assertIn(f'optionalBind("{button_id}"', script)

    @unittest.skipUnless(shutil.which("osascript"), "JavaScriptCore syntax check requires osascript")
    def test_static_javascript_syntax(self) -> None:
        script = """
ObjC.import('Foundation');
const files = ['api.js', 'renderers.js', 'workbench.js', 'app.js'];
for (const file of files) {
  const path = $.NSString.stringWithUTF8String('src/wiicon5/web/static/' + file);
  const text = $.NSString.stringWithContentsOfFileEncodingError(path, $.NSUTF8StringEncoding, null).js;
  new Function(text);
}
"""
        subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script],
            cwd=PROJECT_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )

    @unittest.skipUnless(shutil.which("osascript"), "JavaScriptCore renderer check requires osascript")
    def test_static_renderers_show_candidates_before_summary(self) -> None:
        script = """
ObjC.import('Foundation');
var window = {};
const path = $.NSString.stringWithUTF8String('src/wiicon5/web/static/renderers.js');
const text = $.NSString.stringWithContentsOfFileEncodingError(path, $.NSUTF8StringEncoding, null).js;
eval(text);
const html = window.WiiconRenderers.renderSummary({
  ok: true,
  candidates: [{
    candidate_id: 'syn_test',
    question: 'Покажи клиента с максимальной задолженностью',
    answer: 'Альтаир, задолженность 194889',
    row_count: 1,
    status: 'candidate',
    trace_path: '/tmp/trace',
    metadata_objects: [{ full_name: 'РегистрНакопления.РасчетыСКлиентамиПоДокументам' }]
  }],
  summary: { total: 1, by_status: { candidate: 1 } }
});
if (html.indexOf('Покажи клиента') < 0) {
  throw new Error('candidate question is missing: ' + html);
}
if (html.indexOf('Создать черновик') < 0) {
  throw new Error('candidate action is missing: ' + html);
}
if (html.indexOf('data-action="synthesis-create-draft"') < 0) {
  throw new Error('candidate action binding is missing: ' + html);
}
if (html.indexOf('data-action="open-trace"') < 0) {
  throw new Error('candidate trace action is missing: ' + html);
}
if (html.indexOf('total:') >= 0 && html.indexOf('Покажи клиента') > html.indexOf('total:')) {
  throw new Error('summary rendered before candidates: ' + html);
}
const linkedHtml = window.WiiconRenderers.renderSummary({
  ok: true,
  candidates: [{
    candidate_id: 'syn_linked',
    question: 'Покажи клиента',
    status: 'candidate',
    payload: { draft_id: 'draft_existing' }
  }],
  summary: { total: 1 }
});
if (linkedHtml.indexOf('Открыть черновик') < 0 || linkedHtml.indexOf('draft_existing') < 0) {
  throw new Error('linked draft action is missing: ' + linkedHtml);
}
const draftHtml = window.WiiconRenderers.renderSummary({
  ok: true,
  notice: 'Черновик draft_existing найден. Следующий шаг: открыть черновик.',
  draft: {
    draft_id: 'draft_existing',
    title: 'Черновик',
    status: 'draft',
    description: 'Проверяет клиента с максимальной задолженностью',
    source_kind: 'query_synthesis_candidate',
    example_questions: ['Покажи клиента с максимальной задолженностью'],
    data_sources: [{ alias: 'Расчеты', object_name: 'РегистрНакопления.РасчетыСКлиентами', trust: 'hint' }],
    calculation: { kind: 'trace_query', raw: { query: 'ВЫБРАТЬ 1 ИЗ Справочник.Контрагенты', limit: 1 } },
    synthesis_candidate: {
      candidate_id: 'syn_linked',
      question: 'Покажи клиента',
      answer: 'Клиент найден',
      row_count: 1,
      metadata_objects: [{ full_name: 'Справочник.Контрагенты' }]
    }
  }
});
if (draftHtml.indexOf('Следующий шаг') < 0 || draftHtml.indexOf('draft_existing') < 0) {
  throw new Error('draft notice is missing: ' + draftHtml);
}
if (draftHtml.indexOf('Запрос 1С') < 0 || draftHtml.indexOf('Утвердить проверку') < 0 || draftHtml.indexOf('Опубликовать как кандидат') < 0) {
  throw new Error('draft decision details are missing: ' + draftHtml);
}
if (draftHtml.indexOf('draft-comment-input') < 0 || draftHtml.indexOf('draft-smoke-params-input') < 0 || draftHtml.indexOf('draft-action-result-local') < 0 || draftHtml.indexOf('draft-action-feedback') < 0) {
  throw new Error('draft local action inputs are missing: ' + draftHtml);
}
if (draftHtml.indexOf('data-action="draft-delete"') < 0) {
  throw new Error('draft delete action is missing: ' + draftHtml);
}
const draftListHtml = window.WiiconRenderers.renderSummary({
  ok: true,
  notice: 'Черновик draft_existing удален.',
  drafts: []
});
if (draftListHtml.indexOf('draft_existing удален') < 0) {
  throw new Error('draft list notice is missing: ' + draftListHtml);
}
const previewAndDraftHtml = window.WiiconRenderers.renderSummary({
  ok: true,
  notice: 'Предпросмотр построен.',
  draft: {
    draft_id: 'draft_existing',
    title: 'Черновик',
    status: 'draft',
    calculation: { kind: 'trace_query', raw: { query: 'ВЫБРАТЬ 1', limit: 1 } }
  },
  preview: { ok: true, query: 'ВЫБРАТЬ 1', params: { Период: '2026-01-01' }, limit: 1, issues: [], safety: { ok: true } }
});
if (previewAndDraftHtml.indexOf('Результат предпросмотра') < 0 || previewAndDraftHtml.indexOf('Черновик навыка') < 0 || previewAndDraftHtml.indexOf('draft-comment-input') < 0) {
  throw new Error('preview replaced draft card: ' + previewAndDraftHtml);
}
const approvalAndDraftHtml = window.WiiconRenderers.renderSummary({
  ok: true,
  draft: { draft_id: 'draft_existing', title: 'Черновик', status: 'draft' },
  approval: { approval_id: 'appr_1', decision: 'approved', comment: 'Проверено', smoke_id: 'smoke_1' }
});
if (approvalAndDraftHtml.indexOf('Результат утверждения') < 0 || approvalAndDraftHtml.indexOf('appr_1') < 0 || approvalAndDraftHtml.indexOf('Черновик навыка') < 0) {
  throw new Error('approval result is not visible with draft card: ' + approvalAndDraftHtml);
}
const blockedPublishHtml = window.WiiconRenderers.renderSummary({
  ok: true,
  publication: { ok: false, issues: [{ code: 'missing_successful_smoke' }, { code: 'missing_human_approval' }] }
});
if (blockedPublishHtml.indexOf('Публикация пока не выполнена') < 0 || blockedPublishHtml.indexOf('Сначала выполните успешный проверочный запуск') < 0 || blockedPublishHtml.indexOf('утвердите черновик человеком') < 0) {
  throw new Error('publish blockers are not visible in Russian: ' + blockedPublishHtml);
}
"""
        subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script],
            cwd=PROJECT_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )

    @unittest.skipUnless(shutil.which("osascript"), "JavaScriptCore renderer check requires osascript")
    def test_static_renderers_show_skill_contract_details(self) -> None:
        script = """
ObjC.import('Foundation');
var window = {};
const path = $.NSString.stringWithUTF8String('src/wiicon5/web/static/renderers.js');
const text = $.NSString.stringWithContentsOfFileEncodingError(path, $.NSUTF8StringEncoding, null).js;
eval(text);
const html = window.WiiconRenderers.renderSummary({
  ok: true,
  skill: {
    skill_id: 'render_entity_list_answer',
    kind: 'presentation',
    status: 'stable',
    description: 'Render a typed entity reference list into a user-facing answer without changing facts.',
    capabilities: ['render_answer', 'produce:UserAnswer'],
    inputs: [{ name: 'items', type: 'EntityRefList', required: true, description: 'Typed entity reference list' }],
    outputs: [{ name: 'answer', type: 'UserAnswer', required: true, description: 'Final user answer' }],
    tags: ['presentation'],
    supported_filter_roles: [],
    implementation_strategy: 'deterministic_entity_list_renderer',
    source_path: '/tmp/render_entity_list_answer.json'
  }
});
for (const expected of ['Что делает', 'Когда выбирается', 'Что принимает', 'Что возвращает', 'EntityRefList', 'UserAnswer', 'рендер списка объектов']) {
  if (html.indexOf(expected) < 0) {
    throw new Error('skill detail is missing ' + expected + ': ' + html);
  }
}
if (html.indexOf('СРЕДА ВЫПОЛНЕНИЯ') >= 0) {
  throw new Error('old technical-only skill card leaked into renderer: ' + html);
}
"""
        subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script],
            cwd=PROJECT_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )

    def test_run_http_server_accepts_cli_workbench_dependencies(self) -> None:
        question = "Привет"
        agent = AgentOrchestrator(
            registry=SkillRegistry.load_from_dir(PROJECT_ROOT / "skills"),
            decomposer=ScriptedGoalDecomposer(
                {
                    question: DecompositionResult(
                        intent=IntentResult(
                            intent_type=IntentType.OUT_OF_SCOPE,
                            business_goal=question,
                            requires_1c_data=False,
                            relevant=False,
                        )
                    )
                }
            ),
        )

        class StopServer(Exception):
            pass

        class FakeHTTPServer:
            def __init__(self, address, handler) -> None:
                self.address = address
                self.handler = handler
                self.closed = False

            def serve_forever(self) -> None:
                raise StopServer()

            def server_close(self) -> None:
                self.closed = True

        with TemporaryDirectory() as temp_dir:
            onboarding_manager = OnboardingManager(bot_instance_root=Path(temp_dir) / "bot")
            metadata_explorer = MetadataExplorerService()
            preview_service = QueryPreviewService(metadata_lookup=metadata_explorer.metadata_object)
            smoke_service = McpSmokeTestService(
                bot_instance_root=onboarding_manager.bot_instance_root,
                mcp_client=DictMcpClient({"success": True, "data": []}),
                preview_service=preview_service,
            )
            with patch("wiicon5.web.server.HTTPServer", FakeHTTPServer):
                with self.assertRaises(StopServer):
                    run_http_server(
                        agent,
                        host="127.0.0.1",
                        port=0,
                        onboarding_manager=onboarding_manager,
                        metadata_explorer=metadata_explorer,
                        preview_service=preview_service,
                        smoke_service=smoke_service,
                    )

    def test_admin_token_config_and_authorization(self) -> None:
        agent = AgentOrchestrator(
            registry=SkillRegistry.load_from_dir(PROJECT_ROOT / "skills"),
            decomposer=ScriptedGoalDecomposer({}),
        )
        with TemporaryDirectory() as temp_dir:
            onboarding_manager = OnboardingManager(bot_instance_root=Path(temp_dir) / "bot")
            server = HTTPServer(
                ("127.0.0.1", 0),
                make_handler(
                    agent,
                    onboarding_manager=onboarding_manager,
                    admin_security=AdminSecurityConfig(token="secret-token"),
                ),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                ui_config = json.loads(
                    urllib.request.urlopen(f"http://{host}:{port}/api/ui/config", timeout=5).read().decode("utf-8")
                )
                try:
                    urllib.request.urlopen(f"http://{host}:{port}/api/admin/onboarding/status", timeout=5).read()
                    denied_status = 200
                except urllib.error.HTTPError as exc:
                    denied_status = exc.code
                    denied_body = json.loads(exc.read().decode("utf-8"))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/admin/onboarding/status",
                    headers={"X-WIICON5-Admin-Token": "secret-token"},
                )
                allowed = json.loads(urllib.request.urlopen(request, timeout=5).read().decode("utf-8"))
                static_api = (
                    urllib.request.urlopen(f"http://{host}:{port}/static/api.js", timeout=5).read().decode("utf-8")
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertTrue(ui_config["ok"])
        self.assertTrue(ui_config["config"]["admin"]["token_required"])
        self.assertEqual(denied_status, 401)
        self.assertEqual(denied_body["error"], "admin_token_required")
        self.assertTrue(allowed["ok"])
        self.assertIn("function adminHeaders", static_api)
        self.assertIn("X-WIICON5-Admin-Token", static_api)

    def test_health_and_chat_return_json(self) -> None:
        question = "Привет"
        agent = AgentOrchestrator(
            registry=SkillRegistry.load_from_dir(PROJECT_ROOT / "skills"),
            decomposer=ScriptedGoalDecomposer(
                {
                    question: DecompositionResult(
                        intent=IntentResult(
                            intent_type=IntentType.OUT_OF_SCOPE,
                            business_goal=question,
                            requires_1c_data=False,
                            relevant=False,
                        )
                    )
                }
            ),
        )
        with TemporaryDirectory() as temp_dir:
            onboarding_manager = OnboardingManager(bot_instance_root=Path(temp_dir) / "bot")
            runs_root = Path(temp_dir) / "runs"
            write_trace(runs_root / "agent_001")
            write_onboarding_candidate(onboarding_manager.bot_instance_root)
            write_synthesis_candidates(onboarding_manager.bot_instance_root)
            write_regression_case(onboarding_manager.bot_instance_root)
            metadata_explorer = MetadataExplorerService(
                provider=StaticMetadataProvider(
                    [
                        MetadataObject(
                            full_name="Справочник.Склады",
                            synonym="Склады",
                            fields=["Ссылка"],
                            field_details={"Ссылка": {"name": "Ссылка", "_source": "mcp", "_trust": "verified"}},
                            raw={"_source": "mcp", "_trust": "verified", "kind": "Справочник"},
                        ),
                        MetadataObject(
                            full_name="РегистрНакопления.ТоварыНаСкладах",
                            synonym="Товары на складах",
                            fields=["Номенклатура", "ВНаличии"],
                            field_details={
                                "Номенклатура": {
                                    "name": "Номенклатура",
                                    "_category": "dimension",
                                    "_source": "metadata_xml",
                                    "_trust": "verified",
                                },
                                "ВНаличии": {
                                    "name": "ВНаличии",
                                    "_category": "resource",
                                    "_source": "metadata_xml",
                                    "_trust": "verified",
                                },
                            },
                            raw={"_source": "metadata_xml", "_trust": "verified", "kind": "РегистрНакопления"},
                        ),
                    ]
                )
            )
            preview_service = QueryPreviewService(metadata_lookup=metadata_explorer.metadata_object)
            server = HTTPServer(
                ("127.0.0.1", 0),
                make_handler(
                    agent,
                    onboarding_manager=onboarding_manager,
                    metadata_explorer=metadata_explorer,
                    trace_importer=TraceDraftImporter(runs_root=runs_root),
                    preview_service=preview_service,
                    smoke_service=McpSmokeTestService(
                        bot_instance_root=onboarding_manager.bot_instance_root,
                        mcp_client=DictMcpClient(
                            {"success": True, "data": [{"Номенклатура": "Телевизор", "Количество": 10}]}
                        ),
                        preview_service=preview_service,
                    ),
                ),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                health = json.loads(urllib.request.urlopen(f"http://{host}:{port}/health", timeout=5).read().decode("utf-8"))
                version = json.loads(
                    urllib.request.urlopen(f"http://{host}:{port}/api/version", timeout=5).read().decode("utf-8")
                )
                ui_config = json.loads(
                    urllib.request.urlopen(f"http://{host}:{port}/api/ui/config", timeout=5).read().decode("utf-8")
                )
                onboarding_status = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/admin/onboarding/status",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                onboarding_candidates = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/admin/workbench/onboarding/candidates",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                synthesis_candidates = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/admin/workbench/synthesis/candidates",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                synthesis_candidates_all = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/admin/workbench/synthesis/candidates?status=all",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                synthesis_candidate_id = synthesis_candidates["candidates"][0]["candidate_id"]
                reject_synthesis_request = urllib.request.Request(
                    f"http://{host}:{port}/api/admin/workbench/synthesis/candidates/{synthesis_candidate_id}/reject",
                    data=json.dumps(
                        {"actor": "candidate-admin", "comment": "Неверный бизнес-смысл"},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                rejected_synthesis_candidate = json.loads(
                    urllib.request.urlopen(reject_synthesis_request, timeout=5).read().decode("utf-8")
                )
                synthesis_candidates_after_reject = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/admin/workbench/synthesis/candidates",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                onboarding_candidate_id = onboarding_candidates["candidates"][0]["candidate_id"]
                create_candidate_draft_request = urllib.request.Request(
                    f"http://{host}:{port}/api/admin/workbench/onboarding/candidates/{onboarding_candidate_id}/create-draft",
                    data=json.dumps({"actor": "candidate-admin"}, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                candidate_draft = json.loads(
                    urllib.request.urlopen(create_candidate_draft_request, timeout=5).read().decode("utf-8")
                )
                reject_candidate_request = urllib.request.Request(
                    f"http://{host}:{port}/api/admin/workbench/onboarding/candidates/{onboarding_candidate_id}/reject",
                    data=json.dumps(
                        {"actor": "candidate-admin", "comment": "Проверим позже"},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                rejected_candidate = json.loads(
                    urllib.request.urlopen(reject_candidate_request, timeout=5).read().decode("utf-8")
                )
                chat_page_response = urllib.request.urlopen(f"http://{host}:{port}/chat", timeout=5)
                chat_page = chat_page_response.read().decode("utf-8")
                static_css_response = urllib.request.urlopen(f"http://{host}:{port}/static/styles.css", timeout=5)
                static_css = static_css_response.read().decode("utf-8")
                static_app = urllib.request.urlopen(f"http://{host}:{port}/static/app.js", timeout=5).read().decode("utf-8")
                static_api = urllib.request.urlopen(f"http://{host}:{port}/static/api.js", timeout=5).read().decode("utf-8")
                static_workbench = (
                    urllib.request.urlopen(f"http://{host}:{port}/static/workbench.js", timeout=5).read().decode("utf-8")
                )
                static_renderers = (
                    urllib.request.urlopen(f"http://{host}:{port}/static/renderers.js", timeout=5).read().decode("utf-8")
                )
                request = urllib.request.Request(
                    f"http://{host}:{port}/chat",
                    data=json.dumps({"message": question, "session_id": "s1"}, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                chat = json.loads(urllib.request.urlopen(request, timeout=5).read().decode("utf-8"))
                conversation = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/conversation?session_id=s1",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                conversations = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/conversations",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                skill_catalog = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/admin/skills/catalog",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                docs_index = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/docs",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                docs_content = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/docs/content?path=docs/workbench/user_guide.md",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                try:
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/docs/content?path=../VERSION",
                        timeout=5,
                    ).read()
                    docs_traversal_status = 200
                except urllib.error.HTTPError as exc:
                    docs_traversal_status = exc.code
                stock_skill = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/admin/skills/catalog/get_stock_balances",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                metadata_search = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/admin/metadata/search?q=%D1%81%D0%BA%D0%BB%D0%B0%D0%B4",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                metadata_object = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/admin/metadata/object?full_name=%D0%A1%D0%BF%D1%80%D0%B0%D0%B2%D0%BE%D1%87%D0%BD%D0%B8%D0%BA.%D0%A1%D0%BA%D0%BB%D0%B0%D0%B4%D1%8B",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                create_draft_request = urllib.request.Request(
                    f"http://{host}:{port}/api/admin/workbench/drafts",
                    data=json.dumps(
                        {
                            "actor": "tester",
                            "draft": {
                                "title": "Остатки по складу",
                                "example_questions": ["Покажи остатки по Центральному складу"],
                                "data_sources": [
                                    {
                                        "alias": "Остатки",
                                        "object_name": "РегистрНакопления.ТоварыНаСкладах.Остатки",
                                        "trust": "verified",
                                    }
                                ],
                                "field_mappings": [
                                    {
                                        "role": "product",
                                        "source_alias": "Остатки",
                                        "field_name": "Номенклатура",
                                        "confirmed": True,
                                    },
                                    {
                                        "role": "quantity",
                                        "source_alias": "Остатки",
                                        "field_name": "ВНаличииОстаток",
                                        "confirmed": True,
                                    },
                                ],
                                "calculation": {
                                    "kind": "top_n_by_metric",
                                    "source_alias": "Остатки",
                                    "group_by": ["product"],
                                    "measures": [
                                        {
                                            "role": "stock_balance",
                                            "expression": "quantity",
                                            "aggregate": "sum",
                                            "label": "Количество",
                                        }
                                    ],
                                    "sort": [{"field": "Количество", "direction": "desc"}],
                                    "limit": 5,
                                },
                            },
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                created_draft = json.loads(urllib.request.urlopen(create_draft_request, timeout=5).read().decode("utf-8"))
                draft_id = created_draft["draft"]["draft_id"]
                drafts = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/admin/workbench/drafts",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                update_draft_request = urllib.request.Request(
                    f"http://{host}:{port}/api/admin/workbench/drafts/{draft_id}",
                    data=json.dumps(
                        {"actor": "editor", "description": "Описание от консультанта"},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="PATCH",
                )
                updated_draft = json.loads(urllib.request.urlopen(update_draft_request, timeout=5).read().decode("utf-8"))
                draft_audit = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/admin/workbench/audit?object_id={draft_id}",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                preview_draft_request = urllib.request.Request(
                    f"http://{host}:{port}/api/admin/workbench/drafts/{draft_id}/preview",
                    data=json.dumps({"actor": "previewer"}, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                preview_draft = json.loads(urllib.request.urlopen(preview_draft_request, timeout=5).read().decode("utf-8"))
                smoke_draft_request = urllib.request.Request(
                    f"http://{host}:{port}/api/admin/workbench/drafts/{draft_id}/smoke",
                    data=json.dumps({"actor": "smoke-runner"}, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                smoke_draft = json.loads(urllib.request.urlopen(smoke_draft_request, timeout=5).read().decode("utf-8"))
                approve_draft_request = urllib.request.Request(
                    f"http://{host}:{port}/api/admin/workbench/drafts/{draft_id}/approve",
                    data=json.dumps(
                        {
                            "actor": "approver",
                            "comment": "Smoke sample reviewed",
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                approved_draft = json.loads(urllib.request.urlopen(approve_draft_request, timeout=5).read().decode("utf-8"))
                draft_approvals = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/admin/workbench/drafts/{draft_id}/approvals",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                publish_candidate_request = urllib.request.Request(
                    f"http://{host}:{port}/api/admin/workbench/drafts/{draft_id}/publish-candidate",
                    data=json.dumps(
                        {
                            "actor": "publisher",
                            "approve": True,
                            "comment": "Publication sample reviewed",
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                published_candidate = json.loads(
                    urllib.request.urlopen(publish_candidate_request, timeout=5).read().decode("utf-8")
                )
                regression_run_request = urllib.request.Request(
                    f"http://{host}:{port}/api/admin/regression/run",
                    data=json.dumps({"actor": "regression-runner"}, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                regression_run = json.loads(
                    urllib.request.urlopen(regression_run_request, timeout=5).read().decode("utf-8")
                )
                published_skill_id = published_candidate["publication"]["skill"]["skill_id"]
                promote_skill_request = urllib.request.Request(
                    f"http://{host}:{port}/api/admin/skills/{published_skill_id}/promote",
                    data=json.dumps(
                        {
                            "actor": "promoter",
                            "reason": "Smoke sample reviewed and regression case attached.",
                            "regression_case_ids": ["reg_web_stock_top"],
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                promoted_skill = json.loads(
                    urllib.request.urlopen(promote_skill_request, timeout=5).read().decode("utf-8")
                )
                draft_approvals_after_publish = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/admin/workbench/drafts/{draft_id}/approvals",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                delete_draft_request = urllib.request.Request(
                    f"http://{host}:{port}/api/admin/workbench/drafts/{draft_id}?actor=deleter",
                    method="DELETE",
                )
                deleted_draft = json.loads(urllib.request.urlopen(delete_draft_request, timeout=5).read().decode("utf-8"))
                import_trace_request = urllib.request.Request(
                    f"http://{host}:{port}/api/admin/workbench/drafts/from-trace",
                    data=json.dumps(
                        {"actor": "trace-admin", "trace_path": "agent_001"},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                imported_draft = json.loads(urllib.request.urlopen(import_trace_request, timeout=5).read().decode("utf-8"))
                created_trace_file_exists = (Path(created_draft["trace_path"]) / "draft_after.json").exists()
                updated_trace_file_exists = (Path(updated_draft["trace_path"]) / "draft_before.json").exists()
                preview_trace_file_exists = (Path(preview_draft["trace_path"]) / "query_preview.json").exists()
                smoke_trace_file_exists = (Path(smoke_draft["trace_path"]) / "smoke_result.json").exists()
                publish_trace_file_exists = (Path(published_candidate["trace_path"]) / "publish_result.json").exists()
                backend_history = urllib.request.urlopen(f"http://{host}:{port}/history/backend", timeout=5).read().decode("utf-8")
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertTrue(health["ok"])
        self.assertEqual(version["version"], (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip())
        self.assertTrue(ui_config["ok"])
        self.assertEqual(ui_config["config"]["version"], version["version"])
        self.assertFalse(ui_config["config"]["admin"]["token_required"])
        self.assertIn("text/html", chat_page_response.headers["Content-Type"])
        self.assertIn("text/css", static_css_response.headers["Content-Type"])
        self.assertIn("WIICON ChatBot 5", chat_page)
        self.assertIn("/static/app.js", chat_page)
        self.assertIn("/static/api.js", chat_page)
        self.assertIn("/static/workbench.js", chat_page)
        self.assertIn("app.js?v=5.0.0-alpha.70", chat_page)
        self.assertIn("workbench.js?v=5.0.0-alpha.70", chat_page)
        self.assertIn("renderers.js?v=5.0.0-alpha.70", chat_page)
        self.assertIn("styles.css?v=5.0.0-alpha.70", chat_page)
        self.assertIn("/static/renderers.js", chat_page)
        self.assertIn("topNav", chat_page)
        self.assertIn("view-chat", chat_page)
        self.assertIn("view-workbench", chat_page)
        self.assertIn("view-metadata", chat_page)
        self.assertIn("view-docs", chat_page)
        self.assertIn("view-admin", chat_page)
        self.assertIn("chatForm", chat_page)
        self.assertIn("appVersion", chat_page)
        self.assertIn("sessionList", chat_page)
        self.assertIn("newSessionButton", chat_page)
        self.assertIn("settingsDetails", chat_page)
        self.assertIn("reloadHistoryButton", chat_page)
        self.assertIn("trainingBanner", chat_page)
        self.assertIn("documentationPanel", chat_page)
        self.assertIn("docsSelect", chat_page)
        self.assertIn("docsOpenButton", chat_page)
        self.assertIn("startOnboardingButton", chat_page)
        self.assertIn("adminTokenInput", chat_page)
        self.assertIn("workbench-layout", chat_page)
        self.assertIn("Проверка и утверждение", chat_page)
        self.assertIn("Дополнительные действия", chat_page)
        self.assertIn("skillCatalogButton", chat_page)
        self.assertIn("draftListButton", chat_page)
        self.assertIn("onboardingCandidatesButton", chat_page)
        self.assertIn("synthesisCandidatesButton", chat_page)
        self.assertIn("metadataSearchInput", chat_page)
        self.assertIn("createDraftButton", chat_page)
        self.assertIn("previewDraftButton", chat_page)
        self.assertIn("smokeDraftButton", chat_page)
        self.assertIn("approvalCommentInput", chat_page)
        self.assertIn("candidateIdInput", chat_page)
        self.assertIn("candidateCreateDraftButton", chat_page)
        self.assertIn("candidateRejectButton", chat_page)
        self.assertIn("synthesisCandidateIdInput", chat_page)
        self.assertIn("synthesisCreateDraftButton", chat_page)
        self.assertIn("synthesisRejectButton", chat_page)
        self.assertIn("synthesisIgnoreSimilarButton", chat_page)
        self.assertIn("workbenchSummary", chat_page)
        self.assertIn("metadataObjectInput", chat_page)
        self.assertIn("metadataObjectButton", chat_page)
        self.assertIn("draftDetailsButton", chat_page)
        self.assertIn("draftExampleQuestionInput", chat_page)
        self.assertIn("draftSourceObjectInput", chat_page)
        self.assertIn("draftGroupFieldInput", chat_page)
        self.assertIn("draftMeasureFieldInput", chat_page)
        self.assertIn("draftFieldsConfirmedInput", chat_page)
        self.assertIn("field-picker", static_app)
        self.assertIn("Использовать как источник", static_app)
        self.assertIn("skillLifecycleIdInput", chat_page)
        self.assertIn("skillDetailsButton", chat_page)
        self.assertIn("skillRegressionCasesInput", chat_page)
        self.assertIn("skillPromoteButton", chat_page)
        self.assertIn("skillRollbackButton", chat_page)
        self.assertIn("skillDeprecateButton", chat_page)
        self.assertIn("skillBlockButton", chat_page)
        self.assertIn("runRegressionButton", chat_page)
        self.assertIn("regressionCasesPathInput", chat_page)
        self.assertIn("publishDraftButton", chat_page)
        self.assertIn(".workbench-layout", static_css)
        self.assertIn("ADMIN_TOKEN_STORAGE_KEY", static_api)
        self.assertIn("function adminHeaders", static_api)
        self.assertIn("function fetchAdmin", static_api)
        self.assertIn("X-WIICON5-Admin-Token", static_api)
        self.assertIn("requiredElement", static_app)
        self.assertIn("optionalBind", static_app)
        self.assertIn("showFatalUiError", static_app)
        self.assertIn("window.addEventListener(\"error\"", static_app)
        self.assertIn("window.addEventListener(\"unhandledrejection\"", static_app)
        self.assertIn("withButtonState", static_app)
        self.assertIn("runAction", static_app)
        self.assertIn("runWorkbenchAction", static_app)
        self.assertIn('messageInput").addEventListener("keydown"', static_app)
        self.assertIn("requestSubmit()", static_app)
        self.assertIn("startTitleBlink", static_app)
        self.assertIn("Новое сообщение", static_app)
        self.assertIn("loadDocumentationIndex", static_app)
        self.assertIn("openSelectedDocumentation", static_app)
        self.assertIn("renderMarkdownContent", static_renderers)
        self.assertIn("renderSkillCard", static_renderers)
        self.assertIn("renderDraftCard", static_renderers)
        self.assertIn("renderMetadataObjectCard", static_renderers)
        self.assertIn("renderCandidateCard", static_renderers)
        self.assertIn("renderCandidatesResponse", static_renderers)
        self.assertIn("renderJsonDetails", static_renderers)
        self.assertIn("loadSkillCatalog", static_workbench)
        self.assertIn("loadOnboardingCandidates", static_workbench)
        self.assertIn("loadSynthesisCandidates", static_workbench)
        self.assertIn("postDraftAction", static_workbench)
        self.assertIn("postCandidateAction", static_workbench)
        self.assertIn("postCandidateActionById", static_workbench)
        self.assertIn("postSynthesisCandidateAction", static_workbench)
        self.assertIn("postSynthesisCandidateActionById", static_workbench)
        self.assertIn("/api/admin/workbench/synthesis/candidates?status=candidate", static_workbench)
        self.assertIn("postSkillLifecycleAction", static_workbench)
        self.assertIn("postSkillLifecycleActionById", static_workbench)
        self.assertIn("runRegressionReplay", static_workbench)
        self.assertIn("renderWorkbenchSummary", static_workbench)
        self.assertIn("showTracePath", static_workbench)
        self.assertIn("buildTopMetricDraftFromForm", static_workbench)
        self.assertIn("handleWorkbenchActionClick", static_app)
        self.assertIn('document.addEventListener("click", handleWorkbenchActionClick)', static_app)
        self.assertIn('closest("#view-workbench")', static_app)
        self.assertNotIn('requiredElement("workbenchSummary").addEventListener("click"', static_app)
        self.assertIn("event.preventDefault();", static_app)
        self.assertIn("event.stopPropagation();", static_app)
        self.assertIn("synthesis-create-draft", static_renderers)
        self.assertIn("synthesis-reject", static_renderers)
        self.assertIn("open-trace", static_renderers)
        self.assertIn("open-trace", static_app)
        self.assertIn("open-draft", static_renderers)
        self.assertStaticRequiredElementsExist(chat_page, static_app)
        self.assertButtonBindings(
            chat_page,
            static_app,
            [
                "skillCatalogButton",
                "draftListButton",
                "metadataSearchButton",
                "createDraftButton",
                "previewDraftButton",
                "smokeDraftButton",
                "publishDraftButton",
                "skillPromoteButton",
                "runRegressionButton",
            ],
        )
        self.assertIn("/api/admin/skills/catalog", static_workbench)
        self.assertIn("/api/admin/workbench/drafts", static_workbench)
        self.assertIn("/api/admin/metadata/search", static_app)
        self.assertIn("/api/admin/regression/run", static_workbench)
        self.assertTrue(onboarding_status["ok"])
        self.assertFalse(onboarding_status["status"]["trained"])
        self.assertTrue(onboarding_candidates["ok"])
        self.assertEqual(onboarding_candidates["summary"]["total"], 1)
        self.assertTrue(synthesis_candidates["ok"])
        self.assertEqual(synthesis_candidates["summary"]["total"], 1)
        self.assertEqual(synthesis_candidates["candidates"][0]["candidate_id"], "syn_active")
        self.assertEqual(synthesis_candidates_all["summary"]["total"], 2)
        self.assertEqual(rejected_synthesis_candidate["candidate"]["status"], "rejected")
        self.assertEqual(synthesis_candidates_after_reject["summary"]["total"], 0)
        self.assertEqual(candidate_draft["draft"]["source_kind"], "onboarding_candidate")
        self.assertEqual(rejected_candidate["rejection"]["candidate_id"], onboarding_candidate_id)
        self.assertTrue(skill_catalog["ok"])
        self.assertGreaterEqual(skill_catalog["summary"]["total"], 1)
        self.assertTrue(docs_index["ok"])
        self.assertIn("docs/workbench/user_guide.md", [item["path"] for item in docs_index["docs"]])
        self.assertTrue(docs_content["ok"])
        self.assertEqual(docs_content["doc"]["path"], "docs/workbench/user_guide.md")
        self.assertIn("Workbench", docs_content["content"])
        self.assertEqual(docs_traversal_status, 404)
        self.assertTrue(stock_skill["ok"])
        self.assertEqual(stock_skill["skill"]["skill_id"], "get_stock_balances")
        self.assertIn("source_path", stock_skill["skill"])
        self.assertTrue(metadata_search["ok"])
        self.assertEqual(metadata_search["objects"][0]["full_name"], "Справочник.Склады")
        self.assertTrue(metadata_object["ok"])
        self.assertEqual(metadata_object["object"]["fields"][0]["name"], "Ссылка")
        self.assertTrue(created_draft["ok"])
        self.assertTrue(created_trace_file_exists)
        self.assertEqual(drafts["drafts"][0]["draft_id"], created_draft["draft"]["draft_id"])
        self.assertEqual(updated_draft["draft"]["description"], "Описание от консультанта")
        self.assertTrue(updated_trace_file_exists)
        self.assertEqual([item["event_type"] for item in draft_audit["events"]], ["workbench.draft.created", "workbench.draft.updated"])
        self.assertTrue(preview_draft["preview"]["ok"], preview_draft)
        self.assertIn("СУММА", preview_draft["preview"]["query"])
        self.assertTrue(preview_trace_file_exists)
        self.assertTrue(smoke_draft["smoke"]["ok"], smoke_draft)
        self.assertEqual(smoke_draft["smoke"]["row_count"], 1)
        self.assertTrue(smoke_trace_file_exists)
        self.assertTrue(approved_draft["approval"]["approval_id"])
        self.assertEqual(approved_draft["approval"]["decision"], "approved")
        self.assertEqual(approved_draft["approval"]["smoke_id"], smoke_draft["smoke"]["smoke_id"])
        self.assertEqual(draft_approvals["latest"]["approval_id"], approved_draft["approval"]["approval_id"])
        self.assertTrue(published_candidate["publication"]["ok"], published_candidate)
        self.assertEqual(published_candidate["publication"]["skill"]["status"], "candidate")
        self.assertEqual(published_candidate["publication"]["approval"]["smoke_id"], smoke_draft["smoke"]["smoke_id"])
        self.assertTrue(publish_trace_file_exists)
        self.assertNotEqual(published_candidate["publication"]["approval"]["approval_id"], approved_draft["approval"]["approval_id"])
        self.assertTrue(regression_run["ok"], regression_run)
        self.assertEqual(regression_run["regression"]["passed"], 1)
        self.assertTrue(promoted_skill["ok"], promoted_skill)
        self.assertEqual(promoted_skill["lifecycle"]["after_status"], "verified")
        self.assertEqual(promoted_skill["lifecycle"]["skill"]["status"], "verified")
        self.assertEqual(
            draft_approvals_after_publish["latest"]["approval_id"],
            published_candidate["publication"]["approval"]["approval_id"],
        )
        self.assertEqual(len(draft_approvals_after_publish["approvals"]), 2)
        self.assertTrue(deleted_draft["ok"])
        self.assertTrue(imported_draft["ok"])
        self.assertEqual(imported_draft["draft"]["source_kind"], "trace")
        self.assertEqual(imported_draft["draft"]["example_questions"], ["Покажи товар с самым большим остатком"])
        self.assertIn("applyMetadataSource", static_workbench)
        self.assertIn("applyMetadataField", static_workbench)
        self.assertIn("loadSkillDetails", static_workbench)
        self.assertIn("loadDraftDetails", static_workbench)
        self.assertIn("deleteDraftById", static_workbench)
        self.assertIn("readDraftComment", static_workbench)
        self.assertIn("showDraftCardError", static_workbench)
        self.assertIn("showDraftActionResult", static_workbench)
        self.assertIn("draft-action-result-local", static_workbench)
        self.assertIn("draft-action-feedback", static_workbench)
        self.assertIn("Заполните комментарий в карточке черновика", static_workbench)
        self.assertIn("DRAFT_ACTION_NOTICES", static_workbench)
        self.assertIn("withButtonState(button, label", static_workbench)
        self.assertIn("handleWorkbenchActionClick", static_app)
        self.assertIn('document.addEventListener("click", handleWorkbenchActionClick)', static_app)
        self.assertIn('closest("#view-workbench")', static_app)
        self.assertNotIn('requiredElement("workbenchSummary").addEventListener("click"', static_app)
        self.assertIn("postDraftAction(backendAction", static_app)
        self.assertIn("draft-delete", static_app)
        self.assertIn("draft-approve", static_renderers)
        self.assertIn("missing_successful_smoke", static_renderers)
        self.assertIn("Публикация пока не выполнена", static_renderers)
        self.assertIn("draft-comment-input", static_renderers)
        self.assertIn("draft-smoke-params-input", static_renderers)
        self.assertIn("renderApprovalResult", static_renderers)
        self.assertIn("renderDraftActionResult", static_renderers)
        self.assertIn("Утвердить проверку", static_renderers)
        self.assertIn("Опубликовать как кандидат", static_renderers)
        self.assertIn('postSkillLifecycleAction("promote"', static_app)
        self.assertTrue(chat["ok"])
        self.assertEqual(chat["result"]["source"], "general_answer")
        self.assertEqual([item["role"] for item in conversation["messages"]], ["user", "assistant"])
        self.assertTrue(conversations["ok"])
        self.assertEqual([item["session_id"] for item in conversations["sessions"]], ["s1"])
        self.assertEqual(conversations["sessions"][0]["message_count"], 2)
        self.assertIn("5.0.0-alpha.2", backend_history)


class StaticMetadataProvider(MetadataProvider):
    def __init__(self, objects: list[MetadataObject]) -> None:
        self.objects = {item.full_name: item for item in objects}
        self.last_requests = []

    def search_objects(self, term: str) -> list[MetadataObject]:
        self.last_requests.append({"operation": "search_objects", "term": term})
        lowered = term.lower()
        return [
            item
            for item in self.objects.values()
            if lowered in item.full_name.lower() or lowered in item.synonym.lower()
        ]

    def get_object(self, full_name: str) -> MetadataObject:
        self.last_requests.append({"operation": "get_object", "full_name": full_name})
        return self.objects.get(full_name, MetadataObject(full_name=full_name))


def write_trace(trace) -> None:
    trace = Path(trace)
    (trace / "input").mkdir(parents=True, exist_ok=True)
    (trace / "intent").mkdir(parents=True, exist_ok=True)
    (trace / "query_synthesis").mkdir(parents=True, exist_ok=True)
    (trace / "result").mkdir(parents=True, exist_ok=True)
    question = "Покажи товар с самым большим остатком"
    query = """
    ВЫБРАТЬ ПЕРВЫЕ 1
        Остатки.Номенклатура КАК Номенклатура,
        Остатки.ВНаличииОстаток КАК Количество
    ИЗ
        РегистрНакопления.ТоварыНаСкладах.Остатки(&Период) КАК Остатки
    """
    (trace / "input" / "user_message.json").write_text(json.dumps({"message": question}, ensure_ascii=False), encoding="utf-8")
    (trace / "intent" / "goal_decomposition.json").write_text(
        json.dumps({"business_goal": question, "final_artifact_type": "TypedTable"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (trace / "query_synthesis" / "result.json").write_text(
        json.dumps(
            {
                "synthesis": {
                    "ok": True,
                    "final_artifact": {
                        "type": "TypedTable",
                        "value": {"columns": ["Номенклатура", "Количество"], "rows": []},
                    },
                    "trace": {
                        "metadata_objects": [
                            {
                                "full_name": "РегистрНакопления.ТоварыНаСкладах",
                                "trust": "verified",
                                "fields": ["Номенклатура", "ВНаличииОстаток"],
                            }
                        ],
                        "final_query": {"query": query, "params": {}, "limit": 1},
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (trace / "result" / "result.json").write_text(
        json.dumps({"source": "query_synthesis_ok", "message": "Найден результат."}, ensure_ascii=False),
        encoding="utf-8",
    )


def write_onboarding_candidate(bot_root: Path) -> None:
    onboarding = bot_root / "onboarding"
    onboarding.mkdir(parents=True, exist_ok=True)
    (onboarding / "candidate_bindings.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "semantic_role": "stock_balance",
                        "object": "РегистрНакопления.ТоварыНаСкладах",
                        "confidence": 0.7,
                        "evidence": ["object has product and warehouse fields"],
                        "status": "candidate",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def write_synthesis_candidates(bot_root: Path) -> None:
    candidates = bot_root / "workbench" / "candidates" / "synthesis"
    candidates.mkdir(parents=True, exist_ok=True)
    base = {
        "trace_path": "/runs/agent_test",
        "query": "ВЫБРАТЬ 1 КАК Значение",
        "params": {},
        "limit": 1,
        "answer": "Тестовый ответ",
        "row_count": 1,
        "final_artifact_type": "UserAnswer",
        "metadata_objects": [],
        "created_at": "2026-07-06T10:00:00+00:00",
        "seen_count": 1,
        "payload": {},
    }
    active = {
        **base,
        "candidate_id": "syn_active",
        "question": "Активный кандидат",
        "status": "candidate",
        "updated_at": "2026-07-06T10:01:00+00:00",
    }
    rejected = {
        **base,
        "candidate_id": "syn_rejected",
        "question": "Отклоненный кандидат",
        "status": "rejected",
        "updated_at": "2026-07-06T10:02:00+00:00",
    }
    (candidates / "syn_active.json").write_text(json.dumps(active, ensure_ascii=False), encoding="utf-8")
    (candidates / "syn_rejected.json").write_text(json.dumps(rejected, ensure_ascii=False), encoding="utf-8")


def write_regression_case(bot_root: Path) -> None:
    regression = bot_root / "regression"
    regression.mkdir(parents=True, exist_ok=True)
    (regression / "reg_web_stock_top.json").write_text(
        json.dumps(
            {
                "case_id": "reg_web_stock_top",
                "question": "Привет",
                "expected_behavior": "ok",
                "expected_source": "general_answer",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()

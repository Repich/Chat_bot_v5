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
from wiicon5.web.server import make_handler, run_http_server, synthesis_candidate_trace_summary
from wiicon5.workbench.metadata_explorer import MetadataExplorerService
from wiicon5.workbench.preview import QueryPreviewService
from wiicon5.workbench.skill_catalog import SkillCatalogService
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

    def test_synthesis_candidate_trace_summary_reads_successful_attempt(self) -> None:
        with TemporaryDirectory() as temp_dir:
            trace_dir = Path(temp_dir) / "runs" / "agent_1"
            result_dir = trace_dir / "query_synthesis"
            result_dir.mkdir(parents=True)
            (result_dir / "result.json").write_text(
                json.dumps(
                    {
                        "synthesis": {
                            "trace": {
                                "row_count": 1,
                                "final_query": {"query": "ВЫБРАТЬ Клиент ИЗ Справочник.Контрагенты", "params": {"П": 1}, "limit": 10},
                                "attempts": [
                                    {
                                        "query_response": {"reasoning": "first"},
                                        "query_review": {"ok": False, "issues": [{"message": "bad field"}]},
                                    },
                                    {
                                        "query_response": {"reasoning": "fixed"},
                                        "query_review": {
                                            "ok": True,
                                            "sources": [{"source": "Справочник.Контрагенты", "alias": "К", "object_type": "Справочник"}],
                                        },
                                        "mcp_response": {"success": True, "data": [{"Клиент": "Альтаир"}]},
                                        "row_count": 1,
                                        "result_sufficiency": {"sufficient": True, "reasoning": "enough"},
                                    },
                                ],
                                "answer_formatting": {"trace": {"response": {"reasoning": "formatted"}}},
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            summary = synthesis_candidate_trace_summary(str(trace_dir))

        self.assertEqual(summary["attempt_count"], 2)
        self.assertEqual(summary["successful_attempt_count"], 1)
        self.assertEqual(summary["rows_sample"], [{"Клиент": "Альтаир"}])
        self.assertEqual(summary["query_review"]["sources"][0]["source"], "Справочник.Контрагенты")
        self.assertEqual(summary["attempts"][0]["query_review"]["issues"][0]["message"], "bad field")

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
    def test_static_renderers_show_editable_skill_actions(self) -> None:
        script = """
ObjC.import('Foundation');
var window = {};
const path = $.NSString.stringWithUTF8String('src/wiicon5/web/static/renderers.js');
const text = $.NSString.stringWithContentsOfFileEncodingError(path, $.NSUTF8StringEncoding, null).js;
eval(text);
const html = window.WiiconRenderers.renderSummary({
  ok: true,
  skills: [{
    skill_id: 'learned_product_price_lookup',
    kind: 'data_acquisition',
    status: 'verified',
    description: 'Получает цены номенклатуры по типу цены и названию товара.',
    capabilities: ['query_1c'],
    inputs: [],
    outputs: [{ name: 'prices', type: 'PriceTable', required: true, description: 'Цены номенклатуры' }],
    tags: ['learned'],
    implementation_strategy: 'learned_query',
    implementation: {
      kind: 'parameterized_lookup_query',
      query: 'ВЫБРАТЬ 1 КАК Цена',
      params: { ВидЦены: 'Розничная' }
    },
    user_editable: true,
    source_path: '/tmp/skills/learned/active/learned_product_price_lookup.json'
  }],
  summary: { total: 1 }
});
for (const expected of ['Навыков: 1', 'Получает цены номенклатуры', 'Запрос 1С', 'Настройки выполнения, JSON', 'Сохранить изменения', 'Удалить']) {
  if (html.indexOf(expected) < 0) {
    throw new Error('editable skill detail is missing ' + expected + ': ' + html);
  }
}
for (const expected of ['data-action="skill-save"', 'data-action="skill-delete"', 'skill-query-input', 'skill-implementation-input']) {
  if (html.indexOf(expected) < 0) {
    throw new Error('editable skill action is missing ' + expected + ': ' + html);
  }
}
if (html.indexOf('Опубликовать как кандидат') >= 0 || html.indexOf('Жизненный цикл') >= 0 || html.indexOf('Отметить проверенным') >= 0) {
  throw new Error('old lifecycle wording leaked into skill list: ' + html);
}
const protectedHtml = window.WiiconRenderers.renderSummary({
  ok: true,
  skill: {
    skill_id: 'render_entity_list_answer',
    kind: 'presentation',
    status: 'stable',
    description: 'Render list',
    capabilities: [],
    inputs: [],
    outputs: [],
    implementation_strategy: 'deterministic_entity_list_renderer',
    user_editable: false,
    source_path: '/tmp/skills/atomic/presentation/render_entity_list_answer.json'
  }
});
if (protectedHtml.indexOf('Базовый системный навык защищен') < 0) {
  throw new Error('protected skill hint is missing: ' + protectedHtml);
}
if (protectedHtml.indexOf('data-action="skill-save"') >= 0 || protectedHtml.indexOf('data-action="skill-delete"') >= 0) {
  throw new Error('protected skill must not expose edit/delete actions: ' + protectedHtml);
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
        with patch("wiicon5.web.server.ThreadingHTTPServer", FakeHTTPServer):
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

    def test_active_learned_skill_can_be_updated_and_deleted_from_catalog(self) -> None:
        agent = AgentOrchestrator(registry=SkillRegistry(), decomposer=ScriptedGoalDecomposer({}))
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bot_root = root / "bot"
            global_skills = root / "global_skills"
            write_active_learned_financial_skill(global_skills)
            onboarding_manager = OnboardingManager(bot_instance_root=bot_root)
            server = HTTPServer(
                ("127.0.0.1", 0),
                make_handler(
                    agent,
                    onboarding_manager=onboarding_manager,
                    skill_catalog=SkillCatalogService(global_skills_dir=global_skills, bot_instance_root=bot_root),
                ),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                update_request = urllib.request.Request(
                    f"http://{host}:{port}/api/admin/skills/catalog/learned_financial_metrics",
                    data=json.dumps(
                        {
                            "actor": "consultant",
                            "implementation": {
                                "kind": "period_metric_aggregate",
                                "source": "РегистрНакопления.ВыручкаИСебестоимостьПродаж",
                                "alias": "ВыручкаИСебестоимостьПродаж",
                                "period_field": "Период",
                                "metrics": [{"label": "Выручка", "expression": "СУММА(ВыручкаИСебестоимостьПродаж.СуммаВыручкиБезНДС)"}],
                                "limit": 50,
                            },
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="PATCH",
                )
                updated = json.loads(urllib.request.urlopen(update_request, timeout=5).read().decode("utf-8"))
                updated_catalog = json.loads(
                    urllib.request.urlopen(
                        f"http://{host}:{port}/api/admin/skills/catalog/learned_financial_metrics",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
                delete_request = urllib.request.Request(
                    f"http://{host}:{port}/api/admin/skills/catalog/learned_financial_metrics?actor=consultant",
                    method="DELETE",
                )
                deleted = json.loads(urllib.request.urlopen(delete_request, timeout=5).read().decode("utf-8"))
                active_path_exists = (
                    global_skills / "learned" / "active" / "learned_financial_metrics.json"
                ).exists()
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertTrue(updated["ok"], updated)
        self.assertEqual(updated["skill"]["implementation"]["limit"], 50)
        self.assertEqual(updated_catalog["skill"]["implementation"]["limit"], 50)
        self.assertEqual(updated_catalog["skill"]["status"], "verified")
        self.assertEqual(updated_catalog["skill"]["source_kind"], "global_learned")
        self.assertTrue(deleted["ok"], deleted)
        self.assertFalse(active_path_exists)

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
            write_learned_skill_candidate(onboarding_manager.bot_instance_root / "skills", trace_path=str(runs_root / "agent_001"))
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
                synthesis_candidate_id = "syn_active"
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
        asset_version = version["version"]
        self.assertIn(f"app.js?v={asset_version}", chat_page)
        self.assertIn(f"workbench.js?v={asset_version}", chat_page)
        self.assertIn(f"renderers.js?v={asset_version}", chat_page)
        self.assertIn(f"styles.css?v={asset_version}", chat_page)
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
        self.assertIn("skillCatalogButton", chat_page)
        self.assertIn("metadataSearchInput", chat_page)
        self.assertIn("workbenchSummary", chat_page)
        self.assertIn("metadataObjectInput", chat_page)
        self.assertIn("metadataObjectButton", chat_page)
        self.assertIn("skillDetailsButton", chat_page)
        for removed_id in [
            "draftListButton",
            "onboardingCandidatesButton",
            "synthesisCandidatesButton",
            "createDraftButton",
            "previewDraftButton",
            "smokeDraftButton",
            "approvalCommentInput",
            "candidateIdInput",
            "synthesisCandidateIdInput",
            "skillLifecycleIdInput",
            "skillPromoteButton",
            "runRegressionButton",
            "publishDraftButton",
        ]:
            self.assertNotIn(removed_id, chat_page)
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
        self.assertIn("renderMetadataObjectCard", static_renderers)
        self.assertIn("renderJsonDetails", static_renderers)
        self.assertIn("loadSkillCatalog", static_workbench)
        self.assertIn("saveSkillById", static_workbench)
        self.assertIn("deleteSkillById", static_workbench)
        self.assertIn("skill-save", static_app)
        self.assertIn("skill-delete", static_app)
        self.assertIn("skill-query-input", static_renderers)
        self.assertIn("skill-implementation-input", static_renderers)
        self.assertIn("renderWorkbenchSummary", static_workbench)
        self.assertIn("showTracePath", static_workbench)
        self.assertIn("handleWorkbenchActionClick", static_app)
        self.assertIn('document.addEventListener("click", handleWorkbenchActionClick)', static_app)
        self.assertIn('closest("#view-workbench")', static_app)
        self.assertNotIn('requiredElement("workbenchSummary").addEventListener("click"', static_app)
        self.assertIn("event.preventDefault();", static_app)
        self.assertIn("event.stopPropagation();", static_app)
        self.assertIn("open-trace", static_renderers)
        self.assertIn("open-trace", static_app)
        self.assertStaticRequiredElementsExist(chat_page, static_app)
        self.assertButtonBindings(
            chat_page,
            static_app,
            ["skillCatalogButton", "metadataSearchButton"],
        )
        self.assertIn("/api/admin/skills/catalog", static_workbench)
        self.assertIn("/api/admin/metadata/search", static_app)
        self.assertTrue(onboarding_status["ok"])
        self.assertFalse(onboarding_status["status"]["trained"])
        self.assertTrue(onboarding_candidates["ok"])
        self.assertEqual(onboarding_candidates["summary"]["total"], 1)
        self.assertTrue(synthesis_candidates["ok"])
        synthesis_candidate_ids = [item["candidate_id"] for item in synthesis_candidates["candidates"]]
        self.assertIn("syn_active", synthesis_candidate_ids)
        self.assertNotIn("learned_product_price_lookup", synthesis_candidate_ids)
        self.assertEqual(synthesis_candidates["summary"]["total"], 1)
        self.assertGreaterEqual(synthesis_candidates_all["summary"]["total"], 2)
        self.assertEqual(rejected_synthesis_candidate["candidate"]["status"], "rejected")
        after_reject_ids = [item["candidate_id"] for item in synthesis_candidates_after_reject["candidates"]]
        self.assertNotIn("syn_active", after_reject_ids)
        self.assertEqual(candidate_draft["draft"]["source_kind"], "onboarding_candidate")
        self.assertEqual(rejected_candidate["rejection"]["candidate_id"], onboarding_candidate_id)
        self.assertTrue(skill_catalog["ok"])
        self.assertGreaterEqual(skill_catalog["summary"]["total"], 1)
        learned_catalog_skill = next(
            item for item in skill_catalog["skills"] if item["skill_id"] == "learned_product_price_lookup"
        )
        self.assertTrue(learned_catalog_skill["runtime_active_by_default"])
        self.assertTrue(learned_catalog_skill["user_editable"])
        self.assertEqual(learned_catalog_skill["source_kind"], "bot_learned")
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
        self.assertIn("loadSkillDetails", static_workbench)
        self.assertIn("saveSkillById", static_workbench)
        self.assertIn("deleteSkillById", static_workbench)
        self.assertIn("runWorkbenchAction", static_workbench)
        self.assertIn("handleWorkbenchActionClick", static_app)
        self.assertIn('document.addEventListener("click", handleWorkbenchActionClick)', static_app)
        self.assertIn('closest("#view-workbench")', static_app)
        self.assertNotIn('requiredElement("workbenchSummary").addEventListener("click"', static_app)
        self.assertIn("skill-save", static_app)
        self.assertIn("skill-delete", static_app)
        self.assertIn("Настройки выполнения, JSON", static_renderers)
        self.assertIn("Изменения применяются сразу", static_renderers)
        self.assertIn("closestSkillCard", static_workbench)
        self.assertNotIn('postSkillLifecycleAction("promote"', static_app)
        self.assertTrue(chat["ok"])
        self.assertEqual(chat["result"]["source"], "general_answer")
        self.assertEqual([item["role"] for item in chat["messages"]], ["user", "assistant"])
        self.assertTrue(all(item["ts"] for item in chat["messages"]))
        self.assertEqual([item["role"] for item in conversation["messages"]], ["user", "assistant"])
        self.assertIn("formatMessageTime", static_app)
        self.assertIn("message-time", static_css)
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


def write_learned_skill_candidate(skills_root: Path, *, trace_path: str) -> None:
    candidates = skills_root / "learned" / "active"
    candidates.mkdir(parents=True, exist_ok=True)
    payload = {
        "skill_id": "learned_product_price_lookup",
        "version": "0.1.0",
        "kind": "data_acquisition",
        "status": "verified",
        "description": "Learned product price lookup.",
        "capabilities": ["learned_query", "parameterized_lookup_query", "product", "price_type", "produce:PriceTable"],
        "inputs": [{"name": "filters", "type": "SemanticFilterList", "required": True}],
        "outputs": [{"name": "table", "type": "PriceTable", "required": True}],
        "tags": ["learned", "lookup", "product", "price_type"],
        "supported_filter_roles": ["product", "price_type"],
        "implementation_strategy": "learned_query",
        "implementation": {
            "kind": "parameterized_lookup_query",
            "query": "ВЫБРАТЬ 1 КАК Цена",
            "params": {"ВидЦены": "Розничная", "МаскаТовара": "%куртк%"},
            "limit": 100,
            "parameter_bindings": [
                {"semantic_field": "price_type", "parameter": "ВидЦены", "transform": "raw", "required": True},
                {"semantic_field": "product", "parameter": "МаскаТовара", "transform": "contains_like", "required": True},
            ],
            "metadata_dependencies": ["РегистрСведений.ЦеныНоменклатуры"],
            "evidence": {
                "created_from_trace": trace_path,
                "question": "Получить розничные цены на куртки",
            },
        },
    }
    (candidates / "learned_product_price_lookup.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def write_active_learned_financial_skill(skills_root: Path) -> None:
    candidates = skills_root / "learned" / "active"
    candidates.mkdir(parents=True, exist_ok=True)
    payload = {
        "skill_id": "learned_financial_metrics",
        "version": "0.1.0",
        "kind": "data_acquisition",
        "status": "verified",
        "description": "Learned financial metrics.",
        "capabilities": ["learned_query", "retrieve_metrics", "produce:FinancialMetricsTable"],
        "inputs": [{"name": "filters", "type": "SemanticFilterList", "required": False}],
        "outputs": [{"name": "table", "type": "FinancialMetricsTable", "required": True}],
        "tags": ["learned", "metrics"],
        "supported_filter_roles": ["year", "period", "period_granularity"],
        "semantic_role": "financial_metrics",
        "implementation_strategy": "learned_query",
        "implementation": {
            "kind": "period_metric_aggregate",
            "source": "РегистрНакопления.ВыручкаИСебестоимостьПродаж",
            "alias": "ВыручкаИСебестоимостьПродаж",
            "period_field": "Период",
            "metrics": [
                {
                    "label": "Выручка",
                    "expression": "СУММА(ВыручкаИСебестоимостьПродаж.СуммаВыручкиБезНДС)",
                },
                {
                    "label": "Прибыль",
                    "expression": "СУММА(ВыручкаИСебестоимостьПродаж.СуммаВыручкиБезНДС - ВыручкаИСебестоимостьПродаж.СтоимостьБезНДС)",
                },
            ],
            "activity_filter": True,
            "activity_field": "Активность",
            "metadata_dependencies": ["РегистрНакопления.ВыручкаИСебестоимостьПродаж"],
        },
    }
    (candidates / "learned_financial_metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


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

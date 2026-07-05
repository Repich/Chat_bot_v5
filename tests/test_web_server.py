from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from wiicon5.agent.orchestrator import AgentOrchestrator
from wiicon5.intent.decomposer import DecompositionResult
from wiicon5.intent.models import IntentResult, IntentType
from wiicon5.knowledge.metadata import MetadataObject, MetadataProvider
from wiicon5.mcp.client import DictMcpClient
from wiicon5.onboarding.status import OnboardingManager
from wiicon5.skills.registry import SkillRegistry
from wiicon5.testing.scripted_decomposer import ScriptedGoalDecomposer
from wiicon5.web.server import make_handler
from wiicon5.workbench.metadata_explorer import MetadataExplorerService
from wiicon5.workbench.smoke import McpSmokeTestService
from wiicon5.workbench.trace_import import TraceDraftImporter


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WebServerTests(unittest.TestCase):
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
            metadata_explorer = MetadataExplorerService(
                provider=StaticMetadataProvider(
                    [
                        MetadataObject(
                            full_name="Справочник.Склады",
                            synonym="Склады",
                            fields=["Ссылка"],
                            field_details={"Ссылка": {"name": "Ссылка", "_source": "mcp", "_trust": "verified"}},
                            raw={"_source": "mcp", "_trust": "verified", "kind": "Справочник"},
                        )
                    ]
                )
            )
            server = HTTPServer(
                ("127.0.0.1", 0),
                make_handler(
                    agent,
                    onboarding_manager=onboarding_manager,
                    metadata_explorer=metadata_explorer,
                    trace_importer=TraceDraftImporter(runs_root=runs_root),
                    smoke_service=McpSmokeTestService(
                        bot_instance_root=onboarding_manager.bot_instance_root,
                        mcp_client=DictMcpClient(
                            {"success": True, "data": [{"Номенклатура": "Телевизор", "Количество": 10}]}
                        ),
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
                        {"actor": "approver", "comment": "Smoke sample reviewed"},
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
                        {"actor": "publisher", "comment": "Publication sample reviewed"},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                published_candidate = json.loads(
                    urllib.request.urlopen(publish_candidate_request, timeout=5).read().decode("utf-8")
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
                backend_history = urllib.request.urlopen(f"http://{host}:{port}/history/backend", timeout=5).read().decode("utf-8")
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertTrue(health["ok"])
        self.assertEqual(version["version"], (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip())
        self.assertIn("text/html", chat_page_response.headers["Content-Type"])
        self.assertIn("WIICON ChatBot 5", chat_page)
        self.assertIn("chatForm", chat_page)
        self.assertIn("appVersion", chat_page)
        self.assertIn("sessionList", chat_page)
        self.assertIn("newSessionButton", chat_page)
        self.assertIn("settingsDetails", chat_page)
        self.assertIn("reloadHistoryButton", chat_page)
        self.assertIn("trainingBanner", chat_page)
        self.assertIn("startOnboardingButton", chat_page)
        self.assertIn("workbenchPanel", chat_page)
        self.assertIn("skillCatalogButton", chat_page)
        self.assertIn("draftListButton", chat_page)
        self.assertIn("onboardingCandidatesButton", chat_page)
        self.assertIn("synthesisCandidatesButton", chat_page)
        self.assertIn("metadataSearchInput", chat_page)
        self.assertIn("createDraftButton", chat_page)
        self.assertIn("previewDraftButton", chat_page)
        self.assertIn("smokeDraftButton", chat_page)
        self.assertIn("approvalCommentInput", chat_page)
        self.assertIn("approveDraftButton", chat_page)
        self.assertIn("rejectDraftButton", chat_page)
        self.assertIn("candidateIdInput", chat_page)
        self.assertIn("candidateCreateDraftButton", chat_page)
        self.assertIn("candidateRejectButton", chat_page)
        self.assertIn("synthesisCandidateIdInput", chat_page)
        self.assertIn("synthesisCreateDraftButton", chat_page)
        self.assertIn("synthesisRejectButton", chat_page)
        self.assertIn("synthesisIgnoreSimilarButton", chat_page)
        self.assertIn("publishDraftButton", chat_page)
        self.assertTrue(onboarding_status["ok"])
        self.assertFalse(onboarding_status["status"]["trained"])
        self.assertTrue(onboarding_candidates["ok"])
        self.assertEqual(onboarding_candidates["summary"]["total"], 1)
        self.assertTrue(synthesis_candidates["ok"])
        self.assertEqual(synthesis_candidates["summary"]["total"], 0)
        self.assertEqual(candidate_draft["draft"]["source_kind"], "onboarding_candidate")
        self.assertEqual(rejected_candidate["rejection"]["candidate_id"], onboarding_candidate_id)
        self.assertTrue(skill_catalog["ok"])
        self.assertGreaterEqual(skill_catalog["summary"]["total"], 1)
        self.assertTrue(stock_skill["ok"])
        self.assertEqual(stock_skill["skill"]["skill_id"], "get_stock_balances")
        self.assertIn("source_path", stock_skill["skill"])
        self.assertTrue(metadata_search["ok"])
        self.assertEqual(metadata_search["objects"][0]["full_name"], "Справочник.Склады")
        self.assertTrue(metadata_object["ok"])
        self.assertEqual(metadata_object["object"]["fields"][0]["name"], "Ссылка")
        self.assertTrue(created_draft["ok"])
        self.assertEqual(drafts["drafts"][0]["draft_id"], created_draft["draft"]["draft_id"])
        self.assertEqual(updated_draft["draft"]["description"], "Описание от консультанта")
        self.assertEqual([item["event_type"] for item in draft_audit["events"]], ["workbench.draft.created", "workbench.draft.updated"])
        self.assertTrue(preview_draft["preview"]["ok"], preview_draft)
        self.assertIn("СУММА", preview_draft["preview"]["query"])
        self.assertTrue(smoke_draft["smoke"]["ok"], smoke_draft)
        self.assertEqual(smoke_draft["smoke"]["row_count"], 1)
        self.assertTrue(approved_draft["approval"]["approval_id"])
        self.assertEqual(approved_draft["approval"]["decision"], "approved")
        self.assertEqual(draft_approvals["latest"]["approval_id"], approved_draft["approval"]["approval_id"])
        self.assertTrue(published_candidate["publication"]["ok"], published_candidate)
        self.assertEqual(published_candidate["publication"]["skill"]["status"], "candidate")
        self.assertNotEqual(published_candidate["publication"]["approval"]["approval_id"], approved_draft["approval"]["approval_id"])
        self.assertEqual(
            draft_approvals_after_publish["latest"]["approval_id"],
            published_candidate["publication"]["approval"]["approval_id"],
        )
        self.assertEqual(len(draft_approvals_after_publish["approvals"]), 2)
        self.assertTrue(deleted_draft["ok"])
        self.assertTrue(imported_draft["ok"])
        self.assertEqual(imported_draft["draft"]["source_kind"], "trace")
        self.assertEqual(imported_draft["draft"]["example_questions"], ["Покажи товар с самым большим остатком"])
        self.assertIn('input.addEventListener("keydown"', chat_page)
        self.assertIn("form.requestSubmit()", chat_page)
        self.assertIn("startTitleBlink", chat_page)
        self.assertIn("Новое сообщение", chat_page)
        self.assertIn("loadSkillCatalog", chat_page)
        self.assertIn("loadOnboardingCandidates", chat_page)
        self.assertIn("loadSynthesisCandidates", chat_page)
        self.assertIn("postDraftAction", chat_page)
        self.assertIn("postCandidateAction", chat_page)
        self.assertIn("postSynthesisCandidateAction", chat_page)
        self.assertIn('postDraftAction("approve"', chat_page)
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


if __name__ == "__main__":
    unittest.main()

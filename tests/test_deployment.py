from __future__ import annotations

import hashlib
import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from wiicon5.deployment.diagnostics import SessionDiagnosticStore
from wiicon5.deployment.updates import (
    OfflineUpdateManager,
    apply_update,
    read_update_package,
    rollback_update,
)


class SessionDiagnosticStoreTests(unittest.TestCase):
    def test_bundle_contains_session_traces_and_logs_without_env_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            bot = root / "bot"
            runs = bot / "runs"
            trace = runs / "agent_001"
            (trace / "result").mkdir(parents=True)
            (trace / "result" / "result.json").write_text('{"ok": true}', encoding="utf-8")
            bot.mkdir(exist_ok=True)
            (bot / "bot.yaml").write_text("bot:\n  id: test\n", encoding="utf-8")
            project.mkdir()
            (project / ".env.wiicon5").write_text("WIICON5_LLM_API_KEY=top-secret\n", encoding="utf-8")
            service_log = root / "logs" / "service.log"
            service_log.parent.mkdir()
            service_log.write_text("service started\n", encoding="utf-8")
            store = SessionDiagnosticStore(
                root=bot / "diagnostics",
                runs_root=runs,
                project_root=project,
                bot_root=bot,
                service_log_paths=(service_log,),
            )
            store.append("demo/session", "request.started", {"request_id": "r1", "message": "Покажи склады"})
            store.append(
                "demo/session",
                "request.completed",
                {"request_id": "r1", "trace_path": str(trace), "result": {"source": "skill_execution_ok"}},
            )

            bundle = store.export(
                "demo/session",
                conversation=[{"role": "user", "content": "Покажи склады"}],
                version="5.0.0-test",
                public_config={"bot": {"id": "test"}},
            )

            with zipfile.ZipFile(bundle.path) as archive:
                names = set(archive.namelist())
                combined = b"".join(archive.read(name) for name in names)
            self.assertIn("session/events.jsonl", names)
            self.assertIn("session/conversation.json", names)
            self.assertIn("traces/agent_001/result/result.json", names)
            self.assertIn("logs/service.log", names)
            self.assertIn("config/bot.yaml", names)
            self.assertNotIn(b"top-secret", combined)
            self.assertNotIn(".env.wiicon5", names)
            self.assertEqual(store.status("demo/session")["event_count"], 2)


class OfflineUpdateTests(unittest.TestCase):
    def test_verified_update_preserves_data_and_supports_rollback(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current = root / "app" / "current"
            current.mkdir(parents=True)
            (current / "VERSION").write_text("5.0.0-alpha.1\n", encoding="utf-8")
            (current / "old.txt").write_text("old", encoding="utf-8")
            persistent = root / "data" / "learned.json"
            persistent.parent.mkdir(parents=True)
            persistent.write_text("keep", encoding="utf-8")
            package = root / "updates" / "inbox" / "update.zip"
            write_update_package(
                package,
                "5.0.0-alpha.2",
                {
                    "app/VERSION": b"5.0.0-alpha.2\n",
                    "app/new.txt": b"new",
                    "data_seed/seed.json": b"seed",
                },
            )

            result = apply_update(package, install_root=root)

            self.assertTrue(result["ok"])
            self.assertEqual((root / "app" / "current" / "new.txt").read_text(), "new")
            self.assertEqual((root / "data" / "learned.json").read_text(), "keep")
            self.assertEqual((root / "data" / "seed.json").read_text(), "seed")
            self.assertTrue(rollback_update(install_root=root))
            self.assertEqual((root / "app" / "current" / "old.txt").read_text(), "old")

    def test_manager_rejects_tampered_package_and_requests_latest_valid_version(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inbox = root / "inbox"
            request_file = root / "apply-request.json"
            old_package = inbox / "old.zip"
            new_package = inbox / "new.zip"
            write_update_package(old_package, "5.0.0-alpha.2", {"app/VERSION": b"5.0.0-alpha.2\n"})
            write_update_package(new_package, "5.0.0-alpha.3", {"app/VERSION": b"5.0.0-alpha.3\n"})
            manager = OfflineUpdateManager(inbox=inbox, request_file=request_file, current_version="5.0.0-alpha.1")

            selected = manager.request_latest()

            self.assertEqual(selected.version, "5.0.0-alpha.3")
            self.assertEqual(json.loads(request_file.read_text())["package"], str(new_package.resolve()))
            tampered = inbox / "tampered.zip"
            write_update_package(tampered, "5.0.0-alpha.4", {"app/VERSION": b"5.0.0-alpha.4\n"})
            rewrite_zip_entry(tampered, "payload/app/VERSION", b"changed")
            with self.assertRaisesRegex(ValueError, "контрольная сумма"):
                read_update_package(tampered, verify_files=True)

    def test_update_rejects_unlisted_payload_and_rolls_back_after_post_swap_failure(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current = root / "app" / "current"
            current.mkdir(parents=True)
            (current / "VERSION").write_text("5.0.0-alpha.1\n", encoding="utf-8")
            (current / "old.txt").write_text("old", encoding="utf-8")
            package = root / "update.zip"
            write_update_package(
                package,
                "5.0.0-alpha.2",
                {"app/VERSION": b"5.0.0-alpha.2\n", "data_seed/new.json": b"seed"},
            )
            with patch("wiicon5.deployment.updates.merge_data_seed", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    apply_update(package, install_root=root)
            self.assertEqual((root / "app" / "current" / "old.txt").read_text(), "old")

            rewrite_zip_entry(package, "payload/app/unlisted.py", b"print('unexpected')")
            with self.assertRaisesRegex(ValueError, "не совпадает"):
                read_update_package(package, verify_files=True)


def write_update_package(path: Path, version: str, files: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in files.items()
    ]
    manifest = {
        "schema_version": 1,
        "product": "wiicon-chatbot-v5",
        "version": version,
        "created_at": "2026-07-12T00:00:00+00:00",
        "files": records,
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in files.items():
            archive.writestr(f"payload/{name}", data)


def rewrite_zip_entry(path: Path, entry_name: str, data: bytes) -> None:
    with zipfile.ZipFile(path) as source:
        entries = {item.filename: source.read(item.filename) for item in source.infolist()}
    entries[entry_name] = data
    with zipfile.ZipFile(path, "w") as target:
        for name, value in entries.items():
            target.writestr(name, value)


if __name__ == "__main__":
    unittest.main()

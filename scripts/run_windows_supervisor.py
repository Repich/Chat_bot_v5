from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Supervise WIICON5 and apply offline updates.")
    parser.add_argument("--install-root", required=True)
    parser.add_argument("--port", type=int, default=7786)
    args = parser.parse_args()
    install_root = Path(args.install_root).resolve()
    logs_root = install_root / "logs"
    logs_root.mkdir(parents=True, exist_ok=True)
    supervisor_log = logs_root / "supervisor.log"
    request_file = install_root / "updates" / "apply-request.json"

    while True:
        update_result = apply_pending_update(install_root, request_file, supervisor_log)
        child = start_bot(install_root, args.port, logs_root / "service.log", supervisor_log)
        healthy = wait_for_health(args.port, child, timeout_seconds=90)
        if not healthy:
            log(supervisor_log, f"Новая версия не прошла health-check; pid={child.pid}.")
            stop_process(child)
            if update_result and rollback(install_root, supervisor_log):
                mark_update_failed(install_root, update_result, "health_check_failed")
                continue
        elif update_result:
            mark_update_applied(install_root, update_result)
            log(supervisor_log, f"Обновление {update_result.get('version')} успешно запущено.")

        while child.poll() is None:
            if request_file.is_file():
                log(supervisor_log, "Получена заявка на обновление; останавливаю рабочий процесс.")
                stop_process(child)
                break
            time.sleep(1)
        exit_code = child.poll()
        if request_file.is_file():
            continue
        log(supervisor_log, f"Рабочий процесс завершился с кодом {exit_code}; повторный запуск через 3 секунды.")
        time.sleep(3)


def start_bot(install_root: Path, port: int, service_log: Path, supervisor_log: Path) -> subprocess.Popen:
    app_root = install_root / "app" / "current"
    runtime = install_root / "runtime" / "python.exe"
    if not runtime.is_file():
        runtime = Path(sys.executable)
    env = dict(os.environ)
    env.update(read_env_file(install_root / "config" / ".env.wiicon5"))
    env.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "WIICON5_INSTALL_ROOT": str(install_root),
            "WIICON5_BOT_ID": "wiic_bwiki",
            "WIICON5_BOT_ROOT": str(install_root / "data" / "bot_instances" / "wiic_bwiki"),
            "WIICON5_BOT_CONFIG": str(app_root / "bot_instances" / "wiic_bwiki" / "bot.yaml"),
            "WIICON5_RUNS_DIR": str(install_root / "data" / "bot_instances" / "wiic_bwiki" / "runs"),
            "WIICON5_SKILLS_DIR": str(app_root / "skills"),
            "WIICON5_BINDINGS_DIR": str(install_root / "data" / "skills" / "bindings"),
            "WIICON5_DIAGNOSTICS_DIR": str(install_root / "data" / "diagnostics"),
            "WIICON5_SERVICE_LOG": str(service_log),
            "WIICON5_UPDATE_INBOX": str(install_root / "updates" / "inbox"),
            "WIICON5_UPDATE_REQUEST_FILE": str(install_root / "updates" / "apply-request.json"),
        }
    )
    service_log.parent.mkdir(parents=True, exist_ok=True)
    stream = service_log.open("a", encoding="utf-8")
    command = [
        str(runtime),
        str(app_root / "scripts" / "run_wiic_bwiki.py"),
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
    ]
    log(supervisor_log, f"Запуск версии {read_version(app_root)}: {' '.join(command)}")
    process = subprocess.Popen(command, cwd=str(app_root), env=env, stdout=stream, stderr=subprocess.STDOUT)
    stream.close()
    return process


def apply_pending_update(install_root: Path, request_file: Path, supervisor_log: Path) -> dict | None:
    request = read_json(request_file)
    if not request:
        return None
    app_root = install_root / "app" / "current"
    sys.path.insert(0, str(app_root / "src"))
    from wiicon5.deployment.updates import apply_update

    package = Path(str(request.get("package") or ""))
    try:
        result = apply_update(package, install_root=install_root)
        request_file.unlink(missing_ok=True)
        return {**result, "package_path": str(package)}
    except Exception as exc:
        log(supervisor_log, f"Не удалось применить обновление {package}: {exc}")
        request_file.unlink(missing_ok=True)
        failed_root = install_root / "updates" / "failed"
        failed_root.mkdir(parents=True, exist_ok=True)
        if package.is_file():
            shutil.move(str(package), failed_root / package.name)
        write_json(failed_root / "last-error.json", {"ts": utc_now(), "package": str(package), "error": str(exc)})
        return None
    finally:
        try:
            sys.path.remove(str(app_root / "src"))
        except ValueError:
            pass


def rollback(install_root: Path, supervisor_log: Path) -> bool:
    app_root = install_root / "app" / "current"
    sys.path.insert(0, str(app_root / "src"))
    try:
        from wiicon5.deployment.updates import rollback_update

        result = rollback_update(install_root=install_root)
        log(supervisor_log, "Выполнен автоматический откат." if result else "Каталог для отката не найден.")
        return result
    finally:
        try:
            sys.path.remove(str(app_root / "src"))
        except ValueError:
            pass


def mark_update_applied(install_root: Path, result: dict) -> None:
    package = Path(str(result.get("package_path") or result.get("package") or ""))
    target_root = install_root / "updates" / "applied"
    target_root.mkdir(parents=True, exist_ok=True)
    if package.is_file():
        target = target_root / package.name
        target.unlink(missing_ok=True)
        shutil.move(str(package), target)
    write_json(target_root / "last-success.json", {"ts": utc_now(), **result})


def mark_update_failed(install_root: Path, result: dict, reason: str) -> None:
    package = Path(str(result.get("package_path") or result.get("package") or ""))
    target_root = install_root / "updates" / "failed"
    target_root.mkdir(parents=True, exist_ok=True)
    if package.is_file():
        target = target_root / package.name
        target.unlink(missing_ok=True)
        shutil.move(str(package), target)
    write_json(target_root / "last-error.json", {"ts": utc_now(), "reason": reason, **result})


def wait_for_health(port: int, child: subprocess.Popen, *, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        if child.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("ok"):
                    return True
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(1)
    return False


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def read_env_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_version(app_root: Path) -> str:
    try:
        return (app_root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def log(path: Path, message: str) -> None:
    line = f"{utc_now()} {message}"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())

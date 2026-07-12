from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


PRODUCT_ID = "wiicon-chatbot-v5"
UPDATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class UpdatePackage:
    path: Path
    version: str
    created_at: str
    files: tuple[Mapping[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "file_name": self.path.name,
            "version": self.version,
            "created_at": self.created_at,
            "file_count": len(self.files),
            "size_bytes": self.path.stat().st_size if self.path.exists() else 0,
        }


class OfflineUpdateManager:
    def __init__(self, *, inbox: Path, request_file: Path, current_version: str) -> None:
        self.inbox = inbox.resolve()
        self.request_file = request_file.resolve()
        self.current_version = current_version
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.request_file.parent.mkdir(parents=True, exist_ok=True)

    def packages(self) -> list[UpdatePackage]:
        result: list[UpdatePackage] = []
        for path in self.inbox.glob("*.zip"):
            try:
                result.append(read_update_package(path, verify_files=False))
            except (OSError, ValueError, zipfile.BadZipFile):
                continue
        return sorted(result, key=lambda item: (version_key(item.version), item.created_at, item.path.name), reverse=True)

    def status(self) -> dict[str, Any]:
        packages = self.packages()
        pending = read_json(self.request_file)
        return {
            "enabled": True,
            "current_version": self.current_version,
            "inbox": str(self.inbox),
            "request_file": str(self.request_file),
            "pending": pending,
            "packages": [item.to_dict() for item in packages],
            "latest": packages[0].to_dict() if packages else None,
        }

    def request_latest(self) -> UpdatePackage:
        packages = self.packages()
        if not packages:
            raise FileNotFoundError(f"В каталоге обновлений нет ZIP-пакетов: {self.inbox}")
        package = read_update_package(packages[0].path, verify_files=True)
        if version_key(package.version) <= version_key(self.current_version):
            raise ValueError(
                f"Последний пакет {package.version} не новее установленной версии {self.current_version}."
            )
        payload = {
            "schema_version": 1,
            "requested_at": utc_now(),
            "package": str(package.path),
            "version": package.version,
        }
        atomic_write_json(self.request_file, payload)
        return package


def read_update_package(path: Path, *, verify_files: bool = True) -> UpdatePackage:
    resolved = path.resolve()
    with zipfile.ZipFile(resolved) as archive:
        try:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        except KeyError as exc:
            raise ValueError("В архиве отсутствует manifest.json.") from exc
        if not isinstance(manifest, dict):
            raise ValueError("manifest.json должен содержать объект JSON.")
        if manifest.get("product") != PRODUCT_ID:
            raise ValueError("Архив предназначен для другого продукта.")
        if int(manifest.get("schema_version") or 0) != UPDATE_SCHEMA_VERSION:
            raise ValueError("Неподдерживаемая версия формата обновления.")
        version = str(manifest.get("version") or "").strip()
        if not version:
            raise ValueError("В manifest.json не указана версия.")
        raw_files = manifest.get("files")
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError("В manifest.json отсутствует список файлов.")
        files: list[Mapping[str, Any]] = []
        expected_archive_names: set[str] = set()
        for item in raw_files:
            if not isinstance(item, Mapping):
                raise ValueError("Некорректная запись файла в manifest.json.")
            relative = safe_payload_path(str(item.get("path") or ""))
            archive_name = f"payload/{relative.as_posix()}"
            if archive_name in expected_archive_names:
                raise ValueError(f"Файл {archive_name} повторяется в manifest.json.")
            expected_archive_names.add(archive_name)
            if archive_name not in archive.namelist():
                raise ValueError(f"В архиве отсутствует файл {archive_name}.")
            if verify_files:
                digest = hashlib.sha256(archive.read(archive_name)).hexdigest()
                if digest != str(item.get("sha256") or ""):
                    raise ValueError(f"Нарушена контрольная сумма файла {relative.as_posix()}.")
            files.append(dict(item))
        actual_archive_names = {
            item.filename
            for item in archive.infolist()
            if not item.is_dir() and item.filename.startswith("payload/")
        }
        if actual_archive_names != expected_archive_names:
            unexpected = sorted(actual_archive_names - expected_archive_names)
            missing = sorted(expected_archive_names - actual_archive_names)
            raise ValueError(f"Содержимое payload не совпадает с manifest.json: лишние={unexpected}, отсутствуют={missing}.")
    return UpdatePackage(
        path=resolved,
        version=version,
        created_at=str(manifest.get("created_at") or ""),
        files=tuple(files),
    )


def apply_update(package_path: Path, *, install_root: Path) -> dict[str, Any]:
    package = read_update_package(package_path, verify_files=True)
    root = install_root.resolve()
    app_root = root / "app"
    current = app_root / "current"
    rollback = app_root / "rollback"
    staging_root = root / "updates" / "staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f"{file_safe_version(package.version)}_", dir=staging_root))
    stage_app = stage / "app"
    swapped = False
    try:
        extract_update_payload(package.path, stage)
        if not stage_app.is_dir() or not (stage_app / "VERSION").is_file():
            raise ValueError("Пакет не содержит полноценный каталог app с VERSION.")
        if rollback.exists():
            shutil.rmtree(rollback)
        if current.exists():
            current.replace(rollback)
        stage_app.replace(current)
        swapped = True
        merge_data_seed(stage / "data_seed", root / "data")
        shutil.rmtree(stage, ignore_errors=True)
        return {
            "ok": True,
            "version": package.version,
            "package": str(package.path),
            "rollback_available": rollback.is_dir(),
        }
    except Exception:
        if swapped:
            if current.exists():
                shutil.rmtree(current)
            if rollback.exists():
                rollback.replace(current)
        elif not current.exists() and rollback.exists():
            rollback.replace(current)
        shutil.rmtree(stage, ignore_errors=True)
        raise


def rollback_update(*, install_root: Path) -> bool:
    root = install_root.resolve()
    current = root / "app" / "current"
    rollback = root / "app" / "rollback"
    if not rollback.is_dir():
        return False
    failed = root / "app" / "failed"
    if failed.exists():
        shutil.rmtree(failed)
    if current.exists():
        current.replace(failed)
    rollback.replace(current)
    return True


def extract_update_payload(package_path: Path, target: Path) -> None:
    with zipfile.ZipFile(package_path) as archive:
        for info in archive.infolist():
            if info.filename == "manifest.json" or info.is_dir():
                continue
            if not info.filename.startswith("payload/"):
                raise ValueError(f"Недопустимый файл вне payload: {info.filename}")
            relative = safe_payload_path(info.filename[len("payload/") :])
            destination = target.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)


def merge_data_seed(source: Path, target: Path) -> None:
    if not source.is_dir():
        return
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        destination = target / path.relative_to(source)
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def safe_payload_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or path.parts[0] not in {"app", "data_seed"}:
        raise ValueError(f"Недопустимый путь в пакете: {value}")
    return path


def version_key(value: str) -> tuple[int, ...]:
    normalized = value.lower().replace("alpha", ".").replace("beta", ".").replace("rc", ".")
    parts: list[int] = []
    current = ""
    for char in normalized:
        if char.isdigit():
            current += char
        elif current:
            parts.append(int(current))
            current = ""
    if current:
        parts.append(int(current))
    return tuple(parts or [0])


def file_safe_version(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "."} else "-" for char in value)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_manifest(*, version: str, files: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": UPDATE_SCHEMA_VERSION,
        "product": PRODUCT_ID,
        "version": version,
        "created_at": utc_now(),
        "files": [dict(item) for item in files],
    }

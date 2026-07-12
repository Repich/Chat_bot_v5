from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path


PYTHON_EMBED_VERSION = "3.12.10"
PYTHON_EMBED_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_EMBED_VERSION}/"
    f"python-{PYTHON_EMBED_VERSION}-embed-amd64.zip"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build WIICON5 offline Windows installer and update package.")
    parser.add_argument("--output-dir", default="dist/offline")
    parser.add_argument("--mode", choices=["all", "update", "installer"], default="all")
    parser.add_argument("--python-runtime-zip", default="")
    parser.add_argument("--skip-runtime-download", action="store_true")
    parser.add_argument("--include-data-seed-in-update", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    output_dir = (root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    app_files = application_files(root)
    built_packages: list[Path] = []

    if args.mode in {"all", "update"}:
        update_path = output_dir / f"wiicon5-update-{version}.zip"
        build_update_archive(
            root,
            app_files,
            update_path,
            version,
            include_data_seed=args.include_data_seed_in_update,
        )
        built_packages.append(update_path)
        print(update_path)

    if args.mode in {"all", "installer"}:
        runtime_zip = resolve_runtime_zip(
            output_dir,
            explicit=Path(args.python_runtime_zip).expanduser() if args.python_runtime_zip else None,
            allow_download=not args.skip_runtime_download,
        )
        installer_path = output_dir / f"wiicon5-offline-windows-x64-{version}.zip"
        build_installer_archive(root, app_files, runtime_zip, installer_path, version)
        built_packages.append(installer_path)
        print(installer_path)
    checksum_path = output_dir / "SHA256SUMS.txt"
    write_checksum_manifest(built_packages, checksum_path)
    print(checksum_path)
    return 0


def build_update_archive(
    root: Path,
    app_files: list[Path],
    target: Path,
    version: str,
    *,
    include_data_seed: bool = False,
) -> None:
    records = []
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in app_files:
            relative = path.relative_to(root)
            data = path.read_bytes()
            payload_path = Path("app") / relative
            archive.writestr(f"payload/{payload_path.as_posix()}", data)
            records.append(file_record(payload_path, data))
        if include_data_seed:
            for source, relative in data_seed_files(root):
                data = source.read_bytes()
                payload_path = Path("data_seed") / relative
                archive.writestr(f"payload/{payload_path.as_posix()}", data)
                records.append(file_record(payload_path, data))
        manifest = build_manifest(version, records)
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


def build_installer_archive(
    root: Path,
    app_files: list[Path],
    runtime_zip: Path,
    target: Path,
    version: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="wiicon5-installer-") as temporary:
        stage = Path(temporary) / f"WiiconChatBot5-{version}"
        app_target = stage / "app" / "current"
        for path in app_files:
            destination = app_target / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        for source, relative in data_seed_files(root):
            destination = stage / "data_seed" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        with zipfile.ZipFile(runtime_zip) as archive:
            archive.extractall(stage / "runtime")
        configure_embedded_python(stage / "runtime")
        for name in ["install.cmd", "install.ps1", "run-bot.cmd", "apply-update.cmd", "server.env.example"]:
            shutil.copy2(root / "deployment" / "windows" / name, stage / name)
        (stage / "PACKAGE_VERSION.txt").write_text(version + "\n", encoding="utf-8")
        zip_tree(stage, target)


def application_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    )
    paths = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8"))
        path = root / relative
        allowed = relative.parts[0] in {"src", "scripts", "skills", "bot_instances", "docs", "deployment"} or relative.as_posix() in {
            "README.md",
            "VERSION",
            "pyproject.toml",
        }
        if allowed and path.is_file() and not path.name.startswith(".env"):
            paths.append(path)
    return sorted(paths)


def data_seed_files(root: Path) -> list[tuple[Path, Path]]:
    result: list[tuple[Path, Path]] = []
    for source_root, relative_root in [
        (root / "skills", Path("skills")),
        (root / "bot_instances" / "wiic_bwiki", Path("bot_instances") / "wiic_bwiki"),
    ]:
        if not source_root.is_dir():
            continue
        for path in sorted(source_root.rglob("*")):
            if not path.is_file() or should_skip_mutable_seed(path, source_root):
                continue
            result.append((path, relative_root / path.relative_to(source_root)))
    return result


def should_skip_mutable_seed(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    blocked = {"runs", "diagnostics", "workbench", "evaluation", "regression/results", "__pycache__"}
    value = relative.as_posix()
    return any(value == item or value.startswith(item + "/") for item in blocked) or path.name == ".DS_Store"


def resolve_runtime_zip(output_dir: Path, *, explicit: Path | None, allow_download: bool) -> Path:
    if explicit:
        if not explicit.is_file():
            raise FileNotFoundError(explicit)
        return explicit.resolve()
    cache = output_dir / f"python-{PYTHON_EMBED_VERSION}-embed-amd64.zip"
    if cache.is_file():
        return cache
    if not allow_download:
        raise FileNotFoundError("Windows Python runtime не найден; укажите --python-runtime-zip.")
    print(f"Downloading {PYTHON_EMBED_URL}")
    urllib.request.urlretrieve(PYTHON_EMBED_URL, cache)
    return cache


def configure_embedded_python(runtime_root: Path) -> None:
    path_files = list(runtime_root.glob("python*._pth"))
    if not path_files:
        raise FileNotFoundError("В Windows runtime отсутствует python*._pth.")
    for path in path_files:
        lines = path.read_text(encoding="utf-8").splitlines()
        app_source = r"..\app\current\src"
        if app_source not in lines:
            lines.append(app_source)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_manifest(version: str, files: list[dict]) -> dict:
    from datetime import datetime, timezone

    return {
        "schema_version": 1,
        "product": "wiicon-chatbot-v5",
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }


def file_record(path: Path, data: bytes) -> dict:
    return {"path": path.as_posix(), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def write_checksum_manifest(packages: list[Path], target: Path) -> None:
    lines = []
    for package in packages:
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        lines.append(f"{digest}  {package.name}")
    target.write_text("\n".join(lines) + "\n", encoding="ascii")


def zip_tree(root: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, str(Path(root.name) / path.relative_to(root)))


if __name__ == "__main__":
    raise SystemExit(main())

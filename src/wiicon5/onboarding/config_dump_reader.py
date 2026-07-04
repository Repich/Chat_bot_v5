from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


TEXT_SUFFIXES = {".bsl", ".xml", ".json", ".txt", ".md", ".os", ".mdo"}


@dataclass(frozen=True)
class DumpFile:
    path: Path
    relative_path: str
    text: str
    sha256: str


def read_config_dump(root: Path, *, max_file_bytes: int = 2_000_000) -> List[DumpFile]:
    if not root.exists():
        raise FileNotFoundError(f"Config dump path does not exist: {root}")
    files: List[DumpFile] = []
    for path in sorted(iter_source_files(root)):
        if path.stat().st_size > max_file_bytes:
            continue
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        files.append(
            DumpFile(
                path=path,
                relative_path=str(path.relative_to(root)),
                text=text,
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
    return files


def iter_source_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        if is_text_source(root):
            yield root
        return
    for path in root.rglob("*"):
        if path.is_file() and is_text_source(path):
            yield path


def is_text_source(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional


@dataclass(frozen=True)
class Settings:
    llm_api_base: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: float
    mcp_url: str
    mcp_timeout_seconds: float
    skills_dir: Path
    bindings_dir: Path
    runs_dir: Path
    config_fingerprint: str

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None, root: Optional[Path] = None) -> "Settings":
        base = root or Path.cwd()
        values = merged_env(base, env)
        return cls(
            llm_api_base=first_value(values, "WIICON5_LLM_API_BASE", "DEEPSEEK_API_BASE", "WIICON4_LLM_API_BASE"),
            llm_api_key=first_value(values, "WIICON5_LLM_API_KEY", "DEEPSEEK_API_KEY", "WIICON4_LLM_API_KEY"),
            llm_model=first_value(values, "WIICON5_LLM_MODEL", "DEEPSEEK_MODEL", "WIICON4_LLM_MODEL", default="deepseek-chat"),
            llm_timeout_seconds=float(first_value(values, "WIICON5_LLM_TIMEOUT_SECONDS", "WIICON4_LLM_TIMEOUT_SECONDS", default="60")),
            mcp_url=first_value(values, "WIICON5_MCP_URL", "WIICON4_MCP_URL", default="http://127.0.0.1:6003"),
            mcp_timeout_seconds=float(first_value(values, "WIICON5_MCP_TIMEOUT_SECONDS", "WIICON4_MCP_TIMEOUT_SECONDS", default="30")),
            skills_dir=path_from_env(values.get("WIICON5_SKILLS_DIR"), base / "skills"),
            bindings_dir=path_from_env(values.get("WIICON5_BINDINGS_DIR"), base / "skills" / "bindings"),
            runs_dir=path_from_env(values.get("WIICON5_RUNS_DIR"), base / "runs"),
            config_fingerprint=values.get("WIICON5_CONFIG_FINGERPRINT", "local"),
        )

    def validate_for_llm(self) -> None:
        missing = []
        if not self.llm_api_base:
            missing.append("WIICON5_LLM_API_BASE")
        if not self.llm_api_key:
            missing.append("WIICON5_LLM_API_KEY")
        if missing:
            raise ValueError("Missing required LLM settings: " + ", ".join(missing))


def path_from_env(value: Optional[str], default: Path) -> Path:
    if not value:
        return default
    return Path(value).expanduser()


def merged_env(root: Path, explicit_env: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    values = {}
    for path in [root / ".env", root / ".env.local", root / ".env.wiicon5"]:
        values.update(read_env_file(path))
    values.update(os.environ)
    if explicit_env is not None:
        values.update(explicit_env)
    return values


def read_env_file(path: Path) -> Mapping[str, str]:
    if not path.exists():
        return {}
    result = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        result[key] = value
    return result


def first_value(values: Mapping[str, str], *keys: str, default: str = "") -> str:
    for key in keys:
        value = values.get(key)
        if value:
            return value
    return default

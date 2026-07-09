from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Tuple

from wiicon5.bot_instance import BotInstanceConfig, BotInstanceContext


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
    bot_instance: BotInstanceConfig
    bot_context: BotInstanceContext
    admin_enabled: bool = True
    admin_token: str = ""
    admin_bind_local_only: bool = True
    admin_allowed_config_roots: Tuple[Path, ...] = ()
    workbench_allow_raw_query_edit: bool = False
    failure_solver_enabled: bool = False
    failure_solver_provider: str = "openai_compatible"
    failure_solver_api_base: str = ""
    failure_solver_api_key: str = ""
    failure_solver_model: str = "gpt-5.4"
    failure_solver_timeout_seconds: float = 120.0
    failure_solver_codex_command: str = ""
    auto_learned_skills_enabled: bool = True
    auto_learned_skills_activate: bool = True
    auto_learned_skills_scope: str = "bot"
    auto_learned_skills_failure_threshold: int = 3

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None, root: Optional[Path] = None) -> "Settings":
        base = root or Path.cwd()
        values = merged_env(base, env)
        bot_id = values.get("WIICON5_BOT_ID", "local")
        bot_root = path_from_env(values.get("WIICON5_BOT_ROOT"), base / "bot_instances" / bot_id)
        bot_config_path = path_from_env(values.get("WIICON5_BOT_CONFIG"), bot_root / "bot.yaml")
        bot_instance = BotInstanceConfig.from_file(bot_config_path)
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
            bot_instance=bot_instance,
            bot_context=BotInstanceContext(config=bot_instance, root=bot_root),
            admin_enabled=bool_from_env(values.get("WIICON5_ADMIN_ENABLED"), default=True),
            admin_token=values.get("WIICON5_ADMIN_TOKEN", ""),
            admin_bind_local_only=bool_from_env(values.get("WIICON5_ADMIN_BIND_LOCAL_ONLY"), default=True),
            admin_allowed_config_roots=path_list_from_env(
                values.get("WIICON5_ADMIN_ALLOWED_CONFIG_ROOTS"),
                default=(base, Path.home()),
            ),
            workbench_allow_raw_query_edit=bool_from_env(
                values.get("WIICON5_WORKBENCH_ALLOW_RAW_QUERY_EDIT"),
                default=False,
            ),
            failure_solver_enabled=bool_from_env(values.get("WIICON5_FAILURE_SOLVER_ENABLED"), default=False),
            failure_solver_provider=first_value(
                values,
                "WIICON5_FAILURE_SOLVER_PROVIDER",
                default="openai_compatible",
            ),
            failure_solver_api_base=first_value(
                values,
                "WIICON5_FAILURE_SOLVER_API_BASE",
                "OPENAI_API_BASE",
                "OPENAI_BASE_URL",
            ),
            failure_solver_api_key=first_value(
                values,
                "WIICON5_FAILURE_SOLVER_API_KEY",
                "OPENAI_API_KEY",
            ),
            failure_solver_model=first_value(
                values,
                "WIICON5_FAILURE_SOLVER_MODEL",
                default="gpt-5.4",
            ),
            failure_solver_timeout_seconds=float(
                first_value(values, "WIICON5_FAILURE_SOLVER_TIMEOUT_SECONDS", default="120")
            ),
            failure_solver_codex_command=first_value(values, "WIICON5_FAILURE_SOLVER_CODEX_COMMAND"),
            auto_learned_skills_enabled=bool_from_env(
                values.get("WIICON5_AUTO_LEARNED_SKILLS_ENABLED"),
                default=True,
            ),
            auto_learned_skills_activate=bool_from_env(
                values.get("WIICON5_AUTO_LEARNED_SKILLS_ACTIVATE"),
                default=True,
            ),
            auto_learned_skills_scope=first_value(
                values,
                "WIICON5_AUTO_LEARNED_SKILLS_SCOPE",
                default="bot",
            ).strip().lower()
            or "bot",
            auto_learned_skills_failure_threshold=int(
                first_value(values, "WIICON5_AUTO_LEARNED_SKILLS_FAILURE_THRESHOLD", default="3")
            ),
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


def path_list_from_env(value: Optional[str], *, default: Tuple[Path, ...]) -> Tuple[Path, ...]:
    if not value:
        return tuple(default)
    paths = []
    for item in value.split(os.pathsep):
        normalized = item.strip()
        if normalized:
            paths.append(Path(normalized).expanduser())
    return tuple(paths)


def bool_from_env(value: Optional[str], *, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on", "да"}


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

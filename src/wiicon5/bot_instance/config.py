from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


@dataclass(frozen=True)
class InstanceKnowledgeConfig:
    enabled: bool = False
    answer_enabled: bool = True
    source_kind: str = "confluence"
    base_url: str = ""
    root_page_id: str = ""
    space_key: str = ""
    stale_after_days: int = 730
    search_top_k: int = 8
    sync_timeout_seconds: float = 30.0
    max_pages: int = 5000


@dataclass(frozen=True)
class BotInstanceConfig:
    bot_id: str = "local"
    bot_name: str = "WIICON ChatBot 5"
    domain_label: str = "WIICON/WIIC и данные 1С"
    answer_style: str = "business_short"
    forbidden_write_operations: bool = True
    domain_hint_packs: List[str] = field(default_factory=lambda: ["one_c_standard", "trade_ru", "wiicon"])
    general_markers: List[str] = field(default_factory=lambda: default_general_markers())
    data_markers: List[str] = field(default_factory=lambda: default_data_markers())
    weather_markers: List[str] = field(default_factory=lambda: default_weather_markers())
    intro_answer: str = (
        "Я WIICON ChatBot 5, агент для работы с WIICON/WIIC и данными 1С. "
        "Помогаю искать данные через MCP, строить проверяемые навыки и оставляю трассировку действий для разбора ошибок."
    )
    capabilities_answer: str = (
        "Умею отвечать на вопросы по WIICON/WIIC, раскладывать бизнес-вопрос на атомарные навыки, "
        "искать метаданные конфигурации через MCP, строить read-only запросы 1С и сохранять найденные bindings для повторного использования."
    )
    default_general_answer: str = (
        "Я агент WIICON ChatBot 5. Моя зона ответственности - WIICON/WIIC, данные 1С, MCP-запросы, "
        "навыки получения данных и диагностируемые ответы."
    )
    out_of_scope_weather_answer: str = (
        "Это вне моей зоны: я работаю с WIICON/WIIC и данными 1С. По погоде лучше познакомлю с отличным синоптиком."
    )
    out_of_scope_answer: str = "Это вне моей зоны: я работаю с WIICON/WIIC, данными 1С и диагностикой связанных запросов."
    knowledge: InstanceKnowledgeConfig = field(default_factory=InstanceKnowledgeConfig)

    @classmethod
    def default(cls) -> "BotInstanceConfig":
        return cls()

    @classmethod
    def from_file(cls, path: Path) -> "BotInstanceConfig":
        if not path.exists():
            return cls.default()
        return cls.from_mapping(parse_simple_yaml(path.read_text(encoding="utf-8")))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "BotInstanceConfig":
        bot = dict(payload.get("bot") or {})
        baseline = dict(payload.get("baseline") or {})
        answers = dict(payload.get("answers") or {})
        knowledge = dict(payload.get("knowledge") or {})
        return cls(
            bot_id=str(bot.get("id") or "local"),
            bot_name=str(bot.get("name") or "WIICON ChatBot 5"),
            domain_label=str(bot.get("domain_label") or "WIICON/WIIC и данные 1С"),
            answer_style=str(bot.get("answer_style") or "business_short"),
            forbidden_write_operations=as_bool(bot.get("forbidden_write_operations"), default=True),
            domain_hint_packs=as_list(bot.get("domain_hint_packs")) or ["one_c_standard", "trade_ru", "wiicon"],
            general_markers=as_list(baseline.get("general_markers")) or default_general_markers(),
            data_markers=as_list(baseline.get("data_markers")) or default_data_markers(),
            weather_markers=as_list(baseline.get("weather_markers")) or default_weather_markers(),
            intro_answer=str(answers.get("intro") or cls.default().intro_answer),
            capabilities_answer=str(answers.get("capabilities") or cls.default().capabilities_answer),
            default_general_answer=str(answers.get("default_general") or cls.default().default_general_answer),
            out_of_scope_weather_answer=str(
                answers.get("out_of_scope_weather") or cls.default().out_of_scope_weather_answer
            ),
            out_of_scope_answer=str(answers.get("out_of_scope_default") or cls.default().out_of_scope_answer),
            knowledge=InstanceKnowledgeConfig(
                enabled=as_bool(knowledge.get("enabled"), default=False),
                answer_enabled=as_bool(knowledge.get("answer_enabled"), default=True),
                source_kind=str(knowledge.get("source_kind") or "confluence"),
                base_url=str(knowledge.get("base_url") or ""),
                root_page_id=str(knowledge.get("root_page_id") or ""),
                space_key=str(knowledge.get("space_key") or ""),
                stale_after_days=as_int(knowledge.get("stale_after_days"), default=730, minimum=1),
                search_top_k=as_int(knowledge.get("search_top_k"), default=8, minimum=1, maximum=20),
                sync_timeout_seconds=as_float(knowledge.get("sync_timeout_seconds"), default=30.0, minimum=1.0),
                max_pages=as_int(knowledge.get("max_pages"), default=5000, minimum=1),
            ),
        )


@dataclass(frozen=True)
class BotInstanceContext:
    config: BotInstanceConfig
    root: Path


def default_general_markers() -> List[str]:
    return [
        "привет",
        "здравств",
        "добрый день",
        "кто ты",
        "что ты",
        "представься",
        "что умеешь",
        "что можешь",
        "возможности",
    ]


def default_data_markers() -> List[str]:
    return [
        "покажи",
        "найди",
        "сколько",
        "остат",
        "склад",
        "номенклатур",
        "заказ",
        "документ",
        "дебитор",
        "задолж",
        "клиент",
        "поступлен",
        "требован",
    ]


def default_weather_markers() -> List[str]:
    return ["погода", "температура", "дожд", "снег"]


def parse_simple_yaml(text: str) -> Dict[str, Any]:
    """Parse the small bot.yaml subset used by this project.

    The parser intentionally supports only top-level sections, scalar fields,
    and string lists. This avoids adding a YAML dependency to the runtime.
    """

    result: Dict[str, Any] = {}
    current_section = ""
    current_list_key: Optional[str] = None
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not raw_line.startswith(" ") and stripped.endswith(":"):
            current_section = stripped[:-1].strip()
            result.setdefault(current_section, {})
            current_list_key = None
            continue
        if not current_section:
            continue
        section = result.setdefault(current_section, {})
        if stripped.startswith("- ") and current_list_key:
            section.setdefault(current_list_key, []).append(parse_scalar(stripped[2:].strip()))
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            section[key] = []
            current_list_key = key
        else:
            section[key] = parse_scalar(value)
            current_list_key = None
    return result


def parse_scalar(value: str) -> Any:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return value


def as_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "y", "да"}


def as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def as_int(value: Any, *, default: int, minimum: int, maximum: Optional[int] = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(minimum, parsed)
    return min(parsed, maximum) if maximum is not None else parsed


def as_float(value: Any, *, default: float, minimum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)

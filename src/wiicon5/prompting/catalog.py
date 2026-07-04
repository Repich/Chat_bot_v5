from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from wiicon5.bot_instance import BotInstanceConfig


class PromptCatalog:
    def __init__(self, template_root: Optional[Path] = None) -> None:
        self.template_root = template_root or Path(__file__).resolve().parent / "templates"

    def discovery_prompt(self, bot_config: Optional[BotInstanceConfig] = None) -> str:
        return self._compose(["core/discovery.md"], bot_config)

    def query_prompt(self, bot_config: Optional[BotInstanceConfig] = None) -> str:
        config = bot_config or BotInstanceConfig.default()
        paths = ["core/query_synthesis.md", "one_c/query_language_rules.md", "one_c/safety_rules.md"]
        paths.extend(domain_pack_path(pack) for pack in config.domain_hint_packs)
        return self._compose(paths, config)

    def metadata_repair_prompt(self, bot_config: Optional[BotInstanceConfig] = None) -> str:
        config = bot_config or BotInstanceConfig.default()
        paths = ["core/metadata_repair.md"]
        paths.extend(domain_pack_path(pack) for pack in config.domain_hint_packs)
        return self._compose(paths, config)

    def decomposition_prompt(self, bot_config: Optional[BotInstanceConfig] = None) -> str:
        return self._compose(["core/decomposition.md"], bot_config)

    def _compose(self, relative_paths: Iterable[str], bot_config: Optional[BotInstanceConfig]) -> str:
        config = bot_config or BotInstanceConfig.default()
        parts = []
        for relative_path in relative_paths:
            path = self.template_root / relative_path
            if path.exists():
                parts.append(path.read_text(encoding="utf-8").strip())
        return "\n\n".join(parts).format(
            bot_name=config.bot_name,
            domain_label=config.domain_label,
        )


def domain_pack_path(pack_id: str) -> str:
    return f"domain_packs/{pack_id}.md"

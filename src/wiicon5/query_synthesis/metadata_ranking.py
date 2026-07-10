from __future__ import annotations

from typing import List, Optional, Protocol

from wiicon5.bot_instance import BotInstanceConfig
from wiicon5.domain_packs.trade_ru.metadata_ranking import trade_ru_metadata_score
from wiicon5.knowledge.metadata import MetadataObject


class MetadataRankingPolicy(Protocol):
    def score(self, item: MetadataObject, search_terms: List[str]) -> int:
        ...


class NoopMetadataRankingPolicy:
    def score(self, item: MetadataObject, search_terms: List[str]) -> int:
        return 0


class CompositeMetadataRankingPolicy:
    def __init__(self, pack_ids: List[str]) -> None:
        self.pack_ids = list(pack_ids)

    def score(self, item: MetadataObject, search_terms: List[str]) -> int:
        score = 0
        if "trade_ru" in self.pack_ids:
            score += trade_ru_metadata_score(item, search_terms)
        return score

    @classmethod
    def from_bot_config(cls, bot_config: Optional[BotInstanceConfig] = None) -> "CompositeMetadataRankingPolicy":
        config = bot_config or BotInstanceConfig.default()
        return cls(config.domain_hint_packs)

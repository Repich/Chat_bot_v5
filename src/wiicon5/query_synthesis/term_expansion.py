from __future__ import annotations

from typing import Iterable, List, Optional, Protocol

from wiicon5.bot_instance import BotInstanceConfig
from wiicon5.knowledge.semantic_profiles import STOCK_BALANCE_PROFILE


class MetadataTermExpansionPolicy(Protocol):
    def expand(self, terms: List[str]) -> List[str]:
        ...


class NoopTermExpansionPolicy:
    def expand(self, terms: List[str]) -> List[str]:
        return list(terms)


class OneCStandardTermExpansionPolicy:
    def expand(self, terms: List[str]) -> List[str]:
        result = list(terms)
        text = " ".join(terms).lower()
        if "номенклатур" in text:
            add_unique(result, "Справочник.Номенклатура")
        return result


class TradeRuTermExpansionPolicy:
    def expand(self, terms: List[str]) -> List[str]:
        result = list(terms)
        text = " ".join(terms).lower()
        if "остат" in text and any(marker in text for marker in ["товар", "номенклатур", "склад", "магазин"]):
            for term in STOCK_BALANCE_PROFILE.object_terms:
                add_unique(result, term)
            add_unique(result, "регистр накопления")
        if any(marker in text for marker in ["продаж", "прода", "реализац"]):
            add_unique(result, "реализация")
            add_unique(result, "Реализация товаров")
            add_unique(result, "РеализацияТоваровУслуг")
            add_unique(result, "Документ.РеализацияТоваровУслуг")
            add_unique(result, "ВыручкаИСебестоимостьПродаж")
            add_unique(result, "РегистрНакопления.ВыручкаИСебестоимостьПродаж")
        if any(marker in text for marker in ["отгруз", "реализац", "клиент", "дебитор", "задолж", "долж"]):
            add_unique(result, "РасчетыСКлиентами")
            add_unique(result, "Расчеты с клиентами")
            add_unique(result, "РегистрНакопления.РасчетыСКлиентами")
            add_unique(result, "РегистрНакопления.РасчетыСКлиентамиПоДокументам")
        if any(marker in text for marker in ["поставка", "поставк", "поступлен", "поставщик", "приобрет"]):
            add_unique(result, "поступление")
            add_unique(result, "приобретение")
            add_unique(result, "Поступление товаров")
            add_unique(result, "Приобретение товаров")
            add_unique(result, "ПоступлениеТоваровУслуг")
            add_unique(result, "ПриобретениеТоваровУслуг")
            add_unique(result, "Документ.ПриобретениеТоваровУслуг")
            add_unique(result, "РасчетыСПоставщиками")
        return result


class WiiconTermExpansionPolicy:
    def expand(self, terms: List[str]) -> List[str]:
        return list(terms)


class CompositeMetadataTermExpansionPolicy:
    def __init__(self, policies: Iterable[MetadataTermExpansionPolicy]) -> None:
        self.policies = list(policies)

    def expand(self, terms: List[str]) -> List[str]:
        result = list(terms)
        for policy in self.policies:
            result = policy.expand(result)
        return result

    @classmethod
    def from_bot_config(cls, bot_config: Optional[BotInstanceConfig] = None) -> "CompositeMetadataTermExpansionPolicy":
        config = bot_config or BotInstanceConfig.default()
        policies: List[MetadataTermExpansionPolicy] = []
        for pack_id in config.domain_hint_packs:
            if pack_id == "one_c_standard":
                policies.append(OneCStandardTermExpansionPolicy())
            elif pack_id == "trade_ru":
                policies.append(TradeRuTermExpansionPolicy())
            elif pack_id == "wiicon":
                policies.append(WiiconTermExpansionPolicy())
        if not policies:
            policies.append(NoopTermExpansionPolicy())
        return cls(policies)


def add_unique(items: List[str], value: str) -> None:
    normalized = value.strip()
    if normalized and normalized not in items:
        items.append(normalized)

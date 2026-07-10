from __future__ import annotations

from typing import List, Set

from wiicon5.knowledge.metadata import MetadataObject, is_field_confirmed


def trade_ru_metadata_score(item: MetadataObject, search_terms: List[str]) -> int:
    query_text = " ".join(search_terms).lower()
    if not ("остат" in query_text and any(marker in query_text for marker in ["товар", "номенклатур", "склад", "магазин"])):
        return 0
    has_product = metadata_has_field_like(item, ["номенклатур", "товар"], preferred_categories={"dimension"})
    has_warehouse = metadata_has_field_like(item, ["склад", "магазин"], preferred_categories={"dimension", "attribute"})
    has_quantity = metadata_has_field_like(
        item,
        ["количество", "вналичии", "в наличии", "доступно", "остат"],
        preferred_categories={"resource", "attribute"},
        require_numeric=True,
    )
    score = 0
    if has_product:
        score += 25
    if has_warehouse:
        score += 25
    if has_quantity:
        score += 25
    if has_product and has_warehouse:
        score += 80
    if has_product and has_warehouse and has_quantity:
        score += 120
        if item.full_name.startswith("РегистрНакопления."):
            score += 40
        elif item.full_name.startswith("РегистрСведений."):
            score += 20
    return score


def metadata_has_field_like(
    item: MetadataObject,
    terms: List[str],
    *,
    preferred_categories: Set[str],
    require_numeric: bool = False,
) -> bool:
    for field_name, details in item.field_details.items():
        if not is_field_confirmed(details):
            continue
        category = str(details.get("_category") or "")
        if preferred_categories and category not in preferred_categories:
            continue
        values = [
            field_name,
            str(details.get("Имя") or details.get("name") or ""),
            str(details.get("Синоним") or details.get("synonym") or ""),
            str(details.get("Тип") or details.get("type") or ""),
        ]
        compact_text = " ".join(values).replace(" ", "").lower()
        spaced_text = " ".join(values).lower()
        if require_numeric and not any(marker in compact_text for marker in ["число", "number", "numeric"]):
            continue
        if any(term.replace(" ", "").lower() in compact_text or term.lower() in spaced_text for term in terms):
            return True
    return False

from __future__ import annotations

from typing import Any


ROLE_ALIASES = {
    "год": "year",
    "year_filter": "year",
    "дата": "period",
    "date": "period",
    "date_range": "period",
    "период": "period",
    "product_name": "product",
    "product_ref": "product",
    "item": "product",
    "item_name": "product",
    "nomenclature": "product",
    "nomenclature_name": "product",
    "номенклатура": "product",
    "наименование_номенклатуры": "product",
    "товар": "product",
    "товар_наименование": "product",
    "price_kind": "price_type",
    "price_name": "price_type",
    "price_type_name": "price_type",
    "вид_цены": "price_type",
    "видцены": "price_type",
    "тип_цены": "price_type",
}


def canonical_role(value: Any) -> str:
    role = str(value or "").strip().lower()
    return ROLE_ALIASES.get(role, role)


def roles_match(left: Any, right: Any) -> bool:
    return bool(canonical_role(left)) and canonical_role(left) == canonical_role(right)

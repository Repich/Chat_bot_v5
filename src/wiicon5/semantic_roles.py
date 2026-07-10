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

ENTITY_IDENTITY_SUFFIXES = (
    "_name",
    "_ref",
    "_reference",
    "_наименование",
    "_ссылка",
)


def canonical_role(value: Any) -> str:
    role = str(value or "").strip().lower()
    aliased = ROLE_ALIASES.get(role)
    if aliased:
        return aliased
    for suffix in ENTITY_IDENTITY_SUFFIXES:
        if role.endswith(suffix) and len(role) > len(suffix):
            base = role[: -len(suffix)]
            return ROLE_ALIASES.get(base, base)
    return role


def roles_match(left: Any, right: Any) -> bool:
    return bool(canonical_role(left)) and canonical_role(left) == canonical_role(right)

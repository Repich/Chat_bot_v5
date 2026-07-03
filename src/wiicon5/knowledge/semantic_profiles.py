from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class FieldRoleProfile:
    role: str
    terms: List[str]
    required: bool = True
    default: Optional[str] = None
    min_score: float = 0.58
    preferred_categories: List[str] = field(default_factory=list)
    preferred_type_terms: List[str] = field(default_factory=list)
    rejected_type_terms: List[str] = field(default_factory=list)
    rejected_field_terms: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class SemanticRoleProfile:
    semantic_role: str
    object_terms: List[str]
    object_type_terms: List[str] = field(default_factory=list)
    allowed_object_prefixes: List[str] = field(default_factory=list)
    rejected_object_terms: List[str] = field(default_factory=list)
    virtual_table: Optional[str] = None
    alias: str = ""
    field_roles: List[FieldRoleProfile] = field(default_factory=list)


WAREHOUSE_PROFILE = SemanticRoleProfile(
    semantic_role="warehouse",
    object_terms=["склад", "склады", "место хранения", "места хранения", "хранилище"],
    object_type_terms=["справочник", "catalog"],
    allowed_object_prefixes=["Справочник."],
    alias="Склады",
    field_roles=[
        FieldRoleProfile(role="ref", terms=["ссылка", "ref"], required=False, default="Ссылка"),
        FieldRoleProfile(role="name", terms=["наименование", "название", "представление", "name"], default="Наименование"),
        FieldRoleProfile(
            role="city",
            terms=["город", "населенный пункт"],
            required=False,
            min_score=0.85,
            rejected_type_terms=["булево"],
            rejected_field_terms=["использовать", "адресное хранение"],
        ),
        FieldRoleProfile(
            role="warehouse_type",
            terms=["тип склада", "вид склада", "категория склада", "категория", "назначение склада"],
            required=False,
            min_score=0.65,
            preferred_type_terms=["перечисление", "справочникссылка"],
            rejected_field_terms=["цена", "вид цены"],
        ),
    ],
)


STOCK_BALANCE_PROFILE = SemanticRoleProfile(
    semantic_role="stock_balance",
    object_terms=["остатки товаров", "товары на складах", "остатки номенклатуры", "складские остатки", "остатки"],
    object_type_terms=["регистрнакопления", "регистр накопления", "accumulationregister"],
    allowed_object_prefixes=["РегистрНакопления."],
    virtual_table="Остатки",
    alias="Остатки",
    field_roles=[
        FieldRoleProfile(
            role="product",
            terms=["номенклатура", "товар", "продукт", "изделие"],
            preferred_categories=["dimension"],
            preferred_type_terms=["номенклатура"],
        ),
        FieldRoleProfile(
            role="warehouse",
            terms=["склад", "место хранения", "хранилище"],
            preferred_categories=["dimension"],
            preferred_type_terms=["склад"],
        ),
        FieldRoleProfile(
            role="quantity",
            terms=["количество остаток", "количествоостаток", "в наличии", "в наличии остаток", "доступно", "доступно остаток", "остаток"],
            preferred_categories=["resource"],
            preferred_type_terms=["число"],
            rejected_type_terms=["булево"],
        ),
        FieldRoleProfile(
            role="warehouse_name",
            terms=["склад наименование", "место хранения наименование"],
            required=False,
            preferred_categories=["attribute", "dimension"],
            preferred_type_terms=["строка"],
        ),
    ],
)


TRANSFER_DOCUMENT_COUNT_PROFILE = SemanticRoleProfile(
    semantic_role="transfer_document_count",
    object_terms=["перемещение товаров", "перемещения товаров", "товары перемещение"],
    object_type_terms=["документ", "document"],
    allowed_object_prefixes=["Документ."],
    rejected_object_terms=["ордер", "заказ", "распоряжение", "акт"],
    alias="Перемещения",
    field_roles=[
        FieldRoleProfile(role="ref", terms=["ссылка", "ref"], required=False, default="Ссылка"),
        FieldRoleProfile(
            role="date",
            terms=["дата", "период", "date"],
            default="Дата",
            preferred_categories=["attribute", "standard_attribute"],
            preferred_type_terms=["дата"],
        ),
        FieldRoleProfile(
            role="posted",
            terms=["проведен", "проведено"],
            required=False,
            preferred_categories=["attribute", "standard_attribute"],
            preferred_type_terms=["булево"],
        ),
    ],
)


PROFILES_BY_SKILL_ID: Dict[str, SemanticRoleProfile] = {
    "get_warehouses": WAREHOUSE_PROFILE,
    "get_stock_balances": STOCK_BALANCE_PROFILE,
    "count_transfer_documents_by_day": TRANSFER_DOCUMENT_COUNT_PROFILE,
}


def profile_for_skill(skill_id: str) -> Optional[SemanticRoleProfile]:
    return PROFILES_BY_SKILL_ID.get(skill_id)

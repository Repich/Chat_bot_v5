from __future__ import annotations

from wiicon5.models import SkillBinding


def custom_warehouse_binding() -> SkillBinding:
    return SkillBinding(
        skill_id="get_warehouses",
        config_fingerprint="cfg_custom",
        semantic_role="warehouse",
        one_c_object={"full_name": "Справочник.МестаХранения", "alias": "Места"},
        fields={
            "ref": "Ссылка",
            "name": "Название",
            "warehouse_type": "Категория",
            "city": "Город",
        },
        confidence=0.92,
        evidence=["unit-test"],
    )


def custom_stock_binding() -> SkillBinding:
    return SkillBinding(
        skill_id="get_stock_balances",
        config_fingerprint="cfg_custom",
        semantic_role="stock_balance",
        one_c_object={
            "full_name": "РегистрНакопления.ОстаткиТоваров",
            "virtual_table": "Остатки",
            "alias": "Остатки",
        },
        fields={
            "product": "Товар",
            "warehouse": "МестоХранения",
            "quantity": "ДоступноОстаток",
            "warehouse_name": "МестоХранения.Наименование",
        },
        confidence=0.88,
        evidence=["unit-test"],
    )


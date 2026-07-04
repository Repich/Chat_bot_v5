from __future__ import annotations

from typing import Dict, Iterable, List

from wiicon5.onboarding.metadata_index_builder import IndexedObject


ROLE_KEYWORDS = {
    "warehouse": ["склад", "местахранения"],
    "product": ["номенклатура", "товар"],
    "stock_balance": ["остат", "товарынаскладах"],
    "customer_settlement": ["расчет", "клиент", "дебитор"],
    "supplier_settlement": ["расчет", "поставщик"],
    "sales_document": ["реализация", "продажа", "отгруз"],
    "purchase_document": ["приобретение", "поступление", "поставка"],
}


def generate_binding_candidates(objects: Iterable[IndexedObject]) -> List[Dict[str, object]]:
    candidates: List[Dict[str, object]] = []
    for item in objects:
        normalized = item.full_name.replace(".", "").replace("_", "").lower()
        for role, keywords in ROLE_KEYWORDS.items():
            matched = [keyword for keyword in keywords if keyword in normalized]
            if not matched:
                continue
            candidates.append(
                {
                    "semantic_role": role,
                    "object": item.full_name,
                    "confidence": min(0.9, 0.35 + 0.15 * len(matched)),
                    "evidence": [f"name_contains:{keyword}" for keyword in matched],
                    "status": "candidate",
                }
            )
    return candidates

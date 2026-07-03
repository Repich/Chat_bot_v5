from __future__ import annotations

from typing import Any


PLACEHOLDER_PREFIXES = (
    "context_",
    "all_",
    "selected_",
    "previous_",
    "from ",
)

PLACEHOLDER_VALUES = {
    "context product",
    "context_product",
    "all warehouses",
    "all_warehouses",
    "from warehouses",
    "previous product",
    "previous_product",
    "selected product",
    "selected_product",
    "unknown",
    "not specified",
    "not_specified",
    "неизвестно",
    "не указан",
    "не_указан",
}


def is_unresolved_placeholder_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = " ".join(value.strip().lower().split())
    compact = normalized.replace(" ", "_")
    return (
        normalized in PLACEHOLDER_VALUES
        or compact in PLACEHOLDER_VALUES
        or any(normalized.startswith(prefix) or compact.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)
    )

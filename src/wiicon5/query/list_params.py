from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping


@dataclass(frozen=True)
class ListParameterExpansion:
    query: str
    params: Dict[str, Any]
    changed: bool = False
    expansions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "changed": self.changed,
            "query": self.query,
            "params": dict(self.params),
            "expansions": list(self.expansions),
        }


def expand_in_list_parameters(query: str, params: Mapping[str, Any]) -> ListParameterExpansion:
    new_params: Dict[str, Any] = dict(params)
    expansions: List[Dict[str, Any]] = []

    def replace(match: re.Match[str]) -> str:
        param_name = match.group("param")
        value = new_params.get(param_name)
        if not isinstance(value, list) or not value:
            return match.group(0)
        scalar_names = []
        for index, item in enumerate(value, start=1):
            scalar_name = unique_param_name(new_params, f"{param_name}_{index}")
            new_params[scalar_name] = item
            scalar_names.append(scalar_name)
        expansions.append(
            {
                "param": param_name,
                "count": len(value),
                "scalar_params": list(scalar_names),
            }
        )
        return "В (" + ", ".join("&" + name for name in scalar_names) + ")"

    new_query = re.sub(
        r"\bВ\s*\(\s*&(?P<param>[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)\s*\)",
        replace,
        query,
        flags=re.IGNORECASE,
    )
    used_params = set(re.findall(r"&([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)", new_query))
    for expansion in expansions:
        original = expansion["param"]
        if original not in used_params:
            new_params.pop(original, None)
    return ListParameterExpansion(
        query=new_query,
        params=new_params,
        changed=new_query != query or new_params != dict(params),
        expansions=expansions,
    )


def unique_param_name(params: Mapping[str, Any], base: str) -> str:
    if base not in params:
        return base
    index = 2
    while f"{base}_{index}" in params:
        index += 1
    return f"{base}_{index}"

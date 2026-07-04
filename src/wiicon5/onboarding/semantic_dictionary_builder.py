from __future__ import annotations

import re
from typing import Dict, Iterable, List

from wiicon5.onboarding.metadata_index_builder import IndexedObject


def build_semantic_dictionary(objects: Iterable[IndexedObject]) -> Dict[str, List[str]]:
    dictionary: Dict[str, List[str]] = {}
    for item in objects:
        for token in semantic_tokens(item.full_name):
            dictionary.setdefault(token, [])
            if item.full_name not in dictionary[token]:
                dictionary[token].append(item.full_name)
    return dict(sorted(dictionary.items()))


def semantic_tokens(text: str) -> List[str]:
    raw = re.sub(r"([a-zа-яё])([A-ZА-ЯЁ])", r"\1 \2", text.replace(".", " "))
    tokens: List[str] = []
    for token in re.split(r"[^0-9A-Za-zА-Яа-яЁё]+", raw.lower()):
        if len(token) >= 4 and token not in tokens:
            tokens.append(token)
    return tokens

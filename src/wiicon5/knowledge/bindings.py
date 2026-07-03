from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from wiicon5.conversation.context import ConversationContext
from wiicon5.models import SkillBinding, SkillContract


DEFAULT_CONFIG_FINGERPRINT = "default"


class BindingError(Exception):
    pass


class BindingNotFound(BindingError):
    pass


class BindingStore(ABC):
    @abstractmethod
    def get(self, skill_id: str, config_fingerprint: str) -> Optional[SkillBinding]:
        raise NotImplementedError

    @abstractmethod
    def put(self, binding: SkillBinding) -> None:
        raise NotImplementedError

    @abstractmethod
    def all(self) -> List[SkillBinding]:
        raise NotImplementedError


class InMemoryBindingStore(BindingStore):
    def __init__(self, bindings: Iterable[SkillBinding] = ()) -> None:
        self._bindings: Dict[Tuple[str, str], SkillBinding] = {}
        for binding in bindings:
            self.put(binding)

    def get(self, skill_id: str, config_fingerprint: str) -> Optional[SkillBinding]:
        return self._bindings.get((skill_id, config_fingerprint))

    def put(self, binding: SkillBinding) -> None:
        self._bindings[(binding.skill_id, binding.config_fingerprint)] = binding

    def all(self) -> List[SkillBinding]:
        return list(self._bindings.values())


class JsonBindingStore(BindingStore):
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, skill_id: str, config_fingerprint: str) -> Optional[SkillBinding]:
        path = self._path(skill_id, config_fingerprint)
        if not path.exists():
            return None
        return SkillBinding.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def put(self, binding: SkillBinding) -> None:
        path = self._path(binding.skill_id, binding.config_fingerprint)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(binding.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def all(self) -> List[SkillBinding]:
        bindings: List[SkillBinding] = []
        for path in sorted(self.root.rglob("*.json")):
            bindings.append(SkillBinding.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        return bindings

    def _path(self, skill_id: str, config_fingerprint: str) -> Path:
        return self.root / config_fingerprint / f"{skill_id}.binding.json"


class BindingDiscoverer(ABC):
    @abstractmethod
    def discover(self, skill: SkillContract, context: ConversationContext) -> Optional[SkillBinding]:
        raise NotImplementedError


class BindingResolver:
    def __init__(self, store: BindingStore, discoverer: Optional[BindingDiscoverer] = None) -> None:
        self.store = store
        self.discoverer = discoverer

    def resolve(self, skill: SkillContract, context: ConversationContext) -> SkillBinding:
        config_fingerprint = context.config_fingerprint or DEFAULT_CONFIG_FINGERPRINT
        binding = self.store.get(skill.skill_id, config_fingerprint)
        if binding is not None:
            return binding
        if self.discoverer is not None:
            discovered = self.discoverer.discover(skill, context)
            if discovered is not None:
                self.store.put(discovered)
                return discovered
        raise BindingNotFound(f"No binding for skill {skill.skill_id} and config {config_fingerprint}.")


class ScriptedBindingDiscoverer(BindingDiscoverer):
    def __init__(self, bindings: Dict[str, SkillBinding]) -> None:
        self.bindings = dict(bindings)
        self.calls: List[str] = []

    def discover(self, skill: SkillContract, context: ConversationContext) -> Optional[SkillBinding]:
        self.calls.append(skill.skill_id)
        return self.bindings.get(skill.skill_id)


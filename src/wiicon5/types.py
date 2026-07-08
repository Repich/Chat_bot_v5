from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set


DEFAULT_TYPE_PARENTS: Dict[str, List[str]] = {
    "ProductRef": ["EntityRef"],
    "WarehouseRef": ["EntityRef"],
    "CounterpartyRef": ["EntityRef"],
    "DocumentRef": ["EntityRef"],
    "ProductRefList": ["EntityRefList"],
    "WarehouseRefList": ["EntityRefList"],
    "DocumentRefList": ["EntityRefList"],
    "StockBalanceTable": ["TypedTable"],
    "DebtBalanceTable": ["TypedTable"],
    "AggregateTable": ["TypedTable"],
    "CountResult": ["AggregateTable"],
    "DocumentCountByPeriodTable": ["TypedTable"],
    "DocumentLineTable": ["TypedTable"],
    "DocumentListTable": ["TypedTable"],
    "TopNMetricTable": ["AggregateTable"],
    "PriceTable": ["TypedTable"],
    "LearnedLookupTable": ["TypedTable"],
    "WorkbenchLookupTable": ["TypedTable"],
    "WorkbenchQueryResultTable": ["TypedTable"],
    "UserAnswer": ["Answer"],
}

ABSTRACT_ARTIFACT_TYPES = {
    "Answer",
    "EntityRef",
    "EntityRefList",
    "TypedTable",
}

TECHNICAL_PORT_TYPES = {
    "Integer",
    "SemanticFilterList",
    "String",
}


class TypeSystem:
    def __init__(self, parents: Optional[Dict[str, Iterable[str]]] = None) -> None:
        self.parents = {key: list(value) for key, value in (parents or DEFAULT_TYPE_PARENTS).items()}

    def is_assignable(self, source_type: str, target_type: str) -> bool:
        if source_type == target_type:
            return True
        if target_type == "TypedTable" and source_type.endswith("Table") and source_type != "TypedTable":
            return True
        if target_type == "EntityRefList" and source_type.endswith("RefList") and source_type != "EntityRefList":
            return True
        if target_type == "EntityRef" and source_type.endswith("Ref") and source_type != "EntityRef":
            return True
        return target_type in self.ancestors(source_type)

    def is_abstract_artifact_type(self, artifact_type: str) -> bool:
        return artifact_type in ABSTRACT_ARTIFACT_TYPES

    def is_technical_port_type(self, artifact_type: str) -> bool:
        return artifact_type in TECHNICAL_PORT_TYPES

    def concrete_artifact_types(self) -> Set[str]:
        return {
            artifact_type
            for artifact_type in self.parents
            if not self.is_abstract_artifact_type(artifact_type) and not self.is_technical_port_type(artifact_type)
        }

    def ancestors(self, source_type: str) -> Set[str]:
        result: Set[str] = set()
        stack = list(self.parents.get(source_type, []))
        while stack:
            current = stack.pop()
            if current in result:
                continue
            result.add(current)
            stack.extend(self.parents.get(current, []))
        return result

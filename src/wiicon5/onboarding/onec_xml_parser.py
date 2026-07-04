from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional


KIND_BY_XML_TAG = {
    "Catalog": "Справочник",
    "Document": "Документ",
    "AccumulationRegister": "РегистрНакопления",
    "InformationRegister": "РегистрСведений",
    "Enum": "Перечисление",
}

CATEGORY_BY_XML_TAG = {
    "Attribute": "attribute",
    "Dimension": "dimension",
    "Resource": "resource",
    "TabularSection": "table_part",
}

STANDARD_FIELDS_BY_KIND = {
    "Справочник": ["Ссылка", "Наименование", "Код", "ПометкаУдаления", "ЭтоГруппа", "Родитель", "Владелец"],
    "Документ": ["Ссылка", "Номер", "Дата", "Проведен", "ПометкаУдаления"],
}


@dataclass(frozen=True)
class ParsedXmlField:
    name: str
    category: str
    synonym: str = ""
    type_text: str = ""
    nested_fields: List["ParsedXmlField"] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedXmlObject:
    full_name: str
    kind: str
    synonym: str = ""
    fields: List[ParsedXmlField] = field(default_factory=list)


def parse_metadata_xml(text: str, *, relative_path: str = "") -> Optional[ParsedXmlObject]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    metadata_node = first_metadata_node(root)
    if metadata_node is None:
        return None
    xml_tag = local_name(metadata_node.tag)
    kind = KIND_BY_XML_TAG.get(xml_tag)
    if not kind:
        return None
    properties = direct_child(metadata_node, "Properties")
    object_name = property_text(properties, "Name") if properties is not None else ""
    if not object_name:
        object_name = object_name_from_path(relative_path)
    if not object_name:
        return None
    fields: List[ParsedXmlField] = []
    for standard_name in STANDARD_FIELDS_BY_KIND.get(kind, []):
        fields.append(ParsedXmlField(name=standard_name, category="standard_attribute"))
    child_objects = direct_child(metadata_node, "ChildObjects")
    if child_objects is not None:
        fields.extend(parse_child_objects(child_objects))
    return ParsedXmlObject(
        full_name=f"{kind}.{object_name}",
        kind=kind,
        synonym=property_text(properties, "Synonym") if properties is not None else "",
        fields=deduplicate_fields(fields),
    )


def first_metadata_node(root: ET.Element) -> Optional[ET.Element]:
    if local_name(root.tag) in KIND_BY_XML_TAG:
        return root
    for child in list(root):
        if local_name(child.tag) in KIND_BY_XML_TAG:
            return child
    return None


def parse_child_objects(child_objects: ET.Element) -> List[ParsedXmlField]:
    fields: List[ParsedXmlField] = []
    for child in list(child_objects):
        xml_tag = local_name(child.tag)
        category = CATEGORY_BY_XML_TAG.get(xml_tag)
        if not category:
            continue
        properties = direct_child(child, "Properties")
        if properties is None:
            continue
        name = property_text(properties, "Name")
        if not name:
            continue
        nested: List[ParsedXmlField] = []
        if category == "table_part":
            nested_child_objects = direct_child(child, "ChildObjects")
            if nested_child_objects is not None:
                nested = [
                    item
                    for item in parse_child_objects(nested_child_objects)
                    if item.category in {"attribute", "standard_attribute"}
                ]
        fields.append(
            ParsedXmlField(
                name=name,
                category=category,
                synonym=property_text(properties, "Synonym"),
                type_text=normalize_type_text(property_text(properties, "Type")),
                nested_fields=deduplicate_fields(nested),
            )
        )
    return deduplicate_fields(fields)


def deduplicate_fields(fields: List[ParsedXmlField]) -> List[ParsedXmlField]:
    result: List[ParsedXmlField] = []
    seen = set()
    for item in fields:
        if item.name in seen:
            continue
        seen.add(item.name)
        result.append(item)
    return result


def direct_child(element: ET.Element, name: str) -> Optional[ET.Element]:
    for child in list(element):
        if local_name(child.tag) == name:
            return child
    return None


def property_text(properties: Optional[ET.Element], name: str) -> str:
    if properties is None:
        return ""
    child = direct_child(properties, name)
    if child is None:
        return ""
    return localized_text(child)


def localized_text(element: ET.Element) -> str:
    for child in element.iter():
        if local_name(child.tag) == "content" and child.text and child.text.strip():
            return normalize_whitespace(child.text)
    return normalize_whitespace(" ".join(element.itertext()))


def normalize_type_text(value: str) -> str:
    if not value:
        return ""
    replacements = [
        (r"cfg:CatalogRef\.([A-Za-zА-Яа-яЁё0-9_]+)", r"СправочникСсылка.\1"),
        (r"cfg:DocumentRef\.([A-Za-zА-Яа-яЁё0-9_]+)", r"ДокументСсылка.\1"),
        (r"cfg:EnumRef\.([A-Za-zА-Яа-яЁё0-9_]+)", r"ПеречислениеСсылка.\1"),
        (r"cfg:ChartOfCharacteristicTypesRef\.([A-Za-zА-Яа-яЁё0-9_]+)", r"ПланВидовХарактеристикСсылка.\1"),
        (r"cfg:ChartOfAccountsRef\.([A-Za-zА-Яа-яЁё0-9_]+)", r"ПланСчетовСсылка.\1"),
        (r"cfg:ChartOfCalculationTypesRef\.([A-Za-zА-Яа-яЁё0-9_]+)", r"ПланВидовРасчетаСсылка.\1"),
        (r"cfg:DefinedType\.([A-Za-zА-Яа-яЁё0-9_]+)", r"ОпределяемыйТип.\1"),
        (r"\bxs:string\b", "Строка"),
        (r"\bxs:boolean\b", "Булево"),
        (r"\bxs:dateTime\b", "Дата"),
        (r"\bxs:decimal\b", "Число"),
        (r"\bxs:int\b", "Число"),
        (r"\bxs:long\b", "Число"),
    ]
    result = value
    for pattern, repl in replacements:
        result = re.sub(pattern, repl, result)
    return normalize_whitespace(result)


def object_name_from_path(relative_path: str) -> str:
    if not relative_path:
        return ""
    part = relative_path.split("/")[-1]
    return part.rsplit(".", 1)[0] if "." in part else part


def local_name(tag: str) -> str:
    return tag.split("}", 1)[-1]


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())

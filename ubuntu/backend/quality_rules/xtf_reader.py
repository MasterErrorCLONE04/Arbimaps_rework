from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable


TARGET_CLASSES = {
    # ILC
    "ILC_Predio",
    "ILC_DatosAdicionalesLevantamientoCatastral",

    # ARB capas principales
    "ARB_MarcaPredial",
    "ARB_Direccion",
    "ARB_Dirección",
    "ARB_PuntoReferencia",
    "ARB_UnidadConstruccion",
    "ARB_Construccion",
    "ARB_TerrenoHistorico",
    "ARB_Terreno",

    # ARB tablas
    "ARB_Tramite",
    "ARB_ReferenciaRegistralSistemaAntiguoValor",
    "ARB_Predio",
    "ARB_NovedadNumeroPredialValor",
    "ARB_NovedadFMIValor",
    "ARB_InformacionPH",
    "ARB_DerechoInteresadoFuente",
    "ARB_DerechoTipo",
    "ARB_CaracteristicasUnidadConstruccion",
    "ARB_AvaluoValor",
    "ARB_PredioTipo",
    "ARB_AdjuntoUnidadConstruccion",
    "ARB_AdjuntoTerreno",
    "ARB_AdjuntoPuntoReferencia",
    "ARB_AdjuntoInteresado",
    "ARB_AdjuntoFuenteAdministrativa",

    # Catálogos / apoyo
    "ARB_CondicionPredioTipo",
    "ARB_Predio_Novedad_Numero_Predial",

    # variantes minúsculas
    "ilc_predio",
    "ilc_datosadicionaleslevantamientocatastral",

    "arb_marcapredial",
    "arb_direccion",
    "arb_dirección",
    "arb_puntoreferencia",
    "arb_unidadconstruccion",
    "arb_construccion",
    "arb_terrenohistorico",
    "arb_terreno",

    "arb_tramite",
    "arb_referenciaregistralsistemaantiguovalor",
    "arb_predio",
    "arb_novedadnumeropredialvalor",
    "arb_novedadfmivalor",
    "arb_informacionph",
    "arb_derechointeresadofuente",
    "arb_derechotipo",
    "arb_caracteristicasunidadconstruccion",
    "arb_avaluovalor",
    "arb_prediotipo",
    "arb_adjuntounidadconstruccion",
    "arb_adjuntoterreno",
    "arb_adjuntopuntoreferencia",
    "arb_adjuntointeresado",
    "arb_adjuntofuenteadministrativa",

    "arb_condicionprediotipo",
    "arb_predio_novedad_numero_predial",
}


ALIASES_BY_NORMALIZED = {
    # Dirección
    "arbdireccion": "ARB_Direccion",
    "arbdirección": "ARB_Direccion",
    "cdireccion": "ARB_Direccion",

    # Capas físicas / geográficas
    "arbmarcapredial": "ARB_MarcaPredial",
    "arbpuntoreferencia": "ARB_PuntoReferencia",
    "arbunidadconstruccion": "ARB_UnidadConstruccion",
    "dunidaddeconstruccion": "ARB_UnidadConstruccion",
    "unidaddeconstruccion": "ARB_UnidadConstruccion",
    "arbconstruccion": "ARB_Construccion",
    "arbterrenohistorico": "ARB_TerrenoHistorico",
    "arbterreno": "ARB_Terreno",
    "eterreno": "ARB_Terreno",
    "terreno": "ARB_Terreno",

    # Tablas ARB
    "arbtramite": "ARB_Tramite",
    "arbreferenciaregistralsistemaantiguovalor": "ARB_ReferenciaRegistralSistemaAntiguoValor",
    "arbpredio": "ARB_Predio",
    "arbnovedadnumeropredialvalor": "ARB_NovedadNumeroPredialValor",
    "arbnovedadfmivalor": "ARB_NovedadFMIValor",
    "arbinformacionph": "ARB_InformacionPH",
    "arbderechointeresadofuente": "ARB_DerechoInteresadoFuente",
    "derechointeresadofuente": "ARB_DerechoInteresadoFuente",
    "arbderechotipo": "ARB_DerechoTipo",
    "arbcaracteristicasunidadconstruccion": "ARB_CaracteristicasUnidadConstruccion",
    "arbavaluovalor": "ARB_AvaluoValor",
    "arbprediotipo": "ARB_PredioTipo",
    "apredio": "ARB_Predio",

    # Adjuntos
    "arbadjuntounidadconstruccion": "ARB_AdjuntoUnidadConstruccion",
    "arbadjuntoterreno": "ARB_AdjuntoTerreno",
    "arbadjuntopuntoreferencia": "ARB_AdjuntoPuntoReferencia",
    "arbadjuntointeresado": "ARB_AdjuntoInteresado",
    "arbadjuntofuenteadministrativa": "ARB_AdjuntoFuenteAdministrativa",

    # Catálogos / apoyo
    "arbcondicionprediotipo": "ARB_CondicionPredioTipo",
    "arbpredionovedadnumeropredial": "ARB_Predio_Novedad_Numero_Predial",

    # ILC
    "ilcpredio": "ILC_Predio",
    "ilcdatosadicionaleslevantamientocatastral": "ILC_DatosAdicionalesLevantamientoCatastral",
}


def _normalize_text(value: str) -> str:
    return (
        str(value)
        .strip()
        .lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )


def _normalize_key(value: str) -> str:
    text = _normalize_text(value)
    return "".join(ch for ch in text if ch.isalnum())


def _clean_tag(tag: str) -> str:
    if "}" in tag:
        tag = tag.split("}", 1)[1]
    if "." in tag:
        tag = tag.split(".")[-1]
    return tag.strip()


def _canonical_class_name(name: str) -> str:
    raw = _clean_tag(name)
    normalized = _normalize_key(raw)
    return ALIASES_BY_NORMALIZED.get(normalized, raw)


def _build_allowed_class_map(class_names: Iterable[str]) -> dict[str, str]:
    allowed: dict[str, str] = {}

    for name in class_names:
        canonical = _canonical_class_name(name)
        normalized_original = _normalize_key(_clean_tag(name))
        normalized_canonical = _normalize_key(canonical)

        allowed[normalized_original] = canonical
        allowed[normalized_canonical] = canonical

    for normalized, canonical in ALIASES_BY_NORMALIZED.items():
        if canonical in class_names or canonical in allowed.values():
            allowed[normalized] = canonical

    return allowed


def _extract_text_recursive(node: ET.Element) -> str:
    """
    Extrae el primer valor útil encontrado en un nodo XML:
    1. texto directo del nodo
    2. atributo REF/ref
    3. texto o REF de hijos recursivamente
    """
    text = (node.text or "").strip()
    if text:
        return text

    ref = node.attrib.get("REF") or node.attrib.get("ref")
    if ref:
        return str(ref).strip()

    for child in node:
        value = _extract_text_recursive(child)
        if value:
            return value

    return ""


def parse_xtf_tables(
    path: Path,
    class_names: Iterable[str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """
    Lee un XTF y devuelve un diccionario:
        {
            "ARB_Predio": [{...}, {...}],
            "ARB_Construccion": [{...}],
            ...
        }

    Soporta:
    - mayúsculas/minúsculas
    - tildes
    - Dirección/Direccion
    - tags con namespace o prefijo de modelo
    - valores anidados en hijos XML
    - referencias REF/ref
    """
    selected_classes = set(class_names or TARGET_CLASSES)
    allowed_classes = _build_allowed_class_map(selected_classes)

    tables: dict[str, list[dict[str, str]]] = {}

    tree = ET.parse(path)
    root = tree.getroot()
    parents = {id(child): parent for parent in root.iter() for child in parent}

    for element in root.iter():
        raw_class_name = _clean_tag(element.tag)
        normalized_class_name = _normalize_key(raw_class_name)

        canonical_class_name = allowed_classes.get(normalized_class_name)
        if not canonical_class_name:
            continue

        record: dict[str, str] = {}

        # atributos del nodo principal
        for key, value in element.attrib.items():
            record[_clean_tag(key)] = str(value).strip()

        # hijos del nodo principal
        for child in element:
            child_key = _clean_tag(child.tag)

            if _is_geometry_node(child):
                value = _node_to_xml(child)
            else:
                value = _extract_text_recursive(child)

            if value:
                record[child_key] = value

        if canonical_class_name == "ARB_Direccion":
            predio_ref = _find_parent_ref(element, parents, "ARB_Predio", allowed_classes)
            if predio_ref:
                record.setdefault("predio", predio_ref)
                record.setdefault("arb_predio_direccion", predio_ref)

        tables.setdefault(canonical_class_name, []).append(record)

    return {name: rows for name, rows in tables.items() if rows}

def _is_geometry_node(node: ET.Element) -> bool:
    key = _normalize_key(_clean_tag(node.tag))
    return key in {"geometria", "geometry", "geom", "localizacion"}


def _node_to_xml(node: ET.Element) -> str:
    return ET.tostring(node, encoding="unicode")


def _find_parent_ref(
    element: ET.Element,
    parents: dict[int, ET.Element],
    canonical_parent: str,
    allowed_classes: dict[str, str],
) -> str:
    parent = parents.get(id(element))
    while parent is not None:
        raw_class_name = _clean_tag(parent.tag)
        normalized_class_name = _normalize_key(raw_class_name)
        if allowed_classes.get(normalized_class_name) == canonical_parent:
            ref = parent.attrib.get("TID") or parent.attrib.get("t_id") or parent.attrib.get("id")
            return str(ref).strip() if ref else ""
        parent = parents.get(id(parent))
    return ""

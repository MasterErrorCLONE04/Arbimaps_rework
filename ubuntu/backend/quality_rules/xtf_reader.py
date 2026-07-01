from __future__ import annotations

import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable


TARGET_CLASSES = {
    # ILC
    "ILC_Predio",
    "ILC_DatosAdicionalesLevantamientoCatastral",
    "ILC_CaracteristicasUnidadConstruccion",
    "ILC_UnidadConstruccion",
    "ILC_EstructuraAvaluo",

    # ARB capas principales
    "ARB_MarcaPredial",
    "ARB_Marca",
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
    "CCA_AvaluoValor",
    "ARB_PredioTipo",
    "CUC_TipologiaConstruccion",
    "CUC_TipologiaNoConvencional",
    "CUC_CalificacionConvencional",
    "cuc_calificacion_unidadconstruccion",
    "ARB_AdjuntoUnidadConstruccion",
    "ARB_AdjuntoTerreno",
    "ARB_AdjuntoPuntoReferencia",
    "ARB_AdjuntoInteresado",
    "ARB_AdjuntoFuenteAdministrativa",

    # Catálogos / apoyo
    "ARB_CondicionPredioTipo",
    "ARB_NovedadNumeroPredialTipo",
    "ARB_ConstruccionPlantaTipo",
    "ARB_UnidadConstruccionTipo",
    "ARB_TipologiaTipo",
    "ARB_Predio_Novedad_Numero_Predial",
    "ARB_Predio_Derecho",
    "ARB_Predio_Terreno",
    "ARB_Predio_Construccion",

    # variantes minúsculas
    "ilc_predio",
    "ilc_datosadicionaleslevantamientocatastral",
    "ilc_caracteristicasunidadconstruccion",
    "ilc_unidadconstruccion",
    "ilc_estructuraavaluo",

    "arb_marcapredial",
    "arb_marca",
    "arb_direccion",
    "arb_dirección",
    "arb_puntoreferencia",
    "arb_unidadconstruccion",
    "arb_construccion",
    "arb_construccion_unidadconstruccion",
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
    "cca_avaluovalor",
    "arb_prediotipo",
    "cuc_tipologiaconstruccion",
    "cuc_tipologianoconvencional",
    "cuc_calificacionconvencional",
    "cuc_calificacion_unidadconstruccion",
    "arb_adjuntounidadconstruccion",
    "arb_adjuntoterreno",
    "arb_adjuntopuntoreferencia",
    "arb_adjuntointeresado",
    "arb_adjuntofuenteadministrativa",

    "arb_condicionprediotipo",
    "arb_novedadnumeropredialtipo",
    "arb_construccionplantatipo",
    "arb_unidadconstrucciontipo",
    "arb_tipologiatipo",
    "arb_predio_novedad_numero_predial",
    "arb_predio_derecho",
    "arb_predio_terreno",
    "arb_predio_construccion",
}


ALIASES_BY_NORMALIZED = {
    # Dirección
    "arbdireccion": "ARB_Direccion",
    "arbdirección": "ARB_Direccion",
    "cdireccion": "ARB_Direccion",

    # Capas físicas / geográficas
    "arbmarcapredial": "ARB_MarcaPredial",
    "arbmarca": "ARB_MarcaPredial",
    "arbpuntoreferencia": "ARB_PuntoReferencia",
    "arbunidadconstruccion": "ARB_UnidadConstruccion",
    "dunidaddeconstruccion": "ARB_UnidadConstruccion",
    "dunidadconstruccion": "ARB_UnidadConstruccion",
    "unidaddeconstruccion": "ARB_UnidadConstruccion",
    "unidadconstruccion": "ARB_UnidadConstruccion",
    "arbconstruccion": "ARB_Construccion",
    "arbconstruccionunidadconstruccion": "ARB_Construccion_UnidadConstruccion",
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
    "ccavaluovalor": "CCA_AvaluoValor",
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
    "arbnovedadnumeropredialtipo": "ARB_NovedadNumeroPredialTipo",
    "arbconstruccionplantatipo": "ARB_ConstruccionPlantaTipo",
    "arbunidadconstrucciontipo": "ARB_UnidadConstruccionTipo",
    "arbtipologiatipo": "ARB_TipologiaTipo",
    "arbpredionovedadnumeropredial": "ARB_Predio_Novedad_Numero_Predial",
    "arbpredioderecho": "arb_predio_derecho",
    "arbpredioterreno": "arb_predio_terreno",
    "arbpredioconstruccion": "arb_predio_construccion",

    # ILC
    "ilcpredio": "ILC_Predio",
    "ilcdatosadicionaleslevantamientocatastral": "ILC_DatosAdicionalesLevantamientoCatastral",
    "ilccaracteristicasunidadconstruccion": "ILC_CaracteristicasUnidadConstruccion",
    "ilcunidadconstruccion": "ILC_UnidadConstruccion",
    "ilcestructuraavaluo": "ILC_EstructuraAvaluo",

    # CUC
    "cuctipologiaconstruccion": "CUC_TipologiaConstruccion",
    "cuctipologianoconvencional": "CUC_TipologiaNoConvencional",
    "cuccalificacionconvencional": "CUC_CalificacionConvencional",
    "cuccalificacionunidadconstruccion": "cuc_calificacion_unidadconstruccion",
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
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
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

        predio_relation_fields = {
            "ARB_Direccion": "arb_predio_direccion",
            "ARB_NovedadNumeroPredialValor": "arb_predio_novedad_numero_predial",
            "ARB_MarcaPredial": "arb_predio_marca",
            "ARB_Terreno": "arb_predio_terreno",
            "ARB_DerechoInteresadoFuente": "arb_predio_derecho",
            "ARB_Construccion": "arb_predio_construccion",
            "ARB_AvaluoValor": "arb_predio_avaluo",
            "CCA_AvaluoValor": "cca_predio_avaluo",
            "ILC_EstructuraAvaluo": "ilc_predio_avaluo",
        }

        predio_relation_field = predio_relation_fields.get(canonical_class_name)
        if predio_relation_field:
            predio_ref = (
                _find_parent_ref(element, parents, "ARB_Predio", allowed_classes)
                or _find_parent_ref(element, parents, "ILC_Predio", allowed_classes)
            )
            if predio_ref:
                record.setdefault("predio", predio_ref)
                record.setdefault(predio_relation_field, predio_ref)

        if canonical_class_name == "ARB_UnidadConstruccion":
            construccion_ref = _find_parent_ref(element, parents, "ARB_Construccion", allowed_classes)
            if construccion_ref:
                record.setdefault("construccion", construccion_ref)
                record.setdefault("arb_construccion_unidadconstruccion", construccion_ref)
            predio_ref = (
                _find_parent_ref(element, parents, "ARB_Predio", allowed_classes)
                or _find_parent_ref(element, parents, "ILC_Predio", allowed_classes)
            )
            if predio_ref:
                record.setdefault("predio", predio_ref)
                record.setdefault("arb_predio_unidadconstruccion", predio_ref)

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
            ref = (
                parent.attrib.get("TID")
                or parent.attrib.get("tid")
                or parent.attrib.get("t_id")
                or parent.attrib.get("T_Id")
                or parent.attrib.get("T_ID")
                or parent.attrib.get("id")
            )
            return str(ref).strip() if ref else ""
        parent = parents.get(id(parent))
    return ""

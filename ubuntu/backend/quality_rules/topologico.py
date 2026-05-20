from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any, Iterable

from .base import DatasetReader, RuleIssue

try:
    from shapely import wkb, wkt
    from shapely.geometry import MultiPolygon, Point, Polygon, shape
except Exception:
    wkb = None
    wkt = None
    shape = None
    MultiPolygon = None
    Point = None
    Polygon = None

COMPONENT_SLUG = "topologico"

DEFAULT_RULE_IDS = frozenset({
    "5.1", "5.2", "5.3", "5.4", "5.5", "5.6", "5.7",
})


class TopologicoHelper:
    """Utilidades compartidas para reglas topologicas."""

    IDENTIFIER_FIELDS = (
        "t_ili_tid",
        "T_Ili_Tid",
        "T_ILI_TID",
        "id_operacion",
        "Id_Operacion",
        "t_id",
        "TID",
        "id",
        "identificador",
        "Identificador",
        "etiqueta",
        "Etiqueta",
        "complemento",
        "Complemento",
    )

    PREDIO_TABLES = (
        "ARB_Predio",
        "arb_predio",
        "CCA_Predio",
        "cca_predio",
        "A_Predio",
        "a_predio",
    )

    TERRENO_TABLES = (
        "ARB_Terreno",
        "ARB-Terreno",
        "arb_terreno",
        "CCA_Terreno",
        "cca_terreno",
        "E_Terreno",
        "e_terreno",
        "Terreno",
        "terreno",
    )

    DERECHO_INTERESADO_FUENTE_TABLES = (
        "ARB_DerechoInteresadoFuente",
        "arb_derechointeresadofuente",
        "ARB_Derecho_Interesado_Fuente",
        "arb_derecho_interesado_fuente",
        "ARB_Derecho Interesado Fuente",
        "Derecho Interesado Fuente",
        "derecho_interesado_fuente",
    )

    DERECHO_TIPO_TABLES = (
        "ARB_DerechoTipo",
        "arb_derechotipo",
    )

    PREDIO_TIPO_TABLES = (
        "ARB_PredioTipo",
        "arb_prediotipo",
    )

    UNIDAD_CONSTRUCCION_TABLES = (
        "ARB_UnidadConstruccion",
        "arb_unidadconstruccion",
        "D_Unidad_de_Construccion",
        "d_unidad_de_construccion",
        "ARB_Unidad_de_construccion",
        "ARB_Unidad_de_construcción",
        "Unidad de Construccion",
        "Unidad de Construcción",
    )

    CONSTRUCCION_TABLES = (
        "ARB_Construccion",
        "arb_construccion",
        "Construccion",
        "Construcción",
    )

    DIRECCION_TABLES = (
        "ARB_Direccion",
        "ARB_Dirección",
        "arb_direccion",
        "arb_dirección",
        "C_Direccion",
        "c_direccion",
    )

    def __init__(self, dataset: DatasetReader):
        self.dataset = dataset

    def _iter_table_rows(self, table_names: Iterable[str]):
        seen: set[str] = set()

        for table_name in table_names:
            normalized = self._normalize_key(table_name)

            if normalized in seen:
                continue

            if not self.dataset.has_table(table_name):
                continue

            seen.add(normalized)

            for row in self.dataset.get_records(table_name):
                yield table_name, row

    def iter_predio(self):
        yield from self._iter_table_rows(self.PREDIO_TABLES)

    def iter_terreno(self):
        yield from self._iter_table_rows(self.TERRENO_TABLES)

    def iter_derecho_interesado_fuente(self):
        yield from self._iter_table_rows(self.DERECHO_INTERESADO_FUENTE_TABLES)

    def iter_derecho_tipo(self):
        yield from self._iter_table_rows(self.DERECHO_TIPO_TABLES)

    def iter_predio_tipo(self):
        yield from self._iter_table_rows(self.PREDIO_TIPO_TABLES)

    def iter_unidad_construccion(self):
        yield from self._iter_table_rows(self.UNIDAD_CONSTRUCCION_TABLES)

    def iter_construccion(self):
        yield from self._iter_table_rows(self.CONSTRUCCION_TABLES)

    def iter_direccion(self):
        yield from self._iter_table_rows(self.DIRECCION_TABLES)

    def identify(self, row: dict[str, object]) -> str | None:
        for field in self.IDENTIFIER_FIELDS:
            value = self.get_field_value(row, (field,))
            if _is_not_empty(value):
                return str(value).strip()
        return None

    def get_field_value(self, row: dict[str, object], candidates: tuple[str, ...]) -> Any | None:
        normalized_candidates = {self._normalize_key(candidate) for candidate in candidates}

        for key, value in row.items():
            if self._normalize_key(str(key)) in normalized_candidates and _is_not_empty(value):
                if isinstance(value, (bytes, bytearray, memoryview, dict)):
                    return value
                if hasattr(value, "overlaps") or hasattr(value, "contains"):
                    return value
                return str(value).strip()

        return None

    def all_keys(self, row: dict[str, object], candidates: tuple[str, ...]) -> set[str]:
        keys = set()
        for candidate in candidates:
            value = self.get_field_value(row, (candidate,))
            if _is_not_empty(value):
                keys.add(str(value).strip())
        return keys

    def make_issue(
        self,
        row: dict[str, object],
        *,
        rule_id: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> RuleIssue:
        fixed_details = details or {}

        if "class" not in fixed_details and "tabla" in fixed_details:
            fixed_details["class"] = fixed_details["tabla"]

        return RuleIssue(
            rule_id=rule_id,
            object_ref=self.identify(row),
            message=message,
            details=fixed_details,
        )

    @staticmethod
    def _normalize_key(name: object) -> str:
        text = str(name).strip().lower()
        text = (
            text.replace("á", "a")
            .replace("é", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ú", "u")
            .replace("ñ", "n")
        )
        return "".join(ch for ch in text if ch.isalnum())

    @classmethod
    def normalizar_valor_dominio(cls, field_name: object, value: object) -> str:
        if _is_empty(value):
            return ""

        text = str(value).strip()
        norm = cls._normalize_key(text)
        field_norm = cls._normalize_key(field_name)

        derecho = {
            "1": "Posesion",
            "14": "Posesion",
            "posesion": "Posesion",
            "2": "Ocupacion",
            "15": "Ocupacion",
            "ocupacion": "Ocupacion",
            "3": "Dominio",
            "16": "Dominio",
            "dominio": "Dominio",
        }
        if field_norm in {"dtipo", "tipoderecho"} and norm in derecho:
            return derecho[norm]
        if field_norm in {"dtipo", "tipoderecho"}:
            for suffix, ilicode in (
                ("posesion", "Posesion"),
                ("ocupacion", "Ocupacion"),
                ("dominio", "Dominio"),
            ):
                if norm.endswith(suffix):
                    return ilicode

        predio_tipo = {
            "0": "Predio.Publico.Baldio.Reserva_Indigena",
            "1": "Predio.Publico.Baldio.Baldio",
            "2": "Predio.Publico.Fiscal_Patrimonial",
            "3": "Predio.Publico.Uso_Publico",
            "4": "Predio.Publico.Presunto_Baldio",
            "5": "Predio.Privado.Privado",
            "6": "Predio.Privado.Colectivo",
            "1198": "Predio.Publico.Baldio.Reserva_Indigena",
            "1199": "Predio.Publico.Baldio.Baldio",
            "1200": "Predio.Publico.Fiscal_Patrimonial",
            "1201": "Predio.Publico.Uso_Publico",
            "1202": "Predio.Publico.Presunto_Baldio",
            "1203": "Predio.Privado.Privado",
            "1204": "Predio.Privado.Colectivo",
            "prediopublicobaldioreservaindigena": "Predio.Publico.Baldio.Reserva_Indigena",
            "prediopublicobaldiobaldio": "Predio.Publico.Baldio.Baldio",
            "prediopublicofiscalpatrimonial": "Predio.Publico.Fiscal_Patrimonial",
            "prediopublicousopublico": "Predio.Publico.Uso_Publico",
            "prediopublicopresuntobaldio": "Predio.Publico.Presunto_Baldio",
            "predioprivadoprivado": "Predio.Privado.Privado",
            "predioprivadocolectivo": "Predio.Privado.Colectivo",
            "usopublico": "Predio.Publico.Uso_Publico",
            "privado": "Predio.Privado.Privado",
            "colectivo": "Predio.Privado.Colectivo",
        }
        if field_norm == "tipo" and norm in predio_tipo:
            return predio_tipo[norm]
        if field_norm == "tipo":
            for suffix, ilicode in predio_tipo.items():
                if not suffix.isdigit() and norm.endswith(suffix):
                    return ilicode

        return text


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip()
        return text == "" or text.upper() in {"NULL", "<NULL>"} or text.lower() in {"none", "nan"}
    return False


def _is_not_empty(value: Any) -> bool:
    return not _is_empty(value)


def _clean_xml_tag(tag: str) -> str:
    if "}" in tag:
        tag = tag.split("}", 1)[1]
    if "." in tag:
        tag = tag.split(".")[-1]
    return tag.strip().lower()


def _coords_from_node(node: ET.Element) -> list[tuple[float, float]]:
    coords: list[tuple[float, float]] = []
    for coord in node.iter():
        if _clean_xml_tag(coord.tag) != "coord":
            continue

        values = {}
        for child in coord:
            text = (child.text or "").strip()
            if text:
                values[_clean_xml_tag(child.tag)] = text

        x = values.get("c1")
        y = values.get("c2")
        if x is None or y is None:
            continue

        try:
            coords.append((float(x), float(y)))
        except ValueError:
            continue
    return coords


def _closed_ring(coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ring = list(coords)
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def _load_xtf_geometry(xml_text: str):
    if Polygon is None or Point is None:
        return None

    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return None

    polygons = []
    surfaces = [node for node in root.iter() if _clean_xml_tag(node.tag) == "surface"]

    for surface in surfaces:
        rings = []
        boundaries = [node for node in surface.iter() if _clean_xml_tag(node.tag) == "boundary"]
        boundary_nodes = boundaries or [surface]

        for boundary in boundary_nodes:
            ring = _closed_ring(_coords_from_node(boundary))
            if len(ring) >= 4:
                rings.append(ring)

        if not rings:
            continue

        try:
            polygon = Polygon(rings[0], rings[1:])
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            if not polygon.is_empty:
                polygons.append(polygon)
        except Exception:
            continue

    if len(polygons) == 1:
        return polygons[0]

    if len(polygons) > 1 and MultiPolygon is not None:
        try:
            geom = MultiPolygon(polygons)
            if not geom.is_valid:
                geom = geom.buffer(0)
            return geom
        except Exception:
            return None

    coords = _coords_from_node(root)
    if len(coords) == 1:
        try:
            return Point(coords[0])
        except Exception:
            return None

    return None


def _load_geometry(value: object):
    if value is None:
        return None

    if hasattr(value, "overlaps") or hasattr(value, "contains"):
        return value

    if wkt is None or wkb is None or shape is None:
        return None

    if isinstance(value, dict):
        try:
            return shape(value)
        except Exception:
            return None

    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            return wkb.loads(bytes(value))
        except Exception:
            return None

    text = str(value).strip()
    if _is_empty(text):
        return None

    if text.startswith("<"):
        geom = _load_xtf_geometry(text)
        if geom is not None:
            return geom

    try:
        return wkt.loads(text)
    except Exception:
        pass

    try:
        return wkb.loads(bytes.fromhex(text))
    except Exception:
        pass

    try:
        return shape(json.loads(text))
    except Exception:
        return None


def _derecho_tipo_map(helper: TopologicoHelper) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for _, row in helper.iter_derecho_tipo():
        ilicode = helper.get_field_value(row, ("ilicode", "iliCode", "dispName"))
        tipo = TopologicoHelper.normalizar_valor_dominio("d_tipo", ilicode)
        if not tipo:
            continue

        for key in helper.all_keys(row, ("t_id", "T_Id", "id", "itfCode", "iliCode", "ilicode")):
            mapping[str(key)] = tipo
    return mapping


def _derecho_tipo(helper: TopologicoHelper, value: object, domain_map: dict[str, str] | None = None) -> str:
    tipo = TopologicoHelper.normalizar_valor_dominio("d_tipo", value)
    if tipo in {"Dominio", "Posesion", "Ocupacion"}:
        return tipo

    if domain_map and _is_not_empty(value):
        return domain_map.get(str(value).strip(), tipo)

    return tipo


def _predio_tipo(value: object) -> str:
    return TopologicoHelper.normalizar_valor_dominio("tipo", value)


def _predio_key_fields() -> tuple[str, ...]:
    return ("TID", "t_id", "id", "id_operacion", "Id_Operacion", "identificador", "t_ili_tid", "T_Ili_Tid", "T_ILI_TID")


def _object_key_fields() -> tuple[str, ...]:
    return ("TID", "t_id", "id", "t_ili_tid", "T_Ili_Tid", "T_ILI_TID")


def _terreno_predio_ref_fields() -> tuple[str, ...]:
    return ("predio", "Predio", "id_operacion", "Id_Operacion", "etiqueta", "cca_predio_terreno")


def _unidad_predio_ref_fields() -> tuple[str, ...]:
    return ("predio", "Predio", "id_operacion", "Id_Operacion", "etiqueta")


def _unidad_construccion_ref_fields() -> tuple[str, ...]:
    return ("construccion", "Construccion", "construcción", "arb_construccion_unidadconstruccion")


def _direccion_predio_ref_fields() -> tuple[str, ...]:
    return ("arb_predio_direccion", "predio", "Predio", "id_operacion", "Id_Operacion", "etiqueta")


def _geometry_fields() -> tuple[str, ...]:
    return ("geometria", "Geometria", "geometry", "geom", "localizacion", "Localizacion")


def _predios_por_derecho(helper: TopologicoHelper) -> tuple[set[str], set[str], set[str]]:
    dominio: set[str] = set()
    posesion: set[str] = set()
    ocupacion: set[str] = set()
    domain_map = _derecho_tipo_map(helper)

    for _, row in helper.iter_derecho_interesado_fuente():
        tipo = _derecho_tipo(helper, helper.get_field_value(row, ("d_tipo", "D_Tipo", "tipo_derecho")), domain_map)
        predio_refs = helper.all_keys(row, ("predio", "Predio", "id_operacion", "Id_Operacion"))
        if not predio_refs:
            continue

        if tipo == "Dominio":
            dominio.update(predio_refs)
        elif tipo == "Posesion":
            posesion.update(predio_refs)
        elif tipo == "Ocupacion":
            ocupacion.update(predio_refs)

    return dominio, posesion, ocupacion


def _index_predios(helper: TopologicoHelper) -> dict[str, dict[str, object]]:
    predios_by_id: dict[str, dict[str, object]] = {}
    for _, predio in helper.iter_predio():
        for key in helper.all_keys(predio, _predio_key_fields()):
            predios_by_id.setdefault(key, predio)
    return predios_by_id


def _construccion_predios_by_id(helper: TopologicoHelper) -> dict[str, set[str]]:
    predios_by_id: dict[str, set[str]] = {}
    for _, construccion in helper.iter_construccion():
        predio_refs = helper.all_keys(construccion, _terreno_predio_ref_fields())
        if not predio_refs:
            continue

        for key in helper.all_keys(construccion, _object_key_fields()):
            predios_by_id.setdefault(key, set()).update(predio_refs)
    return predios_by_id


def _predio_refs_for_unidad(
    helper: TopologicoHelper,
    unidad: dict[str, object],
    construccion_predios: dict[str, set[str]],
) -> set[str]:
    predio_refs = helper.all_keys(unidad, _unidad_predio_ref_fields())
    construccion_refs = helper.all_keys(unidad, _unidad_construccion_ref_fields())

    for construccion_ref in construccion_refs:
        predio_refs.update(construccion_predios.get(str(construccion_ref), set()))

    return predio_refs


def _terrain_from_row(helper: TopologicoHelper, table_name: str, row: dict[str, object], predio_refs: set[str]):
    geom = _load_geometry(helper.get_field_value(row, _geometry_fields()))
    if geom is None:
        return None

    return {
        "row": row,
        "tabla": table_name,
        "predio": next(iter(predio_refs), None),
        "predio_refs": predio_refs,
        "geom": geom,
        "id": helper.get_field_value(row, ("t_id", "TID", "id")),
        "tid": helper.identify(row),
    }


def _iter_terrenos_filtrados(helper: TopologicoHelper, predio_ids: set[str]) -> list[dict[str, object]]:
    terrenos = []
    for table_name, row in helper.iter_terreno():
        predio_refs = helper.all_keys(row, _terreno_predio_ref_fields())
        if not predio_refs or predio_refs.isdisjoint(predio_ids):
            continue

        terreno = _terrain_from_row(helper, table_name, row, predio_refs)
        if terreno is not None:
            terrenos.append(terreno)
    return terrenos


def _terrenos_por_predio(helper: TopologicoHelper) -> dict[str, list[dict[str, object]]]:
    terrenos_por_predio: dict[str, list[dict[str, object]]] = {}

    for table_name, row in helper.iter_terreno():
        predio_refs = helper.all_keys(row, _terreno_predio_ref_fields())
        if not predio_refs:
            continue

        terreno = _terrain_from_row(helper, table_name, row, predio_refs)
        if terreno is None:
            continue

        for predio_ref in predio_refs:
            terrenos_por_predio.setdefault(str(predio_ref), []).append(terreno)

    return terrenos_por_predio


def _geom_overlaps(g1, g2) -> bool:
    try:
        inter = g1.intersection(g2)
        return bool(not inter.is_empty and getattr(inter, "area", 0) > 0)
    except Exception:
        return False


def _geom_contains(g1, g2) -> bool:
    try:
        return bool(g1.covers(g2))
    except Exception:
        return False


def _pares_overlap(geoms: list[dict[str, object]]):
    for i in range(len(geoms)):
        for j in range(i + 1, len(geoms)):
            a = geoms[i]
            b = geoms[j]
            if a.get("id") and a.get("id") == b.get("id"):
                continue
            if _geom_overlaps(a["geom"], b["geom"]):
                yield a, b


# -------------- reglas --------------------

def _rule_5_1(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []

    dominio, _, _ = _predios_por_derecho(helper)
    terrenos = _iter_terrenos_filtrados(helper, dominio)

    for t1, t2 in _pares_overlap(terrenos):
        issues.append(
            helper.make_issue(
                t1["row"],
                rule_id="5.1",
                message="El terreno formal 1 se superpone con el terreno formal numero 2.",
                details={
                    "tabla": t1["tabla"],
                    "identificador_terreno_1": t1["tid"],
                    "identificador_terreno_2": t2["tid"],
                    "predio_1": t1["predio"],
                    "predio_2": t2["predio"],
                },
            )
        )

    return issues


def _rule_5_2(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []

    _, posesion, ocupacion = _predios_por_derecho(helper)
    terrenos = _iter_terrenos_filtrados(helper, posesion | ocupacion)

    for t1, t2 in _pares_overlap(terrenos):
        issues.append(
            helper.make_issue(
                t1["row"],
                rule_id="5.2",
                message="El terreno informal 1 se superpone con el terreno informal numero 2.",
                details={
                    "tabla": t1["tabla"],
                    "identificador_terreno_1": t1["tid"],
                    "identificador_terreno_2": t2["tid"],
                    "predio_1": t1["predio"],
                    "predio_2": t2["predio"],
                },
            )
        )

    return issues


def _rule_5_3(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []

    dominio, posesion, _ = _predios_por_derecho(helper)
    predios_by_id = _index_predios(helper)

    terrenos_posesion = _iter_terrenos_filtrados(helper, posesion)
    terrenos_publicos = []

    tipos_publicos = {
        "Predio.Publico.Baldio.Reserva_Indigena",
        "Predio.Publico.Baldio.Baldio",
        "Predio.Publico.Fiscal_Patrimonial",
        "Predio.Publico.Uso_Publico",
        "Predio.Publico.Presunto_Baldio",
    }

    for terreno in _iter_terrenos_filtrados(helper, dominio):
        predio = predios_by_id.get(str(terreno["predio"]))
        tipo = _predio_tipo(helper.get_field_value(predio or {}, ("tipo", "Tipo")))
        if tipo in tipos_publicos:
            terrenos_publicos.append(terreno)

    for t1 in terrenos_posesion:
        for t2 in terrenos_publicos:
            if t1.get("id") and t1.get("id") == t2.get("id"):
                continue
            if _geom_overlaps(t1["geom"], t2["geom"]):
                issues.append(
                    helper.make_issue(
                        t1["row"],
                        rule_id="5.3",
                        message=(
                            "Todo terreno asociado a derecho de posesión no puede "
                            "superponerse con un terreno asociado a un predio formal de tipo público."
                        ),
                        details={
                            "tabla": t1["tabla"],
                            "id_terreno_posesion": t1["tid"],
                            "id_terreno_publico": t2["tid"],
                            "predio_posesion": t1["predio"],
                            "predio_publico": t2["predio"],
                        },
                    )
                )

    return issues


def _rule_5_4(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []

    dominio, _, ocupacion = _predios_por_derecho(helper)
    predios_by_id = _index_predios(helper)

    terrenos_ocupacion = _iter_terrenos_filtrados(helper, ocupacion)
    terrenos_privados = []

    tipos_privados = {
        "Predio.Privado.Privado",
        "Predio.Privado.Colectivo",
    }

    for terreno in _iter_terrenos_filtrados(helper, dominio):
        predio = predios_by_id.get(str(terreno["predio"]))
        tipo = _predio_tipo(helper.get_field_value(predio or {}, ("tipo", "Tipo")))
        if tipo in tipos_privados:
            terrenos_privados.append(terreno)

    for t1 in terrenos_ocupacion:
        for t2 in terrenos_privados:
            if t1.get("id") and t1.get("id") == t2.get("id"):
                continue
            if _geom_overlaps(t1["geom"], t2["geom"]):
                issues.append(
                    helper.make_issue(
                        t1["row"],
                        rule_id="5.4",
                        message=(
                            "Todo terreno asociado a derecho de ocupación no puede "
                            "superponerse con un terreno asociado a un predio formal de tipo privado."
                        ),
                        details={
                            "tabla": t1["tabla"],
                            "id_terreno_ocupacion": t1["tid"],
                            "id_terreno_privado": t2["tid"],
                            "predio_ocupacion": t1["predio"],
                            "predio_privado": t2["predio"],
                        },
                    )
                )

    return issues


def _rule_5_5(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []

    unidades: list[dict[str, object]] = []

    for table_name, row in helper.iter_unidad_construccion():
        geom = _load_geometry(helper.get_field_value(row, _geometry_fields()))

        if geom is None:
            continue

        unidades.append({
            "row": row,
            "tabla": table_name,
            "geom": geom,
            "id": helper.get_field_value(row, ("t_id", "TID", "id")),
            "tid": helper.identify(row),
            "tipo_planta": helper.get_field_value(row, ("tipo_planta", "Tipo_Planta")),
            "planta_ubicacion": helper.get_field_value(row, ("planta_ubicacion", "Planta_Ubicacion")),
        })

    for i in range(len(unidades)):
        for j in range(i + 1, len(unidades)):
            cu1 = unidades[i]
            cu2 = unidades[j]

            if cu1["id"] and cu1["id"] == cu2["id"]:
                continue

            if cu1["tipo_planta"] != cu2["tipo_planta"]:
                continue

            if cu1["planta_ubicacion"] != cu2["planta_ubicacion"]:
                continue

            if _geom_overlaps(cu1["geom"], cu2["geom"]):
                issues.append(
                    helper.make_issue(
                        cu1["row"],
                        rule_id="5.5",
                        message=(
                            "No debe existir superposición espacial entre unidades de construcción "
                            "que compartan el mismo tipo de planta y la misma planta de ubicación."
                        ),
                        details={
                            "tabla": cu1["tabla"],
                            "id_unidad_construccion1": cu1["tid"],
                            "id_unidad_construccion2": cu2["tid"],
                            "tipo_planta": cu1["tipo_planta"],
                            "planta_ubicacion": cu1["planta_ubicacion"],
                        },
                    )
                )

    return issues


def _rule_5_6(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []

    terrenos_por_predio = _terrenos_por_predio(helper)
    construccion_predios = _construccion_predios_by_id(helper)

    for table_name, row in helper.iter_unidad_construccion():
        planta_ubicacion = helper.get_field_value(row, ("planta_ubicacion", "Planta_Ubicacion"))
        if str(planta_ubicacion) != "1":
            continue

        predio_refs = _predio_refs_for_unidad(helper, row, construccion_predios)
        if not predio_refs:
            continue

        geom_uc = _load_geometry(helper.get_field_value(row, _geometry_fields()))
        if geom_uc is None:
            continue

        for predio_ref in predio_refs:
            for terreno in terrenos_por_predio.get(str(predio_ref), []):
                if not _geom_contains(terreno["geom"], geom_uc):
                    issues.append(
                        helper.make_issue(
                            row,
                            rule_id="5.6",
                            message=(
                                "Cada unidad de construcción con planta de ubicación 1 "
                                "debe estar completamente contenida dentro del terreno asociado al predio."
                            ),
                            details={
                                "tabla": table_name,
                                "id_terreno": terreno["tid"],
                                "id_uconstruccion": helper.identify(row),
                                "predio": predio_ref,
                            },
                        )
                    )

    return issues


def _rule_5_7(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []

    terrenos_por_predio = _terrenos_por_predio(helper)

    for table_name, row in helper.iter_direccion():
        predio_refs = helper.all_keys(row, _direccion_predio_ref_fields())
        if not predio_refs:
            continue

        geom_dir = _load_geometry(helper.get_field_value(row, _geometry_fields()))
        if geom_dir is None:
            continue

        for predio_ref in predio_refs:
            for terreno in terrenos_por_predio.get(str(predio_ref), []):
                if not _geom_contains(terreno["geom"], geom_dir):
                    issues.append(
                        helper.make_issue(
                            row,
                            rule_id="5.7",
                            message=(
                                "La dirección debe estar completamente contenida dentro "
                                "del terreno asociado al predio."
                            ),
                            details={
                                "tabla": table_name,
                                "identificador_terreno": terreno["tid"],
                                "identificador_direccion": helper.identify(row),
                                "predio": predio_ref,
                            },
                        )
                    )

    return issues


RULE_FUNCTIONS = {
    "5.1": _rule_5_1,
    "5.2": _rule_5_2,
    "5.3": _rule_5_3,
    "5.4": _rule_5_4,
    "5.5": _rule_5_5,
    "5.6": _rule_5_6,
    "5.7": _rule_5_7,
}

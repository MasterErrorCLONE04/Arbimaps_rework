from __future__ import annotations

import json
import math
import unicodedata
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
        "T_Id",
        "T_ID",
        "tid",
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

    PREDIO_DERECHO_TABLES = (
        "ARB_Predio_Derecho",
        "ARB_PredioDerecho",
        "arb_predio_derecho",
        "arb_predioderecho",
    )

    PREDIO_TERRENO_TABLES = (
        "ARB_Predio_Terreno",
        "ARB_PredioTerreno",
        "arb_predio_terreno",
        "arb_predioterreno",
        "CCA_Predio_Terreno",
        "cca_predio_terreno",
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

    def iter_predio_derecho(self):
        yield from self._iter_table_rows(self.PREDIO_DERECHO_TABLES)

    def iter_predio_terreno(self):
        yield from self._iter_table_rows(self.PREDIO_TERRENO_TABLES)

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

        object_ref = (
            fixed_details.get("object_ref")
            or fixed_details.get("par_superposicion")
            or fixed_details.get("par_validacion")
            or self.identify(row)
        )

        return RuleIssue(
            rule_id=rule_id,
            object_ref=str(object_ref) if _is_not_empty(object_ref) else self.identify(row),
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
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
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
        if field_norm in {"dtipo", "tipoderecho", "tipo"} and norm in derecho:
            return derecho[norm]
        if field_norm in {"dtipo", "tipoderecho", "tipo"}:
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


def _display_id(value: object, fallback: str = "sin ID") -> str:
    if _is_empty(value):
        return fallback
    return str(value).strip()


def _pair_ref(id1: object, id2: object) -> str:
    return f"{_display_id(id1, 'sin_id_1')} <-> {_display_id(id2, 'sin_id_2')}"


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


class _SimpleIntersection:
    def __init__(self, area: float):
        self.area = area
        self.is_empty = area <= 0


class _SimplePoint:
    def __init__(self, coord: tuple[float, float]):
        self.coord = coord

    def intersection(self, other):
        return _SimpleIntersection(0)

    def overlaps(self, other) -> bool:
        return False

    def covers(self, other) -> bool:
        if isinstance(other, _SimplePoint):
            return self.coord == other.coord
        return False


class _SimplePolygon:
    def __init__(self, outer: list[tuple[float, float]], holes: list[list[tuple[float, float]]] | None = None):
        self.outer = _closed_ring(outer)
        self.holes = [_closed_ring(hole) for hole in (holes or [])]
        self.is_empty = len(self.outer) < 4 or _ring_area(self.outer) <= 0

    def intersection(self, other):
        if isinstance(other, _SimpleMultiPolygon):
            return other.intersection(self)
        if isinstance(other, _SimplePolygon):
            return _SimpleIntersection(_polygon_intersection_area(self.outer, other.outer))
        return _SimpleIntersection(0)

    def overlaps(self, other) -> bool:
        if isinstance(other, _SimpleMultiPolygon):
            return other.overlaps(self)
        if not isinstance(other, _SimplePolygon):
            return False
        inter = self.intersection(other)
        if inter.is_empty or getattr(inter, "area", 0) <= 0:
            return False
        return not self.covers(other) and not other.covers(self)

    def covers(self, other) -> bool:
        if isinstance(other, _SimplePoint):
            return _point_in_ring(other.coord, self.outer) and not any(
                _point_in_ring(other.coord, hole) for hole in self.holes
            )
        if isinstance(other, _SimplePolygon):
            return all(_point_in_ring(point, self.outer) for point in other.outer[:-1])
        if isinstance(other, _SimpleMultiPolygon):
            return all(self.covers(polygon) for polygon in other.polygons)
        return False


class _SimpleMultiPolygon:
    def __init__(self, polygons: list[_SimplePolygon]):
        self.polygons = [polygon for polygon in polygons if not polygon.is_empty]
        self.is_empty = not self.polygons

    def intersection(self, other):
        area = 0.0
        for polygon in self.polygons:
            inter = polygon.intersection(other)
            area += float(getattr(inter, "area", 0) or 0)
        return _SimpleIntersection(area)

    def overlaps(self, other) -> bool:
        inter = self.intersection(other)
        if inter.is_empty or getattr(inter, "area", 0) <= 0:
            return False
        return not self.covers(other) and not _geom_contains(other, self)

    def covers(self, other) -> bool:
        if isinstance(other, _SimpleMultiPolygon):
            return all(self.covers(polygon) for polygon in other.polygons)
        return any(polygon.covers(other) for polygon in self.polygons)


def _ring_area(ring: list[tuple[float, float]]) -> float:
    if len(ring) < 4:
        return 0.0
    total = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _point_on_segment(point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> bool:
    px, py = point
    ax, ay = a
    bx, by = b
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > 1e-9:
        return False
    return min(ax, bx) - 1e-9 <= px <= max(ax, bx) + 1e-9 and min(ay, by) - 1e-9 <= py <= max(ay, by) + 1e-9


def _point_in_ring(point: tuple[float, float], ring: list[tuple[float, float]]) -> bool:
    if len(ring) < 4:
        return False

    x, y = point
    inside = False

    for i in range(len(ring) - 1):
        a = ring[i]
        b = ring[i + 1]
        if _point_on_segment(point, a, b):
            return True

        xi, yi = a
        xj, yj = b
        if (yi > y) != (yj > y):
            x_intersection = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x <= x_intersection:
                inside = not inside

    return inside


def _segment_intersection(
    a1: tuple[float, float],
    a2: tuple[float, float],
    b1: tuple[float, float],
    b2: tuple[float, float],
) -> tuple[float, float] | None:
    x1, y1 = a1
    x2, y2 = a2
    x3, y3 = b1
    x4, y4 = b2
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)

    if abs(denom) < 1e-12:
        for point in (a1, a2, b1, b2):
            if _point_on_segment(point, a1, a2) and _point_on_segment(point, b1, b2):
                return point
        return None

    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denom
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denom
    point = (px, py)

    if _point_on_segment(point, a1, a2) and _point_on_segment(point, b1, b2):
        return point
    return None


def _unique_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    seen = set()
    unique = []
    for x, y in points:
        key = (round(x, 9), round(y, 9))
        if key in seen:
            continue
        seen.add(key)
        unique.append((x, y))
    return unique


def _polygon_intersection_area(poly_a: list[tuple[float, float]], poly_b: list[tuple[float, float]]) -> float:
    points: list[tuple[float, float]] = []

    points.extend(point for point in poly_a[:-1] if _point_in_ring(point, poly_b))
    points.extend(point for point in poly_b[:-1] if _point_in_ring(point, poly_a))

    for i in range(len(poly_a) - 1):
        for j in range(len(poly_b) - 1):
            point = _segment_intersection(poly_a[i], poly_a[i + 1], poly_b[j], poly_b[j + 1])
            if point is not None:
                points.append(point)

    points = _unique_points(points)
    if len(points) < 3:
        return 0.0

    centroid_x = sum(x for x, _ in points) / len(points)
    centroid_y = sum(y for _, y in points) / len(points)
    points.sort(key=lambda p: math.atan2(p[1] - centroid_y, p[0] - centroid_x))
    return _ring_area(_closed_ring(points))


def _load_xtf_geometry(xml_text: str):
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

        if Polygon is None:
            polygon = _SimplePolygon(rings[0], rings[1:])
            if not polygon.is_empty:
                polygons.append(polygon)
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

    if len(polygons) > 1 and MultiPolygon is None:
        simple_polygons = [polygon for polygon in polygons if isinstance(polygon, _SimplePolygon)]
        if simple_polygons:
            return _SimpleMultiPolygon(simple_polygons)

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
        if Point is None:
            return _SimplePoint(coords[0])
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

    if isinstance(value, dict) and shape is not None:
        try:
            return shape(value)
        except Exception:
            return None

    if isinstance(value, (bytes, bytearray, memoryview)) and wkb is not None:
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

    if wkt is not None:
        try:
            return wkt.loads(text)
        except Exception:
            pass

    if wkb is not None:
        try:
            return wkb.loads(bytes.fromhex(text))
        except Exception:
            pass

    if shape is not None:
        try:
            return shape(json.loads(text))
        except Exception:
            return None

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
        mapped = domain_map.get(str(value).strip())
        if mapped in {"Dominio", "Posesion", "Ocupacion"}:
            return mapped

    return tipo


def _predio_tipo(value: object) -> str:
    return TopologicoHelper.normalizar_valor_dominio("tipo", value)


def _predio_key_fields() -> tuple[str, ...]:
    return (
        "TID",
        "tid",
        "t_id",
        "T_Id",
        "T_ID",
        "id",
        "id_operacion",
        "Id_Operacion",
        "identificador",
        "identificacion",
        "t_ili_tid",
        "T_Ili_Tid",
        "T_ILI_TID",
        "numero_predial",
        "Numero_Predial",
        "numero_predial_nacional",
        "Numero_Predial_Nacional",
        "etiqueta",
        "Etiqueta",
    )


def _predio_canonical_fields() -> tuple[str, ...]:
    return (
        "t_ili_tid",
        "T_Ili_Tid",
        "T_ILI_TID",
        "TID",
        "tid",
        "t_id",
        "T_Id",
        "T_ID",
        "id",
        "id_operacion",
        "Id_Operacion",
        "identificador",
        "identificacion",
        "numero_predial",
        "Numero_Predial",
        "numero_predial_nacional",
        "Numero_Predial_Nacional",
        "etiqueta",
        "Etiqueta",
    )


def _object_key_fields() -> tuple[str, ...]:
    return ("TID", "tid", "t_id", "T_Id", "T_ID", "id", "t_ili_tid", "T_Ili_Tid", "T_ILI_TID")


def _terreno_predio_ref_fields() -> tuple[str, ...]:
    return (
        "predio",
        "Predio",
        "arb_predio",
        "ARB_Predio",
        "arb_predio_terreno",
        "arb_predio_construccion",
        "cca_predio_terreno",
        "id_predio",
        "Id_Predio",
        "predio_id",
        "Predio_ID",
        "predio_asociado",
        "id_operacion",
        "Id_Operacion",
        "id_grupo",
        "Id_Grupo",
        "numero_predial",
        "Numero_Predial",
        "numero_predial_nacional",
        "Numero_Predial_Nacional",
        "etiqueta",
        "Etiqueta",
    )


def _association_predio_fields() -> tuple[str, ...]:
    return (
        "predio",
        "Predio",
        "arb_predio",
        "ARB_Predio",
        "id_predio",
        "Id_Predio",
        "predio_id",
        "Predio_ID",
        "predio_asociado",
        "id_operacion",
        "Id_Operacion",
        "id_grupo",
        "Id_Grupo",
        "numero_predial",
        "Numero_Predial",
        "numero_predial_nacional",
        "Numero_Predial_Nacional",
        "etiqueta",
        "Etiqueta",
    )


def _association_terreno_fields() -> tuple[str, ...]:
    return (
        "terreno",
        "Terreno",
        "arb_terreno",
        "ARB_Terreno",
        "id_terreno",
        "terreno_id",
    )


def _association_derecho_fields() -> tuple[str, ...]:
    return (
        "derecho",
        "Derecho",
        "arb_derechointeresadofuente",
        "ARB_DerechoInteresadoFuente",
        "derecho_interesado_fuente",
        "Derecho_Interesado_Fuente",
        "id_derecho",
        "derecho_id",
    )


def _unidad_predio_ref_fields() -> tuple[str, ...]:
    return (
        "predio",
        "Predio",
        "id_operacion",
        "Id_Operacion",
        "id_grupo",
        "Id_Grupo",
        "numero_predial",
        "Numero_Predial",
        "baunit",
        "BAUnit",
        "ue_baunit",
        "uebaunit",
        "etiqueta",
        "Etiqueta",
    )


def _unidad_construccion_ref_fields() -> tuple[str, ...]:
    return ("construccion", "Construccion", "construcción", "arb_construccion_unidadconstruccion")


def _direccion_predio_ref_fields() -> tuple[str, ...]:
    return (
        "arb_predio_direccion",
        "predio",
        "Predio",
        "id_operacion",
        "Id_Operacion",
        "id_grupo",
        "Id_Grupo",
        "numero_predial",
        "Numero_Predial",
        "etiqueta",
        "Etiqueta",
    )


def _geometry_fields() -> tuple[str, ...]:
    return ("geometria", "Geometria", "geometry", "geom", "localizacion", "Localizacion")


def _derecho_predio_ref_fields() -> tuple[str, ...]:
    return (
        "predio",
        "Predio",
        "arb_predio",
        "ARB_Predio",
        "arb_predio_derecho",
        "id_predio",
        "Id_Predio",
        "predio_id",
        "Predio_ID",
        "predio_asociado",
        "id_operacion",
        "Id_Operacion",
        "id_grupo",
        "Id_Grupo",
        "numero_predial",
        "Numero_Predial",
        "numero_predial_nacional",
        "Numero_Predial_Nacional",
        "etiqueta",
        "Etiqueta",
    )


def _derecho_tipo_fields() -> tuple[str, ...]:
    return (
        "d_tipo",
        "D_Tipo",
        "tipo_derecho",
        "Tipo_Derecho",
        "tipo",
        "Tipo",
    )


def _association_map(
    rows: Iterable[tuple[str, dict[str, object]]],
    helper: TopologicoHelper,
    *,
    source_fields: tuple[str, ...],
    target_fields: tuple[str, ...],
) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}

    for _, row in rows:
        sources = helper.all_keys(row, source_fields)
        targets = helper.all_keys(row, target_fields)

        if not sources or not targets:
            continue

        for target in targets:
            mapping.setdefault(str(target), set()).update(str(source) for source in sources)

    return mapping


def _derecho_predios_by_id(helper: TopologicoHelper) -> dict[str, set[str]]:
    return _association_map(
        helper.iter_predio_derecho(),
        helper,
        source_fields=_association_predio_fields(),
        target_fields=_association_derecho_fields(),
    )


def _terreno_predios_by_id(helper: TopologicoHelper) -> dict[str, set[str]]:
    return _association_map(
        helper.iter_predio_terreno(),
        helper,
        source_fields=_association_predio_fields(),
        target_fields=_association_terreno_fields(),
    )


def _predio_refs_for_object(
    helper: TopologicoHelper,
    row: dict[str, object],
    direct_fields: tuple[str, ...],
    association_map: dict[str, set[str]],
) -> set[str]:
    predio_refs = helper.all_keys(row, direct_fields)

    for key in helper.all_keys(row, _object_key_fields()):
        predio_refs.update(association_map.get(str(key), set()))

    return predio_refs


def _predio_alias_index(helper: TopologicoHelper) -> dict[str, str]:
    alias_index: dict[str, str] = {}

    for _, predio in helper.iter_predio():
        predio_keys = helper.all_keys(predio, _predio_key_fields())
        canonical = None

        for field_name in _predio_canonical_fields():
            value = helper.get_field_value(predio, (field_name,))
            if _is_not_empty(value):
                canonical = str(value).strip()
                break

        if canonical is None:
            canonical = next(iter(predio_keys), None)

        if not canonical:
            continue

        canonical = str(canonical).strip()
        for key in predio_keys:
            alias_index.setdefault(str(key).strip(), canonical)
        alias_index.setdefault(canonical, canonical)

    return alias_index


def _canonical_predio_refs(refs: set[str], alias_index: dict[str, str] | None) -> set[str]:
    if not alias_index:
        return {str(ref).strip() for ref in refs if _is_not_empty(ref)}

    canonical_refs: set[str] = set()
    for ref in refs:
        if _is_empty(ref):
            continue
        ref_text = str(ref).strip()
        canonical_refs.add(alias_index.get(ref_text, ref_text))
    return canonical_refs


def _predios_por_derecho(
    helper: TopologicoHelper,
    alias_index: dict[str, str] | None = None,
) -> tuple[set[str], set[str], set[str]]:
    dominio: set[str] = set()
    posesion: set[str] = set()
    ocupacion: set[str] = set()
    domain_map = _derecho_tipo_map(helper)
    derecho_predios = _derecho_predios_by_id(helper)

    for _, row in helper.iter_derecho_interesado_fuente():
        tipo_raw = helper.get_field_value(row, _derecho_tipo_fields())
        tipo = _derecho_tipo(helper, tipo_raw, domain_map)
        predio_refs = _predio_refs_for_object(
            helper,
            row,
            _derecho_predio_ref_fields(),
            derecho_predios,
        )
        predio_refs = _canonical_predio_refs(predio_refs, alias_index)

        if not predio_refs:
            continue

        if tipo == "Dominio":
            dominio.update(predio_refs)
        elif tipo == "Posesion":
            posesion.update(predio_refs)
        elif tipo == "Ocupacion":
            ocupacion.update(predio_refs)

    return dominio, posesion, ocupacion


def _index_predios(helper: TopologicoHelper, alias_index: dict[str, str] | None = None) -> dict[str, dict[str, object]]:
    predios_by_id: dict[str, dict[str, object]] = {}
    for _, predio in helper.iter_predio():
        for key in helper.all_keys(predio, _predio_key_fields()):
            predios_by_id.setdefault(key, predio)
            if alias_index and key in alias_index:
                predios_by_id.setdefault(alias_index[key], predio)
    return predios_by_id


def _construccion_predios_by_id(
    helper: TopologicoHelper,
    alias_index: dict[str, str] | None = None,
) -> dict[str, set[str]]:
    predios_by_id: dict[str, set[str]] = {}
    for _, construccion in helper.iter_construccion():
        predio_refs = helper.all_keys(construccion, _terreno_predio_ref_fields())
        predio_refs = _canonical_predio_refs(predio_refs, alias_index)
        if not predio_refs:
            continue

        for key in helper.all_keys(construccion, _object_key_fields()):
            predios_by_id.setdefault(key, set()).update(predio_refs)
    return predios_by_id


def _predio_refs_for_unidad(
    helper: TopologicoHelper,
    unidad: dict[str, object],
    construccion_predios: dict[str, set[str]],
    alias_index: dict[str, str] | None = None,
) -> set[str]:
    predio_refs = helper.all_keys(unidad, _unidad_predio_ref_fields())
    predio_refs = _canonical_predio_refs(predio_refs, alias_index)
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
        "id": helper.get_field_value(row, ("t_id", "T_Id", "T_ID", "TID", "tid", "id")),
        "tid": helper.identify(row),
    }


def _iter_terrenos_filtrados(
    helper: TopologicoHelper,
    predio_ids: set[str],
    alias_index: dict[str, str] | None = None,
    *,
    fallback_todos_si_no_hay_clasificacion: bool = False,
) -> list[dict[str, object]]:
    terrenos = []
    terreno_predios = _terreno_predios_by_id(helper)
    predio_ids = _canonical_predio_refs(predio_ids, alias_index)

    # En algunos XTF no viene la tabla ARB_DerechoInteresadoFuente.
    # QGIS, en ese caso, valida 5.1/5.2 contra todos los terrenos cargados.
    # Para igualar ese comportamiento, 5.1 y 5.2 activan este fallback.
    if not predio_ids and not fallback_todos_si_no_hay_clasificacion:
        return terrenos

    for table_name, row in helper.iter_terreno():
        predio_refs = _predio_refs_for_object(
            helper,
            row,
            _terreno_predio_ref_fields(),
            terreno_predios,
        )
        predio_refs_canonicas = _canonical_predio_refs(predio_refs, alias_index)

        if predio_ids and (
            not predio_refs_canonicas
            or predio_refs_canonicas.isdisjoint(predio_ids)
        ):
            continue

        terreno = _terrain_from_row(helper, table_name, row, predio_refs_canonicas)
        if terreno is not None:
            terrenos.append(terreno)
    return terrenos


def _terrenos_por_predio(
    helper: TopologicoHelper,
    alias_index: dict[str, str] | None = None,
) -> dict[str, list[dict[str, object]]]:
    terrenos_por_predio: dict[str, list[dict[str, object]]] = {}
    terreno_predios = _terreno_predios_by_id(helper)

    for table_name, row in helper.iter_terreno():
        predio_refs = _predio_refs_for_object(
            helper,
            row,
            _terreno_predio_ref_fields(),
            terreno_predios,
        )
        predio_refs_canonicas = _canonical_predio_refs(predio_refs, alias_index)
        if not predio_refs_canonicas:
            continue

        terreno = _terrain_from_row(helper, table_name, row, predio_refs_canonicas)
        if terreno is None:
            continue

        for predio_ref in predio_refs_canonicas:
            terrenos_por_predio.setdefault(str(predio_ref), []).append(terreno)

    return terrenos_por_predio


def _geom_overlaps(g1, g2) -> bool:
    try:
        if hasattr(g1, "overlaps"):
            return bool(g1.overlaps(g2))

        # Fallback para las geometrias simples cuando Shapely no esta disponible:
        # superposicion = area comun positiva, sin que una geometria cubra totalmente a la otra.
        inter = g1.intersection(g2)
        if inter.is_empty or getattr(inter, "area", 0) <= 0:
            return False
        return not _geom_contains(g1, g2) and not _geom_contains(g2, g1)
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
    alias_index = _predio_alias_index(helper)

    dominio, _, _ = _predios_por_derecho(helper, alias_index)
    terrenos = _iter_terrenos_filtrados(
        helper,
        dominio,
        alias_index,
        fallback_todos_si_no_hay_clasificacion=True,
    )

    for t1, t2 in _pares_overlap(terrenos):
        id_1 = _display_id(t1["tid"])
        id_2 = _display_id(t2["tid"])
        pair_id = _pair_ref(t1["tid"], t2["tid"])
        issues.append(
            helper.make_issue(
                t1["row"],
                rule_id="5.1",
                message=(
                    f"El terreno formal con ID {id_1} se superpone con "
                    f"el terreno formal con ID {id_2}."
                ),
                details={
                    "tabla": t1["tabla"],
                    "identificador_terreno_1": t1["tid"],
                    "identificador_terreno_2": t2["tid"],
                    "predio_1": t1["predio"],
                    "predio_2": t2["predio"],
                    "par_superposicion": pair_id,
                    "object_ref": pair_id,
                },
            )
        )

    return issues


def _rule_5_2(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []
    alias_index = _predio_alias_index(helper)

    _, posesion, ocupacion = _predios_por_derecho(helper, alias_index)
    terrenos = _iter_terrenos_filtrados(
        helper,
        posesion | ocupacion,
        alias_index,
        fallback_todos_si_no_hay_clasificacion=True,
    )

    for t1, t2 in _pares_overlap(terrenos):
        id_1 = _display_id(t1["tid"])
        id_2 = _display_id(t2["tid"])
        pair_id = _pair_ref(t1["tid"], t2["tid"])
        issues.append(
            helper.make_issue(
                t1["row"],
                rule_id="5.2",
                message=(
                    f"El terreno informal con ID {id_1} se superpone con "
                    f"el terreno informal con ID {id_2}."
                ),
                details={
                    "tabla": t1["tabla"],
                    "identificador_terreno_1": t1["tid"],
                    "identificador_terreno_2": t2["tid"],
                    "predio_1": t1["predio"],
                    "predio_2": t2["predio"],
                    "par_superposicion": pair_id,
                    "object_ref": pair_id,
                },
            )
        )

    return issues


def _rule_5_3(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []
    alias_index = _predio_alias_index(helper)

    dominio, posesion, _ = _predios_por_derecho(helper, alias_index)
    predios_by_id = _index_predios(helper, alias_index)

    terrenos_posesion = _iter_terrenos_filtrados(helper, posesion, alias_index)
    terrenos_publicos = []

    tipos_publicos = {
        "Predio.Publico.Baldio.Reserva_Indigena",
        "Predio.Publico.Baldio.Baldio",
        "Predio.Publico.Fiscal_Patrimonial",
        "Predio.Publico.Uso_Publico",
        "Predio.Publico.Presunto_Baldio",
    }

    for terreno in _iter_terrenos_filtrados(helper, dominio, alias_index):
        predio = predios_by_id.get(str(terreno["predio"]))
        tipo = _predio_tipo(helper.get_field_value(predio or {}, ("tipo", "Tipo")))
        if tipo in tipos_publicos:
            terrenos_publicos.append(terreno)

    for t1 in terrenos_posesion:
        for t2 in terrenos_publicos:
            if t1.get("id") and t1.get("id") == t2.get("id"):
                continue
            if _geom_overlaps(t1["geom"], t2["geom"]):
                id_1 = _display_id(t1["tid"])
                id_2 = _display_id(t2["tid"])
                pair_id = _pair_ref(t1["tid"], t2["tid"])
                issues.append(
                    helper.make_issue(
                        t1["row"],
                        rule_id="5.3",
                        message=(
                            f"El terreno de posesión con ID {id_1} se superpone con "
                            f"el terreno formal público con ID {id_2}."
                        ),
                        details={
                            "tabla": t1["tabla"],
                            "id_terreno_posesion": t1["tid"],
                            "id_terreno_publico": t2["tid"],
                            "predio_posesion": t1["predio"],
                            "predio_publico": t2["predio"],
                            "par_superposicion": pair_id,
                            "object_ref": pair_id,
                        },
                    )
                )

    return issues


def _rule_5_4(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []
    alias_index = _predio_alias_index(helper)

    dominio, _, ocupacion = _predios_por_derecho(helper, alias_index)
    predios_by_id = _index_predios(helper, alias_index)

    terrenos_ocupacion = _iter_terrenos_filtrados(helper, ocupacion, alias_index)
    terrenos_privados = []

    tipos_privados = {
        "Predio.Privado.Privado",
        "Predio.Privado.Colectivo",
    }

    for terreno in _iter_terrenos_filtrados(helper, dominio, alias_index):
        predio = predios_by_id.get(str(terreno["predio"]))
        tipo = _predio_tipo(helper.get_field_value(predio or {}, ("tipo", "Tipo")))
        if tipo in tipos_privados:
            terrenos_privados.append(terreno)

    for t1 in terrenos_ocupacion:
        for t2 in terrenos_privados:
            if t1.get("id") and t1.get("id") == t2.get("id"):
                continue
            if _geom_overlaps(t1["geom"], t2["geom"]):
                id_1 = _display_id(t1["tid"])
                id_2 = _display_id(t2["tid"])
                pair_id = _pair_ref(t1["tid"], t2["tid"])
                issues.append(
                    helper.make_issue(
                        t1["row"],
                        rule_id="5.4",
                        message=(
                            f"El terreno de ocupación con ID {id_1} se superpone con "
                            f"el terreno formal privado con ID {id_2}."
                        ),
                        details={
                            "tabla": t1["tabla"],
                            "id_terreno_ocupacion": t1["tid"],
                            "id_terreno_privado": t2["tid"],
                            "predio_ocupacion": t1["predio"],
                            "predio_privado": t2["predio"],
                            "par_superposicion": pair_id,
                            "object_ref": pair_id,
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
                id_1 = _display_id(cu1["tid"])
                id_2 = _display_id(cu2["tid"])
                pair_id = _pair_ref(cu1["tid"], cu2["tid"])
                issues.append(
                    helper.make_issue(
                        cu1["row"],
                        rule_id="5.5",
                        message=(
                            f"La unidad de construcción con ID {id_1} se superpone con "
                            f"la unidad de construcción con ID {id_2}."
                        ),
                        details={
                            "tabla": cu1["tabla"],
                            "id_unidad_construccion1": cu1["tid"],
                            "id_unidad_construccion2": cu2["tid"],
                            "tipo_planta": cu1["tipo_planta"],
                            "planta_ubicacion": cu1["planta_ubicacion"],
                            "par_superposicion": pair_id,
                            "object_ref": pair_id,
                        },
                    )
                )

    return issues


def _rule_5_6(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []
    alias_index = _predio_alias_index(helper)

    terrenos_por_predio = _terrenos_por_predio(helper, alias_index)
    construccion_predios = _construccion_predios_by_id(helper, alias_index)

    for table_name, row in helper.iter_unidad_construccion():
        planta_ubicacion = helper.get_field_value(row, ("planta_ubicacion", "Planta_Ubicacion"))
        if str(planta_ubicacion) != "1":
            continue

        predio_refs = _predio_refs_for_unidad(helper, row, construccion_predios, alias_index)
        if not predio_refs:
            continue

        geom_uc = _load_geometry(helper.get_field_value(row, _geometry_fields()))
        if geom_uc is None:
            continue

        for predio_ref in predio_refs:
            for terreno in terrenos_por_predio.get(str(predio_ref), []):
                if not _geom_contains(terreno["geom"], geom_uc):
                    id_unidad = _display_id(helper.identify(row))
                    id_terreno = _display_id(terreno["tid"])
                    pair_id = _pair_ref(helper.identify(row), terreno["tid"])
                    issues.append(
                        helper.make_issue(
                            row,
                            rule_id="5.6",
                            message=(
                                f"La unidad de construcción con ID {id_unidad} no está "
                                f"completamente contenida dentro del terreno asociado con ID {id_terreno}."
                            ),
                            details={
                                "tabla": table_name,
                                "id_terreno": terreno["tid"],
                                "id_uconstruccion": helper.identify(row),
                                "predio": predio_ref,
                                "par_validacion": pair_id,
                                "object_ref": pair_id,
                            },
                        )
                    )

    return issues


def _rule_5_7(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []
    alias_index = _predio_alias_index(helper)

    terrenos_por_predio = _terrenos_por_predio(helper, alias_index)

    for table_name, row in helper.iter_direccion():
        predio_refs = helper.all_keys(row, _direccion_predio_ref_fields())
        predio_refs = _canonical_predio_refs(predio_refs, alias_index)
        if not predio_refs:
            continue

        geom_dir = _load_geometry(helper.get_field_value(row, _geometry_fields()))
        if geom_dir is None:
            continue

        for predio_ref in predio_refs:
            for terreno in terrenos_por_predio.get(str(predio_ref), []):
                if not _geom_contains(terreno["geom"], geom_dir):
                    id_direccion = _display_id(helper.identify(row))
                    id_terreno = _display_id(terreno["tid"])
                    pair_id = _pair_ref(helper.identify(row), terreno["tid"])
                    issues.append(
                        helper.make_issue(
                            row,
                            rule_id="5.7",
                            message=(
                                f"La dirección con ID {id_direccion} no está completamente "
                                f"contenida dentro del terreno asociado con ID {id_terreno}."
                            ),
                            details={
                                "tabla": table_name,
                                "identificador_terreno": terreno["tid"],
                                "identificador_direccion": helper.identify(row),
                                "predio": predio_ref,
                                "par_validacion": pair_id,
                                "object_ref": pair_id,
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

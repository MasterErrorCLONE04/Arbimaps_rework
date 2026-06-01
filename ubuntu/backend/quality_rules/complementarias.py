from __future__ import annotations
import json
import unicodedata
import xml.etree.ElementTree as ET

from .base import DatasetReader, RuleIssue
from shapely import wkb, wkt
from shapely.geometry import MultiPolygon, Point, Polygon, shape

COMPONENT_SLUG = "complementarias"

DEFAULT_RULE_IDS = frozenset({
    "10.1", "10.2", "10.3", "10.4"
})


class ComplementariasHelper:
    """Utilidades compartidas para reglas complementarias."""
    IDENTIFIER_FIELDS = (
        "id_operacion",
        "Id_Operacion",
        "t_id",
        "T_Id",
        "id",
        "TID",
        "t_ili_tid",
        "T_Ili_Tid",
        "numero_predial",
        "Numero_Predial",
    )

    PREDIO_TABLES = (
        "ARB_Predio",
        "arb_predio",
    )

    DERECHO_INTERESADO_TABLES = (
        "ARB_DerechoInteresadoFuente",
        "arb_derechointeresadofuente",
    )

    TERRENO_TABLES = (
        "ARB_Terreno",
        "arb_terreno",
    )

    UNIDAD_CONSTRUCCION_TABLES = (
        "ARB_UnidadConstruccion",
        "arb_unidadconstruccion",
        "D_Unidad_de_Construccion",
        "d_unidad_de_construccion",
        "ARB_Unidad_de_construccion",
        "arb_unidad_de_construccion",
        "Unidad de Construccion",
        "Unidad de Construcción",
    )

    CONSTRUCCION_UNIDAD_TABLES = (
        "ARB_Construccion_UnidadConstruccion",
        "arb_construccion_unidadconstruccion",
        "ARB_ConstruccionUnidadConstruccion",
        "arb_construccionunidadconstruccion",
    )

    CARACTERISTICAS_UNIDAD_TABLES = (
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )

    MARCA_PREDIAL_TABLES = (
        "ARB_MarcaPredial",
        "arb_marcapredial",
        "ARB_Marca",
        "arb_marca",
    )



    def __init__(self, dataset: DatasetReader):
        self.dataset = dataset

    def _iter_table_rows(self, table_names: tuple[str, ...]):
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

    def iter_predios(self):
        yield from self._iter_table_rows(self.PREDIO_TABLES)

    def iter_unidades_construccion(self):
        yield from self._iter_table_rows(self.UNIDAD_CONSTRUCCION_TABLES)

    def iter_construccion_unidad(self):
        yield from self._iter_table_rows(self.CONSTRUCCION_UNIDAD_TABLES)

    def iter_derecho_interesado(self):
        yield from self._iter_table_rows(self.DERECHO_INTERESADO_TABLES)

    def iter_terreno(self):
        yield from self._iter_table_rows(self.TERRENO_TABLES)

    def iter_caracteristicas_unidad(self):
        yield from self._iter_table_rows(self.CARACTERISTICAS_UNIDAD_TABLES)

    def iter_marcas_prediales(self):
        yield from self._iter_table_rows(self.MARCA_PREDIAL_TABLES)

    def identify(self, row: dict[str, object]) -> str | None:
        for field in self.IDENTIFIER_FIELDS:
            value = self.get_field_value(row, (field,))
            if _is_not_empty(value):
                return str(value).strip()

        return None

    def get_field_value(self, row: dict[str, object], candidates: tuple[str, ...]) -> str | None:
        normalized_candidates = {self._normalize_key(candidate) for candidate in candidates}

        for key, value in row.items():
            if self._normalize_key(str(key)) in normalized_candidates:
                if value not in (None, ""):
                    return str(value).strip()

        return None
    
    def get_raw_field_value(self, row: dict[str, object], candidates: tuple[str, ...]) -> object | None:
        normalized_candidates = {self._normalize_key(candidate) for candidate in candidates}

        for key, value in row.items():
            if self._normalize_key(str(key)) in normalized_candidates:
                return value

        return None

    def make_issue(
        self,
        row: dict[str, object],
        *,
        rule_id: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> RuleIssue:
        fixed_details = details or {}

        if "class" not in fixed_details:
            if "tabla" in fixed_details:
                fixed_details["class"] = fixed_details["tabla"]

        return RuleIssue(
            rule_id=rule_id,
            object_ref=self.identify(row),
            message=message,
            details=fixed_details,
        )

    @staticmethod
    def _normalize_key(name: str) -> str:
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
    
def _is_empty(value: object) -> bool:
    if value is None:
        return True

    text = str(value).strip()

    return (
        text == ""
        or text.upper() in {"NULL", "<NULL>"}
        or text.lower() in {"none", "nan"}
    )


def _is_not_empty(value: object) -> bool:
    return not _is_empty(value)

def _get_predio_nuevo_ids(helper: ComplementariasHelper) -> set[str]:
    ids = {"Predio_Nuevo", "Predio Nuevo", "predio_nuevo"}

    for _, row in helper._iter_table_rows((
        "ARB_NovedadNumeroPredialTipo",
        "arb_novedadnumeropredialtipo",
    )):
        ilicode = helper.get_field_value(row, ("iliCode", "ilicode"))
        t_id = helper.get_field_value(row, ("T_Id", "t_id", "id"))
        itf_code = helper.get_field_value(row, ("itfCode", "itfcode"))
        disp_name = helper.get_field_value(row, ("dispName", "dispname"))

        if _matches_domain_value(ilicode, {"Predio_Nuevo"}) or _matches_domain_value(disp_name, {"Predio Nuevo"}):
            for value in (t_id, itf_code, ilicode, disp_name):
                if _is_not_empty(value):
                    ids.add(str(value).strip())

    return ids


def _matches_domain_value(value: object, accepted_values: set[str]) -> bool:
    if _is_empty(value):
        return False

    normalized_value = ComplementariasHelper._normalize_key(str(value))

    for accepted in accepted_values:
        normalized_accepted = ComplementariasHelper._normalize_key(accepted)
        if not normalized_accepted:
            continue
        if normalized_value == normalized_accepted:
            return True
        if not normalized_accepted.isdigit() and normalized_value.endswith(normalized_accepted):
            return True

    return False


def _is_predio_nuevo(value: object, predio_nuevo_ids: set[str]) -> bool:
    return _matches_domain_value(value, predio_nuevo_ids | {"Predio_Nuevo", "Predio Nuevo"})

def _pos(texto: str | None, n: int) -> str | None:
    if not texto:
        return None
    texto = str(texto).strip()
    return texto[n - 1] if len(texto) >= n else None

def _get_tipo_planta_piso_ids(helper: ComplementariasHelper) -> set[str]:
    ids: set[str] = {"Piso", "piso", "1"}

    for _, row in helper._iter_table_rows((
        "ARB_ConstruccionPlantaTipo",
        "arb_construccionplantatipo",
        "ARB_UnidadConstruccionPlantaTipo",
        "ARB_PlantaTipo",
    )):
        ilicode = helper.get_field_value(row, ("iliCode", "ilicode"))
        t_id = helper.get_field_value(row, ("T_Id", "t_id", "id"))
        itf_code = helper.get_field_value(row, ("itfCode", "itfcode"))
        disp_name = helper.get_field_value(row, ("dispName", "dispname"))

        if _matches_domain_value(ilicode, {"Piso"}) or _matches_domain_value(disp_name, {"Piso"}):
            for v in (t_id, itf_code, ilicode, disp_name):
                if _is_not_empty(v):
                    ids.add(str(v).strip())

    return ids


def _is_tipo_planta_piso(value: object, tipo_piso_ids: set[str]) -> bool:
    return _matches_domain_value(value, tipo_piso_ids | {"Piso"})


def _get_construccion_por_unidad(helper: ComplementariasHelper) -> dict[str, str]:
    mapping: dict[str, str] = {}

    for _, row in helper.iter_construccion_unidad():
        construccion = helper.get_field_value(
            row,
            (
                "construccion",
                "Construccion",
                "arb_construccion",
                "ARB_Construccion",
            ),
        )
        unidad = helper.get_field_value(
            row,
            (
                "unidad_construccion",
                "Unidad_Construccion",
                "unidadconstruccion",
                "UnidadConstruccion",
                "unidad",
                "Unidad",
                "arb_unidadconstruccion",
                "ARB_UnidadConstruccion",
            ),
        )

        if _is_not_empty(construccion) and _is_not_empty(unidad):
            mapping[str(unidad).strip()] = str(construccion).strip()

    return mapping


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

    if len(polygons) > 1:
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
    if _is_empty(value):
        return None

    if hasattr(value, "intersects"):
        return value

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


def _safe_text(value: object) -> str:
    return "" if _is_empty(value) else str(value).strip()


def _geometry_signature(geom: object) -> str:
    for attr in ("wkb_hex", "wkt"):
        value = getattr(geom, attr, None)
        if value:
            return str(value)

    bounds = getattr(geom, "bounds", None)
    if bounds:
        return "|".join(str(item) for item in bounds)

    return str(id(geom))


def _has_area_superposition(geom_a: object, geom_b: object) -> bool:
    try:
        if not geom_a.intersects(geom_b):
            return False

        intersection = geom_a.intersection(geom_b)
        area = getattr(intersection, "area", 0)
        if callable(area):
            area = area()
        return float(area) > 0
    except Exception:
        return False


#---------------------------- reglas ------------------------------

def rule_10_1(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ComplementariasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, marca in helper.iter_marcas_prediales():
        resuelta_raw = helper.get_field_value(marca, ("resuelta",))

        valor = str(resuelta_raw).strip().lower()

        esta_resuelta = valor in {"true", "t", "1"}

        if not esta_resuelta:
            issues.append(
                helper.make_issue(
                    marca,
                    rule_id="10.1",
                    message=(
                        "Existen marcas prediales sin resolver, toda marca predial "
                        "debe estar resuelta para garantizar la calidad de los datos."
                    ),
                    details={
                        "tabla": table_name,
                        "resuelta": resuelta_raw,
                    },
                )
            )

    return issues

def rule_10_2(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ComplementariasHelper(dataset)
    issues: list[RuleIssue] = []

    predio_nuevo_ids = _get_predio_nuevo_ids(helper)

    for table_name, novedad in helper._iter_table_rows((
        "ARB_NovedadNumeroPredialValor",
        "arb_novedadnumeropredialvalor",
    )):
        tipo_novedad = helper.get_field_value(
            novedad,
            ("tipo_novedad",),
        )

        # ✅ solo si es Predio_Nuevo
        if not _is_predio_nuevo(tipo_novedad, predio_nuevo_ids):
            continue

        numero_predial = helper.get_field_value(
            novedad,
            ("numero_predial", "Numero_Predial", "numero_predial_nacional"),
        )

        pos_22 = _pos(numero_predial, 22)
        pos_18 = _pos(numero_predial, 18)

        if pos_22 == "2" and (pos_18 is None or not pos_18.isalpha()):
            issues.append(
                helper.make_issue(
                    novedad,
                    rule_id="10.2",
                    message=(
                        'El número predial debe contener un carácter alfabético '
                        'en la posición 18 cuando en la posición 22 tenga el valor "2" '
                        'y esté asociado a una novedad de tipo Predio Nuevo.'
                    ),
                    details={
                        "tabla": table_name,
                        "numero_predial": numero_predial,
                        "pos_18": pos_18,
                        "pos_22": pos_22,
                        "tipo_novedad_id": tipo_novedad,
                    },
                )
            )

    return issues

def rule_10_3(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ComplementariasHelper(dataset)
    issues: list[RuleIssue] = []

    tipo_piso_ids = _get_tipo_planta_piso_ids(helper)
    construccion_por_unidad = _get_construccion_por_unidad(helper)
    unidades: list[dict[str, object]] = []
    unidades_vistas: set[tuple[str, str, int, str]] = set()
    issues_emitidos: set[tuple[str, str, str, int, int, str]] = set()

    for table_name, unidad in helper.iter_unidades_construccion():
        planta_raw = helper.get_field_value(unidad, ("planta_ubicacion", "Planta_Ubicacion"))
        tipo_planta = helper.get_field_value(unidad, ("tipo_planta", "Tipo_Planta"))

        if not _is_not_empty(planta_raw) or not _is_not_empty(tipo_planta):
            continue

        if not _is_tipo_planta_piso(tipo_planta, tipo_piso_ids):
            continue

        geom_raw = helper.get_raw_field_value(
            unidad,
            ("geometria", "Geometria", "geometry", "geom", "localizacion", "Localizacion"),
        )
        geom = _load_geometry(geom_raw)

        if geom is None:
            continue

        try:
            planta = int(float(str(planta_raw).strip().replace(",", ".")))
        except Exception:
            continue

        unidad_id = helper.get_field_value(
            unidad,
            ("t_id", "T_Id", "TID", "id", "t_ili_tid"),
        )
        construccion = helper.get_field_value(
            unidad,
            ("construccion", "Construccion", "arb_construccion_unidadconstruccion"),
        )

        if _is_empty(construccion) and _is_not_empty(unidad_id):
            construccion = construccion_por_unidad.get(str(unidad_id).strip())

        identificador = helper.get_field_value(
            unidad,
            ("identificador", "Identificador", "t_id", "T_Id", "TID", "id", "t_ili_tid"),
        )

        unidad_key = (
            _safe_text(identificador or unidad_id),
            _safe_text(construccion),
            planta,
            _geometry_signature(geom),
        )

        if unidad_key in unidades_vistas:
            continue

        unidades_vistas.add(unidad_key)

        unidades.append({
            "row": unidad,
            "tabla": table_name,
            "planta": planta,
            "geom": geom,
            "construccion": construccion,
            "identificador": identificador or unidad_id,
        })

    for unidad in unidades:
        planta_superior = unidad["planta"]

        if planta_superior <= 1:
            continue

        planta_inferior = planta_superior - 1
        unidad_superior_id = unidad["identificador"]

        if _is_empty(unidad["construccion"]):
            issue_key = (
                _safe_text(unidad_superior_id),
                _geometry_signature(unidad["geom"]),
                _safe_text(unidad["construccion"]),
                planta_superior,
                planta_inferior,
                "sin_construccion",
            )

            if issue_key in issues_emitidos:
                continue

            issues_emitidos.add(issue_key)

            issues.append(
                helper.make_issue(
                    unidad["row"],
                    rule_id="10.3",
                    message=(
                        f"No fue posible resolver la construcción asociada a la unidad "
                        f"{unidad_superior_id} ubicada en la planta {planta_superior}. "
                        f"Esta condición impide validar la superposición con la planta "
                        f"{planta_inferior}."
                    ),
                    details={
                        "tabla": unidad["tabla"],
                        "unidad_superior": unidad_superior_id,
                        "planta_superior": planta_superior,
                        "construccion": unidad["construccion"],
                        "planta_inferior": planta_inferior,
                        "motivo": "Construcción no resuelta.",
                    },
                )
            )
            continue

        inferiores = [
            otra for otra in unidades
            if otra["planta"] == planta_inferior
            and otra["construccion"] == unidad["construccion"]
        ]

        ids_inferiores = [
            str(inferior["identificador"])
            for inferior in inferiores
            if _is_not_empty(inferior["identificador"])
        ]

        if not inferiores:
            issue_key = (
                _safe_text(unidad_superior_id),
                _geometry_signature(unidad["geom"]),
                _safe_text(unidad["construccion"]),
                planta_superior,
                planta_inferior,
                "sin_planta_inferior",
            )

            if issue_key in issues_emitidos:
                continue

            issues_emitidos.add(issue_key)

            issues.append(
                helper.make_issue(
                    unidad["row"],
                    rule_id="10.3",
                    message=(
                        f"La unidad {unidad_superior_id} ubicada en la planta "
                        f"{planta_superior} no tiene unidades asociadas en la planta "
                        f"inferior inmediata {planta_inferior} dentro de la misma "
                        f"construcción {unidad['construccion']}."
                    ),
                    details={
                        "tabla": unidad["tabla"],
                        "unidad_superior": unidad_superior_id,
                        "planta_superior": planta_superior,
                        "construccion": unidad["construccion"],
                        "planta_inferior": planta_inferior,
                        "unidades_inferiores": [],
                        "unidades_inferiores_revisadas": 0,
                        "motivo": "No existe unidad en la planta inferior inmediata.",
                    },
                )
            )
            continue

        tiene_superposicion = any(
            _has_area_superposition(unidad["geom"], inferior["geom"])
            for inferior in inferiores
        )

        if not tiene_superposicion:
            issue_key = (
                _safe_text(unidad_superior_id),
                _geometry_signature(unidad["geom"]),
                _safe_text(unidad["construccion"]),
                planta_superior,
                planta_inferior,
                "sin_superposicion",
            )

            if issue_key in issues_emitidos:
                continue

            issues_emitidos.add(issue_key)

            issues.append(
                helper.make_issue(
                    unidad["row"],
                    rule_id="10.3",
                    message=(
                        f"La unidad {unidad_superior_id} ubicada en la planta "
                        f"{planta_superior} no se superpone con área mayor a cero "
                        f"con las unidades de la planta inferior inmediata "
                        f"{planta_inferior}: {', '.join(ids_inferiores) or 'sin identificador'}."
                    ),
                    details={
                        "tabla": unidad["tabla"],
                        "unidad_superior": unidad_superior_id,
                        "planta_superior": planta_superior,
                        "construccion": unidad["construccion"],
                        "planta_inferior": planta_inferior,
                        "unidades_inferiores": ids_inferiores,
                        "unidades_inferiores_revisadas": len(inferiores),
                        "motivo": "Existe planta inferior, pero no hay superposición espacial con área mayor a cero.",
                    },
                )
            )

    return issues

def rule_10_4(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ComplementariasHelper(dataset)
    issues: list[RuleIssue] = []

    # 🔹 1. predios que tienen novedad
    predios_con_novedad: set[str] = set()

    for _, novedad in helper._iter_table_rows((
        "ARB_NovedadNumeroPredialValor",
        "arb_novedadnumeropredialvalor",
    )):
        predio_ref = helper.get_field_value(
            novedad,
            ("arb_predio_novedad_numero_predial", "predio", "arb_predio"),
        )

        if predio_ref:
            predios_con_novedad.add(str(predio_ref))

    # 🔹 2. validar predios
    for table_name, predio in helper.iter_predios():
        predio_id = helper.get_field_value(predio, ("t_id", "T_Id", "TID", "id", "id_operacion"))

        numero_predial = helper.get_field_value(
            predio,
            ("numero_predial", "Numero_Predial", "numero_predial_nacional"),
        )

        pos_18 = _pos(numero_predial, 18)

        # 🔴 condición de la regla
        if pos_18 and pos_18.isalpha():
            if not predio_id or str(predio_id) not in predios_con_novedad:
                issues.append(
                    helper.make_issue(
                        predio,
                        rule_id="10.4",
                        message=(
                            "Todo predio que tenga un carácter alfabético en la posición "
                            "18 del número predial debe estar asociado a una novedad "
                            "de número predial."
                        ),
                        details={
                            "tabla": table_name,
                            "predio_id": predio_id,
                            "numero_predial": numero_predial,
                            "posicion_18": pos_18,
                            "tiene_novedad": False,
                        },
                    )
                )

    return issues

RULE_FUNCTIONS = {
    "10.1": rule_10_1,
    "10.2": rule_10_2,
    "10.3": rule_10_3,
    "10.4": rule_10_4,
}

from __future__ import annotations
from shapely import wkb, wkt
from shapely.geometry import shape
from .base import DatasetReader, RuleIssue
import xml.etree.ElementTree as ET
from shapely.geometry import Polygon
from shapely.ops import unary_union

COMPONENT_SLUG = "fisico"

DEFAULT_RULE_IDS = frozenset({
    "3.1", "3.2", "3.3","3.4", "3.5","3.6","3.7", "3.8", "3.9", "3.10", 
    "3.11", "3.12","3.13", "3.14", "3.15", "3.16", "3.17", "3.18", "3.19", "3.20",
    "3.21",
})


class FisicoHelper:
    """Utilidades compartidas para reglas fisicas."""
    IDENTIFIER_FIELDS = (
        "t_ili_tid",
        "T_Ili_Tid",
        "T_ILI_TID",
        "id_operacion",
        "t_id",
        "TID",
    )

    PREDIO_TABLES = (
        "ARB_Predio",
        "arb_predio",
    )

    UNIDAD_CONSTRUCCION_TABLES = (
        "ARB_UnidadConstruccion",
        "arb_unidadconstruccion",
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

    def identify(self, row: dict[str, object]) -> str | None:
        for field in self.IDENTIFIER_FIELDS:
            value = row.get(field)
            if value not in (None, ""):
                return str(value).strip()

        return None

    def get_field_value(self, row: dict[str, object], candidates: tuple[str, ...]) -> str | None:
        normalized_candidates = {self._normalize_key(candidate) for candidate in candidates}

        for key, value in row.items():
            if self._normalize_key(str(key)) in normalized_candidates:
                if value not in (None, ""):
                    return str(value).strip()

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
        return "".join(ch for ch in text if ch.isalnum())


def _condicion_predio_ilicode(value: object) -> str:
    if value in (None, ""):
        return ""

    text = str(value).strip()

    mapping = {
        "1338": "PH.Matriz",
        "1339": "Condominio.Unidad_Predial",
        "1340": "Bien_Uso_Publico",
        "1341": "PH.Unidad_Predial",
        "1342": "Condominio.Matriz",
        "1343": "Parque_Cementerio.Matriz",
        "1344": "NPH",
        "1345": "Informal",
        "1346": "Parque_Cementerio.Unidad_Predial",
        "1347": "Via",

        "PH.Matriz": "PH.Matriz",
        "Condominio.Unidad_Predial": "Condominio.Unidad_Predial",
        "Bien_Uso_Publico": "Bien_Uso_Publico",
        "PH.Unidad_Predial": "PH.Unidad_Predial",
        "Condominio.Matriz": "Condominio.Matriz",
        "Parque_Cementerio.Matriz": "Parque_Cementerio.Matriz",
        "NPH": "NPH",
        "Informal": "Informal",
        "Parque_Cementerio.Unidad_Predial": "Parque_Cementerio.Unidad_Predial",
        "Via": "Via",
    }

    return mapping.get(text, text)

def _tipo_unidad_construccion_ilicode(value: object) -> str:
    if value in (None, ""):
        return ""

    text = str(value).strip()

    mapping = {
        # itfcode
        "0": "Residencial",
        "1": "Comercial",
        "2": "Conservacion_Proteccion_Ambiental",
        "3": "Industrial",
        "4": "Institucional",
        "5": "Anexo",

        # t_id
        "1348": "Conservacion_Proteccion_Ambiental",
        "1349": "Industrial",
        "1350": "Institucional",
        "1351": "Anexo",
        "1352": "Residencial",
        "1353": "Comercial",

        # ilicode
        "Residencial": "Residencial",
        "Comercial": "Comercial",
        "Conservacion_Proteccion_Ambiental": "Conservacion_Proteccion_Ambiental",
        "Industrial": "Industrial",
        "Institucional": "Institucional",
        "Anexo": "Anexo",
    }

    return mapping.get(text, text)


def _uso_unidad_es_ph_o_deposito_locker(value: object) -> bool:
    if value in (None, ""):
        return False

    text = str(value).strip()

    return text.endswith("_PH") or text == "Residencial.Depositos_Lockers"

def _uso_unidad_es_ph(value: object) -> bool:
    if value in (None, ""):
        return False

    text = str(value).strip()
    return text.endswith("_PH")

def _uso_pertenece_a_dominio(uso: object, dominio: str) -> bool:
    if uso in (None, ""):
        return False

    return str(uso).strip().startswith(f"{dominio}.")


def _to_int(value: object) -> int | None:
    if value in (None, ""):
        return None

    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None
    
def _to_float(value: object) -> float | None:
    if value in (None, ""):
        return None

    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None
    
def _validar_uso_por_tipo_unidad(
    dataset: DatasetReader,
    *,
    rule_id: str,
    tipo_esperado: str,
) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper._iter_table_rows((
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )):
        tipo_unidad = helper.get_field_value(row, ("tipo_unidad_construccion",))
        tipo_unidad_str = _tipo_unidad_construccion_ilicode(tipo_unidad)

        uso = helper.get_field_value(row, ("uso",))

        if tipo_unidad_str == tipo_esperado and not _uso_pertenece_a_dominio(uso, tipo_esperado):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id=rule_id,
                    message=(
                        f'Cuando el tipo de la unidad de construcción es "{tipo_esperado}", '
                        f'el uso debe coincidir con la clasificación de {tipo_esperado}.'
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_unidad_construccion": tipo_unidad,
                        "tipo_unidad_construccion_ilicode": tipo_unidad_str,
                        "uso": uso,
                    },
                )
            )

    return issues

def _destinacion_economica_ilicode(value: object) -> str:
    if value in (None, ""):
        return ""

    text = str(value).strip()

    mapping = {
        "1040": "Habitacional",
        "1069": "Comercial",
        "1042": "Industrial",
        "1044": "Institucional",
        "1064": "Cultural",
        "1070": "Educativo",
        "1067": "Religioso",

        "Habitacional": "Habitacional",
        "Comercial": "Comercial",
        "Industrial": "Industrial",
        "Institucional": "Institucional",
        "Cultural": "Cultural",
        "Educativo": "Educativo",
        "Religioso": "Religioso",
    }

    return mapping.get(text, text)


def _area_unidad(row: dict[str, object], helper: FisicoHelper) -> float:
    # 1. Si viene desde QGIS, usar exactamente la geometría de QGIS: $area
    feature = row.get("__qgis_feature__")
    if feature is not None:
        try:
            geom = feature.geometry()
            if geom is not None and not geom.isEmpty():
                return float(geom.area())
        except Exception:
            pass

    # 2. Si la geometría viene como campo QgsGeometry
    for key, value in row.items():
        if helper._normalize_key(str(key)) in {
            "geometria",
            "geometry",
            "geom",
            "thegeom",
            "wkbgeometry",
        }:
            geom_raw = value
            break
    else:
        return 0.0

    if geom_raw in (None, ""):
        return 0.0

    # QgsGeometry guardado directamente
    try:
        if hasattr(geom_raw, "area") and callable(geom_raw.area):
            return float(geom_raw.area())
    except Exception:
        pass

    # Shapely geometry
    try:
        if hasattr(geom_raw, "area") and not callable(geom_raw.area):
            return float(geom_raw.area)
    except Exception:
        pass

    text = str(geom_raw).strip()

    try:
        if text.upper().startswith(("POLYGON", "MULTIPOLYGON")):
            return float(wkt.loads(text).area)

        if text.startswith("<"):
            return float(_area_from_xtf_geometry(text))

        return float(wkb.loads(bytes.fromhex(text)).area)

    except Exception:
        return 0.0


def _clean_xml_tag(tag: str) -> str:
    if "}" in tag:
        tag = tag.split("}", 1)[1]
    if "." in tag:
        tag = tag.split(".")[-1]
    return tag.strip().lower()


def _area_from_xtf_geometry(xml_text: str) -> float:
    root = ET.fromstring(xml_text)

    rings: list[list[tuple[float, float]]] = []
    current_ring: list[tuple[float, float]] = []

    for node in root.iter():
        tag = _clean_xml_tag(node.tag)

        if tag == "coord":
            coords = {}

            for child in node:
                child_tag = _clean_xml_tag(child.tag)
                if child.text:
                    coords[child_tag] = child.text.strip()

            x = coords.get("c1")
            y = coords.get("c2")

            if x is not None and y is not None:
                current_ring.append((float(x), float(y)))

        elif tag in {"boundary", "polyline"}:
            if current_ring:
                rings.append(current_ring)
                current_ring = []

    if current_ring:
        rings.append(current_ring)

    fixed_rings: list[list[tuple[float, float]]] = []

    for ring in rings:
        if len(ring) < 3:
            continue

        if ring[0] != ring[-1]:
            ring = ring + [ring[0]]

        fixed_rings.append(ring)

    if not fixed_rings:
        return 0.0

    exterior = fixed_rings[0]
    holes = fixed_rings[1:]

    polygon = Polygon(exterior, holes)

    if not polygon.is_valid:
        polygon = polygon.buffer(0)

    return float(polygon.area)

def _build_ilicode_map(dataset: DatasetReader, table_name: str) -> dict[str, str]:
    mapping = {}

    for _, row in FisicoHelper(dataset)._iter_table_rows((table_name, table_name.lower())):
        t_id = row.get("t_id")
        ilicode = row.get("ilicode")

        if t_id and ilicode:
            mapping[str(t_id)] = str(ilicode).strip()

    return mapping

def _area_terreno(terreno: dict[str, object], helper: FisicoHelper) -> float | None:
    """Área geométrica exacta del terreno, sin redondear antes de aplicar la regla 3.5.

    La regla compara contra 2 m², por lo que redondear 1.99 a 2.0 produciría un
    falso negativo. Se aceptan geometrías QGIS/Shapely, WKT, WKB hexadecimal y
    el XML geométrico nativo del XTF.
    """
    feature = terreno.get("__qgis_feature__")
    if feature is not None:
        try:
            geom = feature.geometry()
            if geom is not None and not geom.isEmpty():
                return float(geom.area())
        except Exception:
            pass

    geometria = None
    wanted = {
        "geometria", "geometry", "geom", "thegeom", "wkbgeometry", "shape"
    }
    for key, value in terreno.items():
        if helper._normalize_key(str(key)) in wanted:
            geometria = value
            break

    if geometria is None or (isinstance(geometria, str) and geometria.strip() == ""):
        return None

    try:
        if hasattr(geometria, "area") and callable(geometria.area):
            return float(geometria.area())
    except Exception:
        pass

    try:
        if hasattr(geometria, "area") and not callable(geometria.area):
            return float(geometria.area)
    except Exception:
        pass

    if isinstance(geometria, dict):
        try:
            return float(shape(geometria).area)
        except Exception:
            return None

    text = str(geometria).strip()
    if not text:
        return None

    try:
        if text.upper().startswith(("POLYGON", "MULTIPOLYGON")):
            return float(wkt.loads(text).area)
        if text.startswith("<"):
            return float(_area_from_xtf_geometry(text))
        return float(wkb.loads(bytes.fromhex(text)).area)
    except Exception:
        return None


def _is_empty_value(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _all_row_keys(helper: FisicoHelper, row: dict[str, object], candidates: tuple[str, ...]) -> set[str]:
    wanted = {helper._normalize_key(name) for name in candidates}
    values: set[str] = set()
    for key, value in row.items():
        if helper._normalize_key(str(key)) in wanted and not _is_empty_value(value):
            values.add(str(value).strip())
    return values


def _index_rows_by_fields(helper: FisicoHelper, rows, fields):
    index = {}
    for table_name, row in rows:
        for key in _all_row_keys(helper, row, fields):
            index.setdefault(key, []).append((table_name, row))
    return index


def _unique_rows(index, refs):
    matches = []; seen = set()
    for ref in refs:
        for item in index.get(ref, []):
            rid = id(item[1])
            if rid not in seen:
                seen.add(rid); matches.append(item)
    return matches if len(matches) == 1 else []


def _iter_caracteristicas_con_predio(dataset: DatasetReader):
    """Relación real: Predio <- Construcción <- Unidad -> Característica.

    Se admiten vínculos directos y ID_Grupo=NPN solo como respaldos no ambiguos.
    """
    helper = FisicoHelper(dataset)
    predios = list(helper.iter_predios())
    construcciones = list(helper._iter_table_rows(("ARB_Construccion", "arb_construccion")))
    unidades = list(helper.iter_unidades_construccion())
    caracteristicas = list(helper._iter_table_rows(("ARB_CaracteristicasUnidadConstruccion", "arb_caracteristicasunidadconstruccion")))
    predio_id_index = _index_rows_by_fields(helper, predios, ("TID", "t_ili_tid", "t_id", "id"))
    predio_npn_index = _index_rows_by_fields(helper, predios, ("numero_predial", "Numero_Predial", "Numero_Predial_Nacional"))
    construccion_index = _index_rows_by_fields(helper, construcciones, ("TID", "t_ili_tid", "t_id", "id"))
    caracteristica_index = _index_rows_by_fields(helper, caracteristicas, ("TID", "t_ili_tid", "t_id", "id"))
    yielded = set()
    for unidad_table, unidad in unidades:
        car_refs = _all_row_keys(helper, unidad, ("caracteristicasunidadconstruccion", "caracteristicas_unidad_construccion"))
        car_matches = _unique_rows(caracteristica_index, car_refs)
        if not car_matches:
            continue
        caracteristica_table, caracteristica = car_matches[0]
        predio_matches = _unique_rows(predio_id_index, _all_row_keys(helper, unidad, ("predio", "arb_predio_unidadconstruccion", "arb_predio")))
        if not predio_matches:
            cons_matches = _unique_rows(construccion_index, _all_row_keys(helper, unidad, ("construccion", "arb_construccion_unidadconstruccion", "arb_construccion")))
            if cons_matches:
                _, construccion = cons_matches[0]
                predio_matches = _unique_rows(predio_id_index, _all_row_keys(helper, construccion, ("predio", "arb_predio_construccion", "arb_predio")))
        if not predio_matches:
            predio_matches = _unique_rows(predio_npn_index, _all_row_keys(helper, caracteristica, ("id_grupo", "ID_Grupo", "numero_predial")))
        if not predio_matches:
            continue
        predio_table, predio = predio_matches[0]
        key = (id(predio), id(unidad), id(caracteristica))
        if key in yielded:
            continue
        yielded.add(key)
        yield predio_table, predio, unidad_table, unidad, caracteristica_table, caracteristica



def _geometry_shape(row: dict[str, object], helper: FisicoHelper):
    """Devuelve una geometría Shapely sin alterar su precisión.

    Se usa únicamente para resolver excepciones espaciales de las reglas
    3.13-3.16. Acepta la geometría nativa del XTF, WKT/WKB, GeoJSON/dict y
    objetos Shapely. Si no se puede interpretar, devuelve None.
    """
    raw = None
    wanted = {"geometria", "geometry", "geom", "thegeom", "wkbgeometry", "shape"}
    for key, value in row.items():
        if helper._normalize_key(str(key)) in wanted:
            raw = value
            break
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None

    # Shapely u otro objeto geométrico compatible.
    try:
        if hasattr(raw, "geom_type") and hasattr(raw, "intersection"):
            return raw
    except Exception:
        pass

    if isinstance(raw, dict):
        try:
            return shape(raw)
        except Exception:
            return None

    text = str(raw).strip()
    if not text:
        return None
    try:
        if text.upper().startswith(("POLYGON", "MULTIPOLYGON")):
            return wkt.loads(text)
        if not text.startswith("<"):
            return wkb.loads(bytes.fromhex(text))
    except Exception:
        return None

    # Geometría XML INTERLIS/ISO19107 del XTF. Cada SURFACE puede tener
    # varias BOUNDARY; la primera es exterior y las siguientes son huecos.
    try:
        root = ET.fromstring(text)
        surfaces = [node for node in root.iter() if _clean_xml_tag(node.tag) == "surface"]
        if not surfaces:
            surfaces = [root]
        polygons = []
        for surface in surfaces:
            rings = []
            boundaries = [node for node in surface.iter() if _clean_xml_tag(node.tag) == "boundary"]
            if not boundaries:
                boundaries = [surface]
            for boundary in boundaries:
                ring = []
                for node in boundary.iter():
                    if _clean_xml_tag(node.tag) != "coord":
                        continue
                    coords = {}
                    for child in node:
                        if child.text:
                            coords[_clean_xml_tag(child.tag)] = child.text.strip()
                    if coords.get("c1") is not None and coords.get("c2") is not None:
                        ring.append((float(coords["c1"]), float(coords["c2"])))
                if len(ring) >= 3:
                    if ring[0] != ring[-1]:
                        ring.append(ring[0])
                    rings.append(ring)
            if rings:
                poly = Polygon(rings[0], rings[1:])
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if not poly.is_empty:
                    polygons.append(poly)
        if not polygons:
            return None
        return polygons[0] if len(polygons) == 1 else unary_union(polygons)
    except Exception:
        return None


def _predios_exentos_por_unidades_informales(dataset: DatasetReader) -> set[str]:
    """Predios formales sin unidad propia cubiertos por unidades informales.

    La excepción textual de 3.13-3.16 solo es aplicable cuando puede
    demostrarse espacialmente: una unidad asociada a un predio Informal tiene
    intersección de área positiva con el terreno del predio formal. No se usa
    una mera existencia global de predios informales porque eso eximiría
    predios no relacionados y generaría falsos negativos.
    """
    helper = FisicoHelper(dataset)
    predios = list(helper.iter_predios())
    predio_id_index = _index_rows_by_fields(
        helper, predios, ("TID", "t_ili_tid", "t_id", "id", "id_operacion")
    )

    terrenos_por_predio: dict[int, list[object]] = {}
    for _, terreno in helper._iter_table_rows(("ARB_Terreno", "arb_terreno", "Terreno", "terreno")):
        predio_matches = _unique_rows(
            predio_id_index,
            _all_row_keys(helper, terreno, ("predio", "arb_predio", "id_predio", "Id_Predio")),
        )
        if not predio_matches:
            continue
        _, predio = predio_matches[0]
        geom = _geometry_shape(terreno, helper)
        if geom is not None:
            terrenos_por_predio.setdefault(id(predio), []).append(geom)

    unidades_informales = []
    seen_units = set()
    for _, predio, _, unidad, _, _ in _iter_caracteristicas_con_predio(dataset):
        condicion_raw = helper.get_field_value(predio, ("condicion_predio", "Condicion_Predio"))
        if _condicion_predio_ilicode(condicion_raw) != "Informal":
            continue
        uid = helper.identify(unidad) or str(id(unidad))
        if uid in seen_units:
            continue
        seen_units.add(uid)
        geom = _geometry_shape(unidad, helper)
        if geom is not None:
            unidades_informales.append(geom)

    if not unidades_informales:
        return set()

    exentos: set[str] = set()
    for _, predio in predios:
        condicion_raw = helper.get_field_value(predio, ("condicion_predio", "Condicion_Predio"))
        if _condicion_predio_ilicode(condicion_raw) == "Informal":
            continue
        terrenos = terrenos_por_predio.get(id(predio), [])
        if not terrenos:
            continue
        encontrado = False
        for terreno_geom in terrenos:
            for unidad_geom in unidades_informales:
                try:
                    inter = terreno_geom.intersection(unidad_geom)
                    if not inter.is_empty and float(inter.area) > 1e-8:
                        encontrado = True
                        break
                except Exception:
                    continue
            if encontrado:
                break
        if encontrado:
            key = helper.identify(predio)
            if key:
                exentos.add(key)
    return exentos


def _dominio_uso_unidad(value: object) -> str:
    if _is_empty_value(value):
        return ""
    prefix = str(value).strip().split(".", 1)[0]
    return prefix if prefix in {"Anexo", "Comercial", "Industrial", "Institucional", "Residencial"} else ""


def _clasificacion_predominancia(helper: FisicoHelper, caracteristica: dict[str, object]):
    tipo_raw = helper.get_field_value(caracteristica, ("tipo_unidad_construccion",))
    tipo = _tipo_unidad_construccion_ilicode(tipo_raw)
    uso = helper.get_field_value(caracteristica, ("uso",))
    dominio_uso = _dominio_uso_unidad(uso)
    return dominio_uso or tipo or "Sin_clasificar", {
        "tipo_unidad_construccion": tipo_raw, "tipo_unidad_construccion_ilicode": tipo,
        "uso": uso, "dominio_uso": dominio_uso,
    }


def _validar_destinacion_vs_tipo_predominante(dataset: DatasetReader, *, rule_id: str, destinaciones_aplican: set[str], tipo_requerido: str, mensaje_existencia: str, mensaje_predominancia: str) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []
    datos_por_predio: dict[str, dict[str, object]] = {}

    # Registrar primero TODOS los predios a los que aplica la destinación.
    # Así un predio sin ninguna unidad no queda invisible para la regla.
    for predio_table, predio in helper.iter_predios():
        destinacion_raw = helper.get_field_value(predio, ("destinacion_economica", "Destinacion_Economica"))
        destinacion = _destinacion_economica_ilicode(destinacion_raw)
        if destinacion not in destinaciones_aplican:
            continue
        predio_key = helper.identify(predio) or str(id(predio))
        datos_por_predio[predio_key] = {
            "predio": predio,
            "tabla": predio_table,
            "destinacion": destinacion_raw,
            "destinacion_str": destinacion,
            "areas": {},
            "tiene": False,
            "clasificaciones": [],
            "cantidad_unidades": 0,
        }

    # Agregar las unidades correctamente relacionadas Predio <- Construcción <- Unidad.
    unidades_vistas: dict[str, set[str]] = {}
    for _, predio, unidad_table, unidad, caracteristica_table, caracteristica in _iter_caracteristicas_con_predio(dataset):
        predio_key = helper.identify(predio) or str(id(predio))
        datos = datos_por_predio.get(predio_key)
        if datos is None:
            continue
        uid = helper.identify(unidad) or str(id(unidad))
        vistos = unidades_vistas.setdefault(predio_key, set())
        if uid not in vistos:
            vistos.add(uid)
            datos["cantidad_unidades"] = int(datos["cantidad_unidades"]) + 1

        clasificacion, detalles = _clasificacion_predominancia(helper, caracteristica)
        area = _area_unidad(unidad, helper)
        if area <= 0:
            area = _to_float(helper.get_field_value(caracteristica, ("area_construida",))) or 0.0
        areas = datos["areas"]
        assert isinstance(areas, dict)
        areas[clasificacion] = float(areas.get(clasificacion, 0.0)) + area
        datos["tiene"] = bool(datos["tiene"]) or clasificacion == tipo_requerido
        clasificaciones = datos["clasificaciones"]
        assert isinstance(clasificaciones, list)
        clasificaciones.append({
            "tabla": caracteristica_table,
            "unidad_tabla": unidad_table,
            "area": area,
            "clasificacion": clasificacion,
            **detalles,
        })

    # Excepción descrita por las reglas: predio formal sin unidad propia cuando
    # existen unidades de predios informales espacialmente sobre su terreno.
    exentos_informales = _predios_exentos_por_unidades_informales(dataset)

    for predio_key, datos in datos_por_predio.items():
        predio = datos["predio"]
        assert isinstance(predio, dict)
        numero_predial = helper.get_field_value(predio, ("numero_predial", "Numero_Predial"))

        if int(datos["cantidad_unidades"]) == 0:
            condicion = _condicion_predio_ilicode(
                helper.get_field_value(predio, ("condicion_predio", "Condicion_Predio"))
            )
            if condicion != "Informal" and predio_key in exentos_informales:
                continue
            issues.append(helper.make_issue(
                predio,
                rule_id=rule_id,
                message=mensaje_existencia,
                details={
                    "tabla": datos["tabla"],
                    "numero_predial": numero_predial,
                    "destinacion_economica": datos["destinacion"],
                    "destinacion_economica_ilicode": datos["destinacion_str"],
                    "validacion": f"existencia_tipo_{tipo_requerido.lower()}",
                    "motivo": "predio_sin_unidades_construccion",
                    "clasificaciones": [],
                },
            ))
            continue

        if not bool(datos["tiene"]):
            issues.append(helper.make_issue(
                predio,
                rule_id=rule_id,
                message=mensaje_existencia,
                details={
                    "tabla": datos["tabla"],
                    "numero_predial": numero_predial,
                    "destinacion_economica": datos["destinacion"],
                    "destinacion_economica_ilicode": datos["destinacion_str"],
                    "validacion": f"existencia_tipo_{tipo_requerido.lower()}",
                    "clasificaciones": datos["clasificaciones"],
                },
            ))
            continue

        areas = datos["areas"]
        assert isinstance(areas, dict)
        area_req = float(areas.get(tipo_requerido, 0.0))
        otras = {k: float(v) for k, v in areas.items() if k != tipo_requerido}
        if otras:
            tipo_mayor, area_mayor = max(otras.items(), key=lambda x: x[1])
            if area_mayor > area_req + 0.1:
                issues.append(helper.make_issue(
                    predio,
                    rule_id=rule_id,
                    message=mensaje_predominancia,
                    details={
                        "tabla": datos["tabla"],
                        "numero_predial": numero_predial,
                        "destinacion_economica": datos["destinacion"],
                        "destinacion_economica_ilicode": datos["destinacion_str"],
                        "tipo_predominante": tipo_mayor,
                        "area_tipo_requerido": area_req,
                        "area_tipo_predominante": area_mayor,
                        "areas_por_tipo": areas,
                        "validacion": f"predominancia_area_{tipo_requerido.lower()}",
                        "clasificaciones": datos["clasificaciones"],
                    },
                ))
    return issues

# -------------------- Reglas --------------------

def _rule_3_1(dataset: DatasetReader) -> list[RuleIssue]:
    """PH.Unidad_Predial debe tener al menos una UnidadConstruccion asociada.

    La relación del XTF es Predio -> Construccion -> UnidadConstruccion.
    Se exceptúan parqueaderos o garajes descubiertos identificables de forma
    objetiva por la dirección asociada (PQ/Parqueadero o GA/Garaje) cuando no
    existe UnidadConstruccion. Las unidades PH no construidas solo se excluyen
    si el modelo aporta un atributo objetivo que permita identificarlas.
    """
    import re

    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []

    construccion_a_predio: dict[str, str] = {}
    predios_con_unidad: set[str] = set()
    predios_parqueadero_garaje: set[str] = set()

    # 1) Construccion -> Predio
    for _, construccion in helper._iter_table_rows(("ARB_Construccion", "arb_construccion")):
        construccion_id = helper.get_field_value(construccion, ("TID", "t_id", "id"))
        predio_ref = helper.get_field_value(
            construccion,
            ("predio", "arb_predio", "id_predio", "Id_Predio"),
        )
        if construccion_id and predio_ref:
            construccion_a_predio[str(construccion_id)] = str(predio_ref)

    # 2) UnidadConstruccion -> Construccion -> Predio
    for _, unidad in helper.iter_unidades_construccion():
        construccion_ref = helper.get_field_value(
            unidad,
            ("construccion", "arb_construccion", "id_construccion", "Id_Construccion"),
        )
        if not construccion_ref:
            continue
        predio_ref = construccion_a_predio.get(str(construccion_ref))
        if predio_ref:
            predios_con_unidad.add(predio_ref)

    # 3) Identificar de forma objetiva parqueaderos/garajes por la direccion.
    # PQ = Parqueadero y GA = Garaje (abreviaturas usadas por el propio modelo).
    patron_excepcion = re.compile(r"(?:^|[^A-Z0-9])(PQ|PARQUEADERO|GA|GARAJE)(?:[^A-Z0-9]|$)", re.IGNORECASE)
    for _, direccion in helper._iter_table_rows(("ARB_Direccion", "arb_direccion", "ARB_Dirección", "arb_dirección")):
        predio_ref = helper.get_field_value(
            direccion,
            (
                "predio", "arb_predio", "arb_predio_direccion",
                "predio_asociado", "id_predio", "Id_Predio",
            ),
        )
        if not predio_ref:
            continue

        texto_direccion = helper.get_field_value(
            direccion,
            (
                "complemento", "Complemento",
                "nombre_predio", "Nombre_Predio",
                "direccion", "Direccion",
            ),
        )
        if texto_direccion and patron_excepcion.search(str(texto_direccion).upper()):
            predios_parqueadero_garaje.add(str(predio_ref))

    # 4) Evaluar únicamente PH.Unidad_Predial
    for table_name, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        numero_predial = helper.get_field_value(
            row,
            ("numero_predial", "Numero_Predial", "Numero_Predial_Nacional"),
        )
        condicion_predio = helper.get_field_value(row, ("condicion_predio", "Condicion_Predio"))
        condicion_predio_str = _condicion_predio_ilicode(condicion_predio)

        if condicion_predio_str != "PH.Unidad_Predial" or not predio_id:
            continue

        predio_id_str = str(predio_id)
        if predio_id_str in predios_con_unidad:
            continue

        # Excepción explícita de la regla: parqueadero/garaje descubierto.
        # Si no hay UnidadConstruccion y la dirección lo identifica como PQ/GA,
        # no se reporta como incumplimiento de 3.1.
        if predio_id_str in predios_parqueadero_garaje:
            continue

        issues.append(
            helper.make_issue(
                row,
                rule_id="3.1",
                message=(
                    "El predio con condición PH.Unidad_Predial debe tener asociada "
                    "al menos una unidad de construcción."
                ),
                details={
                    "tabla": table_name,
                    "numero_predial": numero_predial,
                    "condicion_predio": condicion_predio,
                    "condicion_predio_ilicode": condicion_predio_str,
                    "predio_id": predio_id,
                },
            )
        )

    return issues

def _rule_3_2(dataset: DatasetReader) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []
    condiciones_ph_condominio = {
        "PH.Matriz", "PH.Unidad_Predial", "Condominio.Matriz", "Condominio.Unidad_Predial",
    }
    tipos_convencionales = {"Residencial", "Comercial", "Industrial", "Institucional"}
    for _, predio, unidad_table, unidad, caracteristica_table, caracteristica in _iter_caracteristicas_con_predio(dataset):
        condicion_raw = helper.get_field_value(predio, ("condicion_predio", "Condicion_Predio"))
        condicion = _condicion_predio_ilicode(condicion_raw)
        tipo_raw = helper.get_field_value(caracteristica, ("tipo_unidad_construccion",))
        tipo = _tipo_unidad_construccion_ilicode(tipo_raw)
        uso = helper.get_field_value(caracteristica, ("uso",))
        if condicion in condiciones_ph_condominio and tipo in tipos_convencionales and not _uso_unidad_es_ph_o_deposito_locker(uso):
            issues.append(helper.make_issue(
                caracteristica, rule_id="3.2",
                message=("Toda unidad de construcción asociada a un predio con condición PH o Condominio "
                         "debe relacionar usos establecidos específicamente para PH o Depósitos_Lockers."),
                details={"tabla": caracteristica_table, "unidad_tabla": unidad_table,
                         "condicion_predio": condicion_raw, "condicion_predio_ilicode": condicion,
                         "tipo_unidad_construccion": tipo_raw, "tipo_unidad_construccion_ilicode": tipo, "uso": uso},
            ))
    return issues

def _rule_3_3(dataset: DatasetReader) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []
    condiciones_ph_condominio = {
        "PH.Matriz", "PH.Unidad_Predial", "Condominio.Matriz", "Condominio.Unidad_Predial",
    }
    tipos_convencionales = {"Residencial", "Comercial", "Industrial", "Institucional"}
    for _, predio, unidad_table, unidad, caracteristica_table, caracteristica in _iter_caracteristicas_con_predio(dataset):
        condicion_raw = helper.get_field_value(predio, ("condicion_predio", "Condicion_Predio"))
        condicion = _condicion_predio_ilicode(condicion_raw)
        if not condicion:
            continue
        tipo_raw = helper.get_field_value(caracteristica, ("tipo_unidad_construccion",))
        tipo = _tipo_unidad_construccion_ilicode(tipo_raw)
        uso = helper.get_field_value(caracteristica, ("uso",))
        if condicion not in condiciones_ph_condominio and tipo in tipos_convencionales and _uso_unidad_es_ph(uso):
            issues.append(helper.make_issue(
                caracteristica, rule_id="3.3",
                message=("Toda unidad de construcción asociada a un predio con condición diferente a PH "
                         "o Condominio no debe relacionar usos de PH."),
                details={"tabla": caracteristica_table, "unidad_tabla": unidad_table,
                         "condicion_predio": condicion_raw, "condicion_predio_ilicode": condicion,
                         "tipo_unidad_construccion": tipo_raw, "tipo_unidad_construccion_ilicode": tipo, "uso": uso},
            ))
    return issues

def _rule_3_5(dataset: DatasetReader) -> list[RuleIssue]:
    """No debe haber polígonos de terreno menores a 2 m²."""
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []
    for table_name, terreno in helper._iter_table_rows(("ARB_Terreno", "arb_terreno", "Terreno", "terreno")):
        area = _area_terreno(terreno, helper)
        if area is None:
            continue
        area_calculada = round(area, 2)
        if area_calculada < 2:
            issues.append(helper.make_issue(
                terreno, rule_id="3.5",
                message=("Error en área de terreno: no debe haber polígonos de terreno menores a 2 m². "
                         f"Área calculada: {area_calculada} m²."),
                details={"tabla": table_name,
                         "terreno_id": helper.get_field_value(terreno, ("TID", "t_id", "id", "identificador", "etiqueta")),
                         "area_calculada": area_calculada, "area_minima_permitida": 2},
            ))
    return issues

def _rule_3_7(dataset: DatasetReader) -> list[RuleIssue]:
    return _validar_uso_por_tipo_unidad(
        dataset,
        rule_id="3.7",
        tipo_esperado="Anexo",
    )


def _rule_3_8(dataset: DatasetReader) -> list[RuleIssue]:
    return _validar_uso_por_tipo_unidad(
        dataset,
        rule_id="3.8",
        tipo_esperado="Comercial",
    )


def _rule_3_9(dataset: DatasetReader) -> list[RuleIssue]:
    return _validar_uso_por_tipo_unidad(
        dataset,
        rule_id="3.9",
        tipo_esperado="Industrial",
    )


def _rule_3_10(dataset: DatasetReader) -> list[RuleIssue]:
    return _validar_uso_por_tipo_unidad(
        dataset,
        rule_id="3.10",
        tipo_esperado="Institucional",
    )


def _rule_3_11(dataset: DatasetReader) -> list[RuleIssue]:
    return _validar_uso_por_tipo_unidad(
        dataset,
        rule_id="3.11",
        tipo_esperado="Residencial",
    )

def _rule_3_12(dataset: DatasetReader) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_unidades_construccion():
        planta_raw = helper.get_field_value(row, ("planta_ubicacion",))
        planta = _to_int(planta_raw)

        if planta is not None and planta <= 0:
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="3.12",
                    message=(
                        "La planta de ubicación de la unidad de construcción "
                        "no puede ser cero ni negativa."
                    ),
                    details={
                        "tabla": table_name,
                        "planta_ubicacion": planta_raw,
                    },
                )
            )

    return issues

def _rule_3_13(dataset: DatasetReader) -> list[RuleIssue]:
    return _validar_destinacion_vs_tipo_predominante(
        dataset, rule_id="3.13", destinaciones_aplican={"Habitacional"}, tipo_requerido="Residencial",
        mensaje_existencia="El predio con destinación económica Habitacional debe tener al menos una unidad de construcción con característica de tipo Residencial.",
        mensaje_predominancia="El predio con destinación económica Habitacional tiene unidad de construcción Residencial, pero esta no es predominante en área frente a las demás.",
    )

def _rule_3_14(dataset: DatasetReader) -> list[RuleIssue]:
    return _validar_destinacion_vs_tipo_predominante(
        dataset, rule_id="3.14", destinaciones_aplican={"Comercial"}, tipo_requerido="Comercial",
        mensaje_existencia="El predio con destinación económica Comercial debe tener al menos una unidad de construcción con característica de tipo Comercial.",
        mensaje_predominancia="El predio con destinación económica Comercial tiene unidad de construcción Comercial, pero esta no es predominante en área frente a las demás.",
    )

def _rule_3_15(dataset: DatasetReader) -> list[RuleIssue]:
    return _validar_destinacion_vs_tipo_predominante(
        dataset, rule_id="3.15", destinaciones_aplican={"Industrial"}, tipo_requerido="Industrial",
        mensaje_existencia="El predio con destinación económica Industrial debe tener al menos una unidad de construcción con característica de tipo Industrial.",
        mensaje_predominancia="El predio con destinación económica Industrial tiene unidad de construcción Industrial, pero esta no es predominante en área frente a las demás.",
    )

def _rule_3_16(dataset: DatasetReader) -> list[RuleIssue]:
    return _validar_destinacion_vs_tipo_predominante(
        dataset, rule_id="3.16", destinaciones_aplican={"Institucional", "Cultural", "Educativo", "Religioso"}, tipo_requerido="Institucional",
        mensaje_existencia="El predio con destinación económica Institucional, Cultural, Educativo o Religioso debe tener al menos una unidad de construcción con característica de tipo Institucional.",
        mensaje_predominancia="El predio con destinación económica Institucional, Cultural, Educativo o Religioso tiene unidad de construcción Institucional, pero esta no es predominante en área frente a las demás.",
    )



def _rule_3_17(dataset: DatasetReader) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper._iter_table_rows((
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )):
        total_raw = helper.get_field_value(row, ("total_plantas",))
        total = _to_int(total_raw)

        if total is None or total <= 0:
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="3.17",
                    message=(
                        "El total de plantas de la característica de la unidad "
                        "de construcción debe estar diligenciado y ser mayor a cero."
                    ),
                    details={
                        "tabla": table_name,
                        "total_plantas": total_raw,
                    },
                )
            )

    return issues

def _resolve_predio_ref_desde_unidad(
    helper: FisicoHelper,
    unidad: dict[str, object],
    construccion_a_predio: dict[str, str],
) -> str | None:
    """Resuelve el predio de una unidad usando las relaciones reales del XTF.

    Ruta preferida del modelo: UnidadConstruccion -> Construccion -> Predio.
    Se conserva la relación directa como respaldo para datasets ya aplanados.
    """
    predio_ref = helper.get_field_value(
        unidad,
        ("predio", "arb_predio_unidadconstruccion", "arb_predio"),
    )
    if predio_ref:
        return str(predio_ref)

    construccion_ref = helper.get_field_value(
        unidad,
        ("construccion", "arb_construccion_unidadconstruccion", "arb_construccion"),
    )
    if not construccion_ref:
        return None

    return construccion_a_predio.get(str(construccion_ref))


def _construccion_a_predio(helper: FisicoHelper) -> dict[str, str]:
    relacion: dict[str, str] = {}

    for _, construccion in helper._iter_table_rows((
        "ARB_Construccion",
        "arb_construccion",
    )):
        construccion_id = helper.get_field_value(
            construccion,
            ("TID", "t_id", "id", "t_ili_tid"),
        )
        predio_ref = helper.get_field_value(
            construccion,
            ("predio", "arb_predio_construccion", "arb_predio"),
        )
        if construccion_id and predio_ref:
            relacion[str(construccion_id)] = str(predio_ref)

    return relacion


def _rule_3_18(dataset: DatasetReader) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []
    condiciones = {"PH.Unidad_Predial", "Condominio.Unidad_Predial"}
    for _, predio, unidad_table, unidad, caracteristica_table, caracteristica in _iter_caracteristicas_con_predio(dataset):
        condicion_raw = helper.get_field_value(predio, ("condicion_predio", "Condicion_Predio"))
        condicion = _condicion_predio_ilicode(condicion_raw)
        if condicion not in condiciones:
            continue
        area_construida_raw = helper.get_field_value(caracteristica, ("area_construida",))
        area_privada_raw = helper.get_field_value(caracteristica, ("area_privada_construida",))
        area_construida = _to_float(area_construida_raw)
        area_privada = _to_float(area_privada_raw)
        if area_construida != 0 or area_privada is None or area_privada <= 0:
            issues.append(helper.make_issue(
                caracteristica, rule_id="3.18",
                message="Para PH unidad predial y Condominio unidad predial, el área construida debe ser cero y el área privada construida debe ser mayor a cero.",
                details={"tabla": caracteristica_table, "unidad_tabla": unidad_table,
                         "condicion_predio": condicion_raw, "condicion_predio_ilicode": condicion,
                         "area_construida": area_construida_raw, "area_privada_construida": area_privada_raw},
            ))
    return issues

def _rule_3_19(dataset: DatasetReader) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []
    condiciones_unidad = {"PH.Unidad_Predial", "Condominio.Unidad_Predial"}
    for _, predio, unidad_table, unidad, caracteristica_table, caracteristica in _iter_caracteristicas_con_predio(dataset):
        condicion_raw = helper.get_field_value(predio, ("condicion_predio", "Condicion_Predio"))
        condicion = _condicion_predio_ilicode(condicion_raw)
        if not condicion or condicion in condiciones_unidad:
            continue
        area_construida_raw = helper.get_field_value(caracteristica, ("area_construida",))
        area_privada_raw = helper.get_field_value(caracteristica, ("area_privada_construida",))
        area_construida = _to_float(area_construida_raw)
        if area_construida is None or area_construida <= 0 or not _is_empty_value(area_privada_raw):
            issues.append(helper.make_issue(
                caracteristica, rule_id="3.19",
                message="Para predios con condición diferente a PH unidad predial o Condominio unidad predial, el área construida debe ser mayor a cero y el área privada construida debe ser NULL.",
                details={"tabla": caracteristica_table, "unidad_tabla": unidad_table,
                         "condicion_predio": condicion_raw, "condicion_predio_ilicode": condicion,
                         "area_construida": area_construida_raw, "area_privada_construida": area_privada_raw},
            ))
    return issues

def _rule_3_20(dataset: DatasetReader) -> list[RuleIssue]:
    """Compara el área declarada con la suma geométrica de las unidades (tolerancia 1%).

    Para PH/Condominio Unidad_Predial se compara Área_Privada_Construida, porque
    3.18 exige que Área_Construida sea cero. Para las demás condiciones se usa
    Área_Construida.
    """
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []
    condiciones_privada = {"PH.Unidad_Predial", "Condominio.Unidad_Predial"}
    groups: dict[tuple[str, str], dict[str, object]] = {}
    for _, predio, _, unidad, caracteristica_table, caracteristica in _iter_caracteristicas_con_predio(dataset):
        predio_key = helper.identify(predio) or str(id(predio))
        car_key = helper.identify(caracteristica) or str(id(caracteristica))
        key = (predio_key, car_key)
        item = groups.setdefault(key, {"predio": predio, "caracteristica": caracteristica,
                                       "tabla": caracteristica_table, "area": 0.0, "unidades": set()})
        unidades = item["unidades"]
        assert isinstance(unidades, set)
        uid = helper.identify(unidad) or str(id(unidad))
        if uid in unidades:
            continue
        unidades.add(uid)
        item["area"] = float(item["area"]) + _area_unidad(unidad, helper)
    for item in groups.values():
        predio = item["predio"]; caracteristica = item["caracteristica"]
        assert isinstance(predio, dict) and isinstance(caracteristica, dict)
        condicion_raw = helper.get_field_value(predio, ("condicion_predio", "Condicion_Predio"))
        condicion = _condicion_predio_ilicode(condicion_raw)
        usa_privada = condicion in condiciones_privada
        campo = "area_privada_construida" if usa_privada else "area_construida"
        declarada_raw = helper.get_field_value(caracteristica, (campo,))
        declarada = _to_float(declarada_raw)
        if declarada is None:
            continue
        geom = float(item["area"]); decl = float(declarada)
        porcentaje = (0.0 if geom == 0 else float("inf")) if decl == 0 else abs(decl - geom) / abs(decl) * 100.0
        if porcentaje > 1.0:
            issues.append(helper.make_issue(
                caracteristica, rule_id="3.20",
                message=(f"Error en área {'privada construida' if usa_privada else 'construida'}: el valor diligenciado "
                         f"({round(decl, 4)}) no coincide, dentro de la tolerancia del 1%, con el área calculada de las unidades ({round(geom, 4)})."),
                details={"tabla": item["tabla"], "condicion_predio": condicion_raw,
                         "condicion_predio_ilicode": condicion, "campo_comparado": campo,
                         "area_declarada": round(decl, 6), "area_total_calculada": round(geom, 6),
                         "diferencia": round(decl - geom, 2),
                         "diferencia_porcentual": None if porcentaje == float("inf") else round(porcentaje, 4),
                         "tolerancia_porcentual": 1.0},
            ))
    return issues

def _rule_3_21(dataset: DatasetReader) -> list[RuleIssue]:
    #sin defenir
    return []

RULE_FUNCTIONS = {
    "3.1": _rule_3_1,
    "3.2": _rule_3_2,
    "3.3": _rule_3_3,
    "3.5": _rule_3_5,
    "3.7": _rule_3_7,
    "3.8": _rule_3_8,
    "3.9": _rule_3_9,
    "3.10": _rule_3_10,
    "3.11": _rule_3_11,
    "3.12": _rule_3_12,
    "3.13": _rule_3_13,
    "3.14": _rule_3_14,
    "3.15": _rule_3_15,
    "3.16": _rule_3_16,
    "3.17": _rule_3_17,
    "3.18": _rule_3_18,
    "3.19": _rule_3_19,
    "3.20": _rule_3_20,
}

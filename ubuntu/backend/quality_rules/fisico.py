from __future__ import annotations
from shapely import wkb, wkt
from shapely.geometry import shape
from .base import DatasetReader, RuleIssue
import xml.etree.ElementTree as ET
from shapely.geometry import Polygon

COMPONENT_SLUG = "fisico"

DEFAULT_RULE_IDS = frozenset({
    "3.1", "3.2", "3.3","3.4", "3.5","3.6","3.7", "3.8", "3.9", "3.10", 
    "3.11", "3.12","3.13", "3.14", "3.15", "3.16", "3.17", "3.18", "3.19", "3.20",
    "3.21",
})


class FisicoHelper:
    """Utilidades compartidas para reglas fisicas."""
    IDENTIFIER_FIELDS = (
        "id_operacion",
        "t_id",
        "TID",
        "t_ili_tid",
        "numero_predial",
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
    geom_raw = None

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

    if geom_raw in (None, ""):
        return 0.0

    text = str(geom_raw).strip()

    try:
        if text.upper().startswith(("POLYGON", "MULTIPOLYGON")):
            return float(wkt.loads(text).area)

        if text.startswith("<"):
            return _area_from_xtf_geometry(text)

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

    if not rings:
        return 0.0

    exterior = rings[0]

    if len(exterior) < 3:
        return 0.0

    if exterior[0] != exterior[-1]:
        exterior.append(exterior[0])

    polygon = Polygon(exterior)

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
    geometria = helper.get_field_value(
        terreno,
        (
            "geometria",
            "geometry",
            "geom",
            "wkb_geometry",
            "SHAPE",
            "shape",
        ),
    )

    if geometria is None:
        return None

    try:
        if hasattr(geometria, "area"):
            return float(geometria.area)

        if isinstance(geometria, dict):
            from shapely.geometry import shape

            return float(shape(geometria).area)

        if isinstance(geometria, str):
            from shapely import wkt

            return float(wkt.loads(geometria).area)

    except Exception:
        return None

    return None
# -------------------- Reglas --------------------

def _rule_3_1(dataset: DatasetReader) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_con_unidad: set[str] = set()

    for _, row in helper.iter_unidades_construccion():
        predio_ref = helper.get_field_value(row, ("predio",))
        if predio_ref:
            predios_con_unidad.add(str(predio_ref))

    for table_name, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        numero_predial = helper.get_field_value(row, ("numero_predial", "Numero_Predial"))
        condicion_predio = helper.get_field_value(row, ("condicion_predio", "Condicion_Predio"))
        condicion_predio_str = _condicion_predio_ilicode(condicion_predio)

        if condicion_predio_str == "PH.Unidad_Predial":
            if predio_id and str(predio_id) not in predios_con_unidad:
                issues.append(
                    helper.make_issue(
                        row,
                        rule_id="3.1",
                        message=(
                            "El predio con condición de PH unidad predial debe asociar "
                            "una unidad de construcción."
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

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = row

    caracteristicas_by_id: dict[str, dict[str, object]] = {}

    for table_name, row in helper._iter_table_rows((
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )):
        caracteristica_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        if caracteristica_id:
            caracteristicas_by_id[str(caracteristica_id)] = row

    condiciones_ph_condominio = {
        "PH.Matriz",
        "PH.Unidad_Predial",
        "Condominio.Matriz",
        "Condominio.Unidad_Predial",
    }

    tipos_convencionales = {
        "Residencial",
        "Comercial",
        "Industrial",
        "Institucional",
    }

    for table_name, row in helper.iter_unidades_construccion():
        predio_ref = helper.get_field_value(row, ("predio",))
        caracteristica_ref = helper.get_field_value(
            row,
            ("caracteristicasunidadconstruccion",),
        )

        predio_row = predios_by_id.get(str(predio_ref)) if predio_ref else None
        caracteristica_row = (
            caracteristicas_by_id.get(str(caracteristica_ref))
            if caracteristica_ref
            else None
        )

        if not predio_row or not caracteristica_row:
            continue

        condicion_predio = helper.get_field_value(
            predio_row,
            ("condicion_predio", "Condicion_Predio"),
        )
        condicion_predio_str = _condicion_predio_ilicode(condicion_predio)

        tipo_unidad = helper.get_field_value(
            caracteristica_row,
            ("tipo_unidad_construccion",),
        )
        tipo_unidad_str = _tipo_unidad_construccion_ilicode(tipo_unidad)

        uso = helper.get_field_value(caracteristica_row, ("uso",))

        if (
            condicion_predio_str in condiciones_ph_condominio
            and tipo_unidad_str in tipos_convencionales
            and not _uso_unidad_es_ph_o_deposito_locker(uso)
        ):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="3.2",
                    message=(
                        "Toda unidad de construcción asociada a un predio con condición "
                        "PH o Condominio debe relacionar usos establecidos específicamente "
                        "para PH o Depósitos_Lockers."
                    ),
                    details={
                        "tabla": table_name,
                        "predio_ref": predio_ref,
                        "condicion_predio": condicion_predio,
                        "condicion_predio_ilicode": condicion_predio_str,
                        "tipo_unidad_construccion": tipo_unidad,
                        "tipo_unidad_construccion_ilicode": tipo_unidad_str,
                        "uso": uso,
                    },
                )
            )

    return issues

def _rule_3_3(dataset: DatasetReader) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = row

    caracteristicas_by_id: dict[str, dict[str, object]] = {}

    for _, row in helper._iter_table_rows((
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )):
        caracteristica_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        if caracteristica_id:
            caracteristicas_by_id[str(caracteristica_id)] = row

    condiciones_ph_condominio = {
        "PH.Matriz",
        "PH.Unidad_Predial",
        "Condominio.Matriz",
        "Condominio.Unidad_Predial",
    }

    tipos_convencionales = {
        "Residencial",
        "Comercial",
        "Industrial",
        "Institucional",
    }

    for table_name, row in helper.iter_unidades_construccion():
        predio_ref = helper.get_field_value(row, ("predio",))
        caracteristica_ref = helper.get_field_value(
            row,
            ("caracteristicasunidadconstruccion",),
        )

        predio_row = predios_by_id.get(str(predio_ref)) if predio_ref else None
        caracteristica_row = (
            caracteristicas_by_id.get(str(caracteristica_ref))
            if caracteristica_ref
            else None
        )

        if not predio_row or not caracteristica_row:
            continue

        condicion_predio = helper.get_field_value(
            predio_row,
            ("condicion_predio", "Condicion_Predio"),
        )
        condicion_predio_str = _condicion_predio_ilicode(condicion_predio)

        tipo_unidad = helper.get_field_value(
            caracteristica_row,
            ("tipo_unidad_construccion",),
        )
        tipo_unidad_str = _tipo_unidad_construccion_ilicode(tipo_unidad)

        uso = helper.get_field_value(caracteristica_row, ("uso",))

        if (
            condicion_predio_str not in condiciones_ph_condominio
            and tipo_unidad_str in tipos_convencionales
            and _uso_unidad_es_ph(uso)
        ):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="3.3",
                    message=(
                        "Toda unidad de construcción asociada a un predio con condición "
                        "diferente a PH o Condominio no debe relacionar usos de PH."
                    ),
                    details={
                        "tabla": table_name,
                        "predio_ref": predio_ref,
                        "condicion_predio": condicion_predio,
                        "condicion_predio_ilicode": condicion_predio_str,
                        "tipo_unidad_construccion": tipo_unidad,
                        "tipo_unidad_construccion_ilicode": tipo_unidad_str,
                        "uso": uso,
                    },
                )
            )

    return issues

#def _rule_3_4(dataset: DatasetReader) -> list[RuleIssue]:
    #sin defenir
    return []

def _rule_3_5(dataset: DatasetReader) -> list[RuleIssue]:
    """
    Regla: No debe haber polígonos de terreno menores a 2 m².
    """
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []

    for _, terreno in helper._iter_table_rows((
        "ARB_Terreno",
        "arb_terreno",
        "Terreno",
        "terreno",
    )):
        terreno_id = helper.get_field_value(
            terreno,
            ("TID", "t_id", "id", "identificador"),
        )

        area_terreno = _area_terreno(terreno, helper)

        if area_terreno is None:
            continue

        area_terreno_calculada = round(area_terreno, 2)

        if area_terreno_calculada < 2:
            issues.append(
                helper.make_issue(
                    terreno,
                    rule_id="3.5",
                    message=(
                        "Error en área de terreno: no debe haber polígonos "
                        f"de terreno menores a 2 m². Área calculada: "
                        f"{area_terreno_calculada} m²."
                    ),
                    details={
                        "tabla": "ARB_Terreno",
                        "terreno_id": terreno_id,
                        "area_calculada": area_terreno_calculada,
                        "area_minima_permitida": 2,
                    },
                )
            )

    return issues

#def _rule_3_6(dataset: DatasetReader) -> list[RuleIssue]:
    #sin defenir
    return []

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
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}
    caracteristicas_by_id: dict[str, dict[str, object]] = {}
    unidades_por_predio: dict[str, list[dict[str, object]]] = {}

    for _, predio in helper.iter_predios():
        predio_id = helper.get_field_value(predio, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for _, caracteristica in helper._iter_table_rows((
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )):
        caracteristica_id = helper.get_field_value(
            caracteristica,
            ("TID", "t_id", "id"),
        )
        if caracteristica_id:
            caracteristicas_by_id[str(caracteristica_id)] = caracteristica

    for _, unidad in helper.iter_unidades_construccion():
        predio_ref = helper.get_field_value(unidad, ("predio",))
        if predio_ref:
            unidades_por_predio.setdefault(str(predio_ref), []).append(unidad)

    for predio_id, predio in predios_by_id.items():
        destinacion = helper.get_field_value(predio, ("destinacion_economica",))
        destinacion_str = _destinacion_economica_ilicode(destinacion)

        if destinacion_str != "Habitacional":
            continue

        unidades = unidades_por_predio.get(str(predio_id), [])

        # Si el predio no tiene unidades, no se valida.
        if not unidades:
            continue

        caracteristicas_del_predio: list[dict[str, object]] = []
        areas_por_tipo: dict[str, float] = {}
        tiene_residencial = False

        for unidad in unidades:
            caracteristica_ref = helper.get_field_value(
                unidad,
                ("caracteristicasunidadconstruccion",),
            )

            caracteristica = (
                caracteristicas_by_id.get(str(caracteristica_ref))
                if caracteristica_ref
                else None
            )

            if not caracteristica:
                continue

            caracteristicas_del_predio.append(caracteristica)

            tipo_unidad = helper.get_field_value(
                caracteristica,
                ("tipo_unidad_construccion",),
            )
            tipo_unidad_str = _tipo_unidad_construccion_ilicode(tipo_unidad)

            if tipo_unidad_str == "Residencial":
                tiene_residencial = True

            area = _area_unidad(unidad, helper)

            if area == 0:
                area = _area_unidad(caracteristica, helper)

            areas_por_tipo[tipo_unidad_str] = (
                areas_por_tipo.get(tipo_unidad_str, 0.0) + area
            )

        if not caracteristicas_del_predio:
            continue

        numero_predial = helper.get_field_value(
            predio,
            ("numero_predial", "Numero_Predial"),
        )

        if not tiene_residencial:
            for caracteristica in caracteristicas_del_predio:
                issues.append(
                    helper.make_issue(
                        caracteristica,
                        rule_id="3.13",
                        message=(
                            "El predio con destinación económica Habitacional "
                            "debe tener al menos una unidad de construcción "
                            "con característica de tipo Residencial."
                        ),
                        details={
                            "tabla": "ARB_CaracteristicasUnidadConstruccion",
                            "numero_predial": numero_predial,
                            "destinacion_economica": destinacion,
                            "destinacion_economica_ilicode": destinacion_str,
                            "validacion": "existencia_tipo_residencial",
                        },
                    )
                )
            continue

        tipo_predominante = max(
            areas_por_tipo.items(),
            key=lambda item: item[1],
        )[0]

        if tipo_predominante != "Residencial":
            for caracteristica in caracteristicas_del_predio:
                issues.append(
                    helper.make_issue(
                        caracteristica,
                        rule_id="3.13",
                        message=(
                            "El predio con destinación económica Habitacional "
                            "tiene unidad de construcción Residencial, pero esta "
                            "no es predominante en área frente a las demás."
                        ),
                        details={
                            "tabla": "ARB_CaracteristicasUnidadConstruccion",
                            "numero_predial": numero_predial,
                            "destinacion_economica": destinacion,
                            "destinacion_economica_ilicode": destinacion_str,
                            "tipo_predominante": tipo_predominante,
                            "areas_por_tipo": areas_por_tipo,
                            "validacion": "predominancia_area_residencial",
                        },
                    )
                )

    return issues

def _rule_3_14(dataset: DatasetReader) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}
    caracteristicas_by_id: dict[str, dict[str, object]] = {}
    unidades_por_predio: dict[str, list[dict[str, object]]] = {}

    for _, predio in helper.iter_predios():
        predio_id = helper.get_field_value(predio, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for _, caracteristica in helper._iter_table_rows((
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )):
        caracteristica_id = helper.get_field_value(caracteristica, ("TID", "t_id", "id"))
        if caracteristica_id:
            caracteristicas_by_id[str(caracteristica_id)] = caracteristica

    for _, unidad in helper.iter_unidades_construccion():
        predio_ref = helper.get_field_value(unidad, ("predio",))
        if predio_ref:
            unidades_por_predio.setdefault(str(predio_ref), []).append(unidad)

    for predio_id, predio in predios_by_id.items():
        destinacion = helper.get_field_value(predio, ("destinacion_economica",))
        destinacion_str = _destinacion_economica_ilicode(destinacion)

        if destinacion_str != "Comercial":
            continue

        unidades = unidades_por_predio.get(str(predio_id), [])

        if not unidades:
            continue

        caracteristicas_del_predio: list[dict[str, object]] = []
        areas_por_tipo: dict[str, float] = {}
        tiene_comercial = False

        for unidad in unidades:
            caracteristica_ref = helper.get_field_value(
                unidad,
                ("caracteristicasunidadconstruccion",),
            )

            caracteristica = (
                caracteristicas_by_id.get(str(caracteristica_ref))
                if caracteristica_ref
                else None
            )

            if not caracteristica:
                continue

            caracteristicas_del_predio.append(caracteristica)

            tipo_unidad = helper.get_field_value(
                caracteristica,
                ("tipo_unidad_construccion",),
            )
            tipo_unidad_str = _tipo_unidad_construccion_ilicode(tipo_unidad)

            if tipo_unidad_str == "Comercial":
                tiene_comercial = True

            area = _area_unidad(unidad, helper)

            if area == 0:
                area = _area_unidad(caracteristica, helper)

            areas_por_tipo[tipo_unidad_str] = (
                areas_por_tipo.get(tipo_unidad_str, 0.0) + area
            )

        if not caracteristicas_del_predio:
            continue

        numero_predial = helper.get_field_value(
            predio,
            ("numero_predial", "Numero_Predial"),
        )

        if not tiene_comercial:
            for caracteristica in caracteristicas_del_predio:
                issues.append(
                    helper.make_issue(
                        caracteristica,
                        rule_id="3.14",
                        message=(
                            "El predio con destinación económica Comercial "
                            "debe tener al menos una unidad de construcción "
                            "con característica de tipo Comercial."
                        ),
                        details={
                            "tabla": "ARB_CaracteristicasUnidadConstruccion",
                            "numero_predial": numero_predial,
                            "destinacion_economica": destinacion,
                            "destinacion_economica_ilicode": destinacion_str,
                            "validacion": "existencia_tipo_comercial",
                        },
                    )
                )
            continue

        tipo_predominante = max(
            areas_por_tipo.items(),
            key=lambda item: item[1],
        )[0]

        if tipo_predominante != "Comercial":
            for caracteristica in caracteristicas_del_predio:
                issues.append(
                    helper.make_issue(
                        caracteristica,
                        rule_id="3.14",
                        message=(
                            "El predio con destinación económica Comercial "
                            "tiene unidad de construcción Comercial, pero esta "
                            "no es predominante en área frente a las demás."
                        ),
                        details={
                            "tabla": "ARB_CaracteristicasUnidadConstruccion",
                            "numero_predial": numero_predial,
                            "destinacion_economica": destinacion,
                            "destinacion_economica_ilicode": destinacion_str,
                            "tipo_predominante": tipo_predominante,
                            "areas_por_tipo": areas_por_tipo,
                            "validacion": "predominancia_area_comercial",
                        },
                    )
                )

    return issues

def _rule_3_15(dataset: DatasetReader) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}
    caracteristicas_by_id: dict[str, dict[str, object]] = {}
    unidades_por_predio: dict[str, list[dict[str, object]]] = {}

    for _, predio in helper.iter_predios():
        predio_id = helper.get_field_value(predio, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for _, caracteristica in helper._iter_table_rows((
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )):
        caracteristica_id = helper.get_field_value(caracteristica, ("TID", "t_id", "id"))
        if caracteristica_id:
            caracteristicas_by_id[str(caracteristica_id)] = caracteristica

    for _, unidad in helper.iter_unidades_construccion():
        predio_ref = helper.get_field_value(unidad, ("predio",))
        if predio_ref:
            unidades_por_predio.setdefault(str(predio_ref), []).append(unidad)

    for predio_id, predio in predios_by_id.items():
        destinacion = helper.get_field_value(predio, ("destinacion_economica",))
        destinacion_str = _destinacion_economica_ilicode(destinacion)

        if destinacion_str != "Industrial":
            continue

        unidades = unidades_por_predio.get(str(predio_id), [])

        if not unidades:
            continue

        caracteristicas_del_predio: list[dict[str, object]] = []
        areas_por_tipo: dict[str, float] = {}
        tiene_industrial = False

        for unidad in unidades:
            caracteristica_ref = helper.get_field_value(
                unidad,
                ("caracteristicasunidadconstruccion",),
            )

            caracteristica = (
                caracteristicas_by_id.get(str(caracteristica_ref))
                if caracteristica_ref
                else None
            )

            if not caracteristica:
                continue

            caracteristicas_del_predio.append(caracteristica)

            tipo_unidad = helper.get_field_value(
                caracteristica,
                ("tipo_unidad_construccion",),
            )
            tipo_unidad_str = _tipo_unidad_construccion_ilicode(tipo_unidad)

            if tipo_unidad_str == "Industrial":
                tiene_industrial = True

            area = _area_unidad(unidad, helper)

            if area == 0:
                area = _area_unidad(caracteristica, helper)

            areas_por_tipo[tipo_unidad_str] = (
                areas_por_tipo.get(tipo_unidad_str, 0.0) + area
            )

        if not caracteristicas_del_predio:
            continue

        numero_predial = helper.get_field_value(
            predio,
            ("numero_predial", "Numero_Predial"),
        )

        if not tiene_industrial:
            for caracteristica in caracteristicas_del_predio:
                issues.append(
                    helper.make_issue(
                        caracteristica,
                        rule_id="3.15",
                        message=(
                            "El predio con destinación económica Industrial "
                            "debe tener al menos una unidad de construcción "
                            "con característica de tipo Industrial."
                        ),
                        details={
                            "tabla": "ARB_CaracteristicasUnidadConstruccion",
                            "numero_predial": numero_predial,
                            "destinacion_economica": destinacion,
                            "destinacion_economica_ilicode": destinacion_str,
                            "validacion": "existencia_tipo_industrial",
                        },
                    )
                )
            continue

        tipo_predominante = max(
            areas_por_tipo.items(),
            key=lambda item: item[1],
        )[0]

        if tipo_predominante != "Industrial":
            for caracteristica in caracteristicas_del_predio:
                issues.append(
                    helper.make_issue(
                        caracteristica,
                        rule_id="3.15",
                        message=(
                            "El predio con destinación económica Industrial "
                            "tiene unidad de construcción Industrial, pero esta "
                            "no es predominante en área frente a las demás."
                        ),
                        details={
                            "tabla": "ARB_CaracteristicasUnidadConstruccion",
                            "numero_predial": numero_predial,
                            "destinacion_economica": destinacion,
                            "destinacion_economica_ilicode": destinacion_str,
                            "tipo_predominante": tipo_predominante,
                            "areas_por_tipo": areas_por_tipo,
                            "validacion": "predominancia_area_industrial",
                        },
                    )
                )

    return issues

def _rule_3_16(dataset: DatasetReader) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}
    caracteristicas_by_id: dict[str, dict[str, object]] = {}
    unidades_por_predio: dict[str, list[dict[str, object]]] = {}

    for _, predio in helper.iter_predios():
        predio_id = helper.get_field_value(predio, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for _, caracteristica in helper._iter_table_rows((
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )):
        caracteristica_id = helper.get_field_value(caracteristica, ("TID", "t_id", "id"))
        if caracteristica_id:
            caracteristicas_by_id[str(caracteristica_id)] = caracteristica

    for _, unidad in helper.iter_unidades_construccion():
        predio_ref = helper.get_field_value(unidad, ("predio",))
        if predio_ref:
            unidades_por_predio.setdefault(str(predio_ref), []).append(unidad)

    destinaciones_institucionales = {
        "Institucional",
        "Cultural",
        "Educativo",
        "Religioso",
    }

    for predio_id, predio in predios_by_id.items():
        destinacion = helper.get_field_value(predio, ("destinacion_economica",))
        destinacion_str = _destinacion_economica_ilicode(destinacion)

        if destinacion_str not in destinaciones_institucionales:
            continue

        unidades = unidades_por_predio.get(str(predio_id), [])

        if not unidades:
            continue

        caracteristicas_del_predio: list[dict[str, object]] = []
        areas_por_tipo: dict[str, float] = {}
        tiene_institucional = False

        for unidad in unidades:
            caracteristica_ref = helper.get_field_value(
                unidad,
                ("caracteristicasunidadconstruccion",),
            )

            caracteristica = (
                caracteristicas_by_id.get(str(caracteristica_ref))
                if caracteristica_ref
                else None
            )

            if not caracteristica:
                continue

            caracteristicas_del_predio.append(caracteristica)

            tipo_unidad = helper.get_field_value(
                caracteristica,
                ("tipo_unidad_construccion",),
            )
            tipo_unidad_str = _tipo_unidad_construccion_ilicode(tipo_unidad)

            if tipo_unidad_str == "Institucional":
                tiene_institucional = True

            area = _area_unidad(unidad, helper)

            if area == 0:
                area = _area_unidad(caracteristica, helper)

            areas_por_tipo[tipo_unidad_str] = (
                areas_por_tipo.get(tipo_unidad_str, 0.0) + area
            )

        if not caracteristicas_del_predio:
            continue

        numero_predial = helper.get_field_value(
            predio,
            ("numero_predial", "Numero_Predial"),
        )

        if not tiene_institucional:
            for caracteristica in caracteristicas_del_predio:
                issues.append(
                    helper.make_issue(
                        caracteristica,
                        rule_id="3.16",
                        message=(
                            "El predio con destinación económica Institucional, Cultural, "
                            "Educativo o Religioso debe tener al menos una unidad de "
                            "construcción con característica de tipo Institucional."
                        ),
                        details={
                            "tabla": "ARB_CaracteristicasUnidadConstruccion",
                            "numero_predial": numero_predial,
                            "destinacion_economica": destinacion,
                            "destinacion_economica_ilicode": destinacion_str,
                            "validacion": "existencia_tipo_institucional",
                        },
                    )
                )
            continue

        tipo_predominante = max(
            areas_por_tipo.items(),
            key=lambda item: item[1],
        )[0]

        if tipo_predominante != "Institucional":
            for caracteristica in caracteristicas_del_predio:
                issues.append(
                    helper.make_issue(
                        caracteristica,
                        rule_id="3.16",
                        message=(
                            "El predio con destinación económica Institucional, Cultural, "
                            "Educativo o Religioso tiene unidad de construcción Institucional, "
                            "pero esta no es predominante en área frente a las demás."
                        ),
                        details={
                            "tabla": "ARB_CaracteristicasUnidadConstruccion",
                            "numero_predial": numero_predial,
                            "destinacion_economica": destinacion,
                            "destinacion_economica_ilicode": destinacion_str,
                            "tipo_predominante": tipo_predominante,
                            "areas_por_tipo": areas_por_tipo,
                            "validacion": "predominancia_area_institucional",
                        },
                    )
                )

    return issues

def _rule_3_16(dataset: DatasetReader) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}
    caracteristicas_by_id: dict[str, dict[str, object]] = {}
    unidades_por_predio: dict[str, list[dict[str, object]]] = {}

    for _, predio in helper.iter_predios():
        predio_id = helper.get_field_value(predio, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for _, caracteristica in helper._iter_table_rows((
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )):
        caracteristica_id = helper.get_field_value(caracteristica, ("TID", "t_id", "id"))
        if caracteristica_id:
            caracteristicas_by_id[str(caracteristica_id)] = caracteristica

    for _, unidad in helper.iter_unidades_construccion():
        predio_ref = helper.get_field_value(unidad, ("predio",))
        if predio_ref:
            unidades_por_predio.setdefault(str(predio_ref), []).append(unidad)

    destinaciones_institucionales = {
        "Institucional",
        "Cultural",
        "Educativo",
        "Religioso",
    }

    for predio_id, predio in predios_by_id.items():
        destinacion = helper.get_field_value(predio, ("destinacion_economica",))
        destinacion_str = _destinacion_economica_ilicode(destinacion)

        if destinacion_str not in destinaciones_institucionales:
            continue

        unidades = unidades_por_predio.get(str(predio_id), [])

        if not unidades:
            continue

        caracteristicas_del_predio: list[dict[str, object]] = []
        areas_por_tipo: dict[str, float] = {}
        tiene_institucional = False

        for unidad in unidades:
            caracteristica_ref = helper.get_field_value(
                unidad,
                ("caracteristicasunidadconstruccion",),
            )

            caracteristica = (
                caracteristicas_by_id.get(str(caracteristica_ref))
                if caracteristica_ref
                else None
            )

            if not caracteristica:
                continue

            caracteristicas_del_predio.append(caracteristica)

            tipo_unidad = helper.get_field_value(
                caracteristica,
                ("tipo_unidad_construccion",),
            )
            tipo_unidad_str = _tipo_unidad_construccion_ilicode(tipo_unidad)

            if tipo_unidad_str == "Institucional":
                tiene_institucional = True

            area = _area_unidad(unidad, helper)

            if area == 0:
                area = _area_unidad(caracteristica, helper)

            areas_por_tipo[tipo_unidad_str] = (
                areas_por_tipo.get(tipo_unidad_str, 0.0) + area
            )

        if not caracteristicas_del_predio:
            continue

        numero_predial = helper.get_field_value(
            predio,
            ("numero_predial", "Numero_Predial"),
        )

        if not tiene_institucional:
            for caracteristica in caracteristicas_del_predio:
                issues.append(
                    helper.make_issue(
                        caracteristica,
                        rule_id="3.16",
                        message=(
                            "El predio con destinación económica Institucional, Cultural, "
                            "Educativo o Religioso debe tener al menos una unidad de "
                            "construcción con característica de tipo Institucional."
                        ),
                        details={
                            "tabla": "ARB_CaracteristicasUnidadConstruccion",
                            "numero_predial": numero_predial,
                            "destinacion_economica": destinacion,
                            "destinacion_economica_ilicode": destinacion_str,
                            "validacion": "existencia_tipo_institucional",
                        },
                    )
                )
            continue

        tipo_predominante = max(
            areas_por_tipo.items(),
            key=lambda item: item[1],
        )[0]

        if tipo_predominante != "Institucional":
            for caracteristica in caracteristicas_del_predio:
                issues.append(
                    helper.make_issue(
                        caracteristica,
                        rule_id="3.16",
                        message=(
                            "El predio con destinación económica Institucional, Cultural, "
                            "Educativo o Religioso tiene unidad de construcción Institucional, "
                            "pero esta no es predominante en área frente a las demás."
                        ),
                        details={
                            "tabla": "ARB_CaracteristicasUnidadConstruccion",
                            "numero_predial": numero_predial,
                            "destinacion_economica": destinacion,
                            "destinacion_economica_ilicode": destinacion_str,
                            "tipo_predominante": tipo_predominante,
                            "areas_por_tipo": areas_por_tipo,
                            "validacion": "predominancia_area_institucional",
                        },
                    )
                )

    return issues


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

def _rule_3_18(dataset: DatasetReader) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}
    caracteristicas_by_id: dict[str, dict[str, object]] = {}

    for _, predio in helper.iter_predios():
        predio_id = helper.get_field_value(predio, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for _, caracteristica in helper._iter_table_rows((
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )):
        caracteristica_id = helper.get_field_value(caracteristica, ("TID", "t_id", "id"))
        if caracteristica_id:
            caracteristicas_by_id[str(caracteristica_id)] = caracteristica

    condiciones_unidad_predial = {
        "PH.Unidad_Predial",
        "Condominio.Unidad_Predial",
    }

    for table_name, unidad in helper.iter_unidades_construccion():
        predio_ref = helper.get_field_value(unidad, ("predio",))
        caracteristica_ref = helper.get_field_value(unidad, ("caracteristicasunidadconstruccion",))

        predio = predios_by_id.get(str(predio_ref)) if predio_ref else None
        caracteristica = caracteristicas_by_id.get(str(caracteristica_ref)) if caracteristica_ref else None

        if not predio or not caracteristica:
            continue

        condicion = helper.get_field_value(predio, ("condicion_predio",))
        condicion_str = _condicion_predio_ilicode(condicion)

        area_construida_raw = helper.get_field_value(caracteristica, ("area_construida",))
        area_privada_raw = helper.get_field_value(caracteristica, ("area_privada_construida",))

        area_construida = _to_float(area_construida_raw)
        area_privada = _to_float(area_privada_raw)

        if (
            condicion_str in condiciones_unidad_predial
            and (
                area_construida != 0
                or area_privada is None
                or area_privada <= 0
            )
        ):
            issues.append(
                helper.make_issue(
                    caracteristica,
                    rule_id="3.18",
                    message=(
                        "Para PH unidad predial y Condominio unidad predial, "
                        "el área construida debe ser cero y el área privada construida "
                        "debe ser mayor a cero."
                    ),
                    details={
                        "tabla": "ARB_CaracteristicasUnidadConstruccion",
                        "predio_ref": predio_ref,
                        "condicion_predio": condicion,
                        "condicion_predio_ilicode": condicion_str,
                        "area_construida": area_construida_raw,
                        "area_privada_construida": area_privada_raw,
                    },
                )
            )

    return issues

def _rule_3_19(dataset: DatasetReader) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}
    caracteristicas_by_id: dict[str, dict[str, object]] = {}

    for _, predio in helper.iter_predios():
        predio_id = helper.get_field_value(predio, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for _, caracteristica in helper._iter_table_rows((
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )):
        caracteristica_id = helper.get_field_value(caracteristica, ("TID", "t_id", "id"))
        if caracteristica_id:
            caracteristicas_by_id[str(caracteristica_id)] = caracteristica

    condiciones_unidad_predial = {
        "PH.Unidad_Predial",
        "Condominio.Unidad_Predial",
    }

    for table_name, unidad in helper.iter_unidades_construccion():
        predio_ref = helper.get_field_value(unidad, ("predio",))
        caracteristica_ref = helper.get_field_value(unidad, ("caracteristicasunidadconstruccion",))

        predio = predios_by_id.get(str(predio_ref)) if predio_ref else None
        caracteristica = caracteristicas_by_id.get(str(caracteristica_ref)) if caracteristica_ref else None

        if not predio or not caracteristica:
            continue

        condicion = helper.get_field_value(predio, ("condicion_predio",))
        condicion_str = _condicion_predio_ilicode(condicion)

        area_construida_raw = helper.get_field_value(caracteristica, ("area_construida",))
        area_privada_raw = helper.get_field_value(caracteristica, ("area_privada_construida",))

        area_construida = _to_float(area_construida_raw)

        if (
            condicion_str not in condiciones_unidad_predial
            and (
                area_construida is None
                or area_construida <= 0
                or area_privada_raw not in (None, "")
            )
        ):
            issues.append(
                helper.make_issue(
                    caracteristica,
                    rule_id="3.19",
                    message=(
                        "Para predios con condición diferente a PH unidad predial "
                        "o Condominio unidad predial, el área construida debe ser mayor "
                        "a cero y el área privada construida debe ser NULL."
                    ),
                    details={
                        "tabla": "ARB_CaracteristicasUnidadConstruccion",
                        "predio_ref": predio_ref,
                        "condicion_predio": condicion,
                        "condicion_predio_ilicode": condicion_str,
                        "area_construida": area_construida_raw,
                        "area_privada_construida": area_privada_raw,
                    },
                )
            )

    return issues

#def _rule_3_20(dataset: DatasetReader) -> list[RuleIssue]:
    helper = FisicoHelper(dataset)
    issues: list[RuleIssue] = []

    caracteristicas_by_id: dict[str, dict[str, object]] = {}
    area_geometrica_por_caracteristica: dict[str, float] = {}

    for _, caracteristica in helper._iter_table_rows((
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )):
        caracteristica_id = helper.get_field_value(
            caracteristica,
            ("TID", "t_id", "id", "identificador"),
        )
        if caracteristica_id:
            caracteristicas_by_id[str(caracteristica_id)] = caracteristica

    for _, unidad in helper.iter_unidades_construccion():
        caracteristica_ref = helper.get_field_value(
            unidad,
            ("caracteristicasunidadconstruccion",),
        )
        if not caracteristica_ref:
            continue

        area_unidad = _area_unidad(unidad, helper)

        area_geometrica_por_caracteristica[str(caracteristica_ref)] = (
            area_geometrica_por_caracteristica.get(str(caracteristica_ref), 0.0)
            + area_unidad
        )

    for caracteristica_id, area_total in area_geometrica_por_caracteristica.items():
        caracteristica = caracteristicas_by_id.get(caracteristica_id)
        if not caracteristica:
            continue

        area_construida_raw = helper.get_field_value(
            caracteristica,
            ("area_construida",),
        )
        area_construida = _to_float(area_construida_raw)

        if area_construida is None:
            continue

        # Igual que QGIS: round(...,1)
        area_total_calculada = round(area_total, 1)
        area_construida_redondeada = round(area_construida, 1)

        diferencia = area_construida_redondeada - area_total_calculada

        if diferencia != 0:
            issues.append(
                helper.make_issue(
                    caracteristica,
                    rule_id="3.20",
                    message=(
                        "Error en área construida: el valor diligenciado "
                        f"({area_construida_redondeada}) no coincide con el área calculada "
                        f"de las unidades ({area_total_calculada})."
                    ),
                    details={
                        "tabla": "ARB_CaracteristicasUnidadConstruccion",
                        "caracteristica_id": caracteristica_id,
                        "area_construida": area_construida_redondeada,
                        "area_total_calculada": area_total_calculada,
                        "diferencia": diferencia,
                    },
                )
            )

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
    #"3.20": _rule_3_20,
}
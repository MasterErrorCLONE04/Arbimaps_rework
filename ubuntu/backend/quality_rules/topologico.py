from __future__ import annotations

import json

from .base import DatasetReader, RuleIssue

try:  
    from shapely import wkb, wkt
    from shapely.geometry import shape
except Exception: 
    wkb = None
    wkt = None
    shape = None

COMPONENT_SLUG = "topologico"

DEFAULT_RULE_IDS = frozenset({
    "5.1", "5.2", "5.3", "5.4", "5.5", "5.6", "5.7",
})


class TopologicoHelper:
    """Utilidades compartidas para reglas topologicas."""

    IDENTIFIER_FIELDS = (
        "id_operacion",
        "t_id",
        "TID",
        "id",
        "t_ili_tid",
    )

    PREDIO_TABLES = (
        "ARB_Predio",
        "arb_predio",
        "CCA_Predio",
        "cca_predio",
    )

    TERRENO_TABLES = (
        "ARB_Terreno",
        "ARB-Terreno",
        "arb_terreno",
        "CCA_Terreno",
        "cca_terreno",
    )

    DERECHO_INTERESADO_FUENTE_TABLES = (
        "ARB_DerechoInteresadoFuente",
        "arb_derechointeresadofuente",
        "ARB_Derecho Interesado Fuente",
        "arb_derecho_interesado_fuente",
    )

    UNIDAD_CONSTRUCCION_TABLES = (
        "ARB_UnidadConstruccion",
        "arb_unidadconstruccion",
    )

    DIRECCION_TABLES = (
        "ARB_Direccion",
        "arb_direccion",
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

    def iter_predio(self):
        yield from self._iter_table_rows(self.PREDIO_TABLES)

    def iter_terreno(self):
        yield from self._iter_table_rows(self.TERRENO_TABLES)

    def iter_derecho_interesado_fuente(self):
        yield from self._iter_table_rows(self.DERECHO_INTERESADO_FUENTE_TABLES)

    def iter_unidad_construccion(self):
        yield from self._iter_table_rows(self.UNIDAD_CONSTRUCCION_TABLES)

    def iter_direccion(self):
        yield from self._iter_table_rows(self.DIRECCION_TABLES)

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

        if "class" not in fixed_details and "tabla" in fixed_details:
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



def _load_geometry(value: object):
    if value in (None, "") or wkt is None or wkb is None or shape is None:
        return None

    if hasattr(value, "overlaps"):
        return value

    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            return wkb.loads(bytes(value))
        except Exception:
            return None

    text = str(value).strip()
    if not text:
        return None

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

# -------------- reglas --------------------

def _rule_5_1(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []

    # 🔴 1. Obtener IDs de tipo Dominio desde ARB_DerechoTipo
    dominio_ids: set[str] = set()

    for _, row in helper._iter_table_rows(("ARB_DerechoTipo", "arb_derechotipo")):
        ilicode = helper.get_field_value(row, ("ilicode",))
        t_id = helper.get_field_value(row, ("t_id", "id"))

        if ilicode and ilicode.strip().lower() == "dominio" and t_id:
            dominio_ids.add(str(t_id))

    # 🔴 2. Identificar predios con derecho Dominio
    predios_formales: set[str] = set()

    for _, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, ("d_tipo",))
        predio_ref = helper.get_field_value(row, ("predio",))

        if tipo and str(tipo) in dominio_ids and predio_ref:
            predios_formales.add(str(predio_ref))

    # 🔴 3. Obtener terrenos formales
    terrenos: list[dict[str, object]] = []

    for table_name, row in helper.iter_terreno():
        predio_ref = helper.get_field_value(row, ("predio",))

        if not predio_ref or str(predio_ref) not in predios_formales:
            continue

        geom_raw = helper.get_field_value(row, ("geometria", "geometry", "geom"))
        geom = _load_geometry(geom_raw)

        if geom is None:
            continue

        terrenos.append({
            "row": row,
            "tabla": table_name,
            "predio": predio_ref,
            "geom": geom,
            "id": helper.get_field_value(row, ("t_id", "id")),
            "tid": helper.get_field_value(row, ("t_ili_tid", "TID")),
        })

    # 🔴 4. Comparar overlaps (como ST_Overlaps)
    for i in range(len(terrenos)):
        for j in range(i + 1, len(terrenos)):
            t1 = terrenos[i]
            t2 = terrenos[j]

            if t1["id"] == t2["id"]:
                continue

            try:
                if t1["geom"].overlaps(t2["geom"]):
                    issues.append(
                        helper.make_issue(
                            t1["row"],
                            rule_id="5.1",
                            message="El terreno formal 1 se superpone con el terreno formal numero 2.",
                            details={
                                "tabla": t1["tabla"],
                                "identificador_terreno_1": t1["tid"],
                                "identificador_terreno_2": t2["tid"],
                            },
                        )
                    )
            except Exception:
                continue

    return issues

def _rule_5_2(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []

    informal_tipo_ids: set[str] = set()

    for _, row in helper._iter_table_rows(("ARB_DerechoTipo", "arb_derechotipo")):
        ilicode = helper.get_field_value(row, ("ilicode",))
        t_id = helper.get_field_value(row, ("t_id", "id"))

        if ilicode and helper._normalize_key(ilicode) in {"posesion", "ocupacion"} and t_id:
            informal_tipo_ids.add(str(t_id))

    predios_informales: set[str] = set()

    for _, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, ("d_tipo",))
        predio_ref = helper.get_field_value(row, ("predio",))

        if tipo and str(tipo) in informal_tipo_ids and predio_ref:
            predios_informales.add(str(predio_ref))

    terrenos: list[dict[str, object]] = []

    for table_name, row in helper.iter_terreno():
        predio_ref = helper.get_field_value(row, ("predio",))

        if not predio_ref or str(predio_ref) not in predios_informales:
            continue

        geom_raw = helper.get_field_value(row, ("geometria", "geometry", "geom"))
        geom = _load_geometry(geom_raw)

        if geom is None:
            continue

        terrenos.append({
            "row": row,
            "tabla": table_name,
            "predio": predio_ref,
            "geom": geom,
            "id": helper.get_field_value(row, ("t_id", "id")),
            "tid": helper.get_field_value(row, ("t_ili_tid", "TID", "t_id")),
        })

    for i in range(len(terrenos)):
        for j in range(i + 1, len(terrenos)):
            t1 = terrenos[i]
            t2 = terrenos[j]

            if t1["id"] and t1["id"] == t2["id"]:
                continue

            try:
                if t1["geom"].overlaps(t2["geom"]):
                    issues.append(
                        helper.make_issue(
                            t1["row"],
                            rule_id="5.2",
                            message=(
                                "El terreno informal 1 se superpone con el terreno informal numero 2."
                            ),
                            details={
                                "tabla": t1["tabla"],
                                "identificador_terreno_1": t1["tid"],
                                "identificador_terreno_2": t2["tid"],
                                "predio_1": t1["predio"],
                                "predio_2": t2["predio"],
                            },
                        )
                    )
            except Exception:
                continue

    return issues

def _rule_5_3(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []

    # 🔴 IDs reales de tu modelo
    POSESION_ID = "14"
    DOMINIO_ID = "16"

    PREDIO_PUBLICO_IDS = {"1198", "1200", "1201", "1202", "1203"}

    predios_posesion: set[str] = set()
    predios_dominio: set[str] = set()

    for _, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, ("d_tipo",))
        predio_ref = helper.get_field_value(row, ("predio",))

        if not tipo or not predio_ref:
            continue

        if str(tipo) == POSESION_ID:
            predios_posesion.add(str(predio_ref))

        if str(tipo) == DOMINIO_ID:
            predios_dominio.add(str(predio_ref))

    predios_by_id = {}
    for _, row in helper.iter_predio():
        pid = helper.get_field_value(row, ("t_id", "id"))
        if pid:
            predios_by_id[str(pid)] = row

    terrenos_posesion = []
    terrenos_publicos = []

    for table_name, row in helper.iter_terreno():
        predio_ref = helper.get_field_value(row, ("predio",))
        if not predio_ref:
            continue

        geom = _load_geometry(helper.get_field_value(row, ("geometria",)))
        if geom is None:
            continue

        terreno = {
            "row": row,
            "tabla": table_name,
            "predio": str(predio_ref),
            "geom": geom,
            "id": helper.get_field_value(row, ("t_id",)),
            "tid": helper.get_field_value(row, ("t_ili_tid", "t_id")),
        }

        if str(predio_ref) in predios_posesion:
            terrenos_posesion.append(terreno)

        predio_row = predios_by_id.get(str(predio_ref))
        predio_tipo = helper.get_field_value(predio_row or {}, ("tipo",))

        if (
            str(predio_ref) in predios_dominio
            and predio_tipo
            and str(predio_tipo) in PREDIO_PUBLICO_IDS
        ):
            terrenos_publicos.append(terreno)

    for t1 in terrenos_posesion:
        for t2 in terrenos_publicos:
            if t1["id"] == t2["id"]:
                continue

            try:
                if t1["geom"].overlaps(t2["geom"]):
                    issues.append(
                        helper.make_issue(
                            t1["row"],
                            rule_id="5.3",
                            message=(
                                "Todo terreno asociado a derecho de posesión no puede "
                                "superponerse con un terreno asociado a un predio formal de tipo público."
                            ),
                            details={
                                "id_terreno_posesion": t1["tid"],
                                "id_terreno_publico": t2["tid"],
                            },
                        )
                    )
            except Exception:
                continue

    return issues

def _rule_5_4(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []

    DOMINIO_ID = "16"
    OCUPACION_ID = "15"
    PREDIO_PRIVADO_IDS = {"1199", "1204"}

    predios_ocupacion: set[str] = set()
    predios_dominio: set[str] = set()

    for _, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, ("d_tipo",))
        predio_ref = helper.get_field_value(row, ("predio",))

        if not tipo or not predio_ref:
            continue

        if str(tipo) == OCUPACION_ID:
            predios_ocupacion.add(str(predio_ref))

        if str(tipo) == DOMINIO_ID:
            predios_dominio.add(str(predio_ref))

    predios_by_id = {}
    for _, row in helper.iter_predio():
        pid = helper.get_field_value(row, ("t_id", "TID", "id"))
        if pid:
            predios_by_id[str(pid)] = row

    terrenos_ocupacion = []
    terrenos_privados = []

    for table_name, row in helper.iter_terreno():
        predio_ref = helper.get_field_value(row, ("predio",))
        if not predio_ref:
            continue

        geom = _load_geometry(helper.get_field_value(row, ("geometria", "geometry", "geom")))
        if geom is None:
            continue

        terreno = {
            "row": row,
            "tabla": table_name,
            "predio": str(predio_ref),
            "geom": geom,
            "id": helper.get_field_value(row, ("t_id", "TID", "id")),
            "tid": helper.get_field_value(row, ("t_ili_tid", "TID", "t_id")),
        }

        if str(predio_ref) in predios_ocupacion:
            terrenos_ocupacion.append(terreno)

        predio_row = predios_by_id.get(str(predio_ref))
        predio_tipo = helper.get_field_value(predio_row or {}, ("tipo",))

        if (
            str(predio_ref) in predios_dominio
            and predio_tipo
            and str(predio_tipo) in PREDIO_PRIVADO_IDS
        ):
            terrenos_privados.append(terreno)

    for t1 in terrenos_ocupacion:
        for t2 in terrenos_privados:
            if t1["id"] and t1["id"] == t2["id"]:
                continue

            try:
                if t1["geom"].overlaps(t2["geom"]):
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
            except Exception:
                continue

    return issues

def _rule_5_5(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []

    unidades: list[dict[str, object]] = []

    for table_name, row in helper.iter_unidad_construccion():
        geom = _load_geometry(
            helper.get_field_value(row, ("geometria", "geometry", "geom"))
        )

        if geom is None:
            continue

        unidades.append({
            "row": row,
            "tabla": table_name,
            "geom": geom,
            "id": helper.get_field_value(row, ("t_id", "TID", "id")),
            "tid": helper.get_field_value(row, ("t_ili_tid", "TID", "t_id")),
            "tipo_planta": helper.get_field_value(row, ("tipo_planta",)),
            "planta_ubicacion": helper.get_field_value(row, ("planta_ubicacion",)),
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

            try:
                if cu1["geom"].overlaps(cu2["geom"]):
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
            except Exception:
                continue

    return issues


def _rule_5_6(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []

    terrenos_por_predio: dict[str, list[dict[str, object]]] = {}

    for table_name, row in helper.iter_terreno():
        predio_ref = helper.get_field_value(row, ("predio",))
        if not predio_ref:
            continue

        geom = _load_geometry(
            helper.get_field_value(row, ("geometria", "geometry", "geom"))
        )
        if geom is None:
            continue

        terrenos_por_predio.setdefault(str(predio_ref), []).append({
            "row": row,
            "tabla": table_name,
            "predio": str(predio_ref),
            "geom": geom,
            "tid": helper.get_field_value(row, ("t_ili_tid", "TID", "t_id")),
        })

    for table_name, row in helper.iter_unidad_construccion():
        planta_ubicacion = helper.get_field_value(row, ("planta_ubicacion",))
        if str(planta_ubicacion) != "1":
            continue

        predio_ref = helper.get_field_value(row, ("predio",))
        if not predio_ref:
            continue

        geom_uc = _load_geometry(
            helper.get_field_value(row, ("geometria", "geometry", "geom"))
        )
        if geom_uc is None:
            continue

        terrenos = terrenos_por_predio.get(str(predio_ref), [])

        for terreno in terrenos:
            try:
                if not terreno["geom"].contains(geom_uc):
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
                                "id_uconstruccion": helper.get_field_value(
                                    row, ("t_ili_tid", "TID", "t_id")
                                ),
                                "predio": predio_ref,
                            },
                        )
                    )
            except Exception:
                continue

    return issues

def _rule_5_7(dataset: DatasetReader) -> list[RuleIssue]:
    helper = TopologicoHelper(dataset)
    issues: list[RuleIssue] = []

    terrenos_por_predio: dict[str, list[dict[str, object]]] = {}

    # 🔹 Terrenos
    for table_name, row in helper.iter_terreno():
        predio_ref = helper.get_field_value(row, ("predio",))
        if not predio_ref:
            continue

        geom = _load_geometry(
            helper.get_field_value(row, ("geometria", "geometry", "geom"))
        )
        if geom is None:
            continue

        terrenos_por_predio.setdefault(str(predio_ref), []).append({
            "row": row,
            "tabla": table_name,
            "geom": geom,
            "tid": helper.get_field_value(row, ("t_ili_tid", "TID", "t_id")),
        })

    # 🔹 Direcciones
    for table_name, row in helper.iter_direccion():

        predio_ref = helper.get_field_value(row, ("arb_predio_direccion",))
        if not predio_ref:
            continue

        geom_dir = _load_geometry(
            helper.get_field_value(row, ("geometria", "geometry", "geom"))
        )
        if geom_dir is None:
            continue

        terrenos = terrenos_por_predio.get(str(predio_ref), [])

        for terreno in terrenos:
            try:
                if not terreno["geom"].contains(geom_dir):
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
                                "identificador_direccion": helper.get_field_value(
                                    row, ("t_ili_tid", "TID", "t_id")
                                ),
                                "predio": predio_ref,
                            },
                        )
                    )
            except Exception:
                continue

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

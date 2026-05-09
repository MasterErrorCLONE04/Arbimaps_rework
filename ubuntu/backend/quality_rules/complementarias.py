from __future__ import annotations
from shapely.geometry import shape
from .base import DatasetReader, RuleIssue
import json
from shapely import wkb, wkt
from shapely.geometry import shape
import re

COMPONENT_SLUG = "complementarias"

DEFAULT_RULE_IDS = frozenset({
    "10.1", "10.2", "10.3", "10.4"
})


class ComplementariasHelper:
    """Utilidades compartidas para reglas complementarias."""
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
    )

    CARACTERISTICAS_UNIDAD_TABLES = (
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )

    MARCA_PREDIAL_TABLES = (
        "ARB_MarcaPredial",
        "arb_marcapredial",
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
    
def _get_predio_nuevo_ids(helper: ComplementariasHelper) -> set[str]:
    ids = set()

    for _, row in helper._iter_table_rows((
        "ARB_NovedadNumeroPredialTipo",
        "arb_novedadnumeropredialtipo",
    )):
        ilicode = helper.get_field_value(row, ("ilicode",))
        t_id = helper.get_field_value(row, ("t_id", "id"))

        if ilicode and ilicode.strip().lower() == "predio_nuevo" and t_id:
            ids.add(str(t_id))

    return ids

def _pos(texto: str | None, n: int) -> str | None:
    if not texto:
        return None
    texto = str(texto).strip()
    return texto[n - 1] if len(texto) >= n else None

def _get_tipo_planta_piso_ids(helper: ComplementariasHelper) -> set[str]:
    ids: set[str] = set()

    for _, row in helper._iter_table_rows((
        "ARB_ConstruccionPlantaTipo",
        "arb_construccionplantatipo",
    )):
        ilicode = helper.get_field_value(row, ("ilicode",))
        t_id = helper.get_field_value(row, ("t_id", "id"))

        if ilicode and ilicode.strip().lower() == "piso" and t_id:
            ids.add(str(t_id))

    return ids

def _load_geometry(value: object):
    if value in (None, ""):
        return None

    if hasattr(value, "intersects"):
        return value

    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            return wkb.loads(bytes(value))
        except Exception:
            return None

    text = str(value).strip()

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
        if not tipo_novedad or str(tipo_novedad) not in predio_nuevo_ids:
            continue

        numero_predial = helper.get_field_value(
            novedad,
            ("numero_predial",),
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

    unidades: list[dict[str, object]] = []

    for table_name, unidad in helper.iter_unidades_construccion():
        planta_raw = helper.get_field_value(unidad, ("planta_ubicacion",))
        tipo_planta = helper.get_field_value(unidad, ("tipo_planta",))
        geom_raw = helper.get_field_value(unidad, ("geometria", "geometry", "geom"))

        if not planta_raw or not tipo_planta:
            continue

        if str(tipo_planta) not in tipo_piso_ids:
            continue

        geom = _load_geometry(geom_raw)

        if geom is None:
            continue

        try:
            planta = int(float(planta_raw))
        except Exception:
            continue

        unidades.append({
            "row": unidad,
            "tabla": table_name,
            "planta": planta,
            "geom": geom,
            "construccion": helper.get_field_value(unidad, ("construccion",)),
            "identificador": helper.get_field_value(unidad, ("identificador", "t_id", "TID")),
        })

    for unidad in unidades:
        planta_superior = unidad["planta"]

        if planta_superior <= 1:
            continue

        planta_inferior = planta_superior - 1

        inferiores = [
            otra for otra in unidades
            if otra["planta"] == planta_inferior
            and otra["construccion"] == unidad["construccion"]
        ]

        if not inferiores:
            issues.append(
                helper.make_issue(
                    unidad["row"],
                    rule_id="10.3",
                    message=(
                        "La unidad de construcción ubicada en la planta superior "
                        "no se superpone con ninguna unidad en la planta inferior inmediata. "
                        "Esta condición es inconsistente espacialmente."
                    ),
                    details={
                        "tabla": unidad["tabla"],
                        "identificador": unidad["identificador"],
                        "construccion": unidad["construccion"],
                        "planta_superior": planta_superior,
                        "planta_inferior": planta_inferior,
                        "motivo": "No existe unidad en la planta inferior inmediata.",
                    },
                )
            )
            continue

        tiene_superposicion = False

        for inferior in inferiores:
            try:
                if unidad["geom"].intersects(inferior["geom"]):
                    tiene_superposicion = True
                    break
            except Exception:
                continue

        if not tiene_superposicion:
            issues.append(
                helper.make_issue(
                    unidad["row"],
                    rule_id="10.3",
                    message=(
                        "La unidad de construcción ubicada en la planta superior "
                        "no se superpone con ninguna unidad en la planta inferior inmediata. "
                        "Esta condición es inconsistente espacialmente."
                    ),
                    details={
                        "tabla": unidad["tabla"],
                        "identificador": unidad["identificador"],
                        "construccion": unidad["construccion"],
                        "planta_superior": planta_superior,
                        "planta_inferior": planta_inferior,
                        "unidades_inferiores_revisadas": len(inferiores),
                        "motivo": "Existe planta inferior, pero no hay superposición espacial.",
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
            ("arb_predio_novedad_numero_predial",),
        )

        if predio_ref:
            predios_con_novedad.add(str(predio_ref))

    # 🔹 2. validar predios
    for table_name, predio in helper.iter_predios():
        predio_id = helper.get_field_value(predio, ("t_id", "TID", "id"))

        numero_predial = helper.get_field_value(
            predio,
            ("numero_predial",),
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

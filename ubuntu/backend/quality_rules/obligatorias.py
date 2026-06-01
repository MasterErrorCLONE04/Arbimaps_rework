from __future__ import annotations

from .base import DatasetReader, RuleIssue
import json
import re

try:
    from shapely import wkb, wkt
    from shapely.geometry import shape
except Exception:
    wkb = None
    wkt = None
    shape = None

COMPONENT_SLUG = "obligatorias"

DEFAULT_RULE_IDS = frozenset({
    "11.1", "11.2", "11.3", "11.4", "11.5", "11.6", "11.7", "11.8", "11.9", "11.10",
    "11.11", "11.12","11.13", "11.14", "11.15", "11.16", "11.17", "11.18", "11.19", "11.20",
    "11.21", "11.22", "11.23", "11.24", "11.25", "11.26", "11.27", "11.28", "11.29", "11.30",
    "11.31", "11.32", "11.33", "11.34", "11.35", "11.36", "11.37", "11.38", "11.39", "11.40",
    "11.41", "11.42", "11.43", "11.44", "11.45", "11.46", "11.47", "11.48", "11.49", "11.50",
    "11.51", "11.52", "11.53", "11.54", "11.55", "11.56", "11.57", "11.58", "11.59", "11.60",
    "11.61", "11.62", "11.63", "11.64", "11.65", "11.66", "11.67", "11.68", "11.69", "11.70",
})


_EMPTY_TEXTS = {
    "",
    "NULL",
    "<NULL>",
    "NONE",
    "NAN",
    "0",
    "0.0",
    "NO APLICA",
    "NO_APLICA",
    "N/A",
    "NA",
    "S/D",
    "SD",
    "SIN DATO",
    "SIN DATOS",
    "SIN INFORMACION",
    "SIN INFORMACIÓN",
    "-",
    ".",
}


def _is_empty_value(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip().upper()
        text_no_accents = (
            text.replace("Á", "A")
            .replace("É", "E")
            .replace("Í", "I")
            .replace("Ó", "O")
            .replace("Ú", "U")
            .replace("Ñ", "N")
        )
        return text in _EMPTY_TEXTS or text_no_accents in _EMPTY_TEXTS
    return False


class ObligatoriasHelper:
    """Utilidades compartidas para reglas obligatorias."""
    IDENTIFIER_FIELDS = (
        "t_ili_tid",
        "T_Ili_Tid",
        "T_ILI_TID",
        "id_operacion",
        "t_id",
        "TID",
        "id",
        "identificador",
        "numero_predial",
        "etiqueta",
    )

    #campos

    NUMERO_PREDIAL_FIELDS = (
        "numero_predial",
        "Numero_Predial",

    )

    #capas

    PREDIO_TABLES = (
        "ARB_Predio",
        "arb_predio",
        "A_Predio",
        "a_predio",
    )

    UNIDAD_CONSTRUCCION_TABLES = (
        "ARB_UnidadConstruccion",
        "arb_unidadconstruccion",
        "D_Unidad_de_Construccion",
        "d_unidad_de_construccion",
        "ARB_Unidad_de_construcción",
        "ARB_Unidad_de_construccion",
    )

    DIRECCION = (
        "ARB_Direccion",
        "arb_direccion",
        "C_Direccion",
        "c_direccion",
    )

    INFORMACION_PH = (
        "ARB_InformacionPH",
        "arb_info",
        "Información PH",
        "Informacion PH",
        "informacion_ph",
    )

    CARACTERISTICAS_UNIDADES = (
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
        "ARB_Características_de_la_unidad_de_construcción",
        "ARB_Caracteristicas_de_la_unidad_de_construccion",
        "caracteristicas_calificacion",
        "Características Calificación",
        "Caracteristicas Calificacion",
    )

    TRAMITE = (
        "ARB_Tramite",
        "arb_tramite",
        "Tramites",
        "Trámites",
    )

    DERECHO_INTERESADO = (
        "ARB_DerechoInteresadoFuente",
        "arb_derechointeresadofuente",
        "ARB_Derecho_Interesado_Fuente",
        "Derecho Interesado Fuente",
        "derecho_interesado_fuente",
    )

    TERRENO = (
        "ARB_Terreno",
        "arb_terreno",
        "E_Terreno",
        "e_terreno",
    )

    PUNTO_REFERENCIA = (
        "ARB_PuntoReferencia",
        "arb_puntoreferencia",
        "Punto Referencia",
    )


    def __init__(self, dataset: DatasetReader):
        self.dataset = dataset

    def _iter_table_rows(self, table_names: tuple[str, ...]):
        seen: set[str] = set()

        for table_name in table_names:
            if not self.dataset.has_table(table_name):
                continue

            try:
                canonical = self.dataset.canonical_for(table_name) or table_name
            except Exception:
                canonical = table_name

            normalized = self._normalize_key(canonical)

            if normalized in seen:
                continue

            seen.add(normalized)

            for row in self.dataset.get_records(table_name):
                yield canonical, row

    def iter_predios(self):
        yield from self._iter_table_rows(self.PREDIO_TABLES)

    def iter_unidades_construccion(self):
        yield from self._iter_table_rows(self.UNIDAD_CONSTRUCCION_TABLES)

    def iter_direccion(self):
        yield from self._iter_table_rows(self.DIRECCION)

    def iter_informacion_ph(self):
        yield from self._iter_table_rows(self.INFORMACION_PH)

    def iter_caracteristicas_unidades(self):
        yield from self._iter_table_rows(self.CARACTERISTICAS_UNIDADES)

    def iter_tramite(self):
        yield from self._iter_table_rows(self.TRAMITE)

    def iter_derecho_interesado(self):
        yield from self._iter_table_rows(self.DERECHO_INTERESADO)

    def iter_terreno(self):
        yield from self._iter_table_rows(self.TERRENO)

    def iter_punto_diferencia(self):
        yield from self._iter_table_rows(self.PUNTO_REFERENCIA)

    def identify(self, row: dict[str, object]) -> str | None:
        for field in self.IDENTIFIER_FIELDS:
            value = row.get(field)
            if not _is_empty_value(value):
                return str(value).strip()

        normalized_targets = {self._normalize_key(field) for field in self.IDENTIFIER_FIELDS}
        for key, value in row.items():
            if self._normalize_key(str(key)) in normalized_targets and not _is_empty_value(value):
                return str(value).strip()

        return None

    def get_field_value(self, row: dict[str, object], candidates: tuple[str, ...]) -> str | None:
        normalized_candidates = {self._normalize_key(candidate) for candidate in candidates}

        for key, value in row.items():
            if self._normalize_key(str(key)) in normalized_candidates:
                if not _is_empty_value(value):
                    return str(value).strip()

        return None

    def _get_raw_field_value(self, row: dict[str, object], candidates: tuple[str, ...]) -> str | None:
        normalized_candidates = {self._normalize_key(candidate) for candidate in candidates}

        for key, value in row.items():
            if self._normalize_key(str(key)) in normalized_candidates:
                if value is not None and str(value).strip() != "":
                    return str(value).strip()

        return None

    def is_calificacion_convencional(self, row: dict[str, object]) -> bool:
        value = self._get_raw_field_value(row, ("tipo_calificacion", "Tipo de calificación", "Tipo de calificacion"))

        token = self._normalize_key(value)
        if token in {"3", "0", "noconvencional"} or "noconvencional" in token:
            return False
        if token in {"1", "tipologia"} or "tipologia" in token:
            return False
        if _is_empty_value(value):
            return True
        return token in {"2", "convencional"} or "convencional" in token

    def is_calificacion_tipologia(self, row: dict[str, object]) -> bool:
        value = self._get_raw_field_value(row, ("tipo_calificacion", "Tipo de calificación", "Tipo de calificacion"))

        token = self._normalize_key(value)
        if _is_empty_value(value) and token != "0":
            return False
        return token in {"1", "tipologia"} or "tipologia" in token

    def is_unidad_anexo(self, row: dict[str, object]) -> bool:
        value = self._get_raw_field_value(
            row,
            ("tipo_unidad_construccion", "Tipo de unidad de construcción", "Tipo de unidad de construccion"),
        )

        token = self._normalize_key(value)
        if _is_empty_value(value) and token != "0":
            return False
        return token in {"4", "289", "anexo"} or "anexo" in token

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


#------------------ reglas ------------------------------

def rule_11_1(dataset: DatasetReader) -> list[RuleIssue]:
    # Regla 11.1 deshabilitada temporalmente
    return []

    """
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        numero_predial = helper.get_field_value(row, helper.NUMERO_PREDIAL_FIELDS)

        if not numero_predial:
            continue

        codigo_departamento = numero_predial[0:2]
        codigo_municipio = numero_predial[2:5]

        if codigo_departamento == "41" and codigo_municipio == "001":
            continue

        issues.append(
            helper.make_issue(
                row,
                rule_id="11.1",
                message=(
                    "El codigo de departamento y municipio del numero predial "
                    "debe responder al DIVIPOLA"
                ),
                details={
                    "tabla": table_name,
                    "campo": "numero_predial",
                    "numero_predial": numero_predial,
                    "valor_encontrado_1_2": codigo_departamento,
                    "valor_esperado_1_2": "41",
                    "departamento_esperado": "HUILA",
                    "valor_encontrado_3_5": codigo_municipio,
                    "valor_esperado_3_5": "001",
                    "municipio_esperado": "NEIVA",
                },
            )
        )

    return issues
    """


def rule_11_2(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []


    predios_con_direccion: set[str] = set()

    for _, row in helper.iter_direccion():
        predio_ref = helper.get_field_value(
            row,
            ("arb_predio_direccion",),
        )

        if predio_ref:
            predios_con_direccion.add(str(predio_ref))


    for table_name, predio in helper.iter_predios():
        predio_id = helper.get_field_value(
            predio,
            ("t_id", "TID", "id"),
        )

        if not predio_id or str(predio_id) not in predios_con_direccion:
            numero_predial = helper.get_field_value(
                predio,
                ("numero_predial",),
            )

            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="11.2",
                    message="El predio no tiene dirección registrada.",
                    details={
                        "tabla": table_name,
                        "predio_id": predio_id,
                        "numero_predial": numero_predial,
                        "tiene_direccion": False,
                    },
                )
            )

    return issues


def rule_11_3(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, predio in helper.iter_predios():
        area = helper.get_field_value(
            predio,
            ("area_catastral_terreno",),
        )

        if area in (None, ""):
            numero_predial = helper.get_field_value(
                predio,
                ("numero_predial",),
            )

            predio_id = helper.get_field_value(
                predio,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="11.3",
                    message="El predio no tiene área catastral de terreno.",
                    details={
                        "tabla": table_name,
                        "predio_id": predio_id,
                        "numero_predial": numero_predial,
                        "area_catastral_terreno": area,
                        "tiene_area": False,
                    },
                )
            )

    return issues

def rule_11_4(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, predio in helper.iter_predios():
        numero_predial = helper.get_field_value(
            predio,
            ("numero_predial",),
        )

        if numero_predial in (None, ""):
            predio_id = helper.get_field_value(
                predio,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="11.4",
                    message="El predio no tiene número predial nacional.",
                    details={
                        "tabla": table_name,
                        "predio_id": predio_id,
                        "numero_predial": numero_predial,
                        "tiene_numero_predial": False,
                    },
                )
            )

    return issues

def rule_11_5(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, predio in helper.iter_predios():
        tipo = helper.get_field_value(
            predio,
            ("tipo",),
        )

        if tipo in (None, ""):
            predio_id = helper.get_field_value(
                predio,
                ("t_id", "TID", "id"),
            )

            numero_predial = helper.get_field_value(
                predio,
                ("numero_predial",),
            )

            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="11.5",
                    message="El predio no tiene clasificación de tipo de predio.",
                    details={
                        "tabla": table_name,
                        "predio_id": predio_id,
                        "numero_predial": numero_predial,
                        "tipo": tipo,
                        "tiene_tipo": False,
                    },
                )
            )

    return issues

def rule_11_6(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, predio in helper.iter_predios():
        condicion = helper.get_field_value(
            predio,
            ("condicion_predio",),
        )

        if condicion in (None, ""):
            predio_id = helper.get_field_value(
                predio,
                ("t_id", "TID", "id"),
            )

            numero_predial = helper.get_field_value(
                predio,
                ("numero_predial",),
            )

            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="11.6",
                    message="El predio no tienen asignada una condición.",
                    details={
                        "tabla": table_name,
                        "predio_id": predio_id,
                        "numero_predial": numero_predial,
                        "condicion": condicion,
                        "tiene_condicion": False,
                    },
                )
            )

    return issues

def rule_11_7(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, predio in helper.iter_predios():
        destinacion_economica = helper.get_field_value(
            predio,
            ("destinacion_economica",),
        )

        if destinacion_economica in (None, ""):
            predio_id = helper.get_field_value(
                predio,
                ("t_id", "TID", "id"),
            )

            numero_predial = helper.get_field_value(
                predio,
                ("numero_predial",),
            )

            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="11.7",
                    message="El predio no tiene definida la destinación económica.",
                    details={
                        "tabla": table_name,
                        "predio_id": predio_id,
                        "numero_predial": numero_predial,
                        "destinacion_economica": destinacion_economica,
                        "tiene_destinacion_economica": False,
                    },
                )
            )

    return issues

def rule_11_8(dataset: DatasetReader) ->list[RuleIssue]:
    return[]

def rule_11_9(dataset: DatasetReader) ->list[RuleIssue]:
    return[]

def rule_11_10(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, predio in helper.iter_predios():
        resultado_visita = helper.get_field_value(
            predio,
            ("resultado_visita",),
        )

        if resultado_visita in (None, ""):
            predio_id = helper.get_field_value(
                predio,
                ("t_id", "TID", "id"),
            )

            numero_predial = helper.get_field_value(
                predio,
                ("numero_predial",),
            )

            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="11.10",
                    message="El predio no tiene resultado de la visita.",
                    details={
                        "tabla": table_name,
                        "predio_id": predio_id,
                        "numero_predial": numero_predial,
                        "resultado_visita": resultado_visita,
                        "tiene_resultado_visita": False,
                    },
                )
            )

    return issues

def rule_11_11(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, predio in helper.iter_predios():
        comadato = helper.get_field_value(
            predio,
            ("comodato",),
        )

        if comadato in (None, ""):
            predio_id = helper.get_field_value(
                predio,
                ("t_id", "TID", "id"),
            )

            numero_predial = helper.get_field_value(
                predio,
                ("numero_predial",),
            )

            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="11.11",
                    message="El predio no tiene el campo comodato diligenciado.",
                    details={
                        "tabla": table_name,
                        "predio_id": predio_id,
                        "numero_predial": numero_predial,
                        "comadato": comadato,
                        "tiene_comadato": False,
                    },
                )
            )

    return issues

def rule_11_12(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, predio in helper.iter_predios():
        comunidades_indegenas = helper.get_field_value(
            predio,
            ("beneficio_comunidades_indigenas",),
        )

        if comunidades_indegenas in (None, ""):
            predio_id = helper.get_field_value(
                predio,
                ("t_id", "TID", "id"),
            )

            numero_predial = helper.get_field_value(
                predio,
                ("numero_predial",),
            )

            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="11.12",
                    message="El predio no tiene el campo beneficio de comunidades indígenas diligenciado.",
                    details={
                        "tabla": table_name,
                        "predio_id": predio_id,
                        "numero_predial": numero_predial,
                        "comunidades_indegenas": comunidades_indegenas,
                        "tiene_comunidades_indegenas": False,
                    },
                )
            )

    return issues

def rule_11_13(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, predio in helper.iter_predios():
        datos_quien_atendio_visita = helper.get_field_value(
            predio,
            ("nombres_apellidos_quien_atendio",),
        )

        if datos_quien_atendio_visita in (None, ""):
            predio_id = helper.get_field_value(
                predio,
                ("t_id", "TID", "id"),
            )

            numero_predial = helper.get_field_value(
                predio,
                ("numero_predial",),
            )

            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="11.13",
                    message="El predio no tiene datos de quien atendió la visita.",
                    details={
                        "tabla": table_name,
                        "predio_id": predio_id,
                        "numero_predial": numero_predial,
                        "datos_quien_atendio_visita": datos_quien_atendio_visita,
                        "tiene_datos_quien_atendio_visita": False,
                    },
                )
            )

    return issues

def rule_11_14(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, predio in helper.iter_predios():
        autoriza_notificaciones = helper.get_field_value(
            predio,
            ("autoriza_notificaciones",),
        )

        if autoriza_notificaciones in (None, ""):
            predio_id = helper.get_field_value(
                predio,
                ("t_id", "TID", "id"),
            )

            numero_predial = helper.get_field_value(
                predio,
                ("numero_predial",),
            )

            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="11.14",
                    message="El predio no tiene el campo autorización de notificacione diligenciado.",
                    details={
                        "tabla": table_name,
                        "predio_id": predio_id,
                        "numero_predial": numero_predial,
                        "autoriza_notificaciones": autoriza_notificaciones,
                        "tiene_autoriza_notificaciones": False,
                    },
                )
            )

    return issues

def rule_11_15(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, unidad_construccion in helper.iter_unidades_construccion():
        tipo_planta = helper.get_field_value(
            unidad_construccion,
            ("tipo_planta",),
        )

        if tipo_planta in (None, ""):
            unidad_id = helper.get_field_value(
                unidad_construccion,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    unidad_construccion,
                    rule_id="11.15",
                    message="La unidad de construcción no tiene asignado el tipo de planta.",
                    details={
                        "tabla": table_name,
                        "unidad_construccion_id": unidad_id,
                        "tipo_planta": tipo_planta,
                        "tiene_tipo_planta": False,
                    },
                )
            )

    return issues

def rule_11_16(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, unidad_construccion in helper.iter_unidades_construccion():
        ubicacion_planta = helper.get_field_value(
            unidad_construccion,
            ("planta_ubicacion",),
        )

        if ubicacion_planta in (None, ""):
            unidad_id = helper.get_field_value(
                unidad_construccion,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    unidad_construccion,
                    rule_id="11.16",
                    message="La unidad de construcción no tiene la ubicación de la planta.",
                    details={
                        "tabla": table_name,
                        "unidad_construccion_id": unidad_id,
                        "ubicacion_planta": ubicacion_planta,
                        "tiene_ubicacion_planta": False,
                    },
                )
            )

    return issues

def rule_11_17(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, unidad_construccion in helper.iter_unidades_construccion():
        altura_unidad = helper.get_field_value(
            unidad_construccion,
            ("altura",),
        )

        if altura_unidad in (None, ""):
            unidad_id = helper.get_field_value(
                unidad_construccion,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    unidad_construccion,
                    rule_id="11.17",
                    message="La altura de la unidad de construcción no está diligenciada.",
                    details={
                        "tabla": table_name,
                        "unidad_construccion_id": unidad_id,
                        "altura_unidad": altura_unidad,
                        "tiene_altura_unidad": False,
                    },
                )
            )

    return issues

def rule_11_18(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, unidad in helper.iter_unidades_construccion():
        geometria = helper.get_field_value(
            unidad,
            ("geometria", "geometry", "geom",),
        )

        if geometria in (None, ""):
            unidad_id = helper.get_field_value(
                unidad,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    unidad,
                    rule_id="11.18",
                    message="La unidad de construcción no tiene geometría.",
                    details={
                        "tabla": table_name,
                        "unidad_construccion_id": unidad_id,
                        "geometria": geometria,
                        "tiene_geometria": False,
                    },
                )
            )

    return issues

def rule_11_19(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, informacion_ph in helper.iter_informacion_ph():
        area_terreno = helper.get_field_value(
            informacion_ph,
            ("area_total_terreno",),
        )

        if area_terreno in (None, ""):
            informacion_ph_id = helper.get_field_value(
                informacion_ph,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    informacion_ph,
                    rule_id="11.19",
                    message="La propiedad horizontal no cuenta con el área del terreno.",
                    details={
                        "tabla": table_name,
                        "informacion_ph_id": informacion_ph_id,
                        "area_terreno": area_terreno,
                        "tiene_area_terreno": False,
                    },
                )

            )

    return issues


def rule_11_20(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, informacion_ph in helper.iter_informacion_ph():
        area_terreno_privada = helper.get_field_value(
            informacion_ph,
            ("area_total_terreno_privada",),
        )

        if area_terreno_privada in (None, ""):
            informacion_ph_id = helper.get_field_value(
                informacion_ph,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    informacion_ph,
                    rule_id="11.20",
                    message="La propiedad horizontal no cuenta con el área privada del terreno.",
                    details={
                        "tabla": table_name,
                        "informacion_ph_id": informacion_ph_id,
                        "area_terreno_privada ": area_terreno_privada ,
                        "tiene_area_terreno_privada ": False,
                    },
                )

            )

    return issues

def rule_11_21(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, informacion_ph in helper.iter_informacion_ph():
        area_terreno_comun = helper.get_field_value(
            informacion_ph,
            ("area_total_terreno_comun",),
        )

        if area_terreno_comun in (None, ""):
            informacion_ph_id = helper.get_field_value(
                informacion_ph,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    informacion_ph,
                    rule_id="11.21",
                    message="La propiedad horizontal no cuenta con el área común del terreno.",
                    details={
                        "tabla": table_name,
                        "informacion_ph_id": informacion_ph_id,
                        "area_terreno_comun ": area_terreno_comun ,
                        "tiene_area_terreno_comun": False,
                    },
                )

            )

    return issues

def rule_11_22(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, informacion_ph in helper.iter_informacion_ph():
        area_total_construida = helper.get_field_value(
            informacion_ph,
            ("area_total_construida",),
        )

        if area_total_construida in (None, ""):
            informacion_ph_id = helper.get_field_value(
                informacion_ph,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    informacion_ph,
                    rule_id="11.22",
                    message="La propiedad horizontal no tiene el área construida.",
                    details={
                        "tabla": table_name,
                        "informacion_ph_id": informacion_ph_id,
                        "area_total_construida ": area_total_construida,
                        "tiene_area_total_construida": False,
                    },
                )

            )

    return issues

def rule_11_23(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, informacion_ph in helper.iter_informacion_ph():
        area_total_construida_privada = helper.get_field_value(
            informacion_ph,
            ("area_total_construida_privada",),
        )

        if area_total_construida_privada in (None, ""):
            informacion_ph_id = helper.get_field_value(
                informacion_ph,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    informacion_ph,
                    rule_id="11.23",
                    message="La propiedad horizontal no tiene el área construida privada.",
                    details={
                        "tabla": table_name,
                        "informacion_ph_id": informacion_ph_id,
                        "area_total_construida_privada": area_total_construida_privada,
                        "tiene_area_total_construida_privada": False,
                    },
                )

            )

    return issues

def rule_11_24(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, informacion_ph in helper.iter_informacion_ph():
        area_total_construida_comun = helper.get_field_value(
            informacion_ph,
            ("area_total_construida_comun",),
        )

        if area_total_construida_comun in (None, ""):
            informacion_ph_id = helper.get_field_value(
                informacion_ph,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    informacion_ph,
                    rule_id="11.24",
                    message="La propiedad horizontal no tiene el área construida común.",
                    details={
                        "tabla": table_name,
                        "informacion_ph_id": informacion_ph_id,
                        "area_total_construida_comun": area_total_construida_comun,
                        "tiene_area_total_construida_comun": False,
                    },
                )

            )

    return issues

def rule_11_25(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, informacion_ph in helper.iter_informacion_ph():
        numero_torres = helper.get_field_value(
            informacion_ph,
            ("numero_torres",),
        )

        if numero_torres in (None, ""):
            informacion_ph_id = helper.get_field_value(
                informacion_ph,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    informacion_ph,
                    rule_id="11.25",
                    message="La propiedad horizontal no tiene el número de torres.",
                    details={
                        "tabla": table_name,
                        "informacion_ph_id": informacion_ph_id,
                        "numero_torres": numero_torres,
                        "tiene_numero_torres": False,
                    },
                )

            )

    return issues

def rule_11_26(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, informacion_ph in helper.iter_informacion_ph():
        total_unidades_privadas = helper.get_field_value(
            informacion_ph,
            ("total_unidades_privadas",),
        )

        if total_unidades_privadas in (None, ""):
            informacion_ph_id = helper.get_field_value(
                informacion_ph,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    informacion_ph,
                    rule_id="11.26",
                    message="La propiedad horizontal no tiene el total de unidades privadas.",
                    details={
                        "tabla": table_name,
                        "informacion_ph_id": informacion_ph_id,
                        "total_unidades_privadas": total_unidades_privadas,
                        "tiene_total_unidades_privadas": False,
                    },
                )

            )

    return issues

def rule_11_27(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        tipo_unidad = helper.get_field_value(
            caracteristicas_unidades,
            ("tipo_unidad_construccion",),
        )

        if tipo_unidad in (None,""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.27",
                    message="El tipo de unidad de construcción no está diligenciado.",
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "tipo_unidad": tipo_unidad,
                        "tiene_tipo_unidad": False,
                    },
                )
            )

    return issues

def rule_11_28(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        total_plantas = helper.get_field_value(
            caracteristicas_unidades,
            ("total_plantas",),
        )

        if total_plantas in (None,""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.28",
                    message="El total de plantas de la unidad de construcción no está diligenciado.",
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "total_plantas": total_plantas,
                        "tiene_total_plantas": False,
                    },
                )
            )

    return issues

def rule_11_29(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        uso = helper.get_field_value(
            caracteristicas_unidades,
            ("uso",),
        )

        if uso in (None,""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.29",
                    message="El uso de la unidad de construcción no está diligenciado.",
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "uso": uso,
                        "tiene_uso": False,
                    },
                )
            )

    return issues

def rule_11_30(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        año_costruccion = helper.get_field_value(
            caracteristicas_unidades,
            ("anio_construccion",),
        )

        if año_costruccion in (None,""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.30",
                    message="El año de la unidad de construcción no está diligenciado.",
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "año_costruccion": año_costruccion,
                        "tiene_año_costruccion": False,
                    },
                )
            )

    return issues

def rule_11_31(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        area_construida = helper.get_field_value(
            caracteristicas_unidades,
            ("area_construida",),
        )

        if area_construida in (None,""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.31",
                    message="El área construida de la unidad de construcción no está diligenciada.",
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "area_construida": area_construida,
                        "tiene_area_construida ": False,
                    },
                )
            )

    return issues

def rule_11_32(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        if not helper.is_calificacion_convencional(caracteristicas_unidades):
            continue

        calificacion_armazon = helper.get_field_value(
            caracteristicas_unidades,
            ("cc_armazon",),
        )

        if calificacion_armazon  in (None,""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.32",
                    message="El armazón no se encuentra calificado.",
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "calificacion_armazon": calificacion_armazon ,
                        "tiene_calificacion_armazon": False,
                    },
                )
            )

    return issues

def rule_11_33(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        if not helper.is_calificacion_convencional(caracteristicas_unidades):
            continue

        calificacion_muros = helper.get_field_value(
            caracteristicas_unidades,
            ("cc_muros",),
        )

        if calificacion_muros  in (None,""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.33",
                    message="Los muros no se encuentran calificados.",
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "calificacion_muros": calificacion_muros,
                        "tiene_calificacion_muros": False,
                    },
                )
            )

    return issues

def rule_11_34(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        if not helper.is_calificacion_convencional(caracteristicas_unidades):
            continue

        calificacion_cubierta = helper.get_field_value(
            caracteristicas_unidades,
            ("cc_cubierta",),
        )

        if calificacion_cubierta  in (None,""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.34",
                    message="La cubierta no se encuentra calificada.",
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "calificacion_cubierta": calificacion_cubierta,
                        "tiene_calificacion_cubierta": False,
                    },
                )
            )

    return issues

def rule_11_35(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        if not helper.is_calificacion_convencional(caracteristicas_unidades):
            continue

        calificacion_conservacion_estructura = helper.get_field_value(
            caracteristicas_unidades,
            ("cc_conservacion_estructura",),
        )

        if calificacion_conservacion_estructura  in (None,""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.35",
                    message="La conservación de la estuctura no se encuentra calificada.",
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "calificacion_conservacion_estructura": calificacion_conservacion_estructura,
                        "tiene_calificacion_conservacion_estructura": False,
                    },
                )
            )

    return issues

def rule_11_36(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        if not helper.is_calificacion_convencional(caracteristicas_unidades):
            continue

        calificacion_fachada = helper.get_field_value(
            caracteristicas_unidades,
            ("cc_fachada",),
        )

        if calificacion_fachada  in (None,""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.36",
                    message="La fachada no se encuentra calificada.",
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "calificacion_fachada": calificacion_fachada,
                        "tiene_calificacion_fachada": False,
                    },
                )
            )

    return issues

def rule_11_37(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        if not helper.is_calificacion_convencional(caracteristicas_unidades):
            continue

        calificacion_cubrimiento_muros = helper.get_field_value(
            caracteristicas_unidades,
            ("cc_cubrimiento_muros",),
        )

        if calificacion_cubrimiento_muros  in (None,""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.37",
                    message="El cubrimiento de los muros no se encuentra calificado.",
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "calificacion_cubrimiento_muros": calificacion_cubrimiento_muros,
                        "tiene_calificacion_cubrimiento_muros": False,
                    },
                )
            )

    return issues

def rule_11_38(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        if not helper.is_calificacion_convencional(caracteristicas_unidades):
            continue

        calificacion_pisos = helper.get_field_value(
            caracteristicas_unidades,
            ("cc_piso",),
        )

        if calificacion_pisos  in (None,""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.38",
                    message="El piso no se encuentra calificado.",
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "calificacion_pisos": calificacion_pisos,
                        "tiene_calificacion_pisos": False,
                    },
                )
            )

    return issues

def rule_11_39(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        if not helper.is_calificacion_convencional(caracteristicas_unidades):
            continue

        calificacion_conservacion_acabados = helper.get_field_value(
            caracteristicas_unidades,
            ("cc_conservacion_acabados",),
        )

        if calificacion_conservacion_acabados  in (None,""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.39",
                    message="La conservación de los acabados no se encuentra calificada.",
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "calificacion_conservacion_acabados": calificacion_conservacion_acabados,
                        "tiene_calificacion_conservacion_acabados": False,
                    },
                )
            )

    return issues

def rule_11_40(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        if not helper.is_calificacion_convencional(caracteristicas_unidades):
            continue

        calificacion_mobiliario_baño = helper.get_field_value(
            caracteristicas_unidades,
            ("cc_mobiliario_banio",),
        )

        if calificacion_mobiliario_baño  in (None,""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.40",
                    message="El mobiliario del baño no se encuentra calificado.",
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "calificacion_mobiliario_baño": calificacion_mobiliario_baño,
                        "tiene_calificacion_mobiliario_baño": False,
                    },
                )
            )

    return issues

def rule_11_41(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        if not helper.is_calificacion_convencional(caracteristicas_unidades):
            continue

        calificacion_mobiliario_cocina = helper.get_field_value(
            caracteristicas_unidades,
            ("cc_mobiliario_cocina",),
        )

        if calificacion_mobiliario_cocina  in (None,""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.41",
                    message="El mobiliario de la cocina no se encuentra calificado.",
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "calificacion_mobiliario_cocina": calificacion_mobiliario_cocina,
                        "tiene_calificacion_mobiliario_cocina": False,
                    },
                )
            )

    return issues

def rule_11_42(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        total_calificacion = helper.get_field_value(
            caracteristicas_unidades,
            ("cc_total_calificacion",),
        )

        if total_calificacion in (None,""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.42",
                    message="La calificación no tiene total asignado.",
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "total_calificacion": total_calificacion,
                        "tiene_total_calificacion": False,
                    },
                )
            )

    return issues

def rule_11_43(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, tramites in helper.iter_tramite():
        entidad_tramite = helper.get_field_value(
            tramites,
            ("entidad",),
        )

        if entidad_tramite  in (None,""):
            tramites_id = helper.get_field_value(
                tramites,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    tramites,
                    rule_id="11.43",
                    message="La entidad del trámite no se encuentra diligenciada.",
                    details={
                        "tabla": table_name,
                        "tramites_id": tramites_id,
                        "entidad_tramite ": entidad_tramite ,
                        "tiene_entidad_tramite ": False,
                    },
                )
            )

    return issues

def rule_11_44(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, derecho_interesado in helper.iter_derecho_interesado():
        tipo_derecho = helper.get_field_value(
            derecho_interesado,
            ("d_tipo",),
        )

        if tipo_derecho  in (None,""):
            derecho_interesado_id = helper.get_field_value(
                derecho_interesado,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    derecho_interesado,
                    rule_id="11.44",
                    message="Los derechos existentes no tienen un tipo definido.",
                    details={
                        "tabla": table_name,
                        "derecho_interesado_id": derecho_interesado_id,
                        "tipo_derecho": tipo_derecho,
                        "tiene_tipo_derecho ": False,
                    },
                )
            )

    return issues

def rule_11_45(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, derecho_interesado in helper.iter_derecho_interesado():
        posesion_ancestral_y_o_tradicional = helper.get_field_value(
            derecho_interesado,
            ("d_posesion_ancestral_y_o_tradicional",),
        )

        if posesion_ancestral_y_o_tradicional  in (None,""):
            derecho_interesado_id = helper.get_field_value(
                derecho_interesado,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    derecho_interesado,
                    rule_id="11.45",
                    message="Los derechos no tienen información sobre la posesión ancestral o tradicional.",
                    details={
                        "tabla": table_name,
                        "derecho_interesado_id": derecho_interesado_id,
                        "posesion_ancestral_y_o_tradicional": posesion_ancestral_y_o_tradicional,
                        "tiene_posesion_ancestral_y_o_tradicional": False,
                    },
                )
            )

    return issues

def rule_11_46(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, derecho_interesado in helper.iter_derecho_interesado():
        fecha_inicio_tenencia = helper.get_field_value(
            derecho_interesado,
            ("d_fecha_inicio_tenencia",),
        )

        if fecha_inicio_tenencia  in (None,""):
            derecho_interesado_id = helper.get_field_value(
                derecho_interesado,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    derecho_interesado,
                    rule_id="11.46",
                    message="Los derechos no tienen fecha de inicio de tenencia.",
                    details={
                        "tabla": table_name,
                        "derecho_interesado_id": derecho_interesado_id,
                        "fecha_inicio_tenencia": fecha_inicio_tenencia,
                        "tiene_fecha_inicio_tenencia": False,
                    },
                )
            )

    return issues

def rule_11_47(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, derecho_interesado in helper.iter_derecho_interesado():
        tipo_fuente_administrativa = helper.get_field_value(
            derecho_interesado,
            ("fa_tipo",),
        )

        if tipo_fuente_administrativa in (None,""):
            derecho_interesado_id = helper.get_field_value(
                derecho_interesado,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    derecho_interesado,
                    rule_id="11.47",
                    message="Las fuentes administrativas no tienen un tipo definido.",
                    details={
                        "tabla": table_name,
                        "derecho_interesado_id": derecho_interesado_id,
                        "tipo_fuente_administrativa": tipo_fuente_administrativa,
                        "tiene_tipo_fuente_administrativa": False,
                    },
                )
            )

    return issues

def rule_11_48(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, derecho_interesado in helper.iter_derecho_interesado():
        tipo_fuente_administrativa = helper.get_field_value(
            derecho_interesado,
            ("fa_tipo",),
        )

        if tipo_fuente_administrativa in (None,""):
            derecho_interesado_id = helper.get_field_value(
                derecho_interesado,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    derecho_interesado,
                    rule_id="11.48",
                    message="El interesado no tiene un tipo definido.",
                    details={
                        "tabla": table_name,
                        "derecho_interesado_id": derecho_interesado_id,
                        "tipo_fuente_administrativa": tipo_fuente_administrativa,
                        "tiene_tipo_fuente_administrativa": False,
                    },
                )
            )

    return issues

def rule_11_49(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, derecho_interesado in helper.iter_derecho_interesado():
        tipo_documento = helper.get_field_value(
            derecho_interesado,
            ("i_tipo_documento",),
        )

        if tipo_documento in (None,""):
            derecho_interesado_id = helper.get_field_value(
                derecho_interesado,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    derecho_interesado,
                    rule_id="11.49",
                    message="El interesado no tiene un tipo de documento definido.",
                    details={
                        "tabla": table_name,
                        "derecho_interesado_id": derecho_interesado_id,
                        "tipo_documento": tipo_documento,
                        "tiene_tipo_documento": False,
                    },
                )
            )

    return issues

def rule_11_50(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, derecho_interesado in helper.iter_derecho_interesado():
        documento_identidad = helper.get_field_value(
            derecho_interesado,
            ("i_documento_identidad",),
        )

        if documento_identidad in (None,""):
            derecho_interesado_id = helper.get_field_value(
                derecho_interesado,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    derecho_interesado,
                    rule_id="11.50",
                    message="El interesado no tiene documento de identidad.",
                    details={
                        "tabla": table_name,
                        "derecho_interesado_id": derecho_interesado_id,
                        "documento_identidad": documento_identidad,
                        "tiene_documento_identidad": False,
                    },
                )
            )

    return issues

def rule_11_51(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, derecho_interesado in helper.iter_derecho_interesado():
        autorreconocimiento_campesino = helper.get_field_value(
            derecho_interesado,
            ("i_autorreconocimiento_campesino",),
        )

        if autorreconocimiento_campesino in (None,""):
            derecho_interesado_id = helper.get_field_value(
                derecho_interesado,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    derecho_interesado,
                    rule_id="11.51",
                    message="El interesado no se reconoce como campesino.",
                    details={
                        "tabla": table_name,
                        "derecho_interesado_id": derecho_interesado_id,
                        "autorreconocimiento_campesino": autorreconocimiento_campesino,
                        "tiene_autorreconocimiento_campesino": False,
                    },
                )
            )

    return issues

def rule_11_52(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, derecho_interesado in helper.iter_derecho_interesado():
        nombre_pueblo = helper.get_field_value(
            derecho_interesado,
            ("ie_nombre_pueblo",),
        )

        grupo_etnico = helper.get_field_value(
            derecho_interesado,
            ("i_grupo_etnico",),
        )

        if str(grupo_etnico) in {'8', '0', 'Etnico.Indigena'} and nombre_pueblo in (None, ''):
            derecho_interesado_id = helper.get_field_value(
                derecho_interesado,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    derecho_interesado,
                    rule_id="11.52",
                    message="El interesado pertenece al grupo étnico Indígena y no tiene diligenciado el nombre del pueblo.",
                    details={
                        "tabla": table_name,
                        "derecho_interesado_id": derecho_interesado_id,
                        "grupo_etnico": grupo_etnico,
                        "ie_nombre_pueblo": nombre_pueblo,
                    },
                )
            )

    return issues

def rule_11_53(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, derecho_interesado in helper.iter_derecho_interesado():
        autoriza_notificacion_correo = helper.get_field_value(
            derecho_interesado,
            ("ic_autoriza_notificacion_correo",),
        )

        if autoriza_notificacion_correo in (None,""):
            derecho_interesado_id = helper.get_field_value(
                derecho_interesado,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    derecho_interesado,
                    rule_id="11.53",
                    message="El interesado no tiene información sobre la autorización de notificaciones " \
                    "vía correo electrónico.",
                    details={
                        "tabla": table_name,
                        "derecho_interesado_id": derecho_interesado_id,
                        "autoriza_notificacion_correo": autoriza_notificacion_correo,
                        "tiene_autoriza_notificacion_correo": False,
                    },
                )
            )

    return issues

def rule_11_54(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, derecho_interesado in helper.iter_derecho_interesado():
        departamento = helper.get_field_value(
            derecho_interesado,
            ("ic_departamento",),
        )

        if departamento in (None,""):
            derecho_interesado_id = helper.get_field_value(
                derecho_interesado,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    derecho_interesado,
                    rule_id="11.54",
                    message="El interesado no tiene información del departamento",
                    details={
                        "tabla": table_name,
                        "derecho_interesado_id": derecho_interesado_id,
                        "departamento": departamento,
                        "tiene_departamento": False,
                    },
                )
            )

    return issues

def rule_11_55(dataset: DatasetReader) ->list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, derecho_interesado in helper.iter_derecho_interesado():
        municipio = helper.get_field_value(
            derecho_interesado,
            ("ic_municipio",),
        )

        if municipio in (None,""):
            derecho_interesado_id = helper.get_field_value(
                derecho_interesado,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    derecho_interesado,
                    rule_id="11.55",
                    message="El interesado no tiene información del municipio",
                    details={
                        "tabla": table_name,
                        "derecho_interesado_id": derecho_interesado_id,
                        "municipio": municipio,
                        "tiene_municipio": False,
                    },
                )
            )

    return issues

def rule_11_56(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, terreno in helper.iter_terreno():
        geometria = helper.get_field_value(
            terreno,
            ("geometria", "geometry", "geom",),
        )

        if geometria in (None, ""):
            terreno_id = helper.get_field_value(
                terreno,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    terreno,
                    rule_id="11.56",
                    message="El terreno no tiene asociada una geometría.",
                    details={
                        "tabla": table_name,
                        "terreno_id": terreno_id,
                        "geometria": geometria,
                        "tiene_geometria": False,
                    },
                )
            )

    return issues

def rule_11_57(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        tipo_anexo = helper.get_field_value(
            caracteristicas_unidades,
            ("cnc_tipo_anexo",),
        )

        tipo_unidad_construccion = helper.get_field_value(
            caracteristicas_unidades,
            ("tipo_unidad_construccion",),
        )

        if helper.is_unidad_anexo(caracteristicas_unidades) and tipo_anexo in (None, ""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.57",
                    message=(
                        "La característica de unidad de construcción no tiene "
                        "información sobre el tipo de anexo."
                    ),
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "tipo_unidad_construccion": tipo_unidad_construccion,
                        "tipo_anexo": tipo_anexo,
                        "tiene_tipo_anexo": False,
                    },
                )
            )

    return issues

def rule_11_58(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        conservacion_anexo = helper.get_field_value(
            caracteristicas_unidades,
            ("cnc_conservacion_anexo",),
        )

        tipo_unidad_construccion = helper.get_field_value(
            caracteristicas_unidades,
            ("tipo_unidad_construccion",),
        )

        if helper.is_unidad_anexo(caracteristicas_unidades) and conservacion_anexo in (None, ""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.58",
                    message=(
                        "La característica de unidad de construcción no tiene "
                        "información sobre la conservación del anexo"
                    ),
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "tipo_unidad_construccion": tipo_unidad_construccion,
                        "conservacion_anexo": conservacion_anexo,
                        "tiene_conservacion_anexo": False,
                    },
                )
            )

    return issues

def rule_11_59(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        tipo_tipologia = helper.get_field_value(
            caracteristicas_unidades,
            ("ct_tipo_tipologia",),
        )

        tipo_unidad_construccion = helper.get_field_value(
            caracteristicas_unidades,
            ("tipo_unidad_construccion",),
        )

        if helper.is_calificacion_tipologia(caracteristicas_unidades) and tipo_tipologia in (None, ""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.59",
                    message=(
                        "La característica de unidad de construcción "
                        "no tiene información sobre el tipo de tipología"
                    ),
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "tipo_unidad_construccion": tipo_unidad_construccion,
                        "tipo_tipologia": tipo_tipologia,
                        "tiene_tipo_tipologia": False,
                    },
                )
            )

    return issues

def rule_11_60(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, caracteristicas_unidades in helper.iter_caracteristicas_unidades():
        conservacion_tipologia = helper.get_field_value(
            caracteristicas_unidades,
            ("ct_conservacion_tipologia",),
        )

        tipo_unidad_construccion = helper.get_field_value(
            caracteristicas_unidades,
            ("tipo_unidad_construccion",),
        )

        if helper.is_calificacion_tipologia(caracteristicas_unidades) and conservacion_tipologia in (None, ""):
            caracteristicas_unidades_id = helper.get_field_value(
                caracteristicas_unidades,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    caracteristicas_unidades,
                    rule_id="11.60",
                    message=(
                        "La característica de unidad de construcción no "
                        "tiene información sobre la conservación de la tipología"
                    ),
                    details={
                        "tabla": table_name,
                        "caracteristicas_unidades_id": caracteristicas_unidades_id,
                        "tipo_unidad_construccion": tipo_unidad_construccion,
                        "conservacion_tipologia": conservacion_tipologia,
                        "tiene_conservacion_tipologiaa": False,
                    },
                )
            )

    return issues

def rule_11_61(dataset: DatasetReader) ->list[RuleIssue]:
    return[]

def rule_11_62(dataset: DatasetReader) ->list[RuleIssue]:
    return[]

def rule_11_63(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, punto_referencia in helper.iter_punto_diferencia():
        geometria = helper.get_field_value(
            punto_referencia,
            ("geometria", "geometry", "geom",),
        )

        if geometria in (None, ""):
            punto_referencia_id = helper.get_field_value(
                punto_referencia,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    punto_referencia,
                    rule_id="11.63",
                    message="El punto de referencia no una geometría asociada.",
                    details={
                        "tabla": table_name,
                        "punto_referencia_id": punto_referencia_id,
                        "geometria": geometria,
                        "tiene_geometria": False,
                    },
                )
            )

    return issues

def rule_11_64(dataset: DatasetReader) ->list[RuleIssue]:
    return[]


def rule_11_65(dataset: DatasetReader) -> list[RuleIssue]:
    helper = ObligatoriasHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, punto_referencia in helper.iter_punto_diferencia():
        tipo_punto_referencia = helper.get_field_value(
            punto_referencia,
            ("tipo_punto_referencia",),
        )

        if tipo_punto_referencia in (None, ""):
            punto_referencia_id = helper.get_field_value(
                punto_referencia,
                ("t_id", "TID", "id"),
            )

            issues.append(
                helper.make_issue(
                    punto_referencia,
                    rule_id="11.65",
                    message="El punto no tiene información sobre el tipo de referencia.",
                    details={
                        "tabla": table_name,
                        "punto_referencia_id": punto_referencia_id,
                        "tipo_punto_referencia": tipo_punto_referencia,
                        "tiene_tipo_punto_referencia": False,
                    },
                )
            )

    return issues


RULE_FUNCTIONS = {
    "11.1": rule_11_1,
    "11.2": rule_11_2,
    "11.3": rule_11_3,
    "11.4": rule_11_4,
    "11.5": rule_11_5,
    "11.6": rule_11_6,
    "11.7": rule_11_7,
    "11.8": rule_11_8,
    "11.9": rule_11_9,
    "11.10": rule_11_10,
    "11.11": rule_11_11,
    "11.12": rule_11_12,
    "11.13": rule_11_13,
    "11.14": rule_11_14,
    "11.15": rule_11_15,
    "11.16": rule_11_16,
    "11.17": rule_11_17,
    "11.18": rule_11_18,
    "11.19": rule_11_19,
    "11.20": rule_11_20,
    "11.21": rule_11_21,
    "11.22": rule_11_22,
    "11.23": rule_11_23,
    "11.24": rule_11_24,
    "11.25": rule_11_25,
    "11.26": rule_11_26,
    "11.27": rule_11_27,
    "11.28": rule_11_28,
    "11.29": rule_11_29,
    "11.30": rule_11_30,
    "11.31": rule_11_31,
    "11.32": rule_11_32,
    "11.33": rule_11_33,
    "11.34": rule_11_34,
    "11.35": rule_11_35,
    "11.36": rule_11_36,
    "11.37": rule_11_37,
    "11.38": rule_11_38,
    "11.39": rule_11_39,
    "11.40": rule_11_40,
    "11.41": rule_11_41,
    "11.42": rule_11_42,
    "11.43": rule_11_43,
    "11.44": rule_11_44,
    "11.45": rule_11_45,
    "11.46": rule_11_46,
    "11.47": rule_11_47,
    "11.48": rule_11_48,
    "11.49": rule_11_49,
    "11.50": rule_11_50,
    "11.51": rule_11_51,
    "11.52": rule_11_52,
    "11.53": rule_11_53,
    "11.54": rule_11_54,
    "11.55": rule_11_55,
    "11.56": rule_11_56,
    "11.57": rule_11_57,
    "11.58": rule_11_58,
    "11.59": rule_11_59,
    "11.60": rule_11_60,
    "11.61": rule_11_61,
    "11.62": rule_11_62,
    "11.63": rule_11_63,
    "11.64": rule_11_64,
    "11.65": rule_11_65,
}

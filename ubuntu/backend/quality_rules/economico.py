from __future__ import annotations

from .base import DatasetReader, RuleIssue

COMPONENT_SLUG = "economico"

DEFAULT_RULE_IDS = frozenset({
    "4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "4.9", "4.10",
})


class EconomicoHelper:
    """Utilidades compartidas para reglas economicas."""
    IDENTIFIER_FIELDS = (
        "t_ili_tid",
        "T_Ili_Tid",
        "T_ILI_TID",
        "id_operacion",
        "t_id",
        "TID",
    )

    CARACTERISTICAS_UC_TABLES = (
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
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

    def iter_caracteristicas_unidad_construccion(self):
        yield from self._iter_table_rows(self.CARACTERISTICAS_UC_TABLES)

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


def _is_empty(value: object) -> bool:
    if value is None:
        return True

    text = str(value).strip()
    return text == "" or text.upper() in {"NULL", "<NULL>"} or text.lower() in {"none", "nan"}


def _is_not_empty(value: object) -> bool:
    return not _is_empty(value)


def _as_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalized_domain_text(value: object) -> str:
    return EconomicoHelper._normalize_key(_as_text(value))


def _normalizar_valor_dominio(value: object) -> str:
    if _is_empty(value):
        return ""

    text = _as_text(value)
    norm = _normalized_domain_text(text)

    generic = {
        "residencial": "Residencial",
        "comercial": "Comercial",
        "industrial": "Industrial",
        "institucional": "Institucional",
        "anexo": "Anexo",
        "conservacionproteccionambiental": "Conservacion_Proteccion_Ambiental",
        "sinbanio": "Sin_Banio",
        "sinbano": "Sin_Banio",
        "sincocina": "Sin_Cocina",
        "cancelacion": "Cancelacion",
        "cancelacionporenglobe": "Cancelacion_Por_Englobe",
        "cancelacionpordesenglobe": "Cancelacion_Por_Desenglobe",
    }

    return generic.get(norm, text)


def _unidad_construccion_tipo_ilicode(value: object) -> str:
    """Normaliza tipo_unidad_construccion igual que QGIS para 4.1 a 4.4."""
    if _is_empty(value):
        return ""

    text = _normalizar_valor_dominio(value)
    norm = _normalized_domain_text(text)

    mapping = {
        # iliCode / dispName
        "conservacionproteccionambiental": "Conservacion_Proteccion_Ambiental",
        "industrial": "Industrial",
        "institucional": "Institucional",
        "anexo": "Anexo",
        "residencial": "Residencial",
        "comercial": "Comercial",

        # itfCode del dominio ARB_UnidadConstruccionTipo
        "2": "Conservacion_Proteccion_Ambiental",
        "3": "Industrial",
        "4": "Institucional",
        "5": "Anexo",
        "0": "Residencial",
        "1": "Comercial",

        # t_id vistos en modelo 1.0
        "1058": "Conservacion_Proteccion_Ambiental",
        "1059": "Industrial",
        "1060": "Institucional",
        "1061": "Anexo",
        "1062": "Residencial",
        "1063": "Comercial",

        # compatibilidad con modelos anteriores usados en web/QGIS
        "1348": "Conservacion_Proteccion_Ambiental",
        "1349": "Industrial",
        "1350": "Institucional",
        "1351": "Anexo",
        "1352": "Residencial",
        "1353": "Comercial",
        "287": "Industrial",
        "288": "Institucional",
        "289": "Anexo",
        "290": "Residencial",
        "291": "Comercial",
    }

    return mapping.get(norm, text)


_TIPOLOGIAS_RESIDENCIALES_QGIS_ANTERIOR = {
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13",
}

_TIPOLOGIAS_COMERCIALES_QGIS_ANTERIOR = {
   "25", "26", "27", "28", "29", "30", "31", "32", 
}

_TIPOLOGIAS_INDUSTRIALES_QGIS_ANTERIOR = {
   "33", "34","35", "36", "37"
}

_TIPOLOGIAS_INSTITUCIONALES_QGIS_ANTERIOR = {
   "38", "39", "40", "41", "42", "43", "44", "45", "46", "47", "48", "49", "50", "51", 
}

_TIPOLOGIAS_CONSERVACION_QGIS_ANTERIOR = {
    "14", "15", "16", "17", "18", "19", 
}

def _tipologia_ilicode(value: object) -> str:
    """Normaliza tipo_tipologia / ct_tipo_tipologia para validar 4.1 a 4.4 sobre ILICODE."""
    if _is_empty(value):
        return ""

    text = _as_text(value)

    # Si el XTF ya trae iliCode completo, se conserva.
    if "." in text:
        return text

    norm = _normalized_domain_text(text)

    # Compatibilidad cuando el lector trae displayName simple.
    display_prefix = {
        "residencial": "Residencial.DisplayName",
        "comercial": "Comercial.DisplayName",
        "industrial": "Industrial.DisplayName",
        "institucional": "Institucional.DisplayName",
    }

    for prefix, fallback in display_prefix.items():
        if norm.startswith(prefix):
            return fallback

    # Compatibilidad con códigos numéricos del modelo QGIS anterior.
    if norm in _TIPOLOGIAS_RESIDENCIALES_QGIS_ANTERIOR:
        return text
    if norm in _TIPOLOGIAS_COMERCIALES_QGIS_ANTERIOR:
        return text
    if norm in _TIPOLOGIAS_INDUSTRIALES_QGIS_ANTERIOR:
        return text
    if norm in _TIPOLOGIAS_INSTITUCIONALES_QGIS_ANTERIOR:
        return text
    if norm in _TIPOLOGIAS_CONSERVACION_QGIS_ANTERIOR:
        return text

    return text


def _tipologia_residencial_valida(value: object) -> bool:
    if _is_empty(value):
        return True

    tipologia = _as_text(value)
    norm = _normalized_domain_text(value)

    excepciones = {
        "Conservacion.Residencial_Sencilla_Tipo_1_4014011",
        "Conservacion.Residencial_Sencilla_Tipo_2_4024022",
        "Conservacion.Residencial_Tipo_3_Restaurada_4024023",
        "ED.ED_Multifamiliar_VIP_5_Pisos_9016551",
        "ED.ED_Multifamiliar_Vivienda_VIS_Serie_2_Pisos_9011122",
        "ED.ED_Multifamiliar_VIS_Hasta_12_Pisos_9016194",
        "ED.ED_Multifamiliar_Medio_9026505",
    }

    return (
        tipologia.startswith("Residencial.")
        or tipologia in excepciones
        or norm in _TIPOLOGIAS_RESIDENCIALES_QGIS_ANTERIOR
    )


def _tipologia_comercial_excepcion(value: object) -> bool:
    if _is_empty(value):
        return False

    tipologia = _as_text(value)

    excepciones = {
        "Conservacion.Construccion_Tipo_4_Restaurada_4034024",
        "Conservacion.Construccion_Tipo_5_Restaurada_Con_Reforzamiento_4031035",
        "Conservacion.Construccion_Tipo_6_Restaurada_Con_Reforzamiento_4031036",
        "ED.ED_Servicios_Tipo_1_9026547",
    }

    return tipologia in excepciones


def _tipologia_comercial_valida(value: object) -> bool:
    if _is_empty(value):
        return True

    tipologia = _as_text(value)
    norm = _normalized_domain_text(value)

    return tipologia.startswith("Comercial.") or norm in _TIPOLOGIAS_COMERCIALES_QGIS_ANTERIOR


def _tipologia_industrial_valida(value: object) -> bool:
    if _is_empty(value):
        return True

    tipologia = _as_text(value)
    norm = _normalized_domain_text(value)

    return tipologia.startswith("Industrial.") or norm in _TIPOLOGIAS_INDUSTRIALES_QGIS_ANTERIOR


def _tipologia_institucional_valida(value: object) -> bool:
    if _is_empty(value):
        return True

    tipologia = _as_text(value)
    norm = _normalized_domain_text(value)

    return tipologia.startswith("Institucional.") or norm in _TIPOLOGIAS_INSTITUCIONALES_QGIS_ANTERIOR

def _tipologia_conservacion_valida(value: object) -> bool:
    """Valida tipologias de conservacion usando iliCode.

    En ARB_TipologiaTipo normalmente llegan como
    Conservacion.Residencial_Sencilla_Tipo_1_4014011, etc.
    Tambien acepta los codigos numericos antiguos definidos para QGIS.
    """
    if _is_empty(value):
        return True

    tipologia = _as_text(value)
    norm = _normalized_domain_text(value)

    return (
        tipologia.startswith("Conservacion.")
        or tipologia.startswith("Conservación.")
        or norm.startswith("conservacion")
        or norm in _TIPOLOGIAS_CONSERVACION_QGIS_ANTERIOR
    )


def _tipo_calificar_ilicode(value: object) -> str:
    if _is_empty(value):
        return ""

    text = _normalizar_valor_dominio(value)
    norm = _normalized_domain_text(text)

    mapping = {
        "industrial": "Industrial",
        "287": "Industrial",
        "residencial": "Residencial",
        "290": "Residencial",
        "comercial": "Comercial",
        "291": "Comercial",
        "institucional": "Institucional",
        "288": "Institucional",
        "0": "Residencial",
        "1": "Industrial",
        "2": "Comercial",
        "3": "Institucional",
    }

    return mapping.get(norm, text)


def _tamanio_banio_requiere_conservacion(value: object) -> bool:
    if value in (None, ""):
        return False

    text = str(value).strip()

    return text != "Sin_Banio"


def _tamanio_cocina_requiere_conservacion(value: object) -> bool:
    if value in (None, ""):
        return False

    text = str(value).strip()

    return text != "Sin_Cocina"

def _to_float(value: object) -> float | None:
    if value in (None, ""):
        return None

    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        return None
    
def _novedad_es_cancelacion(value: object) -> bool:
    if value in (None, ""):
        return False

    return str(value).strip().startswith("Cancelacion")
# -------------------- Reglas --------------------

def _rule_4_1(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_caracteristicas_unidad_construccion():

        tipo_unidad = helper.get_field_value(row, ("tipo_unidad_construccion",))
        tipo_tipologia = helper.get_field_value(row, ("tipo_tipologia", "ct_tipo_tipologia"))

        tipo_unidad_str = _unidad_construccion_tipo_ilicode(tipo_unidad)
        tipo_tipologia_ilicode = _tipologia_ilicode(tipo_tipologia)

        if (
            tipo_unidad_str == "Residencial"
            and _is_not_empty(tipo_tipologia_ilicode)
            and not _tipologia_residencial_valida(tipo_tipologia_ilicode)
        ):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="4.1",
                    message=(
                        "Cuando el tipo de unidad de construcción es Residencial, "
                        "solo se permiten tipologías residenciales."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_unidad_construccion": tipo_unidad,
                        "tipo_unidad_construccion_ilicode": tipo_unidad_str,
                        "tipo_tipologia": tipo_tipologia,
                        "tipo_tipologia_ilicode": tipo_tipologia_ilicode,
                    },
                )
            )

    return issues

def _rule_4_2(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_caracteristicas_unidad_construccion():
        tipo_unidad = helper.get_field_value(row, ("tipo_unidad_construccion",))
        tipo_unidad_str = _unidad_construccion_tipo_ilicode(tipo_unidad)

        tipo_tipologia = helper.get_field_value(row, ("tipo_tipologia", "ct_tipo_tipologia"))
        tipo_tipologia_ilicode = _tipologia_ilicode(tipo_tipologia)

        if not _is_not_empty(tipo_tipologia_ilicode):
            continue

        message = None

        if (
            tipo_unidad_str == "Comercial"
            and not _tipologia_comercial_valida(tipo_tipologia_ilicode)
        ):
            message = (
                "Cuando el tipo de unidad de construcción es Comercial, "
                "en caso de usos de calificación por tipologías, solamente "
                "se pueden asociar tipologías comerciales."
            )

        if message:
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="4.2",
                    message=message,
                    details={
                        "tabla": table_name,
                        "tipo_unidad_construccion": tipo_unidad,
                        "tipo_unidad_construccion_ilicode": tipo_unidad_str,
                        "tipo_tipologia": tipo_tipologia,
                        "tipo_tipologia_ilicode": tipo_tipologia_ilicode,
                    },
                )
            )

    return issues

def _rule_4_3(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_caracteristicas_unidad_construccion():
        tipo_unidad = helper.get_field_value(row, ("tipo_unidad_construccion",))
        tipo_unidad_str = _unidad_construccion_tipo_ilicode(tipo_unidad)

        tipo_tipologia = helper.get_field_value(row, ("tipo_tipologia", "ct_tipo_tipologia"))
        tipo_tipologia_ilicode = _tipologia_ilicode(tipo_tipologia)

        if (
            tipo_unidad_str == "Industrial"
            and _is_not_empty(tipo_tipologia_ilicode)
            and not _tipologia_industrial_valida(tipo_tipologia_ilicode)
        ):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="4.3",
                    message=(
                        "Cuando el tipo de unidad de construcción es Industrial, "
                        "en caso de usos de calificación por tipologías, solamente "
                        "se pueden asociar tipologías industriales."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_unidad_construccion": tipo_unidad,
                        "tipo_unidad_construccion_ilicode": tipo_unidad_str,
                        "tipo_tipologia": tipo_tipologia,
                        "tipo_tipologia_ilicode": tipo_tipologia_ilicode,
                    },
                )
            )

    return issues

def _rule_4_4(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_caracteristicas_unidad_construccion():
        tipo_unidad = helper.get_field_value(row, ("tipo_unidad_construccion",))
        tipo_unidad_str = _unidad_construccion_tipo_ilicode(tipo_unidad)

        tipo_tipologia = helper.get_field_value(row, ("tipo_tipologia", "ct_tipo_tipologia"))
        tipo_tipologia_ilicode = _tipologia_ilicode(tipo_tipologia)

        if (
            tipo_unidad_str == "Institucional"
            and _is_not_empty(tipo_tipologia_ilicode)
            and not _tipologia_institucional_valida(tipo_tipologia_ilicode)
        ):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="4.4",
                    message=(
                        "Cuando el tipo de unidad de construcción es Institucional, "
                        "en caso de usos de calificación por tipologías, solamente "
                        "se pueden asociar tipologías institucionales."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_unidad_construccion": tipo_unidad,
                        "tipo_unidad_construccion_ilicode": tipo_unidad_str,
                        "tipo_tipologia": tipo_tipologia,
                        "tipo_tipologia_ilicode": tipo_tipologia_ilicode,
                    },
                )
            )

    return issues

def _rule_4_10(dataset: DatasetReader) -> list[RuleIssue]:
    """Cuando la unidad es Conservacion_Proteccion_Ambiental, solo permite tipologias de Conservacion."""
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_caracteristicas_unidad_construccion():
        tipo_unidad = helper.get_field_value(row, ("tipo_unidad_construccion",))
        tipo_tipologia = helper.get_field_value(row, ("tipo_tipologia", "ct_tipo_tipologia"))

        tipo_unidad_str = _unidad_construccion_tipo_ilicode(tipo_unidad)
        tipo_tipologia_ilicode = _tipologia_ilicode(tipo_tipologia)

        if (
            tipo_unidad_str == "Conservacion_Proteccion_Ambiental"
            and _is_not_empty(tipo_tipologia_ilicode)
            and not _tipologia_conservacion_valida(tipo_tipologia_ilicode)
        ):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="4.10",
                    message=(
                        "Cuando el tipo de unidad de construcción es "
                        "Conservacion_Proteccion_Ambiental, solamente se pueden "
                        "asociar tipologías de Conservación."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_unidad_construccion": tipo_unidad,
                        "tipo_unidad_construccion_ilicode": tipo_unidad_str,
                        "tipo_tipologia": tipo_tipologia,
                        "tipo_tipologia_ilicode": tipo_tipologia_ilicode,
                    },
                )
            )

    return issues


def _rule_4_5(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    campos_banio = (
        "cc_tamanio_banio",
        "cc_enchape_banio",
        "cc_conservacion_banio",
        "cc_mobiliario_banio",
    )

    campos_cocina = (
        "cc_tamanio_cocina",
        "cc_enchape_cocina",
        "cc_conservacion_cocina",
        "cc_mobiliario_cocina",
    )

    tipos_validos = {"Residencial", "Comercial", "Industrial", "Institucional", "Anexo"}

    for table_name, row in helper.iter_caracteristicas_unidad_construccion():
        tipo_calificar = helper.get_field_value(
            row,
            ("cc_tipo_calificar", "tipo_calificar"),
        )
        tipo_calificar_str = _tipo_calificar_ilicode(tipo_calificar)

        # Igual que QGIS: si no existe/no resuelve cc_tipo_calificar,
        # usa tipo_unidad_construccion como respaldo.
        if tipo_calificar_str not in tipos_validos:
            tipo_unidad = helper.get_field_value(row, ("tipo_unidad_construccion",))
            tipo_calificar_str = _unidad_construccion_tipo_ilicode(tipo_unidad)

        if tipo_calificar_str != "Industrial":
            continue

        cerchas = helper.get_field_value(row, ("cc_cerchas_complemento_industria",))

        message = None
        details = {
            "tabla": table_name,
            "tipo_calificar": tipo_calificar,
            "tipo_calificar_ilicode": tipo_calificar_str,
            "cc_cerchas_complemento_industria": cerchas,
        }

        for campo in campos_banio:
            valor = helper.get_field_value(row, (campo,))
            if _is_not_empty(valor):
                message = (
                    "Cuando el tipo de calificación es Industrial, "
                    "los atributos relacionados con baño deben ser NULL."
                )
                details[campo] = valor
                break

        if message is None:
            for campo in campos_cocina:
                valor = helper.get_field_value(row, (campo,))
                if _is_not_empty(valor):
                    message = (
                        "Cuando el tipo de calificación es Industrial, "
                        "los atributos relacionados con cocina deben ser NULL."
                    )
                    details[campo] = valor
                    break

        if message is None and not _is_not_empty(cerchas):
            message = (
                "Cuando el tipo de calificación es Industrial, "
                "debe diligenciarse el atributo Cerchas_Complemento Industria."
            )

        if message:
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="4.5",
                    message=message,
                    details=details,
                )
            )

    return issues

def _rule_4_6(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_caracteristicas_unidad_construccion():
        tipo_calificar = helper.get_field_value(row, ("cc_tipo_calificar",))
        tipo_calificar_str = _tipo_calificar_ilicode(tipo_calificar)

        if tipo_calificar_str != "Residencial":
            continue

        tamanio_banio = helper.get_field_value(row, ("cc_tamanio_banio",))
        enchape_banio = helper.get_field_value(row, ("cc_enchape_banio",))
        mobiliario_banio = helper.get_field_value(row, ("cc_mobiliario_banio",))
        conservacion_banio = helper.get_field_value(row, ("cc_conservacion_banio",))

        tamanio_cocina = helper.get_field_value(row, ("cc_tamanio_cocina",))
        enchape_cocina = helper.get_field_value(row, ("cc_enchape_cocina",))
        mobiliario_cocina = helper.get_field_value(row, ("cc_mobiliario_cocina",))
        conservacion_cocina = helper.get_field_value(row, ("cc_conservacion_cocina",))

        requiere_conservacion_banio = (
            _tamanio_banio_requiere_conservacion(tamanio_banio)
            or _is_not_empty(enchape_banio)
            or _is_not_empty(mobiliario_banio)
        )

        requiere_conservacion_cocina = (
            _tamanio_cocina_requiere_conservacion(tamanio_cocina)
            or _is_not_empty(enchape_cocina)
            or _is_not_empty(mobiliario_cocina)
        )

        message = None

        if requiere_conservacion_banio and not _is_not_empty(conservacion_banio):
            message = (
                "Cuando el tipo de calificación es Residencial y existen atributos "
                "relacionados con baño, debe diligenciarse conservación de baño."
            )

        elif requiere_conservacion_cocina and not _is_not_empty(conservacion_cocina):
            message = (
                "Cuando el tipo de calificación es Residencial y existen atributos "
                "relacionados con cocina, debe diligenciarse conservación de cocina."
            )

        if message:
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="4.6",
                    message=message,
                    details={
                        "tabla": table_name,
                        "tipo_calificar": tipo_calificar,
                        "tipo_calificar_ilicode": tipo_calificar_str,
                        "cc_tamanio_banio": tamanio_banio,
                        "cc_enchape_banio": enchape_banio,
                        "cc_mobiliario_banio": mobiliario_banio,
                        "cc_conservacion_banio": conservacion_banio,
                        "cc_tamanio_cocina": tamanio_cocina,
                        "cc_enchape_cocina": enchape_cocina,
                        "cc_mobiliario_cocina": mobiliario_cocina,
                        "cc_conservacion_cocina": conservacion_cocina,
                    },
                )
            )

    return issues

def _rule_4_7(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    campos_banio_no_permitidos = (
        "cc_tamanio_banio",
        "cc_enchape_banio",
        "cc_conservacion_banio",
    )

    campos_cocina_no_permitidos = (
        "cc_tamanio_cocina",
        "cc_enchape_cocina",
        "cc_conservacion_cocina",
    )

    for table_name, row in helper.iter_caracteristicas_unidad_construccion():
        tipo_calificar = helper.get_field_value(row, ("cc_tipo_calificar",))
        tipo_calificar_str = _tipo_calificar_ilicode(tipo_calificar)

        if tipo_calificar_str != "Comercial":
            continue

        message = None
        details = {
            "tabla": table_name,
            "tipo_calificar": tipo_calificar,
            "tipo_calificar_ilicode": tipo_calificar_str,
            "cc_mobiliario_banio": helper.get_field_value(row, ("cc_mobiliario_banio",)),
            "cc_mobiliario_cocina": helper.get_field_value(row, ("cc_mobiliario_cocina",)),
        }

        for campo in campos_banio_no_permitidos:
            valor = helper.get_field_value(row, (campo,))
            if _is_not_empty(valor):
                message = (
                    "Cuando el tipo de calificación es Comercial, cualquier atributo "
                    "relacionado con baño diferente de mobiliario de baño debe ser NULL."
                )
                details[campo] = valor
                break

        if message is None:
            for campo in campos_cocina_no_permitidos:
                valor = helper.get_field_value(row, (campo,))
                if _is_not_empty(valor):
                    message = (
                        "Cuando el tipo de calificación es Comercial, cualquier atributo "
                        "relacionado con cocina diferente de mobiliario de cocina debe ser NULL."
                    )
                    details[campo] = valor
                    break

        if message:
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="4.7",
                    message=message,
                    details=details,
                )
            )

    return issues

def _rule_4_8(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_caracteristicas_unidad_construccion():
        total_raw = helper.get_field_value(row, ("cc_total_calificacion", "total_calificacion"))
        total = _to_float(total_raw)

        if total is not None and total > 100:
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="4.8",
                    message="El total de la calificación no puede ser mayor a 100.",
                    details={
                        "tabla": table_name,
                        "total_calificacion": total_raw,
                    },
                )
            )

    return issues

def _rule_4_9(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_cancelados: set[str] = set()

    for _, row in helper._iter_table_rows((
        "ARB_NovedadNumeroPredialValor",
        "arb_novedadnumeropredialvalor",
    )):
        predio_ref = helper.get_field_value(
            row,
            (
                "cca_predio_novedad_numero_predial",
                "predio",
            ),
        )
        tipo_novedad = helper.get_field_value(row, ("tipo_novedad",))

        if predio_ref and _novedad_es_cancelacion(tipo_novedad):
            predios_cancelados.add(str(predio_ref))

    for table_name, row in helper._iter_table_rows((
        "ARB_Predio",
        "arb_predio",
    )):
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        numero_predial = helper.get_field_value(row, ("numero_predial",))
        avaluo_catastral = helper.get_field_value(
            row,
            (
                "avaluo_catastral",
                "avaluo",
                "valor_avaluo",
            ),
        )

        if (
            predio_id
            and str(predio_id) not in predios_cancelados
            and not _is_not_empty(avaluo_catastral)
        ):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="4.9",
                    message=(
                        "En la base catastral final se debe registrar el avalúo "
                        "del predio, exceptuando los predios cancelados."
                    ),
                    details={
                        "tabla": table_name,
                        "predio_id": predio_id,
                        "numero_predial": numero_predial,
                        "avaluo_catastral": avaluo_catastral,
                    },
                )
            )

    return issues



RULE_FUNCTIONS = {
    "4.1": _rule_4_1,
    "4.2": _rule_4_2,
    "4.3": _rule_4_3,
    "4.4": _rule_4_4,
    "4.5": _rule_4_5,
    "4.6": _rule_4_6,
    "4.7": _rule_4_7,
    "4.8": _rule_4_8,
    "4.9": _rule_4_9,
    "4.10": _rule_4_10,
}

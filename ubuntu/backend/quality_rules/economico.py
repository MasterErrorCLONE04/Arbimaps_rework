from __future__ import annotations

import unicodedata

from .base import DatasetReader, RuleIssue

COMPONENT_SLUG = "economico"

DEFAULT_RULE_IDS = frozenset({
    "4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "4.9",
    "4.10", "4.11", "4.12", "4.13", "4.14", "4.15", "4.16", "4.17", "4.18",
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
        "id",
        "ID",
        "iliCode",
        "ilicode",
    )

    CARACTERISTICAS_UC_TABLES = (
        # En el XTF estos NO son tablas de dominio:
        # Tipo_Unidad_Construccion y CT_Tipo_Tipologia son campos dentro de
        # ARB_CaracteristicasUnidadConstruccion / ILC_CaracteristicasUnidadConstruccion.
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
        "ILC_CaracteristicasUnidadConstruccion",
        "ilc_caracteristicasunidadconstruccion",
    )

    UNIDAD_CONSTRUCCION_TABLES = (
        # La unidad se usa solo para heredar la referencia
        # caracteristicasunidadconstruccion -> caracteristicas.
        "ARB_UnidadConstruccion",
        "arb_unidadconstruccion",
        "ILC_UnidadConstruccion",
        "ilc_unidadconstruccion",
    )

    TIPOLOGIA_CONSTRUCCION_TABLES = (
        "CUC_TipologiaConstruccion",
        "cuc_tipologiaconstruccion",
        "CUC_TipologiaNoConvencional",
        "cuc_tipologianoconvencional",
        "CUC_CalificacionConvencional",
        "cuc_calificacionconvencional",
    )

    CALIFICACION_UC_ASSOC_TABLES = (
        "cuc_calificacion_unidadconstruccion",
        "CUC_Calificacion_UnidadConstruccion",
        "CUC_CalificacionUnidadConstruccion",
    )

    UNIDAD_TIPO_TABLES = (
        "ARB_UnidadConstruccionTipo",
        "arb_unidadconstrucciontipo",
        "CCA_UnidadConstruccionTipo",
        "cca_unidadconstrucciontipo",
        "CR_UnidadConstruccionTipo",
        "cr_unidadconstrucciontipo",
    )

    TIPOLOGIA_TIPO_TABLES = (
        "ARB_TipologiaTipo",
        "arb_tipologiatipo",
        "CUC_TipologiaTipo",
        "cuc_tipologiatipo",
    )

    CALIFICACION_TIPO_TABLES = (
        "ARB_CalificacionTipo",
        "arb_calificaciontipo",
        "CCA_CalificacionTipo",
        "cca_calificaciontipo",
        "ILC_CalificacionTipo",
        "ilc_calificaciontipo",
    )

    AVALUO_TABLES = (
        "ILC_EstructuraAvaluo",
        "ilc_estructuraavaluo",
        "ARB_AvaluoValor",
        "arb_avaluovalor",
        "CCA_AvaluoValor",
        "cca_avaluovalor",
    )

    TIPO_UNIDAD_FIELDS = (
        "tipo_unidad_construccion",
        "Tipo_Unidad_Construccion",
        "tipo_unidadconstruccion",
        "Tipo_UnidadConstruccion",
        "tipo_unidad",
        "Tipo_Unidad",
        "unidad_construccion_tipo",
        "UnidadConstruccionTipo",
        "arb_unidadconstrucciontipo",
        "ilc_unidadconstrucciontipo",
    )

    TIPO_TIPOLOGIA_FIELDS = (
        "tipo_tipologia",
        "Tipo_Tipologia",
        "ct_tipo_tipologia",
        "CT_Tipo_Tipologia",
        "tipologia",
        "Tipologia",
        "tipo_tipologia_construccion",
        "Tipo_Tipologia_Construccion",
        "cuc_tipologiaconstruccion",
        "cuc_tipologia_construccion",
        "cuc_calificacionconvencional",
        "cuc_calificacion_convencional",
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

    def iter_unidades_construccion(self):
        yield from self._iter_table_rows(self.UNIDAD_CONSTRUCCION_TABLES)

    def iter_avaluos(self):
        yield from self._iter_table_rows(self.AVALUO_TABLES)

    def iter_caracteristicas_tipologia(self):
        """
        Devuelve las parejas tipo_unidad/tipologia que deben validar 4.1-4.4 y 4.10.

        Estructura real del XTF:
        - ARB_CaracteristicasUnidadConstruccion trae los campos:
          Tipo_Unidad_Construccion y CT_Tipo_Tipologia.
        - ARB_UnidadConstruccion solo trae una referencia:
          caracteristicasunidadconstruccion = TID de la característica.

        Por eso se validan SIEMPRE las características, y opcionalmente se agrega
        el TID de la unidad que las referencia para que el reporte sea más claro.
        """
        unidad_by_caracteristica: dict[str, list[tuple[str, dict[str, object]]]] = {}

        for unidad_table, unidad_row in self.iter_unidades_construccion():
            caracteristica_ref = self.get_field_value(
                unidad_row,
                (
                    "caracteristicasunidadconstruccion",
                    "caracteristicas_unidad_construccion",
                    "arb_caracteristicasunidadconstruccion",
                    "arb_caracteristicas_unidad_construccion",
                    "ilc_caracteristicasunidadconstruccion",
                    "ilc_caracteristicas_unidad_construccion",
                ),
            )
            if caracteristica_ref:
                unidad_by_caracteristica.setdefault(str(caracteristica_ref), []).append((unidad_table, unidad_row))

        for table_name, row in self.iter_caracteristicas_unidad_construccion():
            tipo_unidad = self.get_field_value(row, self.TIPO_UNIDAD_FIELDS)
            tipo_tipologia = self.get_field_value(row, self.TIPO_TIPOLOGIA_FIELDS)

            # Resolver REF numérico o TID si llega así, pero sin depender de tablas externas.
            tipo_unidad_resuelta = self._resolve_domain_value(
                tipo_unidad,
                self._domain_values_by_ref(self.UNIDAD_TIPO_TABLES),
                {},
            )
            tipo_tipologia_resuelta = self._resolve_domain_value(
                tipo_tipologia,
                {
                    **self._domain_values_by_ref(self.TIPOLOGIA_TIPO_TABLES),
                    **self._tipologias_by_ref(),
                },
                {},
            )

            details: dict[str, object] = {
                "caracteristica_tid": self.identify(row),
            }

            if tipo_unidad_resuelta != tipo_unidad:
                details["tipo_unidad_construccion_original"] = tipo_unidad
            if tipo_tipologia_resuelta != tipo_tipologia:
                details["tipo_tipologia_original"] = tipo_tipologia

            unidades = []
            for identifier in self.row_identifiers(row):
                unidades.extend(unidad_by_caracteristica.get(str(identifier), []))

            if not unidades:
                yield table_name, row, tipo_unidad_resuelta, tipo_tipologia_resuelta, details
                continue

            # Una característica puede estar asociada a una o varias unidades.
            # Se reporta contra la característica, pero se muestra la unidad que la usa.
            for unidad_table, unidad_row in unidades:
                unit_details = dict(details)
                unit_details["unidad_tabla"] = unidad_table
                unit_details["unidad_ref"] = self.identify(unidad_row)
                yield table_name, row, tipo_unidad_resuelta, tipo_tipologia_resuelta, unit_details

    def _tipologia_row_value(self, row: dict[str, object]) -> str | None:
        return self.get_field_value(
            row,
            (
                "ilicode", "iliCode", "IliCode", "ILICODE",
                "tipo_tipologia", "Tipo_Tipologia", "ct_tipo_tipologia", "CT_Tipo_Tipologia",
                "tipologia", "Tipologia", "dispname", "DispName", "nombre", "Nombre",
                "description", "Description",
            ),
        ) or self.identify(row)

    def _domain_row_value(self, row: dict[str, object]) -> str | None:
        # IMPORTANTE:
        # Para dominios solo usamos ILICODE. No usamos dispname, itfcode,
        # seq ni description porque esos valores pueden producir falsos positivos
        # cuando cambian entre proyectos/modelos.
        return self.get_field_value(
            row,
            ("ilicode", "iliCode", "IliCode", "ILICODE"),
        )


    def _domain_identifiers(self, row: dict[str, object]) -> list[str]:
        # Solo se indexa por identificadores reales del registro:
        # TID/t_id/id/t_ili_tid. No se indexa por itfcode ni seq.
        return self.row_identifiers(row)


    def _domain_values_by_ref(self, table_names: tuple[str, ...]) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for _, row in self._iter_table_rows(table_names):
            value = self._domain_row_value(row)
            if not value:
                continue
            for identifier in self._domain_identifiers(row):
                lookup[str(identifier)] = value
        return lookup

    def _resolve_domain_value(
        self,
        value: object,
        lookup: dict[str, str],
        fallback: dict[str, str],
    ) -> str | None:
        if _is_empty(value):
            return None
        text = str(value).strip()
        return lookup.get(text) or fallback.get(self._normalize_key(text)) or text

    def resolve_tipo_calificacion(self, value: object) -> str | None:
        """Resuelve Tipo_Calificacion contra ARB_CalificacionTipo por ilicode."""
        return self._resolve_domain_value(
            value,
            self._domain_values_by_ref(self.CALIFICACION_TIPO_TABLES),
            {},
        )

    def _tipologias_by_ref(self) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for _, row in self._iter_table_rows(self.TIPOLOGIA_CONSTRUCCION_TABLES):
            value = self._tipologia_row_value(row)
            if not value:
                continue
            for identifier in self.row_identifiers(row):
                lookup[str(identifier)] = value
        return lookup

    def _resolve_tipologia_value(self, value: object, tipologias_by_ref: dict[str, str]) -> str | None:
        if _is_empty(value):
            return None
        text = str(value).strip()
        return tipologias_by_ref.get(text, text)

    def row_identifiers(self, row: dict[str, object]) -> list[str]:
        identifier_fields = {
            self._normalize_key(field)
            for field in (*self.IDENTIFIER_FIELDS, "T_ID", "T_Id", "tid", "id")
        }
        identifiers: list[str] = []

        for key, value in row.items():
            if self._normalize_key(str(key)) not in identifier_fields:
                continue
            if value in (None, ""):
                continue
            identifier = str(value).strip()
            if identifier and identifier not in identifiers:
                identifiers.append(identifier)

        return identifiers

    def _tipologias_by_caracteristica_ref(self) -> dict[str, list[tuple[str, dict[str, object]]]]:
        tipologias_by_id: dict[str, tuple[str, dict[str, object]]] = {}
        for table_name, row in self._iter_table_rows(self.TIPOLOGIA_CONSTRUCCION_TABLES):
            for identifier in self.row_identifiers(row):
                tipologias_by_id[str(identifier)] = (table_name, row)

        lookup: dict[str, list[tuple[str, dict[str, object]]]] = {}
        for _, row in self._iter_table_rows(self.CALIFICACION_UC_ASSOC_TABLES):
            caracteristica_ref = self.get_field_value(
                row,
                (
                    "ilc_caracteristicasunidadconstruccion",
                    "ilc_caracteristicas_unidad_construccion",
                    "arb_caracteristicasunidadconstruccion",
                    "arb_caracteristicas_unidad_construccion",
                    "caracteristicasunidadconstruccion",
                    "caracteristicas_unidad_construccion",
                    "unidadconstruccion",
                    "unidad_construccion",
                ),
            )
            calificacion_ref = self.get_field_value(
                row,
                (
                    "cuc_calificacionunidadconstruccion",
                    "cuc_calificacion_unidad_construccion",
                    "cuc_tipologiaconstruccion",
                    "cuc_tipologia_construccion",
                    "calificacionunidadconstruccion",
                    "calificacion_unidad_construccion",
                    "tipologiaconstruccion",
                    "tipologia_construccion",
                    "tipologia",
                ),
            )

            if not caracteristica_ref or not calificacion_ref:
                continue

            tipologia = tipologias_by_id.get(str(calificacion_ref))
            if tipologia:
                lookup.setdefault(str(caracteristica_ref), []).append(tipologia)

        return lookup

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
        replacements = {
            "\u00c3\u00a1": "a",
            "\u00c3\u00a9": "e",
            "\u00c3\u00ad": "i",
            "\u00c3\u00b3": "o",
            "\u00c3\u00ba": "u",
            "\u00c3\u00b1": "n",
            "\u00c3\u0192\u00c2\u00a1": "a",
            "\u00c3\u0192\u00c2\u00a9": "e",
            "\u00c3\u0192\u00c2\u00ad": "i",
            "\u00c3\u0192\u00c2\u00b3": "o",
            "\u00c3\u0192\u00c2\u00ba": "u",
            "\u00c3\u0192\u00c2\u00b1": "n",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
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


_TIPO_UNIDAD_RELACION_BY_REF = {
    "158": "Conservacion_Proteccion_Ambiental",
    "159": "Industrial",
    "160": "Institucional",
    "161": "Anexo",
    "162": "Residencial",
    "163": "Comercial",
}

_TIPOLOGIA_RELACION_BY_REF = {
    "1500": "Conservacion.Residencial_Sencilla_Tipo_2_4024022",
    "1501": "Residencial.Tipo_2_1004122",
    "1502": "Comercial.Basico_2_2014111",
    "1503": "Comercial.Intermedio_2_2021532",
    "1504": "Industrial.Liviana_2_3001121",
    "1505": "Institucional.Institucional_Tipo_3_5021143",
    "1506": "Industrial.Liviana_1_3002311",
    "1507": "Residencial.Tipo_5_1021125",
    "1508": "Conservacion.Construccion_Tipo_5_Restaurada_Con_Reforzamiento_4031035",
    "1509": "Institucional.Religioso_Tipo_1_6021131",
    "1510": "ED.ED_Multifamiliar_VIP_5_Pisos_9016551",
    "1511": "Comercial.Especializado_3_2033133",
    "1512": "Comercial.Especializado_2_2036543",
    "1513": "Institucional.Salud_1_7011121",
    "1514": "ED.ED_Servicios_Tipo_1_9026547",
    "1515": "Industrial.Pesada_1_3023132",
    "1516": "Comercial.Intermedio_3_2026532",
    "1517": "Institucional.Salud_2_7021132",
    "1518": "Residencial.Tipo_1_1014011",
    "1519": "Conservacion.Construccion_Tipo_6_Restaurada_Con_Reforzamiento_4031036",
    "1520": "ED.ED_Multifamiliar_Medio_9026505",
    "1521": "Industrial.Mediana_1_3011132",
    "1522": "Institucional.Institucional_Tipo_4_5036144",
    "1523": "ED.ED_Multifamiliar_VIS_Hasta_12_Pisos_9016194",
    "1524": "Comercial.Especializado_4_2036533",
    "1525": "Residencial.Tipo_3_mas_1011133",
    "1526": "Comercial.Intermedio_1_2021132",
    "1527": "Residencial.Prefabricado_2_1005530",
    "1528": "Institucional.Salud_Plus_7036584",
    "1529": "Institucional.Institucional_Tipo_5_Prefabricado_5015510",
    "1530": "Institucional.Religioso_Tipo_2_6031132",
    "1531": "Residencial.Tipo_3_menos_1004113",
    "1532": "ED.ED_Multifamiliar_Vivienda_VIS_Serie_2_Pisos_9011122",
    "1533": "Residencial.Tipo_6_mas_1031146",
    "1534": "Institucional.Institucional_Tipo_1_5014111",
    "1535": "Conservacion.Residencial_Sencilla_Tipo_1_4014011",
    "1536": "Comercial.Especializado_1_2023123",
    "1537": "Institucional.Institucional_Tipo_6_5011111",
    "1538": "Institucional.Salud_3_7031173",
    "1539": "Residencial.Tipo_4_1021134",
    "1540": "Institucional.Institucional_Tipo_8_5036553",
    "1541": "Residencial.Tipo_5_mas_1031135",
    "1542": "Residencial.Tipo_4_menos_1024114",
    "1543": "Conservacion.Residencial_Tipo_3_Restaurada_4024023",
    "1544": "Institucional.Institucional_Tipo_7_5021132",
    "1545": "Conservacion.Construccion_Tipo_4_Restaurada_4034024",
    "1546": "Residencial.Prefabricado_1_1005510",
    "1547": "Residencial.Tipo_0_1002311",
    "1548": "Residencial.Tipo_6_1031126",
    "1549": "Institucional.Institucional_Tipo_2_5011122",
    "1550": "Industrial.Pesada_2_3033443",
    "1551": "Residencial.Tipo_5_menos_1011115",
}


def _unidad_construccion_tipo_ilicode(value: object, *, table_name: str | None = None) -> str:
    """Normaliza tipo_unidad_construccion para reglas 4.1 a 4.4."""
    if _is_empty(value):
        return ""

    text = _normalizar_valor_dominio(value)
    norm = _normalized_domain_text(text)
    table_norm = _normalized_domain_text(table_name)

    named_mapping = (
        ("conservacionproteccionambiental", "Conservacion_Proteccion_Ambiental"),
        ("residencial", "Residencial"),
        ("comercial", "Comercial"),
        ("industrial", "Industrial"),
        ("institucional", "Institucional"),
        ("anexo", "Anexo"),
    )

    for key, canonical in named_mapping:
        if norm == key or norm.endswith(key):
            return canonical

    if "ilc" in table_norm:
        ilc_numeric = {
            "0": "Residencial",
            "1": "Comercial",
            "2": "Industrial",
            "3": "Institucional",
            "4": "Anexo",
        }
        if norm in ilc_numeric:
            return ilc_numeric[norm]

    mapping = {
        "2": "Conservacion_Proteccion_Ambiental",
        "3": "Industrial",
        "4": "Institucional",
        "5": "Anexo",
        "0": "Residencial",
        "1": "Comercial",
        "1058": "Conservacion_Proteccion_Ambiental",
        "1059": "Industrial",
        "1060": "Institucional",
        "1061": "Anexo",
        "1062": "Residencial",
        "1063": "Comercial",
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

def _tipo_calificacion_ilicode(value: object) -> str:
    """
    Normaliza Tipo_Calificacion usando ILICODE.
    No depende de t_id, itfcode ni seq.
    """
    if _is_empty(value):
        return ""

    text = _normalizar_valor_dominio(value)
    norm = _normalized_domain_text(text)

    named_mapping = (
        ("tipologia", "Tipologia"),
        ("noconvencional", "No_Convencional"),
        ("convencional", "Convencional"),
    )

    for key, canonical in named_mapping:
        if norm == key or norm.endswith(key):
            return canonical

    return text

def _tipologia_segments(value: object) -> list[str]:
    text = _as_text(value)
    if not text:
        return []

    text = text.replace("::", ".").replace("/", ".")
    return [_normalized_domain_text(segment) for segment in text.split(".") if segment.strip()]


def _tipologia_categoria(value: object) -> str | None:
    exact_categories = {
        "residencial": "Residencial",
        "comercial": "Comercial",
        "industrial": "Industrial",
        "institucional": "Institucional",
        "conservacion": "Conservacion",
        "ed": "ED",
        "ph": "ED",
    }
    segments = _tipologia_segments(value)

    for segment in segments:
        if segment in exact_categories:
            return exact_categories[segment]

    for segment in segments:
        for key, canonical in exact_categories.items():
            if key in {"ed", "ph"}:
                continue
            if segment.endswith(key) or segment.startswith(key):
                return canonical

    norm = _normalized_domain_text(value)
    for key, canonical in exact_categories.items():
        if norm.startswith(key) or key in norm:
            return canonical

    return None


def _tipologia_es_excepcion(value: object, excepciones: set[str]) -> bool:
    norm = _normalized_domain_text(value)
    if not norm:
        return False

    for excepcion in excepciones:
        excepcion_norm = _normalized_domain_text(excepcion)
        excepcion_tail = _normalized_domain_text(excepcion.split(".", 1)[-1])
        if excepcion_norm in norm or excepcion_tail in norm:
            return True

    return False


_RESIDENCIAL_TIPOLOGIA_EXCEPCIONES = {
    "Conservacion.Residencial_Sencilla_Tipo_1_4014011",
    "Conservacion.Residencial_Sencilla_Tipo_2_4024022",
    "Conservacion.Residencial_Tipo_3_Restaurada_4024023",
    "ED.ED_Multifamiliar_VIP_5_Pisos_9016551",
    "ED.ED_Multifamiliar_Vivienda_VIS_Serie_2_Pisos_9011122",
    "ED.ED_Multifamiliar_VIS_Hasta_12_Pisos_9016194",
    "ED.ED_Multifamiliar_Medio_9026505",
}

_COMERCIAL_TIPOLOGIA_EXCEPCIONES = {
    "Conservacion.Construccion_Tipo_4_Restaurada_4034024",
    "Conservacion.Construccion_Tipo_5_Restaurada_Con_Reforzamiento_4031035",
    "Conservacion.Construccion_Tipo_6_Restaurada_Con_Reforzamiento_4031036",
    "ED.ED_Servicios_Tipo_1_9026547",
}


def _tipologia_residencial_excepcion(value: object) -> bool:
    return _tipologia_es_excepcion(value, _RESIDENCIAL_TIPOLOGIA_EXCEPCIONES)


def _tipologia_residencial_valida(value: object) -> bool:
    if _is_empty(value):
        return True

    norm = _normalized_domain_text(value)
    return (
        _tipologia_categoria(value) == "Residencial"
        or _tipologia_residencial_excepcion(value)
        or norm in _TIPOLOGIAS_RESIDENCIALES_QGIS_ANTERIOR
    )


def _tipologia_comercial_excepcion(value: object) -> bool:
    return _tipologia_es_excepcion(value, _COMERCIAL_TIPOLOGIA_EXCEPCIONES)


def _tipologia_comercial_valida(value: object) -> bool:
    if _is_empty(value):
        return True

    norm = _normalized_domain_text(value)
    return (
        _tipologia_categoria(value) == "Comercial"
        or _tipologia_comercial_excepcion(value)
        or norm in _TIPOLOGIAS_COMERCIALES_QGIS_ANTERIOR
    )


def _tipologia_industrial_valida(value: object) -> bool:
    if _is_empty(value):
        return True

    norm = _normalized_domain_text(value)
    return _tipologia_categoria(value) == "Industrial" or norm in _TIPOLOGIAS_INDUSTRIALES_QGIS_ANTERIOR


def _tipologia_institucional_valida(value: object) -> bool:
    if _is_empty(value):
        return True

    norm = _normalized_domain_text(value)
    return _tipologia_categoria(value) == "Institucional" or norm in _TIPOLOGIAS_INSTITUCIONALES_QGIS_ANTERIOR


def _tipologia_conservacion_valida(value: object) -> bool:
    if _is_empty(value):
        return True

    norm = _normalized_domain_text(value)
    return _tipologia_categoria(value) == "Conservacion" or norm in _TIPOLOGIAS_CONSERVACION_QGIS_ANTERIOR


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

    text = str(value).strip().replace(" ", "")
    if not text:
        return None

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return None


def _novedad_es_cancelacion(value: object) -> bool:
    if _is_empty(value):
        return False
    norm = _normalized_domain_text(value)
    return "cancelacion" in norm or "cancelacion" in norm
# Puntajes de calificacion convencional. Se mantienen alineados con el
# calculador de calificacion de edificaciones usado por el proyecto.
def _score_norm(value: object) -> str:
    return _normalized_domain_text(value)


def _score_conservacion(value: object) -> tuple[int, bool]:
    if _is_empty(value): return 0, True
    v = _score_norm(value)
    for key, pts in (("malo", 0), ("regular", 2), ("bueno", 4), ("excelente", 5)):
        if key in v: return pts, True
    return 0, False


def _score_armazon(value: object, industrial_comercial: bool) -> tuple[int, bool]:
    if _is_empty(value): return 0, True
    v = _score_norm(value)
    if "concretocuatro" in v or "concreto4" in v: return (22 if industrial_comercial else 6), True
    if "concretohastatres" in v or "concretohasta3" in v: return (22 if industrial_comercial else 4), True
    if "ladrillo" in v or "bloque" in v: return (12 if industrial_comercial else 2), True
    if "prefabricado" in v: return (8 if industrial_comercial else 1), True
    if "madera" in v: return (4 if industrial_comercial else 0), True
    return 0, False


def _score_muros(value: object) -> tuple[int, bool]:
    if _is_empty(value): return 0, True
    v = _score_norm(value)
    if "materialesdedesecho" in v or "esterilla" in v: return 0, True
    if any(x in v for x in ("bahareque", "adobe", "tapia")): return 1, True
    if "concretoprefabricado" in v: return 3, True
    if "madera" in v: return 2, True
    if "bloque" in v or "ladrillo" in v: return 4, True
    return 0, False


def _score_cubierta(value: object) -> tuple[int, bool]:
    if _is_empty(value): return 0, True
    v = _score_norm(value)
    if "placaimpermeabilizada" in v or "cubiertalujosa" in v or "ornamental" in v: return 16, True
    if "azotea" in v or "aluminio" in v or "placasencilla" in v: return 13, True
    if "cubiertasencilla" in v and ("eternit" in v or "tejadebarro" in v): return 9, True
    if "entrepiso" in v or ("provisional" in v and "prefabricado" in v): return 6, True
    if "zinc" in v or "eternitrustico" in v or "tejadebarro" in v: return 3, True
    if "materialesdedesecho" in v or "telasasfalticas" in v: return 1, True
    return 0, False


def _score_fachada(value: object, industrial_comercial: bool) -> tuple[int, bool]:
    if _is_empty(value): return 0, True
    v = _score_norm(value).replace("fachada", "")
    tabla = ({"pobre": 2, "sencilla": 4, "regular": 6, "buena": 8, "lujosa": 12}
             if industrial_comercial else
             {"pobre": 0, "sencilla": 2, "regular": 4, "buena": 6, "lujosa": 8})
    for key, pts in tabla.items():
        if key in v: return pts, True
    return 0, False


def _score_cubrimiento(value: object, industrial_comercial: bool) -> tuple[int, bool]:
    if _is_empty(value): return 0, True
    v = _score_norm(value)
    if "sincubrimiento" in v: return 0, True
    if "marmol" in v or "lujoso" in v or "otros" in v: return (7 if industrial_comercial else 4), True
    if "madera" in v or "piedraornamental" in v: return (5 if industrial_comercial else 3), True
    if "estuco" in v or "ceramica" in v or "papelfino" in v: return (3 if industrial_comercial else 2), True
    if "panete" in v or "paniete" in v or "papelcomun" in v or "ladrilloprensado" in v: return (2 if industrial_comercial else 1), True
    return 0, False


def _score_piso(value: object, industrial_comercial: bool) -> tuple[int, bool]:
    if _is_empty(value): return 0, True
    v = _score_norm(value)
    if "granopequeno" in v: return (11 if industrial_comercial else 8), True
    if "retaldemarmol" in v or "otroslujosos" in v or ("marmol" in v and "granopequeno" not in v): return (13 if industrial_comercial else 9), True
    if "parquet" in v or "paquet" in v or "alfombra" in v or "maderafina" in v: return (11 if industrial_comercial else 8), True
    if any(x in v for x in ("tableta", "caucho", "cuacho", "acrilico", "granito", "baldosafina")): return (9 if industrial_comercial else 6), True
    if "listonmachihembrado" in v: return (7 if industrial_comercial else 4), True
    if "baldosacomun" in v or "tablon" in v or "ladrillo" in v: return (5 if industrial_comercial else 3), True
    if "cemento" in v or "maderaburda" in v: return (3 if industrial_comercial else 2), True
    if "tierrapisada" in v: return 0, True
    return 0, False


def _score_tamanio(value: object, objeto: str, comercial: bool) -> tuple[int, bool]:
    if _is_empty(value): return 0, True
    if comercial: return 0, True
    v = _score_norm(value)
    if (objeto == "banio" and ("sinbanio" in v or "sinbano" in v)) or (objeto == "cocina" and "sincocina" in v): return 0, True
    if "pequen" in v: return 1, True
    if "median" in v: return 2, True
    if "grande" in v: return 3, True
    return 0, False


def _score_enchape(value: object, comercial: bool) -> tuple[int, bool]:
    if _is_empty(value): return 0, True
    if comercial: return 0, True
    v = _score_norm(value)
    if "sincubrimiento" in v: return 0, True
    if "marmol" in v or "enchapelujoso" in v: return 5, True
    if "ceramica" in v or "cristanac" in v or "granito" in v: return 4, True
    if "decorado" in v or "papelfino" in v: return 3, True
    if "unicolor" in v or "papelcomun" in v: return 2, True
    if "panete" in v or "paniete" in v or "baldosa" in v or "cemento" in v: return 1, True
    return 0, False


def _score_mobiliario_banio(value: object, comercial: bool) -> tuple[int, bool]:
    if _is_empty(value): return 0, True
    v = _score_norm(value)
    tabla = (("lujoso", 16), ("bueno", 9), ("regular", 6), ("sencillo", 3), ("pobre", 0)) if comercial else (("lujoso", 11), ("bueno", 9), ("regular", 6), ("sencillo", 3), ("pobre", 0))
    for key, pts in tabla:
        if key in v: return pts, True
    return 0, False


def _score_mobiliario_cocina(value: object, comercial: bool) -> tuple[int, bool]:
    if _is_empty(value): return 0, True
    v = _score_norm(value)
    tabla = (("lujoso", 13), ("bueno", 9), ("regular", 6), ("sencillo", 3), ("pobre", 0)) if comercial else (("lujoso", 6), ("bueno", 4), ("regular", 3), ("sencillo", 2), ("pobre", 0))
    for key, pts in tabla:
        if key in v: return pts, True
    return 0, False


def _score_cercha(value: object) -> tuple[int, bool]:
    if _is_empty(value): return 0, True
    v = _score_norm(value)
    if "metalicapesada" in v: return 34, True
    if "metalicamediana" in v: return 22, True
    if "metalicaliviana" in v: return 12, True
    if "madera" in v: return 6, True
    return 0, False


def _score_altura(value: object) -> tuple[int, bool]:
    if _is_empty(value): return 0, True
    if isinstance(value, bool): return (6 if value else 0), True
    v = _score_norm(value)
    if v in {"1", "true", "si", "yes", "checked"} or "superiora6" in v: return 6, True
    if v in {"0", "false", "no", "unchecked"}: return 0, True
    return 0, False


def _calcular_total_convencional(helper: EconomicoHelper, row: dict[str, object], tipo: str) -> tuple[int | None, list[str]]:
    tipo_norm = _normalized_domain_text(tipo)
    industrial = tipo_norm == "industrial"
    comercial = tipo_norm == "comercial"
    residencial = tipo_norm == "residencial"
    if not (industrial or comercial or residencial):
        return None, ["cc_tipo_calificar"]
    ic = industrial or comercial
    total = 0
    desconocidos: list[str] = []

    def add(campo: str, scorer, *args):
        nonlocal total
        valor = helper.get_field_value(row, (campo,))
        puntos, conocido = scorer(valor, *args)
        total += puntos
        if not conocido and _is_not_empty(valor): desconocidos.append(campo)

    add("cc_armazon", _score_armazon, ic)
    add("cc_muros", _score_muros)
    add("cc_cubierta", _score_cubierta)
    add("cc_conservacion_estructura", _score_conservacion)
    add("cc_fachada", _score_fachada, ic)
    add("cc_cubrimiento_muros", _score_cubrimiento, ic)
    add("cc_piso", _score_piso, ic)
    add("cc_conservacion_acabados", _score_conservacion)
    if industrial:
        add("cc_cerchas_complemento_industria", _score_cercha)
        add("cc_altura_cerchas_superior_6m", _score_altura)
    else:
        add("cc_tamanio_banio", _score_tamanio, "banio", comercial)
        add("cc_enchape_banio", _score_enchape, comercial)
        add("cc_mobiliario_banio", _score_mobiliario_banio, comercial)
        add("cc_conservacion_banio", _score_conservacion)
        add("cc_tamanio_cocina", _score_tamanio, "cocina", comercial)
        add("cc_enchape_cocina", _score_enchape, comercial)
        add("cc_mobiliario_cocina", _score_mobiliario_cocina, comercial)
        add("cc_conservacion_cocina", _score_conservacion)
    return total, desconocidos


TIPO_CALIFICACION_FIELDS = (
    "tipo_calificacion",
    "Tipo_Calificacion",
    "ct_tipo_calificacion",
    "CT_Tipo_Calificacion",
    "calificacion_tipo",
    "Calificacion_Tipo",
    "arb_calificaciontipo",
    "ARB_CalificacionTipo",
    "calificaciontipo",
    "CalificacionTipo",
)

CNC_TIPO_ANEXO_FIELDS = (
    "cnc_tipo_anexo",
    "CNC_Tipo_Anexo",
    "tipo_anexo",
    "Tipo_Anexo",
)

CNC_CONSERVACION_ANEXO_FIELDS = (
    "cnc_conservacion_anexo",
    "CNC_Conservacion_Anexo",
    "conservacion_anexo",
    "Conservacion_Anexo",
)


def _get_tipo_calificacion_resuelto(
    helper: EconomicoHelper,
    row: dict[str, object],
) -> tuple[str | None, str | None, str]:
    raw = helper.get_field_value(row, TIPO_CALIFICACION_FIELDS)
    resuelto = helper.resolve_tipo_calificacion(raw)
    ilicode = _tipo_calificacion_ilicode(resuelto)
    return raw, resuelto, ilicode


def _get_tipo_unidad_resuelto(
    helper: EconomicoHelper,
    row: dict[str, object],
    table_name: str,
) -> tuple[str | None, str | None, str]:
    raw = helper.get_field_value(row, helper.TIPO_UNIDAD_FIELDS)
    resuelto = helper._resolve_domain_value(
        raw,
        helper._domain_values_by_ref(helper.UNIDAD_TIPO_TABLES),
        {},
    )
    ilicode = _unidad_construccion_tipo_ilicode(resuelto, table_name=table_name)
    return raw, resuelto, ilicode

# -------------------- Reglas --------------------

def _rule_4_1(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row, tipo_unidad, tipo_tipologia, relation_details in helper.iter_caracteristicas_tipologia():
        _raw_metodo, _resolved_metodo, metodo = _get_tipo_calificacion_resuelto(helper, row)
        if metodo and metodo != "Tipologia":
            continue
        tipo_unidad_str = _unidad_construccion_tipo_ilicode(tipo_unidad, table_name=table_name)
        tipo_tipologia_ilicode = _tipologia_ilicode(tipo_tipologia)
        if not _is_not_empty(tipo_tipologia_ilicode):
            continue

        message = None
        if tipo_unidad_str == "Residencial" and not _tipologia_residencial_valida(tipo_tipologia_ilicode):
            message = "Cuando el tipo de unidad de construccion es Residencial, solo se permiten tipologias residenciales."
        elif tipo_unidad_str != "Residencial" and _tipologia_residencial_excepcion(tipo_tipologia_ilicode):
            message = "Cuando la tipologia corresponde a una excepcion residencial de Conservacion o ED, el tipo de unidad de construccion debe ser Residencial."

        if message:
            issues.append(helper.make_issue(row, rule_id="4.1", message=message, details={
                "tabla": table_name, "tipo_unidad_construccion": tipo_unidad,
                "tipo_unidad_construccion_ilicode": tipo_unidad_str,
                "tipo_tipologia": tipo_tipologia, "tipo_tipologia_ilicode": tipo_tipologia_ilicode,
                **relation_details,
            }))
    return issues

def _rule_4_2(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row, tipo_unidad, tipo_tipologia, relation_details in helper.iter_caracteristicas_tipologia():
        _raw_metodo, _resolved_metodo, metodo = _get_tipo_calificacion_resuelto(helper, row)
        if metodo and metodo != "Tipologia":
            continue
        tipo_unidad_str = _unidad_construccion_tipo_ilicode(tipo_unidad, table_name=table_name)
        tipo_tipologia_ilicode = _tipologia_ilicode(tipo_tipologia)
        if not _is_not_empty(tipo_tipologia_ilicode):
            continue

        message = None
        if tipo_unidad_str == "Comercial" and not _tipologia_comercial_valida(tipo_tipologia_ilicode):
            message = "Cuando el tipo de unidad de construccion es Comercial, solo se permiten tipologias comerciales y sus excepciones definidas."
        elif tipo_unidad_str != "Comercial" and _tipologia_comercial_excepcion(tipo_tipologia_ilicode):
            message = "Cuando la tipologia corresponde a una excepcion comercial de Conservacion o ED, el tipo de unidad de construccion debe ser Comercial."

        if message:
            issues.append(helper.make_issue(row, rule_id="4.2", message=message, details={
                "tabla": table_name, "tipo_unidad_construccion": tipo_unidad,
                "tipo_unidad_construccion_ilicode": tipo_unidad_str,
                "tipo_tipologia": tipo_tipologia, "tipo_tipologia_ilicode": tipo_tipologia_ilicode,
                **relation_details,
            }))
    return issues

def _rule_4_3(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row, tipo_unidad, tipo_tipologia, relation_details in helper.iter_caracteristicas_tipologia():
        _raw_metodo, _resolved_metodo, metodo = _get_tipo_calificacion_resuelto(helper, row)
        if metodo and metodo != "Tipologia":
            continue
        tipo_unidad_str = _unidad_construccion_tipo_ilicode(tipo_unidad, table_name=table_name)
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
                        "Cuando el tipo de unidad de construccion es Industrial, "
                        "solamente se pueden asociar tipologias industriales."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_unidad_construccion": tipo_unidad,
                        "tipo_unidad_construccion_ilicode": tipo_unidad_str,
                        "tipo_tipologia": tipo_tipologia,
                        "tipo_tipologia_ilicode": tipo_tipologia_ilicode,
                        **relation_details,
                    },
                )
            )

    return issues


def _rule_4_4(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row, tipo_unidad, tipo_tipologia, relation_details in helper.iter_caracteristicas_tipologia():
        _raw_metodo, _resolved_metodo, metodo = _get_tipo_calificacion_resuelto(helper, row)
        if metodo and metodo != "Tipologia":
            continue
        tipo_unidad_str = _unidad_construccion_tipo_ilicode(tipo_unidad, table_name=table_name)
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
                        "Cuando el tipo de unidad de construccion es Institucional, "
                        "solamente se pueden asociar tipologias institucionales."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_unidad_construccion": tipo_unidad,
                        "tipo_unidad_construccion_ilicode": tipo_unidad_str,
                        "tipo_tipologia": tipo_tipologia,
                        "tipo_tipologia_ilicode": tipo_tipologia_ilicode,
                        **relation_details,
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
        _raw_metodo, _resolved_metodo, metodo = _get_tipo_calificacion_resuelto(helper, row)
        if metodo and metodo != "Convencional":
            continue
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
        _raw_metodo, _resolved_metodo, metodo = _get_tipo_calificacion_resuelto(helper, row)
        if metodo and metodo != "Convencional":
            continue
        tipo_calificar = helper.get_field_value(row, ("cc_tipo_calificar", "tipo_calificar"))
        tipo_calificar_str = _tipo_calificar_ilicode(tipo_calificar)
        if tipo_calificar_str not in {"Residencial", "Comercial", "Industrial", "Institucional", "Anexo"}:
            tipo_unidad = helper.get_field_value(row, ("tipo_unidad_construccion",))
            tipo_calificar_str = _unidad_construccion_tipo_ilicode(tipo_unidad, table_name=table_name)

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
        _raw_metodo, _resolved_metodo, metodo = _get_tipo_calificacion_resuelto(helper, row)
        if metodo and metodo != "Convencional":
            continue
        tipo_calificar = helper.get_field_value(row, ("cc_tipo_calificar", "tipo_calificar"))
        tipo_calificar_str = _tipo_calificar_ilicode(tipo_calificar)
        if tipo_calificar_str not in {"Residencial", "Comercial", "Industrial", "Institucional", "Anexo"}:
            tipo_unidad = helper.get_field_value(row, ("tipo_unidad_construccion",))
            tipo_calificar_str = _unidad_construccion_tipo_ilicode(tipo_unidad, table_name=table_name)

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
        _raw_cal, _resolved_cal, tipo_calificacion = _get_tipo_calificacion_resuelto(helper, row)
        # 4.8 corresponde a la calificacion convencional. Si el modelo no trae
        # Tipo_Calificacion, se aplica solo cuando existen campos CC diligenciados.
        if tipo_calificacion and tipo_calificacion != "Convencional":
            continue

        total_raw = helper.get_field_value(row, ("cc_total_calificacion", "total_calificacion"))
        campos_cc = ("cc_armazon", "cc_muros", "cc_cubierta", "cc_conservacion_estructura", "cc_fachada",
                     "cc_cubrimiento_muros", "cc_piso", "cc_conservacion_acabados", "cc_tamanio_banio",
                     "cc_mobiliario_banio", "cc_tamanio_cocina", "cc_mobiliario_cocina",
                     "cc_cerchas_complemento_industria")
        if not tipo_calificacion and not any(_is_not_empty(helper.get_field_value(row, (f,))) for f in campos_cc) and _is_empty(total_raw):
            continue

        total = _to_float(total_raw)
        tipo_calificar = helper.get_field_value(row, ("cc_tipo_calificar", "tipo_calificar"))
        tipo_puntaje = _tipo_calificar_ilicode(tipo_calificar)
        if tipo_puntaje not in {"Residencial", "Comercial", "Industrial"}:
            tipo_unidad = helper.get_field_value(row, ("tipo_unidad_construccion",))
            tipo_puntaje = _unidad_construccion_tipo_ilicode(tipo_unidad, table_name=table_name)

        esperado, desconocidos = _calcular_total_convencional(helper, row, tipo_puntaje)
        message = None
        if total is None:
            message = "El total de la calificacion convencional debe ser un valor numerico mayor que cero."
        elif total <= 0:
            message = "El total de la calificacion convencional debe ser diferente de cero."
        elif total > 100:
            message = "El total de la calificacion no puede ser mayor a 100."
        elif esperado is not None and not desconocidos and abs(total - esperado) > 1e-9:
            message = "El total de la calificacion no coincide con la sumatoria de los puntos de los atributos diligenciados."

        if message:
            issues.append(helper.make_issue(row, rule_id="4.8", message=message, details={
                "tabla": table_name, "tipo_calificar": tipo_calificar, "tipo_calificar_ilicode": tipo_puntaje,
                "total_calificacion": total_raw, "total_calculado": esperado,
                "campos_sin_equivalencia_puntaje": desconocidos,
            }))
    return issues


def _row_identifier_aliases(helper: EconomicoHelper, row: dict[str, object]) -> set[str]:
    aliases: set[str] = set()
    for field in helper.IDENTIFIER_FIELDS:
        value = helper.get_field_value(row, (field,))
        if _is_not_empty(value):
            aliases.add(str(value).strip())
    return aliases


def _rule_4_9(dataset: DatasetReader) -> list[RuleIssue]:
    """En una base final ILC, cada predio no cancelado debe tener EstructuraAvaluo."""
    helper = EconomicoHelper(dataset)
    predios = list(helper._iter_table_rows(("ILC_Predio", "ilc_predio")))
    if not predios:
        return []  # No es contexto de base catastral final ILC.

    avaluos = list(helper._iter_table_rows(("ILC_EstructuraAvaluo", "ilc_estructuraavaluo")))
    avaluo_refs: set[str] = set()
    for _, row in avaluos:
        ref = helper.get_field_value(row, ("ilc_predio_avaluo", "predio", "predio_ref", "ilc_predio", "predio_id"))
        if _is_not_empty(ref):
            avaluo_refs.add(str(ref).strip())

    # El lector XTF normalmente crea la referencia. Para un único predio/avalúo
    # legacy sin FK explícita se puede asociar sin ambigüedad.
    if not avaluo_refs and len(predios) == 1 and avaluos:
        avaluo_refs.update(_row_identifier_aliases(helper, predios[0][1]))

    cancelados: set[str] = set()
    datos = list(helper._iter_table_rows((
        "ILC_DatosAdicionalesLevantamientoCatastral",
        "ilc_datosadicionaleslevantamientocatastral",
    )))
    for _, row in datos:
        novedad = helper.get_field_value(row, (
            "novedad_numeros_prediales", "Novedad_Numeros_Prediales",
            "novedad_numero_predial", "novedad_numeros_prediales_tipo",
        ))
        if not _novedad_es_cancelacion(novedad):
            continue
        ref = helper.get_field_value(row, ("predio", "ilc_predio", "predio_ref", "ilc_predio_datos_adicionales", "predio_id"))
        if _is_not_empty(ref):
            cancelados.add(str(ref).strip())
        elif len(predios) == 1:
            cancelados.update(_row_identifier_aliases(helper, predios[0][1]))

    issues: list[RuleIssue] = []
    for table_name, row in predios:
        aliases = _row_identifier_aliases(helper, row)
        novedad_predio = helper.get_field_value(row, ("novedad_numeros_prediales", "Novedad_Numeros_Prediales"))
        if _novedad_es_cancelacion(novedad_predio):
            cancelados.update(aliases)
        if aliases & cancelados:
            continue
        if not aliases:
            continue
        if not (aliases & avaluo_refs):
            issues.append(helper.make_issue(row, rule_id="4.9", message=(
                "En la base catastral final, el predio no cancelado debe tener un registro en ILC_EstructuraAvaluo."
            ), details={"tabla": table_name, "identificadores_predio": sorted(aliases)}))
    return issues


def _iter_estructura_avaluo(helper: EconomicoHelper):
    yield from helper._iter_table_rows(("ILC_EstructuraAvaluo", "ilc_estructuraavaluo"))


def _avaluo_values(helper: EconomicoHelper, row: dict[str, object]) -> dict[str, float | None]:
    fields = {
        "valor_comercial": ("valor_comercial", "Valor_Comercial"),
        "valor_comercial_terreno": ("valor_comercial_terreno", "Valor_Comercial_Terreno"),
        "valor_comercial_unidades": ("valor_comercial_total_unidadesconstruccion", "Valor_Comercial_Total_UnidadesConstruccion", "valor_comercial_total_unidades_construccion"),
        "valor_catastral": ("valor_catastral", "Valor_Catastral"),
        "valor_catastral_terreno": ("valor_catastral_terreno", "Valor_Catastral_Terreno"),
        "valor_catastral_unidades": ("valor_catastral_total_unidadesconstruccion", "Valor_Catastral_Total_UnidadesConstruccion", "valor_catastral_total_unidades_construccion"),
    }
    return {key: _to_float(helper.get_field_value(row, aliases)) for key, aliases in fields.items()}


def _rule_4_16(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset); issues: list[RuleIssue] = []
    for table_name, row in _iter_estructura_avaluo(helper):
        v = _avaluo_values(helper, row); total=v["valor_comercial"]; terreno=v["valor_comercial_terreno"]; unidades=v["valor_comercial_unidades"]
        if total is None or terreno is None or unidades is None or total <= 0 or abs(total - (terreno + unidades)) > 0.01:
            issues.append(helper.make_issue(row, rule_id="4.16", message="El avalúo comercial debe ser mayor que cero y corresponder a terreno + total de unidades de construcción.", details={"tabla":table_name, **v}))
    return issues


def _rule_4_17(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset); issues: list[RuleIssue] = []
    for table_name, row in _iter_estructura_avaluo(helper):
        v = _avaluo_values(helper, row); total=v["valor_catastral"]; terreno=v["valor_catastral_terreno"]; unidades=v["valor_catastral_unidades"]
        if total is None or terreno is None or unidades is None or total <= 0 or abs(total - (terreno + unidades)) > 0.01:
            issues.append(helper.make_issue(row, rule_id="4.17", message="El avalúo catastral debe ser mayor que cero y corresponder a terreno + total de unidades de construcción.", details={"tabla":table_name, **v}))
    return issues


def _rule_4_18(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset); issues: list[RuleIssue] = []
    for table_name, row in _iter_estructura_avaluo(helper):
        v = _avaluo_values(helper, row)
        if any(value is None or value <= 0 for value in v.values()):
            bad = True
        else:
            bad = not (
                v["valor_comercial"] > v["valor_catastral"]
                and v["valor_catastral"] > 0.60 * v["valor_comercial"]
                and v["valor_comercial_terreno"] > v["valor_catastral_terreno"]
                and v["valor_comercial_unidades"] > v["valor_catastral_unidades"]
            )
        if bad:
            issues.append(helper.make_issue(row, rule_id="4.18", message="Los avalúos comerciales deben ser mayores a los catastrales, el catastral debe superar el 60% del comercial y todos los valores deben ser mayores que cero.", details={"tabla":table_name, **v}))
    return issues


def _rule_4_10(dataset: DatasetReader) -> list[RuleIssue]:
    """
    Regla 4.10:
    Si el tipo de unidad de construcción es Conservación y protección ambiental,
    la tipología asociada también debe ser de Conservación.
    """
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row, tipo_unidad, tipo_tipologia, relation_details in helper.iter_caracteristicas_tipologia():
        _raw_metodo, _resolved_metodo, metodo = _get_tipo_calificacion_resuelto(helper, row)
        if metodo and metodo != "Tipologia":
            continue
        tipo_unidad_str = _unidad_construccion_tipo_ilicode(tipo_unidad, table_name=table_name)
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
                        "Cuando el tipo de unidad de construccion es Conservacion y proteccion ambiental, "
                        "solamente se pueden asociar tipologias de conservacion."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_unidad_construccion": tipo_unidad,
                        "tipo_unidad_construccion_ilicode": tipo_unidad_str,
                        "tipo_tipologia": tipo_tipologia,
                        "tipo_tipologia_ilicode": tipo_tipologia_ilicode,
                        **relation_details,
                    },
                )
            )

    return issues

def _rule_4_11(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_caracteristicas_unidad_construccion():
        tipo_calificacion_raw = helper.get_field_value(
            row,
            (
                "tipo_calificacion",
                "Tipo_Calificacion",
                "ct_tipo_calificacion",
                "CT_Tipo_Calificacion",
            ),
        )

        tipo_calificacion_resuelto = helper.resolve_tipo_calificacion(tipo_calificacion_raw)
        tipo_calificacion_ilicode = _tipo_calificacion_ilicode(tipo_calificacion_resuelto)

        ct_tipo_tipologia = helper.get_field_value(
            row,
            (
                "ct_tipo_tipologia",
                "CT_Tipo_Tipologia",
            ),
        )

        if (
            tipo_calificacion_ilicode == "Tipologia"
            and not _is_not_empty(ct_tipo_tipologia)
        ):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="4.11",
                    message=(
                        "Cuando el Tipo de Calificacion es Tipologia, "
                        "el campo CT_Tipo_Tipologia debe estar diligenciado."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_calificacion": tipo_calificacion_raw,
                        "tipo_calificacion_resuelto": tipo_calificacion_resuelto,
                        "tipo_calificacion_ilicode": tipo_calificacion_ilicode,
                        "ct_tipo_tipologia": ct_tipo_tipologia,
                    },
                )
            )

    return issues

def _rule_4_12(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_caracteristicas_unidad_construccion():
        tipo_calificacion_raw = helper.get_field_value(
            row,
            (
                "tipo_calificacion",
                "Tipo_Calificacion",
                "ct_tipo_calificacion",
                "CT_Tipo_Calificacion",
            ),
        )

        tipo_calificacion_resuelto = helper.resolve_tipo_calificacion(tipo_calificacion_raw)
        tipo_calificacion_ilicode = _tipo_calificacion_ilicode(tipo_calificacion_resuelto)

        ct_conservacion_tipologia = helper.get_field_value(
            row,
            (
                "ct_conservacion_tipologia",
                "CT_Conservacion_Tipologia",
            ),
        )

        if (
            tipo_calificacion_ilicode == "Tipologia"
            and not _is_not_empty(ct_conservacion_tipologia)
        ):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="4.12",
                    message=(
                        "Cuando el Tipo de Calificacion es Tipologia, "
                        "el campo CT_Conservacion_Tipologia debe estar diligenciado."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_calificacion": tipo_calificacion_raw,
                        "tipo_calificacion_resuelto": tipo_calificacion_resuelto,
                        "tipo_calificacion_ilicode": tipo_calificacion_ilicode,
                        "ct_conservacion_tipologia": ct_conservacion_tipologia,
                    },
                )
            )

    return issues

def _rule_4_13(dataset: DatasetReader) -> list[RuleIssue]:
    """
    Regla 4.13:
    Si Tipo_Calificacion es No_Convencional,
    entonces Tipo_Unidad_Construccion debe ser Anexo.

    Nota: esta regla NO marca error por el caso contrario
    (por ejemplo Tipologia + Anexo), para evitar falsos positivos.
    """
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_caracteristicas_unidad_construccion():
        tipo_calificacion_raw, tipo_calificacion_resuelto, tipo_calificacion_ilicode = (
            _get_tipo_calificacion_resuelto(helper, row)
        )
        tipo_unidad_raw, tipo_unidad_resuelto, tipo_unidad_ilicode = (
            _get_tipo_unidad_resuelto(helper, row, table_name)
        )

        # Si no es No_Convencional, esta regla no aplica.
        if tipo_calificacion_ilicode != "No_Convencional":
            continue

        if tipo_unidad_ilicode != "Anexo":
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="4.13",
                    message=(
                        "Cuando el Tipo_Calificacion es No_Convencional, "
                        "el Tipo_Unidad_Construccion debe ser Anexo."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_calificacion": tipo_calificacion_raw,
                        "tipo_calificacion_resuelto": tipo_calificacion_resuelto,
                        "tipo_calificacion_ilicode": tipo_calificacion_ilicode,
                        "tipo_unidad_construccion": tipo_unidad_raw,
                        "tipo_unidad_construccion_resuelto": tipo_unidad_resuelto,
                        "tipo_unidad_construccion_ilicode": tipo_unidad_ilicode,
                    },
                )
            )

    return issues


def _rule_4_14(dataset: DatasetReader) -> list[RuleIssue]:
    """
    Regla 4.14:
    Si Tipo_Calificacion es No_Convencional,
    el campo CNC_Tipo_Anexo debe estar diligenciado.
    """
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_caracteristicas_unidad_construccion():
        tipo_calificacion_raw, tipo_calificacion_resuelto, tipo_calificacion_ilicode = (
            _get_tipo_calificacion_resuelto(helper, row)
        )
        cnc_tipo_anexo = helper.get_field_value(row, CNC_TIPO_ANEXO_FIELDS)

        if (
            tipo_calificacion_ilicode == "No_Convencional"
            and not _is_not_empty(cnc_tipo_anexo)
        ):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="4.14",
                    message=(
                        "Cuando el Tipo_Calificacion es No_Convencional, "
                        "el campo CNC_Tipo_Anexo debe estar diligenciado."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_calificacion": tipo_calificacion_raw,
                        "tipo_calificacion_resuelto": tipo_calificacion_resuelto,
                        "tipo_calificacion_ilicode": tipo_calificacion_ilicode,
                        "cnc_tipo_anexo": cnc_tipo_anexo,
                    },
                )
            )

    return issues


def _rule_4_15(dataset: DatasetReader) -> list[RuleIssue]:
    """
    Regla 4.15:
    Si Tipo_Calificacion es No_Convencional,
    el campo CNC_Conservacion_Anexo debe estar diligenciado.
    """
    helper = EconomicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_caracteristicas_unidad_construccion():
        tipo_calificacion_raw, tipo_calificacion_resuelto, tipo_calificacion_ilicode = (
            _get_tipo_calificacion_resuelto(helper, row)
        )
        cnc_conservacion_anexo = helper.get_field_value(row, CNC_CONSERVACION_ANEXO_FIELDS)

        if (
            tipo_calificacion_ilicode == "No_Convencional"
            and not _is_not_empty(cnc_conservacion_anexo)
        ):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="4.15",
                    message=(
                        "Cuando el Tipo_Calificacion es No_Convencional, "
                        "el campo CNC_Conservacion_Anexo debe estar diligenciado."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_calificacion": tipo_calificacion_raw,
                        "tipo_calificacion_resuelto": tipo_calificacion_resuelto,
                        "tipo_calificacion_ilicode": tipo_calificacion_ilicode,
                        "cnc_conservacion_anexo": cnc_conservacion_anexo,
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
    "4.11": _rule_4_11,
    "4.12": _rule_4_12,
    "4.13": _rule_4_13,
    "4.14": _rule_4_14,
    "4.15": _rule_4_15,
    "4.16": _rule_4_16,
    "4.17": _rule_4_17,
    "4.18": _rule_4_18,
}

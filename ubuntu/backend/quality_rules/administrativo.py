from __future__ import annotations
import re
import unicodedata
from .base import DatasetReader, RuleIssue

COMPONENT_SLUG = "administrativo"
DEFAULT_RULE_IDS = frozenset({
    "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "1.9", "1.10",
    "1.11", "1.12", "1.13", "1.14", "1.15", "1.16", "1.17", "1.18", "1.19", "1.20",
    "1.21", "1.22", "1.23", "1.24", "1.25", "1.26", "1.27", "1.28", "1.29", "1.30",
    "1.31", "1.32", "1.33", "1.34", "1.35", "1.36", "1.37", "1.38", "1.39", "1.40",
    "1.41", "1.42", "1.43", "1.44", "1.45", "1.46", "1.47", "1.48", "1.49",
})


class NumeroPredialHelper:
    """Utilidades compartidas para reglas administrativas."""

    IDENTIFIER_FIELDS = (
        "id_predio",
        "ID_PREDIO",
        "predio_id",
        "Predio_ID",
        "id",
        "ID",
        "local_id",
        "Id_Operacion",
        "t_id",
        "T_ID",
        "tid",
        "TID",
    )

    PREDIO_TABLES = (
        "ARB_Predio",
        "arb_predio",
    )

    NOVEDAD_TABLES = (
        "ARB_NovedadNumeroPredialValor",
        "arb_novedadnumeropredialvalor",
    )

    TERRENO_TABLES = (
        "ARB_Terreno",
        "arb_terreno",
    )

    CONSTRUCCION_TABLES = (
        "ARB_Construccion",
        "arb_construccion",
    )

    UNIDAD_CONSTRUCCION_TABLES = (
        "ARB_UnidadConstruccion",
        "arb_unidadconstruccion",
    )

    INFORMACION_PH_TABLES = (
        "ARB_InformacionPH",
        "arb_informacionph",
    )

    CARACTERISTICAS_UNIDAD_TABLES = (
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )

    DIRECCION_TABLES = (
        "ARB_Direccion",
        "arb_direccion",
        "ARB_Dirección",
        "arb_dirección",
    )

    NUMERO_PREDIAL_FIELDS = (
        "Numero_Predial_Nacional",
        "numero_predial_nacional",
        "numero_predial",
        "Numero_Predial",
    )

    NOVEDAD_NUMERO_FIELDS = (
        "Novedad_Numeros_Prediales",
        "Numero_Predial",
        "numero_predial",
        "numero_predial_nacional",
    )

    CONDICION_FIELDS = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    MATRICULA_FIELDS = (
        "matricula_inmobiliaria",
        "Matrícula inmobiliaria",
        "Matricula_Inmobiliaria",
        "Matricula_inmobiliaria",
    )

    ORIP_FIELDS = (
        "codigo_orip",
        "Codigo_ORIP",
        "Código ORIP",
        "codigoorip",
    )

    DIRECCION_FIELDS = (
        "ARB_Direccion",
        "arb_direccion",
        "ARB_Dirección",
        "arb_dirección",
    )

    DESTINACION_FIELDS = (
        "destinacion_economica",
        "Destinacion_Economica",
        "destinacion",
        "Destinacion",
    )

    PREDIO_MATRIZ_FIELDS = (
        "predio_matriz",
        "Predio_Matriz",
    )

    AREA_CONSTRUIDA_FIELDS = (
        "Area_Construida",
        "area_construida",
    )

    def __init__(self, dataset: DatasetReader):
        self.dataset = dataset

    def iter_predios(self):
        yield from self._iter_table_rows(self.PREDIO_TABLES)

    def iter_novedades(self):
        yield from self._iter_table_rows(self.NOVEDAD_TABLES)

    def iter_direcciones(self):
        yield from self._iter_table_rows(self.DIRECCION_TABLES)

    def iter_terrenos(self):
        yield from self._iter_table_rows(self.TERRENO_TABLES)

    def iter_construcciones(self):
        yield from self._iter_table_rows(self.CONSTRUCCION_TABLES)

    def iter_unidades_construccion(self):
        yield from self._iter_table_rows(self.UNIDAD_CONSTRUCCION_TABLES)

    def iter_informacion_ph(self):
        yield from self._iter_table_rows(self.INFORMACION_PH_TABLES)

    def iter_caracteristicas_unidad(self):
        yield from self._iter_table_rows(self.CARACTERISTICAS_UNIDAD_TABLES)

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

    def identify(self, row: dict[str, object]) -> str | None:
        preferred_fields = (
            "id_operacion",
            "Id_Operacion",
            "ID_OPERACION",
            "id_predio",
            "ID_PREDIO",
            "predio_id",
            "Predio_ID",
            "id",
            "ID",
            "local_id",
            "Local_ID",
            "t_id",
            "T_ID",
            "tid",
            "TID",
        )

        # 1. intento directo por nombre conocido
        for field in preferred_fields:
            value = row.get(field)
            if value not in (None, ""):
                return str(value).strip()

        # 2. intento por coincidencia normalizada exacta
        normalized_targets = {self._normalize_key(field) for field in preferred_fields}
        for key, candidate in row.items():
            if self._normalize_key(str(key)) in normalized_targets and candidate not in (None, ""):
                return str(candidate).strip()

        # 3. intento flexible: cualquier llave que contenga idoperacion
        for key, candidate in row.items():
            normalized_key = self._normalize_key(str(key))
            if "idoperacion" in normalized_key and candidate not in (None, ""):
                return str(candidate).strip()

        # 4. fallback útil para predios si no apareció el id_operacion
        fallback_fields = (
            "numero_predial",
            "Numero_Predial",
            "numero_predial_nacional",
            "Numero_Predial_Nacional",
        )
        normalized_fallbacks = {self._normalize_key(field) for field in fallback_fields}
        for key, candidate in row.items():
            if self._normalize_key(str(key)) in normalized_fallbacks and candidate not in (None, ""):
                return str(candidate).strip()

        return None

    def get_field_value(self, row: dict[str, object], candidates: tuple[str, ...]) -> str | None:
        match = self._extract_field(row, candidates, require_value=False)
        if not match:
            return None
        _, raw_value = match
        if raw_value in (None, ""):
            return None
        return str(raw_value).strip()

    def get_relation_value(self, row: dict[str, object], candidates: tuple[str, ...]) -> str | None:
        return self.get_field_value(row, candidates)

    def make_issue(
        self,
        row: dict[str, object],
        *,
        rule_id: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> RuleIssue:
        return RuleIssue(
            rule_id=rule_id,
            object_ref=self.identify(row),
            message=message,
            details=details or {},
        )

    def pull_predial_number(
        self,
        row: dict[str, object],
        *,
        allow_guess: bool,
        use_novedad_fields: bool = False,
    ) -> tuple[str, str, object] | None:
        fields = self.NOVEDAD_NUMERO_FIELDS if use_novedad_fields else self.NUMERO_PREDIAL_FIELDS
        match = self._extract_field(row, fields, require_value=True)
        if match:
            field_name, raw_value = match
            numero = self._coerce_predial_str(raw_value)
            if numero:
                return field_name, numero, raw_value

        if not allow_guess:
            return None

        for key, value in row.items():
            key_lower = self._normalize_key(key)
            if "numero" in key_lower and "predial" in key_lower:
                numero = self._coerce_predial_str(value)
                if numero:
                    return key, numero, value

        return None

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

    @staticmethod
    def _is_empty(value: object) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ""
        return False

    @classmethod
    def _extract_field(
        cls,
        row: dict[str, object],
        candidates: tuple[str, ...],
        *,
        require_value: bool,
    ) -> tuple[str, object] | None:
        normalized_candidates = {cls._normalize_key(candidate) for candidate in candidates}

        for key, value in row.items():
            if cls._normalize_key(key) in normalized_candidates:
                if not require_value or not cls._is_empty(value):
                    return key, value

        return None

    @classmethod
    def _coerce_predial_str(cls, value: object) -> str:
        if value is None:
            return ""

        if isinstance(value, dict):
            for key in (
                "Numero_Predial_Nacional",
                "Numero_Predial",
                "numero_predial",
                "numero_predial_nacional",
            ):
                text = cls._coerce_predial_str(value.get(key))
                if text:
                    return text
            return ""

        if isinstance(value, (list, tuple, set)):
            for item in value:
                text = cls._coerce_predial_str(item)
                if text:
                    return text
            return ""

        return str(value).strip()


def _is_valid_numero_predial(numero: str) -> bool:
    return len(numero) == 30 and numero.isdigit()


def _normalize_catalog_value(value: object, aliases: dict[str, str]) -> str:
    if value is None:
        return ""

    text = str(value).strip().lower()
    text = (
        text.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )
    text = text.replace(" ", "_").replace("-", "_")

    return aliases.get(text, text.upper())


CONDICION_ALIASES = {
    "nph": "NPH",
    "bien_uso_publico": "BIEN_USO_PUBLICO",
    "via": "VIA",
    "parque_cementerio.unidad_predial": "PARQUE_CEMENTERIO_UNIDAD_PREDIAL",
    "parque_cementerio.matriz": "PARQUE_CEMENTERIO_MATRIZ",
    "informal": "INFORMAL",
    "ph.matriz": "PH_MATRIZ",
    "ph.unidad_predial": "PH_UNIDAD_PREDIAL",
    "condominio.matriz": "CONDOMINIO_MATRIZ",
    "condominio.unidad_predial": "CONDOMINIO_UNIDAD_PREDIAL",
}

DESTINACION_ALIASES = {
    "lote_rural": "LOTE_RURAL",
    "lote_urbanizado_no_construido": "LOTE_URBANIZADO_NO_CONSTRUIDO",
    "lote_urbanizado_sin_construccion": "LOTE_URBANIZADO_NO_CONSTRUIDO",
    "comercial": "COMERCIAL",
    "educativo": "EDUCATIVO",
    "habitacional": "HABITACIONAL",
    "industrial": "INDUSTRIAL",
    "institucional": "INSTITUCIONAL",
    "salubridad": "SALUBRIDAD",
}

NOVEDAD_ALIAS = {
    "cancelacion": "CANCELACION",
    "cancelacion_por_englobe": "CANCELACION_POR_ENGLOBE",
    "cancelacion_por_desenglobe": "CANCELACION_POR_DESENGLOBE",
}


def _normalize_condicion(value: object) -> str:
    return _normalize_catalog_value(value, CONDICION_ALIASES)


def _normalize_destinacion(value: object) -> str:
    return _normalize_catalog_value(value, DESTINACION_ALIASES)


def _normalize_novedad(value: object) -> str:
    return _normalize_catalog_value(value, NOVEDAD_ALIAS)


def _expected_suffix_by_condicion(condicion: str) -> str | None:
    mapping = {
        "NPH": "000000000",
        "BIEN_USO_PUBLICO": "300000000",
        "VIA": "400000000",
        "PARQUE_CEMENTERIO_UNIDAD_PREDIAL": "700000000",
        "PARQUE_CEMENTERIO_MATRIZ": "700000000",
        "INFORMAL": "200000000",
    }
    return mapping.get(condicion)


def _expected_suffix_ph(condicion: str) -> str | None:
    mapping = {
        "PH_MATRIZ": "900000000",
        "PH_UNIDAD_PREDIAL": "900000000",
    }
    return mapping.get(condicion)


def _expected_digit_ph(condicion: str) -> str | None:
    mapping = {
        "PH_MATRIZ": "9",
        "PH_UNIDAD_PREDIAL": "9",
    }
    return mapping.get(condicion)


def _expected_suffix_condominio(condicion: str) -> str | None:
    mapping = {
        "CONDOMINIO_MATRIZ": "800000000",
        "CONDOMINIO_UNIDAD_PREDIAL": "800000000",
    }
    return mapping.get(condicion)


def _expected_digit_condominio(condicion: str) -> str | None:
    mapping = {
        "CONDOMINIO_MATRIZ": "8",
        "CONDOMINIO_UNIDAD_PREDIAL": "8",
    }
    return mapping.get(condicion)

#----------------------------- REGLAS -----------------------------

def _rule_1_1(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        result = helper.pull_predial_number(row, allow_guess=False)
        if not result:
            missing_field = helper._extract_field(row, helper.NUMERO_PREDIAL_FIELDS, require_value=False)
            if missing_field:
                field_name, raw_value = missing_field
                message = "Numero_Predial_Nacional debe estar diligenciado."
                payload = {"valor": raw_value}
            else:
                field_name = helper.NUMERO_PREDIAL_FIELDS[0]
                message = "Numero_Predial_Nacional no existe en el registro."
                payload = {}
            details = {
                **payload,
                "tabla": table_name,
                "campo": field_name,
                "class": table_name,
            }
            issues.append(
                RuleIssue(
                    rule_id="1.1",
                    object_ref=helper.identify(row),
                    message=message,
                    details=details,
                )
            )
            continue

        field_name, numero_str, raw_value = result

        condicion_raw = helper.get_field_value(row, helper.CONDICION_FIELDS)
        if not condicion_raw:
            issues.append(
                RuleIssue(
                    rule_id="1.1",
                    object_ref=helper.identify(row),
                    message="No se puede validar la regla 1.1 porque condicion_predio no existe o está vacía.",
                    details={
                        "tabla": table_name,
                        "campo": "condicion_predio",
                        "class": table_name,
                        "numero": numero_str,
                    },
                )
            )
            continue

        condicion = _normalize_condicion(condicion_raw)
        expected = _expected_suffix_by_condicion(condicion)

        if not expected:
            continue

        actual = numero_str[21:30]

        if actual != expected:
            issues.append(
                RuleIssue(
                    rule_id="1.1",
                    object_ref=helper.identify(row),
                    message=(
                        f"Los campos 22-30 de Numero_Predial_Nacional no cumplen la regla "
                        f"para la condición '{condicion_raw}'."
                    ),
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                        "valor": raw_value,
                        "numero": numero_str,
                        "condicion_predio": condicion_raw,
                        "valor_esperado_22_30": expected,
                        "valor_encontrado_22_30": actual,
                    },
                )
            )

    return issues


def _rule_1_2(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        result = helper.pull_predial_number(row, allow_guess=False)
        if not result:
            missing_field = helper._extract_field(row, helper.NUMERO_PREDIAL_FIELDS, require_value=False)
            if missing_field:
                field_name, raw_value = missing_field
                message = "Numero_Predial_Nacional debe estar diligenciado."
                payload = {"valor": raw_value}
            else:
                field_name = helper.NUMERO_PREDIAL_FIELDS[0]
                message = "Numero_Predial_Nacional no existe en el registro."
                payload = {}
            details = {
                **payload,
                "tabla": table_name,
                "campo": field_name,
                "class": table_name,
            }
            issues.append(
                RuleIssue(
                    rule_id="1.2",
                    object_ref=helper.identify(row),
                    message=message,
                    details=details,
                )
            )
            continue

        field_name, numero_str, raw_value = result
        if not _is_valid_numero_predial(numero_str):
            issues.append(
                RuleIssue(
                    rule_id="1.2",
                    object_ref=helper.identify(row),
                    message="Numero_Predial_Nacional debe contener 30 digitos.",
                    details={
                        "valor": raw_value,
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                    },
                )
            )

    for table_name, row in helper.iter_novedades():
        result = helper.pull_predial_number(row, allow_guess=True, use_novedad_fields=True)
        if not result:
            continue
        field_name, numero_str, raw_value = result
        if numero_str and not _is_valid_numero_predial(numero_str):
            issues.append(
                RuleIssue(
                    rule_id="1.2",
                    object_ref=helper.identify(row),
                    message="El numero predial registrado en novedades debe contener 30 digitos.",
                    details={
                        "valor": raw_value,
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                    },
                )
            )

    return issues


def _rule_1_3(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    if not any(dataset.has_table(name) for name in helper.PREDIO_TABLES):
        return []

    issues: list[RuleIssue] = []
    for table_name, row in helper.iter_predios():
        result = helper.pull_predial_number(row, allow_guess=False)
        if not result:
            missing_field = helper._extract_field(row, helper.NUMERO_PREDIAL_FIELDS, require_value=False)
            if missing_field:
                field_name = missing_field[0]
                message = "Numero_Predial_Nacional debe estar diligenciado para evaluar los campos 14-21."
            else:
                field_name = helper.NUMERO_PREDIAL_FIELDS[0]
                message = "Numero_Predial_Nacional no existe en el registro."
            issues.append(
                RuleIssue(
                    rule_id="1.3",
                    object_ref=helper.identify(row),
                    message=message,
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                    },
                )
            )
            continue

        field_name, numero_str, raw_value = result
        if len(numero_str) < 21:
            continue
        tramo_14_17 = numero_str[13:17]
        tramo_18_21 = numero_str[17:21]
        if tramo_14_17 == "0000" or tramo_18_21 == "0000":
            issues.append(
                RuleIssue(
                    rule_id="1.3",
                    object_ref=helper.identify(row),
                    message="Los campos 14-17 y 18-21 no pueden ser '0000'.",
                    details={
                        "numero": numero_str,
                        "campo_14_17": tramo_14_17,
                        "campo_18_21": tramo_18_21,
                        "tabla": table_name,
                        "campo": field_name,
                        "valor": raw_value,
                        "class": table_name,
                    },
                )
            )

    return issues


def _rule_1_4(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        result = helper.pull_predial_number(row, allow_guess=False)
        if not result:
            missing_field = helper._extract_field(row, helper.NUMERO_PREDIAL_FIELDS, require_value=False)
            if missing_field:
                field_name, raw_value = missing_field
                message = "Numero_Predial_Nacional debe estar diligenciado."
                payload = {"valor": raw_value}
            else:
                field_name = helper.NUMERO_PREDIAL_FIELDS[0]
                message = "Numero_Predial_Nacional no existe en el registro."
                payload = {}
            details = {
                **payload,
                "tabla": table_name,
                "campo": field_name,
                "class": table_name,
            }
            issues.append(
                RuleIssue(
                    rule_id="1.4",
                    object_ref=helper.identify(row),
                    message=message,
                    details=details,
                )
            )
            continue

        field_name, numero_str, raw_value = result

        condicion_raw = helper.get_field_value(row, helper.CONDICION_FIELDS)
        if not condicion_raw:
            issues.append(
                RuleIssue(
                    rule_id="1.4",
                    object_ref=helper.identify(row),
                    message="No se puede validar la regla 1.4 porque condicion_predio no existe o está vacía.",
                    details={
                        "tabla": table_name,
                        "campo": "condicion_predio",
                        "class": table_name,
                        "numero": numero_str,
                    },
                )
            )
            continue

        condicion = _normalize_condicion(condicion_raw)
        expected = _expected_suffix_ph(condicion)

        if not expected:
            continue

        actual = numero_str[21:30]

        if actual != expected:
            issues.append(
                RuleIssue(
                    rule_id="1.4",
                    object_ref=helper.identify(row),
                    message=(
                        f"Los campos 22-30 de Numero_Predial_Nacional no cumplen la regla "
                        f"para la condición '{condicion_raw}'."
                    ),
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                        "valor": raw_value,
                        "numero": numero_str,
                        "condicion_predio": condicion_raw,
                        "valor_esperado_22_30": expected,
                        "valor_encontrado_22_30": actual,
                    },
                )
            )

    return issues


def _rule_1_5(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        result = helper.pull_predial_number(row, allow_guess=False)
        if not result:
            missing_field = helper._extract_field(row, helper.NUMERO_PREDIAL_FIELDS, require_value=False)
            if missing_field:
                field_name, raw_value = missing_field
                message = "Numero_Predial_Nacional debe estar diligenciado."
                payload = {"valor": raw_value}
            else:
                field_name = helper.NUMERO_PREDIAL_FIELDS[0]
                message = "Numero_Predial_Nacional no existe en el registro."
                payload = {}
            details = {
                **payload,
                "tabla": table_name,
                "campo": field_name,
                "class": table_name,
            }
            issues.append(
                RuleIssue(
                    rule_id="1.5",
                    object_ref=helper.identify(row),
                    message=message,
                    details=details,
                )
            )
            continue

        field_name, numero_str, raw_value = result

        condicion_raw = helper.get_field_value(row, helper.CONDICION_FIELDS)
        if not condicion_raw:
            issues.append(
                RuleIssue(
                    rule_id="1.5",
                    object_ref=helper.identify(row),
                    message="No se puede validar la regla 1.5 porque condicion_predio no existe o está vacía.",
                    details={
                        "tabla": table_name,
                        "campo": "condicion_predio",
                        "class": table_name,
                        "numero": numero_str,
                    },
                )
            )
            continue

        condicion = _normalize_condicion(condicion_raw)
        expected = _expected_digit_ph(condicion)

        if not expected:
            continue

        actual = numero_str[21]

        if actual != expected:
            issues.append(
                RuleIssue(
                    rule_id="1.5",
                    object_ref=helper.identify(row),
                    message=(
                        f"El campo 22 de Numero_Predial_Nacional no cumple la regla "
                        f"para la condición '{condicion_raw}'."
                    ),
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                        "valor": raw_value,
                        "numero": numero_str,
                        "condicion_predio": condicion_raw,
                        "valor_esperado_22": expected,
                        "valor_encontrado_22": actual,
                    },
                )
            )

        posiciones = numero_str[22:30] == "00000000"

        if actual == expected and not posiciones:
            issues.append(
                RuleIssue(
                    rule_id="1.5",
                    object_ref=helper.identify(row),
                    message=(
                        f"Los campos 23-30 de Numero_Predial_Nacional deben ser '00000000' "
                        f"para la condición '{condicion_raw}' cuando el campo 22 es '{expected}'."
                    ),
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                        "valor": raw_value,
                        "numero": numero_str,
                        "condicion_predio": condicion_raw,
                        "valor_esperado_23_30": "00000000",
                        "valor_encontrado_23_30": numero_str[22:30],
                    },
                )
            )

    return issues


def _rule_1_6(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        result = helper.pull_predial_number(row, allow_guess=False)
        if not result:
            missing_field = helper._extract_field(row, helper.NUMERO_PREDIAL_FIELDS, require_value=False)
            if missing_field:
                field_name, raw_value = missing_field
                message = "Numero_Predial_Nacional debe estar diligenciado."
                payload = {"valor": raw_value}
            else:
                field_name = helper.NUMERO_PREDIAL_FIELDS[0]
                message = "Numero_Predial_Nacional no existe en el registro."
                payload = {}
            details = {
                **payload,
                "tabla": table_name,
                "campo": field_name,
                "class": table_name,
            }
            issues.append(
                RuleIssue(
                    rule_id="1.6",
                    object_ref=helper.identify(row),
                    message=message,
                    details=details,
                )
            )
            continue

        field_name, numero_str, raw_value = result

        condicion_raw = helper.get_field_value(row, helper.CONDICION_FIELDS)
        if not condicion_raw:
            issues.append(
                RuleIssue(
                    rule_id="1.6",
                    object_ref=helper.identify(row),
                    message="No se puede validar la regla 1.6 porque condicion_predio no existe o está vacía.",
                    details={
                        "tabla": table_name,
                        "campo": "condicion_predio",
                        "class": table_name,
                        "numero": numero_str,
                    },
                )
            )
            continue

        condicion = _normalize_condicion(condicion_raw)
        expected = _expected_suffix_condominio(condicion)

        if not expected:
            continue

        actual = numero_str[21:30]

        if actual != expected:
            issues.append(
                RuleIssue(
                    rule_id="1.6",
                    object_ref=helper.identify(row),
                    message=(
                        f"Los campos 22-30 de Numero_Predial_Nacional no cumplen la regla "
                        f"para la condición '{condicion_raw}'."
                    ),
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                        "valor": raw_value,
                        "numero": numero_str,
                        "condicion_predio": condicion_raw,
                        "valor_esperado_22_30": expected,
                        "valor_encontrado_22_30": actual,
                    },
                )
            )

    return issues


def _rule_1_7(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        result = helper.pull_predial_number(row, allow_guess=False)
        if not result:
            missing_field = helper._extract_field(row, helper.NUMERO_PREDIAL_FIELDS, require_value=False)
            if missing_field:
                field_name, raw_value = missing_field
                message = "Numero_Predial_Nacional debe estar diligenciado."
                payload = {"valor": raw_value}
            else:
                field_name = helper.NUMERO_PREDIAL_FIELDS[0]
                message = "Numero_Predial_Nacional no existe en el registro."
                payload = {}
            details = {
                **payload,
                "tabla": table_name,
                "campo": field_name,
                "class": table_name,
            }
            issues.append(
                RuleIssue(
                    rule_id="1.7",
                    object_ref=helper.identify(row),
                    message=message,
                    details=details,
                )
            )
            continue

        field_name, numero_str, raw_value = result

        condicion_raw = helper.get_field_value(row, helper.CONDICION_FIELDS)
        if not condicion_raw:
            issues.append(
                RuleIssue(
                    rule_id="1.7",
                    object_ref=helper.identify(row),
                    message="No se puede validar la regla 1.7 porque condicion_predio no existe o está vacía.",
                    details={
                        "tabla": table_name,
                        "campo": "condicion_predio",
                        "class": table_name,
                        "numero": numero_str,
                    },
                )
            )
            continue

        condicion = _normalize_condicion(condicion_raw)
        expected = _expected_digit_condominio(condicion)

        if not expected:
            continue

        actual = numero_str[21]

        if actual != expected:
            issues.append(
                RuleIssue(
                    rule_id="1.7",
                    object_ref=helper.identify(row),
                    message=(
                        f"El campo 22 de Numero_Predial_Nacional no cumple la regla "
                        f"para la condición '{condicion_raw}'."
                    ),
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                        "valor": raw_value,
                        "numero": numero_str,
                        "condicion_predio": condicion_raw,
                        "valor_esperado_22": expected,
                        "valor_encontrado_22": actual,
                    },
                )
            )

        posiciones = numero_str[26:30] == "0000"

        if actual == expected and not posiciones:
            issues.append(
                RuleIssue(
                    rule_id="1.7",
                    object_ref=helper.identify(row),
                    message=(
                        f"Los campos 27-30 de Numero_Predial_Nacional deben ser '0000' "
                        f"para la condición '{condicion_raw}' cuando el campo 22 es '{expected}'."
                    ),
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                        "valor": raw_value,
                        "numero": numero_str,
                        "condicion_predio": condicion_raw,
                        "valor_esperado_27_30": "0000",
                        "valor_encontrado_27_30": numero_str[26:30],
                    },
                )
            )

    return issues


def _rule_1_8(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        result = helper.pull_predial_number(row, allow_guess=False)
        if not result:
            missing_field = helper._extract_field(row, helper.NUMERO_PREDIAL_FIELDS, require_value=False)
            if missing_field:
                field_name, raw_value = missing_field
                message = "Numero_Predial_Nacional debe estar diligenciado."
                payload = {"valor": raw_value}
            else:
                field_name = helper.NUMERO_PREDIAL_FIELDS[0]
                message = "Numero_Predial_Nacional no existe en el registro."
                payload = {}
            details = {
                **payload,
                "tabla": table_name,
                "campo": field_name,
                "class": table_name,
            }
            issues.append(
                RuleIssue(
                    rule_id="1.8",
                    object_ref=helper.identify(row),
                    message=message,
                    details=details,
                )
            )
            continue

        field_name, numero_str, raw_value = result

        valor_22 = numero_str[21]

        if valor_22 in ["1", "5", "6"]:
            issues.append(
                RuleIssue(
                    rule_id="1.8",
                    object_ref=helper.identify(row),
                    message="El campo 22 del Numero_Predial_Nacional no puede ser 1, 5 o 6.",
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                        "valor": raw_value,
                        "numero": numero_str,
                        "valor_encontrado_22": valor_22,
                        "valores_no_permitidos": ["1", "5", "6"],
                    },
                )
            )

    return issues


def _rule_1_9(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        result = helper.pull_predial_number(row, allow_guess=False)
        if not result:
            missing_field = helper._extract_field(row, helper.NUMERO_PREDIAL_FIELDS, require_value=False)
            if missing_field:
                field_name, raw_value = missing_field
                message = "Numero_Predial_Nacional debe estar diligenciado."
                payload = {"valor": raw_value}
            else:
                field_name = helper.NUMERO_PREDIAL_FIELDS[0]
                message = "Numero_Predial_Nacional no existe en el registro."
                payload = {}
            details = {
                **payload,
                "tabla": table_name,
                "campo": field_name,
                "class": table_name,
            }
            issues.append(
                RuleIssue(
                    rule_id="1.9",
                    object_ref=helper.identify(row),
                    message=message,
                    details=details,
                )
            )
            continue

        field_name, numero_str, raw_value = result
        departamento = numero_str[0:2]

        if departamento != "41":
            issues.append(
                RuleIssue(
                    rule_id="1.9",
                    object_ref=helper.identify(row),
                    message="Los campos 1-2 del Numero_Predial_Nacional deben corresponder al codigo del departemneto dilegenciado.",
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                        "valor": raw_value,
                        "numero": numero_str,
                        "valor_encontrado_1_2": departamento,
                        "valores_permitidos_1_2": ["41"],
                    }
                )
            )

    return issues


def _rule_1_10(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        result = helper.pull_predial_number(row, allow_guess=False)
        if not result:
            missing_field = helper._extract_field(row, helper.NUMERO_PREDIAL_FIELDS, require_value=False)
            if missing_field:
                field_name, raw_value = missing_field
                message = "Numero_Predial_Nacional debe estar diligenciado."
                payload = {"valor": raw_value}
            else:
                field_name = helper.NUMERO_PREDIAL_FIELDS[0]
                message = "Numero_Predial_Nacional no existe en el registro."
                payload = {}
            details = {
                **payload,
                "tabla": table_name,
                "campo": field_name,
                "class": table_name,
            }
            issues.append(
                RuleIssue(
                    rule_id="1.10",
                    object_ref=helper.identify(row),
                    message=message,
                    details=details,
                )
            )
            continue

        field_name, numero_str, raw_value = result
        municipio = numero_str[2:5]

        if municipio != "001":
            issues.append(
                RuleIssue(
                    rule_id="1.10",
                    object_ref=helper.identify(row),
                    message="Los campos 3-5 del Numero_Predial_Nacional deben corresponder al codigo del municipio dilegenciado.",
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                        "valor": raw_value,
                        "numero": numero_str,
                        "valor_encontrado_3_5": municipio,
                        "valores_permitidos_3_5": ["001"],
                    }
                )
            )

    return issues


def _rule_1_11(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    occurrences: dict[str, list[dict[str, object]]] = {}

    for table_name, row in helper.iter_predios():
        result = helper.pull_predial_number(row, allow_guess=False)
        if not result:
            missing_field = helper._extract_field(
                row,
                helper.NUMERO_PREDIAL_FIELDS,
                require_value=False,
            )
            if missing_field:
                field_name, raw_value = missing_field
                message = "Numero_Predial_Nacional debe estar diligenciado."
                payload = {"valor": raw_value}
            else:
                field_name = helper.NUMERO_PREDIAL_FIELDS[0]
                message = "Numero_Predial_Nacional no existe en el registro."
                payload = {}

            issues.append(
                RuleIssue(
                    rule_id="1.11",
                    object_ref=helper.identify(row),
                    message=message,
                    details={
                        **payload,
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                    },
                )
            )
            continue

        field_name, numero_str, raw_value = result
        occurrences.setdefault(numero_str, []).append(
            {
                "table_name": table_name,
                "row": row,
                "field_name": field_name,
                "raw_value": raw_value,
                "object_ref": helper.identify(row),
            }
        )

    for numero, records in occurrences.items():
        if len(records) <= 1:
            continue

        refs = [record["object_ref"] for record in records if record["object_ref"]]
        refs_unicas = list(dict.fromkeys(refs))

        for record in records:
            issues.append(
                RuleIssue(
                    rule_id="1.11",
                    object_ref=record["object_ref"],
                    message="En los registros de número predial no deben existir duplicados.",
                    details={
                        "tabla": record["table_name"],
                        "campo": record["field_name"],
                        "class": record["table_name"],
                        "valor": record["raw_value"],
                        "numero": numero,
                        "total_duplicados": len(records),
                        "registros_relacionados": refs_unicas,
                    },
                )
            )

    return issues


def _rule_1_12(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    relaciones: dict[str, dict[str, list[dict[str, object]]]] = {}

    for table_name, row in helper.iter_predios():
        matricula_match = helper._extract_field(
            row,
            helper.MATRICULA_FIELDS,
            require_value=False,
        )

        if not matricula_match:
            issues.append(
                RuleIssue(
                    rule_id="1.12",
                    object_ref=helper.identify(row),
                    message="Matricula_inmobiliaria no existe en el registro.",
                    details={
                        "tabla": table_name,
                        "campo": "Matricula_inmobiliaria",
                        "class": table_name,
                    },
                )
            )
            continue

        matricula_field, matricula_raw = matricula_match
        matricula_str = "" if matricula_raw in (None, "") else str(matricula_raw).strip()

        if not matricula_str:
            issues.append(
                RuleIssue(
                    rule_id="1.12",
                    object_ref=helper.identify(row),
                    message="No se puede validar la regla 1.12 porque Matricula_inmobiliaria no existe o está vacía.",
                    details={
                        "tabla": table_name,
                        "campo": matricula_field,
                        "class": table_name,
                        "valor": matricula_raw,
                    },
                )
            )
            continue

        predial_match = helper._extract_field(
            row,
            helper.NUMERO_PREDIAL_FIELDS,
            require_value=False,
        )

        if not predial_match:
            continue

        predial_field, predial_raw = predial_match
        numero_str = "" if predial_raw in (None, "") else str(predial_raw).strip()

        if not numero_str:
            continue

        relaciones.setdefault(matricula_str, {}).setdefault(numero_str, []).append(
            {
                "tabla": table_name,
                "campo_matricula": matricula_field,
                "campo_predial": predial_field,
                "class": table_name,
                "valor_matricula": matricula_raw,
                "valor_predial": predial_raw,
                "object_ref": helper.identify(row),
            }
        )

    for matricula, numeros in relaciones.items():
        if len(numeros) <= 1:
            continue

        numeros_relacionados = list(numeros.keys())

        for numero, records in numeros.items():
            for record in records:
                issues.append(
                    RuleIssue(
                        rule_id="1.12",
                        object_ref=record["object_ref"],
                        message="El valor de Matricula_inmobiliaria no puede estar relacionado a más de un numero predial.",
                        details={
                            "tabla": record["tabla"],
                            "campo": record["campo_matricula"],
                            "class": record["class"],
                            "valor": record["valor_matricula"],
                            "matricula_inmobiliaria": matricula,
                            "numero": numero,
                            "numeros_prediales_relacionados": numeros_relacionados,
                            "total_numeros_prediales": len(numeros_relacionados),
                        },
                    )
                )

    return issues


def _rule_1_13(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        matricula_match = helper._extract_field(
            row,
            helper.MATRICULA_FIELDS,
            require_value=False,
        )

        if not matricula_match:
            issues.append(
                RuleIssue(
                    rule_id="1.13",
                    object_ref=helper.identify(row),
                    message="Matricula_inmobiliaria no existe en el registro.",
                    details={
                        "tabla": table_name,
                        "campo": "Matricula_inmobiliaria",
                        "class": table_name,
                    },
                )
            )
            continue

        field_name, raw_value = matricula_match
        matricula_str = "" if raw_value in (None, "") else str(raw_value).strip()

        if not matricula_str:
            issues.append(
                RuleIssue(
                    rule_id="1.13",
                    object_ref=helper.identify(row),
                    message="No se puede validar la regla 1.13 porque Matricula_inmobiliaria no existe o está vacía.",
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                        "valor": raw_value,
                    },
                )
            )
            continue

        if not matricula_str.isdigit():
            issues.append(
                RuleIssue(
                    rule_id="1.13",
                    object_ref=helper.identify(row),
                    message="El folio de Matricula_inmobiliaria debe ser numérico y no puede contener letras.",
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                        "valor": raw_value,
                        "matricula_inmobiliaria": matricula_str,
                    },
                )
            )

    return issues


def _rule_1_14(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        codigo_orip_match = helper._extract_field(
            row,
            helper.ORIP_FIELDS,
            require_value=False,
        )

        if not codigo_orip_match:
            issues.append(
                RuleIssue(
                    rule_id="1.14",
                    object_ref=helper.identify(row),
                    message="Codigo_orip no existe en el registro.",
                    details={
                        "tabla": table_name,
                        "campo": "Codigo_orip",
                        "class": table_name,
                    },
                )
            )
            continue

        field_name, raw_value = codigo_orip_match
        codigo_orip_str = "" if raw_value in (None, "") else str(raw_value).strip()

        if not codigo_orip_str:
            issues.append(
                RuleIssue(
                    rule_id="1.14",
                    object_ref=helper.identify(row),
                    message="No se puede validar la regla 1.14 porque Codigo_orip no existe o está vacío.",
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                        "valor": raw_value,
                    },
                )
            )
            continue

        orip = "200"

        if codigo_orip_str != orip:
            issues.append(
                RuleIssue(
                    rule_id="1.14",
                    object_ref=helper.identify(row),
                    message="El Codigo_orip no coincide con el valor esperado.",
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                        "valor": raw_value,
                        "codigo_orip": codigo_orip_str,
                        "orip_esperado": orip,
                    },
                )
            )

    return issues


def _rule_1_15(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    construccion_tables = ("ARB_Construccion", "arb_construccion")
    unidad_tables = ("ARB_UnidadConstruccion", "arb_unidadconstruccion")

    destinacion_fields = (
        "destinacion_economica",
        "Destinacion_Economica",
        "destinacion",
        "Destinacion",
    )

    restricted_values = {
        "LOTE_URBANIZADO_NO_CONSTRUIDO",
        "LOTE_RURAL",
    }

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    predios_restringidos: dict[str, dict[str, object]] = {}
    construcciones_de_predios_restringidos: dict[str, dict[str, object]] = {}

    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            destinacion_match = helper._extract_field(
                row,
                destinacion_fields,
                require_value=False,
            )

            if not destinacion_match:
                continue

            field_name, raw_value = destinacion_match
            destinacion_str = "" if raw_value in (None, "") else str(raw_value).strip()

            if not destinacion_str:
                issues.append(
                    RuleIssue(
                        rule_id="1.15",
                        object_ref=helper.identify(row),
                        message="No se puede validar la regla 1.15 porque destinacion_economica no existe o está vacía.",
                        details={
                            "tabla": table_name,
                            "campo": field_name,
                            "class": table_name,
                            "valor": raw_value,
                        },
                    )
                )
                continue

            if _normalize_destinacion(destinacion_str) in restricted_values:
                predios_restringidos[predio_id] = {
                    "tabla": table_name,
                    "campo": field_name,
                    "class": table_name,
                    "destinacion_economica": destinacion_str,
                    "object_ref": helper.identify(row),
                }

    if not predios_restringidos:
        return issues

    for table_name in construccion_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            construccion_id = get_t_id(row)
            if not construccion_id:
                continue

            predio_fk = row.get("predio")
            if predio_fk in (None, ""):
                continue

            predio_fk_str = str(predio_fk).strip()
            if predio_fk_str in predios_restringidos:
                construcciones_de_predios_restringidos[construccion_id] = {
                    "predio_id": predio_fk_str,
                    "tabla": table_name,
                    "class": table_name,
                }

    if not construcciones_de_predios_restringidos:
        return issues

    for table_name in unidad_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            construccion_fk = row.get("construccion")
            if construccion_fk in (None, ""):
                continue

            construccion_fk_str = str(construccion_fk).strip()
            if construccion_fk_str not in construcciones_de_predios_restringidos:
                continue

            data_construccion = construcciones_de_predios_restringidos[construccion_fk_str]
            predio_id = data_construccion["predio_id"]
            predio_info = predios_restringidos[predio_id]

            issues.append(
                RuleIssue(
                    rule_id="1.15",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "Para predios con destinación económica "
                        "'Lote_Urbanizado_No_Construido' o 'Lote_Rural', "
                        "no se deben relacionar ni ubicar espacialmente unidades de construcción."
                    ),
                    details={
                        "tabla": table_name,
                        "campo": "construccion",
                        "class": table_name,
                        "predio_id": predio_id,
                        "construccion_id": construccion_fk_str,
                        "destinacion_economica": predio_info["destinacion_economica"],
                        "tabla_predio": predio_info["tabla"],
                        "tabla_construccion": data_construccion["tabla"],
                    },
                )
            )

    return issues



def _rule_1_16(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    construccion_tables = ("ARB_Construccion", "arb_construccion")
    unidad_tables = ("ARB_UnidadConstruccion", "arb_unidadconstruccion")

    destinacion_fields = (
        "destinacion_economica",
        "Destinacion_Economica",
        "destinacion",
        "Destinacion",
    )

    numero_predial_fields = (
        "Numero_Predial_Nacional",
        "numero_predial_nacional",
        "numero_predial",
        "Numero_Predial",
    )

    area_fields = (
        "area_catastral_terreno",
    )

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    def parse_float(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", ".").strip())
        except Exception:
            return None

    predios_lote_rural: dict[str, dict[str, object]] = {}
    construccion_to_predio: dict[str, str] = {}
    predios_con_unidades: set[str] = set()

    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            object_ref = helper.identify(row)

            destinacion_match = helper._extract_field(
                row,
                destinacion_fields,
                require_value=False,
            )
            if not destinacion_match:
                continue

            destinacion_field, destinacion_raw = destinacion_match
            destinacion_str = "" if destinacion_raw in (None, "") else str(destinacion_raw).strip()

            if not destinacion_str:
                issues.append(
                    RuleIssue(
                        rule_id="1.16",
                        object_ref=object_ref,
                        message="No se puede validar la regla 1.16 porque destinacion_economica no existe o está vacía.",
                        details={
                            "tabla": table_name,
                            "campo": destinacion_field,
                            "class": table_name,
                            "valor": destinacion_raw,
                        },
                    )
                )
                continue

            numero_match = helper._extract_field(
                row,
                numero_predial_fields,
                require_value=False,
            )
            if not numero_match:
                continue

            numero_field, numero_raw = numero_match
            numero_str = "" if numero_raw in (None, "") else str(numero_raw).strip()

            if not numero_str:
                continue

            area_match = helper._extract_field(
                row,
                area_fields,
                require_value=False,
            )
            area_field = area_match[0] if area_match else area_fields[0]
            area_raw = area_match[1] if area_match else None
            area_value = parse_float(area_raw)

            condicion_raw = helper.get_field_value(row, condicion_fields)
            condicion_norm = _normalize_condicion(condicion_raw) if condicion_raw else ""

            if area_value is not None and area_value < 500:
                if len(numero_str) >= 6 and numero_str[4:6] != "00":
                    issues.append(
                        RuleIssue(
                            rule_id="1.16",
                            object_ref=object_ref,
                            message=(
                                "Para predios con área menor a 500 m², los campos 5-6 del "
                                "Numero_Predial_Nacional deben ser '00'."
                            ),
                            details={
                                "tabla": table_name,
                                "campo": numero_field,
                                "class": table_name,
                                "valor": numero_raw,
                                "numero": numero_str,
                                "area": area_value,
                                "campo_5_6": numero_str[4:6],
                                "valor_esperado_5_6": "00",
                            },
                        )
                    )

            if _normalize_destinacion(destinacion_str) == "LOTE_RURAL":
                predios_lote_rural[predio_id] = {
                    "tabla": table_name,
                    "campo_destinacion": destinacion_field,
                    "campo_numero": numero_field,
                    "campo_area": area_field,
                    "class": table_name,
                    "object_ref": object_ref,
                    "destinacion_economica": destinacion_str,
                    "numero": numero_str,
                    "valor_numero": numero_raw,
                    "area": area_value,
                    "condicion_predio": condicion_raw,
                    "condicion_predio_norm": condicion_norm,
                }

    if not predios_lote_rural:
        return issues

    for predio_id, predio_info in predios_lote_rural.items():
        numero_str = str(predio_info["numero"])
        object_ref = predio_info["object_ref"]

        if len(numero_str) >= 6 and numero_str[4:6] != "00":
            issues.append(
                RuleIssue(
                    rule_id="1.16",
                    object_ref=object_ref,
                    message=(
                        "Los predios con destinación económica 'Lote_Rural' deben estar "
                        "relacionados a números prediales rurales; los campos 5-6 del "
                        "Numero_Predial_Nacional deben ser '00'."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo_numero"],
                        "class": predio_info["class"],
                        "valor": predio_info["valor_numero"],
                        "numero": numero_str,
                        "destinacion_economica": predio_info["destinacion_economica"],
                        "valor_encontrado_5_6": numero_str[4:6],
                        "valor_esperado_5_6": "00",
                    },
                )
            )

        if len(numero_str) > 21:
            valor_22 = numero_str[21]
            if valor_22 in {"8", "9"}:
                issues.append(
                    RuleIssue(
                        rule_id="1.16",
                        object_ref=object_ref,
                        message=(
                            "Los predios con destinación económica 'Lote_Rural' no deben "
                            "ubicar espacialmente unidades de construcción; la posición 22 "
                            "del Numero_Predial_Nacional no puede ser '8' ni '9'."
                        ),
                        details={
                            "tabla": predio_info["tabla"],
                            "campo": predio_info["campo_numero"],
                            "class": predio_info["class"],
                            "valor": predio_info["valor_numero"],
                            "numero": numero_str,
                            "destinacion_economica": predio_info["destinacion_economica"],
                            "valor_encontrado_22": valor_22,
                            "valores_no_permitidos_22": ["8", "9"],
                        },
                    )
                )

        if predio_info["condicion_predio_norm"] in {
            "PH_MATRIZ",
            "PH_UNIDAD_PREDIAL",
            "CONDOMINIO_MATRIZ",
            "CONDOMINIO_UNIDAD_PREDIAL",
        }:
            issues.append(
                RuleIssue(
                    rule_id="1.16",
                    object_ref=object_ref,
                    message=(
                        "Los predios con destinación económica 'Lote_Rural' no deben "
                        "relacionar condición de PH o condominio."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": "condicion_predio",
                        "class": predio_info["class"],
                        "numero": numero_str,
                        "destinacion_economica": predio_info["destinacion_economica"],
                        "condicion_predio": predio_info["condicion_predio"],
                    },
                )
            )

    for table_name in construccion_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            construccion_id = get_t_id(row)
            if not construccion_id:
                continue

            predio_fk = row.get("predio")
            if predio_fk in (None, ""):
                continue

            predio_fk_str = str(predio_fk).strip()
            if predio_fk_str in predios_lote_rural:
                construccion_to_predio[construccion_id] = predio_fk_str

    if not construccion_to_predio:
        return issues

    for table_name in unidad_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            construccion_fk = row.get("construccion")
            if construccion_fk in (None, ""):
                continue

            construccion_fk_str = str(construccion_fk).strip()
            predio_id = construccion_to_predio.get(construccion_fk_str)
            if predio_id:
                predios_con_unidades.add(predio_id)

    for predio_id in predios_con_unidades:
        predio_info = predios_lote_rural[predio_id]
        issues.append(
            RuleIssue(
                rule_id="1.16",
                object_ref=predio_info["object_ref"],
                message=(
                    "Los predios con destinación económica 'Lote_Rural' no deben "
                    "tener unidades de construcción relacionadas."
                ),
                details={
                    "tabla": predio_info["tabla"],
                    "campo": "construccion",
                    "class": predio_info["class"],
                    "predio_id": predio_id,
                    "numero": predio_info["numero"],
                    "destinacion_economica": predio_info["destinacion_economica"],
                },
            )
        )

    return issues


def _rule_1_17(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    construccion_tables = ("ARB_Construccion", "arb_construccion")

    destinacion_fields = (
        "destinacion_economica",
        "Destinacion_Economica",
        "destinacion",
        "Destinacion",
    )

    required_values = {
        "COMERCIAL",
        "EDUCATIVO",
        "HABITACIONAL",
        "INDUSTRIAL",
        "INSTITUCIONAL",
        "SALUBRIDAD",
    }

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    predios_requeridos: dict[str, dict[str, object]] = {}
    predios_con_construccion: set[str] = set()

    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            destinacion_match = helper._extract_field(
                row,
                destinacion_fields,
                require_value=False,
            )
            if not destinacion_match:
                continue

            field_name, raw_value = destinacion_match
            destinacion_str = "" if raw_value in (None, "") else str(raw_value).strip()

            if not destinacion_str:
                issues.append(
                    RuleIssue(
                        rule_id="1.17",
                        object_ref=helper.identify(row),
                        message="No se puede validar la regla 1.17 porque destinacion_economica no existe o está vacía.",
                        details={
                            "tabla": table_name,
                            "campo": field_name,
                            "class": table_name,
                            "valor": raw_value,
                        },
                    )
                )
                continue

            destinacion_norm = _normalize_destinacion(destinacion_str)

            if destinacion_norm in required_values:
                predios_requeridos[predio_id] = {
                    "tabla": table_name,
                    "campo": field_name,
                    "class": table_name,
                    "object_ref": helper.identify(row),
                    "destinacion_economica": destinacion_str,
                }

    if not predios_requeridos:
        return issues

    for table_name in construccion_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_fk = row.get("predio")
            if predio_fk in (None, ""):
                continue

            predio_fk_str = str(predio_fk).strip()
            if predio_fk_str in predios_requeridos:
                predios_con_construccion.add(predio_fk_str)

    for predio_id, predio_info in predios_requeridos.items():
        if predio_id in predios_con_construccion:
            continue

        issues.append(
            RuleIssue(
                rule_id="1.17",
                object_ref=predio_info["object_ref"],
                message=(
                    "Los predios con destinación económica 'Comercial', 'Educativo', "
                    "'Habitacional', 'Industrial', 'Institucional' o 'Salubridad' "
                    "deben tener relacionada al menos una construcción."
                ),
                details={
                    "tabla": predio_info["tabla"],
                    "campo": predio_info["campo"],
                    "class": predio_info["class"],
                    "predio_id": predio_id,
                    "destinacion_economica": predio_info["destinacion_economica"],
                },
            )
        )

    return issues


def _rule_1_18(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    area_registral_fields = (
        "area_registral_m2",
        "Area_Registral_M2",
        "area_registral",
        "Area_Registral",
    )

    for table_name, row in helper.iter_predios():
        area_match = helper._extract_field(
            row,
            area_registral_fields,
            require_value=False,
        )

        if not area_match:
            continue

        area_field, area_raw = area_match
        area_str = "" if area_raw in (None, "") else str(area_raw).strip()

        if not area_str:
            continue

        try:
            area_value = float(area_str.replace(",", "."))
        except Exception:
            issues.append(
                RuleIssue(
                    rule_id="1.18",
                    object_ref=helper.identify(row),
                    message="El campo Area_Registral_M2 debe ser numérico para validar la regla 1.18.",
                    details={
                        "tabla": table_name,
                        "campo": area_field,
                        "class": table_name,
                        "valor": area_raw,
                    },
                )
            )
            continue

        codigo_orip_match = helper._extract_field(
            row,
            helper.ORIP_FIELDS,
            require_value=False,
        )
        matricula_match = helper._extract_field(
            row,
            helper.MATRICULA_FIELDS,
            require_value=False,
        )

        codigo_orip_field = codigo_orip_match[0] if codigo_orip_match else helper.ORIP_FIELDS[0]
        codigo_orip_raw = codigo_orip_match[1] if codigo_orip_match else None
        codigo_orip_str = "" if codigo_orip_raw in (None, "") else str(codigo_orip_raw).strip()

        matricula_field = matricula_match[0] if matricula_match else helper.MATRICULA_FIELDS[0]
        matricula_raw = matricula_match[1] if matricula_match else None
        matricula_str = "" if matricula_raw in (None, "") else str(matricula_raw).strip()

        orip_vacio = not codigo_orip_str
        matricula_vacia = not matricula_str

        if area_value > 0 and (orip_vacio or matricula_vacia):
            issues.append(
                RuleIssue(
                    rule_id="1.18",
                    object_ref=helper.identify(row),
                    message=(
                        "Si Area_Registral_M2 es mayor a cero, los campos "
                        "Codigo_ORIP y Matricula_Inmobiliaria deben estar diligenciados."
                    ),
                    details={
                        "tabla": table_name,
                        "campo": area_field,
                        "class": table_name,
                        "valor": area_raw,
                        "area_registral_m2": area_value,
                        "codigo_orip": codigo_orip_raw,
                        "matricula_inmobiliaria": matricula_raw,
                        "campo_codigo_orip": codigo_orip_field,
                        "campo_matricula_inmobiliaria": matricula_field,
                    },
                )
            )

    return issues


def _rule_1_19(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    tipo_novedad_fields = (
        "tipo_novedad",
        "Tipo_Novedad",
        "novedad",
        "Novedad",
    )

    terreno_predio_fk_fields = (
        "predio",
        "arb_predio",
        "arb_predio_terreno",
        "terreno_predio",
        "predio_asociado",
        "id_predio",
        "Id_Predio",
        "ARB_terreno_predio_ARB_predio_T_Id",
    )

    novedad_predio_fk_fields = (
        "arb_predio_novedad_numero_predial",
        "predio",
        "arb_predio",
        "predio_asociado",
        "id_predio",
        "Id_Predio",
        "id_operacion",
        "Id_Operacion",
        "ARB_predio_novedad_numero_predial",
    )

    required_conditions = {
        "NPH",
        "PH_MATRIZ",
        "CONDOMINIO_MATRIZ",
        "CONDOMINIO_UNIDAD_PREDIAL",
        "VIA",
        "BIEN_USO_PUBLICO",
        "PARQUE_CEMENTERIO_UNIDAD_PREDIAL",
        "PARQUE_CEMENTERIO_MATRIZ",
    }

    cancelation_values = {
        "CANCELACION",
        "CANCELACION_POR_DESENGLOBE",
        "CANCELACION_POR_ENGLOBE",
    }

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    def normalize_relation_key(value: object) -> str:
        text = str(value).strip().lower()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        return re.sub(r"[^a-z0-9]", "", text)

    def field_value(row: dict[str, object], candidates: tuple[str, ...]) -> object | None:
        match = helper._extract_field(row, candidates, require_value=False)
        if not match:
            return None
        value = match[1]
        if value in (None, ""):
            return None
        return value

    def add_predio_alias(alias: object, predio_id: str) -> None:
        if alias in (None, ""):
            return
        alias_text = str(alias).strip()
        if not alias_text:
            return

        alias_values = {alias_text}
        if alias_text.endswith(".0"):
            alias_values.add(alias_text[:-2])

        alias_norm = normalize_relation_key(alias_text)
        if alias_norm:
            alias_values.add(alias_norm)

        for value in alias_values:
            predio_key_aliases.setdefault(value, predio_id)

    def get_predio_keys(row: dict[str, object]) -> set[str]:
        keys: set[str] = set()
        for field in (
            "T_Id",
            "t_id",
            "TID",
            "tid",
            "id_operacion",
            "Id_Operacion",
            "ID_OPERACION",
            "numero_predial",
            "Numero_Predial",
            "Numero_Predial_Nacional",
            "numero_predial_nacional",
        ):
            value = row.get(field)
            if value not in (None, ""):
                keys.add(str(value).strip())
        object_ref = helper.identify(row)
        if object_ref:
            keys.add(str(object_ref).strip())
        return keys

    def resolve_predio_alias(value: object) -> str | None:
        if value in (None, ""):
            return None
        value_text = str(value).strip()
        if not value_text:
            return None

        if value_text in predio_key_aliases:
            return predio_key_aliases[value_text]

        value_norm = normalize_relation_key(value_text)
        if value_norm in predio_key_aliases:
            return predio_key_aliases[value_norm]

        candidates: set[str] = set()
        for token in re.findall(r"\d+", value_text):
            if token in predio_key_aliases:
                candidates.add(predio_key_aliases[token])
        if len(candidates) == 1:
            return next(iter(candidates))

        return value_text

    predios_validos: dict[str, dict[str, object]] = {}
    predios_invalidos: dict[str, dict[str, object]] = {}
    predio_key_aliases: dict[str, str] = {}
    predios_con_cancelacion: set[str] = set()
    terrenos_por_predio: dict[str, list[dict[str, object]]] = {}
    total_terrenos_leidos = 0
    terrenos_con_predio = 0

    for table_name, row in helper.iter_predios():
        predio_id = get_t_id(row)
        if not predio_id:
            continue

        condicion_match = helper._extract_field(
            row,
            condicion_fields,
            require_value=False,
        )
        if not condicion_match:
            continue

        condicion_field, condicion_raw = condicion_match
        condicion_str = "" if condicion_raw in (None, "") else str(condicion_raw).strip()
        if not condicion_str:
            continue

        condicion_norm = _normalize_condicion(condicion_str)

        info = {
            "tabla": table_name,
            "campo": condicion_field,
            "class": table_name,
            "object_ref": helper.identify(row),
            "condicion_predio": condicion_str,
            "condicion_predio_norm": condicion_norm,
            "keys": get_predio_keys(row),
        }

        if condicion_norm in required_conditions:
            predios_validos[predio_id] = info
        else:
            predios_invalidos[predio_id] = info

        add_predio_alias(predio_id, predio_id)
        for key in info["keys"]:
            add_predio_alias(key, predio_id)

    if not predios_validos and not predios_invalidos:
        return issues

    for table_name, row in helper.iter_novedades():
        predio_fk = field_value(row, novedad_predio_fk_fields)
        predio_id = resolve_predio_alias(predio_fk)
        if not predio_id:
            continue

        novedad_match = helper._extract_field(
            row,
            tipo_novedad_fields,
            require_value=False,
        )
        if not novedad_match:
            continue

        _, novedad_raw = novedad_match
        novedad_str = "" if novedad_raw in (None, "") else str(novedad_raw).strip()
        if not novedad_str:
            continue

        if _normalize_novedad(novedad_str) in cancelation_values:
            predios_con_cancelacion.add(predio_id)

    for table_name, row in helper.iter_terrenos():
        total_terrenos_leidos += 1
        predio_fk = field_value(row, terreno_predio_fk_fields)
        predio_id = resolve_predio_alias(predio_fk)
        if not predio_id:
            continue

        terrenos_con_predio += 1
        terrenos_por_predio.setdefault(predio_id, []).append(
            {
                "tabla": table_name,
                "campo": "predio",
                "class": table_name,
                "object_ref": helper.identify(row),
            }
        )

    if total_terrenos_leidos == 0 or terrenos_con_predio == 0:
        return issues

    for predio_id, predio_info in predios_validos.items():
        if predio_id in predios_con_cancelacion:
            continue

        terrenos = terrenos_por_predio.get(predio_id, [])
        if len(terrenos) != 1:
            issues.append(
                RuleIssue(
                    rule_id="1.19",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "Un predio con este tipo de condición del predio solo puede "
                        "tener asociado un terreno."
                    ),
                    details={
                        "tipo_error_presentado": "FDC-R5019-E01",
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "condicion_predio": predio_info["condicion_predio"],
                        "numero_terrenos_asociados": len(terrenos),
                    },
                )
            )

    for predio_id, predio_info in predios_invalidos.items():
        if predio_id in predios_con_cancelacion:
            continue

        terrenos = terrenos_por_predio.get(predio_id, [])
        if len(terrenos) > 0:
            issues.append(
                RuleIssue(
                    rule_id="1.19",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "Un predio con este tipo de condición del predio no puede "
                        "tener asociado ningún terreno."
                    ),
                    details={
                        "tipo_error_presentado": "FDC-R5019-E02",
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "condicion_predio": predio_info["condicion_predio"],
                        "numero_terrenos_asociados": len(terrenos),
                    },
                )
            )

    return issues

def _rule_1_20(dataset: DatasetReader) -> list[RuleIssue]:
    # sin definir falta capa predio_copropiedad
    return []

def _rule_1_21(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    informacion_ph_tables = ("ARB_InformacionPH", "arb_informacionph")

    numero_predial_fields = (
        "Numero_Predial_Nacional",
        "numero_predial_nacional",
        "numero_predial",
        "Numero_Predial",
    )

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    area_coeficiente_fields = (
        "Area_Coeficiente_Copropiedad",
        "area_coeficiente_copropiedad",
    )

    area_total_terreno_fields = (
        "Area_Total_Terreno",
        "area_total_terreno",
    )

    matrix_conditions = {
        "PH_MATRIZ",
        "CONDOMINIO_MATRIZ",
    }

    unit_conditions = {
        "PH_UNIDAD_PREDIAL",
        "CONDOMINIO_UNIDAD_PREDIAL",
    }

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    def parse_float(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", ".").strip())
        except Exception:
            return None

    predios_matriz: dict[str, dict[str, object]] = {}
    suma_areas_unidades: dict[str, float] = {}
    informacion_ph_por_predio: dict[str, dict[str, object]] = {}

    # 1. Leer ARB_InformacionPH
    for table_name in informacion_ph_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_fk = row.get("arb_predio")
            if predio_fk in (None, ""):
                continue

            predio_id = str(predio_fk).strip()

            area_match = helper._extract_field(
                row,
                area_total_terreno_fields,
                require_value=False,
            )
            area_field = area_match[0] if area_match else area_total_terreno_fields[0]
            area_raw = area_match[1] if area_match else None
            area_value = parse_float(area_raw)

            informacion_ph_por_predio[predio_id] = {
                "tabla": table_name,
                "campo": area_field,
                "class": table_name,
                "valor": area_raw,
                "area_total_terreno": area_value,
                "object_ref": helper.identify(row),
            }

    # 2. Leer predios matriz y unidades
    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            object_ref = helper.identify(row)

            condicion_match = helper._extract_field(
                row,
                condicion_fields,
                require_value=False,
            )
            if not condicion_match:
                continue

            condicion_field, condicion_raw = condicion_match
            condicion_str = "" if condicion_raw in (None, "") else str(condicion_raw).strip()
            if not condicion_str:
                issues.append(
                    RuleIssue(
                        rule_id="1.21",
                        object_ref=object_ref,
                        message="No se puede validar la regla 1.21 porque condicion_predio no existe o está vacía.",
                        details={
                            "tabla": table_name,
                            "campo": condicion_field,
                            "class": table_name,
                            "valor": condicion_raw,
                        },
                    )
                )
                continue

            condicion_norm = _normalize_condicion(condicion_str)

            numero_match = helper._extract_field(
                row,
                numero_predial_fields,
                require_value=False,
            )
            if not numero_match:
                continue

            numero_field, numero_raw = numero_match
            numero_str = "" if numero_raw in (None, "") else str(numero_raw).strip()
            if not numero_str:
                continue

            numero_base = numero_str[:22]

            if condicion_norm in matrix_conditions:
                predios_matriz[predio_id] = {
                    "tabla": table_name,
                    "campo": numero_field,
                    "class": table_name,
                    "object_ref": object_ref,
                    "predio_id": predio_id,
                    "numero_predial": numero_str,
                    "numero_base_22": numero_base,
                    "condicion_predio": condicion_str,
                }

            elif condicion_norm in unit_conditions:
                area_match = helper._extract_field(
                    row,
                    area_coeficiente_fields,
                    require_value=False,
                )
                area_field = area_match[0] if area_match else area_coeficiente_fields[0]
                area_raw = area_match[1] if area_match else None
                area_value = parse_float(area_raw)

                if area_value is None:
                    issues.append(
                        RuleIssue(
                            rule_id="1.21",
                            object_ref=object_ref,
                            message=(
                                "No se puede validar la regla 1.21 porque "
                                "Area_Coeficiente_Copropiedad no existe o está vacía "
                                "en una unidad predial."
                            ),
                            details={
                                "tabla": table_name,
                                "campo": area_field,
                                "class": table_name,
                                "valor": area_raw,
                                "numero": numero_str,
                                "condicion_predio": condicion_str,
                            },
                        )
                    )
                    continue

                suma_areas_unidades[numero_base] = round(
                    suma_areas_unidades.get(numero_base, 0.0) + area_value,
                    2,
                )

    if not predios_matriz:
        return issues

    # 3. Comparar área de matriz vs suma de áreas de coeficiente
    for predio_id, predio_info in predios_matriz.items():
        numero_base = str(predio_info["numero_base_22"])
        info_ph = informacion_ph_por_predio.get(predio_id)

        if not info_ph:
            issues.append(
                RuleIssue(
                    rule_id="1.21",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.21 porque el predio matriz "
                        "no tiene registro en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                    },
                )
            )
            continue

        area_matriz = info_ph["area_total_terreno"]
        if area_matriz is None:
            issues.append(
                RuleIssue(
                    rule_id="1.21",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.21 porque Area_Total_Terreno "
                        "no existe o está vacía en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": info_ph["tabla"],
                        "campo": info_ph["campo"],
                        "class": info_ph["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                        "valor": info_ph["valor"],
                    },
                )
            )
            continue

        area_unidades = round(suma_areas_unidades.get(numero_base, 0.0), 2)
        area_matriz_redondeada = round(float(area_matriz), 2)

        if area_matriz_redondeada != area_unidades:
            issues.append(
                RuleIssue(
                    rule_id="1.21",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "La sumatoria de las áreas de coeficiente debe ser igual "
                        "al área de terreno del predio matriz donde se ubican."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial_matriz": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                        "area_terreno_matriz": area_matriz_redondeada,
                        "suma_areas_coeficiente": area_unidades,
                        "numero_base_22": numero_base,
                    },
                )
            )

    return issues

def _rule_1_22(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    informacion_ph_tables = ("ARB_InformacionPH", "arb_informacionph")

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    required_conditions = {
        "PH_MATRIZ",
        "CONDOMINIO_MATRIZ",
    }

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    predios: dict[str, dict[str, object]] = {}
    predios_con_informacion_ph: dict[str, list[dict[str, object]]] = {}

    # 1. Leer predios y su condición
    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            condicion_match = helper._extract_field(
                row,
                condicion_fields,
                require_value=False,
            )
            if not condicion_match:
                continue

            condicion_field, condicion_raw = condicion_match
            condicion_str = "" if condicion_raw in (None, "") else str(condicion_raw).strip()

            if not condicion_str:
                issues.append(
                    RuleIssue(
                        rule_id="1.22",
                        object_ref=helper.identify(row),
                        message="No se puede validar la regla 1.22 porque condicion_predio no existe o está vacía.",
                        details={
                            "tabla": table_name,
                            "campo": condicion_field,
                            "class": table_name,
                            "valor": condicion_raw,
                        },
                    )
                )
                continue

            predios[predio_id] = {
                "tabla": table_name,
                "campo": condicion_field,
                "class": table_name,
                "object_ref": helper.identify(row),
                "condicion_predio": condicion_str,
                "condicion_predio_norm": _normalize_condicion(condicion_str),
            }

    if not predios:
        return issues

    # 2. Buscar registros relacionados en ARB_InformacionPH
    for table_name in informacion_ph_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_fk = row.get("arb_predio")
            if predio_fk in (None, ""):
                continue

            predio_id = str(predio_fk).strip()
            predios_con_informacion_ph.setdefault(predio_id, []).append(
                {
                    "tabla": table_name,
                    "campo": "arb_predio",
                    "class": table_name,
                    "object_ref": helper.identify(row),
                }
            )

    # 3. Validar obligación / prohibición de registro en ARB_InformacionPH
    for predio_id, predio_info in predios.items():
        condicion_norm = predio_info["condicion_predio_norm"]
        registros_ph = predios_con_informacion_ph.get(predio_id, [])

        if condicion_norm in required_conditions:
            if not registros_ph:
                issues.append(
                    RuleIssue(
                        rule_id="1.22",
                        object_ref=predio_info["object_ref"],
                        message=(
                            "Solo los predios con condición PH.Matriz o Condominio.Matriz "
                            "deben tener un registro en la tabla ARB_InformacionPH. "
                            "El predio no tiene registro relacionado."
                        ),
                        details={
                            "tabla": predio_info["tabla"],
                            "campo": predio_info["campo"],
                            "class": predio_info["class"],
                            "predio_id": predio_id,
                            "condicion_predio": predio_info["condicion_predio"],
                        },
                    )
                )
        else:
            if registros_ph:
                issues.append(
                    RuleIssue(
                        rule_id="1.22",
                        object_ref=predio_info["object_ref"],
                        message=(
                            "Solo los predios con condición PH.Matriz o Condominio.Matriz "
                            "deben tener un registro en la tabla ARB_InformacionPH. "
                            "El predio presenta un registro relacionado y no debería."
                        ),
                        details={
                            "tabla": predio_info["tabla"],
                            "campo": predio_info["campo"],
                            "class": predio_info["class"],
                            "predio_id": predio_id,
                            "condicion_predio": predio_info["condicion_predio"],
                            "total_registros_informacion_ph": len(registros_ph),
                        },
                    )
                )

    return issues

def _rule_1_23(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    predio_matriz_fields = (
        "predio_matriz",
        "Predio_Matriz",
    )

    numero_predial_fields = (
        "Numero_Predial_Nacional",
        "numero_predial",
        "Numero_Predial",
    )

    matrix_conditions = {
        "PH_MATRIZ",
        "CONDOMINIO_MATRIZ",
    }

    unit_conditions = {
        "PH_UNIDAD_PREDIAL",
        "CONDOMINIO_UNIDAD_PREDIAL",
    }

    def get_t_id(row):
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    predios_matriz = {}
    conteo_unidades = {}

    # 1. recorrer predios
    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            object_ref = helper.identify(row)

            condicion = helper.get_field_value(row, condicion_fields)
            condicion_norm = _normalize_condicion(condicion) if condicion else ""

            numero = helper.get_field_value(row, numero_predial_fields)

            predio_matriz = helper.get_field_value(row, predio_matriz_fields)

            # guardar matrices
            if condicion_norm in matrix_conditions:
                predios_matriz[predio_id] = {
                    "tabla": table_name,
                    "class": table_name,
                    "object_ref": object_ref,
                    "numero": numero,
                    "condicion": condicion,
                }

            # contar solo UNIDADES
            if condicion_norm in unit_conditions and predio_matriz:
                conteo_unidades[predio_matriz] = (
                    conteo_unidades.get(predio_matriz, 0) + 1
                )

    # 2. validar
    for predio_id, info in predios_matriz.items():
        total = conteo_unidades.get(predio_id, 0)

        if total == 1:
            issues.append(
                RuleIssue(
                    rule_id="1.23",
                    object_ref=info["object_ref"],
                    message=(
                        "Una única unidad predial no puede constituir un PH o Condominio. "
                        "El predio matriz debe tener más de una unidad predial asociada."
                    ),
                    details={
                        "tabla": info["tabla"],
                        "class": info["class"],
                        "predio_id": predio_id,
                        "numero_predial": info["numero"],
                        "condicion_predio": info["condicion"],
                        "total_unidades_asociadas": total,
                    },
                )
            )

    return issues

def _rule_1_24(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    predio_matriz_fields = (
        "predio_matriz",
        "Predio_Matriz",
    )

    numero_predial_fields = (
        "Numero_Predial_Nacional",
        "numero_predial_nacional",
        "numero_predial",
        "Numero_Predial",
    )

    unit_conditions = {
        "PH_UNIDAD_PREDIAL",
        "CONDOMINIO_UNIDAD_PREDIAL",
    }

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            object_ref = helper.identify(row)

            condicion_match = helper._extract_field(
                row,
                condicion_fields,
                require_value=False,
            )
            if not condicion_match:
                continue

            condicion_field, condicion_raw = condicion_match
            condicion_str = "" if condicion_raw in (None, "") else str(condicion_raw).strip()

            if not condicion_str:
                issues.append(
                    RuleIssue(
                        rule_id="1.24",
                        object_ref=object_ref,
                        message="No se puede validar la regla 1.24 porque condicion_predio no existe o está vacía.",
                        details={
                            "tabla": table_name,
                            "campo": condicion_field,
                            "class": table_name,
                            "valor": condicion_raw,
                        },
                    )
                )
                continue

            condicion_norm = _normalize_condicion(condicion_str)
            if condicion_norm not in unit_conditions:
                continue

            numero_match = helper._extract_field(
                row,
                numero_predial_fields,
                require_value=False,
            )
            numero_field = numero_match[0] if numero_match else numero_predial_fields[0]
            numero_raw = numero_match[1] if numero_match else None
            numero_str = "" if numero_raw in (None, "") else str(numero_raw).strip()

            matriz_match = helper._extract_field(
                row,
                predio_matriz_fields,
                require_value=False,
            )

            if not matriz_match:
                issues.append(
                    RuleIssue(
                        rule_id="1.24",
                        object_ref=object_ref,
                        message=(
                            "El predio con condición de unidad predial PH o Condominio "
                            "no tiene relacionado un predio matriz."
                        ),
                        details={
                            "tabla": table_name,
                            "campo": predio_matriz_fields[0],
                            "class": table_name,
                            "predio_id": predio_id,
                            "numero_predial": numero_str,
                            "condicion_predio": condicion_str,
                        },
                    )
                )
                continue

            matriz_field, matriz_raw = matriz_match
            predio_matriz = "" if matriz_raw in (None, "") else str(matriz_raw).strip()

            if not predio_matriz:
                issues.append(
                    RuleIssue(
                        rule_id="1.24",
                        object_ref=object_ref,
                        message=(
                            "El predio con condición de unidad predial PH o Condominio "
                            "no tiene relacionado un predio matriz."
                        ),
                        details={
                            "tabla": table_name,
                            "campo": matriz_field,
                            "class": table_name,
                            "predio_id": predio_id,
                            "numero_predial": numero_str,
                            "condicion_predio": condicion_str,
                            "predio_matriz": matriz_raw,
                        },
                    )
                )

    return issues

def _rule_1_25(dataset: DatasetReader) -> list[RuleIssue]:
    # sin definir falta campo area_geografica en  capa terreno
    return []

def _rule_1_26(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    informacion_ph_tables = ("ARB_InformacionPH", "arb_informacionph")
    construccion_tables = ("ARB_Construccion", "arb_construccion")
    unidad_tables = ("ARB_UnidadConstruccion", "arb_unidadconstruccion")
    caracteristicas_tables = (
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )

    numero_predial_fields = (
        "Numero_Predial_Nacional",
        "numero_predial_nacional",
        "numero_predial",
        "Numero_Predial",
    )

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    predio_matriz_fields = (
        "predio_matriz",
        "Predio_Matriz",
    )

    area_total_construida_fields = (
        "Area_Total_Construida",
        "area_total_construida",
    )

    area_construida_fields = (
        "Area_Construida",
        "area_construida",
    )

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    def parse_float(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", ".").strip())
        except Exception:
            return None

    predios_matriz: dict[str, dict[str, object]] = {}
    predios_unidad_ph: dict[str, dict[str, object]] = {}
    info_ph_por_predio: dict[str, dict[str, object]] = {}

    construccion_a_predio: dict[str, str] = {}
    area_construida_por_caracteristicas: dict[str, float] = {}

    suma_area_por_matriz: dict[str, float] = {}

    # 1. Leer ARB_InformacionPH
    for table_name in informacion_ph_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_fk = row.get("arb_predio")
            if predio_fk in (None, ""):
                continue

            predio_id = str(predio_fk).strip()

            area_match = helper._extract_field(
                row,
                area_total_construida_fields,
                require_value=False,
            )
            area_field = area_match[0] if area_match else area_total_construida_fields[0]
            area_raw = area_match[1] if area_match else None
            area_value = parse_float(area_raw)

            info_ph_por_predio[predio_id] = {
                "tabla": table_name,
                "campo": area_field,
                "class": table_name,
                "valor": area_raw,
                "area_total_construida": area_value,
                "object_ref": helper.identify(row),
            }

    # 2. Leer predios matriz PH y unidades PH
    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            object_ref = helper.identify(row)

            condicion_match = helper._extract_field(
                row,
                condicion_fields,
                require_value=False,
            )
            if not condicion_match:
                continue

            condicion_field, condicion_raw = condicion_match
            condicion_str = "" if condicion_raw in (None, "") else str(condicion_raw).strip()
            if not condicion_str:
                continue

            condicion_norm = _normalize_condicion(condicion_str)

            numero_match = helper._extract_field(
                row,
                numero_predial_fields,
                require_value=False,
            )
            if not numero_match:
                continue

            numero_field, numero_raw = numero_match
            numero_str = "" if numero_raw in (None, "") else str(numero_raw).strip()
            if not numero_str:
                continue

            sufijo_22_30 = numero_str[21:30] if len(numero_str) >= 30 else ""

            matriz_match = helper._extract_field(
                row,
                predio_matriz_fields,
                require_value=False,
            )
            matriz_raw = matriz_match[1] if matriz_match else None
            predio_matriz = "" if matriz_raw in (None, "") else str(matriz_raw).strip()

            if condicion_norm == "PH_MATRIZ" and sufijo_22_30 == "900000000":
                predios_matriz[predio_id] = {
                    "tabla": table_name,
                    "campo": numero_field,
                    "class": table_name,
                    "object_ref": object_ref,
                    "predio_id": predio_id,
                    "numero_predial": numero_str,
                    "condicion_predio": condicion_str,
                }

            elif condicion_norm == "PH_UNIDAD_PREDIAL":
                predios_unidad_ph[predio_id] = {
                    "tabla": table_name,
                    "class": table_name,
                    "object_ref": object_ref,
                    "predio_id": predio_id,
                    "numero_predial": numero_str,
                    "predio_matriz": predio_matriz,
                    "condicion_predio": condicion_str,
                }

    if not predios_matriz:
        return issues

    # 3. Construcción -> predio
    for table_name in construccion_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            construccion_id = get_t_id(row)
            if not construccion_id:
                continue

            predio_fk = row.get("predio")
            if predio_fk in (None, ""):
                continue

            construccion_a_predio[construccion_id] = str(predio_fk).strip()

    # 4. Características -> área construida
    for table_name in caracteristicas_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            caracteristicas_id = get_t_id(row)
            if not caracteristicas_id:
                continue

            area_match = helper._extract_field(
                row,
                area_construida_fields,
                require_value=False,
            )
            if not area_match:
                continue

            _, area_raw = area_match
            area_value = parse_float(area_raw)
            if area_value is None:
                continue

            area_construida_por_caracteristicas[caracteristicas_id] = area_value

    # 5. Recorrer unidades de construcción y acumular área a la matriz
    for table_name in unidad_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            construccion_fk = row.get("construccion")
            if construccion_fk in (None, ""):
                continue

            caracteristicas_fk = row.get("caracteristicasunidadconstruccion")
            if caracteristicas_fk in (None, ""):
                continue

            construccion_id = str(construccion_fk).strip()
            caracteristicas_id = str(caracteristicas_fk).strip()

            predio_id = construccion_a_predio.get(construccion_id)
            if not predio_id:
                continue

            area_uc = area_construida_por_caracteristicas.get(caracteristicas_id)
            if area_uc is None:
                continue

            # UC asociada directamente al predio matriz
            if predio_id in predios_matriz:
                suma_area_por_matriz[predio_id] = round(
                    suma_area_por_matriz.get(predio_id, 0.0) + area_uc,
                    1,
                )
                continue

            # UC asociada a unidad predial PH; sumar a su matriz
            unidad_info = predios_unidad_ph.get(predio_id)
            if unidad_info:
                matriz_id = unidad_info["predio_matriz"]
                if matriz_id:
                    suma_area_por_matriz[matriz_id] = round(
                        suma_area_por_matriz.get(matriz_id, 0.0) + area_uc,
                        1,
                    )

    # 6. Comparar área del matriz vs suma de áreas construidas
    for predio_id, predio_info in predios_matriz.items():
        info_ph = info_ph_por_predio.get(predio_id)

        if not info_ph:
            issues.append(
                RuleIssue(
                    rule_id="1.26",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.26 porque el predio matriz "
                        "no tiene registro en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                    },
                )
            )
            continue

        area_matriz = info_ph["area_total_construida"]
        if area_matriz is None:
            issues.append(
                RuleIssue(
                    rule_id="1.26",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.26 porque area_total_construida "
                        "no existe o está vacía en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": info_ph["tabla"],
                        "campo": info_ph["campo"],
                        "class": info_ph["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "valor": info_ph["valor"],
                    },
                )
            )
            continue

        area_matriz_redondeada = round(float(area_matriz), 1)
        area_total_unidad = round(suma_area_por_matriz.get(predio_id, 0.0), 1)

        if area_matriz_redondeada != area_total_unidad:
            issues.append(
                RuleIssue(
                    rule_id="1.26",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "En la tabla datos de PH o condominio, para los predios con "
                        "condición PH.Matriz, el área total construida debe ser la "
                        "sumatoria de las áreas de las unidades de construcción "
                        "asociadas a las unidades prediales y de las unidades de "
                        "construcción asociadas al predio matriz."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial_matriz": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                        "area_total_construida_matriz": area_matriz_redondeada,
                        "suma_areas_unidades_construccion": area_total_unidad,
                    },
                )
            )

    return issues

def _rule_1_27(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    informacion_ph_tables = ("ARB_InformacionPH", "arb_informacionph")
    construccion_tables = ("ARB_Construccion", "arb_construccion")
    unidad_tables = ("ARB_UnidadConstruccion", "arb_unidadconstruccion")
    caracteristicas_tables = (
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )

    numero_predial_fields = (
        "Numero_Predial_Nacional",
        "numero_predial_nacional",
        "numero_predial",
        "Numero_Predial",
    )

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    predio_matriz_fields = (
        "predio_matriz",
        "Predio_Matriz",
    )

    area_total_construida_privada_fields = (
        "Area_Total_Construida_Privada",
        "area_total_construida_privada",
    )

    area_construida_fields = (
        "Area_Construida",
        "area_construida",
    )

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    def parse_float(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", ".").strip())
        except Exception:
            return None

    predios_matriz: dict[str, dict[str, object]] = {}
    predios_unidad_ph: dict[str, dict[str, object]] = {}
    info_ph_por_predio: dict[str, dict[str, object]] = {}

    construccion_a_predio: dict[str, str] = {}
    area_construida_por_caracteristicas: dict[str, float] = {}

    suma_area_privada_por_matriz: dict[str, float] = {}

    # 1. Leer ARB_InformacionPH
    for table_name in informacion_ph_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_fk = row.get("arb_predio")
            if predio_fk in (None, ""):
                continue

            predio_id = str(predio_fk).strip()

            area_match = helper._extract_field(
                row,
                area_total_construida_privada_fields,
                require_value=False,
            )
            area_field = area_match[0] if area_match else area_total_construida_privada_fields[0]
            area_raw = area_match[1] if area_match else None
            area_value = parse_float(area_raw)

            info_ph_por_predio[predio_id] = {
                "tabla": table_name,
                "campo": area_field,
                "class": table_name,
                "valor": area_raw,
                "area_total_construida_privada": area_value,
                "object_ref": helper.identify(row),
            }

    # 2. Leer predios matriz PH y unidades PH
    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            object_ref = helper.identify(row)

            condicion_match = helper._extract_field(
                row,
                condicion_fields,
                require_value=False,
            )
            if not condicion_match:
                continue

            condicion_field, condicion_raw = condicion_match
            condicion_str = "" if condicion_raw in (None, "") else str(condicion_raw).strip()
            if not condicion_str:
                continue

            condicion_norm = _normalize_condicion(condicion_str)

            numero_match = helper._extract_field(
                row,
                numero_predial_fields,
                require_value=False,
            )
            if not numero_match:
                continue

            numero_field, numero_raw = numero_match
            numero_str = "" if numero_raw in (None, "") else str(numero_raw).strip()
            if not numero_str:
                continue

            sufijo_22_30 = numero_str[21:30] if len(numero_str) >= 30 else ""

            matriz_match = helper._extract_field(
                row,
                predio_matriz_fields,
                require_value=False,
            )
            matriz_raw = matriz_match[1] if matriz_match else None
            predio_matriz = "" if matriz_raw in (None, "") else str(matriz_raw).strip()

            if condicion_norm == "PH_MATRIZ" and sufijo_22_30 == "900000000":
                predios_matriz[predio_id] = {
                    "tabla": table_name,
                    "campo": numero_field,
                    "class": table_name,
                    "object_ref": object_ref,
                    "predio_id": predio_id,
                    "numero_predial": numero_str,
                    "condicion_predio": condicion_str,
                }

            elif condicion_norm == "PH_UNIDAD_PREDIAL":
                predios_unidad_ph[predio_id] = {
                    "tabla": table_name,
                    "class": table_name,
                    "object_ref": object_ref,
                    "predio_id": predio_id,
                    "numero_predial": numero_str,
                    "predio_matriz": predio_matriz,
                    "condicion_predio": condicion_str,
                }

    if not predios_matriz:
        return issues

    # 3. Construcción -> predio
    for table_name in construccion_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            construccion_id = get_t_id(row)
            if not construccion_id:
                continue

            predio_fk = row.get("predio")
            if predio_fk in (None, ""):
                continue

            construccion_a_predio[construccion_id] = str(predio_fk).strip()

    # 4. Características -> área construida
    for table_name in caracteristicas_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            caracteristicas_id = get_t_id(row)
            if not caracteristicas_id:
                continue

            area_match = helper._extract_field(
                row,
                area_construida_fields,
                require_value=False,
            )
            if not area_match:
                continue

            _, area_raw = area_match
            area_value = parse_float(area_raw)
            if area_value is None:
                continue

            area_construida_por_caracteristicas[caracteristicas_id] = area_value

    # 5. Recorrer UCs y sumar solo las asociadas a unidades prediales PH
    for table_name in unidad_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            construccion_fk = row.get("construccion")
            if construccion_fk in (None, ""):
                continue

            caracteristicas_fk = row.get("caracteristicasunidadconstruccion")
            if caracteristicas_fk in (None, ""):
                continue

            construccion_id = str(construccion_fk).strip()
            caracteristicas_id = str(caracteristicas_fk).strip()

            predio_id = construccion_a_predio.get(construccion_id)
            if not predio_id:
                continue

            # solo sumar si la UC pertenece a una unidad predial PH
            unidad_info = predios_unidad_ph.get(predio_id)
            if not unidad_info:
                continue

            matriz_id = unidad_info["predio_matriz"]
            if not matriz_id:
                continue

            area_uc = area_construida_por_caracteristicas.get(caracteristicas_id)
            if area_uc is None:
                continue

            suma_area_privada_por_matriz[matriz_id] = round(
                suma_area_privada_por_matriz.get(matriz_id, 0.0) + area_uc,
                1,
            )

    # 6. Comparar área total construida privada vs suma UCs de unidades prediales
    for predio_id, predio_info in predios_matriz.items():
        info_ph = info_ph_por_predio.get(predio_id)

        if not info_ph:
            issues.append(
                RuleIssue(
                    rule_id="1.27",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.27 porque el predio matriz "
                        "no tiene registro en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                    },
                )
            )
            continue

        area_privada = info_ph["area_total_construida_privada"]
        if area_privada is None:
            issues.append(
                RuleIssue(
                    rule_id="1.27",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.27 porque "
                        "area_total_construida_privada no existe o está vacía "
                        "en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": info_ph["tabla"],
                        "campo": info_ph["campo"],
                        "class": info_ph["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "valor": info_ph["valor"],
                    },
                )
            )
            continue

        area_privada_redondeada = round(float(area_privada), 1)
        suma_privada = round(suma_area_privada_por_matriz.get(predio_id, 0.0), 1)

        if area_privada_redondeada != suma_privada:
            issues.append(
                RuleIssue(
                    rule_id="1.27",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "En la tabla datos de PH o condominio, para los predios con "
                        "condición PH.Matriz, el área total construida privada debe ser "
                        "la sumatoria de las áreas de las unidades de construcción "
                        "asociadas a las unidades prediales."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial_matriz": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                        "area_total_construida_privada": area_privada_redondeada,
                        "suma_areas_unidades_construccion": suma_privada,
                    },
                )
            )

    return issues

def _rule_1_28(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    informacion_ph_tables = ("ARB_InformacionPH", "arb_informacionph")
    construccion_tables = ("ARB_Construccion", "arb_construccion")
    unidad_tables = ("ARB_UnidadConstruccion", "arb_unidadconstruccion")
    caracteristicas_tables = (
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )

    numero_predial_fields = (
        "Numero_Predial_Nacional",
        "numero_predial_nacional",
        "numero_predial",
        "Numero_Predial",
    )

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    area_total_construida_comun_fields = (
        "Area_Total_Construida_Comun",
        "area_total_construida_comun",
    )

    area_construida_fields = (
        "Area_Construida",
        "area_construida",
    )

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    def parse_float(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", ".").strip())
        except Exception:
            return None

    predios_matriz: dict[str, dict[str, object]] = {}
    info_ph_por_predio: dict[str, dict[str, object]] = {}
    construccion_a_predio: dict[str, str] = {}
    area_construida_por_caracteristicas: dict[str, float] = {}
    suma_area_comun_por_matriz: dict[str, float] = {}

    # 1. Leer ARB_InformacionPH
    for table_name in informacion_ph_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_fk = row.get("arb_predio")
            if predio_fk in (None, ""):
                continue

            predio_id = str(predio_fk).strip()

            area_match = helper._extract_field(
                row,
                area_total_construida_comun_fields,
                require_value=False,
            )
            area_field = area_match[0] if area_match else area_total_construida_comun_fields[0]
            area_raw = area_match[1] if area_match else None
            area_value = parse_float(area_raw)

            info_ph_por_predio[predio_id] = {
                "tabla": table_name,
                "campo": area_field,
                "class": table_name,
                "valor": area_raw,
                "area_total_construida_comun": area_value,
                "object_ref": helper.identify(row),
            }

    # 2. Identificar predios PH.MATRIZ con sufijo 900000000
    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            object_ref = helper.identify(row)

            condicion_match = helper._extract_field(
                row,
                condicion_fields,
                require_value=False,
            )
            if not condicion_match:
                continue

            condicion_field, condicion_raw = condicion_match
            condicion_str = "" if condicion_raw in (None, "") else str(condicion_raw).strip()
            if not condicion_str:
                continue

            condicion_norm = _normalize_condicion(condicion_str)

            numero_match = helper._extract_field(
                row,
                numero_predial_fields,
                require_value=False,
            )
            if not numero_match:
                continue

            numero_field, numero_raw = numero_match
            numero_str = "" if numero_raw in (None, "") else str(numero_raw).strip()
            if not numero_str:
                continue

            sufijo_22_30 = numero_str[21:30] if len(numero_str) >= 30 else ""

            if condicion_norm == "PH_MATRIZ" and sufijo_22_30 == "900000000":
                predios_matriz[predio_id] = {
                    "tabla": table_name,
                    "campo": numero_field,
                    "class": table_name,
                    "object_ref": object_ref,
                    "predio_id": predio_id,
                    "numero_predial": numero_str,
                    "condicion_predio": condicion_str,
                }

    if not predios_matriz:
        return issues

    # 3. Construcción -> predio
    for table_name in construccion_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            construccion_id = get_t_id(row)
            if not construccion_id:
                continue

            predio_fk = row.get("predio")
            if predio_fk in (None, ""):
                continue

            construccion_a_predio[construccion_id] = str(predio_fk).strip()

    # 4. Características -> área construida
    for table_name in caracteristicas_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            caracteristicas_id = get_t_id(row)
            if not caracteristicas_id:
                continue

            area_match = helper._extract_field(
                row,
                area_construida_fields,
                require_value=False,
            )
            if not area_match:
                continue

            _, area_raw = area_match
            area_value = parse_float(area_raw)
            if area_value is None:
                continue

            area_construida_por_caracteristicas[caracteristicas_id] = area_value

    # 5. Sumar solo UCs asociadas directamente al predio matriz
    for table_name in unidad_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            construccion_fk = row.get("construccion")
            if construccion_fk in (None, ""):
                continue

            caracteristicas_fk = row.get("caracteristicasunidadconstruccion")
            if caracteristicas_fk in (None, ""):
                continue

            construccion_id = str(construccion_fk).strip()
            caracteristicas_id = str(caracteristicas_fk).strip()

            predio_id = construccion_a_predio.get(construccion_id)
            if not predio_id:
                continue

            if predio_id not in predios_matriz:
                continue

            area_uc = area_construida_por_caracteristicas.get(caracteristicas_id)
            if area_uc is None:
                continue

            suma_area_comun_por_matriz[predio_id] = round(
                suma_area_comun_por_matriz.get(predio_id, 0.0) + area_uc,
                1,
            )

    # 6. Comparar área común vs suma de UCs del matriz
    for predio_id, predio_info in predios_matriz.items():
        info_ph = info_ph_por_predio.get(predio_id)

        if not info_ph:
            issues.append(
                RuleIssue(
                    rule_id="1.28",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.28 porque el predio matriz "
                        "no tiene registro en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                    },
                )
            )
            continue

        area_comun = info_ph["area_total_construida_comun"]
        if area_comun is None:
            issues.append(
                RuleIssue(
                    rule_id="1.28",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.28 porque "
                        "area_total_construida_comun no existe o está vacía "
                        "en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": info_ph["tabla"],
                        "campo": info_ph["campo"],
                        "class": info_ph["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "valor": info_ph["valor"],
                    },
                )
            )
            continue

        area_comun_redondeada = round(float(area_comun), 1)
        suma_comun = round(suma_area_comun_por_matriz.get(predio_id, 0.0), 1)

        if area_comun_redondeada != suma_comun:
            issues.append(
                RuleIssue(
                    rule_id="1.28",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "En la tabla datos de PH o condominio, para los predios con "
                        "condición PH.Matriz, el área total construida común debe ser "
                        "la sumatoria de las áreas de las unidades de construcción "
                        "del PH matriz."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial_matriz": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                        "area_total_construida_comun": area_comun_redondeada,
                        "suma_areas_unidades_construccion_matriz": suma_comun,
                    },
                )
            )

    return issues

def _rule_1_29(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    informacion_ph_tables = ("ARB_InformacionPH", "arb_informacionph")

    numero_predial_fields = (
        "Numero_Predial_Nacional",
        "numero_predial_nacional",
        "numero_predial",
        "Numero_Predial",
    )

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    predio_matriz_fields = (
        "predio_matriz",
        "Predio_Matriz",
    )

    numero_torres_fields = (
        "Numero_Torres",
        "numero_torres",
    )

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    def parse_int(value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(str(value).strip())
        except Exception:
            try:
                return int(float(str(value).replace(",", ".").strip()))
            except Exception:
                return None

    predios_matriz: dict[str, dict[str, object]] = {}
    info_ph_por_predio: dict[str, dict[str, object]] = {}
    max_torres_por_matriz: dict[str, int] = {}

    # 1. Leer ARB_InformacionPH
    for table_name in informacion_ph_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_fk = row.get("arb_predio")
            if predio_fk in (None, ""):
                continue

            predio_id = str(predio_fk).strip()

            torres_match = helper._extract_field(
                row,
                numero_torres_fields,
                require_value=False,
            )
            torres_field = torres_match[0] if torres_match else numero_torres_fields[0]
            torres_raw = torres_match[1] if torres_match else None
            torres_value = parse_int(torres_raw)

            info_ph_por_predio[predio_id] = {
                "tabla": table_name,
                "campo": torres_field,
                "class": table_name,
                "valor": torres_raw,
                "numero_torres": torres_value,
                "object_ref": helper.identify(row),
            }

    # 2. Leer predios matriz PH y unidades PH
    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            object_ref = helper.identify(row)

            condicion_match = helper._extract_field(
                row,
                condicion_fields,
                require_value=False,
            )
            if not condicion_match:
                continue

            condicion_field, condicion_raw = condicion_match
            condicion_str = "" if condicion_raw in (None, "") else str(condicion_raw).strip()
            if not condicion_str:
                continue

            condicion_norm = _normalize_condicion(condicion_str)

            numero_match = helper._extract_field(
                row,
                numero_predial_fields,
                require_value=False,
            )
            if not numero_match:
                continue

            numero_field, numero_raw = numero_match
            numero_str = "" if numero_raw in (None, "") else str(numero_raw).strip()
            if not numero_str:
                continue

            sufijo_22_30 = numero_str[21:30] if len(numero_str) >= 30 else ""

            matriz_match = helper._extract_field(
                row,
                predio_matriz_fields,
                require_value=False,
            )
            matriz_raw = matriz_match[1] if matriz_match else None
            predio_matriz = "" if matriz_raw in (None, "") else str(matriz_raw).strip()

            if condicion_norm == "PH_MATRIZ" and sufijo_22_30 == "900000000":
                predios_matriz[predio_id] = {
                    "tabla": table_name,
                    "campo": numero_field,
                    "class": table_name,
                    "object_ref": object_ref,
                    "predio_id": predio_id,
                    "numero_predial": numero_str,
                    "condicion_predio": condicion_str,
                }

            elif condicion_norm == "PH_UNIDAD_PREDIAL":
                if not predio_matriz:
                    continue

                if len(numero_str) < 26:
                    continue

                tramo_25_26 = numero_str[24:26]
                if not tramo_25_26.isdigit():
                    continue

                valor_torre = int(tramo_25_26)
                max_torres_por_matriz[predio_matriz] = max(
                    max_torres_por_matriz.get(predio_matriz, 0),
                    valor_torre,
                )

    if not predios_matriz:
        return issues

    # 3. Comparar numero_torres vs máximo de posiciones 25-26
    for predio_id, predio_info in predios_matriz.items():
        info_ph = info_ph_por_predio.get(predio_id)

        if not info_ph:
            issues.append(
                RuleIssue(
                    rule_id="1.29",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.29 porque el predio matriz "
                        "no tiene registro en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                    },
                )
            )
            continue

        numero_torres = info_ph["numero_torres"]
        if numero_torres is None:
            issues.append(
                RuleIssue(
                    rule_id="1.29",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.29 porque numero_torres "
                        "no existe o está vacío en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": info_ph["tabla"],
                        "campo": info_ph["campo"],
                        "class": info_ph["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "valor": info_ph["valor"],
                    },
                )
            )
            continue

        max_torres = max_torres_por_matriz.get(predio_id, 0)

        if numero_torres != max_torres:
            issues.append(
                RuleIssue(
                    rule_id="1.29",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "En la tabla datos de PH o condominio, para los predios con "
                        "condición PH.Matriz, el número de torres debe ser igual al "
                        "número máximo indicado en las posiciones 25-26 del número "
                        "predial de las unidades asociadas al PH."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial_matriz": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                        "numero_torres": numero_torres,
                        "maximo_posiciones_25_26": max_torres,
                    },
                )
            )

    return issues

def _rule_1_30(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    informacion_ph_tables = ("ARB_InformacionPH", "arb_informacionph")

    numero_predial_fields = (
        "Numero_Predial_Nacional",
        "numero_predial_nacional",
        "numero_predial",
        "Numero_Predial",
    )

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    predio_matriz_fields = (
        "predio_matriz",
        "Predio_Matriz",
    )

    total_unidades_privadas_fields = (
        "Total_Unidades_Privadas",
        "total_unidades_privadas",
    )

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    def parse_int(value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(str(value).strip())
        except Exception:
            try:
                return int(float(str(value).replace(",", ".").strip()))
            except Exception:
                return None

    predios_matriz: dict[str, dict[str, object]] = {}
    info_ph_por_predio: dict[str, dict[str, object]] = {}
    conteo_unidades_por_matriz: dict[str, int] = {}

    # 1. Leer ARB_InformacionPH
    for table_name in informacion_ph_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_fk = row.get("arb_predio")
            if predio_fk in (None, ""):
                continue

            predio_id = str(predio_fk).strip()

            total_match = helper._extract_field(
                row,
                total_unidades_privadas_fields,
                require_value=False,
            )
            total_field = total_match[0] if total_match else total_unidades_privadas_fields[0]
            total_raw = total_match[1] if total_match else None
            total_value = parse_int(total_raw)

            info_ph_por_predio[predio_id] = {
                "tabla": table_name,
                "campo": total_field,
                "class": table_name,
                "valor": total_raw,
                "total_unidades_privadas": total_value,
                "object_ref": helper.identify(row),
            }

    # 2. Leer predios matriz PH y unidades PH
    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            object_ref = helper.identify(row)

            condicion_match = helper._extract_field(
                row,
                condicion_fields,
                require_value=False,
            )
            if not condicion_match:
                continue

            condicion_field, condicion_raw = condicion_match
            condicion_str = "" if condicion_raw in (None, "") else str(condicion_raw).strip()
            if not condicion_str:
                continue

            condicion_norm = _normalize_condicion(condicion_str)

            numero_match = helper._extract_field(
                row,
                numero_predial_fields,
                require_value=False,
            )
            if not numero_match:
                continue

            numero_field, numero_raw = numero_match
            numero_str = "" if numero_raw in (None, "") else str(numero_raw).strip()
            if not numero_str:
                continue

            sufijo_22_30 = numero_str[21:30] if len(numero_str) >= 30 else ""

            matriz_match = helper._extract_field(
                row,
                predio_matriz_fields,
                require_value=False,
            )
            matriz_raw = matriz_match[1] if matriz_match else None
            predio_matriz = "" if matriz_raw in (None, "") else str(matriz_raw).strip()

            if condicion_norm == "PH_MATRIZ" and sufijo_22_30 == "900000000":
                predios_matriz[predio_id] = {
                    "tabla": table_name,
                    "campo": numero_field,
                    "class": table_name,
                    "object_ref": object_ref,
                    "predio_id": predio_id,
                    "numero_predial": numero_str,
                    "condicion_predio": condicion_str,
                }

            elif condicion_norm == "PH_UNIDAD_PREDIAL":
                if predio_matriz:
                    conteo_unidades_por_matriz[predio_matriz] = (
                        conteo_unidades_por_matriz.get(predio_matriz, 0) + 1
                    )

    if not predios_matriz:
        return issues

    # 3. Comparar total_unidades_privadas vs conteo de predios asociados
    for predio_id, predio_info in predios_matriz.items():
        info_ph = info_ph_por_predio.get(predio_id)

        if not info_ph:
            issues.append(
                RuleIssue(
                    rule_id="1.30",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.30 porque el predio matriz "
                        "no tiene registro en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                    },
                )
            )
            continue

        total_privadas = info_ph["total_unidades_privadas"]
        if total_privadas is None:
            issues.append(
                RuleIssue(
                    rule_id="1.30",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.30 porque "
                        "total_unidades_privadas no existe o está vacío "
                        "en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": info_ph["tabla"],
                        "campo": info_ph["campo"],
                        "class": info_ph["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "valor": info_ph["valor"],
                    },
                )
            )
            continue

        total_asociadas = conteo_unidades_por_matriz.get(predio_id, 0)

        if total_privadas != total_asociadas:
            issues.append(
                RuleIssue(
                    rule_id="1.30",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "En la tabla datos de PH o condominio, para los predios con "
                        "condición PH.Matriz, el total de unidades privadas debe ser "
                        "el conteo de predios asociados al PH."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial_matriz": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                        "total_unidades_privadas": total_privadas,
                        "conteo_predios_asociados": total_asociadas,
                    },
                )
            )

    return issues

def _rule_1_31(dataset: DatasetReader) -> list[RuleIssue]:
    # sin definir falta campo area_geografica en  capa terreno
    return []

def _rule_1_32(dataset: DatasetReader) -> list[RuleIssue]:
    # sin definir falta campo area_geografica en  capa terreno
    return []

def _rule_1_33(dataset: DatasetReader) -> list[RuleIssue]:
    # sin definir falta campo area_geografica en  capa terreno
    return []


def _rule_1_34(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    informacion_ph_tables = ("ARB_InformacionPH", "arb_informacionph")
    construccion_tables = ("ARB_Construccion", "arb_construccion")
    unidad_tables = ("ARB_UnidadConstruccion", "arb_unidadconstruccion")
    caracteristicas_tables = (
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )

    numero_predial_fields = (
        "Numero_Predial_Nacional",
        "numero_predial_nacional",
        "numero_predial",
        "Numero_Predial",
    )

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    predio_matriz_fields = (
        "predio_matriz",
        "Predio_Matriz",
    )

    area_total_construida_fields = (
        "Area_Total_Construida",
        "area_total_construida",
    )

    area_construida_fields = (
        "Area_Construida",
        "area_construida",
    )

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    def parse_float(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", ".").strip())
        except Exception:
            return None

    predios_matriz: dict[str, dict[str, object]] = {}
    predios_unidad_ph: dict[str, dict[str, object]] = {}
    info_ph_por_predio: dict[str, dict[str, object]] = {}

    construccion_a_predio: dict[str, str] = {}
    area_construida_por_caracteristicas: dict[str, float] = {}

    suma_area_por_matriz: dict[str, float] = {}

    # 1. Leer ARB_InformacionPH
    for table_name in informacion_ph_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_fk = row.get("arb_predio")
            if predio_fk in (None, ""):
                continue

            predio_id = str(predio_fk).strip()

            area_match = helper._extract_field(
                row,
                area_total_construida_fields,
                require_value=False,
            )
            area_field = area_match[0] if area_match else area_total_construida_fields[0]
            area_raw = area_match[1] if area_match else None
            area_value = parse_float(area_raw)

            info_ph_por_predio[predio_id] = {
                "tabla": table_name,
                "campo": area_field,
                "class": table_name,
                "valor": area_raw,
                "area_total_construida": area_value,
                "object_ref": helper.identify(row),
            }

    # 2. Leer predios matriz PH y unidades PH
    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            object_ref = helper.identify(row)

            condicion_match = helper._extract_field(
                row,
                condicion_fields,
                require_value=False,
            )
            if not condicion_match:
                continue

            condicion_field, condicion_raw = condicion_match
            condicion_str = "" if condicion_raw in (None, "") else str(condicion_raw).strip()
            if not condicion_str:
                continue

            condicion_norm = _normalize_condicion(condicion_str)

            numero_match = helper._extract_field(
                row,
                numero_predial_fields,
                require_value=False,
            )
            if not numero_match:
                continue

            numero_field, numero_raw = numero_match
            numero_str = "" if numero_raw in (None, "") else str(numero_raw).strip()
            if not numero_str:
                continue

            sufijo_22_30 = numero_str[21:30] if len(numero_str) >= 30 else ""

            matriz_match = helper._extract_field(
                row,
                predio_matriz_fields,
                require_value=False,
            )
            matriz_raw = matriz_match[1] if matriz_match else None
            predio_matriz = "" if matriz_raw in (None, "") else str(matriz_raw).strip()

            if condicion_norm == "CONDOMINIO_MATRIZ" and sufijo_22_30 == "800000000":
                predios_matriz[predio_id] = {
                    "tabla": table_name,
                    "campo": numero_field,
                    "class": table_name,
                    "object_ref": object_ref,
                    "predio_id": predio_id,
                    "numero_predial": numero_str,
                    "condicion_predio": condicion_str,
                }

            elif condicion_norm == "CONDOMINIO_UNIDAD_PREDIAL":
                predios_unidad_ph[predio_id] = {
                    "tabla": table_name,
                    "class": table_name,
                    "object_ref": object_ref,
                    "predio_id": predio_id,
                    "numero_predial": numero_str,
                    "predio_matriz": predio_matriz,
                    "condicion_predio": condicion_str,
                }

    if not predios_matriz:
        return issues

    # 3. Construcción -> predio
    for table_name in construccion_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            construccion_id = get_t_id(row)
            if not construccion_id:
                continue

            predio_fk = row.get("predio")
            if predio_fk in (None, ""):
                continue

            construccion_a_predio[construccion_id] = str(predio_fk).strip()

    # 4. Características -> área construida
    for table_name in caracteristicas_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            caracteristicas_id = get_t_id(row)
            if not caracteristicas_id:
                continue

            area_match = helper._extract_field(
                row,
                area_construida_fields,
                require_value=False,
            )
            if not area_match:
                continue

            _, area_raw = area_match
            area_value = parse_float(area_raw)
            if area_value is None:
                continue

            area_construida_por_caracteristicas[caracteristicas_id] = area_value

    # 5. Recorrer unidades de construcción y acumular área a la matriz
    for table_name in unidad_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            construccion_fk = row.get("construccion")
            if construccion_fk in (None, ""):
                continue

            caracteristicas_fk = row.get("caracteristicasunidadconstruccion")
            if caracteristicas_fk in (None, ""):
                continue

            construccion_id = str(construccion_fk).strip()
            caracteristicas_id = str(caracteristicas_fk).strip()

            predio_id = construccion_a_predio.get(construccion_id)
            if not predio_id:
                continue

            area_uc = area_construida_por_caracteristicas.get(caracteristicas_id)
            if area_uc is None:
                continue

            # UC asociada directamente al predio matriz
            if predio_id in predios_matriz:
                suma_area_por_matriz[predio_id] = round(
                    suma_area_por_matriz.get(predio_id, 0.0) + area_uc,
                    1,
                )
                continue

            # UC asociada a unidad predial PH; sumar a su matriz
            unidad_info = predios_unidad_ph.get(predio_id)
            if unidad_info:
                matriz_id = unidad_info["predio_matriz"]
                if matriz_id:
                    suma_area_por_matriz[matriz_id] = round(
                        suma_area_por_matriz.get(matriz_id, 0.0) + area_uc,
                        1,
                    )

    # 6. Comparar área del matriz vs suma de áreas construidas
    for predio_id, predio_info in predios_matriz.items():
        info_ph = info_ph_por_predio.get(predio_id)

        if not info_ph:
            issues.append(
                RuleIssue(
                    rule_id="1.34",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.34 porque el predio matriz "
                        "no tiene registro en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                    },
                )
            )
            continue

        area_matriz = info_ph["area_total_construida"]
        if area_matriz is None:
            issues.append(
                RuleIssue(
                    rule_id="1.34",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.34 porque area_total_construida "
                        "no existe o está vacía en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": info_ph["tabla"],
                        "campo": info_ph["campo"],
                        "class": info_ph["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "valor": info_ph["valor"],
                    },
                )
            )
            continue

        area_matriz_redondeada = round(float(area_matriz), 1)
        area_total_unidad = round(suma_area_por_matriz.get(predio_id, 0.0), 1)

        if area_matriz_redondeada != area_total_unidad:
            issues.append(
                RuleIssue(
                    rule_id="1.34",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "En la tabla datos de PH o condominio, para los predios con "
                        "condición Condominio.Matriz, el área total construida debe ser la "
                        "sumatoria de las áreas de las unidades de construcción "
                        "asociadas a las unidades prediales y de las unidades de "
                        "construcción asociadas al predio matriz."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial_matriz": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                        "area_total_construida_matriz": area_matriz_redondeada,
                        "suma_areas_unidades_construccion": area_total_unidad,
                    },
                )
            )

    return issues

def _rule_1_35(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    informacion_ph_tables = ("ARB_InformacionPH", "arb_informacionph")
    construccion_tables = ("ARB_Construccion", "arb_construccion")
    unidad_tables = ("ARB_UnidadConstruccion", "arb_unidadconstruccion")
    caracteristicas_tables = (
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )

    numero_predial_fields = (
        "Numero_Predial_Nacional",
        "numero_predial_nacional",
        "numero_predial",
        "Numero_Predial",
    )

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    predio_matriz_fields = (
        "predio_matriz",
        "Predio_Matriz",
    )

    area_total_construida_privada_fields = (
        "Area_Total_Construida_Privada",
        "area_total_construida_privada",
    )

    area_construida_fields = (
        "Area_Construida",
        "area_construida",
    )

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    def parse_float(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", ".").strip())
        except Exception:
            return None

    predios_matriz: dict[str, dict[str, object]] = {}
    predios_unidad_ph: dict[str, dict[str, object]] = {}
    info_ph_por_predio: dict[str, dict[str, object]] = {}

    construccion_a_predio: dict[str, str] = {}
    area_construida_por_caracteristicas: dict[str, float] = {}

    suma_area_privada_por_matriz: dict[str, float] = {}

    # 1. Leer ARB_InformacionPH
    for table_name in informacion_ph_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_fk = row.get("arb_predio")
            if predio_fk in (None, ""):
                continue

            predio_id = str(predio_fk).strip()

            area_match = helper._extract_field(
                row,
                area_total_construida_privada_fields,
                require_value=False,
            )
            area_field = area_match[0] if area_match else area_total_construida_privada_fields[0]
            area_raw = area_match[1] if area_match else None
            area_value = parse_float(area_raw)

            info_ph_por_predio[predio_id] = {
                "tabla": table_name,
                "campo": area_field,
                "class": table_name,
                "valor": area_raw,
                "area_total_construida_privada": area_value,
                "object_ref": helper.identify(row),
            }

    # 2. Leer predios matriz PH y unidades PH
    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            object_ref = helper.identify(row)

            condicion_match = helper._extract_field(
                row,
                condicion_fields,
                require_value=False,
            )
            if not condicion_match:
                continue

            condicion_field, condicion_raw = condicion_match
            condicion_str = "" if condicion_raw in (None, "") else str(condicion_raw).strip()
            if not condicion_str:
                continue

            condicion_norm = _normalize_condicion(condicion_str)

            numero_match = helper._extract_field(
                row,
                numero_predial_fields,
                require_value=False,
            )
            if not numero_match:
                continue

            numero_field, numero_raw = numero_match
            numero_str = "" if numero_raw in (None, "") else str(numero_raw).strip()
            if not numero_str:
                continue

            sufijo_22_30 = numero_str[21:30] if len(numero_str) >= 30 else ""

            matriz_match = helper._extract_field(
                row,
                predio_matriz_fields,
                require_value=False,
            )
            matriz_raw = matriz_match[1] if matriz_match else None
            predio_matriz = "" if matriz_raw in (None, "") else str(matriz_raw).strip()

            if condicion_norm == "CONDOMINIO_MATRIZ" and sufijo_22_30 == "800000000":
                predios_matriz[predio_id] = {
                    "tabla": table_name,
                    "campo": numero_field,
                    "class": table_name,
                    "object_ref": object_ref,
                    "predio_id": predio_id,
                    "numero_predial": numero_str,
                    "condicion_predio": condicion_str,
                }

            elif condicion_norm == "CONDOMINIO_UNIDAD_PREDIAL":
                predios_unidad_ph[predio_id] = {
                    "tabla": table_name,
                    "class": table_name,
                    "object_ref": object_ref,
                    "predio_id": predio_id,
                    "numero_predial": numero_str,
                    "predio_matriz": predio_matriz,
                    "condicion_predio": condicion_str,
                }

    if not predios_matriz:
        return issues

    # 3. Construcción -> predio
    for table_name in construccion_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            construccion_id = get_t_id(row)
            if not construccion_id:
                continue

            predio_fk = row.get("predio")
            if predio_fk in (None, ""):
                continue

            construccion_a_predio[construccion_id] = str(predio_fk).strip()

    # 4. Características -> área construida
    for table_name in caracteristicas_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            caracteristicas_id = get_t_id(row)
            if not caracteristicas_id:
                continue

            area_match = helper._extract_field(
                row,
                area_construida_fields,
                require_value=False,
            )
            if not area_match:
                continue

            _, area_raw = area_match
            area_value = parse_float(area_raw)
            if area_value is None:
                continue

            area_construida_por_caracteristicas[caracteristicas_id] = area_value

    # 5. Recorrer UCs y sumar solo las asociadas a unidades prediales PH
    for table_name in unidad_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            construccion_fk = row.get("construccion")
            if construccion_fk in (None, ""):
                continue

            caracteristicas_fk = row.get("caracteristicasunidadconstruccion")
            if caracteristicas_fk in (None, ""):
                continue

            construccion_id = str(construccion_fk).strip()
            caracteristicas_id = str(caracteristicas_fk).strip()

            predio_id = construccion_a_predio.get(construccion_id)
            if not predio_id:
                continue

            # solo sumar si la UC pertenece a una unidad predial PH
            unidad_info = predios_unidad_ph.get(predio_id)
            if not unidad_info:
                continue

            matriz_id = unidad_info["predio_matriz"]
            if not matriz_id:
                continue

            area_uc = area_construida_por_caracteristicas.get(caracteristicas_id)
            if area_uc is None:
                continue

            suma_area_privada_por_matriz[matriz_id] = round(
                suma_area_privada_por_matriz.get(matriz_id, 0.0) + area_uc,
                1,
            )

    # 6. Comparar área total construida privada vs suma UCs de unidades prediales
    for predio_id, predio_info in predios_matriz.items():
        info_ph = info_ph_por_predio.get(predio_id)

        if not info_ph:
            issues.append(
                RuleIssue(
                    rule_id="1.35",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.35 porque el predio matriz "
                        "no tiene registro en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                    },
                )
            )
            continue

        area_privada = info_ph["area_total_construida_privada"]
        if area_privada is None:
            issues.append(
                RuleIssue(
                    rule_id="1.35",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.35 porque "
                        "area_total_construida_privada no existe o está vacía "
                        "en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": info_ph["tabla"],
                        "campo": info_ph["campo"],
                        "class": info_ph["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "valor": info_ph["valor"],
                    },
                )
            )
            continue

        area_privada_redondeada = round(float(area_privada), 1)
        suma_privada = round(suma_area_privada_por_matriz.get(predio_id, 0.0), 1)

        if area_privada_redondeada != suma_privada:
            issues.append(
                RuleIssue(
                    rule_id="1.35",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "En la tabla datos de PH o condominio, para los predios con "
                        "condición Condominio.Matriz, el área total construida privada debe ser "
                        "la sumatoria de las áreas de las unidades de construcción "
                        "asociadas a las unidades prediales."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial_matriz": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                        "area_total_construida_privada": area_privada_redondeada,
                        "suma_areas_unidades_construccion": suma_privada,
                    },
                )
            )

    return issues

def _rule_1_36(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    informacion_ph_tables = ("ARB_InformacionPH", "arb_informacionph")
    construccion_tables = ("ARB_Construccion", "arb_construccion")
    unidad_tables = ("ARB_UnidadConstruccion", "arb_unidadconstruccion")
    caracteristicas_tables = (
        "ARB_CaracteristicasUnidadConstruccion",
        "arb_caracteristicasunidadconstruccion",
    )

    numero_predial_fields = (
        "Numero_Predial_Nacional",
        "numero_predial_nacional",
        "numero_predial",
        "Numero_Predial",
    )

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    area_total_construida_comun_fields = (
        "Area_Total_Construida_Comun",
        "area_total_construida_comun",
    )

    area_construida_fields = (
        "Area_Construida",
        "area_construida",
    )

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    def parse_float(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", ".").strip())
        except Exception:
            return None

    predios_matriz: dict[str, dict[str, object]] = {}
    info_ph_por_predio: dict[str, dict[str, object]] = {}
    construccion_a_predio: dict[str, str] = {}
    area_construida_por_caracteristicas: dict[str, float] = {}
    suma_area_comun_por_matriz: dict[str, float] = {}

    # 1. Leer ARB_InformacionPH
    for table_name in informacion_ph_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_fk = row.get("arb_predio")
            if predio_fk in (None, ""):
                continue

            predio_id = str(predio_fk).strip()

            area_match = helper._extract_field(
                row,
                area_total_construida_comun_fields,
                require_value=False,
            )
            area_field = area_match[0] if area_match else area_total_construida_comun_fields[0]
            area_raw = area_match[1] if area_match else None
            area_value = parse_float(area_raw)

            info_ph_por_predio[predio_id] = {
                "tabla": table_name,
                "campo": area_field,
                "class": table_name,
                "valor": area_raw,
                "area_total_construida_comun": area_value,
                "object_ref": helper.identify(row),
            }

    # 2. Identificar predios CONDOMINIO.MATRIZ con sufijo 800000000
    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            object_ref = helper.identify(row)

            condicion_match = helper._extract_field(
                row,
                condicion_fields,
                require_value=False,
            )
            if not condicion_match:
                continue

            condicion_field, condicion_raw = condicion_match
            condicion_str = "" if condicion_raw in (None, "") else str(condicion_raw).strip()
            if not condicion_str:
                continue

            condicion_norm = _normalize_condicion(condicion_str)

            numero_match = helper._extract_field(
                row,
                numero_predial_fields,
                require_value=False,
            )
            if not numero_match:
                continue

            numero_field, numero_raw = numero_match
            numero_str = "" if numero_raw in (None, "") else str(numero_raw).strip()
            if not numero_str:
                continue

            sufijo_22_30 = numero_str[21:30] if len(numero_str) >= 30 else ""

            if condicion_norm == "CONDOMINIO_MATRIZ" and sufijo_22_30 == "800000000":
                predios_matriz[predio_id] = {
                    "tabla": table_name,
                    "campo": numero_field,
                    "class": table_name,
                    "object_ref": object_ref,
                    "predio_id": predio_id,
                    "numero_predial": numero_str,
                    "condicion_predio": condicion_str,
                }

    if not predios_matriz:
        return issues

    # 3. Construcción -> predio
    for table_name in construccion_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            construccion_id = get_t_id(row)
            if not construccion_id:
                continue

            predio_fk = row.get("predio")
            if predio_fk in (None, ""):
                continue

            construccion_a_predio[construccion_id] = str(predio_fk).strip()

    # 4. Características -> área construida
    for table_name in caracteristicas_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            caracteristicas_id = get_t_id(row)
            if not caracteristicas_id:
                continue

            area_match = helper._extract_field(
                row,
                area_construida_fields,
                require_value=False,
            )
            if not area_match:
                continue

            _, area_raw = area_match
            area_value = parse_float(area_raw)
            if area_value is None:
                continue

            area_construida_por_caracteristicas[caracteristicas_id] = area_value

    # 5. Sumar solo UCs asociadas directamente al predio matriz
    for table_name in unidad_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            construccion_fk = row.get("construccion")
            if construccion_fk in (None, ""):
                continue

            caracteristicas_fk = row.get("caracteristicasunidadconstruccion")
            if caracteristicas_fk in (None, ""):
                continue

            construccion_id = str(construccion_fk).strip()
            caracteristicas_id = str(caracteristicas_fk).strip()

            predio_id = construccion_a_predio.get(construccion_id)
            if not predio_id:
                continue

            if predio_id not in predios_matriz:
                continue

            area_uc = area_construida_por_caracteristicas.get(caracteristicas_id)
            if area_uc is None:
                continue

            suma_area_comun_por_matriz[predio_id] = round(
                suma_area_comun_por_matriz.get(predio_id, 0.0) + area_uc,
                1,
            )

    # 6. Comparar área común vs suma de UCs del matriz
    for predio_id, predio_info in predios_matriz.items():
        info_ph = info_ph_por_predio.get(predio_id)

        if not info_ph:
            issues.append(
                RuleIssue(
                    rule_id="1.36",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.36 porque el predio matriz "
                        "no tiene registro en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                    },
                )
            )
            continue

        area_comun = info_ph["area_total_construida_comun"]
        if area_comun is None:
            issues.append(
                RuleIssue(
                    rule_id="1.36",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.36 porque "
                        "area_total_construida_comun no existe o está vacía "
                        "en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": info_ph["tabla"],
                        "campo": info_ph["campo"],
                        "class": info_ph["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "valor": info_ph["valor"],
                    },
                )
            )
            continue

        area_comun_redondeada = round(float(area_comun), 1)
        suma_comun = round(suma_area_comun_por_matriz.get(predio_id, 0.0), 1)

        if area_comun_redondeada != suma_comun:
            issues.append(
                RuleIssue(
                    rule_id="1.36",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "En la tabla datos de PH o condominio, para los predios con "
                        "condición Condominio.Matriz, el área total construida común debe ser "
                        "la sumatoria de las áreas de las unidades de construcción "
                        "del Condominio matriz."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial_matriz": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                        "area_total_construida_comun": area_comun_redondeada,
                        "suma_areas_unidades_construccion_matriz": suma_comun,
                    },
                )
            )

    return issues

def _rule_1_37(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    informacion_ph_tables = ("ARB_InformacionPH", "arb_informacionph")

    numero_predial_fields = (
        "Numero_Predial_Nacional",
        "numero_predial_nacional",
        "numero_predial",
        "Numero_Predial",
    )

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    numero_torres_fields = (
        "Numero_Torres",
        "numero_torres",
    )

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    def parse_int(value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(str(value).strip())
        except Exception:
            try:
                return int(float(str(value).replace(",", ".").strip()))
            except Exception:
                return None

    predios_matriz: dict[str, dict[str, object]] = {}
    info_ph_por_predio: dict[str, dict[str, object]] = {}

    # 1. Leer ARB_InformacionPH
    for table_name in informacion_ph_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_fk = row.get("arb_predio")
            if predio_fk in (None, ""):
                continue

            predio_id = str(predio_fk).strip()

            torres_match = helper._extract_field(
                row,
                numero_torres_fields,
                require_value=False,
            )
            torres_field = torres_match[0] if torres_match else numero_torres_fields[0]
            torres_raw = torres_match[1] if torres_match else None
            torres_value = parse_int(torres_raw)

            info_ph_por_predio[predio_id] = {
                "tabla": table_name,
                "campo": torres_field,
                "class": table_name,
                "valor": torres_raw,
                "numero_torres": torres_value,
                "object_ref": helper.identify(row),
            }

    # 2. Leer predios Condominio.Matriz
    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            object_ref = helper.identify(row)

            condicion_match = helper._extract_field(
                row,
                condicion_fields,
                require_value=False,
            )
            if not condicion_match:
                continue

            _, condicion_raw = condicion_match
            condicion_str = "" if condicion_raw in (None, "") else str(condicion_raw).strip()
            if not condicion_str:
                continue

            condicion_norm = _normalize_condicion(condicion_str)

            numero_match = helper._extract_field(
                row,
                numero_predial_fields,
                require_value=False,
            )
            if not numero_match:
                continue

            numero_field, numero_raw = numero_match
            numero_str = "" if numero_raw in (None, "") else str(numero_raw).strip()
            if not numero_str:
                continue

            sufijo_22_30 = numero_str[21:30] if len(numero_str) >= 30 else ""

            if condicion_norm == "CONDOMINIO_MATRIZ" and sufijo_22_30 == "800000000":
                predios_matriz[predio_id] = {
                    "tabla": table_name,
                    "campo": numero_field,
                    "class": table_name,
                    "object_ref": object_ref,
                    "predio_id": predio_id,
                    "numero_predial": numero_str,
                    "condicion_predio": condicion_str,
                }

    if not predios_matriz:
        return issues

    # 3. Validar numero_torres = 0 para Condominio.Matriz
    for predio_id, predio_info in predios_matriz.items():
        info_ph = info_ph_por_predio.get(predio_id)

        if not info_ph:
            issues.append(
                RuleIssue(
                    rule_id="1.37",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.37 porque el predio matriz "
                        "no tiene registro en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                    },
                )
            )
            continue

        numero_torres = info_ph["numero_torres"]

        if numero_torres is None:
            issues.append(
                RuleIssue(
                    rule_id="1.37",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.37 porque numero_torres "
                        "no existe o está vacío en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": info_ph["tabla"],
                        "campo": info_ph["campo"],
                        "class": info_ph["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "valor": info_ph["valor"],
                    },
                )
            )
            continue

        if numero_torres != 0:
            issues.append(
                RuleIssue(
                    rule_id="1.37",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "Para predios con condición Condominio.Matriz, el número de torres debe ser 0."
                    ),
                    details={
                        "tabla": info_ph["tabla"],
                        "campo": info_ph["campo"],
                        "class": info_ph["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                        "numero_torres": numero_torres,
                        "valor_esperado": 0,
                    },
                )
            )

    return issues

def _rule_1_38(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    informacion_ph_tables = ("ARB_InformacionPH", "arb_informacionph")

    numero_predial_fields = (
        "Numero_Predial_Nacional",
        "numero_predial_nacional",
        "numero_predial",
        "Numero_Predial",
    )

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    predio_matriz_fields = (
        "predio_matriz",
        "Predio_Matriz",
    )

    total_unidades_privadas_fields = (
        "Total_Unidades_Privadas",
        "total_unidades_privadas",
    )

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    def parse_int(value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(str(value).strip())
        except Exception:
            try:
                return int(float(str(value).replace(",", ".").strip()))
            except Exception:
                return None

    predios_matriz: dict[str, dict[str, object]] = {}
    info_ph_por_predio: dict[str, dict[str, object]] = {}
    conteo_unidades_por_matriz: dict[str, int] = {}

    # 1. Leer ARB_InformacionPH
    for table_name in informacion_ph_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_fk = row.get("arb_predio")
            if predio_fk in (None, ""):
                continue

            predio_id = str(predio_fk).strip()

            total_match = helper._extract_field(
                row,
                total_unidades_privadas_fields,
                require_value=False,
            )
            total_field = total_match[0] if total_match else total_unidades_privadas_fields[0]
            total_raw = total_match[1] if total_match else None
            total_value = parse_int(total_raw)

            info_ph_por_predio[predio_id] = {
                "tabla": table_name,
                "campo": total_field,
                "class": table_name,
                "valor": total_raw,
                "total_unidades_privadas": total_value,
                "object_ref": helper.identify(row),
            }

    # 2. Leer predios matriz PH y unidades PH
    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            object_ref = helper.identify(row)

            condicion_match = helper._extract_field(
                row,
                condicion_fields,
                require_value=False,
            )
            if not condicion_match:
                continue

            condicion_field, condicion_raw = condicion_match
            condicion_str = "" if condicion_raw in (None, "") else str(condicion_raw).strip()
            if not condicion_str:
                continue

            condicion_norm = _normalize_condicion(condicion_str)

            numero_match = helper._extract_field(
                row,
                numero_predial_fields,
                require_value=False,
            )
            if not numero_match:
                continue

            numero_field, numero_raw = numero_match
            numero_str = "" if numero_raw in (None, "") else str(numero_raw).strip()
            if not numero_str:
                continue

            sufijo_22_30 = numero_str[21:30] if len(numero_str) >= 30 else ""

            matriz_match = helper._extract_field(
                row,
                predio_matriz_fields,
                require_value=False,
            )
            matriz_raw = matriz_match[1] if matriz_match else None
            predio_matriz = "" if matriz_raw in (None, "") else str(matriz_raw).strip()

            if condicion_norm == "CONDOMINIO_MATRIZ" and sufijo_22_30 == "800000000":
                predios_matriz[predio_id] = {
                    "tabla": table_name,
                    "campo": numero_field,
                    "class": table_name,
                    "object_ref": object_ref,
                    "predio_id": predio_id,
                    "numero_predial": numero_str,
                    "condicion_predio": condicion_str,
                }

            elif condicion_norm == "CONDOMINIO_UNIDAD_PREDIAL":
                if predio_matriz:
                    conteo_unidades_por_matriz[predio_matriz] = (
                        conteo_unidades_por_matriz.get(predio_matriz, 0) + 1
                    )

    if not predios_matriz:
        return issues

    # 3. Comparar total_unidades_privadas vs conteo de predios asociados
    for predio_id, predio_info in predios_matriz.items():
        info_ph = info_ph_por_predio.get(predio_id)

        if not info_ph:
            issues.append(
                RuleIssue(
                    rule_id="1.38",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.38 porque el predio matriz "
                        "no tiene registro en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                    },
                )
            )
            continue

        total_privadas = info_ph["total_unidades_privadas"]
        if total_privadas is None:
            issues.append(
                RuleIssue(
                    rule_id="1.38",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "No se puede validar la regla 1.38 porque "
                        "total_unidades_privadas no existe o está vacío "
                        "en ARB_InformacionPH."
                    ),
                    details={
                        "tabla": info_ph["tabla"],
                        "campo": info_ph["campo"],
                        "class": info_ph["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "valor": info_ph["valor"],
                    },
                )
            )
            continue

        total_asociadas = conteo_unidades_por_matriz.get(predio_id, 0)

        if total_privadas != total_asociadas:
            issues.append(
                RuleIssue(
                    rule_id="1.38",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "En la tabla datos de PH o condominio, para los predios con "
                        "condición Condominio.Matriz, el total de unidades privadas debe ser "
                        "el conteo de predios asociados al Condominio."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial_matriz": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                        "total_unidades_privadas": total_privadas,
                        "conteo_predios_asociados": total_asociadas,
                    },
                )
            )

    return issues

def _rule_1_39(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    principal_fields = (
        "es_direccion_principal",
        "Es_Direccion_Principal",
        "es_principal",
        "Es_Principal",
        "direccion_principal",
        "Direccion_Principal",
        "principal",
        "Principal",
        "dir_principal",
        "Dir_Principal",
    )

    predio_fk_fields = (
        "arb_predio_direccion",
        "arb_direccion_arb_predio_direccion_fkey",
        "arb_predio",
        "predio",
        "predio_asociado",
        "id_predio",
        "Id_Predio",
        "id_operacion",
        "Id_Operacion",
        "ARB_direccion_ARB_predio_direccion_fkey",
    )

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    def parse_bool(value: object) -> bool | None:
        if value in (None, ""):
            return None

        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0

        text = str(value).strip().lower()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))

        try:
            return float(text) != 0
        except Exception:
            pass

        if text in {"true", "verdadero", "si", "s", "t", "y", "yes", "checked", "x"}:
            return True
        if text in {"false", "falso", "no", "n", "f", "unchecked"}:
            return False

        return None

    def normalize_relation_key(value: object) -> str:
        text = str(value).strip().lower()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        return re.sub(r"[^a-z0-9]", "", text)

    def field_value(row: dict[str, object], candidates: tuple[str, ...]) -> object | None:
        match = helper._extract_field(row, candidates, require_value=False)
        if not match:
            return None
        value = match[1]
        if value in (None, ""):
            return None
        return value

    def add_predio_alias(alias: object, predio_id: str) -> None:
        if alias in (None, ""):
            return
        alias_text = str(alias).strip()
        if not alias_text:
            return

        alias_values = {alias_text}
        if alias_text.endswith(".0"):
            alias_values.add(alias_text[:-2])

        alias_norm = normalize_relation_key(alias_text)
        if alias_norm:
            alias_values.add(alias_norm)

        for value in alias_values:
            predio_key_aliases.setdefault(value, predio_id)

    def predio_keys(row: dict[str, object]) -> set[str]:
        keys: set[str] = set()
        for field in (
            "T_Id",
            "t_id",
            "TID",
            "tid",
            "id_operacion",
            "Id_Operacion",
            "ID_OPERACION",
            "numero_predial",
            "Numero_Predial",
            "Numero_Predial_Nacional",
            "numero_predial_nacional",
        ):
            value = row.get(field)
            if value not in (None, ""):
                keys.add(str(value).strip())
        object_ref = helper.identify(row)
        if object_ref:
            keys.add(str(object_ref).strip())
        return keys

    def resolve_predio_alias(value: object) -> str | None:
        if value in (None, ""):
            return None
        value_text = str(value).strip()
        if not value_text:
            return None

        if value_text in predio_key_aliases:
            return predio_key_aliases[value_text]

        value_norm = normalize_relation_key(value_text)
        if value_norm in predio_key_aliases:
            return predio_key_aliases[value_norm]

        candidates: set[str] = set()
        for token in re.findall(r"\d+", value_text):
            if token in predio_key_aliases:
                candidates.add(predio_key_aliases[token])
        if len(candidates) == 1:
            return next(iter(candidates))

        return value_text

    predios: dict[str, dict[str, object]] = {}
    predio_key_aliases: dict[str, str] = {}
    direcciones_por_predio: dict[str, list[dict[str, object]]] = {}

    for table_name, row in helper.iter_predios():
        predio_id = get_t_id(row)
        if not predio_id:
            continue

        predios[predio_id] = {
            "tabla": table_name,
            "class": table_name,
            "object_ref": helper.identify(row) or predio_id,
        }

        add_predio_alias(predio_id, predio_id)
        for key in predio_keys(row):
            add_predio_alias(key, predio_id)

    if not predios:
        return issues

    for table_name, row in helper.iter_direcciones():
        predio_fk = field_value(row, predio_fk_fields)
        predio_id = resolve_predio_alias(predio_fk)
        if not predio_id:
            continue

        principal_match = helper._extract_field(
            row,
            principal_fields,
            require_value=False,
        )

        principal_field = principal_match[0] if principal_match else principal_fields[0]
        principal_raw = principal_match[1] if principal_match else None
        es_principal = parse_bool(principal_raw)

        direcciones_por_predio.setdefault(predio_id, []).append(
            {
                "tabla": table_name,
                "class": table_name,
                "campo": principal_field,
                "valor": principal_raw,
                "object_ref": helper.identify(row),
                "es_principal": es_principal,
                "campo_principal_existe": principal_match is not None,
            }
        )

    for predio_id, direcciones in direcciones_por_predio.items():
        total_direcciones = len(direcciones)
        if total_direcciones <= 1:
            continue

        if not any(d["campo_principal_existe"] for d in direcciones):
            continue

        total_principales = sum(1 for d in direcciones if d["es_principal"] is True)

        if total_principales != 1:
            predio_info = predios.get(
                predio_id,
                {
                    "tabla": "ARB_Predio",
                    "class": "ARB_Predio",
                    "object_ref": predio_id,
                },
            )

            issues.append(
                RuleIssue(
                    rule_id="1.39",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "Si un predio tiene más de una dirección asociada en ARB_Direccion, "
                        "debe existir una sola dirección principal."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "total_direcciones": total_direcciones,
                        "total_direcciones_principales": total_principales,
                        "valor_esperado": 1,
                    },
                )
            )

    return issues

def _rule_1_40(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    direccion_tables = ("ARB_Direccion", "arb_direccion", "ARB_Dirección", "arb_dirección")

    tipo_direccion_fields = (
        "tipo_direccion",
        "Tipo_Direccion",
    )

    clase_via_principal_fields = (
        "clase_via_principal",
        "Clase_Via_Principal",
    )

    valor_via_principal_fields = (
        "valor_via_principal",
        "Valor_Via_Principal",
    )

    valor_via_generadora_fields = (
        "valor_via_generadora",
        "Valor_Via_Generadora",
    )

    numero_predio_fields = (
        "numero_predio",
        "Numero_Predio",
    )

    nombre_predio_fields = (
        "nombre_predio",
        "Nombre_Predio",
    )

    predio_fk_fields = (
        "arb_predio_direccion",
    )

    def get_relation_value(row: dict[str, object], candidates: tuple[str, ...]) -> str | None:
        match = helper._extract_field(row, candidates, require_value=False)
        if not match:
            return None
        _, raw_value = match
        if raw_value in (None, ""):
            return None
        return str(raw_value).strip()

    def is_estructurada(value: object) -> bool:
        if value in (None, ""):
            return False
        text = str(value).strip().lower()
        text = (
            text.replace("á", "a")
            .replace("é", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ú", "u")
        )
        def is_estructurada(value: object) -> bool:
            if value in (None, ""):
                return False
            return str(value).strip() == "0"

    def is_empty(value: object) -> bool:
        return value is None or str(value).strip() == ""

    for table_name in direccion_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            tipo_match = helper._extract_field(
                row,
                tipo_direccion_fields,
                require_value=False,
            )
            if not tipo_match:
                continue

            tipo_field, tipo_raw = tipo_match
            if not is_estructurada(tipo_raw):
                continue

            clase_match = helper._extract_field(
                row,
                clase_via_principal_fields,
                require_value=False,
            )
            valor_principal_match = helper._extract_field(
                row,
                valor_via_principal_fields,
                require_value=False,
            )
            valor_generadora_match = helper._extract_field(
                row,
                valor_via_generadora_fields,
                require_value=False,
            )
            numero_match = helper._extract_field(
                row,
                numero_predio_fields,
                require_value=False,
            )
            nombre_match = helper._extract_field(
                row,
                nombre_predio_fields,
                require_value=False,
            )

            clase_raw = clase_match[1] if clase_match else None
            valor_principal_raw = valor_principal_match[1] if valor_principal_match else None
            valor_generadora_raw = valor_generadora_match[1] if valor_generadora_match else None
            numero_raw = numero_match[1] if numero_match else None
            nombre_raw = nombre_match[1] if nombre_match else None

            faltantes = []
            if is_empty(clase_raw):
                faltantes.append("clase_via_principal")
            if is_empty(valor_principal_raw):
                faltantes.append("valor_via_principal")
            if is_empty(valor_generadora_raw):
                faltantes.append("valor_via_generadora")
            if is_empty(numero_raw):
                faltantes.append("numero_predio")

            nombre_diligenciado = not is_empty(nombre_raw)

            if faltantes or nombre_diligenciado:
                predio_id = get_relation_value(row, predio_fk_fields)

                issues.append(
                    RuleIssue(
                        rule_id="1.40",
                        object_ref=helper.identify(row) or predio_id,
                        message=(
                            "Si el tipo de dirección es Estructurada, los campos "
                            "clase_via_principal, valor_via_principal, "
                            "valor_via_generadora y numero_predio deben estar "
                            "diligenciados, y nombre_predio no debe estar diligenciado."
                        ),
                        details={
                            "tabla": table_name,
                            "class": table_name,
                            "predio_id": predio_id,
                            "campo_tipo_direccion": tipo_field,
                            "tipo_direccion": tipo_raw,
                            "faltantes": faltantes,
                            "nombre_predio": nombre_raw,
                            "nombre_predio_debe_estar_vacio": True,
                        },
                    )
                )

    return issues

def _rule_1_41(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    direccion_tables = ("ARB_Direccion", "arb_direccion", "ARB_Dirección", "arb_dirección")

    tipo_direccion_fields = (
        "tipo_direccion",
        "Tipo_Direccion",
    )

    nombre_predio_fields = (
        "nombre_predio",
        "Nombre_Predio",
    )

    complemento_fields = (
        "complemento",
        "Complemento",
    )

    codigo_postal_fields = (
        "codigo_postal",
        "Codigo_Postal",
    )

    clase_via_principal_fields = (
        "clase_via_principal",
        "Clase_Via_Principal",
    )

    valor_via_principal_fields = (
        "valor_via_principal",
        "Valor_Via_Principal",
    )

    letra_via_principal_fields = (
        "letra_via_principal",
        "Letra_Via_Principal",
    )

    letra_via_generadora_fields = (
        "letra_via_generadora",
        "Letra_Via_Generadora",
    )

    sector_ciudad_fields = (
        "sector_ciudad",
        "Sector_Ciudad",
    )

    valor_via_generadora_fields = (
        "valor_via_generadora",
        "Valor_Via_Generadora",
    )

    numero_predio_fields = (
        "numero_predio",
        "Numero_Predio",
    )

    sector_predio_fields = (
        "sector_predio",
        "Sector_Predio",
    )

    predio_fk_fields = (
        "arb_predio_direccion",
        "predio",
        "arb_predio",
    )

    def get_relation_value(row: dict[str, object], candidates: tuple[str, ...]) -> str | None:
        match = helper._extract_field(row, candidates, require_value=False)
        if not match:
            return None
        _, raw_value = match
        if raw_value in (None, ""):
            return None
        return str(raw_value).strip()

    def is_no_estructurada(value: object) -> bool:
        if value in (None, ""):
            return False
        text = str(value).strip()
        # dominio confirmado:
        # 1 = No_Estructurada
        # 0 = Estructurada
        return text == "1"

    def is_empty(value: object) -> bool:
        return value is None or str(value).strip() == ""

    for table_name in direccion_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            tipo_match = helper._extract_field(
                row,
                tipo_direccion_fields,
                require_value=False,
            )
            if not tipo_match:
                continue

            tipo_field, tipo_raw = tipo_match
            if not is_no_estructurada(tipo_raw):
                continue

            nombre_match = helper._extract_field(
                row,
                nombre_predio_fields,
                require_value=False,
            )
            complemento_match = helper._extract_field(
                row,
                complemento_fields,
                require_value=False,
            )
            codigo_postal_match = helper._extract_field(
                row,
                codigo_postal_fields,
                require_value=False,
            )
            clase_match = helper._extract_field(
                row,
                clase_via_principal_fields,
                require_value=False,
            )
            valor_principal_match = helper._extract_field(
                row,
                valor_via_principal_fields,
                require_value=False,
            )
            letra_principal_match = helper._extract_field(
                row,
                letra_via_principal_fields,
                require_value=False,
            )
            letra_generadora_match = helper._extract_field(
                row,
                letra_via_generadora_fields,
                require_value=False,
            )
            sector_ciudad_match = helper._extract_field(
                row,
                sector_ciudad_fields,
                require_value=False,
            )
            valor_generadora_match = helper._extract_field(
                row,
                valor_via_generadora_fields,
                require_value=False,
            )
            numero_match = helper._extract_field(
                row,
                numero_predio_fields,
                require_value=False,
            )
            sector_predio_match = helper._extract_field(
                row,
                sector_predio_fields,
                require_value=False,
            )

            nombre_raw = nombre_match[1] if nombre_match else None
            complemento_raw = complemento_match[1] if complemento_match else None
            codigo_postal_raw = codigo_postal_match[1] if codigo_postal_match else None
            clase_raw = clase_match[1] if clase_match else None
            valor_principal_raw = valor_principal_match[1] if valor_principal_match else None
            letra_principal_raw = letra_principal_match[1] if letra_principal_match else None
            letra_generadora_raw = letra_generadora_match[1] if letra_generadora_match else None
            sector_ciudad_raw = sector_ciudad_match[1] if sector_ciudad_match else None
            valor_generadora_raw = valor_generadora_match[1] if valor_generadora_match else None
            numero_raw = numero_match[1] if numero_match else None
            sector_predio_raw = sector_predio_match[1] if sector_predio_match else None

            nombre_vacio = is_empty(nombre_raw)

            campos_indebidos = []
            if not is_empty(complemento_raw):
                campos_indebidos.append("complemento")
            if not is_empty(codigo_postal_raw):
                campos_indebidos.append("codigo_postal")
            if not is_empty(clase_raw):
                campos_indebidos.append("clase_via_principal")
            if not is_empty(valor_principal_raw):
                campos_indebidos.append("valor_via_principal")
            if not is_empty(letra_principal_raw):
                campos_indebidos.append("letra_via_principal")
            if not is_empty(letra_generadora_raw):
                campos_indebidos.append("letra_via_generadora")
            if not is_empty(sector_ciudad_raw):
                campos_indebidos.append("sector_ciudad")
            if not is_empty(valor_generadora_raw):
                campos_indebidos.append("valor_via_generadora")
            if not is_empty(numero_raw):
                campos_indebidos.append("numero_predio")
            if not is_empty(sector_predio_raw):
                campos_indebidos.append("sector_predio")

            if nombre_vacio or campos_indebidos:
                predio_id = get_relation_value(row, predio_fk_fields)

                issues.append(
                    RuleIssue(
                        rule_id="1.41",
                        object_ref=helper.identify(row) or predio_id,
                        message=(
                            "Si el tipo de dirección es No_Estructurada, únicamente "
                            "el campo nombre_predio debe estar diligenciado."
                        ),
                        details={
                            "tabla": table_name,
                            "class": table_name,
                            "predio_id": predio_id,
                            "campo_tipo_direccion": tipo_field,
                            "tipo_direccion": tipo_raw,
                            "nombre_predio": nombre_raw,
                            "nombre_predio_requerido": True,
                            "campos_indebidos": campos_indebidos,
                        },
                    )
                )

    return issues

def _rule_1_42(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    direccion_tables = ("ARB_Direccion", "arb_direccion", "ARB_Dirección", "arb_dirección")
    direccion_tipo_tables = ("ARB_DireccionTipo", "arb_direcciontipo")

    numero_predial_fields = (
        "Numero_Predial_Nacional",
        "numero_predial_nacional",
        "numero_predial",
        "Numero_Predial",
    )

    tipo_direccion_fields = (
        "tipo_direccion",
        "Tipo_Direccion",
    )

    predio_fk_fields = (
        "arb_predio_direccion",
    )

    def is_empty(value: object) -> bool:
        return value is None or str(value).strip() == ""

    def expected_tipo_direccion(numero: str) -> str | None:
        if len(numero) < 7:
            return None
        digitos_6_7 = numero[5:7]
        if digitos_6_7 == "00":
            return "1"  # No_Estructurada
        return "0"      # Estructurada

    tipo_direccion_catalog_aliases: dict[str, str] = {}

    def normalized_tipo_key(value: object) -> str:
        text = str(value).strip().lower()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.replace(" ", "_").replace("-", "_")
        return re.sub(r"[^a-z0-9_]", "", text)

    def add_tipo_direccion_alias(value: object, normalized_value: str) -> None:
        if value in (None, "") or normalized_value not in {"0", "1"}:
            return
        text = str(value).strip()
        if not text:
            return
        tipo_direccion_catalog_aliases[text] = normalized_value
        tipo_direccion_catalog_aliases[normalized_tipo_key(text)] = normalized_value

    def normalize_tipo_direccion(value: object) -> str:
        if value in (None, ""):
            return ""

        raw_text = str(value).strip()
        text = normalized_tipo_key(raw_text)
        compact_text = re.sub(r"[^a-z0-9]", "", text)

        aliases = {
            "0": "0",  # itfCode Estructurada
            "2": "0",  # T_Id estandar ARB_DireccionTipo: Estructurada
            "estructurada": "0",
            "1": "1",  # itfCode y T_Id No_Estructurada
            "no_estructurada": "1",
            "noestructurada": "1",
        }
        if text in aliases:
            return aliases[text]
        if raw_text in tipo_direccion_catalog_aliases:
            return tipo_direccion_catalog_aliases[raw_text]
        if text in tipo_direccion_catalog_aliases:
            return tipo_direccion_catalog_aliases[text]

        # QGIS puede entregar el valor como etiqueta de dominio completa
        # (p. ej. ARB_DireccionTipo_Estructurada) en vez del codigo corto.
        if "noestructurada" in compact_text or "noestructurado" in compact_text:
            return "1"
        if "estructurada" in compact_text or "estructurado" in compact_text:
            return "0"

        return str(value).strip()

    def load_tipo_direccion_catalog_aliases() -> None:
        for table_name in direccion_tipo_tables:
            if not dataset.has_table(table_name):
                continue

            for row in dataset.get_records(table_name):
                itfcode = helper.get_field_value(row, ("itfcode", "ItfCode", "ITFCODE"))
                ilicode = helper.get_field_value(row, ("ilicode", "iliCode", "IliCode", "ILICODE"))
                dispname = helper.get_field_value(row, ("dispname", "DispName", "DISPNAME"))
                description = helper.get_field_value(row, ("description", "Description", "DESCRIPCION"))

                normalized_catalog_value = ""
                itfcode_text = "" if itfcode in (None, "") else str(itfcode).strip()
                if itfcode_text in {"0", "1"}:
                    normalized_catalog_value = itfcode_text
                else:
                    for candidate in (ilicode, dispname, description):
                        normalized_candidate = normalize_tipo_direccion(candidate)
                        if normalized_candidate in {"0", "1"}:
                            normalized_catalog_value = normalized_candidate
                            break

                if not normalized_catalog_value:
                    continue

                for field in (
                    "t_id",
                    "T_Id",
                    "T_ID",
                    "tid",
                    "TID",
                    "itfcode",
                    "ItfCode",
                    "ilicode",
                    "iliCode",
                    "dispname",
                    "DispName",
                    "description",
                    "Description",
                ):
                    value = row.get(field)
                    add_tipo_direccion_alias(value, normalized_catalog_value)

    def raw_tipo_direccion_value(row: dict[str, object], field_name: str) -> object | None:
        raw_match = helper._extract_field(
            row,
            (
                f"{field_name}__raw",
                "tipo_direccion__raw",
                "Tipo_Direccion__raw",
            ),
            require_value=False,
        )
        if not raw_match:
            return None
        return raw_match[1]

    def tipo_direccion_desc(value: str) -> str:
        return {
            "0": "Estructurada",
            "1": "No_Estructurada",
        }.get(value, "Desconocido")

    def predio_keys(row: dict[str, object]) -> set[str]:
        keys: set[str] = set()
        for field in (
            "T_Id",
            "t_id",
            "TID",
            "tid",
            "id_operacion",
            "Id_Operacion",
            "ID_OPERACION",
            "numero_predial",
            "Numero_Predial",
            "Numero_Predial_Nacional",
        ):
            value = row.get(field)
            if value not in (None, ""):
                keys.add(str(value).strip())
        object_ref = helper.identify(row)
        if object_ref:
            keys.add(str(object_ref).strip())
        return keys

    def normalized_relation_key(value: object) -> str:
        text = str(value).strip().lower()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        return re.sub(r"[^a-z0-9]", "", text)

    def add_predio_alias(alias: object, predio_id: str) -> None:
        if alias in (None, ""):
            return
        alias_text = str(alias).strip()
        if not alias_text:
            return
        predio_key_aliases[alias_text] = predio_id
        alias_norm = normalized_relation_key(alias_text)
        if alias_norm:
            predio_key_aliases.setdefault(alias_norm, predio_id)

    def resolve_predio_alias(value: object) -> str:
        value_text = str(value).strip()
        if value_text in predio_key_aliases:
            return predio_key_aliases[value_text]
        value_norm = normalized_relation_key(value_text)
        if value_norm in predio_key_aliases:
            return predio_key_aliases[value_norm]
        for alias, canonical_id in predio_key_aliases.items():
            alias_norm = normalized_relation_key(alias)
            if len(alias_norm) >= 4 and alias_norm in value_norm:
                return canonical_id
        return value_text

    direcciones_por_predio: dict[str, list[dict[str, object]]] = {}
    predio_key_aliases: dict[str, str] = {}

    load_tipo_direccion_catalog_aliases()

    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = helper.get_field_value(row, ("t_id", "T_ID", "tid", "TID"))
            if not predio_id:
                predio_id = helper.identify(row)
            if not predio_id:
                continue
            for key in predio_keys(row):
                add_predio_alias(key, str(predio_id))

    for table_name in direccion_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = helper.get_field_value(row, predio_fk_fields)
            if not predio_id:
                continue

            predio_id = resolve_predio_alias(predio_id)
            direcciones_por_predio.setdefault(str(predio_id), []).append(row)

    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = helper.get_field_value(row, ("t_id", "T_ID", "tid", "TID"))
            if not predio_id:
                predio_id = helper.identify(row)

            numero = helper.get_field_value(row, numero_predial_fields)
            if is_empty(numero):
                continue

            numero = str(numero).strip()
            tipo_esperado = expected_tipo_direccion(numero)
            if not tipo_esperado:
                continue

            digitos_6_7 = numero[5:7]
            direcciones = direcciones_por_predio.get(str(predio_id), [])

            # Ajuste: si no tiene direcciones, no reporta error
            if not direcciones:
                continue

            for direccion_row in direcciones:
                tipo_match = helper._extract_field(
                    direccion_row,
                    tipo_direccion_fields,
                    require_value=False,
                )
                if not tipo_match:
                    continue

                tipo_field, tipo_direccion = tipo_match
                tipo_direccion_raw = raw_tipo_direccion_value(direccion_row, tipo_field)

                # Ajuste: si tipo_direccion está vacío, no reporta error
                if is_empty(tipo_direccion) and is_empty(tipo_direccion_raw):
                    continue

                tipo_encontrado = normalize_tipo_direccion(tipo_direccion)
                if tipo_encontrado not in {"0", "1"} and not is_empty(tipo_direccion_raw):
                    tipo_encontrado = normalize_tipo_direccion(tipo_direccion_raw)

                if tipo_encontrado != tipo_esperado:
                    issues.append(
                        helper.make_issue(
                            direccion_row,
                            rule_id="1.42",
                            message=(
                                "Los dígitos 6 y 7 del número predial nacional no corresponden con el tipo de dirección."
                            ),
                            details={
                                "tabla": "ARB_Direccion",
                                "campo": "tipo_direccion",
                                "class": "ARB_Direccion",
                                "predio_id": predio_id,
                                "numero_predial": numero,
                                "digitos_6_7": digitos_6_7,
                                "tipo_direccion_encontrado": tipo_encontrado,
                                "tipo_direccion_original": tipo_direccion,
                                "tipo_direccion_raw": tipo_direccion_raw,
                                "tipo_direccion_encontrado_desc": tipo_direccion_desc(tipo_encontrado),
                                "tipo_direccion_esperado": tipo_esperado,
                                "tipo_direccion_esperado_desc": tipo_direccion_desc(tipo_esperado),
                            },
                        )
                    )

    return issues

def _rule_1_43(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    direccion_tables = ("ARB_Direccion", "arb_direccion", "ARB_Dirección", "arb_dirección")

    tipo_direccion_fields = (
        "tipo_direccion",
        "Tipo_Direccion",
    )

    letra_via_principal_fields = (
        "letra_via_principal",
        "Letra_Via_Principal",
    )

    letra_via_generadora_fields = (
        "letra_via_generadora",
        "Letra_Via_Generadora",
    )

    predio_fk_fields = (
        "arb_predio_direccion",
    )

    def get_relation_value(row: dict[str, object], candidates: tuple[str, ...]) -> str | None:
        match = helper._extract_field(row, candidates, require_value=False)
        if not match:
            return None
        _, raw_value = match
        if raw_value in (None, ""):
            return None
        return str(raw_value).strip()

    def is_estructurada(value: object) -> bool:
        if value in (None, ""):
            return False
        return str(value).strip() == "0"  # dominio confirmado: 0 = Estructurada

    def is_empty(value: object) -> bool:
        return value is None or str(value).strip() == ""

    def is_alpha_value(value: object) -> bool:
        if is_empty(value):
            return True

        text = str(value).strip()
        normalized = (
            text.replace("á", "a")
            .replace("é", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ú", "u")
            .replace("Á", "A")
            .replace("É", "E")
            .replace("Í", "I")
            .replace("Ó", "O")
            .replace("Ú", "U")
            .replace("ñ", "n")
            .replace("Ñ", "N")
        )

        return normalized.isalpha()

    for table_name in direccion_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            tipo_match = helper._extract_field(
                row,
                tipo_direccion_fields,
                require_value=False,
            )
            if not tipo_match:
                continue

            tipo_field, tipo_raw = tipo_match
            if not is_estructurada(tipo_raw):
                continue

            letra_principal_match = helper._extract_field(
                row,
                letra_via_principal_fields,
                require_value=False,
            )
            letra_generadora_match = helper._extract_field(
                row,
                letra_via_generadora_fields,
                require_value=False,
            )

            letra_principal_raw = letra_principal_match[1] if letra_principal_match else None
            letra_generadora_raw = letra_generadora_match[1] if letra_generadora_match else None

            campos_invalidos = []

            if not is_empty(letra_principal_raw) and not is_alpha_value(letra_principal_raw):
                campos_invalidos.append("letra_via_principal")

            if not is_empty(letra_generadora_raw) and not is_alpha_value(letra_generadora_raw):
                campos_invalidos.append("letra_via_generadora")

            if campos_invalidos:
                predio_id = get_relation_value(row, predio_fk_fields)

                issues.append(
                    RuleIssue(
                        rule_id="1.43",
                        object_ref=helper.identify(row) or predio_id,
                        message=(
                            "Si una dirección es estructurada y tiene valores en "
                            "letra_via_principal y/o letra_via_generadora, estos deben ser alfabéticos."
                        ),
                        details={
                            "tabla": table_name,
                            "class": table_name,
                            "predio_id": predio_id,
                            "campo_tipo_direccion": tipo_field,
                            "tipo_direccion": tipo_raw,
                            "letra_via_principal": letra_principal_raw,
                            "letra_via_generadora": letra_generadora_raw,
                            "campos_invalidos": campos_invalidos,
                        },
                    )
                )

    return issues

def _rule_1_44(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")

    nombres_fields = (
        "nombres_apellidos_quien_atendio",
        "Nombres_Apellidos_Quien_Atendio",
    )

    tipo_documento_fields = (
        "tipo_documento_quien_atendio",
        "Tipo_Documento_Quien_Atendio",
    )

    numero_documento_fields = (
        "numero_documento_quien_atendio",
        "Numero_Documento_Quien_Atendio",
    )

    NIT_CODE = "2"

    def is_empty(value: object) -> bool:
        return value is None or str(value).strip() == ""

    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            object_ref = helper.identify(row)

            nombres_match = helper._extract_field(
                row,
                nombres_fields,
                require_value=False,
            )
            if not nombres_match:
                continue

            nombres_field, nombres_raw = nombres_match
            nombres_val = "" if nombres_raw in (None, "") else str(nombres_raw).strip()

            if not nombres_val:
                continue

            tipo_match = helper._extract_field(
                row,
                tipo_documento_fields,
                require_value=False,
            )

            if not tipo_match:
                issues.append(
                    RuleIssue(
                        rule_id="1.44",
                        object_ref=object_ref,
                        message=(
                            "Si existe registro en contacto visita, "
                            "tipo_documento_quien_atendio debe estar diligenciado "
                            "y no puede corresponder a NIT."
                        ),
                        details={
                            "tabla": table_name,
                            "campo": tipo_documento_fields[0],
                            "class": table_name,
                            "nombres_apellidos_quien_atendio": nombres_val,
                            "tipo_documento_esperado_distinto_de": "NIT",
                            "valor_prohibido": NIT_CODE,
                        },
                    )
                )
                continue

            tipo_field, tipo_raw = tipo_match
            tipo_val = "" if tipo_raw in (None, "") else str(tipo_raw).strip()

            if not tipo_val:
                issues.append(
                    RuleIssue(
                        rule_id="1.44",
                        object_ref=object_ref,
                        message=(
                            "Si existe registro en contacto visita, "
                            "tipo_documento_quien_atendio debe estar diligenciado "
                            "y no puede corresponder a NIT."
                        ),
                        details={
                            "tabla": table_name,
                            "campo": tipo_field,
                            "class": table_name,
                            "nombres_apellidos_quien_atendio": nombres_val,
                            "tipo_documento_esperado_distinto_de": "NIT",
                            "valor_prohibido": NIT_CODE,
                        },
                    )
                )
                continue

            if tipo_val == NIT_CODE:
                numero_match = helper._extract_field(
                    row,
                    numero_documento_fields,
                    require_value=False,
                )
                numero_raw = numero_match[1] if numero_match else None

                issues.append(
                    RuleIssue(
                        rule_id="1.44",
                        object_ref=object_ref,
                        message=(
                            "Si existe registro en contacto visita, "
                            "tipo_documento_quien_atendio no puede corresponder a NIT."
                        ),
                        details={
                            "tabla": table_name,
                            "campo": tipo_field,
                            "class": table_name,
                            "nombres_apellidos_quien_atendio": nombres_val,
                            "tipo_documento_quien_atendio": tipo_val,
                            "tipo_documento_quien_atendio_desc": "NIT",
                            "numero_documento_quien_atendio": numero_raw,
                            "valor_prohibido": NIT_CODE,
                        },
                    )
                )

    return issues

def _rule_1_45(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")

    nombres_fields = (
        "nombres_apellidos_quien_atendio",
        "Nombres_Apellidos_Quien_Atendio",
    )

    numero_documento_fields = (
        "numero_documento_quien_atendio",
        "Numero_Documento_Quien_Atendio",
    )

    def is_empty(value: object) -> bool:
        return value is None or str(value).strip() == ""

    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            object_ref = helper.identify(row)

            nombres_match = helper._extract_field(
                row,
                nombres_fields,
                require_value=False,
            )
            if not nombres_match:
                continue

            _, nombres_raw = nombres_match
            nombres_val = "" if nombres_raw in (None, "") else str(nombres_raw).strip()

            if not nombres_val:
                continue

            numero_match = helper._extract_field(
                row,
                numero_documento_fields,
                require_value=False,
            )

            if not numero_match:
                issues.append(
                    RuleIssue(
                        rule_id="1.45",
                        object_ref=object_ref,
                        message=(
                            "Si existe registro en contacto visita, "
                            "numero_documento_quien_atendio debe estar diligenciado "
                            "y contener solamente caracteres numéricos."
                        ),
                        details={
                            "tabla": table_name,
                            "campo": numero_documento_fields[0],
                            "class": table_name,
                            "nombres_apellidos_quien_atendio": nombres_val,
                        },
                    )
                )
                continue

            numero_field, numero_raw = numero_match
            numero_val = "" if numero_raw in (None, "") else str(numero_raw).strip()

            if not numero_val:
                issues.append(
                    RuleIssue(
                        rule_id="1.45",
                        object_ref=object_ref,
                        message=(
                            "Si existe registro en contacto visita, "
                            "numero_documento_quien_atendio debe estar diligenciado "
                            "y contener solamente caracteres numéricos."
                        ),
                        details={
                            "tabla": table_name,
                            "campo": numero_field,
                            "class": table_name,
                            "nombres_apellidos_quien_atendio": nombres_val,
                            "numero_documento_quien_atendio": numero_raw,
                        },
                    )
                )
                continue

            if not numero_val.isdigit():
                issues.append(
                    RuleIssue(
                        rule_id="1.45",
                        object_ref=object_ref,
                        message=(
                            "Si existe registro en contacto visita, "
                            "el número de documento de quien atendió debe contener "
                            "solamente caracteres numéricos."
                        ),
                        details={
                            "tabla": table_name,
                            "campo": numero_field,
                            "class": table_name,
                            "nombres_apellidos_quien_atendio": nombres_val,
                            "numero_documento_quien_atendio": numero_val,
                        },
                    )
                )

    return issues



def _rule_1_46(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")

    correo_fields = (
        "correo_electronico",
        "Correo_Electronico",
    )

    email_regex = re.compile(
        r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z][a-zA-Z]*$"
    )

    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            object_ref = helper.identify(row)

            correo_match = helper._extract_field(
                row,
                correo_fields,
                require_value=False,
            )

            if not correo_match:
                continue

            correo_field, correo_raw = correo_match

            if correo_raw is None:
                continue

            correo_val = str(correo_raw).strip()

            if not correo_val:
                continue

            if not email_regex.match(correo_val):
                issues.append(
                    RuleIssue(
                        rule_id="1.46",
                        object_ref=object_ref,
                        message=(
                            "El correo electrónico de la persona que atendió la visita "
                            "no tiene una estructura lógica usuario@dominio."
                        ),
                        details={
                            "tabla": table_name,
                            "campo": correo_field,
                            "class": table_name,
                            "correo_electronico": correo_val,
                        },
                    )
                )

    return issues

def _rule_1_47(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")

    autoriza_fields = (
        "autoriza_notificaciones",
        "Autoriza_Notificaciones",
    )

    celular_fields = (
        "celular",
        "Celular",
    )

    correo_fields = (
        "correo_electronico",
        "Correo_Electronico",
    )

    def is_empty(value: object) -> bool:
        return value is None or str(value).strip() == ""

    def is_true(value: object) -> bool:
        if value in (None, ""):
            return False
        return str(value).strip().lower() in ("true", "1", "t")

    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            object_ref = helper.identify(row)

            autoriza_match = helper._extract_field(
                row,
                autoriza_fields,
                require_value=False,
            )

            if not autoriza_match:
                continue

            autoriza_field, autoriza_raw = autoriza_match

            if not is_true(autoriza_raw):
                continue

            celular = helper.get_field_value(row, celular_fields)
            correo = helper.get_field_value(row, correo_fields)

            celular_vacio = is_empty(celular)
            correo_vacio = is_empty(correo)

            if celular_vacio and correo_vacio:
                issues.append(
                    RuleIssue(
                        rule_id="1.47",
                        object_ref=object_ref,
                        message=(
                            "Si autoriza_notificaciones es verdadero, debe diligenciarse "
                            "al menos uno de los campos celular y/o correo_electronico."
                        ),
                        details={
                            "tabla": table_name,
                            "campo": autoriza_field,
                            "class": table_name,
                            "autoriza_notificaciones": autoriza_raw,
                            "celular": celular,
                            "correo_electronico": correo,
                        },
                    )
                )

    return issues

def _rule_1_48(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")

    domicilio_fields = (
        "domicilio_notificaciones",
        "Domicilio_Notificaciones",
    )

    def is_empty(value: object) -> bool:
        return value is None or str(value).strip() == ""

    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            object_ref = helper.identify(row)

            domicilio_match = helper._extract_field(
                row,
                domicilio_fields,
                require_value=False,
            )

            if not domicilio_match:
                continue

            domicilio_field, domicilio_raw = domicilio_match

            if is_empty(domicilio_raw):
                continue

            domicilio_val = str(domicilio_raw).strip()

            if len(domicilio_val) < 7:
                issues.append(
                    RuleIssue(
                        rule_id="1.48",
                        object_ref=object_ref,
                        message=(
                            "El campo domicilio_notificaciones debe tener al menos 7 caracteres."
                        ),
                        details={
                            "tabla": table_name,
                            "campo": domicilio_field,
                            "class": table_name,
                            "domicilio_notificaciones": domicilio_val,
                            "longitud": len(domicilio_val),
                            "longitud_minima": 7,
                        },
                    )
                )

    return issues

def _rule_1_49(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    predio_tables = ("ARB_Predio", "arb_predio")
    direccion_tables = ("ARB_Direccion", "arb_direccion", "ARB_Dirección", "arb_dirección")

    condicion_fields = (
        "Condicion_Predio",
        "condicion_predio",
        "condicion_predio_nombre",
        "Condicion",
    )

    complemento_fields = (
        "complemento",
        "Complemento",
    )

    allowed_tokens = (
        "AP", "BQ", "BD", "CS", "ED", "ET", "GA", "IN",
        "L", "LO", "MZ", "OF", "PQ", "PN", "TO", "UN", "UR",
    )

    target_conditions = {
        "PH_UNIDAD_PREDIAL",
        "CONDOMINIO_UNIDAD_PREDIAL",
    }

    def get_t_id(row: dict[str, object]) -> str | None:
        for key, value in row.items():
            if str(key).lower() == "t_id" and value not in (None, ""):
                return str(value).strip()
        return None

    def is_empty(value: object) -> bool:
        return value is None or str(value).strip() == ""

    predios_objetivo: dict[str, dict[str, object]] = {}
    direcciones_por_predio: dict[str, list[dict[str, object]]] = {}

    # 1. Identificar predios con condición objetivo
    for table_name in predio_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_id = get_t_id(row)
            if not predio_id:
                continue

            condicion_match = helper._extract_field(
                row,
                condicion_fields,
                require_value=False,
            )
            if not condicion_match:
                continue

            condicion_field, condicion_raw = condicion_match
            condicion_str = "" if condicion_raw in (None, "") else str(condicion_raw).strip()
            if not condicion_str:
                continue

            condicion_norm = _normalize_condicion(condicion_str)
            if condicion_norm not in target_conditions:
                continue

            numero = helper.get_field_value(row, helper.NUMERO_PREDIAL_FIELDS)

            predios_objetivo[predio_id] = {
                "tabla": table_name,
                "campo": condicion_field,
                "class": table_name,
                "object_ref": helper.identify(row),
                "predio_id": predio_id,
                "numero_predial": numero,
                "condicion_predio": condicion_str,
                "condicion_predio_norm": condicion_norm,
            }

    if not predios_objetivo:
        return issues

    # 2. Agrupar direcciones por predio usando la FK real
    for table_name in direccion_tables:
        if not dataset.has_table(table_name):
            continue

        for row in dataset.get_records(table_name):
            predio_fk = helper.get_field_value(row, ("arb_predio_direccion",))
            if not predio_fk:
                continue

            complemento_match = helper._extract_field(
                row,
                complemento_fields,
                require_value=False,
            )
            complemento_field = complemento_match[0] if complemento_match else complemento_fields[0]
            complemento_raw = complemento_match[1] if complemento_match else None

            direcciones_por_predio.setdefault(predio_fk, []).append(
                {
                    "tabla": table_name,
                    "campo": complemento_field,
                    "class": table_name,
                    "object_ref": helper.identify(row),
                    "complemento": complemento_raw,
                }
            )

    # 3. Validar complemento
    for predio_id, predio_info in predios_objetivo.items():
        direcciones = direcciones_por_predio.get(predio_id, [])

        if not direcciones:
            issues.append(
                RuleIssue(
                    rule_id="1.49",
                    object_ref=predio_info["object_ref"],
                    message=(
                        "El predio con condición PH.Unidad_Predial o "
                        "Condominio.Unidad_Predial no tiene dirección asociada."
                    ),
                    details={
                        "tabla": predio_info["tabla"],
                        "campo": predio_info["campo"],
                        "class": predio_info["class"],
                        "predio_id": predio_id,
                        "numero_predial": predio_info["numero_predial"],
                        "condicion_predio": predio_info["condicion_predio"],
                    },
                )
            )
            continue

        for direccion in direcciones:
            complemento_raw = direccion["complemento"]
            complemento_str = "" if complemento_raw in (None, "") else str(complemento_raw).upper().strip()

            contains_allowed = any(token in complemento_str for token in allowed_tokens)

            if is_empty(complemento_raw) or not contains_allowed:
                issues.append(
                    RuleIssue(
                        rule_id="1.49",
                        object_ref=predio_info["object_ref"],
                        message=(
                            "Para predios con condición PH.Unidad_Predial o "
                            "Condominio.Unidad_Predial, la dirección asociada debe "
                            "contener en el campo complemento al menos AP, BQ, BD, "
                            "CS, ED, ET, GA, IN, L, LO, MZ, OF, PQ, PN, TO, UN o UR."
                        ),
                        details={
                            "tabla": direccion["tabla"],
                            "campo": direccion["campo"],
                            "class": direccion["class"],
                            "predio_id": predio_id,
                            "numero_predial": predio_info["numero_predial"],
                            "condicion_predio": predio_info["condicion_predio"],
                            "complemento": complemento_raw,
                            "valores_permitidos": list(allowed_tokens),
                        },
                    )
                )

    return issues

RULE_FUNCTIONS = {
    "1.1": _rule_1_1,
    "1.2": _rule_1_2,
    "1.3": _rule_1_3,
    "1.4": _rule_1_4,
    "1.5": _rule_1_5,
    "1.6": _rule_1_6,
    "1.7": _rule_1_7,
    "1.8": _rule_1_8,
    "1.9": _rule_1_9,
    "1.10": _rule_1_10,
    "1.11": _rule_1_11,
    "1.12": _rule_1_12,
    "1.13": _rule_1_13,
    "1.14": _rule_1_14,
    "1.15": _rule_1_15,
    "1.16": _rule_1_16,
    "1.17": _rule_1_17,
    "1.18": _rule_1_18,
    "1.19": _rule_1_19,
    "1.20": _rule_1_20,
    "1.21": _rule_1_21,
    "1.22": _rule_1_22,
    "1.23": _rule_1_23,
    "1.24": _rule_1_24,
    "1.25": _rule_1_25,
    "1.26": _rule_1_26,
    "1.27": _rule_1_27,
    "1.28": _rule_1_28,
    "1.29": _rule_1_29,
    "1.30": _rule_1_30,
    "1.31": _rule_1_31,
    "1.32": _rule_1_32,
    "1.33": _rule_1_33,
    "1.34": _rule_1_34,
    "1.35": _rule_1_35,
    "1.36": _rule_1_36,
    "1.37": _rule_1_37,
    "1.38": _rule_1_38,
    "1.39": _rule_1_39,
    "1.40": _rule_1_40,
    "1.41": _rule_1_41,
    "1.42": _rule_1_42,
    "1.43": _rule_1_43,
    "1.44": _rule_1_44,
    "1.45": _rule_1_45,
    "1.46": _rule_1_46,
    "1.47": _rule_1_47,
    "1.48": _rule_1_48,
    "1.49": _rule_1_49,
}

__all__ = [
    "COMPONENT_SLUG",
    "DEFAULT_RULE_IDS",
    "RULE_FUNCTIONS",
]

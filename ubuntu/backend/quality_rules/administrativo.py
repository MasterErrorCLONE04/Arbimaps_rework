from __future__ import annotations
import re
import unicodedata
from .base import DatasetReader, RuleIssue
from .municipality_context import get_dataset_municipality_context

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
        "t_ili_tid",
        "T_Ili_Tid",
        "T_ILI_TID",
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
        # Se prioriza el identificador INTERLIS estable: TID en XTF y
        # t_ili_tid después de materializarlo en QGIS. Así el AID es comparable.
        preferred_fields = (
            "t_ili_tid", "T_Ili_Tid", "T_ILI_TID", "TID", "tid",
            "id_operacion", "Id_Operacion", "ID_OPERACION",
            "id_predio", "ID_PREDIO", "predio_id", "Predio_ID",
            "id", "ID", "local_id", "Local_ID", "t_id", "T_ID",
        )
        for field in preferred_fields:
            value = row.get(field)
            if not self._is_empty(value):
                return str(value).strip()
        normalized_targets = {self._normalize_key(field) for field in preferred_fields}
        for key, candidate in row.items():
            if self._normalize_key(str(key)) in normalized_targets and not self._is_empty(candidate):
                return str(candidate).strip()
        for key, candidate in row.items():
            if "idoperacion" in self._normalize_key(str(key)) and not self._is_empty(candidate):
                return str(candidate).strip()
        for field in self.NUMERO_PREDIAL_FIELDS:
            value = row.get(field)
            if not self._is_empty(value):
                return str(value).strip()
        normalized_fallbacks = {self._normalize_key(field) for field in self.NUMERO_PREDIAL_FIELDS}
        for key, candidate in row.items():
            if self._normalize_key(str(key)) in normalized_fallbacks and not self._is_empty(candidate):
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
    @staticmethod
    def _normalize_key(name: str) -> str:
        text = str(name).strip()
        # Tolera nombres históricos que pudieron quedar mal decodificados.
        replacements = {
            "Ã¡": "á", "Ã©": "é", "Ã­": "í", "Ã³": "ó", "Ãº": "ú", "Ã±": "ñ",
            "ÃƒÂ¡": "á", "ÃƒÂ©": "é", "ÃƒÂ­": "í", "ÃƒÂ³": "ó", "ÃƒÂº": "ú", "ÃƒÂ±": "ñ",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        text = unicodedata.normalize("NFKD", text.lower())
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        return "".join(ch for ch in text if ch.isalnum())


    @staticmethod
    @staticmethod
    def _is_empty(value: object) -> bool:
        if value is None:
            return True
        if isinstance(value, float) and value != value:
            return True
        if isinstance(value, str):
            return value.strip().lower() in {"", "null", "none", "nan", "n/a", "na"}
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


def _get_t_id(row: dict[str, object]) -> str | None:
    match = NumeroPredialHelper._extract_field(
        row,
        ("t_id", "T_ID", "tid", "TID"),
        require_value=True,
    )
    if not match:
        return None

    _, value = match
    return str(value).strip()


def _required_field_value(
    helper: NumeroPredialHelper,
    row: dict[str, object],
    issues: list[RuleIssue],
    *,
    rule_id: str,
    table_name: str,
    candidates: tuple[str, ...],
    field_label: str,
    message: str,
    details: dict[str, object] | None = None,
) -> tuple[str, object, str] | None:
    match = helper._extract_field(row, candidates, require_value=False)
    if match:
        field_name, raw_value = match
    else:
        field_name, raw_value = field_label, None

    if match and not helper._is_empty(raw_value):
        return field_name, raw_value, str(raw_value).strip()

    issue_details: dict[str, object] = {
        "tabla": table_name,
        "campo": field_name,
        "class": table_name,
        "valor": raw_value,
    }
    if not match:
        issue_details["campo_no_encontrado"] = True
    if details:
        issue_details.update(details)

    issues.append(
        RuleIssue(
            rule_id=rule_id,
            object_ref=helper.identify(row),
            message=message,
            details=issue_details,
        )
    )
    return None


def _is_valid_numero_predial(numero: str) -> bool:
    return len(numero) == 30 and numero.isdigit()


def _is_predio_nuevo_tipo(value: object) -> bool:
    if value in (None, ""):
        return False
    normalized = NumeroPredialHelper._normalize_key(str(value))
    return normalized == "predionuevo"


def _is_valid_predio_nuevo_provisional(numero: str) -> bool:
    if len(numero) != 30 or not numero.isalnum():
        return False
    return numero[17].isalpha() or numero[13].isalpha()


def _build_predio_nuevo_scope(helper: NumeroPredialHelper) -> tuple[set[str], set[str]]:
    predio_refs: set[str] = set()
    numeros: set[str] = set()
    tipo_fields = ("tipo_novedad", "Tipo_Novedad", "novedad", "Novedad")
    predio_ref_fields = (
        "arb_predio_novedad_numero_predial",
        "ARB_predio_novedad_numero_predial",
        "predio",
        "arb_predio",
        "predio_asociado",
        "id_predio",
        "Id_Predio",
        "id_operacion",
        "Id_Operacion",
    )

    for _, novedad in helper.iter_novedades():
        tipo_novedad = helper.get_field_value(novedad, tipo_fields)
        if not _is_predio_nuevo_tipo(tipo_novedad):
            continue

        predio_ref = helper.get_relation_value(novedad, predio_ref_fields)
        if predio_ref:
            predio_refs.add(str(predio_ref).strip())

        result = helper.pull_predial_number(novedad, allow_guess=True, use_novedad_fields=True)
        if result:
            _, numero, _ = result
            if numero:
                numeros.add(numero)

    return predio_refs, numeros


def _normalize_catalog_value(value: object, aliases: dict[str, str]) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    text = text.replace(" ", "_").replace("-", "_").replace(".", "_")
    text = re.sub(r"[^a-z0-9_]", "", text)
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
        # La regla 1.1 depende de Condicion_Predio. Si la condición no existe,
        # no se puede determinar qué sufijo 22-30 corresponde; ese faltante
        # se reporta en la regla de obligatoriedad 11.6 y no debe duplicarse aquí.
        if not condicion_raw:
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
    predio_nuevo_refs, predio_nuevo_numeros = _build_predio_nuevo_scope(helper)
    provisional_rows: list[tuple[str, dict[str, object], str, str, object]] = []

    def provisional_ordinal(segment: str) -> int | None:
        """A001..A999,B001..: ordinal continuo; 0000/números no son provisionales."""
        value = str(segment or "").strip().upper()
        match = re.fullmatch(r"([A-Z])(\d{3})", value)
        if not match:
            return None
        number = int(match.group(2))
        if number < 1 or number > 999:
            return None
        letter = ord(match.group(1)) - ord("A")
        return letter * 999 + number

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
            issues.append(RuleIssue(
                rule_id="1.2", object_ref=helper.identify(row), message=message,
                details={**payload, "tabla": table_name, "campo": field_name, "class": table_name},
            ))
            continue

        field_name, numero_str, raw_value = result
        predio_ref = _get_t_id(row) or helper.identify(row) or ""
        is_predio_nuevo = numero_str in predio_nuevo_numeros or str(predio_ref) in predio_nuevo_refs
        has_provisional_segment = len(numero_str) == 30 and (
            (len(numero_str) >= 17 and numero_str[13:17][:1].isalpha()) or
            (len(numero_str) >= 21 and numero_str[17:21][:1].isalpha())
        )

        if not _is_valid_numero_predial(numero_str):
            if not (is_predio_nuevo and len(numero_str) == 30 and numero_str.isalnum() and has_provisional_segment):
                issues.append(RuleIssue(
                    rule_id="1.2", object_ref=helper.identify(row),
                    message="Numero_Predial_Nacional debe contener 30 dígitos; solo Predio_Nuevo puede usar la codificación provisional A001 continua.",
                    details={"valor": raw_value, "tabla": table_name, "campo": field_name, "class": table_name},
                ))
                continue

        if is_predio_nuevo and has_provisional_segment:
            provisional_rows.append((table_name, row, numero_str, field_name, raw_value))

    # Formato y continuidad de Manzana/Vereda (14-17) y Terreno (18-21).
    # Se valida cada ámbito catastral por separado para no mezclar secuencias.
    sequence_groups: dict[tuple[str, str], list[tuple[int, tuple[str, dict[str, object], str, str, object]]]] = {}
    for entry in provisional_rows:
        table_name, row, numero, field_name, raw_value = entry
        for label, start, end, group_end in (
            ("manzana_vereda", 13, 17, 13),
            ("terreno", 17, 21, 17),
        ):
            segment = numero[start:end]
            if not segment[:1].isalpha():
                continue
            ordinal = provisional_ordinal(segment)
            if ordinal is None:
                issues.append(RuleIssue(
                    rule_id="1.2", object_ref=helper.identify(row),
                    message=f"La codificación provisional de {label} debe tener formato A001 y ser continua.",
                    details={"tabla": table_name, "campo": field_name, "class": table_name,
                             "numero": numero, "segmento": segment, "segmento_tipo": label, "valor": raw_value},
                ))
                continue
            sequence_groups.setdefault((label, numero[:group_end]), []).append((ordinal, entry))

    for (label, scope), values in sequence_groups.items():
        distinct = sorted({ordinal for ordinal, _ in values})
        expected = list(range(1, len(distinct) + 1))
        if distinct == expected:
            continue
        for ordinal, entry in values:
            table_name, row, numero, field_name, raw_value = entry
            issues.append(RuleIssue(
                rule_id="1.2", object_ref=helper.identify(row),
                message=f"La secuencia provisional de {label} debe iniciar en A001 y no tener saltos.",
                details={"tabla": table_name, "campo": field_name, "class": table_name,
                         "numero": numero, "ambito": scope, "segmento_tipo": label,
                         "secuencia_encontrada": distinct, "secuencia_esperada": expected, "valor": raw_value},
            ))

    for table_name, row in helper.iter_novedades():
        result = helper.pull_predial_number(row, allow_guess=True, use_novedad_fields=True)
        if not result:
            continue
        field_name, numero_str, raw_value = result
        tipo_novedad = helper.get_field_value(row, ("tipo_novedad", "Tipo_Novedad", "novedad", "Novedad"))
        is_predio_nuevo = _is_predio_nuevo_tipo(tipo_novedad)
        if _is_valid_numero_predial(numero_str):
            continue
        provisional_ok = False
        if is_predio_nuevo and len(numero_str) == 30 and numero_str.isalnum():
            segments = [numero_str[13:17], numero_str[17:21]]
            provisional_segments = [seg for seg in segments if seg[:1].isalpha()]
            provisional_ok = bool(provisional_segments) and all(provisional_ordinal(seg) is not None for seg in provisional_segments)
        if not provisional_ok:
            issues.append(RuleIssue(
                rule_id="1.2", object_ref=helper.identify(row),
                message="El número predial registrado en novedades debe contener 30 dígitos o una codificación provisional Predio_Nuevo válida (A001...).",
                details={"valor": raw_value, "tabla": table_name, "campo": field_name, "class": table_name},
            ))

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
    """PH.Matriz: posiciones 22-30 del NPN deben ser 900000000."""
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        condicion_raw = helper.get_field_value(row, helper.CONDICION_FIELDS)
        if _normalize_condicion(condicion_raw) != "PH_MATRIZ":
            continue

        result = helper.pull_predial_number(row, allow_guess=False)
        if not result:
            continue

        field_name, numero_str, raw_value = result
        if len(numero_str) < 30:
            continue

        actual = numero_str[21:30]
        expected = "900000000"
        if actual != expected:
            issues.append(
                RuleIssue(
                    rule_id="1.4",
                    object_ref=helper.identify(row),
                    message="Los campos 22-30 de Numero_Predial_Nacional para PH.Matriz deben ser '900000000'.",
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
    """PH.Unidad_Predial: 22=9, 23-24!=00, 25-26!=00 y 27-30!=0000."""
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        condicion_raw = helper.get_field_value(row, helper.CONDICION_FIELDS)
        if _normalize_condicion(condicion_raw) != "PH_UNIDAD_PREDIAL":
            continue

        result = helper.pull_predial_number(row, allow_guess=False)
        if not result:
            continue

        field_name, numero_str, raw_value = result
        if len(numero_str) < 30:
            continue

        v22 = numero_str[21]
        v23_24 = numero_str[22:24]
        v25_26 = numero_str[24:26]
        v27_30 = numero_str[26:30]

        if v22 != "9" or v23_24 == "00" or v25_26 == "00" or v27_30 == "0000":
            issues.append(
                RuleIssue(
                    rule_id="1.5",
                    object_ref=helper.identify(row),
                    message=(
                        "Para PH.Unidad_Predial el campo 22 debe ser '9', los campos 23-24 y 25-26 "
                        "deben ser diferentes de '00' y los campos 27-30 diferentes de '0000'."
                    ),
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                        "valor": raw_value,
                        "numero": numero_str,
                        "condicion_predio": condicion_raw,
                        "valor_22": v22,
                        "valor_23_24": v23_24,
                        "valor_25_26": v25_26,
                        "valor_27_30": v27_30,
                    },
                )
            )

    return issues

def _rule_1_6(dataset: DatasetReader) -> list[RuleIssue]:
    """Condominio.Matriz: posiciones 22-30 del NPN deben ser 800000000."""
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        condicion_raw = helper.get_field_value(row, helper.CONDICION_FIELDS)
        if _normalize_condicion(condicion_raw) != "CONDOMINIO_MATRIZ":
            continue

        result = helper.pull_predial_number(row, allow_guess=False)
        if not result:
            continue

        field_name, numero_str, raw_value = result
        if len(numero_str) < 30:
            continue

        actual = numero_str[21:30]
        expected = "800000000"
        if actual != expected:
            issues.append(
                RuleIssue(
                    rule_id="1.6",
                    object_ref=helper.identify(row),
                    message="Los campos 22-30 de Numero_Predial_Nacional para Condominio.Matriz deben ser '800000000'.",
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
    """Condominio.Unidad_Predial: 22-26=80000 y 27-30 deben ser distintos de 0000."""
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        condicion_raw = helper.get_field_value(row, helper.CONDICION_FIELDS)
        if _normalize_condicion(condicion_raw) != "CONDOMINIO_UNIDAD_PREDIAL":
            continue

        result = helper.pull_predial_number(row, allow_guess=False)
        if not result:
            continue

        field_name, numero_str, raw_value = result
        if len(numero_str) < 30:
            continue

        v22_26 = numero_str[21:26]
        v27_30 = numero_str[26:30]
        if v22_26 != "80000" or v27_30 == "0000":
            issues.append(
                RuleIssue(
                    rule_id="1.7",
                    object_ref=helper.identify(row),
                    message=(
                        "Para Condominio.Unidad_Predial los campos 22-26 deben ser '80000' "
                        "y los campos 27-30 deben ser diferentes de '0000'."
                    ),
                    details={
                        "tabla": table_name,
                        "campo": field_name,
                        "class": table_name,
                        "valor": raw_value,
                        "numero": numero_str,
                        "condicion_predio": condicion_raw,
                        "valor_22_26": v22_26,
                        "valor_27_30": v27_30,
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
            issues.append(RuleIssue(
                rule_id="1.8", object_ref=helper.identify(row), message=message,
                details={**payload, "tabla": table_name, "campo": field_name, "class": table_name},
            ))
            continue
        field_name, numero_str, raw_value = result
        # La longitud/estructura general se reporta en 1.2; 1.8 no debe lanzar excepción.
        if len(numero_str) < 22:
            continue
        valor_22 = numero_str[21]
        if valor_22 in {"1", "5", "6"}:
            issues.append(RuleIssue(
                rule_id="1.8", object_ref=helper.identify(row),
                message="El campo 22 del Numero_Predial_Nacional no puede ser 1, 5 o 6.",
                details={"tabla": table_name, "campo": field_name, "class": table_name,
                         "valor": raw_value, "numero": numero_str, "valor_encontrado_22": valor_22,
                         "valores_no_permitidos": ["1", "5", "6"]},
            ))
    return issues

def _rule_1_9(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    municipality_context = get_dataset_municipality_context(dataset)
    expected_department = municipality_context.department_code
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

        if departamento != expected_department:
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
                        "valores_permitidos_1_2": [expected_department],
                        "municipio_validacion": municipality_context.tenant_code,
                        "departamento_esperado": municipality_context.department_name,
                    }
                )
            )

    return issues


def _rule_1_10(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    municipality_context = get_dataset_municipality_context(dataset)
    expected_municipality = municipality_context.municipality_code
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

        if municipio != expected_municipality:
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
                        "valores_permitidos_3_5": [expected_municipality],
                        "municipio_validacion": municipality_context.tenant_code,
                        "municipio_esperado": municipality_context.municipality_name,
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
        matricula_match = helper._extract_field(row, helper.MATRICULA_FIELDS, require_value=False)
        if not matricula_match:
            continue
        matricula_field, matricula_raw = matricula_match
        if helper._is_empty(matricula_raw):
            # NULL/vacío no es una matrícula inmobiliaria y no se puede tratar
            # como si todos los predios compartieran el mismo FMI.
            continue
        matricula_str = str(matricula_raw).strip()

        predial_match = helper._extract_field(row, helper.NUMERO_PREDIAL_FIELDS, require_value=False)
        if not predial_match:
            continue
        predial_field, predial_raw = predial_match
        if helper._is_empty(predial_raw):
            continue
        numero_str = str(predial_raw).strip()
        if not numero_str:
            continue

        relaciones.setdefault(matricula_str, {}).setdefault(numero_str, []).append({
            "tabla": table_name,
            "campo_matricula": matricula_field,
            "campo_predial": predial_field,
            "class": table_name,
            "valor_matricula": matricula_raw,
            "valor_predial": predial_raw,
            "object_ref": helper.identify(row),
        })

    for matricula, numeros in relaciones.items():
        if len(numeros) <= 1:
            continue
        relacionados = sorted(numeros)
        for numero, records in numeros.items():
            for record in records:
                issues.append(RuleIssue(
                    rule_id="1.12",
                    object_ref=record["object_ref"],
                    message="El valor de Matricula_inmobiliaria no puede estar relacionado a más de un numero predial.",
                    details={
                        "tabla": record["tabla"], "campo": record["campo_matricula"],
                        "class": record["class"], "valor": record["valor_matricula"],
                        "matricula_inmobiliaria": matricula, "numero": numero,
                        "numeros_prediales_relacionados": relacionados,
                        "total_numeros_prediales": len(relacionados),
                    },
                ))
    return issues



def _rule_1_13(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []
    for table_name, row in helper.iter_predios():
        match = helper._extract_field(row, helper.MATRICULA_FIELDS, require_value=False)
        if not match:
            continue
        field_name, raw_value = match
        if helper._is_empty(raw_value):
            continue
        value = str(raw_value).strip()
        valid = value.isdigit()
        if valid:
            try:
                number = int(value)
                valid = 1 <= number <= 9_999_999
            except Exception:
                valid = False
        if valid:
            continue
        issues.append(RuleIssue(
            rule_id="1.13", object_ref=helper.identify(row),
            message="Matricula_Inmobiliaria debe ser numérica y estar entre 1 y 9999999.",
            details={"tabla": table_name, "campo": field_name, "class": table_name,
                     "valor": raw_value, "matricula_inmobiliaria": value,
                     "rango_permitido": "1-9999999"},
        ))
    return issues

def _rule_1_14(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    municipality_context = get_dataset_municipality_context(dataset)
    expected_orip = municipality_context.orip_code
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_predios():
        matricula_match = helper._extract_field(row, helper.MATRICULA_FIELDS, require_value=False)
        matricula_raw = matricula_match[1] if matricula_match else None
        has_matricula = not helper._is_empty(matricula_raw)
        orip_match = helper._extract_field(row, helper.ORIP_FIELDS, require_value=False)
        orip_field = orip_match[0] if orip_match else helper.ORIP_FIELDS[0]
        orip_raw = orip_match[1] if orip_match else None
        has_orip = not helper._is_empty(orip_raw)

        # Si no existe FMI ni ORIP, no hay círculo registral que validar; 1.18
        # controla la coherencia con Area_Registral_M2.
        if not has_matricula and not has_orip:
            continue
        if not has_orip:
            issues.append(RuleIssue(
                rule_id="1.14", object_ref=helper.identify(row),
                message="Cuando existe Matricula_Inmobiliaria, Codigo_ORIP debe estar diligenciado.",
                details={"tabla": table_name, "campo": orip_field, "class": table_name,
                         "valor": orip_raw, "matricula_inmobiliaria": matricula_raw},
            ))
            continue

        codigo = str(orip_raw).strip()
        wrong_length = len(codigo) != 3
        wrong_circle = bool(expected_orip) and codigo != str(expected_orip).strip()
        if not wrong_length and not wrong_circle:
            continue
        issues.append(RuleIssue(
            rule_id="1.14", object_ref=helper.identify(row),
            message=("Codigo_ORIP debe tener tres caracteres" +
                     (" y coincidir con el círculo registral esperado." if expected_orip else ".")),
            details={"tabla": table_name, "campo": orip_field, "class": table_name,
                     "valor": orip_raw, "codigo_orip": codigo, "orip_esperado": expected_orip,
                     "municipio_validacion": municipality_context.tenant_code,
                     "municipio_esperado": municipality_context.municipality_name},
        ))
    return issues

def _rule_1_15(dataset: DatasetReader) -> list[RuleIssue]:
    """Lote_Urbanizado_No_Construido y Lote_Rural no pueden tener unidades."""
    ctx = _build_admin_property_context(dataset)
    predios = ctx["predios"]
    units = ctx["unit_construction_by_predio"]
    issues: list[RuleIssue] = []
    restricted = {"LOTE_URBANIZADO_NO_CONSTRUIDO", "LOTE_RURAL"}
    for predio_id, predio in predios.items():
        destino = _normalize_destinacion(predio["row"].get("destinacion_economica") or predio["row"].get("Destinacion_Economica"))
        if destino not in restricted:
            continue
        associated = units.get(predio_id, [])
        if not associated:
            continue
        issues.append(RuleIssue(
            rule_id="1.15", object_ref=predio["object_ref"],
            message=("Para predios con destinación económica Lote_Urbanizado_No_Construido o Lote_Rural "
                     "no se deben relacionar unidades de construcción."),
            details={"tabla": predio["tabla"], "campo": "destinacion_economica", "class": predio["tabla"],
                     "numero_predial": predio["npn"], "destinacion_economica": destino,
                     "total_unidades_construccion": len(associated)},
        ))
    return issues

def _admin_to_float(value: object) -> float | None:
    """Convierte números XTF/QGIS sin confundir NULL/vacíos con cero."""
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "nan", "n/a", "na"}:
        return None
    try:
        return float(text.replace(",", "."))
    except Exception:
        return None


def _admin_to_int(value: object) -> int | None:
    number = _admin_to_float(value)
    if number is None:
        return None
    rounded = round(number)
    if abs(number - rounded) > 1e-9:
        return None
    return int(rounded)


def _admin_normalize_relation_key(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", text)


def _admin_add_alias(alias_map: dict[str, str], alias: object, canonical: str) -> None:
    if alias is None:
        return
    text = str(alias).strip()
    if not text:
        return
    candidates = {text}
    if text.endswith(".0"):
        candidates.add(text[:-2])
    normalized = _admin_normalize_relation_key(text)
    if normalized:
        candidates.add(normalized)
    for candidate in candidates:
        alias_map.setdefault(candidate, canonical)


def _admin_resolve_alias(alias_map: dict[str, str], value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in alias_map:
        return alias_map[text]
    if text.endswith(".0") and text[:-2] in alias_map:
        return alias_map[text[:-2]]
    normalized = _admin_normalize_relation_key(text)
    if normalized in alias_map:
        return alias_map[normalized]
    return None


def _admin_row_aliases(helper: NumeroPredialHelper, row: dict[str, object]) -> set[str]:
    aliases: set[str] = set()
    for field in (
        "t_id", "T_Id", "T_ID", "tid", "TID",
        "t_ili_tid", "T_Ili_Tid", "T_ILI_TID",
        "id_operacion", "Id_Operacion", "ID_OPERACION",
        "id_predio", "ID_PREDIO", "predio_id", "Predio_ID",
        "Numero_Predial_Nacional", "numero_predial_nacional",
        "Numero_Predial", "numero_predial",
    ):
        value = row.get(field)
        if value not in (None, ""):
            aliases.add(str(value).strip())
    object_ref = helper.identify(row)
    if object_ref:
        aliases.add(str(object_ref).strip())
    return aliases


def _admin_geometry_area(row: dict[str, object], helper: NumeroPredialHelper) -> float | None:
    """Área geográfica común para WEB (XML XTF) y QGIS (área de QgsGeometry)."""
    numeric = helper._extract_field(
        row,
        ("area_geografica", "Area_Geografica", "area_geometrica", "shape_area", "Shape_Area"),
        require_value=False,
    )
    if numeric:
        area = _admin_to_float(numeric[1])
        if area is not None:
            return area

    geometry = helper._extract_field(
        row,
        ("Geometria", "geometria", "geometry", "Geometry"),
        require_value=False,
    )
    if not geometry or geometry[1] in (None, ""):
        return None

    raw = geometry[1]
    # Algunos adaptadores pueden entregar un objeto geométrico real.
    try:
        area_method = getattr(raw, "area", None)
        if callable(area_method):
            return float(area_method())
    except Exception:
        pass

    text = str(raw).strip()
    if not text.startswith("<"):
        return _admin_to_float(text)

    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(text)
    except Exception:
        return None

    def clean_tag(tag: str) -> str:
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        if "." in tag:
            tag = tag.split(".")[-1]
        return tag.strip().lower()

    def ring_area(points: list[tuple[float, float]]) -> float:
        if len(points) < 3:
            return 0.0
        if points[0] != points[-1]:
            points = points + [points[0]]
        total = 0.0
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            total += x1 * y2 - x2 * y1
        return abs(total) / 2.0

    surfaces = [node for node in root.iter() if clean_tag(node.tag) == "surface"]
    containers = surfaces or [root]
    total_area = 0.0
    found = False

    for container in containers:
        rings: list[list[tuple[float, float]]] = []
        boundaries = [node for node in container.iter() if clean_tag(node.tag) == "boundary"]
        if not boundaries:
            boundaries = [container]
        for boundary in boundaries:
            points: list[tuple[float, float]] = []
            for coord in boundary.iter():
                if clean_tag(coord.tag) != "coord":
                    continue
                values: dict[str, str] = {}
                for child in coord:
                    if child.text:
                        values[clean_tag(child.tag)] = child.text.strip()
                if "c1" in values and "c2" in values:
                    try:
                        points.append((float(values["c1"]), float(values["c2"])))
                    except Exception:
                        pass
            if len(points) >= 3:
                rings.append(points)
        if rings:
            found = True
            outer = ring_area(rings[0])
            holes = sum(ring_area(ring) for ring in rings[1:])
            total_area += max(0.0, outer - holes)

    return total_area if found else None


def _admin_close(a: float, b: float, tolerance: float = 0.01) -> bool:
    return abs(float(a) - float(b)) <= tolerance


def _admin_resolution_1040_tolerance_percent(geometric_area: float, numero_predial: object) -> float:
    """Porcentaje de tolerancia de área de terreno de la Res. 1040/2023.

    La clasificación disponible en el modelo se toma de los dígitos 6-7 del
    NPN: ``00`` se trata como rural sin comportamiento urbano y los demás
    códigos como urbano/centro poblado (comportamiento urbano).
    """
    area = abs(float(geometric_area))
    numero = str(numero_predial or "").strip()
    zona = numero[5:7] if len(numero) >= 7 else ""
    rural = zona == "00"
    if not rural:
        if area <= 80.0:
            return 7.0
        if area <= 250.0:
            return 6.0
        if area <= 500.0:
            return 4.0
        return 3.0
    if area <= 2000.0:
        return 10.0
    if area <= 10000.0:
        return 9.0
    if area <= 100000.0:
        return 7.0
    if area <= 500000.0:
        return 4.0
    return 2.0


def _admin_area_within_resolution_1040_tolerance(
    geometric_area: float, compared_area: float, numero_predial: object
) -> tuple[bool, float, float]:
    """Compara áreas usando |Ageom-Acomp|/Ageom*100 y devuelve (ok, diferencia %, tolerancia %)."""
    geom = float(geometric_area)
    comp = float(compared_area)
    if abs(geom) <= 1e-12:
        ok = _admin_close(geom, comp)
        return ok, (0.0 if ok else float("inf")), 0.0
    difference = abs(geom - comp) / abs(geom) * 100.0
    tolerance = _admin_resolution_1040_tolerance_percent(geom, numero_predial)
    return difference <= tolerance + 1e-9, difference, tolerance


def _build_admin_property_context(dataset: DatasetReader) -> dict[str, object]:
    """Modelo relacional normalizado usado por las reglas 1.16 y 1.20-1.38.

    No supone que exista ``predio_matriz``. La matriz PH/Condominio se infiere
    por el NPN (misma base y sufijo 900000000/800000000), lo que funciona en
    XTF y también después de materializar el XTF en QGIS.
    """
    helper = NumeroPredialHelper(dataset)
    predios: dict[str, dict[str, object]] = {}
    predio_aliases: dict[str, str] = {}
    predio_by_npn: dict[str, str] = {}

    # Predios y aliases de relación (UUID XTF, t_id QGIS, t_ili_tid, NPN, etc.).
    for table_name, row in helper.iter_predios():
        npn = helper.get_field_value(row, helper.NUMERO_PREDIAL_FIELDS) or ""
        predio_id = _get_t_id(row) or helper.identify(row) or (npn if npn else None)
        if not predio_id:
            continue
        predio_id = str(predio_id).strip()
        condicion_raw = helper.get_field_value(row, helper.CONDICION_FIELDS)
        condicion = _normalize_condicion(condicion_raw)
        info = {
            "id": predio_id,
            "tabla": table_name,
            "row": row,
            "object_ref": helper.identify(row) or predio_id,
            "npn": npn,
            "condicion": condicion,
            "condicion_raw": condicion_raw,
            "matrix_id": None,
        }
        predios[predio_id] = info
        if npn:
            predio_by_npn[npn] = predio_id
        _admin_add_alias(predio_aliases, predio_id, predio_id)
        for alias in _admin_row_aliases(helper, row):
            _admin_add_alias(predio_aliases, alias, predio_id)

    # Enlace unidad -> matriz por relación explícita si existe; si no, por NPN.
    for predio_id, info in predios.items():
        condicion = str(info["condicion"])
        if condicion not in {"PH_UNIDAD_PREDIAL", "CONDOMINIO_UNIDAD_PREDIAL"}:
            continue
        row = info["row"]
        explicit = helper.get_field_value(row, helper.PREDIO_MATRIZ_FIELDS)
        matrix_id = _admin_resolve_alias(predio_aliases, explicit)
        npn = str(info["npn"] or "")
        if not matrix_id and len(npn) >= 30:
            suffix = "900000000" if condicion == "PH_UNIDAD_PREDIAL" else "800000000"
            matrix_id = predio_by_npn.get(npn[:21] + suffix)
        info["matrix_id"] = matrix_id

    units_by_matrix: dict[str, list[str]] = {}
    for predio_id, info in predios.items():
        matrix_id = info.get("matrix_id")
        if matrix_id:
            units_by_matrix.setdefault(str(matrix_id), []).append(predio_id)

    # Datos PH/Condominio por predio matriz.
    info_ph_by_predio: dict[str, dict[str, object]] = {}
    for table_name, row in helper.iter_informacion_ph():
        ref = helper.get_relation_value(
            row,
            ("arb_predio", "predio", "id_predio", "Id_Predio", "cca_predio"),
        )
        predio_id = _admin_resolve_alias(predio_aliases, ref)
        if predio_id:
            info_ph_by_predio.setdefault(predio_id, {"tabla": table_name, "row": row})

    # Áreas de terreno asociadas a cada predio.
    terrain_areas_by_predio: dict[str, list[float]] = {}
    for _, row in helper.iter_terrenos():
        ref = helper.get_relation_value(
            row,
            (
                "predio", "arb_predio", "arb_predio_terreno", "terreno_predio",
                "predio_asociado", "id_predio", "Id_Predio",
                "ARB_terreno_predio_ARB_predio_T_Id",
            ),
        )
        predio_id = _admin_resolve_alias(predio_aliases, ref)
        if not predio_id:
            continue
        area = _admin_geometry_area(row, helper)
        if area is not None:
            terrain_areas_by_predio.setdefault(predio_id, []).append(area)

    # Construcción -> predio.
    construction_aliases: dict[str, str] = {}
    construction_to_predio: dict[str, str] = {}
    for _, row in helper.iter_construcciones():
        cid = _get_t_id(row) or helper.identify(row)
        if not cid:
            continue
        cid = str(cid).strip()
        _admin_add_alias(construction_aliases, cid, cid)
        for alias in _admin_row_aliases(helper, row):
            _admin_add_alias(construction_aliases, alias, cid)
        ref = helper.get_relation_value(
            row,
            ("predio", "arb_predio", "predio_asociado", "id_predio", "Id_Predio"),
        )
        predio_id = _admin_resolve_alias(predio_aliases, ref)
        if predio_id:
            construction_to_predio[cid] = predio_id

    # Características de unidades de construcción.
    characteristic_aliases: dict[str, str] = {}
    characteristics: dict[str, dict[str, object]] = {}
    for _, row in helper.iter_caracteristicas_unidad():
        char_id = _get_t_id(row) or helper.identify(row)
        if not char_id:
            continue
        char_id = str(char_id).strip()
        characteristics[char_id] = row
        _admin_add_alias(characteristic_aliases, char_id, char_id)
        for alias in _admin_row_aliases(helper, row):
            _admin_add_alias(characteristic_aliases, alias, char_id)

    unit_construction_by_predio: dict[str, list[dict[str, object]]] = {}
    for table_name, row in helper.iter_unidades_construccion():
        predio_id: str | None = None
        direct_ref = helper.get_relation_value(row, ("predio", "arb_predio", "predio_asociado"))
        if direct_ref:
            predio_id = _admin_resolve_alias(predio_aliases, direct_ref)

        construction_ref = helper.get_relation_value(
            row,
            ("construccion", "arb_construccion", "id_construccion", "construccion_id"),
        )
        construction_id = _admin_resolve_alias(construction_aliases, construction_ref)
        if not predio_id and construction_id:
            predio_id = construction_to_predio.get(construction_id)

        char_ref = helper.get_relation_value(
            row,
            (
                "caracteristicasunidadconstruccion", "caracteristicas_unidad_construccion",
                "caracteristicas", "id_caracteristicas",
            ),
        )
        char_id = _admin_resolve_alias(characteristic_aliases, char_ref)
        char_row = characteristics.get(char_id or "")

        # Respaldo permitido por el modelo: ID_Grupo de características puede
        # ser el NPN. Solo se usa si la relación construcción->predio no resolvió.
        if not predio_id and char_row:
            id_grupo = helper.get_field_value(char_row, ("ID_Grupo", "id_grupo"))
            predio_id = _admin_resolve_alias(predio_aliases, id_grupo)

        if not predio_id:
            continue

        area_construida = None
        area_privada = None
        if char_row:
            area_construida = _admin_to_float(
                helper.get_field_value(char_row, ("Area_Construida", "area_construida"))
            )
            area_privada = _admin_to_float(
                helper.get_field_value(char_row, ("Area_Privada_Construida", "area_privada_construida"))
            )
        unit_construction_by_predio.setdefault(predio_id, []).append(
            {
                "tabla": table_name,
                "row": row,
                "char_row": char_row,
                "area_construida": area_construida,
                "area_privada_construida": area_privada,
            }
        )

    return {
        "helper": helper,
        "predios": predios,
        "predio_aliases": predio_aliases,
        "predio_by_npn": predio_by_npn,
        "units_by_matrix": units_by_matrix,
        "info_ph_by_predio": info_ph_by_predio,
        "terrain_areas_by_predio": terrain_areas_by_predio,
        "unit_construction_by_predio": unit_construction_by_predio,
    }


def _admin_info_number(
    ctx: dict[str, object], matrix_id: str, fields: tuple[str, ...]
) -> tuple[float | None, str, object | None, dict[str, object] | None]:
    helper: NumeroPredialHelper = ctx["helper"]  # type: ignore[assignment]
    info = ctx["info_ph_by_predio"].get(matrix_id)  # type: ignore[index]
    if not info:
        return None, fields[0], None, None
    row = info["row"]
    match = helper._extract_field(row, fields, require_value=False)
    field_name = match[0] if match else fields[0]
    raw = match[1] if match else None
    return _admin_to_float(raw), field_name, raw, info


def _admin_matrix_area_components(
    ctx: dict[str, object], matrix_id: str
) -> tuple[float, float, bool]:
    """Devuelve (privada, común, datos_completos) para PH/Condominio."""
    private_total = 0.0
    common_total = 0.0
    complete = True
    units_by_matrix = ctx["units_by_matrix"]  # type: ignore[assignment]
    unit_rows = ctx["unit_construction_by_predio"]  # type: ignore[assignment]

    for unit_predio_id in units_by_matrix.get(matrix_id, []):
        for record in unit_rows.get(unit_predio_id, []):
            value = record.get("area_privada_construida")
            if value is None:
                complete = False
            else:
                private_total += float(value)

    for record in unit_rows.get(matrix_id, []):
        value = record.get("area_construida")
        if value is None:
            complete = False
        else:
            common_total += float(value)

    return private_total, common_total, complete

def _rule_1_16(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []
    ctx = _build_admin_property_context(dataset)

    rural_destinations = {
        "ACUICOLA", "AGRICOLA", "AGROINDUSTRIAL", "AGROPECUARIO", "AGROFORESTAL",
        "FORESTAL", "INFRAESTRUCTURA_ASOCIADA_PRODUCCION_AGROPECUARIA",
        "INFRAESTRUCTURA_SANEAMIENTO_BASICO", "MINERIA_HIDROCARBUROS",
        "PECUARIO", "LOTE_RURAL",
    }
    urban_lot_destinations = {
        "LOTE_URBANIZABLE_NO_URBANIZADO",
        "LOTE_URBANIZADO_NO_CONSTRUIDO",
    }
    ph_condo_conditions = {
        "PH_MATRIZ", "PH_UNIDAD_PREDIAL", "CONDOMINIO_MATRIZ", "CONDOMINIO_UNIDAD_PREDIAL",
    }

    unit_rows = ctx["unit_construction_by_predio"]  # type: ignore[assignment]
    for table_name, row in helper.iter_predios():
        destino_raw = helper.get_field_value(row, helper.DESTINACION_FIELDS)
        if not destino_raw:
            continue
        destino = _normalize_destinacion(destino_raw)
        if destino not in rural_destinations | urban_lot_destinations:
            continue

        numero = helper.get_field_value(row, helper.NUMERO_PREDIAL_FIELDS)
        if not numero or len(numero) < 7:
            continue
        zona = numero[5:7]  # dígitos 6-7, numeración humana 1-based.
        object_ref = helper.identify(row)

        if destino in rural_destinations and zona != "00":
            issues.append(RuleIssue(
                rule_id="1.16", object_ref=object_ref,
                message="La destinación económica rural exige que los dígitos 6-7 del Numero_Predial_Nacional sean '00'.",
                details={"tabla": table_name, "campo": "Numero_Predial_Nacional", "class": table_name,
                         "numero": numero, "destinacion_economica": destino_raw,
                         "digitos_6_7": zona, "valor_esperado": "00"},
            ))
        elif destino in urban_lot_destinations and zona == "00":
            issues.append(RuleIssue(
                rule_id="1.16", object_ref=object_ref,
                message="La destinación económica de lote urbano exige que los dígitos 6-7 del Numero_Predial_Nacional sean diferentes de '00'.",
                details={"tabla": table_name, "campo": "Numero_Predial_Nacional", "class": table_name,
                         "numero": numero, "destinacion_economica": destino_raw,
                         "digitos_6_7": zona, "valor_esperado": "diferente de 00"},
            ))

        if destino != "LOTE_RURAL":
            continue

        predio_id = _get_t_id(row) or helper.identify(row) or numero
        condicion_raw = helper.get_field_value(row, helper.CONDICION_FIELDS)
        condicion = _normalize_condicion(condicion_raw)
        if condicion in ph_condo_conditions:
            issues.append(RuleIssue(
                rule_id="1.16", object_ref=object_ref,
                message="Un predio con destinación económica Lote_Rural no puede tener condición PH o Condominio.",
                details={"tabla": table_name, "campo": "condicion_predio", "class": table_name,
                         "numero": numero, "destinacion_economica": destino_raw,
                         "condicion_predio": condicion_raw},
            ))

        if predio_id and unit_rows.get(str(predio_id)):
            issues.append(RuleIssue(
                rule_id="1.16", object_ref=object_ref,
                message="Un predio con destinación económica Lote_Rural no debe tener unidades de construcción asociadas.",
                details={"tabla": table_name, "campo": "destinacion_economica", "class": table_name,
                         "numero": numero, "destinacion_economica": destino_raw,
                         "total_unidades_construccion": len(unit_rows.get(str(predio_id), []))},
            ))

    # El texto de la regla menciona que normalmente el lote rural es <500 m²,
    # pero también declara excepciones. Por eso no se genera un falso positivo
    # automático únicamente por superar 500 m².
    return issues



def _rule_1_17(dataset: DatasetReader) -> list[RuleIssue]:
    """Destinaciones indicadas deben tener al menos una UnidadConstruccion relacionada."""
    ctx = _build_admin_property_context(dataset)
    predios = ctx["predios"]
    units = ctx["unit_construction_by_predio"]
    issues: list[RuleIssue] = []
    required = {"COMERCIAL", "EDUCATIVO", "HABITACIONAL", "INDUSTRIAL", "INSTITUCIONAL", "SALUBRIDAD"}
    for predio_id, predio in predios.items():
        helper: NumeroPredialHelper = ctx["helper"]
        destino_raw = helper.get_field_value(predio["row"], helper.DESTINACION_FIELDS)
        destino = _normalize_destinacion(destino_raw)
        if destino not in required or units.get(predio_id):
            continue
        issues.append(RuleIssue(
            rule_id="1.17", object_ref=predio["object_ref"],
            message=("Los predios con destinación económica Comercial, Educativo, Habitacional, Industrial, "
                     "Institucional o Salubridad deben tener relacionada al menos una unidad de construcción."),
            details={"tabla": predio["tabla"], "campo": "destinacion_economica", "class": predio["tabla"],
                     "numero_predial": predio["npn"], "destinacion_economica": destino_raw,
                     "total_unidades_construccion": 0},
        ))
    return issues

def _rule_1_18(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []
    area_fields = ("area_registral_m2", "Area_Registral_M2", "area_registral", "Area_Registral")
    for table_name, row in helper.iter_predios():
        area_match = helper._extract_field(row, area_fields, require_value=False)
        if not area_match or helper._is_empty(area_match[1]):
            continue
        area_field, area_raw = area_match
        try:
            area = float(str(area_raw).replace(",", ".").strip())
        except Exception:
            issues.append(RuleIssue(
                rule_id="1.18", object_ref=helper.identify(row),
                message="Area_Registral_M2 debe ser numérica para validar la regla 1.18.",
                details={"tabla": table_name, "campo": area_field, "class": table_name, "valor": area_raw},
            ))
            continue

        orip_match = helper._extract_field(row, helper.ORIP_FIELDS, require_value=False)
        fmi_match = helper._extract_field(row, helper.MATRICULA_FIELDS, require_value=False)
        orip = orip_match[1] if orip_match else None
        fmi = fmi_match[1] if fmi_match else None
        has_orip = not helper._is_empty(orip)
        has_fmi = not helper._is_empty(fmi)

        reasons: list[str] = []
        if not has_orip and not has_fmi and abs(area) > 1e-9:
            reasons.append("sin Codigo_ORIP ni Matricula_Inmobiliaria, Area_Registral_M2 debe ser 0")
        if area > 0 and (not has_orip or not has_fmi):
            reasons.append("Area_Registral_M2 > 0 requiere Codigo_ORIP y Matricula_Inmobiliaria")
        if has_orip and has_fmi and area <= 0:
            reasons.append("Codigo_ORIP y Matricula_Inmobiliaria diligenciados requieren Area_Registral_M2 > 0")
        if not reasons:
            continue
        issues.append(RuleIssue(
            rule_id="1.18", object_ref=helper.identify(row),
            message="Codigo_ORIP, Matricula_Inmobiliaria y Area_Registral_M2 no son coherentes entre sí.",
            details={"tabla": table_name, "campo": area_field, "class": table_name, "valor": area_raw,
                     "area_registral_m2": area, "codigo_orip": orip, "matricula_inmobiliaria": fmi,
                     "motivos": reasons},
        ))
    return issues

def _rule_1_19(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []
    ctx = _build_admin_property_context(dataset)
    predios = ctx["predios"]
    aliases = ctx["predio_aliases"]

    valid_conditions = {
        "NPH", "PH_MATRIZ", "CONDOMINIO_MATRIZ", "CONDOMINIO_UNIDAD_PREDIAL",
        "VIA", "BIEN_USO_PUBLICO", "PARQUE_CEMENTERIO_MATRIZ", "PARQUE_CEMENTERIO_UNIDAD_PREDIAL",
    }
    cancellations = {"CANCELACION", "CANCELACION_POR_DESENGLOBE", "CANCELACION_POR_ENGLOBE"}

    cancelled: set[str] = set()
    for _, row in helper.iter_novedades():
        ref = helper.get_relation_value(row, (
            "arb_predio_novedad_numero_predial", "ARB_predio_novedad_numero_predial",
            "predio", "arb_predio", "predio_asociado", "id_predio", "Id_Predio",
        ))
        predio_id = _admin_resolve_alias(aliases, ref)
        novedad = helper.get_field_value(row, ("tipo_novedad", "Tipo_Novedad", "novedad", "Novedad"))
        if predio_id and _normalize_novedad(novedad) in cancellations:
            cancelled.add(predio_id)

    terrenos_by_predio: dict[str, list[tuple[str, dict[str, object]]]] = {}
    orphan_terrains: list[tuple[str, dict[str, object], object | None]] = []
    for table_name, row in helper.iter_terrenos():
        ref = helper.get_relation_value(row, (
            "predio", "arb_predio", "arb_predio_terreno", "terreno_predio", "predio_asociado",
            "id_predio", "Id_Predio", "ARB_terreno_predio_ARB_predio_T_Id",
        ))
        predio_id = _admin_resolve_alias(aliases, ref)
        if not predio_id or predio_id not in predios:
            orphan_terrains.append((table_name, row, ref))
            continue
        terrenos_by_predio.setdefault(predio_id, []).append((table_name, row))

    for predio_id, predio in predios.items():
        if predio_id in cancelled:
            continue
        count = len(terrenos_by_predio.get(predio_id, []))
        condicion = str(predio["condicion"] or "")
        if condicion in valid_conditions:
            if count != 1:
                issues.append(RuleIssue(
                    rule_id="1.19", object_ref=predio["object_ref"],
                    message="El predio debe estar asociado a un único terreno.",
                    details={"tipo_error_presentado": "FDC-R5019-E01", "tabla": predio["tabla"],
                             "campo": "condicion_predio", "class": predio["tabla"],
                             "numero_predial": predio["npn"], "condicion_predio": predio["condicion_raw"],
                             "numero_terrenos_asociados": count},
                ))
        elif count > 0:
            issues.append(RuleIssue(
                rule_id="1.19", object_ref=predio["object_ref"],
                message="La condición del predio no permite tener terreno asociado según la regla 1.19.",
                details={"tipo_error_presentado": "FDC-R5019-E02", "tabla": predio["tabla"],
                         "campo": "condicion_predio", "class": predio["tabla"],
                         "numero_predial": predio["npn"], "condicion_predio": predio["condicion_raw"],
                         "numero_terrenos_asociados": count},
            ))

    for table_name, row, ref in orphan_terrains:
        issues.append(RuleIssue(
            rule_id="1.19", object_ref=helper.identify(row),
            message="Todo terreno debe estar asociado a un predio válido permitido por la regla 1.19.",
            details={"tipo_error_presentado": "FDC-R5019-E03", "tabla": table_name,
                     "campo": "predio", "class": table_name, "predio_referencia": ref},
        ))
    return issues

def _rule_1_20(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    helper: NumeroPredialHelper = ctx["helper"]  # type: ignore[assignment]
    issues: list[RuleIssue] = []
    predios = ctx["predios"]  # type: ignore[assignment]
    units_by_matrix = ctx["units_by_matrix"]  # type: ignore[assignment]
    valid_coefficients: dict[str, float] = {}
    invalid_units: set[str] = set()

    for predio_id, info in predios.items():
        if info["condicion"] not in {"PH_UNIDAD_PREDIAL", "CONDOMINIO_UNIDAD_PREDIAL"}:
            continue
        row = info["row"]
        match = helper._extract_field(
            row,
            ("coeficiente_copropiedad", "Coeficiente_Copropiedad", "coeficiente", "Coeficiente"),
            require_value=False,
        )
        raw = match[1] if match else None
        coef = _admin_to_float(raw)
        if coef is None or not (0.0 < coef < 1.0):
            invalid_units.add(predio_id)
            issues.append(RuleIssue(
                rule_id="1.20", object_ref=info["object_ref"],
                message="Las unidades PH/Condominio deben tener un coeficiente de copropiedad mayor que 0 y menor que 1.",
                details={"tabla": info["tabla"], "campo": match[0] if match else "coeficiente_copropiedad",
                         "class": info["tabla"], "numero_predial": info["npn"],
                         "condicion_predio": info["condicion_raw"], "coeficiente": raw},
            ))
        else:
            valid_coefficients[predio_id] = coef

    for matrix_id, unit_ids in units_by_matrix.items():
        if not unit_ids or any(uid in invalid_units or uid not in valid_coefficients for uid in unit_ids):
            continue
        total = sum(valid_coefficients[uid] for uid in unit_ids)
        if _admin_close(total, 1.0, tolerance=1e-6):
            continue
        matrix = predios.get(matrix_id)
        if not matrix:
            continue
        issues.append(RuleIssue(
            rule_id="1.20", object_ref=matrix["object_ref"],
            message="La sumatoria de los coeficientes de copropiedad de las unidades asociadas a una misma matriz debe ser 1.",
            details={"tabla": matrix["tabla"], "campo": "coeficiente_copropiedad", "class": matrix["tabla"],
                     "numero_predial_matriz": matrix["npn"], "suma_coeficientes": round(total, 10),
                     "valor_esperado": 1.0, "total_unidades": len(unit_ids)},
        ))
    return issues


def _rule_1_21(dataset: DatasetReader) -> list[RuleIssue]:
    """Compara áreas solo cuando todos los insumos necesarios existen."""
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    area_coeficiente_fields = ("Area_Coeficiente_Copropiedad", "area_coeficiente_copropiedad")
    area_total_terreno_fields = ("Area_Total_Terreno", "area_total_terreno")
    matrix_conditions = {"PH_MATRIZ", "CONDOMINIO_MATRIZ"}
    unit_conditions = {"PH_UNIDAD_PREDIAL", "CONDOMINIO_UNIDAD_PREDIAL"}

    def parse_float(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", ".").strip())
        except Exception:
            return None

    informacion_ph_por_predio: dict[str, float] = {}
    for _, row in helper.iter_informacion_ph():
        predio_fk = helper.get_relation_value(row, ("arb_predio", "predio", "id_predio", "Id_Predio"))
        if not predio_fk:
            continue
        area_match = helper._extract_field(row, area_total_terreno_fields, require_value=False)
        area_value = parse_float(area_match[1]) if area_match else None
        if area_value is not None:
            informacion_ph_por_predio[predio_fk] = area_value

    predios_matriz: dict[str, dict[str, object]] = {}
    suma_areas_unidades: dict[str, float] = {}

    for table_name, row in helper.iter_predios():
        condicion_raw = helper.get_field_value(row, helper.CONDICION_FIELDS)
        condicion = _normalize_condicion(condicion_raw)
        if condicion not in matrix_conditions and condicion not in unit_conditions:
            continue

        predio_id = _get_t_id(row)
        result = helper.pull_predial_number(row, allow_guess=False)
        if not predio_id or not result:
            continue
        field_name, numero_str, _ = result
        if len(numero_str) < 22:
            continue
        numero_base = numero_str[:22]

        if condicion in matrix_conditions:
            predios_matriz[predio_id] = {
                "tabla": table_name,
                "campo": field_name,
                "class": table_name,
                "object_ref": helper.identify(row),
                "numero_predial": numero_str,
                "numero_base_22": numero_base,
                "condicion_predio": condicion_raw,
            }
        else:
            area_match = helper._extract_field(row, area_coeficiente_fields, require_value=False)
            area_value = parse_float(area_match[1]) if area_match else None
            if area_value is None:
                continue
            suma_areas_unidades[numero_base] = suma_areas_unidades.get(numero_base, 0.0) + area_value

    for predio_id, predio_info in predios_matriz.items():
        area_matriz = informacion_ph_por_predio.get(predio_id)
        if area_matriz is None:
            continue
        numero_base = str(predio_info["numero_base_22"])
        if numero_base not in suma_areas_unidades:
            continue
        area_unidades = round(suma_areas_unidades[numero_base], 2)
        area_matriz_redondeada = round(area_matriz, 2)
        if area_matriz_redondeada != area_unidades:
            issues.append(
                RuleIssue(
                    rule_id="1.21",
                    object_ref=predio_info["object_ref"],
                    message="La sumatoria de las áreas de coeficiente debe ser igual al área de terreno del predio matriz donde se ubican.",
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
    """Si y solo si el NPN termina en 800000000/900000000 debe existir ARB_InformacionPH."""
    ctx = _build_admin_property_context(dataset)
    helper: NumeroPredialHelper = ctx["helper"]
    predios = ctx["predios"]
    aliases = ctx["predio_aliases"]
    info_by_predio = ctx["info_ph_by_predio"]
    issues: list[RuleIssue] = []

    for predio_id, predio in predios.items():
        numero = str(predio["npn"] or "")
        if len(numero) < 30:
            continue
        debe = numero[21:30] in {"800000000", "900000000"}
        tiene = predio_id in info_by_predio
        if debe == tiene:
            continue
        issues.append(RuleIssue(
            rule_id="1.22", object_ref=predio["object_ref"],
            message=("Solo los predios matriz con posiciones 22-30 iguales a 800000000 o 900000000 "
                     "deben tener un registro en ARB_InformacionPH."),
            details={"tabla": predio["tabla"], "campo": "Numero_Predial_Nacional", "class": predio["tabla"],
                     "numero_predial": numero, "valor_22_30": numero[21:30], "tiene_informacion_ph": tiene},
        ))

    # También detecta registros de Información PH huérfanos/desconocidos.
    for table_name, row in helper.iter_informacion_ph():
        ref = helper.get_relation_value(row, ("arb_predio", "predio", "id_predio", "Id_Predio", "cca_predio"))
        predio_id = _admin_resolve_alias(aliases, ref)
        if predio_id and predio_id in predios:
            continue
        issues.append(RuleIssue(
            rule_id="1.22", object_ref=helper.identify(row),
            message="ARB_InformacionPH debe estar asociado a un predio matriz válido.",
            details={"tabla": table_name, "campo": "arb_predio", "class": table_name, "predio_referencia": ref},
        ))
    return issues

def _rule_1_23(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    issues: list[RuleIssue] = []
    predios = ctx["predios"]  # type: ignore[assignment]
    units_by_matrix = ctx["units_by_matrix"]  # type: ignore[assignment]
    for matrix_id, matrix in predios.items():
        if matrix["condicion"] not in {"PH_MATRIZ", "CONDOMINIO_MATRIZ"}:
            continue
        unit_ids = units_by_matrix.get(matrix_id, [])
        if len(unit_ids) != 1:
            continue
        issues.append(RuleIssue(
            rule_id="1.23", object_ref=matrix["object_ref"],
            message="Una única unidad predial no puede constituir un PH o Condominio.",
            details={"tabla": matrix["tabla"], "campo": "Numero_Predial_Nacional", "class": matrix["tabla"],
                     "numero_predial_matriz": matrix["npn"], "total_unidades_asociadas": 1,
                     "unidad_asociada": predios[unit_ids[0]]["npn"] if unit_ids[0] in predios else unit_ids[0]},
        ))
    return issues


def _rule_1_24(dataset: DatasetReader) -> list[RuleIssue]:
    """Las unidades PH/Condominio deben tener un predio matriz correspondiente en el dataset.

    En el XTF el modelo no materializa un campo ``predio_matriz`` en ARB_Predio.
    La asociación se determina por el NPN: misma base (posiciones 1-21) y el
    sufijo de matriz 900000000 para PH o 800000000 para Condominio.
    """
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []

    matrix_by_npn: dict[str, str] = {}
    unit_rows: list[tuple[str, dict[str, object], str, str, object]] = []

    for table_name, row in helper.iter_predios():
        condicion_raw = helper.get_field_value(row, helper.CONDICION_FIELDS)
        condicion = _normalize_condicion(condicion_raw)
        if condicion not in {
            "PH_MATRIZ", "CONDOMINIO_MATRIZ",
            "PH_UNIDAD_PREDIAL", "CONDOMINIO_UNIDAD_PREDIAL",
        }:
            continue

        result = helper.pull_predial_number(row, allow_guess=False)
        if not result:
            continue
        field_name, numero_str, raw_value = result
        if len(numero_str) < 30:
            continue

        if condicion == "PH_MATRIZ" and numero_str[21:30] == "900000000":
            matrix_by_npn[numero_str] = _get_t_id(row) or helper.identify(row) or ""
        elif condicion == "CONDOMINIO_MATRIZ" and numero_str[21:30] == "800000000":
            matrix_by_npn[numero_str] = _get_t_id(row) or helper.identify(row) or ""
        elif condicion in {"PH_UNIDAD_PREDIAL", "CONDOMINIO_UNIDAD_PREDIAL"}:
            unit_rows.append((table_name, row, condicion, field_name, raw_value))

    for table_name, row, condicion, field_name, raw_value in unit_rows:
        numero = helper.get_field_value(row, helper.NUMERO_PREDIAL_FIELDS)
        if not numero or len(numero) < 30:
            continue

        sufijo_matriz = "900000000" if condicion == "PH_UNIDAD_PREDIAL" else "800000000"
        numero_matriz_esperado = numero[:21] + sufijo_matriz

        if numero_matriz_esperado in matrix_by_npn:
            continue

        issues.append(
            RuleIssue(
                rule_id="1.24",
                object_ref=helper.identify(row),
                message=(
                    "El predio con condición de unidad predial PH o Condominio no tiene "
                    "un predio matriz correspondiente asociado."
                ),
                details={
                    "tabla": table_name,
                    "campo": field_name,
                    "class": table_name,
                    "predio_id": _get_t_id(row),
                    "numero_predial": numero,
                    "condicion_predio": helper.get_field_value(row, helper.CONDICION_FIELDS),
                    "numero_predial_matriz_esperado": numero_matriz_esperado,
                },
            )
        )

    return issues

def _rule_1_25(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    helper: NumeroPredialHelper = ctx["helper"]  # type: ignore[assignment]
    issues: list[RuleIssue] = []
    predios = ctx["predios"]  # type: ignore[assignment]
    terrains = ctx["terrain_areas_by_predio"]  # type: ignore[assignment]

    for matrix_id, matrix in predios.items():
        if matrix["condicion"] != "PH_MATRIZ":
            continue
        matrix_areas = terrains.get(matrix_id, [])
        if not matrix_areas:
            continue
        geom_area = sum(matrix_areas)
        info_entry = ctx["info_ph_by_predio"].get(matrix_id)  # type: ignore[index]
        if not info_entry:
            continue
        row = info_entry["row"]
        values = {}
        complete = True
        for key, fields in {
            "total": ("Area_Total_Terreno", "area_total_terreno"),
            "comun": ("Area_Total_Terreno_Comun", "area_total_terreno_comun"),
            "privada": ("Area_Total_Terreno_Privada", "area_total_terreno_privada"),
        }.items():
            raw = helper.get_field_value(row, fields)
            number = _admin_to_float(raw)
            values[key] = number
            if number is None:
                complete = False
        if not complete:
            continue
        failures = []
        total_ok, total_diff, total_tol = _admin_area_within_resolution_1040_tolerance(
            geom_area, values["total"], matrix["npn"]
        )
        common_ok, common_diff, common_tol = _admin_area_within_resolution_1040_tolerance(
            geom_area, values["comun"], matrix["npn"]
        )
        if not total_ok: failures.append("area_total_terreno")
        if not common_ok: failures.append("area_total_terreno_comun")
        if not _admin_close(values["privada"], 0.0): failures.append("area_total_terreno_privada")
        if not failures:
            continue
        issues.append(RuleIssue(
            rule_id="1.25", object_ref=matrix["object_ref"],
            message="Para PH.Matriz, el área total y común de terreno deben corresponder al área geográfica de la matriz y el área privada debe ser 0.",
            details={"tabla": info_entry["tabla"], "campo": ", ".join(failures), "class": info_entry["tabla"],
                     "numero_predial_matriz": matrix["npn"], "area_geografica_matriz": round(geom_area, 2),
                     "area_total_terreno": values["total"], "area_total_terreno_comun": values["comun"],
                     "area_total_terreno_privada": values["privada"], "campos_invalidos": failures,
                     "diferencia_porcentual_total": round(total_diff, 4),
                     "diferencia_porcentual_comun": round(common_diff, 4),
                     "tolerancia_porcentual_total": total_tol,
                     "tolerancia_porcentual_comun": common_tol},
        ))
    return issues


def _rule_1_26(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    issues: list[RuleIssue] = []
    predios = ctx["predios"]
    for matrix_id, matrix in predios.items():
        if matrix["condicion"] != "PH_MATRIZ":
            continue
        expected, field_name, raw, info = _admin_info_number(ctx, matrix_id, ("Area_Total_Construida", "area_total_construida"))
        if expected is None or not info:
            continue
        private_total, common_total, complete = _admin_matrix_area_components(ctx, matrix_id)
        if not complete:
            continue
        calculated = {"total": private_total + common_total, "private": private_total, "common": common_total}["total"]
        if _admin_close(expected, calculated):
            continue
        issues.append(RuleIssue(
            rule_id="1.26", object_ref=matrix["object_ref"],
            message='Para PH.Matriz, el área total construida debe ser la suma del área privada de sus unidades y el área construida común de la matriz.',
            details={"tabla": info["tabla"], "campo": field_name, "class": info["tabla"],
                     "numero_predial_matriz": matrix["npn"], "valor_registrado": expected,
                     "valor_calculado": round(calculated, 2), "area_privada_calculada": round(private_total, 2),
                     "area_comun_calculada": round(common_total, 2)},
        ))
    return issues


def _rule_1_27(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    issues: list[RuleIssue] = []
    predios = ctx["predios"]
    for matrix_id, matrix in predios.items():
        if matrix["condicion"] != "PH_MATRIZ":
            continue
        expected, field_name, raw, info = _admin_info_number(ctx, matrix_id, ("Area_Total_Construida_Privada", "area_total_construida_privada"))
        if expected is None or not info:
            continue
        private_total, common_total, complete = _admin_matrix_area_components(ctx, matrix_id)
        if not complete:
            continue
        calculated = {"total": private_total + common_total, "private": private_total, "common": common_total}["private"]
        if _admin_close(expected, calculated):
            continue
        issues.append(RuleIssue(
            rule_id="1.27", object_ref=matrix["object_ref"],
            message='Para PH.Matriz, el área total construida privada debe ser la suma de las áreas privadas construidas de sus unidades prediales.',
            details={"tabla": info["tabla"], "campo": field_name, "class": info["tabla"],
                     "numero_predial_matriz": matrix["npn"], "valor_registrado": expected,
                     "valor_calculado": round(calculated, 2), "area_privada_calculada": round(private_total, 2),
                     "area_comun_calculada": round(common_total, 2)},
        ))
    return issues


def _rule_1_28(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    issues: list[RuleIssue] = []
    predios = ctx["predios"]
    for matrix_id, matrix in predios.items():
        if matrix["condicion"] != "PH_MATRIZ":
            continue
        expected, field_name, raw, info = _admin_info_number(ctx, matrix_id, ("Area_Total_Construida_Comun", "area_total_construida_comun"))
        if expected is None or not info:
            continue
        private_total, common_total, complete = _admin_matrix_area_components(ctx, matrix_id)
        if not complete:
            continue
        calculated = {"total": private_total + common_total, "private": private_total, "common": common_total}["common"]
        if _admin_close(expected, calculated):
            continue
        issues.append(RuleIssue(
            rule_id="1.28", object_ref=matrix["object_ref"],
            message='Para PH.Matriz, el área total construida común debe ser la suma de las áreas construidas asociadas al predio matriz.',
            details={"tabla": info["tabla"], "campo": field_name, "class": info["tabla"],
                     "numero_predial_matriz": matrix["npn"], "valor_registrado": expected,
                     "valor_calculado": round(calculated, 2), "area_privada_calculada": round(private_total, 2),
                     "area_comun_calculada": round(common_total, 2)},
        ))
    return issues


def _rule_1_29(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    issues: list[RuleIssue] = []
    predios = ctx["predios"]  # type: ignore[assignment]
    units_by_matrix = ctx["units_by_matrix"]  # type: ignore[assignment]
    for matrix_id, matrix in predios.items():
        if matrix["condicion"] != "PH_MATRIZ":
            continue
        value, field_name, raw, info = _admin_info_number(ctx, matrix_id, ("Numero_Torres", "numero_torres"))
        if value is None or not info:
            continue
        unit_ids = units_by_matrix.get(matrix_id, [])
        tower_values: list[int] = []
        for uid in unit_ids:
            npn = str(predios.get(uid, {}).get("npn") or "")
            if len(npn) >= 26 and npn[24:26].isdigit():
                tower_values.append(int(npn[24:26]))
        if not tower_values:
            continue
        expected = max(tower_values)
        actual = _admin_to_int(value)
        if actual == expected:
            continue
        issues.append(RuleIssue(
            rule_id="1.29", object_ref=matrix["object_ref"],
            message="Para PH.Matriz, el número de torres debe ser igual al máximo indicado en las posiciones 25-26 de las unidades asociadas.",
            details={"tabla": info["tabla"], "campo": field_name, "class": info["tabla"],
                     "numero_predial_matriz": matrix["npn"], "numero_torres": raw,
                     "numero_torres_esperado": expected, "torres_en_unidades": tower_values},
        ))
    return issues


def _rule_1_30(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    issues: list[RuleIssue] = []
    predios = ctx["predios"]  # type: ignore[assignment]
    units_by_matrix = ctx["units_by_matrix"]  # type: ignore[assignment]
    for matrix_id, matrix in predios.items():
        if matrix["condicion"] != "PH_MATRIZ":
            continue
        value, field_name, raw, info = _admin_info_number(ctx, matrix_id, ("Total_Unidades_Privadas", "total_unidades_privadas"))
        if value is None or not info:
            continue
        expected = len(units_by_matrix.get(matrix_id, []))
        actual = _admin_to_int(value)
        if actual == expected:
            continue
        issues.append(RuleIssue(
            rule_id="1.30", object_ref=matrix["object_ref"],
            message="Para PH.Matriz, el total de unidades privadas debe ser el conteo de predios asociados al PH.",
            details={"tabla": info["tabla"], "campo": field_name, "class": info["tabla"],
                     "numero_predial_matriz": matrix["npn"], "total_unidades_privadas": raw,
                     "conteo_unidades_asociadas": expected},
        ))
    return issues


def _rule_1_31(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    issues: list[RuleIssue] = []
    predios = ctx["predios"]
    terrains = ctx["terrain_areas_by_predio"]
    units_by_matrix = ctx["units_by_matrix"]
    for matrix_id, matrix in predios.items():
        if matrix["condicion"] != "CONDOMINIO_MATRIZ":
            continue
        registered, field_name, raw, info = _admin_info_number(ctx, matrix_id, ("Area_Total_Terreno", "area_total_terreno"))
        if registered is None or not info:
            continue
        matrix_areas = terrains.get(matrix_id, [])
        if not matrix_areas:
            continue
        matrix_area = sum(matrix_areas)
        private_area = 0.0
        complete = True
        for uid in units_by_matrix.get(matrix_id, []):
            unit_areas = terrains.get(uid, [])
            if not unit_areas:
                complete = False
                break
            private_area += sum(unit_areas)
        if not complete:
            continue
        calculated = {"total": matrix_area + private_area, "private": private_area, "common": matrix_area}["total"]
        if _admin_close(registered, calculated):
            continue
        issues.append(RuleIssue(
            rule_id="1.31", object_ref=matrix["object_ref"],
            message='Para Condominio.Matriz, el área total de terreno debe ser el área geográfica de la matriz más las áreas geográficas de sus unidades privadas.',
            details={"tabla": info["tabla"], "campo": field_name, "class": info["tabla"],
                     "numero_predial_matriz": matrix["npn"], "valor_registrado": registered,
                     "valor_calculado": round(calculated, 2), "area_geografica_matriz": round(matrix_area, 2),
                     "suma_areas_privadas": round(private_area, 2)},
        ))
    return issues


def _rule_1_32(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    issues: list[RuleIssue] = []
    predios = ctx["predios"]
    terrains = ctx["terrain_areas_by_predio"]
    units_by_matrix = ctx["units_by_matrix"]
    for matrix_id, matrix in predios.items():
        if matrix["condicion"] != "CONDOMINIO_MATRIZ":
            continue
        registered, field_name, raw, info = _admin_info_number(ctx, matrix_id, ("Area_Total_Terreno_Privada", "area_total_terreno_privada"))
        if registered is None or not info:
            continue
        matrix_areas = terrains.get(matrix_id, [])
        if not matrix_areas:
            continue
        matrix_area = sum(matrix_areas)
        private_area = 0.0
        complete = True
        for uid in units_by_matrix.get(matrix_id, []):
            unit_areas = terrains.get(uid, [])
            if not unit_areas:
                complete = False
                break
            private_area += sum(unit_areas)
        if not complete:
            continue
        calculated = {"total": matrix_area + private_area, "private": private_area, "common": matrix_area}["private"]
        within_tolerance, difference_percent, tolerance_percent = _admin_area_within_resolution_1040_tolerance(
            calculated, registered, matrix["npn"]
        )
        if within_tolerance:
            continue
        issues.append(RuleIssue(
            rule_id="1.32", object_ref=matrix["object_ref"],
            message='Para Condominio.Matriz, el área total de terreno privada debe ser la suma de las áreas geográficas de sus unidades privadas.',
            details={"tabla": info["tabla"], "campo": field_name, "class": info["tabla"],
                     "numero_predial_matriz": matrix["npn"], "valor_registrado": registered,
                     "valor_calculado": round(calculated, 2), "area_geografica_matriz": round(matrix_area, 2),
                     "suma_areas_privadas": round(private_area, 2),
                     "diferencia_porcentual": round(difference_percent, 4),
                     "tolerancia_porcentual": tolerance_percent},
        ))
    return issues


def _rule_1_33(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    issues: list[RuleIssue] = []
    predios = ctx["predios"]
    terrains = ctx["terrain_areas_by_predio"]
    units_by_matrix = ctx["units_by_matrix"]
    for matrix_id, matrix in predios.items():
        if matrix["condicion"] != "CONDOMINIO_MATRIZ":
            continue
        registered, field_name, raw, info = _admin_info_number(ctx, matrix_id, ("Area_Total_Terreno_Comun", "area_total_terreno_comun"))
        if registered is None or not info:
            continue
        matrix_areas = terrains.get(matrix_id, [])
        if not matrix_areas:
            continue
        matrix_area = sum(matrix_areas)
        private_area = 0.0
        complete = True
        for uid in units_by_matrix.get(matrix_id, []):
            unit_areas = terrains.get(uid, [])
            if not unit_areas:
                complete = False
                break
            private_area += sum(unit_areas)
        if not complete:
            continue
        calculated = {"total": matrix_area + private_area, "private": private_area, "common": matrix_area}["common"]
        within_tolerance, difference_percent, tolerance_percent = _admin_area_within_resolution_1040_tolerance(
            calculated, registered, matrix["npn"]
        )
        if within_tolerance:
            continue
        issues.append(RuleIssue(
            rule_id="1.33", object_ref=matrix["object_ref"],
            message='Para Condominio.Matriz, el área total de terreno común debe corresponder al área geográfica del predio matriz.',
            details={"tabla": info["tabla"], "campo": field_name, "class": info["tabla"],
                     "numero_predial_matriz": matrix["npn"], "valor_registrado": registered,
                     "valor_calculado": round(calculated, 2), "area_geografica_matriz": round(matrix_area, 2),
                     "suma_areas_privadas": round(private_area, 2),
                     "diferencia_porcentual": round(difference_percent, 4),
                     "tolerancia_porcentual": tolerance_percent},
        ))
    return issues



def _rule_1_34(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    issues: list[RuleIssue] = []
    predios = ctx["predios"]
    for matrix_id, matrix in predios.items():
        if matrix["condicion"] != "CONDOMINIO_MATRIZ":
            continue
        expected, field_name, raw, info = _admin_info_number(ctx, matrix_id, ("Area_Total_Construida", "area_total_construida"))
        if expected is None or not info:
            continue
        private_total, common_total, complete = _admin_matrix_area_components(ctx, matrix_id)
        if not complete:
            continue
        calculated = {"total": private_total + common_total, "private": private_total, "common": common_total}["total"]
        if _admin_close(expected, calculated):
            continue
        issues.append(RuleIssue(
            rule_id="1.34", object_ref=matrix["object_ref"],
            message='Para Condominio.Matriz, el área total construida debe ser la suma del área privada de sus unidades y el área construida común de la matriz.',
            details={"tabla": info["tabla"], "campo": field_name, "class": info["tabla"],
                     "numero_predial_matriz": matrix["npn"], "valor_registrado": expected,
                     "valor_calculado": round(calculated, 2), "area_privada_calculada": round(private_total, 2),
                     "area_comun_calculada": round(common_total, 2)},
        ))
    return issues


def _rule_1_35(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    issues: list[RuleIssue] = []
    predios = ctx["predios"]
    for matrix_id, matrix in predios.items():
        if matrix["condicion"] != "CONDOMINIO_MATRIZ":
            continue
        expected, field_name, raw, info = _admin_info_number(ctx, matrix_id, ("Area_Total_Construida_Privada", "area_total_construida_privada"))
        if expected is None or not info:
            continue
        private_total, common_total, complete = _admin_matrix_area_components(ctx, matrix_id)
        if not complete:
            continue
        calculated = {"total": private_total + common_total, "private": private_total, "common": common_total}["private"]
        if _admin_close(expected, calculated):
            continue
        issues.append(RuleIssue(
            rule_id="1.35", object_ref=matrix["object_ref"],
            message='Para Condominio.Matriz, el área total construida privada debe ser la suma de las áreas privadas construidas de sus unidades prediales.',
            details={"tabla": info["tabla"], "campo": field_name, "class": info["tabla"],
                     "numero_predial_matriz": matrix["npn"], "valor_registrado": expected,
                     "valor_calculado": round(calculated, 2), "area_privada_calculada": round(private_total, 2),
                     "area_comun_calculada": round(common_total, 2)},
        ))
    return issues


def _rule_1_36(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    issues: list[RuleIssue] = []
    predios = ctx["predios"]
    for matrix_id, matrix in predios.items():
        if matrix["condicion"] != "CONDOMINIO_MATRIZ":
            continue
        expected, field_name, raw, info = _admin_info_number(ctx, matrix_id, ("Area_Total_Construida_Comun", "area_total_construida_comun"))
        if expected is None or not info:
            continue
        private_total, common_total, complete = _admin_matrix_area_components(ctx, matrix_id)
        if not complete:
            continue
        calculated = {"total": private_total + common_total, "private": private_total, "common": common_total}["common"]
        if _admin_close(expected, calculated):
            continue
        issues.append(RuleIssue(
            rule_id="1.36", object_ref=matrix["object_ref"],
            message='Para Condominio.Matriz, el área total construida común debe ser la suma de las áreas construidas asociadas al predio matriz.',
            details={"tabla": info["tabla"], "campo": field_name, "class": info["tabla"],
                     "numero_predial_matriz": matrix["npn"], "valor_registrado": expected,
                     "valor_calculado": round(calculated, 2), "area_privada_calculada": round(private_total, 2),
                     "area_comun_calculada": round(common_total, 2)},
        ))
    return issues


def _rule_1_37(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    issues: list[RuleIssue] = []
    predios = ctx["predios"]  # type: ignore[assignment]
    for matrix_id, matrix in predios.items():
        if matrix["condicion"] != "CONDOMINIO_MATRIZ":
            continue
        value, field_name, raw, info = _admin_info_number(ctx, matrix_id, ("Numero_Torres", "numero_torres"))
        if value is None or not info:
            continue
        actual = _admin_to_int(value)
        if actual == 0:
            continue
        issues.append(RuleIssue(
            rule_id="1.37", object_ref=matrix["object_ref"],
            message="Para Condominio.Matriz, el número de torres debe ser 0.",
            details={"tabla": info["tabla"], "campo": field_name, "class": info["tabla"],
                     "numero_predial_matriz": matrix["npn"], "numero_torres": raw, "valor_esperado": 0},
        ))
    return issues


def _rule_1_38(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    issues: list[RuleIssue] = []
    predios = ctx["predios"]  # type: ignore[assignment]
    units_by_matrix = ctx["units_by_matrix"]  # type: ignore[assignment]
    for matrix_id, matrix in predios.items():
        if matrix["condicion"] != "CONDOMINIO_MATRIZ":
            continue
        value, field_name, raw, info = _admin_info_number(ctx, matrix_id, ("Total_Unidades_Privadas", "total_unidades_privadas"))
        if value is None or not info:
            continue
        expected = len(units_by_matrix.get(matrix_id, []))
        actual = _admin_to_int(value)
        if actual == expected:
            continue
        issues.append(RuleIssue(
            rule_id="1.38", object_ref=matrix["object_ref"],
            message="Para Condominio.Matriz, el total de unidades privadas debe ser el conteo de predios asociados al Condominio.",
            details={"tabla": info["tabla"], "campo": field_name, "class": info["tabla"],
                     "numero_predial_matriz": matrix["npn"], "total_unidades_privadas": raw,
                     "conteo_unidades_asociadas": expected},
        ))
    return issues


def _rule_1_39(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    helper: NumeroPredialHelper = ctx["helper"]  # type: ignore[assignment]
    aliases = ctx["predio_aliases"]  # type: ignore[assignment]
    predios = ctx["predios"]  # type: ignore[assignment]
    issues: list[RuleIssue] = []
    dirs: dict[str, list[tuple[object, bool | None]]] = {}

    def parse_bool(value: object) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        text = helper._normalize_key(str(value))
        if text in {"true", "verdadero", "si", "1", "yes"}: return True
        if text in {"false", "falso", "no", "0"}: return False
        return None

    for _, row in helper.iter_direcciones():
        ref = helper.get_relation_value(row, (
            "arb_predio_direccion", "arb_direccion_arb_predio_direccion_fkey", "arb_predio",
            "predio", "predio_asociado", "id_predio", "Id_Predio",
        ))
        predio_id = _admin_resolve_alias(aliases, ref)
        if not predio_id:
            continue
        raw = helper.get_field_value(row, (
            "es_direccion_principal", "Es_Direccion_Principal", "es_principal", "Es_Principal",
            "direccion_principal", "Direccion_Principal", "principal", "Principal",
        ))
        dirs.setdefault(predio_id, []).append((raw, parse_bool(raw)))

    for predio_id, values in dirs.items():
        predio = predios.get(predio_id)
        if not predio:
            continue
        total = len(values)
        trues = sum(1 for _, val in values if val is True)
        unknown = sum(1 for _, val in values if val is None)
        valid = (total == 1 and trues == 1 and unknown == 0) or (total > 1 and trues == 1 and unknown == 0)
        if valid:
            continue
        issues.append(RuleIssue(
            rule_id="1.39", object_ref=predio["object_ref"],
            message=("Si el predio tiene una sola dirección, esta debe ser principal; si tiene más de una, "
                     "debe existir exactamente una principal y todas las demás deben ser falsas."),
            details={"tabla": predio["tabla"], "campo": "es_direccion_principal", "class": predio["tabla"],
                     "numero_predial": predio["npn"], "total_direcciones": total,
                     "total_principales": trues, "valores_no_booleanos_o_nulos": unknown,
                     "valores": [raw for raw, _ in values]},
        ))
    return issues


def _normalize_direccion_tipo(value: object) -> str:
    """Normaliza el dominio ARB_DireccionTipo sin depender de su representación.

    XTF normalmente entrega iliCode (Estructurada/No_Estructurada), mientras
    QGIS puede materializar la FK como t_id. El adaptador QGIS intenta resolver
    esa FK a iliCode; se conservan 0/1 como respaldo de intercambios antiguos.
    """
    if value in (None, ""):
        return ""
    token = NumeroPredialHelper._normalize_key(str(value))
    if token in {"estructurada", "direccionestructurada", "0"}:
        return "ESTRUCTURADA"
    if token in {"noestructurada", "direccionnoestructurada", "1"}:
        return "NO_ESTRUCTURADA"
    return ""

def _rule_1_40(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []
    required = {
        "clase_via_principal": ("clase_via_principal", "Clase_Via_Principal"),
        "valor_via_principal": ("valor_via_principal", "Valor_Via_Principal"),
        "valor_via_generadora": ("valor_via_generadora", "Valor_Via_Generadora"),
        "numero_predio": ("numero_predio", "Numero_Predio"),
    }
    for table_name, row in helper.iter_direcciones():
        tipo_match = helper._extract_field(row, ("tipo_direccion", "Tipo_Direccion"), require_value=False)
        tipo_raw = tipo_match[1] if tipo_match else None
        if _normalize_direccion_tipo(tipo_raw) != "ESTRUCTURADA":
            continue
        faltantes: list[str] = []
        for label, fields in required.items():
            match = helper._extract_field(row, fields, require_value=False)
            if not match or helper._is_empty(match[1]):
                faltantes.append(label)
        nombre_match = helper._extract_field(row, ("nombre_predio", "Nombre_Predio"), require_value=False)
        nombre_raw = nombre_match[1] if nombre_match else None
        if not faltantes and helper._is_empty(nombre_raw):
            continue
        ref = helper.get_relation_value(row, ("arb_predio_direccion", "arb_direccion_arb_predio_direccion_fkey", "predio", "arb_predio"))
        issues.append(RuleIssue(
            rule_id="1.40", object_ref=helper.identify(row) or ref,
            message=("Si el tipo de dirección es Estructurada, clase_via_principal, valor_via_principal, "
                     "valor_via_generadora y numero_predio deben estar diligenciados y nombre_predio debe ser NULL."),
            details={"tabla": table_name, "class": table_name,
                     "campo": tipo_match[0] if tipo_match else "tipo_direccion", "tipo_direccion": tipo_raw,
                     "faltantes": faltantes, "nombre_predio": nombre_raw},
        ))
    return issues

def _rule_1_41(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []
    # En una dirección No_Estructurada:
    # - Nombre_Predio es obligatorio.
    # - Clase_Via_Principal puede estar diligenciada.
    # - Los campos numéricos con valor 0 se consideran valores por defecto/no diligenciados.
    forbidden = {
        "complemento": ("complemento", "Complemento"),
        "codigo_postal": ("codigo_postal", "Codigo_Postal"),
        "letra_via_principal": ("letra_via_principal", "Letra_Via_Principal"),
        "letra_via_generadora": ("letra_via_generadora", "Letra_Via_Generadora"),
        "sector_ciudad": ("sector_ciudad", "Sector_Ciudad"),
        "sector_predio": ("sector_predio", "Sector_Predio"),
    }
    numeric_default_zero = {
        "valor_via_principal": ("valor_via_principal", "Valor_Via_Principal"),
        "valor_via_generadora": ("valor_via_generadora", "Valor_Via_Generadora"),
        "numero_predio": ("numero_predio", "Numero_Predio"),
    }

    def tiene_valor_real(valor: object) -> bool:
        if helper._is_empty(valor):
            return False
        texto = str(valor).strip().replace(",", ".")
        try:
            return abs(float(texto)) > 1e-12
        except Exception:
            return True

    for table_name, row in helper.iter_direcciones():
        tipo_match = helper._extract_field(
            row,
            ("tipo_direccion", "Tipo_Direccion"),
            require_value=False
        )
        tipo_raw = tipo_match[1] if tipo_match else None
        if _normalize_direccion_tipo(tipo_raw) != "NO_ESTRUCTURADA":
            continue

        nombre_match = helper._extract_field(
            row,
            ("nombre_predio", "Nombre_Predio"),
            require_value=False
        )
        nombre_raw = nombre_match[1] if nombre_match else None

        clase_match = helper._extract_field(
            row,
            ("clase_via_principal", "Clase_Via_Principal"),
            require_value=False
        )
        clase_raw = clase_match[1] if clase_match else None

        indebidos: list[str] = []

        for label, fields in forbidden.items():
            match = helper._extract_field(row, fields, require_value=False)
            if match and not helper._is_empty(match[1]):
                indebidos.append(label)

        for label, fields in numeric_default_zero.items():
            match = helper._extract_field(row, fields, require_value=False)
            if match and tiene_valor_real(match[1]):
                indebidos.append(label)

        if not helper._is_empty(nombre_raw) and not indebidos:
            continue

        ref = helper.get_relation_value(
            row,
            (
                "arb_predio_direccion",
                "arb_direccion_arb_predio_direccion_fkey",
                "predio",
                "arb_predio"
            )
        )

        issues.append(
            RuleIssue(
                rule_id="1.41",
                object_ref=helper.identify(row) or ref,
                message=(
                    "Si el tipo de dirección es No_Estructurada, Nombre_Predio debe "
                    "estar diligenciado. Clase_Via_Principal puede estar diligenciada "
                    "y los valores numéricos de dirección pueden permanecer en cero."
                ),
                details={
                    "tabla": table_name,
                    "class": table_name,
                    "campo": tipo_match[0] if tipo_match else "tipo_direccion",
                    "tipo_direccion": tipo_raw,
                    "nombre_predio": nombre_raw,
                    "clase_via_principal": clase_raw,
                    "campos_indebidos": indebidos,
                },
            )
        )

    return issues

def _rule_1_42(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    helper: NumeroPredialHelper = ctx["helper"]
    aliases = ctx["predio_aliases"]
    predios = ctx["predios"]
    issues: list[RuleIssue] = []
    for table_name, row in helper.iter_direcciones():
        ref = helper.get_relation_value(row, (
            "arb_predio_direccion", "arb_direccion_arb_predio_direccion_fkey", "arb_predio",
            "predio", "predio_asociado", "id_predio", "Id_Predio",
        ))
        predio_id = _admin_resolve_alias(aliases, ref)
        predio = predios.get(predio_id or "")
        if not predio:
            continue
        npn = str(predio["npn"] or "")
        if len(npn) < 7:
            continue
        expected = "NO_ESTRUCTURADA" if npn[5:7] == "00" else "ESTRUCTURADA"
        match = helper._extract_field(row, ("tipo_direccion", "Tipo_Direccion"), require_value=False)
        raw = match[1] if match else None
        actual = _normalize_direccion_tipo(raw)
        if not actual or actual == expected:
            continue
        issues.append(RuleIssue(
            rule_id="1.42", object_ref=predio["object_ref"],
            message="El tipo de dirección debe corresponder al carácter rural/urbano indicado por los dígitos 6-7 del número predial.",
            details={"tabla": table_name, "campo": match[0] if match else "tipo_direccion", "class": table_name,
                     "numero_predial": npn, "digitos_6_7": npn[5:7], "tipo_direccion": raw,
                     "tipo_esperado": expected},
        ))
    return issues

def _rule_1_43(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []
    for table_name, row in helper.iter_direcciones():
        tipo_match = helper._extract_field(row, ("tipo_direccion", "Tipo_Direccion"), require_value=False)
        tipo_raw = tipo_match[1] if tipo_match else None
        if _normalize_direccion_tipo(tipo_raw) != "ESTRUCTURADA":
            continue
        invalid: list[str] = []
        values: dict[str, object] = {}
        for label, fields in {
            "letra_via_principal": ("letra_via_principal", "Letra_Via_Principal"),
            "letra_via_generadora": ("letra_via_generadora", "Letra_Via_Generadora"),
        }.items():
            match = helper._extract_field(row, fields, require_value=False)
            raw = match[1] if match else None
            values[label] = raw
            if helper._is_empty(raw):
                continue
            text = unicodedata.normalize("NFKD", str(raw).strip())
            text = "".join(ch for ch in text if not unicodedata.combining(ch))
            if not text.isalpha():
                invalid.append(label)
        if not invalid:
            continue
        ref = helper.get_relation_value(row, ("arb_predio_direccion", "arb_direccion_arb_predio_direccion_fkey", "predio", "arb_predio"))
        issues.append(RuleIssue(
            rule_id="1.43", object_ref=helper.identify(row) or ref,
            message="En una dirección Estructurada, Letra_Via_Principal y Letra_Via_Generadora deben ser alfabéticas cuando estén diligenciadas.",
            details={"tabla": table_name, "class": table_name,
                     "campo": tipo_match[0] if tipo_match else "tipo_direccion", "tipo_direccion": tipo_raw,
                     **values, "campos_invalidos": invalid},
        ))
    return issues

def _resultado_visita_es_exitoso(row: dict[str, object], helper: NumeroPredialHelper) -> bool:
    """Las reglas de contacto de visita solo aplican cuando el resultado es Exitoso."""
    value = helper.get_field_value(row, ("resultado_visita", "Resultado_Visita", "Resultado Visita"))
    if value in (None, ""):
        return False
    token = helper._normalize_key(str(value))
    return token in {"exitoso", "exitosa", "exito", "visitaexitosa", "resultadoexitoso"}


def _rule_1_44(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []
    for table_name, row in helper.iter_predios():
        if not _resultado_visita_es_exitoso(row, helper):
            continue
        nombres = helper.get_field_value(row, (
            "nombres_apellidos_quien_atendio", "Nombres_Apellidos_Quien_Atendio",
        ))
        if not nombres:
            continue
        match = helper._extract_field(
            row, ("tipo_documento_quien_atendio", "Tipo_Documento_Quien_Atendio"), require_value=False
        )
        raw = match[1] if match else None
        token = helper._normalize_key(str(raw or ""))
        # El XTF usa el valor semántico NIT; algunos flujos antiguos pueden
        # entregar itfCode=2. En QGIS el adaptador resuelve la FK t_id a iliCode.
        invalid_nit = token in {"nit", "2"}
        if raw not in (None, "") and not invalid_nit:
            continue
        numero_documento = helper.get_field_value(row, (
            "numero_documento_quien_atendio", "Numero_Documento_Quien_Atendio",
        ))
        issues.append(RuleIssue(
            rule_id="1.44", object_ref=helper.identify(row),
            message=("Cuando el resultado de la visita es Exitoso y existen datos de quien atendió, "
                     "tipo_documento_quien_atendio debe estar diligenciado y no puede ser NIT."),
            details={"tabla": table_name, "campo": match[0] if match else "tipo_documento_quien_atendio",
                     "class": table_name, "nombres_apellidos_quien_atendio": nombres,
                     "tipo_documento_quien_atendio": raw,
                     "numero_documento_quien_atendio": numero_documento,
                     "motivo": "NIT no permitido" if invalid_nit else "tipo de documento vacío"},
        ))
    return issues


def _rule_1_45(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []
    for table_name, row in helper.iter_predios():
        if not _resultado_visita_es_exitoso(row, helper):
            continue
        nombres = helper.get_field_value(row, ("nombres_apellidos_quien_atendio", "Nombres_Apellidos_Quien_Atendio"))
        if not nombres:
            continue
        match = helper._extract_field(row, ("numero_documento_quien_atendio", "Numero_Documento_Quien_Atendio"), require_value=False)
        raw = match[1] if match else None
        value = "" if helper._is_empty(raw) else str(raw).strip()
        if value and value.isdigit():
            continue
        issues.append(RuleIssue(
            rule_id="1.45", object_ref=helper.identify(row),
            message=("Cuando el resultado de la visita es Exitoso y existen datos de quien atendió, "
                     "Numero_Documento_Quien_Atendio debe estar diligenciado y contener solo caracteres numéricos."),
            details={"tabla": table_name, "campo": match[0] if match else "numero_documento_quien_atendio",
                     "class": table_name, "nombres_apellidos_quien_atendio": nombres,
                     "numero_documento_quien_atendio": raw},
        ))
    return issues

def _rule_1_46(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []
    email_regex = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
    for table_name, row in helper.iter_predios():
        match = helper._extract_field(row, ("correo_electronico", "Correo_Electronico"), require_value=False)
        if not match or helper._is_empty(match[1]):
            continue
        field, raw = match
        value = str(raw).strip()
        if email_regex.fullmatch(value):
            continue
        issues.append(RuleIssue(
            rule_id="1.46", object_ref=helper.identify(row),
            message="El correo electrónico no tiene una estructura lógica nombre_usuario@dominio.",
            details={"tabla": table_name, "campo": field, "class": table_name, "correo_electronico": value},
        ))
    return issues

def _rule_1_47(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []
    def is_true(value: object) -> bool:
        if isinstance(value, bool): return value
        return helper._normalize_key(str(value or "")) in {"true", "verdadero", "si", "1", "yes", "t"}
    for table_name, row in helper.iter_predios():
        if not _resultado_visita_es_exitoso(row, helper):
            continue
        match = helper._extract_field(row, ("autoriza_notificaciones", "Autoriza_Notificaciones"), require_value=False)
        raw = match[1] if match else None
        if not is_true(raw):
            continue
        celular = helper.get_field_value(row, ("celular", "Celular"))
        correo = helper.get_field_value(row, ("correo_electronico", "Correo_Electronico"))
        if celular or correo:
            continue
        issues.append(RuleIssue(
            rule_id="1.47", object_ref=helper.identify(row),
            message="Si Autoriza_Notificaciones es verdadero, debe diligenciarse celular y/o correo electrónico.",
            details={"tabla": table_name, "campo": match[0] if match else "autoriza_notificaciones",
                     "class": table_name, "autoriza_notificaciones": raw, "celular": celular, "correo_electronico": correo},
        ))
    return issues

def _rule_1_48(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []
    for table_name, row in helper.iter_predios():
        match = helper._extract_field(row, ("domicilio_notificaciones", "Domicilio_Notificaciones"), require_value=False)
        if not match or helper._is_empty(match[1]):
            continue
        field, raw = match
        value = str(raw).strip()
        if len(value) >= 7:
            continue
        issues.append(RuleIssue(
            rule_id="1.48", object_ref=helper.identify(row),
            message="Domicilio_Notificaciones debe contener al menos 7 caracteres.",
            details={"tabla": table_name, "campo": field, "class": table_name,
                     "domicilio_notificaciones": value, "longitud": len(value), "longitud_minima": 7},
        ))
    return issues

def _rule_1_49(dataset: DatasetReader) -> list[RuleIssue]:
    ctx = _build_admin_property_context(dataset)
    helper: NumeroPredialHelper = ctx["helper"]  # type: ignore[assignment]
    aliases = ctx["predio_aliases"]  # type: ignore[assignment]
    predios = ctx["predios"]  # type: ignore[assignment]
    issues: list[RuleIssue] = []
    target = {"PH_UNIDAD_PREDIAL", "CONDOMINIO_UNIDAD_PREDIAL"}
    allowed = ("AP", "BQ", "BD", "CS", "ED", "ET", "GA", "IN", "L", "LO", "MZ", "OF", "PQ", "PN", "TO", "UN", "UR")
    pattern = re.compile(r"(?:^|[^A-Z0-9])(" + "|".join(sorted(allowed, key=len, reverse=True)) + r")(?:$|[^A-Z0-9])", re.IGNORECASE)

    directions_by_predio: dict[str, list[tuple[str, dict[str, object]]]] = {}
    for table_name, row in helper.iter_direcciones():
        ref = helper.get_relation_value(row, (
            "arb_predio_direccion", "arb_direccion_arb_predio_direccion_fkey", "arb_predio",
            "predio", "predio_asociado", "id_predio", "Id_Predio",
        ))
        predio_id = _admin_resolve_alias(aliases, ref)
        if predio_id:
            directions_by_predio.setdefault(predio_id, []).append((table_name, row))

    for predio_id, predio in predios.items():
        if predio["condicion"] not in target:
            continue
        directions = directions_by_predio.get(predio_id, [])
        # La falta total de dirección es obligatoriedad (11.2), no se duplica aquí.
        for table_name, row in directions:
            match = helper._extract_field(row, ("complemento", "Complemento"), require_value=False)
            raw = match[1] if match else None
            text = "" if raw in (None, "") else str(raw).strip().upper()
            if text and pattern.search(text):
                continue
            issues.append(RuleIssue(
                rule_id="1.49", object_ref=predio["object_ref"],
                message=("Para predios PH.Unidad_Predial o Condominio.Unidad_Predial, cada dirección asociada "
                         "debe contener en Complemento uno de los códigos permitidos."),
                details={"tabla": table_name, "campo": match[0] if match else "complemento", "class": table_name,
                         "numero_predial": predio["npn"], "condicion_predio": predio["condicion_raw"],
                         "complemento": raw, "valores_permitidos": list(allowed),
                         "direccion_ref": helper.identify(row)},
            ))
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

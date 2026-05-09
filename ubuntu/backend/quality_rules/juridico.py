from __future__ import annotations
from datetime import date, datetime
import re
from .base import DatasetReader, RuleIssue

COMPONENT_SLUG = "juridico"

DEFAULT_RULE_IDS = frozenset({
    "2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "2.7", "2.8", "2.9", "2.10",
    "2.11", "2.12", "2.13", "2.14", "2.15", "2.16", "2.17", "2.18", "2.19", "2.20",
    "2.21", "2.22", "2.23", "2.24", "2.25", "2.26", "2.27", "2.28", "2.29", "2.30",
    "2.31", "2.32",
})


class JuridicoHelper:
    """Utilidades compartidas para reglas jurídicas."""

    IDENTIFIER_FIELDS = (
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
        "t_id",
        "T_ID",
        "tid",
        "TID",
        "t_ili_tid",
        "T_ILI_TID",
    )

    PREDIO_TABLES = (
        "ARB_Predio",
        "arb_predio",
    )

    DERECHO_INTERESADO_FUENTE_TABLES = (
        "ARB_DerechoInteresadoFuente",
        "arb_derechointeresadofuente",
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

    def iter_derecho_interesado_fuente(self):
        yield from self._iter_table_rows(self.DERECHO_INTERESADO_FUENTE_TABLES)

    def identify(self, row: dict[str, object]) -> str | None:
        for field in self.IDENTIFIER_FIELDS:
            value = row.get(field)
            if value not in (None, ""):
                return str(value).strip()

        normalized_targets = {self._normalize_key(field) for field in self.IDENTIFIER_FIELDS}
        for key, candidate in row.items():
            if self._normalize_key(str(key)) in normalized_targets and candidate not in (None, ""):
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
        fixed_details = details or {}

        if "class" not in fixed_details:
            if "tabla" in fixed_details:
                fixed_details["class"] = fixed_details["tabla"]
            elif "tabla_error" in fixed_details:
                fixed_details["class"] = fixed_details["tabla_error"]

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
            if cls._normalize_key(str(key)) in normalized_candidates:
                if not require_value or not cls._is_empty(value):
                    return key, value

        return None


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None

    text = str(value).strip()
    if not text:
        return None

    text = text.replace("T", " ")

    formats = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%d/%m/%Y",
        "%d-%m-%Y",
    )

    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _matricula_es_vacia_o_cero(value: str | None) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text == "0"


def _numero_predial_es_rural(numero_predial: str | None) -> bool:
    if not numero_predial or len(numero_predial) < 7:
        return False
    return numero_predial[5:7] == "00"


def _numero_predial_es_urbano_sql(numero_predial: str | None) -> bool:
    if not numero_predial or len(numero_predial) < 7:
        return False
    return numero_predial[5:7] == "01"

def _normalize_text_for_compare(value: object) -> str:
    if value in (None, ""):
        return ""

    text = str(value).strip().upper()
    text = (
        text.replace("Á", "A")
        .replace("É", "E")
        .replace("Í", "I")
        .replace("Ó", "O")
        .replace("Ú", "U")
        .replace("Ñ", "N")
    )

    while "  " in text:
        text = text.replace("  ", " ")

    return text


def _interesado_es_valido_baldio(nombre: str | None) -> bool:
    normalized = _normalize_text_for_compare(nombre)

    if not normalized:
        return False

    if normalized in {"LA NACION", "NACION"}:
        return True

    if normalized == "AGENCIA NACIONAL DE TIERRAS":
        return True

    if normalized.startswith("MUNICIPIO"):
        return True

    return False

def _is_not_empty(value: object) -> bool:
    return value not in (None, "") and str(value).strip() != ""


def _only_letters_spaces(value: object) -> bool:
    if not _is_not_empty(value):
        return True
    return re.fullmatch(
        r"[A-Za-zÁÉÍÓÚáéíóúÑñÜü ]+",
        str(value).strip(),
    ) is not None


def _has_suc(value: object) -> bool:
    if not _is_not_empty(value):
        return False
    return "SUC" in _normalize_text_for_compare(value)


def _nit_es_valido(value: object) -> bool:
    if not _is_not_empty(value):
        return False

    text = str(value).strip()

    if not re.fullmatch(r"[0-9]+(-[0-9])?", text):
        return False

    numero = text.replace("-", "")

    return int(numero) > 0


def _derecho_tipo_ilicode(value: object) -> str:
    if value in (None, ""):
        return ""

    text = str(value).strip()

    mapping = {
        "14": "Posesion",
        "15": "Ocupacion",
        "16": "Dominio",
        "Posesion": "Posesion",
        "Ocupacion": "Ocupacion",
        "Dominio": "Dominio",
    }

    return mapping.get(text, text)

def _tiene_marca_persona_juridica(value: object) -> bool:
    if not _is_not_empty(value):
        return False

    text = str(value).strip().upper()

    return re.search(
        r"(?:\sLTDA|\sS\.A\.|\s&\sCIA|S\.C\.A\.|\sS\.A\.S\.|\sSAS)$",
        text,
    ) is not None

def _fuente_tipo_ilicode(value: object) -> str:
    if value in (None, ""):
        return ""

    text = str(value).strip()

    mapping = {
        "1532": "Sin_Documento",
        "1533": "Documento_Fuente.Titulo_Republicano",
        "1534": "Documento_Fuente.Acto_Administrativo",
        "1535": "Documento_Fuente.Escritura_Publica",
        "1536": "Documento_Fuente.Documento_Privado",
        "1537": "Documento_Fuente.Cedula_Real",
        "1538": "Fuente_Informativa_Intercultural.Auto",
        "1539": "Documento_Fuente.Otro_Documento_fuente",
        "1540": "Fuente_Informativa_Intercultural.Mandato_Propio_Indigena",
        "1541": "Fuente_Informativa_Intercultural.Protocolizacion_Notarial",
        "1542": "Fuente_Informativa_Intercultural.Otros_Documentos",
        "1543": "Documento_Fuente.Titulo_Colonial",
        "1544": "Documento_Fuente.Sentencia_Judicial",

        "Sin_Documento": "Sin_Documento",
        "Documento_Fuente.Titulo_Republicano": "Documento_Fuente.Titulo_Republicano",
        "Documento_Fuente.Acto_Administrativo": "Documento_Fuente.Acto_Administrativo",
        "Documento_Fuente.Escritura_Publica": "Documento_Fuente.Escritura_Publica",
        "Documento_Fuente.Documento_Privado": "Documento_Fuente.Documento_Privado",
        "Documento_Fuente.Cedula_Real": "Documento_Fuente.Cedula_Real",
        "Fuente_Informativa_Intercultural.Auto": "Fuente_Informativa_Intercultural.Auto",
        "Documento_Fuente.Otro_Documento_fuente": "Documento_Fuente.Otro_Documento_fuente",
        "Fuente_Informativa_Intercultural.Mandato_Propio_Indigena": (
            "Fuente_Informativa_Intercultural.Mandato_Propio_Indigena"
        ),
        "Fuente_Informativa_Intercultural.Protocolizacion_Notarial": (
            "Fuente_Informativa_Intercultural.Protocolizacion_Notarial"
        ),
        "Fuente_Informativa_Intercultural.Otros_Documentos": (
            "Fuente_Informativa_Intercultural.Otros_Documentos"
        ),
        "Documento_Fuente.Titulo_Colonial": "Documento_Fuente.Titulo_Colonial",
        "Documento_Fuente.Sentencia_Judicial": "Documento_Fuente.Sentencia_Judicial",
    }

    return mapping.get(text, text)

def _contains_any(value: object, words: tuple[str, ...]) -> bool:
    if not _is_not_empty(value):
        return False

    normalized = _normalize_text_for_compare(value)
    return any(word.upper() in normalized for word in words)


def _nombre_completo_interesado(row: dict[str, object], helper: JuridicoHelper) -> str:
    partes = (
        helper.get_field_value(row, ("i_primer_nombre",)),
        helper.get_field_value(row, ("i_segundo_nombre",)),
        helper.get_field_value(row, ("i_primer_apellido",)),
        helper.get_field_value(row, ("i_segundo_apellido",)),
    )

    return " ".join(str(p).strip() for p in partes if _is_not_empty(p)).strip()

def _grupo_etnico_ilicode(value: object) -> str:
    if value in (None, ""):
        return ""

    text = str(value).strip()

    mapping = {
        "8": "Etnico.Indigena",
        "9": "Etnico.Raizal",
        "10": "Ninguno",
        "11": "Etnico.Rrom",
        "12": "Etnico.Palenquero",
        "13": "Etnico.Negro_Afrocolombiano",

        # por si llega como texto
        "Etnico.Indigena": "Etnico.Indigena",
        "Etnico.Raizal": "Etnico.Raizal",
        "Ninguno": "Ninguno",
        "Etnico.Rrom": "Etnico.Rrom",
        "Etnico.Palenquero": "Etnico.Palenquero",
        "Etnico.Negro_Afrocolombiano": "Etnico.Negro_Afrocolombiano",
    }

    return mapping.get(text, text)
# ----------------------------- REGLAS -----------------------------

def _rule_2_1(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    today = date.today()
    min_valid_date = date(1900, 1, 1)
    rural_expected = date(1936, 12, 4)
    urban_expected = date(1959, 12, 31)

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = row

    for table_name, row in helper.iter_derecho_interesado_fuente():
        fecha_inicio_raw = helper.get_field_value(
            row,
            ("d_fecha_inicio_tenencia",),
        )
        fecha_inicio = _parse_date(fecha_inicio_raw)

        tipo_derecho = helper.get_field_value(
            row,
            ("d_tipo",),
        )
        tipo_derecho_str = _derecho_tipo_ilicode(tipo_derecho)

        predio_ref = helper.get_relation_value(
            row,
            ("predio",),
        )

        predio_row = predios_by_id.get(str(predio_ref)) if predio_ref else None

        numero_predial = helper.get_field_value(
            predio_row or {},
            ("Numero_Predial", "numero_predial"),
        )

        fecha_visita_raw = helper.get_field_value(
            predio_row or {},
            ("Fecha_Visita_Predial",),
        )
        fecha_visita = _parse_date(fecha_visita_raw)

        matricula = helper.get_field_value(
            predio_row or {},
            ("Matricula_Inmobiliaria",),
        )

        message = None

        if fecha_inicio is None:
            message = "La fecha de inicio de tenencia no puede ser nula."

        elif fecha_inicio < min_valid_date:
            message = "La fecha de inicio de tenencia no puede ser inferior a 1900-01-01."

        elif fecha_visita and fecha_inicio > fecha_visita:
            message = "La fecha de inicio de tenencia no puede ser mayor a la fecha de visita predial."

        elif fecha_inicio > today:
            message = "La fecha de inicio de tenencia no puede ser mayor a la fecha actual."

        elif tipo_derecho_str == "Dominio" and _matricula_es_vacia_o_cero(matricula):
            if _numero_predial_es_rural(numero_predial) and fecha_inicio != rural_expected:
                message = (
                    "Predio rural sin matrícula o con 0 y derecho Dominio "
                    "debe tener fecha 1936-12-04."
                )

            elif _numero_predial_es_urbano_sql(numero_predial) and fecha_inicio != urban_expected:
                message = (
                    "Predio urbano sin matrícula o con 0 y derecho Dominio "
                    "debe tener fecha 1959-12-31."
                )

        if message:
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.1",
                    message=message,
                    details={
                        "tabla": table_name,
                        "class": table_name,
                        "fecha_inicio_tenencia": fecha_inicio_raw,
                        "fecha_visita_predial": fecha_visita_raw,
                        "numero_predial": numero_predial,
                        "matricula": matricula,
                        "tipo_derecho": tipo_derecho,
                        "predio_ref": predio_ref,
                    },
                )
            )

    return issues

def _rule_2_2(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = row

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, ("d_tipo",))
        predio_ref = helper.get_relation_value(row, ("predio",))

        predio_row = predios_by_id.get(str(predio_ref)) if predio_ref else None
        if not predio_row:
            continue

        tipo_predio = helper.get_field_value(predio_row, ("tipo",))
        matricula = helper.get_field_value(predio_row, ("Matricula_Inmobiliaria",))
        numero_predial = helper.get_field_value(predio_row, ("Numero_Predial", "numero_predial"))

        tipo_derecho_str = _derecho_tipo_ilicode(tipo_derecho)
        tipo_predio_str = str(tipo_predio).strip() if tipo_predio else ""

        message = None

        # Caso 1: privado + dominio => matrícula obligatoria
        if (
            tipo_predio_str == "Predio.Privado.Privado"
            and tipo_derecho_str == "Dominio"
            and _matricula_es_vacia_o_cero(matricula)
        ):
            message = (
                "En un predio de tipo privado con derecho de Dominio, "
                "su matrícula inmobiliaria debe ser diferente de NULL."
            )

        # Caso 2: ocupación o posesión => matrícula debe ser NULL
        elif (
            tipo_derecho_str in ("Ocupacion", "Posesion")
            and not _matricula_es_vacia_o_cero(matricula)
        ):
            message = (
                "En un predio con derecho de Ocupacion o Posesion, "
                "su matrícula inmobiliaria debe ser igual a NULL."
            )

        if message:
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.2",
                    message=message,
                    details={
                        "tabla": table_name,
                        "tipo_predio": tipo_predio,
                        "tipo_derecho": tipo_derecho,
                        "matricula": matricula,
                        "numero_predial": numero_predial,
                        "predio_ref": predio_ref,
                    },
                )
            )

    return issues

def _rule_2_3(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = row

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, ("d_tipo",))
        predio_ref = helper.get_relation_value(row, ("predio",))

        predio_row = predios_by_id.get(str(predio_ref)) if predio_ref else None
        if not predio_row:
            continue

        tipo_predio = helper.get_field_value(predio_row, ("tipo",))
        numero_predial = helper.get_field_value(predio_row, ("Numero_Predial", "numero_predial"))
        matricula = helper.get_field_value(predio_row, ("Matricula_Inmobiliaria",))

        tipo_derecho_str = _derecho_tipo_ilicode(tipo_derecho)
        tipo_predio_str = str(tipo_predio).strip() if tipo_predio else ""

        if tipo_derecho_str == "Posesion" and tipo_predio_str != "Predio.Privado.Privado":
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.3",
                    message=(
                        "Los predios asociados a derecho de tipo Posesión "
                        "deben ser predios de tipo Privado."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_derecho": tipo_derecho,
                        "tipo_predio": tipo_predio,
                        "numero_predial": numero_predial,
                        "matricula": matricula,
                        "predio_ref": predio_ref,
                    },
                )
            )

    return issues

def _rule_2_4(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = row

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, ("d_tipo",))
        predio_ref = helper.get_relation_value(row, ("predio",))

        predio_row = predios_by_id.get(str(predio_ref)) if predio_ref else None
        if not predio_row:
            continue

        tipo_predio = helper.get_field_value(predio_row, ("tipo",))
        numero_predial = helper.get_field_value(predio_row, ("Numero_Predial", "numero_predial"))
        matricula = helper.get_field_value(predio_row, ("Matricula_Inmobiliaria",))

        tipo_derecho_str = _derecho_tipo_ilicode(tipo_derecho)
        tipo_predio_str = str(tipo_predio).strip() if tipo_predio else ""

        if tipo_predio_str == "Predio.Privado.Privado" and tipo_derecho_str == "Ocupacion":
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.4",
                    message=(
                        "Los predios con tipo de predio Privado "
                        "no deben estar asociados a derechos de Ocupación."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_derecho": tipo_derecho,
                        "tipo_predio": tipo_predio,
                        "numero_predial": numero_predial,
                        "matricula": matricula,
                        "predio_ref": predio_ref,
                    },
                )
            )

    return issues

def _rule_2_5(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = row

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, ("d_tipo",))
        predio_ref = helper.get_relation_value(row, ("predio",))

        predio_row = predios_by_id.get(str(predio_ref)) if predio_ref else None
        if not predio_row:
            continue

        tipo_predio = helper.get_field_value(predio_row, ("tipo",))
        numero_predial = helper.get_field_value(predio_row, ("Numero_Predial", "numero_predial"))
        matricula = helper.get_field_value(predio_row, ("Matricula_Inmobiliaria",))

        tipo_derecho_str = _derecho_tipo_ilicode(tipo_derecho)
        tipo_predio_str = str(tipo_predio).strip() if tipo_predio else ""

        if tipo_predio_str.startswith("Predio.Publico") and tipo_derecho_str == "Posesion":
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.5",
                    message=(
                        "Para los predios asociados a tipo de predio Público, "
                        "el tipo de derecho no puede ser Posesión."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_derecho": tipo_derecho,
                        "tipo_predio": tipo_predio,
                        "numero_predial": numero_predial,
                        "matricula": matricula,
                        "predio_ref": predio_ref,
                    },
                )
            )

    return issues

def _rule_2_6(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = row

    tipos_validos_baldio = {
        "Predio.Publico.Baldio.Baldio",
        "Predio.Publico.Baldio.Reserva_Indigena",
        "Predio.Publico.Presunto_Baldio",
    }

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, ("d_tipo",))
        predio_ref = helper.get_relation_value(row, ("predio",))
        nombre_interesado = helper.get_field_value(row, ("nombre",))

        predio_row = predios_by_id.get(str(predio_ref)) if predio_ref else None
        if not predio_row:
            continue

        tipo_predio = helper.get_field_value(predio_row, ("tipo",))
        numero_predial = helper.get_field_value(predio_row, ("Numero_Predial", "numero_predial"))
        matricula = helper.get_field_value(predio_row, ("Matricula_Inmobiliaria",))

        tipo_derecho_str = _derecho_tipo_ilicode(tipo_derecho)
        tipo_predio_str = str(tipo_predio).strip() if tipo_predio else ""

        es_baldio = tipo_predio_str in tipos_validos_baldio

        if es_baldio and tipo_derecho_str == "Dominio":
            if not _interesado_es_valido_baldio(nombre_interesado):
                issues.append(
                    helper.make_issue(
                        row,
                        rule_id="2.6",
                        message=(
                            "En los predios baldíos, baldío reserva indígena y presunto baldío "
                            "con derecho de Dominio, el interesado debe corresponder a la Nación, "
                            "al Municipio o a la Agencia Nacional de Tierras."
                        ),
                        details={
                            "tabla": table_name,
                            "tipo_derecho": tipo_derecho,
                            "tipo_predio": tipo_predio,
                            "nombre_interesado": nombre_interesado,
                            "numero_predial": numero_predial,
                            "matricula": matricula,
                            "predio_ref": predio_ref,
                        },
                    )
                )

    return issues

def _rule_2_7(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = row

    for table_name, row in helper.iter_derecho_interesado_fuente():
        predio_ref = helper.get_relation_value(row, ("predio",))
        predio_row = predios_by_id.get(str(predio_ref)) if predio_ref else None
        if not predio_row:
            continue

        tipo_predio = helper.get_field_value(predio_row, ("tipo",))
        numero_predial = helper.get_field_value(predio_row, ("Numero_Predial", "numero_predial"))

        grupo_etnico = helper.get_field_value(
            row,
            ("I_Grupo_Etnico", "i_grupo_etnico"),
        )

        tipo_predio_str = str(tipo_predio).strip() if tipo_predio else ""
        grupo_etnico_norm = _normalize_text_for_compare(grupo_etnico)

        es_privado_colectivo = tipo_predio_str == "Predio.Privado.Colectivo"

        if es_privado_colectivo:
            if not grupo_etnico_norm or grupo_etnico_norm == "NINGUNO":
                issues.append(
                    helper.make_issue(
                        row,
                        rule_id="2.7",
                        message=(
                            "Si el predio es catalogado como Privado colectivo, "
                            "el interesado debe tener diligenciado el campo "
                            "Grupo_Etnico y debe ser distinto de 'Ninguno'."
                        ),
                        details={
                            "tabla": table_name,
                            "tipo_predio": tipo_predio,
                            "grupo_etnico": grupo_etnico,
                            "numero_predial": numero_predial,
                            "predio_ref": predio_ref,
                        },
                    )
                )

    return issues

def _rule_2_8(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = row

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, ("d_tipo",))
        predio_ref = helper.get_relation_value(row, ("predio",))
        razon_social_interesado = helper.get_field_value(row, ("i_razon_social",))

        predio_row = predios_by_id.get(str(predio_ref)) if predio_ref else None
        if not predio_row:
            continue

        tipo_predio = helper.get_field_value(predio_row, ("tipo",))
        numero_predial = helper.get_field_value(predio_row, ("Numero_Predial", "numero_predial"))
        matricula = helper.get_field_value(predio_row, ("Matricula_Inmobiliaria",))

        tipo_derecho_str = _derecho_tipo_ilicode(tipo_derecho)
        tipo_predio_str = str(tipo_predio).strip() if tipo_predio else ""

        es_presunto_baldio = tipo_predio_str == "Predio.Publico.Presunto_Baldio"

        if es_presunto_baldio and tipo_derecho_str == "Ocupacion":
            if _interesado_es_valido_baldio(razon_social_interesado):
                issues.append(
                    helper.make_issue(
                        row,
                        rule_id="2.8",
                        message=(
                            "Para los predios presuntos baldíos con derecho de Ocupación, "
                            "el interesado relacionado no debe corresponder a la Nación, "
                            "al Municipio o a la Agencia Nacional de Tierras."
                        ),
                        details={
                            "tabla": table_name,
                            "tipo_derecho": tipo_derecho,
                            "tipo_predio": tipo_predio,
                            "razon_social_interesado": razon_social_interesado,
                            "numero_predial": numero_predial,
                            "matricula": matricula,
                            "predio_ref": predio_ref,
                        },
                    )
                )

    return issues

def _rule_2_9(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = row

    predios_publicos = {
        "Predio.Publico.Uso_Publico",
        "Predio.Publico.Fiscal_Patrimonial",
    }

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, ("d_tipo",))
        predio_ref = helper.get_relation_value(row, ("predio",))
        tipo_persona = helper.get_field_value(row, ("i_tipo",))

        predio_row = predios_by_id.get(str(predio_ref)) if predio_ref else None
        if not predio_row:
            continue

        tipo_predio = helper.get_field_value(predio_row, ("tipo",))
        numero_predial = helper.get_field_value(predio_row, ("Numero_Predial", "numero_predial"))
        matricula = helper.get_field_value(predio_row, ("Matricula_Inmobiliaria",))

        tipo_derecho_str = _derecho_tipo_ilicode(tipo_derecho)
        tipo_predio_str = str(tipo_predio).strip() if tipo_predio else ""
        tipo_persona_str = str(tipo_persona).strip() if tipo_persona else ""

        # ✅ Lógica correcta
        if (
            tipo_predio_str in predios_publicos
            and tipo_derecho_str == "Dominio"
            and tipo_persona_str != "Persona_Juridica"
        ):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.9",
                    message=(
                        "Los predios públicos (Fiscal-Patrimonial y Uso Público) "
                        "asociados a derechos de tipo Dominio deben tener una "
                        "persona jurídica como tipo de interesado"
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_derecho": tipo_derecho,
                        "tipo_predio": tipo_predio,
                        "tipo_persona": tipo_persona_str,
                        "numero_predial": numero_predial,
                        "matricula": matricula,
                        "predio_ref": predio_ref,
                    },
                )
            )

    return issues

def _rule_2_10(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = row

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, ("d_tipo",))
        predio_ref = helper.get_relation_value(row, ("predio",))

        predio_row = predios_by_id.get(str(predio_ref)) if predio_ref else None
        if not predio_row:
            continue

        condicion_predio = helper.get_field_value(
            predio_row,
            ("Condicion_Predio", "condicion_predio"),
        )
        tipo_predio = helper.get_field_value(predio_row, ("tipo",))
        numero_predial = helper.get_field_value(
            predio_row,
            ("Numero_Predial", "numero_predial"),
        )
        matricula = helper.get_field_value(predio_row, ("Matricula_Inmobiliaria",))

        condicion_predio_str = str(condicion_predio).strip() if condicion_predio else ""
        tipo_predio_str = str(tipo_predio).strip() if tipo_predio else ""
        tipo_derecho_str = _derecho_tipo_ilicode(tipo_derecho)

        es_via_o_uso_publico = condicion_predio_str in (
            "Via",
            "Bien_Uso_Publico",
        )

        if es_via_o_uso_publico and (
            tipo_predio_str != "Predio.Publico.Uso_Publico"
            or tipo_derecho_str != "Dominio"
        ):
            if (
                tipo_predio_str != "Predio.Publico.Uso_Publico"
                and tipo_derecho_str != "Dominio"
            ):
                message = (
                    "Para los predios que son vía o de uso público, "
                    "el tipo de predio debe ser Uso Público y el tipo de derecho "
                    "relacionado debe ser Dominio."
                )
            elif tipo_predio_str != "Predio.Publico.Uso_Publico":
                message = (
                    "Para los predios que son vía o de uso público, "
                    "el tipo de predio debe ser Uso Público."
                )
            else:
                message = (
                    "Para los predios que son vía o de uso público, "
                    "el tipo de derecho relacionado debe ser Dominio."
                )

            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.10",
                    message=message,
                    details={
                        "tabla": table_name,
                        "condicion_predio": condicion_predio,
                        "tipo_predio": tipo_predio,
                        "tipo_derecho": tipo_derecho,
                        "numero_predial": numero_predial,
                        "matricula": matricula,
                        "predio_ref": predio_ref,
                    },
                )
            )

    return issues

def _rule_2_11(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    # Indexar predios
    for _, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = row

    for table_name, row in helper.iter_derecho_interesado_fuente():

        fecha_inicio_raw = helper.get_field_value(
            row,
            ("d_fecha_inicio_tenencia",),
        )
        fecha_inicio = _parse_date(fecha_inicio_raw)

        fecha_fuente_raw = helper.get_field_value(
            row,
            ("FA_Fecha_Documento_Fuente", "fa_fecha_documento_fuente"),
        )
        fecha_fuente = _parse_date(fecha_fuente_raw)

        predio_ref = helper.get_relation_value(row, ("predio",))

        predio_row = predios_by_id.get(str(predio_ref)) if predio_ref else None
        if not predio_row:
            continue

        matricula = helper.get_field_value(
            predio_row,
            ("Matricula_Inmobiliaria",),
        )

        numero_predial = helper.get_field_value(
            predio_row,
            ("Numero_Predial", "numero_predial"),
        )

        # Solo aplica si hay matrícula
        if not _matricula_es_vacia_o_cero(matricula):
            if fecha_inicio and fecha_fuente and fecha_inicio < fecha_fuente:
                issues.append(
                    helper.make_issue(
                        row,
                        rule_id="2.11",
                        message=(
                            "Para los predios con matrícula inmobiliaria, "
                            "la fecha de inicio de tenencia debe ser mayor o igual "
                            "a la fecha del documento fuente."
                        ),
                        details={
                            "tabla": table_name,
                            "fecha_inicio_tenencia": fecha_inicio_raw,
                            "fecha_documento_fuente": fecha_fuente_raw,
                            "matricula": matricula,
                            "numero_predial": numero_predial,
                            "predio_ref": predio_ref,
                        },
                    )
                )

    return issues

def _rule_2_12(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = row

    for table_name, row in helper.iter_derecho_interesado_fuente():
        predio_ref = helper.get_relation_value(row, ("predio",))
        predio_row = predios_by_id.get(str(predio_ref)) if predio_ref else None
        if not predio_row:
            continue

        matricula = helper.get_field_value(predio_row, ("matricula_inmobiliaria",))
        fecha_visita_raw = helper.get_field_value(predio_row, ("fecha_visita_predial",))
        fecha_visita = _parse_date(fecha_visita_raw)

        fecha_fuente_raw = helper.get_field_value(row, ("fa_fecha_documento_fuente",))
        fecha_fuente = _parse_date(fecha_fuente_raw)

        tipo_fuente = helper.get_field_value(row, ("fa_tipo",))
        numero_fuente = helper.get_field_value(row, ("fa_numero_fuente",))
        ente_emisor = helper.get_field_value(row, ("fa_ente_emisor",))

        message = None

        if not _matricula_es_vacia_o_cero(matricula):
            if fecha_fuente is None:
                message = "La fecha de documento fuente no puede ser NULL."
            elif not _is_not_empty(tipo_fuente):
                message = "El tipo de fuente administrativa no puede ser NULL."
            elif not _is_not_empty(numero_fuente):
                message = "El número de fuente administrativa no puede ser NULL."
            elif not _is_not_empty(ente_emisor):
                message = "El ente emisor de fuente administrativa no puede ser NULL."
            elif fecha_visita and fecha_fuente > fecha_visita:
                message = "La fecha de documento fuente no puede ser posterior a la fecha de levantamiento."

        if message:
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.12",
                    message=message,
                    details={
                        "tabla": table_name,
                        "matricula": matricula,
                        "fecha_documento_fuente": fecha_fuente_raw,
                        "fecha_levantamiento": fecha_visita_raw,
                        "tipo_fuente": tipo_fuente,
                        "numero_fuente": numero_fuente,
                        "ente_emisor": ente_emisor,
                        "predio_ref": predio_ref,
                    },
                )
            )

    return issues

def _rule_2_13(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, ("i_tipo",))
        tipo_documento = helper.get_field_value(row, ("i_tipo_documento",))

        if str(tipo).strip() == "Persona_Juridica" and str(tipo_documento).strip() not in ("NIT", "Secuencial"):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.13",
                    message=(
                        "Un interesado de tipo Persona_Juridica solamente puede tener "
                        "tipo de documento NIT o Secuencial."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo": tipo,
                        "tipo_documento": tipo_documento,
                    },
                )
            )

    return issues

def _rule_2_14(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    documentos_validos = {
        "Cedula_Ciudadania",
        "Pasaporte",
        "Cedula_Extranjeria",
        "Tarjeta_Identidad",
        "Registro_Civil",
        "Secuencial",
    }

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, ("i_tipo",))
        tipo_documento = helper.get_field_value(row, ("i_tipo_documento",))

        if str(tipo).strip() == "Persona_Natural" and str(tipo_documento).strip() not in documentos_validos:
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.14",
                    message=(
                        "Un interesado de tipo Persona_Natural solamente puede tener tipo de documento "
                        "Cédula de Ciudadanía, Pasaporte, Cédula de Extranjería, Tarjeta de Identidad, "
                        "Registro Civil o Secuencial."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo": tipo,
                        "tipo_documento": tipo_documento,
                    },
                )
            )

    return issues

def _rule_2_15(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    documentos_obligan_numero = {
        "Cedula_Ciudadania",
        "Cedula_Extranjeria",
        "Tarjeta_Identidad",
        "Registro_Civil",
    }

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_documento = helper.get_field_value(row, ("i_tipo_documento",))
        documento = helper.get_field_value(row, ("i_documento_identidad",))

        if str(tipo_documento).strip() in documentos_obligan_numero:
            if not _is_not_empty(documento) or str(documento).strip() == "0":
                issues.append(
                    helper.make_issue(
                        row,
                        rule_id="2.15",
                        message=(
                            "El número de documento de identidad debe ser diferente "
                            "de cero o vacío."
                        ),
                        details={
                            "tabla": table_name,
                            "tipo_documento": tipo_documento,
                            "documento_identidad": documento,
                        },
                    )
                )

    return issues

def _rule_2_16(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_documento = helper.get_field_value(row, ("i_tipo_documento",))
        documento = helper.get_field_value(row, ("i_documento_identidad",))

        if str(tipo_documento).strip() == "NIT" and not _nit_es_valido(documento):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.16",
                    message=(
                        "El NIT debe ser mayor a cero, sin letras ni caracteres especiales "
                        "excepto guion. Antes del guion debe ser numérico y después del guion "
                        "debe existir un único dígito entre 0 y 9."
                    ),
                    details={
                        "tabla": table_name,
                        "tipo_documento": tipo_documento,
                        "documento_identidad": documento,
                    },
                )
            )

    return issues

def _rule_2_17(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    campos_nombre = (
        ("i_primer_nombre", "primer nombre"),
        ("i_segundo_nombre", "segundo nombre"),
        ("i_primer_apellido", "primer apellido"),
        ("i_segundo_apellido", "segundo apellido"),
    )

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, ("i_tipo",))
        razon_social = helper.get_field_value(row, ("i_razon_social",))

        if str(tipo).strip() != "Persona_Natural":
            continue

        if _is_not_empty(razon_social):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.17",
                    message="Para Persona_Natural, la razón social debe ser NULL.",
                    details={
                        "tabla": table_name,
                        "razon_social": razon_social,
                    },
                )
            )
            continue

        for campo, etiqueta in campos_nombre:
            valor = helper.get_field_value(row, (campo,))
            if _is_not_empty(valor) and not _only_letters_spaces(valor):
                issues.append(
                    helper.make_issue(
                        row,
                        rule_id="2.17",
                        message=f"El {etiqueta} debe estar compuesto exclusivamente por caracteres alfabéticos.",
                        details={
                            "tabla": table_name,
                            campo: valor,
                        },
                    )
                )
                break

    return issues

def _rule_2_18(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    campos_nombre = (
        ("i_primer_nombre", "primer nombre"),
        ("i_segundo_nombre", "segundo nombre"),
        ("i_primer_apellido", "primer apellido"),
        ("i_segundo_apellido", "segundo apellido"),
    )

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, ("i_tipo",))

        if str(tipo).strip() != "Persona_Juridica":
            continue

        for campo, etiqueta in campos_nombre:
            valor = helper.get_field_value(row, (campo,))
            if _is_not_empty(valor):
                issues.append(
                    helper.make_issue(
                        row,
                        rule_id="2.18",
                        message=(
                            f"En el caso de un interesado de tipo Persona_Juridica, "
                            f"el valor del {etiqueta} debe ser NULL."
                        ),
                        details={
                            "tabla": table_name,
                            campo: valor,
                        },
                    )
                )
                break

    return issues

def _rule_2_19(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    campos_nombre = (
        ("i_primer_nombre", "primer nombre"),
        ("i_segundo_nombre", "segundo nombre"),
        ("i_primer_apellido", "primer apellido"),
        ("i_segundo_apellido", "segundo apellido"),
    )

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, ("i_tipo",))

        if str(tipo).strip() != "Persona_Natural":
            continue

        for campo, etiqueta in campos_nombre:
            valor = helper.get_field_value(row, (campo,))
            if _is_not_empty(valor) and (not _only_letters_spaces(valor) or _has_suc(valor)):
                issues.append(
                    helper.make_issue(
                        row,
                        rule_id="2.19",
                        message=(
                            f"El {etiqueta} debe consistir únicamente en caracteres alfabéticos "
                            f"y no puede contener la sigla SUC."
                        ),
                        details={
                            "tabla": table_name,
                            campo: valor,
                        },
                    )
                )
                break

    return issues

def _rule_2_20(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    campos_nombre = (
        ("i_primer_nombre", "primer nombre"),
        ("i_segundo_nombre", "segundo nombre"),
        ("i_primer_apellido", "primer apellido"),
        ("i_segundo_apellido", "segundo apellido"),
    )

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, ("i_tipo",))
        razon_social = helper.get_field_value(row, ("i_razon_social",))

        if str(tipo).strip() != "Persona_Juridica":
            continue

        message = None
        details = {
            "tabla": table_name,
            "razon_social": razon_social,
        }

        for campo, etiqueta in campos_nombre:
            valor = helper.get_field_value(row, (campo,))
            if _is_not_empty(valor):
                message = (
                    f"En el caso de un interesado de tipo Persona_Juridica, "
                    f"el valor del {etiqueta} debe ser NULL."
                )
                details[campo] = valor
                break

        if message is None and not _is_not_empty(razon_social):
            message = (
                "Para los interesados asociados a Persona_Juridica, "
                "se debe diligenciar solamente el campo de razón social."
            )

        if message:
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.20",
                    message=message,
                    details=details,
                )
            )

    return issues

def _rule_2_21(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, ("i_tipo",))
        sexo = helper.get_field_value(row, ("i_sexo",))

        tipo_str = str(tipo).strip() if tipo else ""

        message = None

        if tipo_str == "Persona_Juridica" and _is_not_empty(sexo):
            message = (
                "En el caso de un interesado de tipo Persona_Juridica, "
                "el valor del campo sexo debe ser NULL."
            )

        elif tipo_str == "Persona_Natural" and not _is_not_empty(sexo):
            message = (
                "En el caso de un interesado de tipo Persona_Natural, "
                "el valor del campo sexo debe ser diferente de NULL."
            )

        if message:
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.21",
                    message=message,
                    details={
                        "tabla": table_name,
                        "tipo": tipo,
                        "sexo": sexo,
                    },
                )
            )

    return issues

def _rule_2_22(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    campos_nombre = (
        ("i_primer_nombre", "primer nombre"),
        ("i_segundo_nombre", "segundo nombre"),
        ("i_primer_apellido", "primer apellido"),
        ("i_segundo_apellido", "segundo apellido"),
    )

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, ("i_tipo",))

        if str(tipo).strip() != "Persona_Natural":
            continue

        for campo, etiqueta in campos_nombre:
            valor = helper.get_field_value(row, (campo,))

            if _tiene_marca_persona_juridica(valor):
                issues.append(
                    helper.make_issue(
                        row,
                        rule_id="2.22",
                        message=(
                            f"El valor del {etiqueta} asocia información "
                            f"de personas jurídicas."
                        ),
                        details={
                            "tabla": table_name,
                            campo: valor,
                            "tipo": tipo,
                        },
                    )
                )
                break

    return issues

#def _rule_2_23(dataset: DatasetReader) -> list[RuleIssue]:
    #sin definir aun
    return []

#def _rule_2_24(dataset: DatasetReader) -> list[RuleIssue]:
    #sin definir aun
    return []

#def _rule_2_25(dataset: DatasetReader) -> list[RuleIssue]:
    #sin definir aun
    return []

#def _rule_2_26(dataset: DatasetReader) -> list[RuleIssue]:
    #sin definir aun
    return []

def _rule_2_27(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_fuente = helper.get_field_value(row, ("fa_tipo",))
        tipo_fuente_str = _fuente_tipo_ilicode(tipo_fuente)

        ente_emisor = helper.get_field_value(row, ("fa_ente_emisor",))
        numero_fuente = helper.get_field_value(row, ("fa_numero_fuente",))
        fecha_fuente = helper.get_field_value(row, ("fa_fecha_documento_fuente",))
        observacion = helper.get_field_value(row, ("fa_observacion",))

        message = None

        if tipo_fuente_str in {
            "Documento_Fuente.Acto_Administrativo",
            "Documento_Fuente.Sentencia_Judicial",
            "Documento_Fuente.Escritura_Publica",
        }:
            if not _is_not_empty(ente_emisor) or not _is_not_empty(numero_fuente) or not _is_not_empty(fecha_fuente):
                message = (
                    "El registro presenta inconsistencias entre el ente emisor, "
                    "número de fuente y fecha del documento en relación con el tipo de fuente administrativa."
                )

        elif tipo_fuente_str in {
            "Documento_Fuente.Titulo_Colonial",
            "Documento_Fuente.Titulo_Republicano",
            "Documento_Fuente.Cedula_Real",
        }:
            if not _is_not_empty(ente_emisor) or _is_not_empty(numero_fuente) or not _is_not_empty(fecha_fuente):
                message = (
                    "El registro presenta inconsistencias entre el ente emisor, "
                    "número de fuente y fecha del documento en relación con el tipo de fuente administrativa."
                )

        elif tipo_fuente_str == "Documento_Fuente.Documento_Privado":
            if _is_not_empty(ente_emisor) or _is_not_empty(numero_fuente) or not _is_not_empty(fecha_fuente) or not _is_not_empty(observacion):
                message = (
                    "El registro presenta inconsistencias entre el ente emisor, "
                    "número de fuente, fecha del documento y observación en relación con el tipo de fuente administrativa."
                )

        elif tipo_fuente_str == "Sin_Documento":
            if _is_not_empty(ente_emisor) or _is_not_empty(numero_fuente) or _is_not_empty(fecha_fuente):
                message = (
                    "El registro presenta inconsistencias entre el ente emisor, "
                    "número de fuente y fecha del documento en relación con el tipo de fuente administrativa."
                )

        elif tipo_fuente_str == "Fuente_Informativa_Intercultural.Mandato_Propio_Indigena":
            if _is_not_empty(ente_emisor) or _is_not_empty(numero_fuente) or not _is_not_empty(fecha_fuente) or not _is_not_empty(observacion):
                message = (
                    "El registro presenta inconsistencias entre el ente emisor, "
                    "número de fuente, fecha del documento y observación en relación con el tipo de fuente administrativa."
                )

        if message:
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.27",
                    message=message,
                    details={
                        "tabla": table_name,
                        "tipo_fuente": tipo_fuente,
                        "tipo_fuente_ilicode": tipo_fuente_str,
                        "ente_emisor": ente_emisor,
                        "numero_fuente": numero_fuente,
                        "fecha_documento_fuente": fecha_fuente,
                        "observacion": observacion,
                    },
                )
            )

    return issues

def _rule_2_28(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_fuente = helper.get_field_value(row, ("fa_tipo",))
        tipo_fuente_str = _fuente_tipo_ilicode(tipo_fuente)

        ente_emisor = helper.get_field_value(row, ("fa_ente_emisor",))

        message = None

        if tipo_fuente_str == "Documento_Fuente.Escritura_Publica":
            if not _contains_any(ente_emisor, ("NOTAR",)):
                message = "El ente emisor de una Escritura Pública debe corresponder a una notaría."

        elif tipo_fuente_str == "Documento_Fuente.Sentencia_Judicial":
            if not _contains_any(ente_emisor, ("JUZGADO",)):
                message = "El ente emisor de una Sentencia Judicial debe corresponder a un juzgado."

        elif tipo_fuente_str == "Documento_Fuente.Acto_Administrativo":
            if not _contains_any(
                ente_emisor,
                ("ALCALD", "ANT", "INCODER", "INCORA", "MINISTERIO"),
            ):
                message = (
                    "El ente emisor de un Acto Administrativo debe corresponder "
                    "a alcaldía, ANT, INCODER, INCORA o ministerio."
                )

        if message:
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.28",
                    message=message,
                    details={
                        "tabla": table_name,
                        "tipo_fuente": tipo_fuente,
                        "tipo_fuente_ilicode": tipo_fuente_str,
                        "ente_emisor": ente_emisor,
                    },
                )
            )

    return issues

def _rule_2_29(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_con_interesado: set[str] = set()

    for _, row in helper.iter_derecho_interesado_fuente():
        predio_ref = helper.get_relation_value(row, ("predio",))
        tipo_interesado = helper.get_field_value(row, ("i_tipo",))
        documento = helper.get_field_value(row, ("i_documento_identidad",))
        razon_social = helper.get_field_value(row, ("i_razon_social",))
        nombre_completo = _nombre_completo_interesado(row, helper)

        if predio_ref and (
            _is_not_empty(tipo_interesado)
            or _is_not_empty(documento)
            or _is_not_empty(razon_social)
            or _is_not_empty(nombre_completo)
        ):
            predios_con_interesado.add(str(predio_ref))

    for table_name, row in helper.iter_predios():
        predio_id = helper.get_field_value(row, ("TID", "t_id", "id"))
        numero_predial = helper.get_field_value(row, ("numero_predial", "Numero_Predial"))

        if predio_id and str(predio_id) not in predios_con_interesado:
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.29",
                    message=(
                        "Todo predio debe tener asociado al menos un derecho "
                        "y un interesado relacionado."
                    ),
                    details={
                        "tabla": table_name,
                        "predio_id": predio_id,
                        "numero_predial": numero_predial,
                    },
                )
            )

    return issues

def _rule_2_30(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    documentos_por_nombre: dict[str, set[str]] = {}
    filas_por_nombre: dict[str, list[tuple[str, dict[str, object]]]] = {}

    for table_name, row in helper.iter_derecho_interesado_fuente():
        documento = helper.get_field_value(row, ("i_documento_identidad",))
        razon_social = helper.get_field_value(row, ("i_razon_social",))
        nombre_completo = _nombre_completo_interesado(row, helper)

        if _is_not_empty(razon_social):
            clave = f"J:{_normalize_text_for_compare(razon_social)}"
        elif _is_not_empty(nombre_completo):
            clave = f"N:{_normalize_text_for_compare(nombre_completo)}"
        else:
            continue

        if not _is_not_empty(documento):
            continue

        documentos_por_nombre.setdefault(clave, set()).add(str(documento).strip())
        filas_por_nombre.setdefault(clave, []).append((table_name, row))

    for clave, documentos in documentos_por_nombre.items():
        if len(documentos) <= 1:
            continue

        for table_name, row in filas_por_nombre.get(clave, []):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.30",
                    message=(
                        "Hay un propietario con el mismo nombre o razón social "
                        "pero con diferente número de identificación."
                    ),
                    details={
                        "tabla": table_name,
                        "nombre_completo": _nombre_completo_interesado(row, helper),
                        "razon_social": helper.get_field_value(row, ("i_razon_social",)),
                        "documento_identidad": helper.get_field_value(row, ("i_documento_identidad",)),
                    },
                )
            )

    return issues

#def _rule_2_31(dataset: DatasetReader) -> list[RuleIssue]:
    #sin definir aun
    return []

def _rule_2_32(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_derecho_interesado_fuente():
        grupo_etnico = helper.get_field_value(row, ("i_grupo_etnico",))
        grupo_etnico_str = _grupo_etnico_ilicode(grupo_etnico)

        nombre_pueblo = helper.get_field_value(row, ("ie_nombre_pueblo",))

        if grupo_etnico_str == "Etnico.Indigena" and not _is_not_empty(nombre_pueblo):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.32",
                    message=(
                        "Se ha identificado que una persona perteneciente a un grupo "
                        "étnico indígena no ha indicado el nombre del pueblo al que pertenece."
                    ),
                    details={
                        "tabla": table_name,
                        "grupo_etnico": grupo_etnico,
                        "grupo_etnico_ilicode": grupo_etnico_str,
                        "nombre_pueblo": nombre_pueblo,
                    },
                )
            )

    return issues


RULE_FUNCTIONS = {
    "2.1": _rule_2_1,
    "2.2": _rule_2_2,
    "2.3": _rule_2_3,
    "2.4": _rule_2_4,
    "2.5": _rule_2_5,
    "2.6": _rule_2_6,
    "2.7": _rule_2_7,
    "2.8": _rule_2_8,
    "2.9": _rule_2_9,
    "2.10": _rule_2_10,
    "2.11": _rule_2_11,
    "2.12": _rule_2_12,
    "2.13": _rule_2_13,
    "2.14": _rule_2_14,
    "2.15": _rule_2_15,
    "2.16": _rule_2_16,
    "2.17": _rule_2_17,
    "2.18": _rule_2_18,
    "2.19": _rule_2_19,
    "2.20": _rule_2_20,
    "2.21": _rule_2_21,
    "2.22": _rule_2_22,
    "2.27": _rule_2_27,
    "2.28": _rule_2_28,
    "2.29": _rule_2_29,
    "2.30": _rule_2_30,
    "2.32": _rule_2_32,
}
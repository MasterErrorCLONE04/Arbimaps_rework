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


def _is_empty_qgis(value: object) -> bool:
    if value is None:
        return True

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            if float(value) == 0:
                return True
        except Exception:
            pass

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


class JuridicoHelper:
    """Utilidades compartidas para reglas jurídicas."""

    IDENTIFIER_FIELDS = (
        "t_ili_tid",
        "T_Ili_Tid",
        "T_ILI_TID",
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
            if not _is_empty_qgis(value):
                return str(value).strip()

        normalized_targets = {self._normalize_key(field) for field in self.IDENTIFIER_FIELDS}
        for key, candidate in row.items():
            if self._normalize_key(str(key)) in normalized_targets and not _is_empty_qgis(candidate):
                return str(candidate).strip()

        return None

    def get_field_value(self, row: dict[str, object], candidates: tuple[str, ...]) -> str | None:
        match = self._extract_field(row, candidates, require_value=False)
        if not match:
            return None
        field_name, raw_value = match
        value = _normalizar_valor_dominio(field_name, raw_value)
        if _is_empty_qgis(value):
            return None
        return str(value).strip()

    def get_relation_value(self, row: dict[str, object], candidates: tuple[str, ...]) -> str | None:
        value = self.get_field_value(row, candidates)
        if value is not None:
            return value
        normalized_candidates = {self._normalize_key(candidate) for candidate in candidates}
        if "predio" in normalized_candidates:
            return self.get_field_value(row, PREDIO_RELATION_FIELDS)
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
        return _is_empty_qgis(value)

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


TIPO_INTERESADO_FIELDS = (
    "i_tipo", "I_Tipo", "tipo_persona", "Tipo_persona", "Tipo de persona",
    "tipo_interesado", "Tipo_interesado", "Tipo de interesado",
    "i_tipo_interesado", "interesado_tipo", "tipo_persona_interesado",
)
SEXO_FIELDS = (
    "i_sexo", "I_Sexo", "sexo", "Sexo", "sexo_interesado", "interesado_sexo",
    "género", "genero", "i_genero", "I_Genero", "Género", "Genero",
)
TIPO_FUENTE_FIELDS = (
    "fa_tipo", "FA_Tipo", "tipo_fuente_administrativa",
    "Tipo_fuente_administrativa", "Tipo de fuente administrativa",
    "fuente_tipo", "tipo_fuente", "Tipo fuente", "tipo_documento_fuente",
)
ENTE_EMISOR_FIELDS = (
    "fa_ente_emisor", "FA_Ente_Emisor", "ente_emisor", "Ente_emisor",
    "Ente emisor", "ente_emisor_fuente", "fuente_ente_emisor",
)
NUMERO_FUENTE_FIELDS = (
    "fa_numero_fuente", "FA_Numero_Fuente", "numero_fuente", "Numero_fuente",
    "Número de fuente", "Numero de fuente", "numero_documento_fuente",
)
FECHA_FUENTE_FIELDS = (
    "fa_fecha_documento_fuente", "FA_Fecha_Documento_Fuente",
    "fecha_documento_fuente", "Fecha_documento_fuente", "Fecha documento fuente",
    "fecha_fuente", "Fecha_fuente", "fecha_documento",
)
OBSERVACION_FUENTE_FIELDS = (
    "fa_observacion", "FA_Observacion", "observacion_fuente_administrativa",
    "Observacion_fuente_administrativa", "Observación de fuente administrativa",
    "Observacion de fuente administrativa", "observacion_fuente", "Observacion_fuente",
)
FECHA_INICIO_TENENCIA_FIELDS = (
    "d_fecha_inicio_tenencia", "D_Fecha_Inicio_Tenencia",
    "fecha_inicio_tenencia", "Fecha_Inicio_Tenencia", "Fecha inicio tenencia",
)
TIPO_DERECHO_FIELDS = (
    "d_tipo", "D_Tipo", "tipo_derecho", "Tipo_Derecho", "Tipo derecho",
)
PREDIO_RELATION_FIELDS = (
    "predio", "Predio", "d_predio", "D_Predio", "id_predio", "ID_PREDIO",
    "predio_id", "Predio_ID", "id_operacion", "Id_Operacion", "ID_OPERACION",
    "TID", "t_id", "id",
)
PREDIO_IDENTIFIER_FIELDS = JuridicoHelper.IDENTIFIER_FIELDS + (
    "predio", "Predio",
)
NUMERO_PREDIAL_FIELDS = (
    "Numero_Predial", "numero_predial", "Numero_Predial_Nacional",
    "numero_predial_nacional", "Numero predial", "Numero predial nacional",
)
FECHA_VISITA_PREDIAL_FIELDS = (
    "Fecha_Visita_Predial", "fecha_visita_predial", "Fecha visita predial",
    "fecha_levantamiento", "Fecha_Levantamiento", "Fecha levantamiento",
)
MATRICULA_INMOBILIARIA_FIELDS = (
    "Matricula_Inmobiliaria", "matricula_inmobiliaria", "Matricula inmobiliaria",
    "matricula", "Matricula",
)
DOCUMENTO_IDENTIDAD_FIELDS = (
    "i_documento_identidad", "I_Documento_Identidad", "documento_identidad",
    "Documento_identidad", "Documento de identidad", "numero_documento",
    "Número documento", "Numero documento", "identificacion", "identificación",
)
RAZON_SOCIAL_FIELDS = (
    "i_razon_social", "I_Razon_Social", "razon_social", "Razon_social",
    "Razón social", "Razon social", "razon_social_interesado",
)
PRIMER_NOMBRE_FIELDS = ("i_primer_nombre", "I_Primer_Nombre", "primer_nombre", "Primer_nombre", "Primer nombre")
SEGUNDO_NOMBRE_FIELDS = ("i_segundo_nombre", "I_Segundo_Nombre", "segundo_nombre", "Segundo_nombre", "Segundo nombre")
PRIMER_APELLIDO_FIELDS = ("i_primer_apellido", "I_Primer_Apellido", "primer_apellido", "Primer_apellido", "Primer apellido")
SEGUNDO_APELLIDO_FIELDS = ("i_segundo_apellido", "I_Segundo_Apellido", "segundo_apellido", "Segundo_apellido", "Segundo apellido")


_DOMINIO_TIPO_INTERESADO = {
    "0": "Persona_Natural", "0.0": "Persona_Natural",
    "1": "Persona_Juridica", "1.0": "Persona_Juridica",
    "2": "Persona_Natural", "2.0": "Persona_Natural",
    "153": "Persona_Juridica", "154": "Persona_Natural",
    "960": "Persona_Juridica", "961": "Persona_Natural",
    "Persona_Juridica": "Persona_Juridica", "Persona_Natural": "Persona_Natural",
}

_DOMINIO_DERECHO_TIPO = {
    "1": "Posesion", "1.0": "Posesion",
    "2": "Ocupacion", "2.0": "Ocupacion",
    "3": "Dominio", "3.0": "Dominio",
    "14": "Posesion", "15": "Ocupacion", "16": "Dominio",
    "63": "Posesion", "64": "Ocupacion", "65": "Dominio",
    "Posesion": "Posesion", "Ocupacion": "Ocupacion", "Dominio": "Dominio",
}

_DOMINIO_DOCUMENTO_TIPO = {
    "1": "Pasaporte", "1.0": "Pasaporte",
    "2": "Tarjeta_Identidad", "2.0": "Tarjeta_Identidad",
    "3": "Cedula_Extranjeria", "3.0": "Cedula_Extranjeria",
    "4": "Cedula_Ciudadania", "4.0": "Cedula_Ciudadania",
    "5": "NIT", "5.0": "NIT",
    "6": "Registro_Civil", "6.0": "Registro_Civil",
    "7": "Secuencial", "7.0": "Secuencial",
    "292": "Cedula_Ciudadania",
    "293": "Pasaporte",
    "294": "Cedula_Extranjeria",
    "295": "Tarjeta_Identidad",
    "296": "NIT",
    "297": "Registro_Civil",
    "298": "Secuencial",
    "1013": "Pasaporte",
    "1014": "Tarjeta_Identidad",
    "1015": "Cedula_Extranjeria",
    "1016": "Cedula_Ciudadania",
    "1017": "NIT",
    "1018": "Registro_Civil",
    "1019": "Secuencial",
    "Pasaporte": "Pasaporte",
    "Tarjeta_Identidad": "Tarjeta_Identidad",
    "Cedula_Extranjeria": "Cedula_Extranjeria",
    "Cedula_Ciudadania": "Cedula_Ciudadania",
    "NIT": "NIT",
    "Registro_Civil": "Registro_Civil",
    "Secuencial": "Secuencial",
}

_DOMINIO_SEXO_TIPO = {
    "1": "Masculino", "1.0": "Masculino",
    "2": "Sin_Determinar", "2.0": "Sin_Determinar",
    "3": "Femenino", "3.0": "Femenino",
    "Masculino": "Masculino",
    "Femenino": "Femenino",
    "Sin_Determinar": "Sin_Determinar",
}

_DOMINIO_FUENTE_TIPO = {
    "1": "Sin_Documento", "1.0": "Sin_Documento",
    "2": "Documento_Fuente.Titulo_Republicano", "2.0": "Documento_Fuente.Titulo_Republicano",
    "3": "Documento_Fuente.Acto_Administrativo", "3.0": "Documento_Fuente.Acto_Administrativo",
    "4": "Documento_Fuente.Escritura_Publica", "4.0": "Documento_Fuente.Escritura_Publica",
    "5": "Documento_Fuente.Documento_Privado", "5.0": "Documento_Fuente.Documento_Privado",
    "6": "Documento_Fuente.Cedula_Real", "6.0": "Documento_Fuente.Cedula_Real",
    "7": "Fuente_Informativa_Intercultural.Auto", "7.0": "Fuente_Informativa_Intercultural.Auto",
    "8": "Documento_Fuente.Otro_Documento_fuente", "8.0": "Documento_Fuente.Otro_Documento_fuente",
    "9": "Fuente_Informativa_Intercultural.Mandato_Propio_Indigena",
    "9.0": "Fuente_Informativa_Intercultural.Mandato_Propio_Indigena",
    "10": "Fuente_Informativa_Intercultural.Protocolizacion_Notarial",
    "10.0": "Fuente_Informativa_Intercultural.Protocolizacion_Notarial",
    "11": "Fuente_Informativa_Intercultural.Otros_Documentos",
    "11.0": "Fuente_Informativa_Intercultural.Otros_Documentos",
    "12": "Documento_Fuente.Titulo_Colonial", "12.0": "Documento_Fuente.Titulo_Colonial",
    "13": "Documento_Fuente.Sentencia_Judicial", "13.0": "Documento_Fuente.Sentencia_Judicial",
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

_DOMINIO_GRUPO_ETNICO = {
    "1": "Etnico.Indigena", "1.0": "Etnico.Indigena",
    "2": "Etnico.Raizal", "2.0": "Etnico.Raizal",
    "3": "Ninguno", "3.0": "Ninguno",
    "4": "Etnico.Rrom", "4.0": "Etnico.Rrom",
    "5": "Etnico.Palenquero", "5.0": "Etnico.Palenquero",
    "6": "Etnico.Negro_Afrocolombiano", "6.0": "Etnico.Negro_Afrocolombiano",
    "8": "Etnico.Indigena",
    "9": "Etnico.Raizal",
    "10": "Ninguno",
    "11": "Etnico.Rrom",
    "12": "Etnico.Palenquero",
    "13": "Etnico.Negro_Afrocolombiano",
    "Etnico.Indigena": "Etnico.Indigena",
    "Etnico.Raizal": "Etnico.Raizal",
    "Ninguno": "Ninguno",
    "Etnico.Rrom": "Etnico.Rrom",
    "Etnico.Palenquero": "Etnico.Palenquero",
    "Etnico.Negro_Afrocolombiano": "Etnico.Negro_Afrocolombiano",
}

_DOMINIO_PREDIO_TIPO = {
    "1": "Predio.Publico.Baldio.Baldio", "1.0": "Predio.Publico.Baldio.Baldio",
    "2": "Predio.Privado.Colectivo", "2.0": "Predio.Privado.Colectivo",
    "3": "Predio.Publico.Presunto_Baldio", "3.0": "Predio.Publico.Presunto_Baldio",
    "4": "Predio.Publico.Fiscal_Patrimonial", "4.0": "Predio.Publico.Fiscal_Patrimonial",
    "5": "Predio.Publico.Baldio.Reserva_Indigena", "5.0": "Predio.Publico.Baldio.Reserva_Indigena",
    "6": "Predio.Publico.Uso_Publico", "6.0": "Predio.Publico.Uso_Publico",
    "7": "Predio.Privado.Privado", "7.0": "Predio.Privado.Privado",
    "312": "Predio.Privado.Colectivo",
    "314": "Predio.Publico.Fiscal_Patrimonial",
    "316": "Predio.Publico.Uso_Publico",
    "Predio.Publico.Baldio.Baldio": "Predio.Publico.Baldio.Baldio",
    "Predio.Privado.Colectivo": "Predio.Privado.Colectivo",
    "Predio.Publico.Presunto_Baldio": "Predio.Publico.Presunto_Baldio",
    "Predio.Publico.Fiscal_Patrimonial": "Predio.Publico.Fiscal_Patrimonial",
    "Predio.Publico.Baldio.Reserva_Indigena": "Predio.Publico.Baldio.Reserva_Indigena",
    "Predio.Publico.Uso_Publico": "Predio.Publico.Uso_Publico",
    "Predio.Privado.Privado": "Predio.Privado.Privado",
}

_DOMINIO_CONDICION_PREDIO = {
    "1": "PH.Matriz", "1.0": "PH.Matriz",
    "2": "Condominio.Unidad_Predial", "2.0": "Condominio.Unidad_Predial",
    "3": "Bien_Uso_Publico", "3.0": "Bien_Uso_Publico",
    "4": "PH.Unidad_Predial", "4.0": "PH.Unidad_Predial",
    "5": "Condominio.Matriz", "5.0": "Condominio.Matriz",
    "6": "Parque_Cementerio.Matriz", "6.0": "Parque_Cementerio.Matriz",
    "7": "NPH", "7.0": "NPH",
    "8": "Informal", "8.0": "Informal",
    "9": "Parque_Cementerio.Unidad_Predial", "9.0": "Parque_Cementerio.Unidad_Predial",
    "10": "Via", "10.0": "Via",
    "206": "Via",
    "209": "Bien_Uso_Publico",
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

_DOMINIOS_POR_CAMPO = {
    "dtipo": _DOMINIO_DERECHO_TIPO,
    "tipoderecho": _DOMINIO_DERECHO_TIPO,
    "itipo": _DOMINIO_TIPO_INTERESADO,
    "tipopersona": _DOMINIO_TIPO_INTERESADO,
    "tipointeresado": _DOMINIO_TIPO_INTERESADO,
    "itipointeresado": _DOMINIO_TIPO_INTERESADO,
    "interesadotipo": _DOMINIO_TIPO_INTERESADO,
    "tipopersonainteresado": _DOMINIO_TIPO_INTERESADO,
    "fatipo": _DOMINIO_FUENTE_TIPO,
    "tipofuenteadministrativa": _DOMINIO_FUENTE_TIPO,
    "fuentetipo": _DOMINIO_FUENTE_TIPO,
    "tipofuente": _DOMINIO_FUENTE_TIPO,
    "tipodocumentofuente": _DOMINIO_FUENTE_TIPO,
    "itipodocumento": _DOMINIO_DOCUMENTO_TIPO,
    "tipodocumento": _DOMINIO_DOCUMENTO_TIPO,
    "documentotipo": _DOMINIO_DOCUMENTO_TIPO,
    "interesadodocumentotipo": _DOMINIO_DOCUMENTO_TIPO,
    "isexo": _DOMINIO_SEXO_TIPO,
    "sexo": _DOMINIO_SEXO_TIPO,
    "sexointeresado": _DOMINIO_SEXO_TIPO,
    "interesadosexo": _DOMINIO_SEXO_TIPO,
    "genero": _DOMINIO_SEXO_TIPO,
    "igenero": _DOMINIO_SEXO_TIPO,
    "igrupoetnico": _DOMINIO_GRUPO_ETNICO,
    "grupoetnico": _DOMINIO_GRUPO_ETNICO,
    "tipo": _DOMINIO_PREDIO_TIPO,
    "tipopredio": _DOMINIO_PREDIO_TIPO,
    "condicionpredio": _DOMINIO_CONDICION_PREDIO,
}


def _parse_date(value: object) -> date | None:
    if _is_empty_qgis(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "toPyDate"):
        try:
            return value.toPyDate()
        except Exception:
            pass
    if hasattr(value, "toPyDateTime"):
        try:
            return value.toPyDateTime().date()
        except Exception:
            pass

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


def _matricula_es_vacia_o_cero(value: object | None) -> bool:
    if _is_empty_qgis(value):
        return True
    text = str(value).strip().upper()
    return text in {"0", "0.0", "NULL", "<NULL>", "NONE"}


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


def _domain_token(value: object) -> str:
    text = _normalize_text_for_compare(value)
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return text.strip("_")


def _normalizar_valor_dominio(nombre_campo: object, valor: object) -> object:
    campo_norm = JuridicoHelper._normalize_key(str(nombre_campo))
    mapa = _DOMINIOS_POR_CAMPO.get(campo_norm)

    if valor is None:
        return None

    texto = str(valor).strip()
    if texto == "":
        return None

    texto = texto.replace(",", ".")
    if re.fullmatch(r"\d+\.0+", texto):
        texto = texto.split(".", 1)[0]

    if mapa:
        if texto in mapa:
            return mapa[texto]

        token = _domain_token(texto)
        for clave, valor_normalizado in mapa.items():
            clave_token = _domain_token(clave)
            valor_token = _domain_token(valor_normalizado)
            if token == clave_token or token == valor_token or token.endswith(valor_token):
                return valor_normalizado

    if _is_empty_qgis(valor):
        return None

    return texto


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
    return not _is_empty_qgis(value)


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
    if _is_empty_qgis(value):
        return ""
    value = _normalizar_valor_dominio("d_tipo", value)
    return str(value).strip() if value is not None else ""


def _tipo_interesado_ilicode(value: object) -> str:
    value = _normalizar_valor_dominio("i_tipo", value)
    if _is_empty_qgis(value):
        return ""

    text = _domain_token(value)

    if text.endswith("PERSONA_JURIDICA") or text in {"1", "153", "960", "JURIDICA", "PERSONA_JURIDICA"}:
        return "Persona_Juridica"
    if text.endswith("PERSONA_NATURAL") or text in {"0", "2", "154", "961", "NATURAL", "PERSONA_NATURAL"}:
        return "Persona_Natural"

    return str(value).strip()


def _normalizar_documento_identidad(value: object) -> str:
    if _is_empty_qgis(value):
        return ""

    text = str(value).strip().upper().replace(",", ".")
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]

    normalized = re.sub(r"[\s.\-]", "", text)
    if not normalized:
        return ""

    normalized_text = _normalize_text_for_compare(normalized)
    if normalized_text in {"0", "00", "000", "NOAPLICA", "NA", "NAN", "NULL", "NONE", "SININFORMACION", "SINDATO", "SINDATOS"}:
        return ""

    if re.fullmatch(r"0+", normalized):
        return ""

    return normalized

def _tiene_marca_persona_juridica(value: object) -> bool:
    if not _is_not_empty(value):
        return False

    text = str(value).strip().upper()

    return re.search(
        r"(?:\sLTDA|\sS\.A\.|\s&\sCIA|S\.C\.A\.|\sS\.A\.S\.|\sSAS)$",
        text,
    ) is not None

def _fuente_tipo_ilicode(value: object) -> str:
    if _is_empty_qgis(value):
        return ""
    value = _normalizar_valor_dominio("fa_tipo", value)
    return str(value).strip() if value is not None else ""

def _contains_any(value: object, words: tuple[str, ...]) -> bool:
    if not _is_not_empty(value):
        return False

    normalized = _normalize_text_for_compare(value)
    return any(word.upper() in normalized for word in words)


def _nombre_completo_interesado(row: dict[str, object], helper: JuridicoHelper) -> str:
    partes = (
        helper.get_field_value(row, PRIMER_NOMBRE_FIELDS),
        helper.get_field_value(row, SEGUNDO_NOMBRE_FIELDS),
        helper.get_field_value(row, PRIMER_APELLIDO_FIELDS),
        helper.get_field_value(row, SEGUNDO_APELLIDO_FIELDS),
    )

    return " ".join(str(p).strip() for p in partes if _is_not_empty(p)).strip()

def _grupo_etnico_ilicode(value: object) -> str:
    if _is_empty_qgis(value):
        return ""
    value = _normalizar_valor_dominio("i_grupo_etnico", value)
    return str(value).strip() if value is not None else ""


def _indexar_predios_por_identificador(helper: JuridicoHelper) -> dict[str, dict[str, object]]:
    predios_by_id: dict[str, dict[str, object]] = {}

    for _, row in helper.iter_predios():
        for field_name in PREDIO_IDENTIFIER_FIELDS:
            predio_id = helper.get_field_value(row, (field_name,))
            if predio_id:
                predios_by_id[str(predio_id)] = row

    return predios_by_id


def _buscar_predio_relacionado(
    helper: JuridicoHelper,
    row: dict[str, object],
    predios_by_id: dict[str, dict[str, object]],
) -> tuple[str | None, dict[str, object] | None]:
    first_ref: str | None = None

    for field_name in PREDIO_RELATION_FIELDS:
        predio_ref = helper.get_relation_value(row, (field_name,))
        if not predio_ref:
            continue

        predio_ref_str = str(predio_ref)
        if first_ref is None:
            first_ref = predio_ref_str

        predio_row = predios_by_id.get(predio_ref_str)
        if predio_row:
            return predio_ref_str, predio_row

    return first_ref, None
# ----------------------------- REGLAS -----------------------------

def _rule_2_1(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    today = date.today()
    min_valid_date = date(1900, 1, 1)
    rural_expected = date(1936, 12, 4)
    urban_expected = date(1959, 12, 31)

    predios_by_id = _indexar_predios_por_identificador(helper)

    for table_name, row in helper.iter_derecho_interesado_fuente():
        fecha_inicio_raw = helper.get_field_value(
            row,
            FECHA_INICIO_TENENCIA_FIELDS,
        )
        fecha_inicio = _parse_date(fecha_inicio_raw)

        tipo_derecho = helper.get_field_value(
            row,
            TIPO_DERECHO_FIELDS,
        )
        tipo_derecho_str = _derecho_tipo_ilicode(tipo_derecho)

        predio_ref, predio_row = _buscar_predio_relacionado(helper, row, predios_by_id)

        numero_predial = helper.get_field_value(
            predio_row or {},
            NUMERO_PREDIAL_FIELDS,
        )

        fecha_visita_raw = helper.get_field_value(
            predio_row or {},
            FECHA_VISITA_PREDIAL_FIELDS,
        )
        fecha_visita = _parse_date(fecha_visita_raw)

        matricula = helper.get_field_value(
            predio_row or {},
            MATRICULA_INMOBILIARIA_FIELDS,
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
        (PRIMER_NOMBRE_FIELDS, "primer nombre", "primer_nombre"),
        (SEGUNDO_NOMBRE_FIELDS, "segundo nombre", "segundo_nombre"),
        (PRIMER_APELLIDO_FIELDS, "primer apellido", "primer_apellido"),
        (SEGUNDO_APELLIDO_FIELDS, "segundo apellido", "segundo_apellido"),
    )

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, TIPO_INTERESADO_FIELDS)
        razon_social = helper.get_field_value(row, RAZON_SOCIAL_FIELDS)

        if _tipo_interesado_ilicode(tipo) != "Persona_Natural":
            continue

        if _is_not_empty(razon_social):
            issues.append(
                helper.make_issue(
                    row,
                    rule_id="2.17",
                    message="Para Persona_Natural, la razón social debe ser NULL.",
                    details={
                        "tabla": table_name,
                        "tipo": tipo,
                        "razon_social": razon_social,
                    },
                )
            )
            continue

        for campos, etiqueta, detalle in campos_nombre:
            valor = helper.get_field_value(row, campos)
            if _is_not_empty(valor) and not _only_letters_spaces(valor):
                issues.append(
                    helper.make_issue(
                        row,
                        rule_id="2.17",
                        message=f"El {etiqueta} debe estar compuesto exclusivamente por caracteres alfabéticos.",
                        details={
                            "tabla": table_name,
                            "tipo": tipo,
                            detalle: valor,
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
    """Regla 2.21 alineada con el validador web.

    QGIS 4 puede entregar i_tipo e i_sexo como T_Id, itfCode, iliCode o
    dispName. En este archivo esos valores ya se normalizan mediante
    get_field_value; por eso aqui solo comparamos contra los valores canonicos
    del validador web: Persona_Juridica y Persona_Natural.
    """
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, TIPO_INTERESADO_FIELDS)
        sexo = helper.get_field_value(row, SEXO_FIELDS)

        tipo_str = _tipo_interesado_ilicode(tipo)
        if not tipo_str and tipo is not None:
            fallback_tipo = _normalize_text_for_compare(tipo)
            if "PERSONA_NATURAL" in fallback_tipo or "NATURAL" in fallback_tipo:
                tipo_str = "Persona_Natural"
            elif "PERSONA_JURIDICA" in fallback_tipo or "JURIDICA" in fallback_tipo:
                tipo_str = "Persona_Juridica"

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
                        "tipo_ilicode": tipo_str,
                        "sexo": sexo,
                        "sexo_raw": row.get("i_sexo__raw") or row.get("I_Sexo__raw"),
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

def _rule_2_23(dataset: DatasetReader) -> list[RuleIssue]:
    return []


def _rule_2_24(dataset: DatasetReader) -> list[RuleIssue]:
    return []


def _rule_2_25(dataset: DatasetReader) -> list[RuleIssue]:
    return []


def _rule_2_26(dataset: DatasetReader) -> list[RuleIssue]:
    return []

def _rule_2_27(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_fuente = helper.get_field_value(row, TIPO_FUENTE_FIELDS)
        tipo_fuente_str = _fuente_tipo_ilicode(tipo_fuente)

        ente_emisor = helper.get_field_value(row, ENTE_EMISOR_FIELDS)
        numero_fuente = helper.get_field_value(row, NUMERO_FUENTE_FIELDS)
        fecha_fuente = helper.get_field_value(row, FECHA_FUENTE_FIELDS)
        observacion = helper.get_field_value(row, OBSERVACION_FUENTE_FIELDS)

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
        documento = helper.get_field_value(row, DOCUMENTO_IDENTIDAD_FIELDS)
        razon_social = helper.get_field_value(row, RAZON_SOCIAL_FIELDS)
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
        documento = helper.get_field_value(row, DOCUMENTO_IDENTIDAD_FIELDS)
        razon_social = helper.get_field_value(row, RAZON_SOCIAL_FIELDS)
        nombre_completo = _nombre_completo_interesado(row, helper)

        if _is_not_empty(razon_social):
            clave = f"J:{_normalize_text_for_compare(razon_social)}"
        elif _is_not_empty(nombre_completo):
            clave = f"N:{_normalize_text_for_compare(nombre_completo)}"
        else:
            continue

        documento_normalizado = _normalizar_documento_identidad(documento)
        if not documento_normalizado:
            continue

        documentos_por_nombre.setdefault(clave, set()).add(documento_normalizado)
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
                        "razon_social": helper.get_field_value(row, RAZON_SOCIAL_FIELDS),
                        "documento_identidad": helper.get_field_value(row, DOCUMENTO_IDENTIDAD_FIELDS),
                    },
                )
            )

    return issues

def _rule_2_31(dataset: DatasetReader) -> list[RuleIssue]:
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
    "2.23": _rule_2_23,
    "2.24": _rule_2_24,
    "2.25": _rule_2_25,
    "2.26": _rule_2_26,
    "2.27": _rule_2_27,
    "2.28": _rule_2_28,
    "2.29": _rule_2_29,
    "2.30": _rule_2_30,
    "2.31": _rule_2_31,
    "2.32": _rule_2_32,
}

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
    """Retorna True cuando las posiciones 6-7 del NPN están entre 01 y 99."""
    if not numero_predial or len(numero_predial) < 7:
        return False
    codigo = str(numero_predial)[5:7]
    return codigo.isdigit() and 1 <= int(codigo) <= 99


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
    """Valida la estructura indicada por la regla 2.16: 9 dígitos-guion-dígito."""
    if not _is_not_empty(value):
        return False
    text = str(value).strip()
    match = re.fullmatch(r"([0-9]{9})-([0-9])", text)
    if not match:
        return False
    cuerpo = match.group(1)
    if int(cuerpo) <= 0:
        return False
    return not _es_secuencia_simple(cuerpo)



def _es_secuencia_simple(value: object) -> bool:
    """Detecta secuencias completas ascendentes o descendentes (123456 / 654321)."""
    text = str(value).strip()
    if len(text) < 4 or not text.isdigit():
        return False
    digits = [int(ch) for ch in text]
    asc = all(b - a == 1 for a, b in zip(digits, digits[1:]))
    desc = all(b - a == -1 for a, b in zip(digits, digits[1:]))
    return asc or desc


def _documento_numerico_valido(value: object) -> bool:
    if not _is_not_empty(value):
        return False
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]+", text):
        return False
    if int(text) <= 0:
        return False
    return not _es_secuencia_simple(text)


def _ente_emisor_valido_acto_administrativo(value: object) -> bool:
    """Evita falsos positivos por subcadenas, por ejemplo ANT dentro de SANTANDER."""
    if not _is_not_empty(value):
        return False
    normalized = _normalize_text_for_compare(value)
    if "AGENCIA NACIONAL DE TIERRAS" in normalized:
        return True
    tokens = re.findall(r"[A-Z0-9]+", normalized)
    if any(token.startswith("ALCALD") for token in tokens):
        return True
    return any(token in {"ANT", "INCODER", "INCORA", "MINISTERIO"} for token in tokens)


def _firma_identidad_interesado(row: dict[str, object], helper: JuridicoHelper) -> str:
    tipo = _tipo_interesado_ilicode(helper.get_field_value(row, TIPO_INTERESADO_FIELDS))
    tipo_documento = helper.get_field_value(row, ("i_tipo_documento", "I_Tipo_Documento", "tipo_documento"))
    razon_social = helper.get_field_value(row, RAZON_SOCIAL_FIELDS)
    nombre = _nombre_completo_interesado(row, helper)
    if _is_not_empty(razon_social):
        identidad = "J:" + _normalize_text_for_compare(razon_social)
    elif _is_not_empty(nombre):
        identidad = "N:" + _normalize_text_for_compare(nombre)
    else:
        return ""
    return "|".join((tipo, _normalize_text_for_compare(tipo_documento), identidad))


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
    """Detecta las marcas societarias enumeradas por la regla 2.22 en cualquier posición."""
    if not _is_not_empty(value):
        return False
    text = _normalize_text_for_compare(value)
    patterns = (
        r"\bLTDA\b",
        r"\bS\s*\.?\s*A\s*\.?\s*S\b",
        r"\bSAS\b",
        r"\bS\s*\.?\s*A\b",
        r"\bSA\b",
        r"\bS\s*\.?\s*C\s*\.?\s*A\b",
        r"\bSCA\b",
        r"\bS\s*\.?\s*EN\s+C\b",
        r"&\s*CIA\b",
        r"\bCIA\b",
    )
    return any(re.search(pattern, text) for pattern in patterns)


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
    rural_expected = date(1936, 12, 4)
    urban_expected = date(1959, 12, 31)
    predios_by_id = _indexar_predios_por_identificador(helper)

    for table_name, row in helper.iter_derecho_interesado_fuente():
        fecha_inicio_raw = helper.get_field_value(row, FECHA_INICIO_TENENCIA_FIELDS)
        if fecha_inicio_raw is None:
            # La obligatoriedad de este dato se controla en el componente 11.x.
            continue
        fecha_inicio = _parse_date(fecha_inicio_raw)
        tipo_derecho = helper.get_field_value(row, TIPO_DERECHO_FIELDS)
        tipo_derecho_str = _derecho_tipo_ilicode(tipo_derecho)
        predio_ref, predio_row = _buscar_predio_relacionado(helper, row, predios_by_id)
        numero_predial = helper.get_field_value(predio_row or {}, NUMERO_PREDIAL_FIELDS)
        fecha_visita_raw = helper.get_field_value(predio_row or {}, FECHA_VISITA_PREDIAL_FIELDS)
        fecha_visita = _parse_date(fecha_visita_raw)
        matricula = helper.get_field_value(predio_row or {}, MATRICULA_INMOBILIARIA_FIELDS)
        message = None

        if fecha_inicio is None:
            message = "La fecha de inicio de tenencia tiene un formato o valor no válido."
        elif fecha_visita and fecha_inicio > fecha_visita:
            message = "La fecha de inicio de tenencia no puede ser mayor a la fecha de visita predial."
        elif tipo_derecho_str == "Dominio" and _matricula_es_vacia_o_cero(matricula):
            if _numero_predial_es_rural(numero_predial) and fecha_inicio != rural_expected:
                message = "Predio rural sin matrícula y con derecho Dominio debe tener fecha de inicio 1936-12-04."
            elif _numero_predial_es_urbano_sql(numero_predial) and fecha_inicio != urban_expected:
                message = "Predio urbano sin matrícula y con derecho Dominio debe tener fecha de inicio 1959-12-31."

        if message:
            issues.append(helper.make_issue(row, rule_id="2.1", message=message, details={
                "tabla": table_name, "fecha_inicio_tenencia": fecha_inicio_raw,
                "fecha_visita_predial": fecha_visita_raw, "numero_predial": numero_predial,
                "matricula": matricula, "tipo_derecho": tipo_derecho, "predio_ref": predio_ref,
            }))
    return issues


def _rule_2_2(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    predios_by_id = _indexar_predios_por_identificador(helper)
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, TIPO_DERECHO_FIELDS)
        predio_ref, predio_row = _buscar_predio_relacionado(helper, row, predios_by_id)
        if not predio_row:
            continue
        tipo_predio = helper.get_field_value(predio_row, ("tipo", "Tipo"))
        condicion = helper.get_field_value(predio_row, ("Condicion_Predio", "condicion_predio"))
        matricula = helper.get_field_value(predio_row, MATRICULA_INMOBILIARIA_FIELDS)
        tipo_derecho_str = _derecho_tipo_ilicode(tipo_derecho)
        tipo_predio_str = str(tipo_predio or "").strip()
        condicion_str = str(condicion or "").strip()
        message = None
        if condicion_str == "Informal":
            if tipo_derecho_str not in {"Posesion", "Ocupacion"}:
                message = "Un predio con condición Informal solo puede estar asociado a Posesion u Ocupacion."
            elif not _matricula_es_vacia_o_cero(matricula):
                message = "Un predio con condición Informal no debe tener matrícula inmobiliaria."
        elif tipo_predio_str == "Predio.Privado.Privado" and tipo_derecho_str == "Dominio" and _matricula_es_vacia_o_cero(matricula):
            message = "En un predio Privado no informal con derecho Dominio, la matrícula inmobiliaria es obligatoria."
        if message:
            issues.append(helper.make_issue(row, rule_id="2.2", message=message, details={
                "tabla": table_name, "tipo_derecho": tipo_derecho, "tipo_predio": tipo_predio,
                "condicion_predio": condicion, "matricula": matricula, "predio_ref": predio_ref,
            }))
    return issues


def _rule_2_3(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    predios_by_id = _indexar_predios_por_identificador(helper)
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, TIPO_DERECHO_FIELDS)
        predio_ref, predio_row = _buscar_predio_relacionado(helper, row, predios_by_id)
        if not predio_row:
            continue
        tipo_predio = helper.get_field_value(predio_row, ("tipo", "Tipo"))
        if _derecho_tipo_ilicode(tipo_derecho) == "Posesion" and str(tipo_predio or "").strip() != "Predio.Privado.Privado":
            issues.append(helper.make_issue(row, rule_id="2.3", message="Los predios asociados a derecho Posesion deben ser de tipo Privado.", details={
                "tabla": table_name, "tipo_derecho": tipo_derecho, "tipo_predio": tipo_predio, "predio_ref": predio_ref,
            }))
    return issues


def _rule_2_4(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    predios_by_id = _indexar_predios_por_identificador(helper)
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, TIPO_DERECHO_FIELDS)
        predio_ref, predio_row = _buscar_predio_relacionado(helper, row, predios_by_id)
        if not predio_row:
            continue
        tipo_predio = helper.get_field_value(predio_row, ("tipo", "Tipo"))
        condicion = helper.get_field_value(predio_row, ("Condicion_Predio", "condicion_predio"))
        if str(tipo_predio or "").strip() == "Predio.Privado.Privado" and _derecho_tipo_ilicode(tipo_derecho) == "Ocupacion" and str(condicion or "").strip() != "Informal":
            issues.append(helper.make_issue(row, rule_id="2.4", message="Los predios Privados con derecho Ocupacion deben tener condición Informal.", details={
                "tabla": table_name, "tipo_derecho": tipo_derecho, "tipo_predio": tipo_predio,
                "condicion_predio": condicion, "predio_ref": predio_ref,
            }))
    return issues


def _rule_2_5(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    predios_by_id = _indexar_predios_por_identificador(helper)
    tipos_publicos = {
        "Predio.Publico.Baldio.Baldio", "Predio.Publico.Baldio.Reserva_Indigena",
        "Predio.Publico.Fiscal_Patrimonial", "Predio.Publico.Uso_Publico", "Predio.Publico.Presunto_Baldio",
    }
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, TIPO_DERECHO_FIELDS)
        predio_ref, predio_row = _buscar_predio_relacionado(helper, row, predios_by_id)
        if not predio_row:
            continue
        tipo_predio = helper.get_field_value(predio_row, ("tipo", "Tipo"))
        if str(tipo_predio or "").strip() in tipos_publicos and _derecho_tipo_ilicode(tipo_derecho) == "Posesion":
            issues.append(helper.make_issue(row, rule_id="2.5", message="Para predios Públicos, el tipo de derecho no puede ser Posesion.", details={
                "tabla": table_name, "tipo_derecho": tipo_derecho, "tipo_predio": tipo_predio, "predio_ref": predio_ref,
            }))
    return issues


def _rule_2_6(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    predios_by_id = _indexar_predios_por_identificador(helper)
    tipos_baldio = {"Predio.Publico.Baldio.Baldio", "Predio.Publico.Baldio.Reserva_Indigena", "Predio.Publico.Presunto_Baldio"}
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, TIPO_DERECHO_FIELDS)
        predio_ref, predio_row = _buscar_predio_relacionado(helper, row, predios_by_id)
        if not predio_row:
            continue
        tipo_predio = helper.get_field_value(predio_row, ("tipo", "Tipo"))
        razon_social = helper.get_field_value(row, RAZON_SOCIAL_FIELDS)
        if str(tipo_predio or "").strip() in tipos_baldio and _derecho_tipo_ilicode(tipo_derecho) == "Dominio" and not _interesado_es_valido_baldio(razon_social):
            issues.append(helper.make_issue(row, rule_id="2.6", message="En baldíos con derecho Dominio, la razón social debe corresponder a la Nación, Municipio o Agencia Nacional de Tierras.", details={
                "tabla": table_name, "tipo_derecho": tipo_derecho, "tipo_predio": tipo_predio,
                "razon_social": razon_social, "predio_ref": predio_ref,
            }))
    return issues


def _rule_2_7(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    predios_by_id = _indexar_predios_por_identificador(helper)
    for table_name, row in helper.iter_derecho_interesado_fuente():
        predio_ref, predio_row = _buscar_predio_relacionado(helper, row, predios_by_id)
        if not predio_row:
            continue
        tipo_predio = helper.get_field_value(predio_row, ("tipo", "Tipo"))
        grupo = helper.get_field_value(row, ("I_Grupo_Etnico", "i_grupo_etnico"))
        grupo_str = _grupo_etnico_ilicode(grupo)
        if str(tipo_predio or "").strip() == "Predio.Privado.Colectivo" and (not grupo_str or grupo_str == "Ninguno"):
            issues.append(helper.make_issue(row, rule_id="2.7", message="En un predio Privado Colectivo, el grupo étnico debe estar diligenciado y ser diferente de Ninguno.", details={
                "tabla": table_name, "tipo_predio": tipo_predio, "grupo_etnico": grupo, "predio_ref": predio_ref,
            }))
    return issues


def _rule_2_8(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    predios_by_id = _indexar_predios_por_identificador(helper)
    tipos_baldio = {"Predio.Publico.Baldio.Baldio", "Predio.Publico.Baldio.Reserva_Indigena", "Predio.Publico.Presunto_Baldio"}
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, TIPO_DERECHO_FIELDS)
        predio_ref, predio_row = _buscar_predio_relacionado(helper, row, predios_by_id)
        if not predio_row:
            continue
        tipo_predio = helper.get_field_value(predio_row, ("tipo", "Tipo"))
        razon_social = helper.get_field_value(row, RAZON_SOCIAL_FIELDS)
        if str(tipo_predio or "").strip() in tipos_baldio and _derecho_tipo_ilicode(tipo_derecho) == "Ocupacion" and _interesado_es_valido_baldio(razon_social):
            issues.append(helper.make_issue(row, rule_id="2.8", message="En baldíos con derecho Ocupacion, el interesado no debe corresponder a la Nación, Municipio o Agencia Nacional de Tierras.", details={
                "tabla": table_name, "tipo_derecho": tipo_derecho, "tipo_predio": tipo_predio,
                "razon_social": razon_social, "predio_ref": predio_ref,
            }))
    return issues


def _rule_2_9(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    predios_by_id = _indexar_predios_por_identificador(helper)
    tipos_objetivo = {"Predio.Publico.Fiscal_Patrimonial", "Predio.Publico.Uso_Publico"}
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, TIPO_DERECHO_FIELDS)
        tipo_interesado = helper.get_field_value(row, TIPO_INTERESADO_FIELDS)
        predio_ref, predio_row = _buscar_predio_relacionado(helper, row, predios_by_id)
        if not predio_row:
            continue
        tipo_predio = helper.get_field_value(predio_row, ("tipo", "Tipo"))
        if str(tipo_predio or "").strip() in tipos_objetivo and _derecho_tipo_ilicode(tipo_derecho) == "Dominio" and _tipo_interesado_ilicode(tipo_interesado) != "Persona_Juridica":
            issues.append(helper.make_issue(row, rule_id="2.9", message="En predios Públicos fiscales/patrimoniales o de uso público con Dominio, el interesado debe ser Persona_Juridica.", details={
                "tabla": table_name, "tipo_predio": tipo_predio, "tipo_derecho": tipo_derecho,
                "tipo_interesado": tipo_interesado, "predio_ref": predio_ref,
            }))
    return issues


def _rule_2_10(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    predios_by_id = _indexar_predios_por_identificador(helper)
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, TIPO_DERECHO_FIELDS)
        predio_ref, predio_row = _buscar_predio_relacionado(helper, row, predios_by_id)
        if not predio_row:
            continue
        tipo_predio = helper.get_field_value(predio_row, ("tipo", "Tipo"))
        condicion = helper.get_field_value(predio_row, ("Condicion_Predio", "condicion_predio"))
        condicion_str = str(condicion or "").strip()
        if condicion_str in {"Via", "Bien_Uso_Publico"} and (str(tipo_predio or "").strip() != "Predio.Publico.Uso_Publico" or _derecho_tipo_ilicode(tipo_derecho) != "Dominio"):
            issues.append(helper.make_issue(row, rule_id="2.10", message="Para predios con condición Via o Bien_Uso_Publico, el tipo debe ser Predio.Publico.Uso_Publico y el derecho Dominio.", details={
                "tabla": table_name, "condicion_predio": condicion, "tipo_predio": tipo_predio,
                "tipo_derecho": tipo_derecho, "predio_ref": predio_ref,
            }))
    return issues


def _rule_2_11(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    predios_by_id = _indexar_predios_por_identificador(helper)
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = helper.get_field_value(row, TIPO_DERECHO_FIELDS)
        if _derecho_tipo_ilicode(tipo_derecho) != "Dominio":
            continue
        predio_ref, predio_row = _buscar_predio_relacionado(helper, row, predios_by_id)
        if not predio_row:
            continue
        matricula = helper.get_field_value(predio_row, MATRICULA_INMOBILIARIA_FIELDS)
        if _matricula_es_vacia_o_cero(matricula):
            continue
        fecha_inicio_raw = helper.get_field_value(row, FECHA_INICIO_TENENCIA_FIELDS)
        fecha_fuente_raw = helper.get_field_value(row, FECHA_FUENTE_FIELDS)
        fecha_inicio = _parse_date(fecha_inicio_raw)
        fecha_fuente = _parse_date(fecha_fuente_raw)
        if fecha_inicio and fecha_fuente and fecha_inicio < fecha_fuente:
            issues.append(helper.make_issue(row, rule_id="2.11", message="En predios con matrícula y derecho Dominio, la fecha de inicio de tenencia debe ser mayor o igual a la fecha del documento fuente.", details={
                "tabla": table_name, "matricula": matricula, "tipo_derecho": tipo_derecho,
                "fecha_inicio_tenencia": fecha_inicio_raw, "fecha_documento_fuente": fecha_fuente_raw,
                "predio_ref": predio_ref,
            }))
    return issues


def _rule_2_12(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    predios_by_id = _indexar_predios_por_identificador(helper)
    require_numero_emisor = {
        "Documento_Fuente.Acto_Administrativo", "Documento_Fuente.Sentencia_Judicial",
        "Documento_Fuente.Escritura_Publica", "Documento_Fuente.Otro_Documento_fuente",
        "Fuente_Informativa_Intercultural.Auto", "Fuente_Informativa_Intercultural.Protocolizacion_Notarial",
        "Fuente_Informativa_Intercultural.Otros_Documentos",
    }
    require_emisor_sin_numero = {
        "Documento_Fuente.Titulo_Colonial", "Documento_Fuente.Titulo_Republicano", "Documento_Fuente.Cedula_Real",
    }
    for table_name, row in helper.iter_derecho_interesado_fuente():
        predio_ref, predio_row = _buscar_predio_relacionado(helper, row, predios_by_id)
        if not predio_row:
            continue
        matricula = helper.get_field_value(predio_row, MATRICULA_INMOBILIARIA_FIELDS)
        if _matricula_es_vacia_o_cero(matricula):
            continue
        tipo_fuente = helper.get_field_value(row, TIPO_FUENTE_FIELDS)
        tipo_fuente_str = _fuente_tipo_ilicode(tipo_fuente)
        fecha_fuente_raw = helper.get_field_value(row, FECHA_FUENTE_FIELDS)
        numero_fuente = helper.get_field_value(row, NUMERO_FUENTE_FIELDS)
        ente_emisor = helper.get_field_value(row, ENTE_EMISOR_FIELDS)
        fecha_visita_raw = helper.get_field_value(predio_row, FECHA_VISITA_PREDIAL_FIELDS)
        fecha_fuente = _parse_date(fecha_fuente_raw)
        fecha_visita = _parse_date(fecha_visita_raw)
        faltantes: list[str] = []
        message = None

        if not tipo_fuente_str:
            faltantes.append("tipo de fuente")
        elif tipo_fuente_str == "Sin_Documento":
            message = "Un predio con matrícula inmobiliaria debe tener una fuente documental asociada."
        else:
            if not _is_not_empty(fecha_fuente_raw):
                faltantes.append("fecha del documento fuente")
            if tipo_fuente_str in require_numero_emisor:
                if not _is_not_empty(numero_fuente):
                    faltantes.append("número de fuente")
                if not _is_not_empty(ente_emisor):
                    faltantes.append("ente emisor")
            elif tipo_fuente_str in require_emisor_sin_numero and not _is_not_empty(ente_emisor):
                faltantes.append("ente emisor")

        if message is None and faltantes:
            message = "Predio con matrícula: faltan " + ", ".join(faltantes) + "."
        elif message is None and _is_not_empty(fecha_fuente_raw) and fecha_fuente is None:
            message = "La fecha del documento fuente tiene un formato o valor no válido."
        elif message is None and fecha_fuente and fecha_visita and fecha_fuente > fecha_visita:
            message = "La fecha del documento fuente no puede ser posterior a la fecha de visita predial."

        if message:
            issues.append(helper.make_issue(row, rule_id="2.12", message=message, details={
                "tabla": table_name, "matricula": matricula, "tipo_fuente": tipo_fuente,
                "fecha_documento_fuente": fecha_fuente_raw, "numero_fuente": numero_fuente,
                "ente_emisor": ente_emisor, "fecha_visita_predial": fecha_visita_raw, "predio_ref": predio_ref,
            }))
    return issues


def _rule_2_13(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, TIPO_INTERESADO_FIELDS)
        tipo_documento = helper.get_field_value(row, ("i_tipo_documento", "I_Tipo_Documento", "tipo_documento"))
        if _tipo_interesado_ilicode(tipo) == "Persona_Juridica" and str(tipo_documento or "").strip() not in {"NIT", "Secuencial"}:
            issues.append(helper.make_issue(row, rule_id="2.13", message="Una Persona_Juridica solamente puede tener tipo de documento NIT o Secuencial.", details={"tabla": table_name, "tipo": tipo, "tipo_documento": tipo_documento}))
    return issues


def _rule_2_14(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    validos = {"Cedula_Ciudadania", "Pasaporte", "Cedula_Extranjeria", "Tarjeta_Identidad", "Registro_Civil", "Secuencial"}
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, TIPO_INTERESADO_FIELDS)
        tipo_documento = helper.get_field_value(row, ("i_tipo_documento", "I_Tipo_Documento", "tipo_documento"))
        if _tipo_interesado_ilicode(tipo) == "Persona_Natural" and str(tipo_documento or "").strip() not in validos:
            issues.append(helper.make_issue(row, rule_id="2.14", message="Una Persona_Natural solo puede usar CC, Pasaporte, CE, TI, Registro Civil o Secuencial.", details={"tabla": table_name, "tipo": tipo, "tipo_documento": tipo_documento}))
    return issues


def _rule_2_15(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    tipos = {"Cedula_Ciudadania", "Cedula_Extranjeria", "Tarjeta_Identidad", "Registro_Civil"}
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_documento = helper.get_field_value(row, ("i_tipo_documento", "I_Tipo_Documento", "tipo_documento"))
        documento = helper.get_field_value(row, DOCUMENTO_IDENTIDAD_FIELDS)
        if str(tipo_documento or "").strip() in tipos and not _documento_numerico_valido(documento):
            issues.append(helper.make_issue(row, rule_id="2.15", message="El documento debe ser numérico, mayor que cero, sin caracteres especiales y no debe ser una secuencia consecutiva.", details={"tabla": table_name, "tipo_documento": tipo_documento, "documento_identidad": documento}))
    return issues


def _rule_2_16(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_documento = helper.get_field_value(row, ("i_tipo_documento", "I_Tipo_Documento", "tipo_documento"))
        documento = helper.get_field_value(row, DOCUMENTO_IDENTIDAD_FIELDS)
        if str(tipo_documento or "").strip() == "NIT" and not _nit_es_valido(documento):
            issues.append(helper.make_issue(row, rule_id="2.16", message="El NIT debe cumplir la estructura de nueve dígitos, guion y un dígito de verificación; ser mayor a cero y no consecutivo.", details={"tabla": table_name, "tipo_documento": tipo_documento, "documento_identidad": documento}))
    return issues


def _rule_2_17(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    campos = (
        (PRIMER_NOMBRE_FIELDS, "primer nombre", True), (SEGUNDO_NOMBRE_FIELDS, "segundo nombre", False),
        (PRIMER_APELLIDO_FIELDS, "primer apellido", True), (SEGUNDO_APELLIDO_FIELDS, "segundo apellido", False),
    )
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, TIPO_INTERESADO_FIELDS)
        if _tipo_interesado_ilicode(tipo) != "Persona_Natural":
            continue
        for field_names, etiqueta, obligatorio in campos:
            valor = helper.get_field_value(row, field_names)
            invalido = (obligatorio and not _is_not_empty(valor)) or (_is_not_empty(valor) and not _only_letters_spaces(valor))
            if invalido:
                message = f"Para Persona_Natural, el {etiqueta} es obligatorio y debe contener solo caracteres alfabéticos." if obligatorio else f"Si se diligencia el {etiqueta}, debe contener solo caracteres alfabéticos."
                issues.append(helper.make_issue(row, rule_id="2.17", message=message, details={"tabla": table_name, "tipo": tipo, etiqueta.replace(' ', '_'): valor}))
                break
    return issues


def _rule_2_18(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    campos = ((PRIMER_NOMBRE_FIELDS, "primer nombre"), (SEGUNDO_NOMBRE_FIELDS, "segundo nombre"), (PRIMER_APELLIDO_FIELDS, "primer apellido"), (SEGUNDO_APELLIDO_FIELDS, "segundo apellido"))
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, TIPO_INTERESADO_FIELDS)
        if _tipo_interesado_ilicode(tipo) != "Persona_Juridica":
            continue
        for fields, etiqueta in campos:
            valor = helper.get_field_value(row, fields)
            if _is_not_empty(valor):
                issues.append(helper.make_issue(row, rule_id="2.18", message=f"Para Persona_Juridica, el {etiqueta} debe ser NULL.", details={"tabla": table_name, "tipo": tipo, etiqueta.replace(' ', '_'): valor}))
                break
    return issues


def _rule_2_19(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    campos = ((PRIMER_NOMBRE_FIELDS, "primer nombre"), (SEGUNDO_NOMBRE_FIELDS, "segundo nombre"), (PRIMER_APELLIDO_FIELDS, "primer apellido"), (SEGUNDO_APELLIDO_FIELDS, "segundo apellido"))
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, TIPO_INTERESADO_FIELDS)
        if _tipo_interesado_ilicode(tipo) != "Persona_Natural":
            continue
        for fields, etiqueta in campos:
            valor = helper.get_field_value(row, fields)
            if _is_not_empty(valor) and (not _only_letters_spaces(valor) or _has_suc(valor)):
                issues.append(helper.make_issue(row, rule_id="2.19", message=f"El {etiqueta} no debe contener SUC, números ni caracteres especiales.", details={"tabla": table_name, "tipo": tipo, etiqueta.replace(' ', '_'): valor}))
                break
    return issues


def _rule_2_20(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    campos = (PRIMER_NOMBRE_FIELDS, SEGUNDO_NOMBRE_FIELDS, PRIMER_APELLIDO_FIELDS, SEGUNDO_APELLIDO_FIELDS)
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, TIPO_INTERESADO_FIELDS)
        if _tipo_interesado_ilicode(tipo) != "Persona_Juridica":
            continue
        razon = helper.get_field_value(row, RAZON_SOCIAL_FIELDS)
        nombres_diligenciados = [helper.get_field_value(row, fields) for fields in campos]
        if any(_is_not_empty(v) for v in nombres_diligenciados) or not _is_not_empty(razon):
            issues.append(helper.make_issue(row, rule_id="2.20", message="Para Persona_Juridica solo debe diligenciarse la razón social y esta es obligatoria.", details={"tabla": table_name, "tipo": tipo, "razon_social": razon, "nombres": nombres_diligenciados}))
    return issues


def _rule_2_21(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, TIPO_INTERESADO_FIELDS)
        sexo = helper.get_field_value(row, SEXO_FIELDS)
        tipo_str = _tipo_interesado_ilicode(tipo)
        if _is_not_empty(sexo) and tipo_str != "Persona_Natural":
            issues.append(helper.make_issue(row, rule_id="2.21", message="El atributo Sexo solo puede diligenciarse para interesados de tipo Persona_Natural.", details={"tabla": table_name, "tipo": tipo, "tipo_ilicode": tipo_str, "sexo": sexo}))
    return issues


def _rule_2_22(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    campos = ((PRIMER_NOMBRE_FIELDS, "primer nombre"), (SEGUNDO_NOMBRE_FIELDS, "segundo nombre"), (PRIMER_APELLIDO_FIELDS, "primer apellido"), (SEGUNDO_APELLIDO_FIELDS, "segundo apellido"))
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, TIPO_INTERESADO_FIELDS)
        if _tipo_interesado_ilicode(tipo) != "Persona_Natural":
            continue
        for fields, etiqueta in campos:
            valor = helper.get_field_value(row, fields)
            if _tiene_marca_persona_juridica(valor):
                issues.append(helper.make_issue(row, rule_id="2.22", message=f"El {etiqueta} contiene una marca propia de Persona_Juridica.", details={"tabla": table_name, "tipo": tipo, etiqueta.replace(' ', '_'): valor}))
                break
    return issues


def _rule_2_23(dataset: DatasetReader) -> list[RuleIssue]:
    # N/A en ARB actual: no se materializa COL_AgrupacionInteresados como entidad independiente.
    return []


def _rule_2_24(dataset: DatasetReader) -> list[RuleIssue]:
    # N/A en ARB actual: no se materializa COL_AgrupacionInteresados como entidad independiente.
    return []


def _rule_2_25(dataset: DatasetReader) -> list[RuleIssue]:
    # N/A en ARB actual: no se materializa COL_AgrupacionInteresados como entidad independiente.
    return []


def _rule_2_26(dataset: DatasetReader) -> list[RuleIssue]:
    # N/A en ARB actual: no existe col_miembros/agrupación con identidad propia para sumar participación sin ambigüedad.
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
        tipo_fuente = helper.get_field_value(row, TIPO_FUENTE_FIELDS)
        tipo_fuente_str = _fuente_tipo_ilicode(tipo_fuente)
        ente = helper.get_field_value(row, ENTE_EMISOR_FIELDS)
        message = None
        if tipo_fuente_str == "Documento_Fuente.Escritura_Publica" and not _contains_any(ente, ("NOTAR",)):
            message = "El ente emisor de una Escritura Pública debe corresponder a una notaría."
        elif tipo_fuente_str == "Documento_Fuente.Sentencia_Judicial" and not _contains_any(ente, ("JUZGADO",)):
            message = "El ente emisor de una Sentencia Judicial debe corresponder a un juzgado."
        elif tipo_fuente_str == "Documento_Fuente.Acto_Administrativo" and not _ente_emisor_valido_acto_administrativo(ente):
            message = "El ente emisor de un Acto Administrativo debe corresponder a alcaldía, ANT, INCODER, INCORA o ministerio."
        if message:
            issues.append(helper.make_issue(row, rule_id="2.28", message=message, details={"tabla": table_name, "tipo_fuente": tipo_fuente, "tipo_fuente_ilicode": tipo_fuente_str, "ente_emisor": ente}))
    return issues


def _rule_2_29(dataset: DatasetReader) -> list[RuleIssue]:
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    predios_by_id = _indexar_predios_por_identificador(helper)
    predios_con_interesado: set[str] = set()
    for _, row in helper.iter_derecho_interesado_fuente():
        tipo = helper.get_field_value(row, TIPO_INTERESADO_FIELDS)
        documento = helper.get_field_value(row, DOCUMENTO_IDENTIDAD_FIELDS)
        razon = helper.get_field_value(row, RAZON_SOCIAL_FIELDS)
        nombre = _nombre_completo_interesado(row, helper)
        if not any((_is_not_empty(tipo), _is_not_empty(documento), _is_not_empty(razon), _is_not_empty(nombre))):
            continue
        predio_ref, predio_row = _buscar_predio_relacionado(helper, row, predios_by_id)
        if predio_row:
            for field in PREDIO_IDENTIFIER_FIELDS:
                value = helper.get_field_value(predio_row, (field,))
                if value:
                    predios_con_interesado.add(str(value))
        elif predio_ref:
            predios_con_interesado.add(str(predio_ref))
    for table_name, row in helper.iter_predios():
        ids = {str(v) for field in PREDIO_IDENTIFIER_FIELDS if (v := helper.get_field_value(row, (field,)))}
        if ids and ids.isdisjoint(predios_con_interesado):
            issues.append(helper.make_issue(row, rule_id="2.29", message="Todo predio debe tener asociado al menos un interesado (o agrupación cuando el modelo la represente).", details={"tabla": table_name, "predio_ids": sorted(ids), "numero_predial": helper.get_field_value(row, NUMERO_PREDIAL_FIELDS)}))
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
    """Detecta un mismo documento asociado a identidades distintas.

    ARB_DerechoInteresadoFuente es una vista/estructura aplanada: la misma persona
    puede repetirse legítimamente por derechos o fuentes diferentes. Sin un id de
    ILC_Interesado separado, tratar toda repetición como duplicado produciría falsos
    positivos. Se reporta cuando el mismo documento identifica personas distintas.
    """
    helper = JuridicoHelper(dataset)
    por_documento: dict[str, dict[str, list[tuple[str, dict[str, object]]]]] = {}
    for table_name, row in helper.iter_derecho_interesado_fuente():
        documento = _normalizar_documento_identidad(helper.get_field_value(row, DOCUMENTO_IDENTIDAD_FIELDS))
        if not documento:
            continue
        firma = _firma_identidad_interesado(row, helper)
        if not firma:
            continue
        por_documento.setdefault(documento, {}).setdefault(firma, []).append((table_name, row))
    issues: list[RuleIssue] = []
    for documento, firmas in por_documento.items():
        if len(firmas) <= 1:
            continue
        for rows in firmas.values():
            for table_name, row in rows:
                issues.append(helper.make_issue(row, rule_id="2.31", message="El mismo número de documento está asociado a identidades diferentes.", details={"tabla": table_name, "documento_identidad": helper.get_field_value(row, DOCUMENTO_IDENTIDAD_FIELDS), "documento_normalizado": documento, "identidades_distintas": len(firmas)}))
    return issues


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
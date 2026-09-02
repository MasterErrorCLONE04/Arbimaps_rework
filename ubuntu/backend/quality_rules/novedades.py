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

COMPONENT_SLUG = "novedades"

DEFAULT_RULE_IDS = frozenset({
    # Conserva el catálogo actual. 8.2, 8.4, 8.5 y 8.7 siguen sin función
    # ejecutable, tal como en la base de 207 reglas; no se reactivan en esta auditoría.
    "8.1", "8.2", "8.3", "8.4", "8.5", "8.6", "8.7", "8.8", "8.11", "8.12",
    "8.13", "8.14", "8.15", "8.16", "8.18", "8.19", "8.20", "8.22", "8.24", "8.26",
})


class NovedadescoHelper:
    """Utilidades compartidas para reglas novedades."""

    IDENTIFIER_FIELDS = (
        "t_ili_tid",
        "T_Ili_Tid",
        "T_ILI_TID",
        "id_operacion",
        "t_id",
        "TID",
        "id",
    )

    PREDIO_TABLES = (
        "ARB_Predio",
        "arb_predio",
    )

    NOVEDAD_NUMERO_PREDIAL_TABLES = (
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

    def iter_novedad_numero_predial(self):
        yield from self._iter_table_rows(self.NOVEDAD_NUMERO_PREDIAL_TABLES)

    def iter_terreno(self):
        yield from self._iter_table_rows(self.TERRENO_TABLES)

    def iter_construccion(self):
        yield from self._iter_table_rows(self.CONSTRUCCION_TABLES)

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
    
def _pos_22(value: object) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return None if len(text) < 22 else text[21]

def _pos_18(value: object) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return None if len(text) < 18 else text[17]

def _is_predio_nuevo_pos_18(pos_18: str | None) -> bool:
    # Las reglas 8.18 y 8.20 definen predio nuevo como A-Z en la posicion 18.
    return bool(pos_18 and pos_18.isalpha())

def _matricula_vacia(value: object) -> bool:
    if value in (None, ""):
        return True
    text = str(value).strip()
    if not text:
        return True
    try:
        return float(text.replace(",", ".")) == 0
    except Exception:
        return False

    # --------------- reglas -------------------

def _rule_8_1(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NovedadescoHelper(dataset)
    issues: list[RuleIssue] = []

    TIPOS_DESENGLOBE = {
        "0",
        "1",
        "Desenglobe_Venta_Parcial",
        "Desenglobe_Division_Material",
    }

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, predio in helper.iter_predio():
        predio_id = helper.get_field_value(predio, ("t_id", "TID", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for table_name, novedad in helper.iter_novedad_numero_predial():
        tipo_novedad = helper.get_field_value(novedad, ("tipo_novedad",))
        predio_ref = helper.get_field_value(
            novedad,
            ("arb_predio_novedad_numero_predial",),
        )

        if not tipo_novedad or str(tipo_novedad) not in TIPOS_DESENGLOBE:
            continue

        predio = predios_by_id.get(str(predio_ref))
        if not predio:
            continue

        matricula = helper.get_field_value(
            predio,
            ("matricula_inmobiliaria", "Matricula_Inmobiliaria"),
        )

        if _matricula_vacia(matricula):
            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="8.1",
                    message=(
                        "Los predios asociados al desenglobe deben tener "
                        "folio de matrícula inmobiliaria."
                    ),
                    details={
                        "tabla": "ARB_Predio",
                        "tabla_novedad": table_name,
                        "predio_ref": predio_ref,
                        "tipo_novedad": tipo_novedad,
                        "matricula_inmobiliaria": matricula,
                    },
                )
            )

    return issues
    
def _rule_8_3(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NovedadescoHelper(dataset)
    issues: list[RuleIssue] = []

    TIPOS_DESENGLOBE = {
        "0",
        "1",
        "Desenglobe_Venta_Parcial",
        "Desenglobe_Division_Material",
    }

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, predio in helper.iter_predio():
        predio_id = helper.get_field_value(predio, ("t_id", "TID", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for table_name, novedad in helper.iter_novedad_numero_predial():
        tipo_novedad = helper.get_field_value(novedad, ("tipo_novedad",))
        predio_ref = helper.get_field_value(
            novedad,
            ("arb_predio_novedad_numero_predial",),
        )

        if not tipo_novedad or str(tipo_novedad) not in TIPOS_DESENGLOBE:
            continue

        predio = predios_by_id.get(str(predio_ref))
        if not predio:
            continue

        numero_predial_predio = helper.get_field_value(
            predio,
            ("numero_predial",),
        )

        numero_predial_novedad = helper.get_field_value(
            novedad,
            ("numero_predial",),
        )

        pos_22_predio = _pos_22(numero_predial_predio)
        pos_22_novedad = _pos_22(numero_predial_novedad)

        if pos_22_predio == "2" or pos_22_novedad == "2":
            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="8.3",
                    message=(
                        "Todo predio asociado a una novedad de número predial "
                        "de tipo desenglobe no puede tener valor 2 en la posición "
                        "22 del número predial del predio ni de la novedad."
                    ),
                    details={
                        "tabla": "ARB_Predio",
                        "tabla_novedad": table_name,
                        "predio_ref": predio_ref,
                        "tipo_novedad": tipo_novedad,
                        "numero_predial_predio": numero_predial_predio,
                        "numero_predial_novedad": numero_predial_novedad,
                        "pos_22_predio": pos_22_predio,
                        "pos_22_novedad": pos_22_novedad,
                    },
                )
            )

    return issues

def _rule_8_6(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NovedadescoHelper(dataset)
    issues: list[RuleIssue] = []

    TIPOS_ENGLOBE = {
        "2",
        "3",
        "Englobe_Nuevo_FMI",
        "Englobe_Mantiene_FMI",
    }

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, predio in helper.iter_predio():
        predio_id = helper.get_field_value(predio, ("t_id", "TID", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for table_name, novedad in helper.iter_novedad_numero_predial():
        tipo_novedad = helper.get_field_value(novedad, ("tipo_novedad",))
        predio_ref = helper.get_field_value(
            novedad,
            ("arb_predio_novedad_numero_predial",),
        )

        if not tipo_novedad or str(tipo_novedad) not in TIPOS_ENGLOBE:
            continue

        predio = predios_by_id.get(str(predio_ref))
        if not predio:
            continue

        matricula = helper.get_field_value(
            predio,
            ("matricula_inmobiliaria", "Matricula_Inmobiliaria"),
        )

        if _matricula_vacia(matricula):
            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="8.6",
                    message=(
                        "Los predios asociados al englobe deben tener "
                        "folio de matrícula inmobiliaria."
                    ),
                    details={
                        "tabla": "ARB_Predio",
                        "tabla_novedad": table_name,
                        "predio_ref": predio_ref,
                        "tipo_novedad": tipo_novedad,
                        "matricula_inmobiliaria": matricula,
                    },
                )
            )

    return issues
    
def _rule_8_8(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NovedadescoHelper(dataset)
    issues: list[RuleIssue] = []

    TIPOS_ENGLOBE = {
        "2",
        "3",
        "Englobe_Nuevo_FMI",
        "Englobe_Mantiene_FMI",
    }

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, predio in helper.iter_predio():
        predio_id = helper.get_field_value(predio, ("t_id", "TID", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for table_name, novedad in helper.iter_novedad_numero_predial():
        tipo_novedad = helper.get_field_value(novedad, ("tipo_novedad",))
        predio_ref = helper.get_field_value(
            novedad,
            ("arb_predio_novedad_numero_predial",),
        )

        if not tipo_novedad or str(tipo_novedad) not in TIPOS_ENGLOBE:
            continue

        predio = predios_by_id.get(str(predio_ref))
        if not predio:
            continue

        numero_predial_predio = helper.get_field_value(
            predio,
            ("numero_predial",),
        )

        numero_predial_novedad = helper.get_field_value(
            novedad,
            ("numero_predial",),
        )

        pos_22_predio = _pos_22(numero_predial_predio)
        pos_22_novedad = _pos_22(numero_predial_novedad)

        if pos_22_predio == "2" or pos_22_novedad == "2":
            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="8.8",
                    message=(
                        "Todo predio asociado a una novedad de número predial "
                        "de tipo englobe no puede tener valor 2 en la posición "
                        "22 del número predial del predio ni de la novedad."
                    ),
                    details={
                        "tabla": "ARB_Predio",
                        "tabla_novedad": table_name,
                        "predio_ref": predio_ref,
                        "tipo_novedad": tipo_novedad,
                        "numero_predial_predio": numero_predial_predio,
                        "numero_predial_novedad": numero_predial_novedad,
                        "pos_22_predio": pos_22_predio,
                        "pos_22_novedad": pos_22_novedad,
                    },
                )
            )

    return issues

def _rule_8_11(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NovedadescoHelper(dataset)
    issues: list[RuleIssue] = []

    TIPOS_CANCELACION = {
        "Cancelacion",
        "Cancelacion_por_Englobe",
        "Cancelacion_por_Desenglobe",
    }

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, predio in helper.iter_predio():
        predio_id = helper.get_field_value(predio, ("t_id", "TID", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for table_name, novedad in helper.iter_novedad_numero_predial():
        tipo_novedad = helper.get_field_value(novedad, ("tipo_novedad",))

        if not tipo_novedad or str(tipo_novedad) not in TIPOS_CANCELACION:
            continue

        predio_ref = helper.get_field_value(
            novedad,
            ("arb_predio_novedad_numero_predial",),
        )

        predio = predios_by_id.get(str(predio_ref))
        if not predio:
            continue

        numero_predial_predio = helper.get_field_value(
            predio,
            ("numero_predial", "numero_predial_nacional"),
        )

        numero_predial_novedad = helper.get_field_value(
            novedad,
            ("numero_predial",),
        )

        pos_18_novedad = _pos_18(numero_predial_novedad)
        pos_22_novedad = _pos_22(numero_predial_novedad)

        # 8.11: en la NOVEDAD, posicion 18 debe ser numerica y distinta de 9;
        # posicion 22 debe ser distinta de 2.
        predio_es_nuevo = (
            pos_18_novedad is None
            or not pos_18_novedad.isdigit()
            or pos_18_novedad == "9"
        )
        predio_es_informal = pos_22_novedad == "2"

        if predio_es_nuevo or predio_es_informal:
            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="8.11",
                    message=(
                        "El número predial del predio que se cancela no debe "
                        "ser predio nuevo ni predio informal."
                    ),
                    details={
                        "tabla": "ARB_Predio",
                        "tabla_novedad": table_name,
                        "predio_ref": predio_ref,
                        "tipo_novedad": tipo_novedad,
                        "numero_predial_predio": numero_predial_predio,
                        "numero_predial_novedad": numero_predial_novedad,
                        "pos_18_novedad": pos_18_novedad,
                        "pos_22_novedad": pos_22_novedad,
                    },
                )
            )

    return issues

def _rule_8_12(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NovedadescoHelper(dataset)
    issues: list[RuleIssue] = []

    TIPOS_CANCELACION = {
        "Cancelacion",
        "Cancelacion_por_Englobe",
        "Cancelacion_por_Desenglobe",
    }

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, predio in helper.iter_predio():
        predio_id = helper.get_field_value(predio, ("t_id", "TID", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for table_name, novedad in helper.iter_novedad_numero_predial():
        tipo_novedad = helper.get_field_value(novedad, ("tipo_novedad",))

        if not tipo_novedad or str(tipo_novedad) not in TIPOS_CANCELACION:
            continue

        predio_ref = helper.get_field_value(
            novedad,
            ("arb_predio_novedad_numero_predial",),
        )

        predio = predios_by_id.get(str(predio_ref))
        if not predio:
            continue

        numero_predial_predio = helper.get_field_value(
            predio,
            ("numero_predial", "numero_predial_nacional"),
        )

        numero_predial_novedad = helper.get_field_value(
            novedad,
            ("numero_predial",),
        )

        if numero_predial_predio != numero_predial_novedad:
            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="8.12",
                    message=(
                        "El número predial del predio debe coincidir con el "
                        "número predial registrado en la novedad de número "
                        "predial asociada al proceso de cancelación."
                    ),
                    details={
                        "tabla": "ARB_Predio",
                        "tabla_novedad": table_name,
                        "predio_ref": predio_ref,
                        "tipo_novedad": tipo_novedad,
                        "numero_predial_predio": numero_predial_predio,
                        "numero_predial_novedad": numero_predial_novedad,
                    },
                )
            )

    return issues

def _rule_8_13(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NovedadescoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, predio in helper.iter_predio():
        predio_id = helper.get_field_value(predio, ("t_id", "TID", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for table_name, novedad in helper.iter_novedad_numero_predial():
        tipo_novedad = helper.get_field_value(novedad, ("tipo_novedad",))

        if str(tipo_novedad) != "Cancelacion":
            continue

        predio_ref = helper.get_field_value(
            novedad,
            ("arb_predio_novedad_numero_predial",),
        )

        predio = predios_by_id.get(str(predio_ref))
        if not predio:
            continue

        observaciones = helper.get_field_value(
            predio,
            ("observaciones", "Observaciones"),
        )

        if observaciones in (None, ""):
            numero_predial_predio = helper.get_field_value(
                predio,
                ("numero_predial", "numero_predial_nacional"),
            )

            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="8.13",
                    message=(
                        'El campo "observaciones" de la tabla predio no puede '
                        "estar vacío cuando el predio tiene una novedad de tipo "
                        "cancelación."
                    ),
                    details={
                        "tabla": "ARB_Predio",
                        "tabla_novedad": table_name,
                        "predio_ref": predio_ref,
                        "tipo_novedad": tipo_novedad,
                        "numero_predial_predio": numero_predial_predio,
                        "observaciones": observaciones,
                    },
                )
            )

    return issues

def _rule_8_14(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NovedadescoHelper(dataset)
    issues: list[RuleIssue] = []

    TIPOS_CANCELACION = {
        "Cancelacion",
        "Cancelacion_por_Englobe",
        "Cancelacion_por_Desenglobe",
    }

    predios_by_id: dict[str, dict[str, object]] = {}
    predios_con_terreno: set[str] = set()
    predios_con_construccion: set[str] = set()

    for _, predio in helper.iter_predio():
        predio_id = helper.get_field_value(predio, ("t_id", "TID", "id", "t_ili_tid"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for _, terreno in helper.iter_terreno():
        ref = helper.get_field_value(terreno, ("arb_predio", "predio", "baunit", "ilc_predio", "ue_baunit"))
        if ref:
            predios_con_terreno.add(str(ref))

    for _, construccion in helper.iter_construccion():
        ref = helper.get_field_value(construccion, ("arb_predio", "predio", "baunit", "ilc_predio", "ue_baunit"))
        if ref:
            predios_con_construccion.add(str(ref))

    for table_name, novedad in helper.iter_novedad_numero_predial():
        tipo_novedad = helper.get_field_value(novedad, ("tipo_novedad",))
        if not tipo_novedad or str(tipo_novedad) not in TIPOS_CANCELACION:
            continue

        predio_ref = helper.get_field_value(novedad, ("arb_predio_novedad_numero_predial",))
        predio = predios_by_id.get(str(predio_ref))
        if not predio:
            continue

        tiene_terreno = str(predio_ref) in predios_con_terreno
        tiene_construccion = str(predio_ref) in predios_con_construccion

        if tiene_terreno or tiene_construccion:
            issues.append(helper.make_issue(
                predio,
                rule_id="8.14",
                message="Los predios cancelados no deben tener informacion espacial.",
                details={
                    "tabla": "ARB_Predio",
                    "tabla_novedad": table_name,
                    "predio_ref": predio_ref,
                    "tipo_novedad": tipo_novedad,
                    "tiene_terreno": 1 if tiene_terreno else 0,
                    "tiene_construccion": 1 if tiene_construccion else 0,
                },
            ))

    return issues

def _rule_8_15(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NovedadescoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}
    numeros_prediales_existentes: set[str] = set()

    for _, predio in helper.iter_predio():
        predio_id = helper.get_field_value(predio, ("t_id", "TID", "id"))
        numero_predial = helper.get_field_value(
            predio,
            ("numero_predial", "numero_predial_nacional"),
        )

        if predio_id:
            predios_by_id[str(predio_id)] = predio

        if numero_predial:
            numeros_prediales_existentes.add(str(numero_predial))

    for table_name, novedad in helper.iter_novedad_numero_predial():
        tipo_novedad = helper.get_field_value(novedad, ("tipo_novedad",))

        if not tipo_novedad or not str(tipo_novedad).startswith("Cambio"):
            continue

        predio_ref = helper.get_field_value(
            novedad,
            ("arb_predio_novedad_numero_predial",),
        )

        predio = predios_by_id.get(str(predio_ref))
        if not predio:
            continue

        numero_predial_predio = helper.get_field_value(
            predio,
            ("numero_predial", "numero_predial_nacional"),
        )

        numero_predial_novedad = helper.get_field_value(
            novedad,
            ("numero_predial",),
        )

        mismo_numero = numero_predial_predio == numero_predial_novedad
        ya_existe_en_predio = numero_predial_novedad in numeros_prediales_existentes

        if mismo_numero or ya_existe_en_predio:
            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="8.15",
                    message=(
                        "El número predial del predio no puede coincidir con "
                        "el valor asignado en una novedad de tipo cambio, y el "
                        "número predial asociado a una novedad debe ser único y "
                        "no existir previamente en la tabla de predios."
                    ),
                    details={
                        "tabla": "ARB_Predio",
                        "tabla_novedad": table_name,
                        "predio_ref": predio_ref,
                        "tipo_novedad": tipo_novedad,
                        "numero_predial_predio": numero_predial_predio,
                        "numero_predial_novedad": numero_predial_novedad,
                        "mismo_numero": mismo_numero,
                        "ya_existe_en_predio": ya_existe_en_predio,
                    },
                )
            )

    return issues

def _rule_8_16(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NovedadescoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, predio in helper.iter_predio():
        predio_id = helper.get_field_value(predio, ("t_id", "TID", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for table_name, novedad in helper.iter_novedad_numero_predial():
        tipo_novedad = helper.get_field_value(novedad, ("tipo_novedad",))

        if not tipo_novedad or not str(tipo_novedad).startswith("Cambio"):
            continue

        predio_ref = helper.get_field_value(
            novedad,
            ("arb_predio_novedad_numero_predial",),
        )

        predio = predios_by_id.get(str(predio_ref))
        if not predio:
            continue

        numero_predial_predio = helper.get_field_value(
            predio,
            ("numero_predial", "numero_predial_nacional"),
        )

        numero_predial_novedad = helper.get_field_value(
            novedad,
            ("numero_predial",),
        )

        pos_18_novedad = _pos_18(numero_predial_novedad)
        pos_22_novedad = _pos_22(numero_predial_novedad)

        posicion_18_invalida = pos_18_novedad is None or not pos_18_novedad.isdigit()
        es_predio_informal = pos_22_novedad == "2"

        if posicion_18_invalida or es_predio_informal:
            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="8.16",
                    message=(
                        "El número predial registrado en la novedad de tipo "
                        "cambio no puede corresponder a un número predial nuevo "
                        "o a un predio informal."
                    ),
                    details={
                        "tabla": "ARB_Predio",
                        "tabla_novedad": table_name,
                        "predio_ref": predio_ref,
                        "tipo_novedad": tipo_novedad,
                        "numero_predial_predio": numero_predial_predio,
                        "numero_predial_novedad": numero_predial_novedad,
                        "pos_18_novedad": pos_18_novedad,
                        "pos_22_novedad": pos_22_novedad,
                    },
                )
            )

    return issues

def _rule_8_18(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NovedadescoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, predio in helper.iter_predio():
        predio_id = helper.get_field_value(predio, ("t_id", "TID", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for table_name, novedad in helper.iter_novedad_numero_predial():
        tipo_novedad = helper.get_field_value(novedad, ("tipo_novedad",))

        if not tipo_novedad or not str(tipo_novedad).startswith("Cambio"):
            continue

        predio_ref = helper.get_field_value(
            novedad,
            ("arb_predio_novedad_numero_predial",),
        )

        predio = predios_by_id.get(str(predio_ref))
        if not predio:
            continue

        numero_predial_predio = helper.get_field_value(
            predio,
            ("numero_predial", "numero_predial_nacional"),
        )

        pos_18 = _pos_18(numero_predial_predio)

        # 8.18 exige expresamente una letra A-Z en la posicion 18.
        es_predio_nuevo = bool(pos_18 and pos_18.isalpha())

        if not es_predio_nuevo:
            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="8.18",
                    message=(
                        "El número predial registrado en la tabla predio debe "
                        "representar un predio nuevo cuando esté vinculado a una "
                        "novedad de tipo cambio."
                    ),
                    details={
                        "tabla": "ARB_Predio",
                        "tabla_novedad": table_name,
                        "predio_ref": predio_ref,
                        "tipo_novedad": tipo_novedad,
                        "numero_predial_predio": numero_predial_predio,
                        "pos_18": pos_18,
                    },
                )
            )

    return issues

def _rule_8_19(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NovedadescoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, predio in helper.iter_predio():
        predio_id = helper.get_field_value(predio, ("t_id", "TID", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for table_name, novedad in helper.iter_novedad_numero_predial():
        tipo_novedad = helper.get_field_value(novedad, ("tipo_novedad",))

        if str(tipo_novedad) != "Predio_Nuevo":
            continue

        predio_ref = helper.get_field_value(
            novedad,
            ("arb_predio_novedad_numero_predial",),
        )

        predio = predios_by_id.get(str(predio_ref))
        if not predio:
            continue

        numero_predial_predio = helper.get_field_value(
            predio,
            ("numero_predial", "numero_predial_nacional"),
        )

        numero_predial_novedad = helper.get_field_value(
            novedad,
            ("numero_predial",),
        )

        if numero_predial_predio != numero_predial_novedad:
            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="8.19",
                    message=(
                        "El número predial registrado en la tabla predio debe "
                        "coincidir exactamente con el número predial registrado "
                        "en la novedad de número predial, cuando esta sea de tipo "
                        "Predio nuevo."
                    ),
                    details={
                        "tabla": "ARB_Predio",
                        "tabla_novedad": table_name,
                        "predio_ref": predio_ref,
                        "tipo_novedad": tipo_novedad,
                        "numero_predial_predio": numero_predial_predio,
                        "numero_predial_novedad": numero_predial_novedad,
                    },
                )
            )

    return issues

def _rule_8_20(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NovedadescoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, predio in helper.iter_predio():
        predio_id = helper.get_field_value(predio, ("t_id", "TID", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for table_name, novedad in helper.iter_novedad_numero_predial():
        tipo_novedad = helper.get_field_value(novedad, ("tipo_novedad",))

        if str(tipo_novedad) != "Predio_Nuevo":
            continue

        predio_ref = helper.get_field_value(
            novedad,
            ("arb_predio_novedad_numero_predial",),
        )

        predio = predios_by_id.get(str(predio_ref))
        if not predio:
            continue

        numero_predial_predio = helper.get_field_value(
            predio,
            ("numero_predial", "numero_predial_nacional"),
        )

        numero_predial_novedad = helper.get_field_value(
            novedad,
            ("numero_predial",),
        )

        pos_18_predio = _pos_18(numero_predial_predio)
        pos_18_novedad = _pos_18(numero_predial_novedad)

        if (
            not _is_predio_nuevo_pos_18(pos_18_predio)
            or not _is_predio_nuevo_pos_18(pos_18_novedad)
        ):
            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="8.20",
                    message=(
                        "Para predios con una novedad de tipo Predio nuevo, "
                        "el carácter en la posición 18 del número predial en "
                        "predio y en la novedad debe ser una letra de A a Z."
                    ),
                    details={
                        "tabla": "ARB_Predio",
                        "tabla_novedad": table_name,
                        "predio_ref": predio_ref,
                        "tipo_novedad": tipo_novedad,
                        "numero_predial_predio": numero_predial_predio,
                        "numero_predial_novedad": numero_predial_novedad,
                        "pos_18_predio": pos_18_predio,
                        "pos_18_novedad": pos_18_novedad,
                    },
                )
            )

    return issues

def _rule_8_22(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NovedadescoHelper(dataset)
    issues: list[RuleIssue] = []

    predios_by_id: dict[str, dict[str, object]] = {}

    for _, predio in helper.iter_predio():
        predio_id = helper.get_field_value(predio, ("t_id", "TID", "id"))
        if predio_id:
            predios_by_id[str(predio_id)] = predio

    for table_name, novedad in helper.iter_novedad_numero_predial():
        tipo_novedad = helper.get_field_value(novedad, ("tipo_novedad",))

        if str(tipo_novedad) != "Predio_Nuevo":
            continue

        predio_ref = helper.get_field_value(
            novedad,
            ("arb_predio_novedad_numero_predial",),
        )

        predio = predios_by_id.get(str(predio_ref))
        if not predio:
            continue

        numero_predial_predio = helper.get_field_value(
            predio,
            ("numero_predial", "numero_predial_nacional"),
        )

        numero_predial_novedad = helper.get_field_value(
            novedad,
            ("numero_predial",),
        )

        pos_22_novedad = _pos_22(numero_predial_novedad)

        if pos_22_novedad == "5":
            issues.append(
                helper.make_issue(
                    predio,
                    rule_id="8.22",
                    message=(
                        "Para predios con una novedad de tipo Predio nuevo, "
                        "el carácter en la posición 22 del número predial no "
                        "debe ser igual a 5, ya que este valor identifica una mejora."
                    ),
                    details={
                        "tabla": "ARB_Predio",
                        "tabla_novedad": table_name,
                        "predio_ref": predio_ref,
                        "tipo_novedad": tipo_novedad,
                        "numero_predial_predio": numero_predial_predio,
                        "numero_predial_novedad": numero_predial_novedad,
                        "pos_22_novedad": pos_22_novedad,
                    },
                )
            )

    return issues

def _rule_8_24(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NovedadescoHelper(dataset)
    issues: list[RuleIssue] = []

    conteo_cambios: dict[str, int] = {}
    muestra_por_numero: dict[str, tuple[str, dict[str, object]]] = {}

    for table_name, novedad in helper.iter_novedad_numero_predial():
        tipo_novedad = helper.get_field_value(novedad, ("tipo_novedad",))

        if not tipo_novedad or not str(tipo_novedad).startswith("Cambio"):
            continue

        numero_predial_novedad = helper.get_field_value(
            novedad,
            ("numero_predial",),
        )

        if not numero_predial_novedad:
            continue

        key = str(numero_predial_novedad)
        conteo_cambios[key] = conteo_cambios.get(key, 0) + 1
        muestra_por_numero.setdefault(key, (table_name, novedad))

    for numero_predial_novedad, conteo in conteo_cambios.items():
        if conteo <= 1:
            continue

        table_name, novedad = muestra_por_numero[numero_predial_novedad]

        issues.append(
            helper.make_issue(
                novedad,
                rule_id="8.24",
                message=(
                    'Un número predial no puede relacionar más de una vez '
                    'una novedad de "cambio de número predial".'
                ),
                details={
                    "tabla_novedad": table_name,
                    "numero_predial_novedad": numero_predial_novedad,
                    "tipo": "Cambio",
                    "conteo": conteo,
                },
            )
        )

    return issues

def _rule_8_26(dataset: DatasetReader) -> list[RuleIssue]:
    helper = NovedadescoHelper(dataset)
    issues: list[RuleIssue] = []

    resumen: dict[str, dict[str, int]] = {}
    muestra_por_numero: dict[str, tuple[str, dict[str, object]]] = {}

    for table_name, novedad in helper.iter_novedad_numero_predial():
        tipo_novedad = helper.get_field_value(novedad, ("tipo_novedad",))
        numero_predial_novedad = helper.get_field_value(
            novedad,
            ("numero_predial",),
        )

        if not numero_predial_novedad:
            continue

        key = str(numero_predial_novedad)

        if key not in resumen:
            resumen[key] = {
                "cancelacion": 0,
                "predionuevo": 0,
            }

        if tipo_novedad and str(tipo_novedad).startswith("Cancelacion"):
            resumen[key]["cancelacion"] += 1
            muestra_por_numero.setdefault(key, (table_name, novedad))

        if str(tipo_novedad) == "Predio_Nuevo":
            resumen[key]["predionuevo"] += 1
            muestra_por_numero.setdefault(key, (table_name, novedad))

    for numero_predial_novedad, valores in resumen.items():
        cancelacion = valores["cancelacion"]
        predionuevo = valores["predionuevo"]

        if cancelacion == 0 or predionuevo == 0:
            continue

        table_name, novedad = muestra_por_numero[numero_predial_novedad]

        issues.append(
            helper.make_issue(
                novedad,
                rule_id="8.26",
                message=(
                    'A un número predial no se le puede relacionar simultáneamente '
                    'una novedad de "Cancelación" y una novedad de "Predio nuevo".'
                ),
                details={
                    "tabla_novedad": table_name,
                    "numero_predial_novedad": numero_predial_novedad,
                    "cancelacion": cancelacion,
                    "predionuevo": predionuevo,
                },
            )
        )

    return issues


def _dedupe_issues(issues: list[RuleIssue]) -> list[RuleIssue]:
    """Elimina solo reportes exactamente repetidos de una misma infracción.

    Un mismo predio puede tener dos filas de novedad idénticas. Eso no convierte
    una matrícula faltante, por ejemplo, en dos errores distintos. Se conservan
    por separado los reportes cuyo mensaje, objeto o detalles sí sean diferentes.
    """
    unique: list[RuleIssue] = []
    seen: set[tuple[str, str | None, str, str]] = set()
    for issue in issues:
        try:
            details_key = json.dumps(issue.details or {}, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            details_key = repr(issue.details)
        key = (issue.rule_id, issue.object_ref, issue.message, details_key)
        if key in seen:
            continue
        seen.add(key)
        unique.append(issue)
    return unique


def _deduped(rule_function):
    def wrapped(dataset: DatasetReader) -> list[RuleIssue]:
        return _dedupe_issues(rule_function(dataset))
    wrapped.__name__ = getattr(rule_function, "__name__", "wrapped_rule")
    wrapped.__doc__ = getattr(rule_function, "__doc__", None)
    return wrapped


RULE_FUNCTIONS = {
    "8.1": _deduped(_rule_8_1),
    "8.3": _deduped(_rule_8_3),
    "8.6": _deduped(_rule_8_6),
    "8.8": _deduped(_rule_8_8),
    "8.11": _deduped(_rule_8_11),
    "8.12": _deduped(_rule_8_12),
    "8.13": _deduped(_rule_8_13),
    "8.14": _deduped(_rule_8_14),
    "8.15": _deduped(_rule_8_15),
    "8.16": _deduped(_rule_8_16),
    "8.18": _deduped(_rule_8_18),
    "8.19": _deduped(_rule_8_19),
    "8.20": _deduped(_rule_8_20),
    "8.22": _deduped(_rule_8_22),
    "8.24": _deduped(_rule_8_24),
    "8.26": _deduped(_rule_8_26),
}

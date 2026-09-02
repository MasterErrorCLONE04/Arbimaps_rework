from __future__ import annotations
from shapely.geometry import shape
from .base import DatasetReader, RuleIssue

import re

COMPONENT_SLUG = "estructura"

DEFAULT_RULE_IDS = frozenset({
    "9.1", "9.2", 
})


class EstructuraHelper:
    """Utilidades compartidas para reglas estructurales."""
    IDENTIFIER_FIELDS = (
        "t_ili_tid",
        "T_Ili_Tid",
        "T_ILI_TID",
        "id_operacion",
        "t_id",
        "TID",
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

CARACTERES_ESPECIALES_RE = re.compile(r'[\*\~\{\}\[\]¨\n\t]')

PIPE_RE = re.compile(r'\|')
#----------------------- reglas -----------------------

def _rule_9_1(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EstructuraHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, rows in dataset._tables.items():
        for row in rows:
            for campo, valor in row.items():
                if valor in (None, ""):
                    continue

                if not isinstance(valor, str):
                    continue

                if CARACTERES_ESPECIALES_RE.search(valor):
                    issues.append(
                        helper.make_issue(
                            row,
                            rule_id="9.1",
                            message=(
                                "Ningún campo de tipo String debe contener "
                                "caracteres especiales."
                            ),
                            details={
                                "tabla": table_name,
                                "campo": campo,
                                "valor": valor,
                                "caracteres_no_permitidos": "* ~ { } [ ] ¨ salto_de_linea tabulacion",
                            },
                        )
                    )

    return issues

def _rule_9_2(dataset: DatasetReader) -> list[RuleIssue]:
    helper = EstructuraHelper(dataset)
    issues: list[RuleIssue] = []

    for table_name, rows in dataset._tables.items():
        for row in rows:
            for campo, valor in row.items():
                if valor in (None, ""):
                    continue

                if not isinstance(valor, str):
                    continue

                if PIPE_RE.search(valor):
                    issues.append(
                        helper.make_issue(
                            row,
                            rule_id="9.2",
                            message=(
                                'Ningún campo de la base de datos puede contener "pipes" (|).'
                            ),
                            details={
                                "tabla": table_name,
                                "campo": campo,
                                "valor": valor,
                            },
                        )
                    )

    return issues
RULE_FUNCTIONS = {
    "9.1": _rule_9_1,
    "9.2": _rule_9_2,

}

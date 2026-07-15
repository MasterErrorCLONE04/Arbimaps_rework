from __future__ import annotations

import re
import unicodedata
from typing import Any


TID_FIELDS = (
    "TID",
    "t_ili_tid",
    "t_id",
)
OBJECT_ID_FIELDS = (
    *TID_FIELDS,
    "id_operacion",
    "id_predio",
    "predio_id",
    "id",
)
NPN_FIELDS = (
    "npn",
    "numero_predial",
    "numero_predial_nacional",
    "Numero_Predial",
    "Numero_Predial_Nacional",
)
PREDIO_TABLES = {"arbpredio", "ilcpredio"}

DIRECT_PREDIO_REFERENCE_FIELDS = {
    "predio",
    "arbpredio",
    "arbprediodireccion",
    "arbpredionovedadfmi",
    "arbpredionovedadnumeropredial",
    "arbpredioreferenciaregistralsistemaantiguo",
    "arbpredioavaluo",
    "ccapredioavaluo",
    "ilcpredioavaluo",
    "arbpredioterreno",
    "arbpredioconstruccion",
    "arbpredioderecho",
    "arbprediomarca",
    "arbprediounidadconstruccion",
}
PARENT_REFERENCE_FIELDS = {
    "construccion",
    "arbconstruccionunidadconstruccion",
    "arbterrenoadjunto",
    "arbunidadconstruccionadjunto",
    "arbpuntoreferenciaadjunto",
    "arbderechointersdfntefaadjunto",
    "arbderechointersdfnteiadjunto",
}
REVERSE_OWNED_REFERENCE_FIELDS = {
    "caracteristicasunidadconstruccion",
    "ilccaracteristicasunidadconstruccion",
}
UUID_TEXT = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
UUID_PATTERN = re.compile(rf"(?i)\b{UUID_TEXT}\b")


def _normalize_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch for ch in text if ch.isalnum())


def _clean_value(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text if text and text.lower() not in {"null", "none", "nan", "n/a", "na"} else ""


def _row_value(row: dict[str, Any], fields: tuple[str, ...] | set[str]) -> str:
    normalized_fields = {_normalize_key(field) for field in fields}
    for key, value in row.items():
        if _normalize_key(key) in normalized_fields:
            cleaned = _clean_value(value)
            if cleaned:
                return cleaned
    return ""


def _record_id(row: dict[str, Any]) -> str:
    return _row_value(row, OBJECT_ID_FIELDS)


def build_tid_lookup(
    tables: dict[str, list[dict[str, Any]]],
) -> dict[str, str]:
    """Relaciona los identificadores alternos de cada objeto con su TID."""
    lookup: dict[str, str] = {}
    alias_fields = {
        _normalize_key(field)
        for field in (*OBJECT_ID_FIELDS, *NPN_FIELDS)
    }

    for rows in tables.values():
        for row in rows:
            if not isinstance(row, dict):
                continue
            tid = _row_value(row, TID_FIELDS)
            if not tid:
                continue
            lookup.setdefault(tid, tid)
            for key, value in row.items():
                if _normalize_key(key) not in alias_fields:
                    continue
                alias = _clean_value(value)
                if alias:
                    lookup.setdefault(alias, tid)

    return lookup


def resolve_display_tid(value: object, lookup: dict[str, str]) -> str | None:
    cleaned = _clean_value(value)
    if not cleaned:
        return None
    return lookup.get(cleaned, cleaned)


def build_npn_lookup(
    tables: dict[str, list[dict[str, Any]]],
) -> dict[str, str]:
    """Relaciona los identificadores de cada objeto XTF con el NPN de su predio."""
    lookup: dict[str, str] = {}
    records: list[tuple[str, dict[str, Any], str]] = []

    for table_name, rows in tables.items():
        normalized_table = _normalize_key(table_name)
        for row in rows:
            if not isinstance(row, dict):
                continue
            object_id = _record_id(row)
            if not object_id:
                continue
            records.append((normalized_table, row, object_id))

            direct_npn = _row_value(row, NPN_FIELDS)
            if direct_npn and (
                normalized_table in PREDIO_TABLES
                or _normalize_key("npn") in {_normalize_key(key) for key in row}
            ):
                lookup[object_id] = direct_npn
                lookup.setdefault(direct_npn, direct_npn)

    max_passes = max(len(records), 1)
    for _ in range(max_passes):
        changed = False

        for _table_name, row, object_id in records:
            resolved_npn = lookup.get(object_id)

            if not resolved_npn:
                for key, value in row.items():
                    normalized_key = _normalize_key(key)
                    if normalized_key not in (
                        DIRECT_PREDIO_REFERENCE_FIELDS | PARENT_REFERENCE_FIELDS
                    ):
                        continue
                    reference = _clean_value(value)
                    if reference and reference in lookup:
                        resolved_npn = lookup[reference]
                        lookup[object_id] = resolved_npn
                        changed = True
                        break

            if not resolved_npn:
                continue

            for key, value in row.items():
                if _normalize_key(key) not in REVERSE_OWNED_REFERENCE_FIELDS:
                    continue
                child_reference = _clean_value(value)
                if child_reference and child_reference not in lookup:
                    lookup[child_reference] = resolved_npn
                    changed = True

        if not changed:
            break

    return lookup


def resolve_issue_npn(
    issue: dict[str, Any],
    lookup: dict[str, str],
) -> str:
    """Obtiene uno o varios NPN para un error usando sus IDs y relaciones."""
    details = issue.get("details")
    if not isinstance(details, dict):
        details = {}

    for source in (issue, details):
        direct_npn = _row_value(source, NPN_FIELDS)
        if direct_npn:
            return lookup.get(direct_npn, direct_npn)

    values: list[str] = []
    preferred_fields = (
        "predio",
        "predio_ref",
        "predio_id",
        "arb_predio",
        "ilc_predio",
        "object_ref",
        "object_id",
        "display_id",
        "tid",
        "t_id",
        "id_terreno",
        "id_construccion",
        "id_uconstruccion",
    )

    for source in (details, issue):
        for field in preferred_fields:
            value = _row_value(source, (field,))
            if value:
                values.append(value)

    for source in (issue, details):
        for value in source.values():
            cleaned = _clean_value(value)
            if cleaned:
                values.extend(UUID_PATTERN.findall(cleaned))

    npns: list[str] = []
    for value in values:
        npn = lookup.get(value)
        if npn and npn not in npns:
            npns.append(npn)

    return " | ".join(npns)


def annotate_ids_with_npns(message: object, lookup: dict[str, str]) -> str:
    """Conserva cada UUID y agrega a su lado el NPN relacionado."""
    text = str(message or "")
    return UUID_PATTERN.sub(
        lambda match: (
            f"{match.group(0)} (NPN: {lookup[match.group(0)]})"
            if match.group(0) in lookup
            else match.group(0)
        ),
        text,
    )


def attach_npns_to_errors(
    errors: list[dict[str, Any]],
    lookup: dict[str, str],
) -> None:
    for error in errors:
        if not isinstance(error, dict):
            continue
        error["npn"] = resolve_issue_npn(error, lookup)
        error["message"] = annotate_ids_with_npns(error.get("message"), lookup)

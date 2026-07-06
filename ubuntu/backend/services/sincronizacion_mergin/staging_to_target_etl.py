from __future__ import annotations

import re
import unicodedata
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json, RealDictCursor

from services.sincronizacion_mergin.connection import LocalPostgresConnectionService

SAFE_SCHEMA_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
FORBIDDEN_SCHEMAS = {"public", "information_schema", "pg_catalog", "pg_toast", "pg_temp"}
SYSTEM_TABLES = {
    "geometry_columns",
    "spatial_ref_sys",
    "geography_columns",
    "raster_columns",
    "raster_overviews",
    "system",
}
AUDIT_TABLE_NAME = "mergin_sync_audit_log"
REFERENCE_KEY_PREFERENCE = ("t_ili_tid", "ilicode")
DOMAIN_KEY_CANDIDATES = ("ilicode", "dispname", "description", "descripcion", "name", "nombre", "itfcode")
COLUMN_EQUIVALENCE_GROUPS = (
    ("geom", "geometry", "geometria", "localizacion"),
)
COLUMN_MATCH_STOPWORDS = {"de", "del", "la", "las", "el", "los", "the", "a"}

connection_service = LocalPostgresConnectionService()


@dataclass
class TablePlan:
    table_name: str
    common_columns: list[str]
    column_map: dict[str, str]
    missing_in_target: list[str]
    missing_in_staging: list[str]
    staging_count: int
    target_count: int
    key_column: str | None
    key_strategy: str | None
    foreign_keys: list[dict[str, str]]
    syncable: bool
    reasons: list[str]
    warnings: list[str]
    staging_geometry_columns: list[str]
    target_geometry_columns: list[str]


def run_staging_to_target_etl(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    staging_schema: str,
    target_schema: str,
    mode: str,
) -> dict[str, Any]:
    mode = str(mode or "").strip().lower()
    if mode not in {"dry_run", "apply"}:
        raise ValueError("mode debe ser 'dry_run' o 'apply'.")

    params = connection_service.build_params(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
    )
    staging_schema = _validate_schema_name(staging_schema, field_name="staging_schema")
    target_schema = _validate_schema_name(target_schema, field_name="target_schema")

    if staging_schema == target_schema:
        raise ValueError("staging_schema y target_schema no pueden ser iguales.")

    with psycopg2.connect(**params.as_connect_kwargs()) as conn:
        metadata = _load_metadata(
            conn=conn,
            staging_schema=staging_schema,
            target_schema=target_schema,
        )

    report = _build_report(
        params=params,
        metadata=metadata,
        staging_schema=staging_schema,
        target_schema=target_schema,
        mode=mode,
    )

    if mode == "apply":
        if report["critical_errors"]:
            report["ok"] = False
            report["message"] = (
                "No se aplico la transferencia porque el dry run detecto errores criticos."
            )
            return report

        _ensure_audit_table(params=params, target_schema=target_schema)
        apply_result = _apply_transfer(
            params=params,
            staging_schema=staging_schema,
            target_schema=target_schema,
            table_plans=metadata["table_plans"],
            simulation=report["simulation"],
        )
        report["apply_result"] = apply_result
        report["summary"].update(
            {
                "applied_tables": apply_result["applied_tables"],
                "inserted_records": apply_result["inserted_records"],
                "updated_records": apply_result["updated_records"],
                "unchanged_records": apply_result["unchanged_records"],
                "skipped_records": apply_result["skipped_records"],
            }
        )
        report["warnings"] = _dedupe_messages(report["warnings"] + apply_result["warnings"])
        report["message"] = "Transferencia aplicada exitosamente sobre el schema destino."

    return report


def _validate_schema_name(value: str, *, field_name: str) -> str:
    schema_name = str(value or "").strip()
    if not schema_name:
        raise ValueError(f"{field_name} es obligatorio.")
    if not SAFE_SCHEMA_RE.match(schema_name):
        raise ValueError(f"{field_name} no cumple el patron seguro permitido.")
    if schema_name.lower() in FORBIDDEN_SCHEMAS:
        raise ValueError(f"{field_name} usa un schema prohibido.")
    return schema_name


def _is_excluded_table(table_name: str) -> bool:
    lower_name = table_name.lower()
    return (
        lower_name in SYSTEM_TABLES
        or lower_name.startswith("t_ili2db_")
        or lower_name.endswith("tipo")
        or "adjunto" in lower_name
        or "foto" in lower_name
        or "document" in lower_name
    )


def _excluded_reason(table_name: str) -> str:
    lower_name = table_name.lower()
    if lower_name.startswith("t_ili2db_"):
        return "Tabla tecnica t_ili2db_* validada pero no sincronizada."
    if lower_name.endswith("tipo"):
        return "Dominio/catalogo conservado en target."
    if lower_name in SYSTEM_TABLES:
        return "Tabla de sistema excluida del ETL."
    return "Tabla excluida por regla de adjuntos/documentos."


def _load_metadata(*, conn, staging_schema: str, target_schema: str) -> dict[str, Any]:
    schemas = _fetch_schemas(conn=conn, schemas=[staging_schema, target_schema])
    if staging_schema not in schemas:
        raise ValueError(f"El staging_schema '{staging_schema}' no existe en la base de datos.")
    if target_schema not in schemas:
        raise ValueError(f"El target_schema '{target_schema}' no existe en la base de datos.")

    tables = _fetch_tables(conn=conn, schemas=[staging_schema, target_schema])
    columns = _fetch_columns(conn=conn, schemas=[staging_schema, target_schema])
    geometry_columns = _fetch_geometry_columns(conn=conn, schemas=[staging_schema, target_schema])
    uniques = _fetch_single_column_uniques(conn=conn, schemas=[staging_schema, target_schema])
    pks = _fetch_primary_keys(conn=conn, schemas=[staging_schema, target_schema])
    fks = _fetch_foreign_keys(conn=conn, schema=target_schema)
    counts = _fetch_row_counts(
        conn=conn,
        schema_tables={
            staging_schema: tables.get(staging_schema, []),
            target_schema: tables.get(target_schema, []),
        },
    )

    table_plans: list[TablePlan] = []
    excluded_plans: list[dict[str, Any]] = []
    common_tables = sorted(set(tables.get(staging_schema, [])) & set(tables.get(target_schema, [])))

    for table_name in sorted(set(tables.get(staging_schema, [])) | set(tables.get(target_schema, []))):
        if _is_excluded_table(table_name):
            excluded_plans.append(
                {
                    "table": table_name,
                    "reason": _excluded_reason(table_name),
                    "staging_count": counts.get((staging_schema, table_name), 0),
                    "target_count": counts.get((target_schema, table_name), 0),
                }
            )
            continue

        if table_name not in common_tables:
            continue

        staging_columns = columns.get((staging_schema, table_name), [])
        target_columns = columns.get((target_schema, table_name), [])
        staging_set = set(staging_columns)
        target_set = set(target_columns)

        column_map = _build_column_map(
            staging_columns=staging_columns,
            target_columns=target_columns,
            staging_geometry_columns=geometry_columns.get((staging_schema, table_name), []),
            target_geometry_columns=geometry_columns.get((target_schema, table_name), []),
        )
        mapped_target_columns = set(column_map.keys())
        mapped_staging_columns = set(column_map.values())

        common_columns = [c for c in target_columns if c in mapped_target_columns]
        missing_in_target = [c for c in staging_columns if c not in mapped_staging_columns]
        missing_in_staging = [c for c in target_columns if c not in mapped_target_columns]

        key_column, key_strategy = _select_key_column(
            staging_columns=staging_columns,
            target_columns=target_columns,
            staging_uniques=uniques.get((staging_schema, table_name), []),
            target_uniques=uniques.get((target_schema, table_name), []),
            target_pk=pks.get((target_schema, table_name), []),
        )

        reasons: list[str] = []
        warnings: list[str] = []
        syncable = True

        if not key_column:
            syncable = False
            reasons.append("No existe llave estable automatizable para upsert.")

        if not [c for c in common_columns if c != "t_id"]:
            syncable = False
            reasons.append("No hay columnas comunes suficientes para sincronizar.")

        if missing_in_target:
            warnings.append(f"Columnas presentes solo en staging: {', '.join(missing_in_target)}.")
        if missing_in_staging:
            warnings.append(f"Columnas presentes solo en target: {', '.join(missing_in_staging)}.")

        table_plans.append(
            TablePlan(
                table_name=table_name,
                common_columns=common_columns,
                column_map=column_map,
                missing_in_target=missing_in_target,
                missing_in_staging=missing_in_staging,
                staging_count=counts.get((staging_schema, table_name), 0),
                target_count=counts.get((target_schema, table_name), 0),
                key_column=key_column,
                key_strategy=key_strategy,
                foreign_keys=[fk for fk in fks if fk["table_name"] == table_name],
                syncable=syncable,
                reasons=reasons,
                warnings=warnings,
                staging_geometry_columns=geometry_columns.get((staging_schema, table_name), []),
                target_geometry_columns=geometry_columns.get((target_schema, table_name), []),
            )
        )

    staging_tables = set(tables.get(staging_schema, []))
    target_tables = set(tables.get(target_schema, []))
    staging_only_table_plans = [
        {
            "table": table_name,
            "reason": "Existe solo en staging; no hay tabla homologa en target para ETL.",
            "staging_count": counts.get((staging_schema, table_name), 0),
            "target_count": 0,
        }
        for table_name in sorted(staging_tables - target_tables)
        if not _is_excluded_table(table_name)
    ]
    target_only_table_plans = [
        {
            "table": table_name,
            "reason": "Existe solo en target; no llego desde staging en esta corrida.",
            "staging_count": 0,
            "target_count": counts.get((target_schema, table_name), 0),
        }
        for table_name in sorted(target_tables - staging_tables)
        if not _is_excluded_table(table_name)
    ]

    return {
        "table_plans": table_plans,
        "excluded_table_plans": excluded_plans,
        "staging_only_table_plans": staging_only_table_plans,
        "target_only_table_plans": target_only_table_plans,
        "technical_validation": [
            {
                "table": n,
                "staging_count": counts.get((staging_schema, n), 0),
                "target_count": counts.get((target_schema, n), 0),
                "action": "validate_only",
            }
            for n in ("t_ili2db_dataset", "t_ili2db_basket")
        ],
    }


def _fetch_schemas(*, conn, schemas: list[str]) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = ANY(%s)",
            (schemas,),
        )
        return {str(row[0]).strip() for row in (cur.fetchall() or []) if row and row[0]}


def _fetch_tables(*, conn, schemas: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = ANY(%s)
              AND table_type = 'BASE TABLE'
            ORDER BY table_schema, table_name
            """,
            (schemas,),
        )
        for row in cur.fetchall() or []:
            result[str(row["table_schema"])].append(str(row["table_name"]))
    return result


def _fetch_columns(*, conn, schemas: list[str]) -> dict[tuple[str, str], list[str]]:
    result: dict[tuple[str, str], list[str]] = defaultdict(list)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT table_schema, table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = ANY(%s)
            ORDER BY table_schema, table_name, ordinal_position
            """,
            (schemas,),
        )
        for row in cur.fetchall() or []:
            result[(str(row["table_schema"]), str(row["table_name"]))].append(str(row["column_name"]))
    return result



def _fetch_geometry_columns(*, conn, schemas: list[str]) -> dict[tuple[str, str], list[str]]:
    result: dict[tuple[str, str], list[str]] = defaultdict(list)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT table_schema, table_name, column_name
            FROM (
                SELECT
                    f_table_schema AS table_schema,
                    f_table_name AS table_name,
                    f_geometry_column AS column_name,
                    0 AS source_priority
                FROM geometry_columns
                WHERE f_table_schema = ANY(%s)

                UNION ALL

                SELECT
                    table_schema,
                    table_name,
                    column_name,
                    1 AS source_priority
                FROM information_schema.columns
                WHERE table_schema = ANY(%s)
                  AND udt_name IN ('geometry', 'geography')
            ) spatial_columns
            ORDER BY table_schema, table_name, source_priority, column_name
            """,
            (schemas, schemas),
        )
        for row in cur.fetchall() or []:
            key = (str(row["table_schema"]), str(row["table_name"]))
            column_name = str(row["column_name"])
            if column_name not in result[key]:
                result[key].append(column_name)
    return result
def _fetch_row_counts(*, conn, schema_tables: dict[str, list[str]]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    with conn.cursor() as cur:
        for schema_name, table_names in schema_tables.items():
            for table_name in table_names:
                cur.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                        sql.Identifier(schema_name),
                        sql.Identifier(table_name),
                    )
                )
                counts[(schema_name, table_name)] = int((cur.fetchone() or [0])[0] or 0)
    return counts


def _fetch_primary_keys(*, conn, schemas: list[str]) -> dict[tuple[str, str], list[str]]:
    result: dict[tuple[str, str], list[str]] = defaultdict(list)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT tc.table_schema, tc.table_name, kcu.column_name, kcu.ordinal_position
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.constraint_schema = kcu.constraint_schema
            WHERE tc.table_schema = ANY(%s)
              AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY tc.table_schema, tc.table_name, kcu.ordinal_position
            """,
            (schemas,),
        )
        for row in cur.fetchall() or []:
            result[(str(row["table_schema"]), str(row["table_name"]))].append(str(row["column_name"]))
    return result


def _fetch_single_column_uniques(*, conn, schemas: list[str]) -> dict[tuple[str, str], list[str]]:
    result: dict[tuple[str, str], list[str]] = defaultdict(list)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT tc.table_schema, tc.table_name, tc.constraint_name
            FROM information_schema.table_constraints tc
            WHERE tc.table_schema = ANY(%s)
              AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')
            ORDER BY tc.table_schema, tc.table_name, tc.constraint_name
            """,
            (schemas,),
        )
        constraints = cur.fetchall() or []

        for row in constraints:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.key_column_usage
                WHERE constraint_schema = %s
                  AND constraint_name = %s
                ORDER BY ordinal_position
                """,
                (row["table_schema"], row["constraint_name"]),
            )
            constraint_columns = [
                str(item["column_name"])
                for item in (cur.fetchall() or [])
                if item and item.get("column_name")
            ]
            if len(constraint_columns) == 1:
                result[(str(row["table_schema"]), str(row["table_name"]))].append(constraint_columns[0])
    return result


def _fetch_foreign_keys(*, conn, schema: str) -> list[dict[str, str]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                tc.table_name,
                kcu.column_name,
                ccu.table_schema AS referenced_schema,
                ccu.table_name AS referenced_table,
                ccu.column_name AS referenced_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.constraint_schema = kcu.constraint_schema
            JOIN information_schema.constraint_column_usage ccu
              ON tc.constraint_name = ccu.constraint_name
             AND tc.constraint_schema = ccu.constraint_schema
            WHERE tc.table_schema = %s
              AND tc.constraint_type = 'FOREIGN KEY'
            ORDER BY tc.table_name, kcu.column_name
            """,
            (schema,),
        )
        return [
            {
                "table_name": str(row["table_name"]),
                "column_name": str(row["column_name"]),
                "referenced_schema": str(row["referenced_schema"]),
                "referenced_table": str(row["referenced_table"]),
                "referenced_column": str(row["referenced_column"]),
            }
            for row in (cur.fetchall() or [])
        ]


def _find_column_case_insensitive(columns: list[str], candidate: str) -> str | None:
    lowered = candidate.lower()
    for column in columns:
        if str(column).lower() == lowered:
            return column
    return None


def _normalize_reference_key_value(value: Any) -> Any:
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        return normalized.casefold()
    return value


def _normalize_column_name_for_match(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    parts = [
        part
        for part in re.split(r"[^a-z0-9]+", text)
        if part and part not in COLUMN_MATCH_STOPWORDS
    ]
    return "".join(parts)


def _build_column_map(
    *,
    staging_columns: list[str],
    target_columns: list[str],
    staging_geometry_columns: list[str] | None = None,
    target_geometry_columns: list[str] | None = None,
) -> dict[str, str]:
    staging_set = set(staging_columns)
    staging_by_normalized: dict[str, list[str]] = defaultdict(list)
    for staging_column in staging_columns:
        staging_by_normalized[_normalize_column_name_for_match(staging_column)].append(staging_column)

    column_map: dict[str, str] = {}

    geometry_pairs = _pair_geometry_columns(
        staging_columns=staging_columns,
        target_columns=target_columns,
        staging_geometry_columns=staging_geometry_columns or [],
        target_geometry_columns=target_geometry_columns or [],
    )
    column_map.update(geometry_pairs)

    for target_column in target_columns:
        if target_column in column_map:
            continue
        if target_column in staging_set:
            column_map[target_column] = target_column
            continue

        target_lower = target_column.lower()
        for group in COLUMN_EQUIVALENCE_GROUPS:
            if target_lower not in group:
                continue
            for candidate in group:
                actual_staging = _find_column_case_insensitive(staging_columns, candidate)
                if actual_staging:
                    column_map[target_column] = actual_staging
                    break
            if target_column in column_map:
                break

        if target_column in column_map:
            continue

        normalized_target = _normalize_column_name_for_match(target_column)
        candidates = [
            candidate
            for candidate in staging_by_normalized.get(normalized_target, [])
            if candidate not in column_map.values()
        ]
        if len(candidates) == 1:
            column_map[target_column] = candidates[0]

    return column_map

def _pair_geometry_columns(
    *,
    staging_columns: list[str],
    target_columns: list[str],
    staging_geometry_columns: list[str],
    target_geometry_columns: list[str],
) -> dict[str, str]:
    if not staging_geometry_columns or not target_geometry_columns:
        return {}

    target_by_lower = {column.lower(): column for column in target_columns}
    staging_by_lower = {column.lower(): column for column in staging_columns}
    remaining_staging = {
        staging_by_lower[column.lower()]
        for column in staging_geometry_columns
        if column.lower() in staging_by_lower
    }
    remaining_target = {
        target_by_lower[column.lower()]
        for column in target_geometry_columns
        if column.lower() in target_by_lower
    }
    pairs: dict[str, str] = {}

    def assign(target_column: str, staging_column: str) -> None:
        if target_column in remaining_target and staging_column in remaining_staging:
            pairs[target_column] = staging_column
            remaining_target.remove(target_column)
            remaining_staging.remove(staging_column)

    for target_column in list(remaining_target):
        staging_column = staging_by_lower.get(target_column.lower())
        if staging_column:
            assign(target_column, staging_column)

    for target_column in list(remaining_target):
        target_lower = target_column.lower()
        for group in COLUMN_EQUIVALENCE_GROUPS:
            if target_lower not in group:
                continue
            for candidate in group:
                staging_column = staging_by_lower.get(candidate)
                if staging_column:
                    assign(target_column, staging_column)
                    break
            if target_column in pairs:
                break

    if len(remaining_target) == 1 and len(remaining_staging) == 1:
        assign(next(iter(remaining_target)), next(iter(remaining_staging)))

    return pairs


def _select_key_column(
    *,
    staging_columns: list[str],
    target_columns: list[str],
    staging_uniques: list[str],
    target_uniques: list[str],
    target_pk: list[str],
) -> tuple[str | None, str | None]:
    staging_set = set(staging_columns)
    target_set = set(target_columns)

    for candidate in REFERENCE_KEY_PREFERENCE:
        actual = _find_column_case_insensitive(staging_columns, candidate)
        if actual and actual in target_set:
            return actual, candidate

    common_uniques = [
        col for col in target_uniques
        if col in staging_set and col in staging_uniques and col != "t_id"
    ]
    if common_uniques:
        return common_uniques[0], "single_unique"

    if len(target_pk) == 1 and target_pk[0] in staging_set and target_pk[0] != "t_id":
        return target_pk[0], "single_primary_key"

    return None, None


def _build_report(
    *,
    params,
    metadata: dict[str, Any],
    staging_schema: str,
    target_schema: str,
    mode: str,
) -> dict[str, Any]:
    table_plans: list[TablePlan] = metadata["table_plans"]
    simulation = _simulate_transfer(
        params=params,
        table_plans=table_plans,
        staging_schema=staging_schema,
        target_schema=target_schema,
    )
    sim_by_table = {item["table"]: item for item in simulation["tables"]}

    tables = []
    warnings: list[str] = []
    critical_errors: list[str] = []

    inserts_estimated = 0
    updates_estimated = 0
    unchanged_records = 0
    nonsyncable_records = 0
    syncable_tables = 0
    nonsyncable_tables = 0

    for plan in table_plans:
        sim = sim_by_table.get(plan.table_name, {})
        structural_errors = _dedupe_messages(plan.reasons or [])
        table_warnings = _dedupe_messages((plan.warnings or []) + (sim.get("warnings") or []))
        row_level_errors = _dedupe_messages(sim.get("critical_errors") or [])
        table_syncable = plan.syncable and not structural_errors

        syncable_tables += 1 if table_syncable else 0
        nonsyncable_tables += 0 if table_syncable else 1

        inserts_estimated += int(sim.get("insertable_records") or 0)
        updates_estimated += int(sim.get("updatable_records") or 0)
        unchanged_records += int(sim.get("unchanged_records") or 0)
        nonsyncable_records += int(sim.get("nonsyncable_records") or 0)

        warnings.extend(table_warnings)
        warnings.extend(row_level_errors)
        critical_errors.extend(structural_errors)

        tables.append(
            {
                "table": plan.table_name,
                "syncable": table_syncable,
                "key_column": plan.key_column,
                "key_strategy": plan.key_strategy,
                "staging_count": plan.staging_count,
                "target_count": plan.target_count,
                "common_columns": plan.common_columns,
                "missing_in_target": plan.missing_in_target,
                "missing_in_staging": plan.missing_in_staging,
                "foreign_keys": plan.foreign_keys,
                "insertable_records": int(sim.get("insertable_records") or 0),
                "updatable_records": int(sim.get("updatable_records") or 0),
                "unchanged_records": int(sim.get("unchanged_records") or 0),
                "nonsyncable_records": int(sim.get("nonsyncable_records") or 0),
                "critical_errors": structural_errors,
                "warnings": _dedupe_messages(table_warnings + row_level_errors),
            }
        )

    all_critical_errors = _dedupe_messages(critical_errors)
    schema_presence_warnings = []
    if metadata["staging_only_table_plans"]:
        schema_presence_warnings.append(
            "Tablas solo en staging: "
            + ", ".join(item["table"] for item in metadata["staging_only_table_plans"])
            + "."
        )
    if metadata["target_only_table_plans"]:
        schema_presence_warnings.append(
            "Tablas solo en target: "
            + ", ".join(item["table"] for item in metadata["target_only_table_plans"])
            + "."
        )
    all_warnings = _dedupe_messages(
        schema_presence_warnings + warnings + simulation["warnings"] + simulation["critical_errors"]
    )

    return {
        "ok": not all_critical_errors,
        "mode": mode,
        "staging_schema": staging_schema,
        "target_schema": target_schema,
        "message": "Simulacion ETL completada." if mode == "dry_run" else "Transferencia ETL lista para aplicar.",
        "tables": tables,
        "excluded_tables": metadata["excluded_table_plans"],
        "staging_only_tables": metadata["staging_only_table_plans"],
        "target_only_tables": metadata["target_only_table_plans"],
        "technical_validation": metadata["technical_validation"],
        "simulation": simulation,
        "warnings": all_warnings,
        "critical_errors": all_critical_errors,
        "summary": {
            "syncable_tables": syncable_tables,
            "nonsyncable_tables": nonsyncable_tables,
            "excluded_tables": len(metadata["excluded_table_plans"]),
            "staging_only_tables": len(metadata["staging_only_table_plans"]),
            "target_only_tables": len(metadata["target_only_table_plans"]),
            "inserts_estimated": inserts_estimated,
            "updates_estimated": updates_estimated,
            "unchanged_records": unchanged_records,
            "nonsyncable_records": nonsyncable_records,
            "critical_errors": len(all_critical_errors),
            "warnings": len(all_warnings),
            "applied_tables": 0,
            "inserted_records": 0,
            "updated_records": 0,
            "skipped_records": nonsyncable_records,
        },
    }


def _simulate_transfer(
    *,
    params,
    table_plans: list[TablePlan],
    staging_schema: str,
    target_schema: str,
) -> dict[str, Any]:
    ordered = _order_table_plans(table_plans)
    if not ordered:
        return {
            "tables": [],
            "warnings": [],
            "critical_errors": ["No se encontraron tablas operativas comunes entre staging y target."],
        }

    warnings: list[str] = []
    critical_errors: list[str] = []
    tables = []

    with psycopg2.connect(**params.as_connect_kwargs()) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            runtime = _prepare_runtime(
                cur=cur,
                table_plans=ordered,
                staging_schema=staging_schema,
                target_schema=target_schema,
            )
            for plan in ordered:
                row = _process_table(
                    cur=cur,
                    plan=plan,
                    target_schema=target_schema,
                    runtime=runtime,
                    apply_changes=False,
                )
                warnings.extend(row["warnings"])
                critical_errors.extend(row["critical_errors"])
                tables.append(row)

    return {
        "tables": tables,
        "warnings": _dedupe_messages(warnings),
        "critical_errors": _dedupe_messages(critical_errors),
    }


def _apply_transfer(
    *,
    params,
    staging_schema: str,
    target_schema: str,
    table_plans: list[TablePlan],
    simulation: dict[str, Any],
) -> dict[str, Any]:
    ordered = _order_table_plans(table_plans)
    result = {
        "applied_tables": 0,
        "inserted_records": 0,
        "updated_records": 0,
        "unchanged_records": 0,
        "skipped_records": 0,
        "warnings": [],
    }

    with psycopg2.connect(**params.as_connect_kwargs()) as conn:
        conn.autocommit = False
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                    (target_schema, staging_schema),
                )
                runtime = _prepare_runtime(
                    cur=cur,
                    table_plans=ordered,
                    staging_schema=staging_schema,
                    target_schema=target_schema,
                )

                for plan in ordered:
                    table_result = _process_table(
                        cur=cur,
                        plan=plan,
                        target_schema=target_schema,
                        runtime=runtime,
                        apply_changes=True,
                    )
                    result["applied_tables"] += 1
                    result["inserted_records"] += table_result["insertable_records"]
                    result["updated_records"] += table_result["updatable_records"]
                    result["unchanged_records"] += table_result["unchanged_records"]
                    result["skipped_records"] += table_result["nonsyncable_records"]
                    result["warnings"].extend(table_result["warnings"])

            conn.commit()
            _write_audit_log(
                params=params,
                target_schema=target_schema,
                staging_schema=staging_schema,
                status="success",
                payload={
                    "summary": result,
                    "simulation_summary": simulation.get("tables", []),
                },
            )
        except Exception as exc:
            conn.rollback()
            _write_audit_log(
                params=params,
                target_schema=target_schema,
                staging_schema=staging_schema,
                status="failed",
                payload={"error": str(exc)},
            )
            raise

    result["warnings"] = _dedupe_messages(result["warnings"])
    return result


def _ensure_audit_table(*, params, target_schema: str) -> None:
    with psycopg2.connect(**params.as_connect_kwargs()) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.{} (
                        id BIGSERIAL PRIMARY KEY,
                        executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        staging_schema TEXT NOT NULL,
                        target_schema TEXT NOT NULL,
                        status TEXT NOT NULL,
                        payload JSONB NOT NULL
                    )
                    """
                ).format(
                    sql.Identifier(target_schema),
                    sql.Identifier(AUDIT_TABLE_NAME),
                )
            )


def _write_audit_log(
    *,
    params,
    target_schema: str,
    staging_schema: str,
    status: str,
    payload: dict[str, Any],
) -> None:
    with psycopg2.connect(**params.as_connect_kwargs()) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "INSERT INTO {}.{} (staging_schema, target_schema, status, payload) VALUES (%s, %s, %s, %s)"
                ).format(
                    sql.Identifier(target_schema),
                    sql.Identifier(AUDIT_TABLE_NAME),
                ),
                (staging_schema, target_schema, status, Json(payload)),
            )


def _order_table_plans(table_plans: list[TablePlan]) -> list[TablePlan]:
    syncable = [plan for plan in table_plans if plan.syncable]
    by_name = {plan.table_name: plan for plan in syncable}
    deps = {plan.table_name: set() for plan in syncable}
    rev = {plan.table_name: set() for plan in syncable}

    for plan in syncable:
        for fk in plan.foreign_keys:
            ref = fk["referenced_table"]
            if ref in by_name and ref != plan.table_name:
                deps[plan.table_name].add(ref)
                rev[ref].add(plan.table_name)

    queue = deque(sorted(name for name, values in deps.items() if not values))
    ordered: list[TablePlan] = []

    while queue:
        name = queue.popleft()
        ordered.append(by_name[name])
        for dependent in sorted(rev[name]):
            deps[dependent].discard(name)
            if not deps[dependent]:
                queue.append(dependent)

    ordered_names = {plan.table_name for plan in ordered}
    ordered.extend(
        sorted(
            (plan for plan in syncable if plan.table_name not in ordered_names),
            key=lambda item: item.table_name,
        )
    )
    return ordered


def _prepare_runtime(
    *,
    cur,
    table_plans: list[TablePlan],
    staging_schema: str,
    target_schema: str,
) -> dict[str, Any]:
    runtime = {
        "staging_rows": {},
        "target_rows_by_key": {},
        "target_rows_by_match_key": {},
        "reference_maps": {},
        "required_insert_columns": {},
        "cur": cur,  # Exponer el cursor para operaciones ad-hoc
        "staging_schema": staging_schema,
        "target_schema": target_schema,
    }

    needed_refs = {
        fk["referenced_table"]
        for plan in table_plans
        for fk in plan.foreign_keys
        if fk["referenced_schema"] == target_schema and fk["referenced_column"] == "t_id"
    }
    ref_keys = {plan.table_name: plan.key_column for plan in table_plans if plan.key_column}

    all_tables_for_mapping = sorted(set(ref_keys.keys()) | needed_refs)

    for table_name in all_tables_for_mapping:
        key_column = ref_keys.get(table_name) or _resolve_reference_key(
            cur=cur,
            staging_schema=staging_schema,
            target_schema=target_schema,
            table_name=table_name,
        )
        if not key_column:
            continue

        staging_index = _fetch_reference_index(
            cur=cur,
            schema_name=staging_schema,
            table_name=table_name,
            key_column=key_column,
        )
        target_index = _fetch_reference_index(
            cur=cur,
            schema_name=target_schema,
            table_name=table_name,
            key_column=key_column,
        )

        runtime["reference_maps"][table_name] = {
            "key_column": key_column,
            "staging_by_t_id": staging_index["by_t_id"],
            "target_by_key": target_index["by_key"],
        }

    for plan in table_plans:
        runtime["staging_rows"][plan.table_name] = _fetch_rows(
            cur=cur,
            schema_name=staging_schema,
            table_name=plan.table_name,
            columns=plan.common_columns,
            column_map=plan.column_map,
        )
        if plan.key_column:
            runtime["target_rows_by_key"][plan.table_name] = _fetch_target_rows_by_key(
                cur=cur,
                schema_name=target_schema,
                table_name=plan.table_name,
                key_column=plan.key_column,
                columns=plan.common_columns,
            )
        runtime["target_rows_by_match_key"][plan.table_name] = _fetch_target_rows_by_match_key(
            cur=cur,
            schema_name=target_schema,
            table_name=plan.table_name,
            columns=plan.common_columns,
        )
        runtime["required_insert_columns"][plan.table_name] = _fetch_required_insert_columns(
            cur=cur,
            schema_name=target_schema,
            table_name=plan.table_name,
        )

    return runtime
def _resolve_reference_key(
    *,
    cur,
    staging_schema: str,
    target_schema: str,
    table_name: str,
) -> str | None:
    # Regla especial para tablas de dominio/catálogo (*tipo)
    if table_name.endswith("tipo"):
        staging_columns = _fetch_table_column_list(
            cur=cur, schema_name=staging_schema, table_name=table_name
        )
        target_columns = _fetch_table_column_list(
            cur=cur, schema_name=target_schema, table_name=table_name
        )
        target_set = set(target_columns)

        for candidate in DOMAIN_KEY_CANDIDATES:
            actual = _find_column_case_insensitive(staging_columns, candidate)
            if actual and actual in target_set:
                return actual  # No se requiere que sea UNIQUE

    # Lógica original para tablas operativas y otras
    staging_columns = _fetch_table_column_list(
        cur=cur,
        schema_name=staging_schema,
        table_name=table_name,
    )
    target_columns = _fetch_table_column_list(
        cur=cur,
        schema_name=target_schema,
        table_name=table_name,
    )
    if not staging_columns or not target_columns:
        return None

    return _select_key_column(
        staging_columns=staging_columns,
        target_columns=target_columns,
        staging_uniques=_fetch_single_unique_columns_for_table(
            cur=cur,
            schema_name=staging_schema,
            table_name=table_name,
        ),
        target_uniques=_fetch_single_unique_columns_for_table(
            cur=cur,
            schema_name=target_schema,
            table_name=table_name,
        ),
        target_pk=_fetch_primary_key_for_table(
            cur=cur,
            schema_name=target_schema,
            table_name=table_name,
        ),
    )[0]


def _fetch_table_column_list(*, cur, schema_name: str, table_name: str) -> list[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema_name, table_name),
    )
    return [
        str(row["column_name"])
        for row in (cur.fetchall() or [])
        if row and row.get("column_name")
    ]


def _fetch_required_insert_columns(*, cur, schema_name: str, table_name: str) -> list[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
          AND is_nullable = 'NO'
          AND column_default IS NULL
          AND COALESCE(is_identity, 'NO') = 'NO'
          AND column_name <> 't_id'
        ORDER BY ordinal_position
        """,
        (schema_name, table_name),
    )
    return [
        str(row["column_name"])
        for row in (cur.fetchall() or [])
        if row and row.get("column_name")
    ]


def _fetch_single_unique_columns_for_table(*, cur, schema_name: str, table_name: str) -> list[str]:
    cur.execute(
        """
        SELECT tc.constraint_name
        FROM information_schema.table_constraints tc
        WHERE tc.table_schema = %s
          AND tc.table_name = %s
          AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')
        """,
        (schema_name, table_name),
    )
    constraints = cur.fetchall() or []

    result: list[str] = []
    for row in constraints:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.key_column_usage
            WHERE constraint_schema = %s
              AND constraint_name = %s
            ORDER BY ordinal_position
            """,
            (schema_name, row["constraint_name"]),
        )
        constraint_columns = [
            str(item["column_name"])
            for item in (cur.fetchall() or [])
            if item and item.get("column_name")
        ]
        if len(constraint_columns) == 1:
            result.append(constraint_columns[0])
    return result


def _fetch_primary_key_for_table(*, cur, schema_name: str, table_name: str) -> list[str]:
    cur.execute(
        """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.constraint_schema = kcu.constraint_schema
        WHERE tc.table_schema = %s
          AND tc.table_name = %s
          AND tc.constraint_type = 'PRIMARY KEY'
        ORDER BY kcu.ordinal_position
        """,
        (schema_name, table_name),
    )
    return [
        str(row["column_name"])
        for row in (cur.fetchall() or [])
        if row and row.get("column_name")
    ]


def _fetch_rows(
    *,
    cur,
    schema_name: str,
    table_name: str,
    columns: list[str],
    column_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if not columns:
        return []

    column_map = column_map or {column: column for column in columns}
    select_list = []
    for target_column in columns:
        source_column = column_map.get(target_column, target_column)
        if source_column == target_column:
            select_list.append(sql.Identifier(source_column))
        else:
            select_list.append(
                sql.SQL("{} AS {}").format(
                    sql.Identifier(source_column),
                    sql.Identifier(target_column),
                )
            )

    cur.execute(
        sql.SQL("SELECT {} FROM {}.{}").format(
            sql.SQL(", ").join(select_list),
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
        )
    )
    return [dict(row) for row in (cur.fetchall() or [])]


def _normalize_business_match_value(value: Any) -> Any:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized.casefold() if normalized else None
    return value


def _build_business_match_key(table_name: str, row: dict[str, Any]) -> tuple[Any, ...] | None:
    if table_name != "arb_direccion":
        return None

    columns = (
        "arb_predio_direccion",
        "tipo_direccion",
        "es_direccion_principal",
        "complemento",
        "nombre_predio",
        "codigo_postal",
        "clase_via_principal",
        "valor_via_principal",
        "letra_via_principal",
        "letra_via_generadora",
        "sector_ciudad",
        "valor_via_generadora",
        "numero_predio",
        "sector_predio",
    )
    values = tuple(_normalize_business_match_value(row.get(column)) for column in columns)
    if values[0] is None:
        return None
    if not any(value is not None for value in values[1:]):
        return None
    return values


def _fetch_target_rows_by_key(
    *,
    cur,
    schema_name: str,
    table_name: str,
    key_column: str,
    columns: list[str],
) -> dict[Any, dict[str, Any]]:
    rows = _fetch_rows(
        cur=cur,
        schema_name=schema_name,
        table_name=table_name,
        columns=columns,
    )
    result: dict[Any, dict[str, Any]] = {}
    for row in rows:
        raw_key = row.get(key_column)
        normalized_key = _normalize_reference_key_value(raw_key)
        if normalized_key is None:
            continue
        result[normalized_key] = row
    return result


def _fetch_target_rows_by_match_key(
    *,
    cur,
    schema_name: str,
    table_name: str,
    columns: list[str],
) -> dict[tuple[Any, ...], dict[str, Any]]:
    rows = _fetch_rows(
        cur=cur,
        schema_name=schema_name,
        table_name=table_name,
        columns=columns,
    )
    result: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        match_key = _build_business_match_key(table_name, row)
        if match_key is None or match_key in result:
            continue
        result[match_key] = row
    return result

def _fetch_reference_index(*, cur, schema_name: str, table_name: str, key_column: str) -> dict[str, dict[Any, Any]]:
    columns = _fetch_table_column_list(
        cur=cur,
        schema_name=schema_name,
        table_name=table_name,
    )
    if "t_id" not in columns or key_column not in columns:
        return {"by_t_id": {}, "by_key": {}}

    cur.execute(
        sql.SQL("SELECT {}, {} FROM {}.{}").format(
            sql.Identifier("t_id"),
            sql.Identifier(key_column),
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
        )
    )

    by_t_id: dict[Any, Any] = {}
    by_key: dict[Any, Any] = {}

    for row in cur.fetchall() or []:
        t_id = row["t_id"]
        key_value = row[key_column]
        if t_id is not None and key_value is not None:
            by_t_id[t_id] = key_value
            if key_value not in by_key:  # Tomar el primer t_id si la llave no es única
                by_key[key_value] = t_id

    return {"by_t_id": by_t_id, "by_key": by_key}


def _apply_required_insert_fallbacks(*, plan: TablePlan, row: dict[str, Any], translated_row: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    adjusted = dict(translated_row)
    warnings: list[str] = []

    if plan.table_name == "arb_construccion":
        identifier_value = adjusted.get("identificador")
        if identifier_value is None or str(identifier_value).strip() == "":
            for candidate_column in ("etiqueta", "t_ili_tid"):
                candidate_value = row.get(candidate_column)
                if candidate_value is None:
                    candidate_value = adjusted.get(candidate_column)
                if candidate_value is None or str(candidate_value).strip() == "":
                    continue
                adjusted["identificador"] = str(candidate_value).strip()
                warnings.append(
                    "se completo identificador con {}={} para permitir el insert.".format(
                        candidate_column,
                        adjusted.get("identificador"),
                    )
                )
                break

    return adjusted, warnings

def _process_table(
    *,
    cur,
    plan: TablePlan,
    target_schema: str,
    runtime: dict[str, Any],
    apply_changes: bool,
) -> dict[str, Any]:
    result = {
        "table": plan.table_name,
        "insertable_records": 0,
        "updatable_records": 0,
        "unchanged_records": 0,
        "nonsyncable_records": 0,
        "warnings": [],
        "critical_errors": [],
    }

    if not plan.syncable or not plan.key_column:
        result["critical_errors"] = list(plan.reasons)
        result["nonsyncable_records"] = plan.staging_count
        return result

    rows = runtime["staging_rows"].get(plan.table_name, [])
    target_rows = runtime["target_rows_by_key"].get(plan.table_name, {})
    target_rows_by_match = runtime["target_rows_by_match_key"].get(plan.table_name, {})
    seen_keys = set()
    mutable_columns = [column for column in plan.common_columns if column != "t_id"]
    required_insert_columns = runtime.get("required_insert_columns", {}).get(plan.table_name, [])
    geometry_target_columns = [
        column for column in plan.target_geometry_columns
        if column in plan.common_columns
    ]
    geometry_mappings = [
        f"{target_col}<-{plan.column_map[target_col]}"
        for target_col in geometry_target_columns
        if target_col in plan.column_map
    ]
    staging_geom_non_null_before = _count_non_null_geometry_rows(rows, geometry_target_columns)
    target_geom_non_null_before = _count_non_null_geometry_rows(list(target_rows.values()), geometry_target_columns)

    for row in rows:
        key_value = row.get(plan.key_column)
        normalized_key_value = _normalize_reference_key_value(key_value)
        if normalized_key_value is None:
            result["nonsyncable_records"] += 1
            result["warnings"].append(
                f"{plan.table_name}: se encontro un registro sin valor en la llave estable {plan.key_column}."
            )
            continue

        if normalized_key_value in seen_keys:
            result["nonsyncable_records"] += 1
            result["warnings"].append(
                f"{plan.table_name}: staging contiene llaves duplicadas para {plan.key_column}={key_value}."
            )
            continue

        seen_keys.add(normalized_key_value)

        target_row = target_rows.get(normalized_key_value)
        translated_row, row_errors, row_warnings = _translate_row_for_target(
            row=row,
            plan=plan,
            runtime=runtime,
            target_row=target_row,
        )
        translated_row, fallback_warnings = _apply_required_insert_fallbacks(
            plan=plan,
            row=row,
            translated_row=translated_row,
        )
        row_warnings.extend(fallback_warnings)

        matched_by_business_key = False
        if target_row is None:
            business_match_key = _build_business_match_key(plan.table_name, translated_row)
            if business_match_key is not None:
                target_row = target_rows_by_match.get(business_match_key)
                matched_by_business_key = target_row is not None
                if matched_by_business_key:
                    row_warnings.append(
                        "se emparejo contra target por llave funcional y no por {}.".format(plan.key_column)
                    )

        result["warnings"].extend(
            f"{plan.table_name}: {plan.key_column}={key_value}. {message}"
            for message in row_warnings
        )
        if row_errors:
            result["nonsyncable_records"] += 1
            result["warnings"].extend(
                f"{plan.table_name}: {plan.key_column}={key_value}. {message}"
                for message in row_errors
            )
            continue

        if target_row:
            if _rows_differ(
                source_row=translated_row,
                target_row=target_row,
                columns=mutable_columns,
                key_column=plan.key_column,
            ):
                if apply_changes:
                    savepoint_name = _make_savepoint_name(plan.table_name, "update", key_value)
                    try:
                        _create_savepoint(cur=cur, savepoint_name=savepoint_name)
                        selector_column = plan.key_column if target_row.get(plan.key_column) is not None else "t_id"
                        selector_value = target_row.get(plan.key_column) if selector_column == plan.key_column else target_row.get("t_id")
                        _update_target_row(
                            cur=cur,
                            schema_name=target_schema,
                            table_name=plan.table_name,
                            selector_column=selector_column,
                            selector_value=selector_value,
                            row=translated_row,
                        )
                    except psycopg2.Error as exc:
                        _rollback_to_savepoint(cur=cur, savepoint_name=savepoint_name)
                        result["nonsyncable_records"] += 1
                        result["warnings"].append(
                            f"{plan.table_name}: {plan.key_column}={key_value}. fallo el update por restriccion/BD: {exc}."
                        )
                        continue
                    else:
                        _release_savepoint(cur=cur, savepoint_name=savepoint_name)
                updated_target_row = {**target_row, **translated_row}
                target_rows[normalized_key_value] = updated_target_row
                updated_business_match_key = _build_business_match_key(plan.table_name, updated_target_row)
                if updated_business_match_key is not None:
                    target_rows_by_match[updated_business_match_key] = updated_target_row
                result["updatable_records"] += 1
            else:
                result["unchanged_records"] += 1
        else:
            missing_required_columns = [
                column
                for column in required_insert_columns
                if translated_row.get(column) is None
            ]
            if missing_required_columns:
                result["nonsyncable_records"] += 1
                result["warnings"].append(
                    f"{plan.table_name}: {plan.key_column}={key_value}. no se pudo insertar porque faltan columnas obligatorias en target: {', '.join(missing_required_columns)}."
                )
                continue

            if apply_changes:
                savepoint_name = _make_savepoint_name(plan.table_name, "insert", key_value)
                try:
                    _create_savepoint(cur=cur, savepoint_name=savepoint_name)
                    inserted_t_id = _insert_target_row(
                        cur=cur,
                        schema_name=target_schema,
                        table_name=plan.table_name,
                        row=translated_row,
                    )
                except psycopg2.Error as exc:
                    _rollback_to_savepoint(cur=cur, savepoint_name=savepoint_name)
                    result["nonsyncable_records"] += 1
                    result["warnings"].append(
                        f"{plan.table_name}: {plan.key_column}={key_value}. fallo el insert por restriccion/BD: {exc}."
                    )
                    continue
                else:
                    _release_savepoint(cur=cur, savepoint_name=savepoint_name)
                runtime["reference_maps"].setdefault(
                    plan.table_name,
                    {
                        "key_column": plan.key_column,
                        "staging_by_t_id": {},
                        "target_by_key": {},
                    },
                )
                runtime["reference_maps"][plan.table_name]["target_by_key"][_normalize_reference_key_value(key_value)] = inserted_t_id
            else:
                runtime["reference_maps"].setdefault(
                    plan.table_name,
                    {
                        "key_column": plan.key_column,
                        "staging_by_t_id": {},
                        "target_by_key": {},
                    },
                )
                runtime["reference_maps"][plan.table_name]["target_by_key"][_normalize_reference_key_value(key_value)] = _synthetic_id(
                    plan.table_name,
                    key_value,
                )

            inserted_target_row = translated_row.copy()
            target_rows[normalized_key_value] = inserted_target_row
            inserted_business_match_key = _build_business_match_key(plan.table_name, inserted_target_row)
            if inserted_business_match_key is not None:
                target_rows_by_match[inserted_business_match_key] = inserted_target_row
            result["insertable_records"] += 1
            if geometry_target_columns:
                result["warnings"].append(
                    f"{plan.table_name}: {plan.key_column}={key_value} se tratara como insert y no como update."
                )

    if geometry_target_columns or plan.staging_geometry_columns or plan.target_geometry_columns:
        target_geom_non_null_after = _count_non_null_geometry_rows(list(target_rows.values()), geometry_target_columns)
        result["warnings"].append(
            f"{plan.table_name}: diagnostico geometria staging={plan.staging_geometry_columns or ['-']} target={plan.target_geometry_columns or ['-']} mapped={geometry_mappings or ['-']} staging_non_null={staging_geom_non_null_before} target_pre_non_null={target_geom_non_null_before} target_post_non_null={target_geom_non_null_after}."
        )

    result["warnings"] = _dedupe_messages(result["warnings"])
    result["critical_errors"] = _dedupe_messages(result["critical_errors"])
    return result
def _translate_row_for_target(
    *,
    row: dict[str, Any],
    plan: TablePlan,
    runtime: dict[str, Any],
    target_row: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    translated: dict[str, Any] = {}
    errors: list[str] = []
    warnings: list[str] = []
    fk_by_column = {
        fk["column_name"]: fk
        for fk in plan.foreign_keys
        if fk["referenced_column"] == "t_id"
    }

    if "domain_value_maps" not in runtime:
        runtime["domain_value_maps"] = {}

    for column in plan.common_columns:
        if column == "t_id":
            continue

        value = row.get(column)
        fk = fk_by_column.get(column)
        if not fk or value is None:
            translated[column] = value
            continue

        ref_table = fk["referenced_table"]
        ref_map = runtime["reference_maps"].get(ref_table)
        domain_map = None
        if ref_table.endswith("tipo"):
            if ref_table not in runtime["domain_value_maps"]:
                runtime["domain_value_maps"][ref_table] = _fetch_domain_crosswalk(
                    runtime["cur"],
                    runtime["staging_schema"],
                    runtime["target_schema"],
                    ref_table,
                )
            domain_map = runtime["domain_value_maps"][ref_table]

        if domain_map and value in domain_map["target_tids"]:
            translated[column] = value
            continue

        if ref_map:
            stable_key = ref_map["staging_by_t_id"].get(value)
            if stable_key is not None:
                target_id = ref_map["target_by_key"].get(_normalize_reference_key_value(stable_key))
                if target_id is not None:
                    translated[column] = target_id
                    continue
                if domain_map:
                    alias_target_id = _match_domain_alias(domain_map, [stable_key])
                    if alias_target_id is not None:
                        translated[column] = alias_target_id
                        continue

        if domain_map:
            staging_aliases = domain_map["staging_aliases_by_t_id"].get(value, set())
            alias_target_id = _match_domain_alias(domain_map, [value, *list(staging_aliases)])
            if alias_target_id is not None:
                translated[column] = alias_target_id
                continue
            existing_target_value = (target_row or {}).get(column)
            if existing_target_value is not None:
                translated[column] = existing_target_value
                warnings.append(
                    f"se conservo {column}={existing_target_value} en target porque {value} no pudo mapearse en el dominio destino '{ref_table}'."
                )
                continue
            errors.append(
                f"el valor {column}={value} no pudo mapearse en el dominio destino '{ref_table}'."
            )
            continue

        if not ref_map:
            existing_target_value = (target_row or {}).get(column)
            if existing_target_value is not None:
                translated[column] = existing_target_value
                warnings.append(
                    f"se conservo {column}={existing_target_value} en target porque {ref_table} no tiene llave estable disponible."
                )
                continue
            errors.append(
                f"no se pudo traducir la FK {column} porque {ref_table} no tiene llave estable disponible."
            )
            continue

        existing_target_value = (target_row or {}).get(column)
        if existing_target_value is not None:
            translated[column] = existing_target_value
            warnings.append(
                f"se conservo {column}={existing_target_value} en target porque no existe referencia en staging para {column}={value} hacia {ref_table}."
            )
            continue
        errors.append(
            f"no existe referencia en staging para {column}={value} hacia {ref_table}."
        )

    return translated, errors, warnings


def _fetch_all_tids_from_table(cur, schema_name: str, table_name: str) -> set[Any]:
    """Busca todos los t_id de una tabla y los devuelve como un set."""
    try:
        cur.execute(
            sql.SQL("SELECT t_id FROM {}.{} WHERE t_id IS NOT NULL").format(
                sql.Identifier(schema_name), sql.Identifier(table_name)
            )
        )
        return {row["t_id"] for row in cur.fetchall() or []}
    except psycopg2.Error:
        return set()


def _normalize_domain_alias(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _collect_domain_aliases(row: dict[str, Any], alias_columns: list[str]) -> set[str]:
    aliases = set()
    for alias_column in alias_columns:
        alias = _normalize_domain_alias(row.get(alias_column))
        if alias:
            aliases.add(alias)
    return aliases


def _fetch_domain_crosswalk(cur, staging_schema: str, target_schema: str, table_name: str) -> dict[str, Any]:
    staging_columns = _fetch_table_column_list(cur=cur, schema_name=staging_schema, table_name=table_name)
    target_columns = _fetch_table_column_list(cur=cur, schema_name=target_schema, table_name=table_name)
    if not target_columns or "t_id" not in target_columns:
        return {"target_tids": set(), "target_by_alias": {}, "staging_aliases_by_t_id": {}}

    alias_columns = []
    for candidate in DOMAIN_KEY_CANDIDATES:
        for actual in (_find_column_case_insensitive(staging_columns, candidate), _find_column_case_insensitive(target_columns, candidate)):
            if actual and actual != "t_id" and actual not in alias_columns:
                alias_columns.append(actual)

    def fetch_rows(schema_name: str, columns: list[str]) -> list[dict[str, Any]]:
        if not columns:
            return []
        cur.execute(
            sql.SQL("SELECT {} FROM {}.{}").format(
                sql.SQL(", ").join(sql.Identifier(column) for column in columns),
                sql.Identifier(schema_name),
                sql.Identifier(table_name),
            )
        )
        return [dict(row) for row in (cur.fetchall() or [])]

    target_rows = fetch_rows(target_schema, ["t_id", *[c for c in alias_columns if c in target_columns]])
    staging_rows = fetch_rows(staging_schema, ["t_id", *[c for c in alias_columns if c in staging_columns]]) if staging_columns and "t_id" in staging_columns else []

    target_tids = set()
    target_by_alias: dict[str, Any] = {}
    for row in target_rows:
        t_id = row.get("t_id")
        if t_id is None:
            continue
        target_tids.add(t_id)
        for alias in _collect_domain_aliases(row, [c for c in row.keys() if c != "t_id"]):
            if alias not in target_by_alias:
                target_by_alias[alias] = t_id

    staging_aliases_by_t_id: dict[Any, set[str]] = {}
    for row in staging_rows:
        t_id = row.get("t_id")
        if t_id is None:
            continue
        staging_aliases_by_t_id[t_id] = _collect_domain_aliases(row, [c for c in row.keys() if c != "t_id"])

    return {
        "target_tids": target_tids,
        "target_by_alias": target_by_alias,
        "staging_aliases_by_t_id": staging_aliases_by_t_id,
    }


def _match_domain_alias(domain_map: dict[str, Any], values: list[Any]) -> Any | None:
    for value in values:
        alias = _normalize_domain_alias(value)
        if alias and alias in domain_map["target_by_alias"]:
            return domain_map["target_by_alias"][alias]
    return None


def _count_non_null_geometry_rows(rows: list[dict[str, Any]], geometry_columns: list[str]) -> int:
    if not rows or not geometry_columns:
        return 0
    return sum(
        1
        for row in rows
        if any(row.get(column) is not None for column in geometry_columns)
    )


def _rows_differ(
    *,
    source_row: dict[str, Any],
    target_row: dict[str, Any],
    columns: list[str],
    key_column: str,
) -> bool:
    return any(
        source_row.get(column) != target_row.get(column)
        for column in columns
        if column != key_column
    )


def _make_savepoint_name(table_name: str, operation: str, key_value: Any) -> str:
    raw = f"sp_{table_name}_{operation}_{key_value}"
    sanitized = re.sub(r"[^a-zA-Z0-9_]+", "_", raw)
    return sanitized[:48] or "sp_sync_row"


def _create_savepoint(*, cur, savepoint_name: str) -> None:
    cur.execute(sql.SQL("SAVEPOINT {}" ).format(sql.Identifier(savepoint_name)))


def _rollback_to_savepoint(*, cur, savepoint_name: str) -> None:
    cur.execute(sql.SQL("ROLLBACK TO SAVEPOINT {}" ).format(sql.Identifier(savepoint_name)))
    cur.execute(sql.SQL("RELEASE SAVEPOINT {}" ).format(sql.Identifier(savepoint_name)))


def _release_savepoint(*, cur, savepoint_name: str) -> None:
    cur.execute(sql.SQL("RELEASE SAVEPOINT {}" ).format(sql.Identifier(savepoint_name)))


def _update_target_row(
    *,
    cur,
    schema_name: str,
    table_name: str,
    selector_column: str,
    selector_value: Any,
    row: dict[str, Any],
) -> None:
    set_columns = [column for column in row.keys() if column != selector_column]
    if not set_columns:
        return

    cur.execute(
        sql.SQL("UPDATE {}.{} SET {} WHERE {} = %s").format(
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
            sql.SQL(", ").join(
                sql.SQL("{} = %s").format(sql.Identifier(column))
                for column in set_columns
            ),
            sql.Identifier(selector_column),
        ),
        [row[column] for column in set_columns] + [selector_value],
    )

def _insert_target_row(*, cur, schema_name: str, table_name: str, row: dict[str, Any]) -> Any:
    columns = list(row.keys())
    if not columns:
        raise RuntimeError(f"No hay columnas para insertar en {table_name}.")

    cur.execute(
        sql.SQL("INSERT INTO {}.{} ({}) VALUES ({}) RETURNING {}").format(
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
            sql.SQL(", ").join(sql.Identifier(column) for column in columns),
            sql.SQL(", ").join(sql.Placeholder() for _ in columns),
            sql.Identifier("t_id"),
        ),
        [row[column] for column in columns],
    )
    inserted = cur.fetchone()
    if not inserted:
        raise RuntimeError(f"No se pudo recuperar el t_id insertado para {table_name}.")
    return inserted["t_id"]


def _synthetic_id(table_name: str, key_value: Any) -> int:
    return -abs(hash((table_name, key_value)))


def _dedupe_messages(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        normalized = str(item or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result




































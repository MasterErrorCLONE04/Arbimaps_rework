import os
import re
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2 import errors as psy_errors

from services.asignaciones_export import ExportServiceError
from tenants import TenantContext, app_table, main_table, tenant_table, validate_identifier, work_table


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "sql" / "asignaciones" / "insertar_predios.sql"
_SCRIPT_START_MARKER = "-- 1) Semilla predios origen"


def _safe_int(value: Optional[str], default: int, minimum: int = 0) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    return parsed if parsed >= minimum else default


def _ms_literal(env_name: str, default_ms: int) -> str:
    ms = _safe_int(os.getenv(env_name), default_ms, minimum=1)
    return f"{ms}ms"


def _set_workspace_session_guards(cur, asignacion_id: int) -> None:
    cur.execute("SET LOCAL lock_timeout = %s", (_ms_literal("ASIG_WORKSPACE_LOCK_TIMEOUT_MS", 5000),))
    cur.execute(
        "SET LOCAL statement_timeout = %s",
        (_ms_literal("ASIG_WORKSPACE_STATEMENT_TIMEOUT_MS", 600000),),
    )
    cur.execute(
        "SET LOCAL idle_in_transaction_session_timeout = %s",
        (_ms_literal("ASIG_WORKSPACE_IDLE_TX_TIMEOUT_MS", 600000),),
    )
    cur.execute("SET LOCAL application_name = %s", (f"asig_workspace_{asignacion_id}",))


def _schema_name_from_qualified(qualified_name: str) -> str:
    schema_name, _, _ = str(qualified_name or "").partition(".")
    return validate_identifier(schema_name, label="qualified_schema")


def _qualify(schema: str, table: str) -> str:
    safe_schema = validate_identifier(schema, label="schema")
    safe_table = validate_identifier(table, label="table")
    return f"{safe_schema}.{safe_table}"


def _sanitize_dataset_name(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "asignacion"


def _load_script_body(*, tenant: TenantContext, schema_work: str) -> str:
    if not _SCRIPT_PATH.exists():
        raise ExportServiceError(
            status_code=500,
            detail=f"No existe el script SQL base: {_SCRIPT_PATH}",
        )

    text = _SCRIPT_PATH.read_text(encoding="utf-8")
    idx = text.find(_SCRIPT_START_MARKER)
    if idx < 0:
        raise ExportServiceError(
            status_code=500,
            detail=(
                "No se encontro el bloque esperado en insertar_predios.sql. "
                f"Marcador: {_SCRIPT_START_MARKER}"
            ),
        )

    body = text[idx:]
    body = re.sub(r"(?im)^\s*(ROLLBACK|BEGIN|COMMIT)\s*;\s*$", "", body)

    # Cut off final verification selects at the end
    idx_verif = body.find("-- 8) Verificación final")
    if idx_verif >= 0:
        body = body[:idx_verif]

    from core.asignaciones import get_assignment_model_context
    model_ctx = get_assignment_model_context()
    is_arb = (model_ctx.predio_table == "arb_predio")

    # If the database does not have CUC table, bypass the CUC guard block
    body = body.replace(
        "INTO v_fk_cal, v_fk_car, v_fk_tipc, v_fk_tipn\n  FROM _fk\n  WHERE child_table='cuc_calificacion_unidadconstruccion';\n\n  IF v_fk_cal IS NULL THEN",
        "INTO v_fk_cal, v_fk_car, v_fk_tipc, v_fk_tipn\n  FROM _fk\n  WHERE child_table='cuc_calificacion_unidadconstruccion';\n\n  IF NOT EXISTS (\n    SELECT 1 \n    FROM information_schema.tables \n    WHERE table_schema='leiva' \n      AND table_name='cuc_calificacion_unidadconstruccion'\n  ) THEN\n    RETURN;\n  END IF;\n\n  IF v_fk_cal IS NULL THEN"
    )

    if is_arb:
        # Exclude all enum/catalog tables from the dynamic FK graph traversal to prevent bleeding and query explosion.
        # Catalog/enum tables in Arbimaps end with 'tipo'. We do NOT exclude 'valor' tables because they store data (like avaluos, adjuntos).
        body = body.replace(
            "AND tc.table_name NOT LIKE 't_ili2db_%'\n  AND ccu.table_name NOT LIKE 't_ili2db_%'",
            "AND tc.table_name NOT LIKE 't_ili2db_%'\n  AND ccu.table_name NOT LIKE 't_ili2db_%'\n  AND tc.table_name NOT LIKE '%tipo'\n  AND ccu.table_name NOT LIKE '%tipo'"
        )
        # Limit recursion loop depth to 5 steps to prevent boundary/tramite mesh bleeding on large datasets
        body = body.replace("v_iter >= 25", "v_iter >= 5")

    source_schema = _schema_name_from_qualified(main_table(tenant, model_ctx.predio_table))
    target_schema = validate_identifier(schema_work, label="schema_work")
    app_schema = _schema_name_from_qualified(app_table(tenant, "asignacion"))

    replacements = {}
    if is_arb:
        replacements[r"\bilc_predio\b"] = "arb_predio"
        replacements[r"\bnumero_predial_nacional\b"] = "numero_predial"
        replacements[r"\bleiva\.ilc_derecho\b"] = f"(SELECT NULL::bigint as t_id, NULL::bigint as unidad, NULL::bigint as t_basket WHERE FALSE)"
        replacements[r"\bleiva\.col_rrrfuente\b"] = f"(SELECT NULL::bigint as t_id, NULL::bigint as rrr, NULL::bigint as fuente_administrativa, NULL::bigint as t_basket WHERE FALSE)"
        replacements[r"\bleiva\.col_rrrinteresado\b"] = f"(SELECT NULL::bigint as t_id, NULL::bigint as rrr, NULL::bigint as interesado_cr_agrupacioninteresados, NULL::bigint as interesado_ilc_interesado, NULL::bigint as t_basket WHERE FALSE)"
        replacements[r"\bleiva\.col_miembros\b"] = f"(SELECT NULL::bigint as t_id, NULL::bigint as agrupacion, NULL::bigint as interesado_ilc_interesado, NULL::bigint as interesado_cr_agrupacioninteresados, NULL::bigint as t_basket WHERE FALSE)"

    replacements[r"\bleiva\b"] = source_schema
    replacements[r"\bb_asignaciones\b"] = target_schema
    replacements[r"\barbimaps_app\b"] = app_schema

    for pattern, replacement in replacements.items():
        body = re.sub(pattern, replacement, body)

    return body.strip()


def _get_asignacion_meta(cur, tenant: TenantContext, asignacion_id: int) -> dict:
    asignacion_table = app_table(tenant, "asignacion")
    cur.execute(
        f"""
        SELECT id, usuario_asignado, titulo, work_datasetname
        FROM {asignacion_table}
        WHERE id = %s
        """,
        (asignacion_id,),
    )
    row = cur.fetchone()
    if not row:
        raise ExportServiceError(status_code=404, detail="Asignacion no encontrada.")
    return {
        "id": int(row[0]),
        "usuario_asignado": row[1],
        "titulo": row[2],
        "work_datasetname": row[3],
    }


def _get_active_npns(cur, tenant: TenantContext, asignacion_id: int) -> list[str]:
    asignacion_predio_table = app_table(tenant, "asignacion_predio")
    cur.execute(
        f"""
        SELECT ap.numero_predial_nacional
        FROM {asignacion_predio_table} ap
        WHERE ap.asignacion_id = %s
          AND ap.activo IS DISTINCT FROM FALSE
        ORDER BY ap.numero_predial_nacional
        """,
        (asignacion_id,),
    )
    return [str(r[0]).strip() for r in (cur.fetchall() or []) if r and r[0]]


def _get_active_predio_ids(cur, tenant: TenantContext, asignacion_id: int) -> list[int]:
    asignacion_predio_table = app_table(tenant, "asignacion_predio")
    cur.execute(
        f"""
        UPDATE {asignacion_predio_table} ap
        SET predio_t_id = p.t_id
        FROM {tenant.schemas.main}.arb_predio p
        WHERE ap.asignacion_id = %s
          AND ap.predio_t_id IS NULL
          AND ap.numero_predial_nacional IS NOT NULL
          AND BTRIM(p.numero_predial::text) = BTRIM(ap.numero_predial_nacional::text)
        """,
        (asignacion_id,),
    )
    cur.execute(
        f"""
        SELECT ap.predio_t_id
        FROM {asignacion_predio_table} ap
        WHERE ap.asignacion_id = %s
          AND ap.activo IS DISTINCT FROM FALSE
          AND ap.predio_t_id IS NOT NULL
        ORDER BY ap.predio_t_id
        """,
        (asignacion_id,),
    )
    return [int(r[0]) for r in (cur.fetchall() or []) if r and r[0] is not None]


def _resolve_dataset_name(meta: dict, dataset_name_override: Optional[str]) -> str:
    if dataset_name_override and str(dataset_name_override).strip():
        return _sanitize_dataset_name(str(dataset_name_override))

    work_ds = (meta.get("work_datasetname") or "").strip()
    if work_ds:
        return _sanitize_dataset_name(work_ds)

    usuario = (meta.get("usuario_asignado") or "").strip()
    titulo = (meta.get("titulo") or "").strip()
    return _sanitize_dataset_name(f"{usuario}_{titulo}_{meta.get('id')}")


def _validate_workspace_dataset(
    cur,
    tenant: TenantContext,
    *,
    schema_work: str,
    dataset_name: str,
    asignacion_id: int,
    seed_count: int,
) -> dict:
    from core.asignaciones import get_assignment_model_context
    model_ctx = get_assignment_model_context()
    is_arb = (model_ctx.predio_table == "arb_predio")

    safe_schema_work = validate_identifier(schema_work, label="schema_work")
    predio_table = _qualify(safe_schema_work, model_ctx.predio_table)
    basket_table = tenant_table(tenant, "t_ili2db_basket", schema_name="work")
    dataset_table = tenant_table(tenant, "t_ili2db_dataset", schema_name="work")
    asignacion_predio_table = app_table(tenant, "asignacion_predio")

    if is_arb:
        dir_table = _qualify(safe_schema_work, "arb_direccion")
        dir_fk_col = "arb_predio_direccion"
        derecho_table = _qualify(safe_schema_work, "arb_derechointeresadofuente")
        derecho_fk_col = "predio"
        npn_col = "numero_predial"
        datos_subquery = "0 AS predios_datos_invalido"
    else:
        dir_table = _qualify(safe_schema_work, "extdireccion")
        dir_fk_col = "ilc_predio_direccion"
        derecho_table = _qualify(safe_schema_work, "ilc_derecho")
        derecho_fk_col = "unidad"
        npn_col = "numero_predial_nacional"
        
        datos_table = _qualify(safe_schema_work, "ilc_datosadicionaleslevantamientocatastral")
        datos_subquery = f"""(
                SELECT COUNT(*)
                FROM (
                    SELECT p.t_id, COUNT(x.*) AS n
                    FROM predios p
                    LEFT JOIN {datos_table} x ON x.ilc_predio = p.t_id
                    GROUP BY p.t_id
                    HAVING COUNT(x.*) <> 1
                ) t
            ) AS predios_datos_invalido"""

    cur.execute(
        f"""
        WITH predios AS (
            SELECT p.t_id, p.{npn_col} AS numero_predial_nacional
            FROM {predio_table} p
            JOIN {basket_table} b ON b.t_id = p.t_basket
            JOIN {dataset_table} d ON d.t_id = b.dataset
            WHERE d.datasetname = %s
        )
        SELECT
            (SELECT COUNT(*) FROM predios) AS predios_total,
            (
                SELECT COUNT(*)
                FROM predios p
                JOIN {asignacion_predio_table} ap
                  ON ap.numero_predial_nacional = p.numero_predial_nacional
                 AND ap.asignacion_id = %s
                 AND ap.activo IS DISTINCT FROM FALSE
            ) AS predios_asignacion_filas,
            (
                SELECT COUNT(DISTINCT ap.numero_predial_nacional)
                FROM predios p
                JOIN {asignacion_predio_table} ap
                  ON ap.numero_predial_nacional = p.numero_predial_nacional
                 AND ap.asignacion_id = %s
                 AND ap.activo IS DISTINCT FROM FALSE
            ) AS predios_asignacion,
            (
                SELECT COUNT(*)
                FROM (
                    SELECT p.t_id, COUNT(d.*) AS n
                    FROM predios p
                    LEFT JOIN {dir_table} d ON d.{dir_fk_col} = p.t_id
                    GROUP BY p.t_id
                    HAVING COUNT(d.*) <> 1
                ) t
            ) AS predios_direccion_invalida,
            {datos_subquery},
            (
                SELECT COUNT(*)
                FROM (
                    SELECT p.t_id, COUNT(r.*) AS n
                    FROM predios p
                    LEFT JOIN {derecho_table} r ON r.{derecho_fk_col} = p.t_id
                    GROUP BY p.t_id
                    HAVING COUNT(r.*) <> 1
                ) t
            ) AS predios_derecho_invalido
        """,
        (dataset_name, asignacion_id, asignacion_id),
    )
    row = cur.fetchone() or (0, 0, 0, 0, 0, 0)
    summary = {
        "predios_total": int(row[0] or 0),
        "predios_asignacion_filas": int(row[1] or 0),
        "predios_asignacion": int(row[2] or 0),
        "predios_direccion_invalida": int(row[3] or 0),
        "predios_datos_invalido": int(row[4] or 0),
        "predios_derecho_invalido": int(row[5] or 0),
    }

    cur.execute(
        f"""
        WITH asignados AS (
            SELECT ap.numero_predial_nacional
            FROM {asignacion_predio_table} ap
            WHERE ap.asignacion_id = %s
              AND ap.activo IS DISTINCT FROM FALSE
        ),
        presentes AS (
            SELECT DISTINCT p.{npn_col} AS numero_predial_nacional
            FROM {predio_table} p
            JOIN {basket_table} b ON b.t_id = p.t_basket
            JOIN {dataset_table} d ON d.t_id = b.dataset
            WHERE d.datasetname = %s
        ),
        missing AS (
            SELECT a.numero_predial_nacional
            FROM asignados a
            LEFT JOIN presentes p ON p.numero_predial_nacional = a.numero_predial_nacional
            WHERE p.numero_predial_nacional IS NULL
        )
        SELECT COUNT(*) FROM missing
        """,
        (asignacion_id, dataset_name),
    )
    missing_count = int((cur.fetchone() or [0])[0] or 0)
    summary["predios_faltantes_workspace"] = missing_count

    if summary["predios_total"] == 0:
        raise ExportServiceError(
            status_code=500,
            detail=(
                f"Workspace SQL incompleto: dataset '{dataset_name}' sin predios "
                f"en {safe_schema_work}."
            ),
        )

    if summary["predios_asignacion"] == 0:
        raise ExportServiceError(
            status_code=500,
            detail=(
                f"Workspace SQL inconsistente en '{dataset_name}': "
                f"semilla={seed_count}, predios_dataset={summary['predios_total']}, "
                f"predios_asignacion={summary['predios_asignacion']}."
            ),
        )

    summary["predios_soporte_extra"] = max(summary["predios_total"] - summary["predios_asignacion"], 0)
    summary["predios_faltantes_dataset"] = max(seed_count - summary["predios_total"], 0)
    summary["predios_faltantes_asignacion"] = max(seed_count - summary["predios_asignacion"], 0)
    summary["has_integrity_warnings"] = (
        summary["predios_soporte_extra"] > 0
        or summary["predios_faltantes_dataset"] > 0
        or summary["predios_faltantes_asignacion"] > 0
        or summary["predios_total"] != seed_count
        or summary["predios_direccion_invalida"] > 0
        or summary["predios_datos_invalido"] > 0
        or summary["predios_derecho_invalido"] > 0
    )
    return summary


def run_insertar_predios_for_asignacion(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    *,
    dataset_name: Optional[str] = None,
    schema_work: Optional[str] = None,
) -> dict:
    expected_schema = validate_identifier(tenant.schemas.work, label="tenant.schemas.work")
    resolved_schema_work = validate_identifier(
        (schema_work or expected_schema).strip().strip('"'),
        label="schema_work",
    )
    if resolved_schema_work != expected_schema:
        raise ExportServiceError(
            status_code=400,
            detail=(
                "Este flujo SQL esta restringido al schema_work del tenant activo "
                f"({expected_schema})."
            ),
        )

    sql_body = _load_script_body(tenant=tenant, schema_work=resolved_schema_work)

    try:
        with conn.cursor() as cur:
            _set_workspace_session_guards(cur, asignacion_id)
            meta = _get_asignacion_meta(cur, tenant, asignacion_id)
            npn_list = _get_active_npns(cur, tenant, asignacion_id)
            predio_id_list = _get_active_predio_ids(cur, tenant, asignacion_id)
            if not npn_list and not predio_id_list:
                raise ExportServiceError(
                    status_code=400,
                    detail=f"La asignacion {asignacion_id} no tiene predios activos.",
                )

            ds_name = _resolve_dataset_name(meta, dataset_name)

            cur.execute("DROP TABLE IF EXISTS _cfg")
            cur.execute(
                """
                CREATE TEMP TABLE _cfg AS
                SELECT %s::text AS dataset_name, %s::text[] AS npn_list, %s::bigint[] AS predio_id_list
                """,
                (ds_name, npn_list, predio_id_list),
            )
            cur.execute(sql_body)

            # Importar predios de f_r1_r2 que no existan en el workspace antes de validar
            cur.execute(
                f"""
                SELECT b.t_id
                FROM {resolved_schema_work}.t_ili2db_basket b
                JOIN {resolved_schema_work}.t_ili2db_dataset d ON d.t_id = b.dataset
                WHERE d.datasetname = %s
                LIMIT 1
                """,
                (ds_name,),
            )
            row = cur.fetchone()
            if not row:
                cur.execute(
                    f"""
                    SELECT t_id 
                    FROM {resolved_schema_work}.t_ili2db_dataset 
                    WHERE datasetname = %s
                    LIMIT 1
                    """,
                    (ds_name,),
                )
                ds_row = cur.fetchone()
                if ds_row:
                    dataset_id = int(ds_row[0])
                else:
                    cur.execute(
                        f"""
                        INSERT INTO {resolved_schema_work}.t_ili2db_dataset(t_id, datasetname)
                        VALUES (COALESCE((SELECT max(t_id) FROM {resolved_schema_work}.t_ili2db_dataset), 0) + 1, %s)
                        RETURNING t_id
                        """,
                        (ds_name,),
                    )
                    dataset_id = int(cur.fetchone()[0])

                import uuid
                basket_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, ds_name))
                cur.execute(
                    f"""
                    INSERT INTO {resolved_schema_work}.t_ili2db_basket (t_id, dataset, topic, t_ili_tid, attachmentkey, domains)
                    VALUES (
                        COALESCE((SELECT max(t_id) FROM {resolved_schema_work}.t_ili2db_basket), 0) + 1,
                        %s,
                        'Captura_ArbiMaps_V1_0.Captura_ArbiMaps',
                        %s,
                        %s,
                        ''
                    )
                    RETURNING t_id
                    """,
                    (dataset_id, basket_uuid, f"{ds_name}_attach_1"),
                )
                t_basket_id = int(cur.fetchone()[0])
            else:
                t_basket_id = int(row[0])

            from services.asignaciones_workspace_f_r1_r2 import importar_predio_f_r1_r2_a_workspace
            for npn in npn_list:
                cur.execute(
                    f"""
                    SELECT 1 FROM {resolved_schema_work}.arb_predio p
                    JOIN {resolved_schema_work}.t_ili2db_basket b ON b.t_id = p.t_basket
                    JOIN {resolved_schema_work}.t_ili2db_dataset d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s AND p.numero_predial = %s
                    LIMIT 1
                    """,
                    (ds_name, npn),
                )
                exists = bool(cur.fetchone())
                if not exists:
                    importar_predio_f_r1_r2_a_workspace(conn, tenant, npn, resolved_schema_work, t_basket_id)

            from core.asignaciones import get_assignment_model_context
            model_ctx = get_assignment_model_context()

            cur.execute(
                """
                SELECT count(*)
                FROM {predio_table} p
                JOIN {basket_table} b ON b.t_id = p.t_basket
                JOIN {dataset_table} d ON d.t_id = b.dataset
                WHERE d.datasetname = %s
                """.format(
                    predio_table=work_table(tenant, model_ctx.predio_table),
                    basket_table=tenant_table(tenant, "t_ili2db_basket", schema_name="work"),
                    dataset_table=tenant_table(tenant, "t_ili2db_dataset", schema_name="work"),
                ),
                (ds_name,),
            )
            predios_cargados = int((cur.fetchone() or [0])[0] or 0)
            integrity = _validate_workspace_dataset(
                cur,
                tenant,
                schema_work=resolved_schema_work,
                dataset_name=ds_name,
                asignacion_id=asignacion_id,
                seed_count=len(npn_list),
            )

            cur.execute(
                f"""
                UPDATE {app_table(tenant, 'asignacion')}
                SET work_datasetname = %s
                WHERE id = %s
                """,
                (ds_name, asignacion_id),
            )

        return {
            "dataset_name": ds_name,
            "seed_predios": len(npn_list),
            "predios_cargados": predios_cargados,
            "predios_asignacion": integrity["predios_asignacion"],
            "predios_soporte_extra": integrity["predios_soporte_extra"],
            "predios_faltantes_dataset": integrity["predios_faltantes_dataset"],
            "predios_faltantes_asignacion": integrity["predios_faltantes_asignacion"],
            "predios_direccion_invalida": integrity["predios_direccion_invalida"],
            "predios_datos_invalido": integrity["predios_datos_invalido"],
            "predios_derecho_invalido": integrity["predios_derecho_invalido"],
            "has_integrity_warnings": integrity["has_integrity_warnings"],
        }
    except ExportServiceError:
        raise
    except psy_errors.QueryCanceled as exc:
        raise ExportServiceError(
            status_code=500,
            detail=(
                "Workspace SQL excedio el tiempo configurado "
                "(ASIG_WORKSPACE_STATEMENT_TIMEOUT_MS)."
            ),
        ) from exc
    except psy_errors.LockNotAvailable as exc:
        raise ExportServiceError(
            status_code=500,
            detail=(
                "Workspace SQL bloqueado por lock en base de datos "
                "(ASIG_WORKSPACE_LOCK_TIMEOUT_MS)."
            ),
        ) from exc
    except psycopg2.OperationalError as exc:
        raise ExportServiceError(
            status_code=500,
            detail=(
                "Error de conexion ejecutando workspace SQL tenant-aware. "
                "El reintento debe ser manejado por el caller."
            ),
        ) from exc
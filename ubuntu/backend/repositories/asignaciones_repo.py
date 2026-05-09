import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from psycopg2 import errorcodes as pg_errorcodes
from psycopg2.extras import RealDictCursor

from core.asignaciones import AssignmentModelContext, get_assignment_model_context
from core.db import db_conn


_ASIG_TABLES_ENSURED = False
_ASIG_EVENT_LOG_HAS_USUARIO_ID: Optional[bool] = None
logger = logging.getLogger(__name__)


def _qualify(schema: str, table: str) -> str:
    schema = (schema or "").strip().strip('"')
    if not schema:
        return table
    return f"{schema}.{table}"


def _resolve_predio_source(
    schema_main: str,
    model_context: Optional[AssignmentModelContext] = None,
) -> tuple[str, str]:
    context = model_context or get_assignment_model_context()
    predio_table = _qualify(schema_main, context.predio_table)
    return predio_table, context.predio_numero_field


def list_baskets_for_dataset(conn, schema_main: str, dataset_id: Optional[int]) -> list[dict]:
    if not dataset_id:
        return []
    basket_table = _qualify(schema_main, "t_ili2db_basket")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
                t_id AS basket_id,
                t_ili_tid AS basket_tid,
                dataset AS dataset_id,
                topic AS topicname
            FROM {basket_table}
            WHERE dataset = %s
            """,
            (dataset_id,),
        )
        return cur.fetchall()


def ensure_asignacion_tables(conn, *, force: bool = False) -> None:
    global _ASIG_TABLES_ENSURED
    # Evita DDL repetitivo en cada request (fuente de locks/caidas SSL).
    if _ASIG_TABLES_ENSURED:
        return

    runtime_ddl = os.getenv("ASIG_RUNTIME_DDL", "0").strip().lower() in {"1", "true", "yes"}
    if not force and not runtime_ddl:
        # En runtime solo asumimos que ya existe el esquema (migrado en startup).
        return

    with conn.cursor() as cur:
        # Nunca esperar indefinidamente por locks de DDL.
        cur.execute("SET LOCAL lock_timeout = '2s'")
        cur.execute("SET LOCAL statement_timeout = '30s'")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS arbimaps_app.asignacion_predio (
                id SERIAL PRIMARY KEY,
                asignacion_id BIGINT REFERENCES arbimaps_app.asignacion(id) ON DELETE CASCADE,
                numero_predial_nacional TEXT NOT NULL,
                predio_t_id BIGINT,
                activo BOOLEAN DEFAULT TRUE,
                creado_por TEXT,
                creado_en TIMESTAMPTZ DEFAULT now()
            )
            """
        )
        cur.execute(
            """
            ALTER TABLE IF EXISTS arbimaps_app.asignacion_predio
            ADD COLUMN IF NOT EXISTS creado_por TEXT
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS arbimaps_app.asignacion_event_log (
                id SERIAL PRIMARY KEY,
                asignacion_id BIGINT REFERENCES arbimaps_app.asignacion(id) ON DELETE CASCADE,
                evento TEXT,
                usuario TEXT,
                mensaje TEXT,
                creado_en TIMESTAMPTZ DEFAULT now()
            )
            """
        )
        cur.execute(
            """
            ALTER TABLE IF EXISTS arbimaps_app.asignacion
            ADD COLUMN IF NOT EXISTS work_datasetname TEXT
            """
        )
        cur.execute(
            """
            ALTER TABLE IF EXISTS arbimaps_app.asignacion
            ADD COLUMN IF NOT EXISTS predios_soporte_extra INTEGER NOT NULL DEFAULT 0
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS arbimaps_app.asignacion_export_job (
                id BIGSERIAL PRIMARY KEY,
                asignacion_id BIGINT NOT NULL REFERENCES arbimaps_app.asignacion(id) ON DELETE CASCADE,
                formato TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'PENDING',
                progreso INTEGER NOT NULL DEFAULT 0,
                mensaje TEXT,
                error_msg TEXT,
                archivo_path TEXT,
                archivo_nombre TEXT,
                archivo_size BIGINT,
                created_by TEXT,
                creado_en TIMESTAMPTZ DEFAULT now(),
                iniciado_en TIMESTAMPTZ,
                finalizado_en TIMESTAMPTZ,
                expira_en TIMESTAMPTZ
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS arbimaps_app.asignacion_retorno (
                id BIGSERIAL PRIMARY KEY,
                asignacion_id BIGINT NOT NULL REFERENCES arbimaps_app.asignacion(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                datasetname_retorno TEXT NOT NULL,
                archivo_nombre_original TEXT,
                archivo_nombre_guardado TEXT,
                archivo_sha256 TEXT,
                correlation_id TEXT,
                estado TEXT NOT NULL DEFAULT 'CARGADO',
                resultado_validacion TEXT,
                removed_predios INTEGER NOT NULL DEFAULT 0,
                synced_predios INTEGER NOT NULL DEFAULT 0,
                creado_por TEXT,
                creado_en TIMESTAMPTZ DEFAULT now(),
                sincronizado_en TIMESTAMPTZ,
                error_msg TEXT
            )
            """
        )
        # Indices para acelerar busquedas/joins criticos de asignaciones y exportacion.
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_asignacion_predio_asignacion
            ON arbimaps_app.asignacion_predio (asignacion_id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_asignacion_predio_numero
            ON arbimaps_app.asignacion_predio (numero_predial_nacional)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_asignacion_predio_asig_num_activo
            ON arbimaps_app.asignacion_predio (asignacion_id, numero_predial_nacional)
            WHERE activo IS DISTINCT FROM FALSE
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_asignacion_event_log_asignacion_id
            ON arbimaps_app.asignacion_event_log (asignacion_id, id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_asignacion_estado_usuario
            ON arbimaps_app.asignacion (estado, usuario_asignado)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_asig_export_job_asig_formato_estado
            ON arbimaps_app.asignacion_export_job (asignacion_id, formato, estado, id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_asig_export_job_estado_id
            ON arbimaps_app.asignacion_export_job (estado, id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_asig_export_job_expira
            ON arbimaps_app.asignacion_export_job (expira_en)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_asig_retorno_asignacion_id
            ON arbimaps_app.asignacion_retorno (asignacion_id, id)
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_asig_retorno_asig_version
            ON arbimaps_app.asignacion_retorno (asignacion_id, version)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_asig_retorno_estado_id
            ON arbimaps_app.asignacion_retorno (estado, id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_asig_retorno_sha_asig
            ON arbimaps_app.asignacion_retorno (asignacion_id, archivo_sha256)
            """
        )
    _ASIG_TABLES_ENSURED = True


def fail_stale_workspace_assignments(
    conn,
    *,
    stale_minutes: Optional[int] = None,
) -> list[dict]:
    minutes_env = os.getenv("ASIG_WORKSPACE_STALE_MINUTES", "20")
    try:
        minutes = int(stale_minutes if stale_minutes is not None else (minutes_env or "20"))
    except Exception:
        minutes = 20
    minutes = max(1, minutes)
    message = (
        "Workspace en estado CREANDO_WORKSPACE fue interrumpido "
        "(timeout/reinicio). Intenta crear la asignacion nuevamente."
    )
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SET LOCAL lock_timeout = '2s'")
        cur.execute("SET LOCAL statement_timeout = '20s'")
        cur.execute(
            """
            UPDATE arbimaps_app.asignacion a
            SET estado = 'ERROR_WORKSPACE',
                error_msg = COALESCE(NULLIF(a.error_msg, ''), %s)
            WHERE a.estado = 'CREANDO_WORKSPACE'
              AND COALESCE(a.creado_en, now()) < (now() - make_interval(mins => %s))
            RETURNING a.id, a.work_datasetname, a.creado_en
            """,
            (message, minutes),
        )
        return cur.fetchall()


def create_export_job(asignacion_id: int, formato: str, created_by: Optional[str]) -> dict:
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            ensure_asignacion_tables(conn)
            cur.execute(
                """
                INSERT INTO arbimaps_app.asignacion_export_job (
                    asignacion_id, formato, estado, progreso, mensaje, created_by
                )
                VALUES (%s, %s, 'PENDING', 0, 'En cola', %s)
                RETURNING *
                """,
                (asignacion_id, formato, created_by),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def get_export_job(job_id: int) -> Optional[dict]:
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            ensure_asignacion_tables(conn)
            cur.execute(
                """
                SELECT *
                FROM arbimaps_app.asignacion_export_job
                WHERE id = %s
                """,
                (job_id,),
            )
            return cur.fetchone()


def list_export_jobs_for_asignacion(asignacion_id: int, limit: int = 20) -> list[dict]:
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            ensure_asignacion_tables(conn)
            cur.execute(
                """
                SELECT *
                FROM arbimaps_app.asignacion_export_job
                WHERE asignacion_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (asignacion_id, limit),
            )
            return cur.fetchall()


def get_active_export_job(asignacion_id: int, formato: str) -> Optional[dict]:
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            ensure_asignacion_tables(conn)
            cur.execute(
                """
                SELECT *
                FROM arbimaps_app.asignacion_export_job
                WHERE asignacion_id = %s
                  AND formato = %s
                  AND estado IN ('PENDING', 'RUNNING')
                ORDER BY id DESC
                LIMIT 1
                """,
                (asignacion_id, formato),
            )
            return cur.fetchone()


def get_or_create_active_export_job(
    asignacion_id: int,
    formato: str,
    created_by: Optional[str],
) -> tuple[dict, bool]:
    """
    Crea el job de exportacion de forma atomica por (asignacion, formato).

    Retorna (job, created):
    - created=True  -> se creo un nuevo job.
    - created=False -> ya existia un job activo y se devuelve ese registro.
    """
    with db_conn() as conn:
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            ensure_asignacion_tables(conn)

            cur.execute(
                """
                SELECT id
                FROM arbimaps_app.asignacion
                WHERE id = %s
                FOR UPDATE
                """,
                (asignacion_id,),
            )
            asignacion = cur.fetchone()
            if not asignacion:
                raise ValueError(f"Asignacion no encontrada: {asignacion_id}")

            cur.execute(
                """
                SELECT *
                FROM arbimaps_app.asignacion_export_job
                WHERE asignacion_id = %s
                  AND formato = %s
                  AND estado IN ('PENDING', 'RUNNING')
                ORDER BY id DESC
                LIMIT 1
                """,
                (asignacion_id, formato),
            )
            existing = cur.fetchone()
            if existing:
                conn.commit()
                return existing, False

            cur.execute(
                """
                INSERT INTO arbimaps_app.asignacion_export_job (
                    asignacion_id, formato, estado, progreso, mensaje, created_by
                )
                VALUES (%s, %s, 'PENDING', 0, 'En cola', %s)
                RETURNING *
                """,
                (asignacion_id, formato, created_by),
            )
            created = cur.fetchone()
        conn.commit()
    return created, True


def update_export_job_progress(job_id: int, progreso: int, mensaje: Optional[str] = None) -> Optional[dict]:
    progreso = max(0, min(int(progreso), 100))
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            ensure_asignacion_tables(conn)
            cur.execute(
                """
                UPDATE arbimaps_app.asignacion_export_job
                SET progreso = %s,
                    mensaje = COALESCE(%s, mensaje)
                WHERE id = %s
                RETURNING *
                """,
                (progreso, mensaje, job_id),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def mark_export_job_running(job_id: int, mensaje: Optional[str] = None) -> Optional[dict]:
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            ensure_asignacion_tables(conn)
            cur.execute(
                """
                UPDATE arbimaps_app.asignacion_export_job
                SET estado = 'RUNNING',
                    progreso = GREATEST(progreso, 5),
                    mensaje = COALESCE(%s, mensaje),
                    iniciado_en = COALESCE(iniciado_en, now())
                WHERE id = %s
                RETURNING *
                """,
                (mensaje, job_id),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def mark_export_job_done(
    job_id: int,
    archivo_path: str,
    archivo_nombre: str,
    archivo_size: int,
    *,
    ttl_hours: int = 24,
    mensaje: Optional[str] = None,
) -> Optional[dict]:
    ttl_hours = max(1, int(ttl_hours))
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            ensure_asignacion_tables(conn)
            cur.execute(
                """
                UPDATE arbimaps_app.asignacion_export_job
                SET estado = 'DONE',
                    progreso = 100,
                    mensaje = COALESCE(%s, mensaje),
                    error_msg = NULL,
                    archivo_path = %s,
                    archivo_nombre = %s,
                    archivo_size = %s,
                    finalizado_en = now(),
                    expira_en = %s
                WHERE id = %s
                RETURNING *
                """,
                (mensaje, archivo_path, archivo_nombre, archivo_size, expires_at, job_id),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def mark_export_job_error(job_id: int, error_msg: str, mensaje: Optional[str] = None) -> Optional[dict]:
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            ensure_asignacion_tables(conn)
            cur.execute(
                """
                UPDATE arbimaps_app.asignacion_export_job
                SET estado = 'ERROR',
                    mensaje = COALESCE(%s, mensaje),
                    error_msg = %s,
                    finalizado_en = now()
                WHERE id = %s
                RETURNING *
                """,
                (mensaje, error_msg, job_id),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def _asig_event_log_has_usuario_id(conn) -> bool:
    global _ASIG_EVENT_LOG_HAS_USUARIO_ID
    if _ASIG_EVENT_LOG_HAS_USUARIO_ID is not None:
        return _ASIG_EVENT_LOG_HAS_USUARIO_ID

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'arbimaps_app'
              AND table_name = 'asignacion_event_log'
              AND column_name = 'usuario_id'
            LIMIT 1
            """
        )
        _ASIG_EVENT_LOG_HAS_USUARIO_ID = bool(cur.fetchone())
    return _ASIG_EVENT_LOG_HAS_USUARIO_ID


def insert_asignacion_event(conn, asignacion_id: int, evento: str, mensaje: Optional[str], usuario: Optional[str]) -> None:
    usuario_id: Optional[int] = None
    if usuario and _asig_event_log_has_usuario_id(conn):
        with conn.cursor(cursor_factory=RealDictCursor) as cur_user:
            cur_user.execute(
                """
                SELECT id_global
                FROM arbimaps_app.users
                WHERE username = %s
                LIMIT 1
                """,
                (usuario,),
            )
            row_user = cur_user.fetchone() or {}
            try:
                if row_user.get("id_global") is not None:
                    usuario_id = int(row_user["id_global"])
            except (TypeError, ValueError):
                usuario_id = None

    with conn.cursor() as cur:
        if _asig_event_log_has_usuario_id(conn):
            cur.execute(
                """
                INSERT INTO arbimaps_app.asignacion_event_log (asignacion_id, evento, usuario, mensaje, usuario_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (asignacion_id, evento, usuario, mensaje, usuario_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO arbimaps_app.asignacion_event_log (asignacion_id, evento, usuario, mensaje)
                VALUES (%s, %s, %s, %s)
                """,
                (asignacion_id, evento, usuario, mensaje),
            )


def safe_log_event(asignacion_id: int, evento: str, mensaje: Optional[str], usuario: Optional[str]) -> None:
    try:
        with db_conn() as conn:
            try:
                ensure_asignacion_tables(conn)
                insert_asignacion_event(conn, asignacion_id, evento, mensaje, usuario)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                pg_code = str(getattr(exc, "pgcode", "") or "")
                if pg_code == pg_errorcodes.INVALID_TEXT_REPRESENTATION:
                    # Compatibilidad con despliegues legacy donde `evento` es enum cerrado.
                    fallback_evento = "CREADA"
                    fallback_mensaje = f"[{evento}] {mensaje or ''}".strip()
                    try:
                        insert_asignacion_event(
                            conn,
                            asignacion_id,
                            fallback_evento,
                            fallback_mensaje,
                            usuario,
                        )
                        conn.commit()
                        return
                    except Exception as fallback_exc:
                        conn.rollback()
                        logger.warning(
                            "safe_log_event enum-fallback failed asignacion_id=%s evento=%s fallback=%s usuario=%s error=%s",
                            asignacion_id,
                            evento,
                            fallback_evento,
                            usuario,
                            fallback_exc,
                        )
                logger.warning(
                    "safe_log_event rollback asignacion_id=%s evento=%s usuario=%s error=%s",
                    asignacion_id,
                    evento,
                    usuario,
                    exc,
                )
    except Exception as exc:
        logger.warning(
            "safe_log_event connection error asignacion_id=%s evento=%s usuario=%s error=%s",
            asignacion_id,
            evento,
            usuario,
            exc,
        )


def fetch_predios_metadata(
    conn,
    schema_main: str,
    numeros: list[str],
    *,
    model_context: Optional[AssignmentModelContext] = None,
) -> list[dict]:
    predio_table, numero_field = _resolve_predio_source(schema_main, model_context)
    basket_table = _qualify(schema_main, "t_ili2db_basket")
    dataset_table = _qualify(schema_main, "t_ili2db_dataset")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
                p.{numero_field} AS numero_predial_nacional,
                p.t_id AS predio_t_id,
                p.t_basket,
                b.t_id AS basket_id,
                b.t_ili_tid AS basket_tid,
                b.topic AS topicname,
                NULL::text AS basketname,
                b.dataset AS dataset_id,
                d.datasetname AS datasetname_main
            FROM {predio_table} p
            LEFT JOIN {basket_table} b ON b.t_id = p.t_basket
            LEFT JOIN {dataset_table} d ON d.t_id = b.dataset
            WHERE p.{numero_field} = ANY(%s)
            """,
            (numeros,),
        )
        return cur.fetchall()


def fetch_predios_asignados(conn, numeros: list[str]) -> list[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT ap.numero_predial_nacional, a.usuario_asignado, ap.asignacion_id
            FROM arbimaps_app.asignacion_predio ap
            JOIN arbimaps_app.asignacion a ON ap.asignacion_id = a.id
            WHERE ap.numero_predial_nacional = ANY(%s)
              AND ap.activo IS DISTINCT FROM FALSE
              AND a.estado IS DISTINCT FROM 'CERRADA'
            """,
            (numeros,),
        )
        return cur.fetchall()


def update_asignacion_fields(
    asignacion_id: int,
    *,
    estado: Optional[str] = None,
    work_datasetname: Optional[str] = None,
    error_msg: Optional[str] = None,
    predios_soporte_extra: Optional[int] = None,
) -> None:
    sets: list[str] = []
    params: list[object] = []
    if estado is not None:
        sets.append("estado=%s")
        params.append(estado)
    if work_datasetname is not None:
        sets.append("work_datasetname=%s")
        params.append(work_datasetname)
    if error_msg is not None:
        sets.append("error_msg=%s")
        params.append(error_msg)
    if predios_soporte_extra is not None:
        sets.append("predios_soporte_extra=%s")
        params.append(max(int(predios_soporte_extra), 0))
    if not sets:
        return
    params.append(asignacion_id)
    sql = f"UPDATE arbimaps_app.asignacion SET {', '.join(sets)} WHERE id=%s"
    with db_conn() as conn:
        with conn.cursor() as cur:
            ensure_asignacion_tables(conn)
            cur.execute(sql, tuple(params))
        conn.commit()


def list_usuarios_disponibles(conn) -> list[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                u.id_global,
                u.username,
                u.first_name,
                u.last_name,
                u.rol
            FROM arbimaps_app.users u
            LEFT JOIN (
                SELECT DISTINCT a.usuario_asignado
                FROM arbimaps_app.asignacion a
                JOIN arbimaps_app.asignacion_predio ap
                  ON ap.asignacion_id = a.id
                 AND ap.activo IS DISTINCT FROM FALSE
                WHERE a.estado IS DISTINCT FROM 'CERRADA'
            ) a ON a.usuario_asignado = u.username
            WHERE u.activo IS TRUE
              AND a.usuario_asignado IS NULL
            ORDER BY u.first_name, u.last_name, u.username
            """
        )
        return cur.fetchall()


def buscar_predios_estado(
    conn,
    schema_main: str,
    numeros: list[str],
    *,
    model_context: Optional[AssignmentModelContext] = None,
) -> list[dict]:
    predio_table, numero_field = _resolve_predio_source(schema_main, model_context)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
              p.{numero_field} AS numero_predial_nacional,
              (
                SELECT a.usuario_asignado
                FROM arbimaps_app.asignacion a
                JOIN arbimaps_app.asignacion_predio ap ON ap.asignacion_id = a.id
                WHERE ap.numero_predial_nacional = p.{numero_field}
                  AND a.estado IS DISTINCT FROM 'CERRADA'
                LIMIT 1
              ) AS asignado_a,
              (
                SELECT a.creado_por
                FROM arbimaps_app.asignacion a
                JOIN arbimaps_app.asignacion_predio ap2 ON ap2.asignacion_id = a.id
                WHERE ap2.numero_predial_nacional = p.{numero_field}
                  AND a.estado IS DISTINCT FROM 'CERRADA'
                LIMIT 1
              ) AS asignado_por
            FROM {predio_table} p
            WHERE p.{numero_field} = ANY(%s)
            """,
            (numeros,),
        )
        return cur.fetchall()


def fetch_datasets_baskets_predio_counts(
    conn,
    schema_main: str,
    *,
    model_context: Optional[AssignmentModelContext] = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    dataset_table = _qualify(schema_main, "t_ili2db_dataset")
    basket_table = _qualify(schema_main, "t_ili2db_basket")
    predio_table, _ = _resolve_predio_source(schema_main, model_context)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
                t_id AS dataset_id,
                datasetname
            FROM {dataset_table}
            ORDER BY datasetname
            """
        )
        dataset_rows = cur.fetchall()

    with conn.cursor(cursor_factory=RealDictCursor) as cur_counts:
        cur_counts.execute(
            f"""
            SELECT t_basket, COUNT(*) AS total_predios
            FROM {predio_table}
            WHERE t_basket IS NOT NULL
            GROUP BY t_basket
            """
        )
        predio_count_rows = cur_counts.fetchall()

    with conn.cursor(cursor_factory=RealDictCursor) as cur2:
        cur2.execute(
            f"""
            SELECT
                b.dataset AS dataset_id,
                b.t_id AS basket_id,
                b.t_ili_tid AS basket_tid,
                b.topic AS topicname
            FROM {basket_table} b
            ORDER BY b.dataset, b.topic
            """
        )
        basket_rows = cur2.fetchall()

    return dataset_rows, basket_rows, predio_count_rows


def list_eventos_asignacion(conn, asignacion_id: int) -> list[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, asignacion_id, evento, usuario, mensaje, creado_en
            FROM arbimaps_app.asignacion_event_log
            WHERE asignacion_id = %s
            ORDER BY id ASC
            """,
            (asignacion_id,),
        )
        return cur.fetchall()


def allocate_asignacion_retorno_version(conn, asignacion_id: int) -> int:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        ensure_asignacion_tables(conn, force=True)
        cur.execute(
            """
            SELECT id
            FROM arbimaps_app.asignacion
            WHERE id = %s
            FOR UPDATE
            """,
            (asignacion_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Asignacion no encontrada: {asignacion_id}")
        cur.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1 AS next_version
            FROM arbimaps_app.asignacion_retorno
            WHERE asignacion_id = %s
            """,
            (asignacion_id,),
        )
        next_row = cur.fetchone() or {}
        return int(next_row.get("next_version") or 1)


def create_asignacion_retorno(
    conn,
    asignacion_id: int,
    version: int,
    datasetname_retorno: str,
    *,
    archivo_nombre_original: Optional[str] = None,
    archivo_nombre_guardado: Optional[str] = None,
    archivo_sha256: Optional[str] = None,
    correlation_id: Optional[str] = None,
    creado_por: Optional[str] = None,
) -> dict:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        ensure_asignacion_tables(conn, force=True)
        cur.execute(
            """
            INSERT INTO arbimaps_app.asignacion_retorno (
                asignacion_id,
                version,
                datasetname_retorno,
                archivo_nombre_original,
                archivo_nombre_guardado,
                archivo_sha256,
                correlation_id,
                creado_por
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                asignacion_id,
                version,
                datasetname_retorno,
                archivo_nombre_original,
                archivo_nombre_guardado,
                archivo_sha256,
                correlation_id,
                creado_por,
            ),
        )
        row = cur.fetchone()
    return row


def update_asignacion_retorno(
    conn,
    retorno_id: int,
    *,
    estado: Optional[str] = None,
    resultado_validacion: Optional[str] = None,
    removed_predios: Optional[int] = None,
    synced_predios: Optional[int] = None,
    error_msg: Optional[str] = None,
    sincronizado_en_now: bool = False,
) -> Optional[dict]:
    sets: list[str] = []
    params: list[object] = []
    if estado is not None:
        sets.append("estado = %s")
        params.append(estado)
    if resultado_validacion is not None:
        sets.append("resultado_validacion = %s")
        params.append(resultado_validacion)
    if removed_predios is not None:
        sets.append("removed_predios = %s")
        params.append(max(int(removed_predios), 0))
    if synced_predios is not None:
        sets.append("synced_predios = %s")
        params.append(max(int(synced_predios), 0))
    if error_msg is not None:
        sets.append("error_msg = %s")
        params.append(error_msg)
    if sincronizado_en_now:
        sets.append("sincronizado_en = now()")
    if not sets:
        return None

    params.append(retorno_id)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        ensure_asignacion_tables(conn, force=True)
        cur.execute(
            f"""
            UPDATE arbimaps_app.asignacion_retorno
            SET {', '.join(sets)}
            WHERE id = %s
            RETURNING *
            """,
            tuple(params),
        )
        return cur.fetchone()


def get_asignacion_work_dataset(conn, asignacion_id: int) -> Optional[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, work_datasetname
            FROM arbimaps_app.asignacion
            WHERE id = %s
            """,
            (asignacion_id,),
        )
        return cur.fetchone()


def get_recent_retorno_by_sha256(conn, asignacion_id: int, archivo_sha256: str) -> Optional[dict]:
    if not archivo_sha256:
        return None
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT *
            FROM arbimaps_app.asignacion_retorno
            WHERE asignacion_id = %s
              AND archivo_sha256 = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (asignacion_id, archivo_sha256),
        )
        return cur.fetchone()


def get_asignacion_for_paquete(conn, asignacion_id: int) -> Optional[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, work_datasetname, datasetname_main, titulo, usuario_asignado
            FROM arbimaps_app.asignacion
            WHERE id = %s
            """,
            (asignacion_id,),
        )
        return cur.fetchone()


def list_asignaciones(conn) -> list[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Evita que el endpoint quede "colgado" por bloqueos DDL/locks largos.
        cur.execute("SET LOCAL lock_timeout = '2s'")
        cur.execute("SET LOCAL statement_timeout = '20s'")
        cur.execute(
            """
            SELECT
                a.*,
                cu.first_name AS coord_first_name,
                cu.last_name AS coord_last_name,
                au.first_name AS asignado_first_name,
                au.last_name AS asignado_last_name,
                stats.total_activos,
                stats.total_inactivos,
                GREATEST(
                    COALESCE(a.predios_soporte_extra, 0),
                    COALESCE(ret.synced_predios, 0) - COALESCE(stats.total_activos, 0),
                    COALESCE(stats.total_nuevos_raw, 0)
                ) AS total_nuevos
            FROM arbimaps_app.asignacion a
            LEFT JOIN arbimaps_app.users cu ON cu.username = a.creado_por
            LEFT JOIN arbimaps_app.users au ON au.username = a.usuario_asignado
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*) FILTER (WHERE ap.activo IS DISTINCT FROM FALSE) AS total_activos,
                    COUNT(*) FILTER (WHERE ap.activo IS FALSE) AS total_inactivos,
                    COUNT(*) FILTER (WHERE ap.predio_t_id IS NULL) AS total_nuevos_raw
                FROM arbimaps_app.asignacion_predio ap
                WHERE ap.asignacion_id = a.id
            ) stats ON TRUE
            LEFT JOIN LATERAL (
                SELECT ar.synced_predios
                FROM arbimaps_app.asignacion_retorno ar
                WHERE ar.asignacion_id = a.id
                  AND ar.estado IN ('SINCRONIZADO', 'VALIDADO')
                ORDER BY ar.id DESC
                LIMIT 1
            ) ret ON TRUE
            WHERE COALESCE(stats.total_activos, 0) > 0
              AND a.estado::text <> 'CERRADA'
            ORDER BY a.id DESC
            """
        )
        return cur.fetchall()


def get_asignacion_detalle(conn, asignacion_id: int) -> Optional[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                a.*,
                cu.first_name AS coord_first_name,
                cu.last_name AS coord_last_name,
                au.first_name AS asignado_first_name,
                au.last_name AS asignado_last_name,
                stats.total_activos,
                stats.total_inactivos,
                GREATEST(
                    COALESCE(a.predios_soporte_extra, 0),
                    COALESCE(ret.synced_predios, 0) - COALESCE(stats.total_activos, 0),
                    COALESCE(stats.total_nuevos_raw, 0)
                ) AS total_nuevos
            FROM arbimaps_app.asignacion a
            LEFT JOIN arbimaps_app.users cu ON cu.username = a.creado_por
            LEFT JOIN arbimaps_app.users au ON au.username = a.usuario_asignado
            LEFT JOIN (
                SELECT
                    ap.asignacion_id,
                    COUNT(*) FILTER (WHERE ap.activo IS DISTINCT FROM FALSE) AS total_activos,
                    COUNT(*) FILTER (WHERE ap.activo IS FALSE) AS total_inactivos,
                    COUNT(*) FILTER (WHERE ap.predio_t_id IS NULL) AS total_nuevos_raw
                FROM arbimaps_app.asignacion_predio ap
                GROUP BY ap.asignacion_id
            ) stats ON stats.asignacion_id = a.id
            LEFT JOIN LATERAL (
                SELECT ar.synced_predios
                FROM arbimaps_app.asignacion_retorno ar
                WHERE ar.asignacion_id = a.id
                  AND ar.estado IN ('SINCRONIZADO', 'VALIDADO')
                ORDER BY ar.id DESC
                LIMIT 1
            ) ret ON TRUE
            WHERE a.id = %s
            LIMIT 1
            """,
            (asignacion_id,),
        )
        return cur.fetchone()


def list_predios_asignacion(conn, asignacion_id: int) -> list[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                ap.id,
                ap.numero_predial_nacional,
                ap.predio_t_id,
                ap.activo,
                ap.creado_por,
                ap.creado_en
            FROM arbimaps_app.asignacion_predio ap
            WHERE ap.asignacion_id = %s
            ORDER BY ap.activo DESC, ap.numero_predial_nacional ASC
            """,
            (asignacion_id,),
        )
        return cur.fetchall()

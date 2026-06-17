import os
import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from psycopg2 import errorcodes as pg_errorcodes
from psycopg2.extras import RealDictCursor

from core.asignaciones import AssignmentModelContext, get_assignment_model_context
from core.db import db_conn


_ASIG_TABLES_ENSURED = False
_ASIG_GEOSERVER_STATUS_VIEW_ENSURED: set[str] = set()
_ASIG_EVENT_LOG_HAS_USUARIO_ID: Optional[bool] = None
logger = logging.getLogger(__name__)


def _qualify(schema: str, table: str) -> str:
    if schema and not isinstance(schema, str) and hasattr(schema, "schemas"):
        schema = schema.schemas.main
    schema = (schema or "").strip().strip('"')
    if not schema:
        return table
    return f"{schema}.{table}"


def _safe_ident(value: str, *, fallback: str = "") -> str:
    text = (value or "").strip().strip('"')
    if text.replace("_", "").isalnum() and text[:1].isalpha():
        return text
    return fallback


def _qident(value: str) -> str:
    clean = _safe_ident(value)
    if not clean:
        raise ValueError(f"Identificador SQL invalido: {value!r}")
    return f'"{clean}"'


def _tenant_schema_names(tenant=None) -> tuple[str, str]:
    app_schema = "arbimaps_app"
    main_schema = "a_base_principal"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
            main_schema = tenant.schemas.main
        elif isinstance(tenant, str):
            app_schema = tenant
    return _safe_ident(app_schema, fallback="arbimaps_app"), _safe_ident(main_schema, fallback="a_base_principal")


def ensure_geoserver_assignment_status_view(conn, tenant=None, *, force: bool = False) -> None:
    global _ASIG_GEOSERVER_STATUS_VIEW_ENSURED

    app_schema, main_schema = _tenant_schema_names(tenant)
    cache_key = f"{app_schema}.{main_schema}"
    if cache_key in _ASIG_GEOSERVER_STATUS_VIEW_ENSURED and not force:
        return

    app_q = _qident(app_schema)
    main_q = _qident(main_schema)
    view_q = f"{app_q}.\"vw_predios_estado_asignacion\""

    with conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '10s'")
        cur.execute("SET LOCAL statement_timeout = '60s'")
        cur.execute(
            f"""
            CREATE OR REPLACE VIEW {view_q} AS
            SELECT
                t.t_id AS terreno_t_id,
                p.t_id AS predio_t_id,
                COALESCE(NULLIF(p.id_operacion::text, ''), p.numero_predial::text) AS id_operacion,
                p.numero_predial::text AS numero_predial_nacional,
                COALESCE(act.estado::text, 'SIN_ASIGNAR') AS estado_asignacion,
                act.asignacion_id,
                act.usuario_asignado,
                act.coordinador_username,
                act.fecha_inicio,
                act.fecha_fin_asignada,
                CASE
                    WHEN act.fecha_fin_asignada IS NULL THEN NULL
                    ELSE GREATEST(
                        0,
                        CEIL(EXTRACT(EPOCH FROM ((act.fecha_fin_asignada::date + INTERVAL '1 day') - now())) / 86400.0)::int
                    )
                END AS dias_restantes,
                t.geometria
            FROM {main_q}."arb_terreno" t
            LEFT JOIN {main_q}."arb_predio" p ON p.t_id = t.predio
            LEFT JOIN LATERAL (
                SELECT
                    a.id AS asignacion_id,
                    a.estado,
                    a.usuario_asignado,
                    a.creado_por AS coordinador_username,
                    a.creado_en AS fecha_inicio,
                    a.fecha_fin_asignada
                FROM {app_q}."asignacion_predio" ap
                JOIN {app_q}."asignacion" a ON a.id = ap.asignacion_id
                WHERE ap.activo IS DISTINCT FROM FALSE
                  AND a.estado::text NOT IN ('CERRADA', 'SINCRONIZADO')
                  AND NULLIF(BTRIM(ap.numero_predial_nacional::text), '') = NULLIF(BTRIM(p.numero_predial::text), '')
                ORDER BY a.creado_en DESC NULLS LAST, a.id DESC
                LIMIT 1
            ) act ON TRUE
            """
        )

    _ASIG_GEOSERVER_STATUS_VIEW_ENSURED.add(cache_key)


def _resolve_predio_source(
    schema_main: str,
    model_context: Optional[AssignmentModelContext] = None,
) -> tuple[str, str]:
    if schema_main and not isinstance(schema_main, str) and hasattr(schema_main, "schemas"):
        schema_main = schema_main.schemas.main
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


def ensure_asignacion_tables(conn, tenant=None, *, force: bool = False) -> None:
    global _ASIG_TABLES_ENSURED
    # Evita DDL repetitivo en cada request (fuente de locks/caidas SSL).
    if _ASIG_TABLES_ENSURED:
        return

    runtime_ddl = os.getenv("ASIG_RUNTIME_DDL", "0").strip().lower() in {"1", "true", "yes"}
    if not force and not runtime_ddl:
        # En runtime solo asumimos que ya existe el esquema (migrado en startup).
        return

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor() as cur:
        # Nunca esperar indefinidamente por locks de DDL.
        cur.execute("SET LOCAL lock_timeout = '10s'")
        cur.execute("SET LOCAL statement_timeout = '60s'")
        in_transaction = not conn.autocommit
        if in_transaction:
            cur.execute("SAVEPOINT ensure_asig_tables_sp")
        try:
            # Asegurar que los enums contienen todos los valores esperados
            # Para evitar "unsafe use of new value ... HINT: New enum values must be committed before they can be used",
            # abrimos una conexion temporal con autocommit=True.
            try:
                from core.db.connection import get_db_params
                import psycopg2
                params = get_db_params()
                with psycopg2.connect(**params) as temp_conn:
                    temp_conn.autocommit = True
                    with temp_conn.cursor() as temp_cur:
                        # 1. Asegurar asignacion_evento
                        for val in ["WORKSPACE_READY", "WORKSPACE_READY_WARN", "PAQUETE_JOB_CREADO", "PAQUETE_JOB_DONE", "PAQUETE_JOB_ERROR", "ERROR", "ESTADO_CAMBIADO", "REASIGNADA", "CERRADA", "ASIGNADA"]:
                            temp_cur.execute(
                                """
                                SELECT 1 FROM pg_enum 
                                JOIN pg_type ON pg_enum.enumtypid = pg_type.oid 
                                WHERE pg_type.typname = 'asignacion_evento' AND pg_enum.enumlabel = %s
                                """,
                                (val,),
                            )
                            if not temp_cur.fetchone():
                                try:
                                    temp_cur.execute(f"ALTER TYPE {app_schema}.asignacion_evento ADD VALUE '{val}'")
                                except Exception as e:
                                    logger.warning("Fallo agregar valor enum %s en conexion autocommit: %s", val, e)
                        
                        # 2. Asegurar asignacion_estado contiene 'CONTROL_CALIDAD_1'
                        temp_cur.execute(
                            """
                            SELECT 1 FROM pg_enum 
                            JOIN pg_type ON pg_enum.enumtypid = pg_type.oid 
                            WHERE pg_type.typname = 'asignacion_estado' AND pg_enum.enumlabel = 'CONTROL_CALIDAD_1'
                            """
                        )
                        if not temp_cur.fetchone():
                            try:
                                temp_cur.execute(f"ALTER TYPE {app_schema}.asignacion_estado ADD VALUE 'CONTROL_CALIDAD_1'")
                            except Exception as e:
                                logger.warning("Fallo agregar valor enum CONTROL_CALIDAD_1 en conexion autocommit: %s", e)
            except Exception as e:
                logger.error("No se pudo conectar a la base de datos para asegurar los enums: %s", e)

            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {app_schema}.asignacion_predio (
                    id SERIAL PRIMARY KEY,
                    asignacion_id BIGINT REFERENCES {app_schema}.asignacion(id) ON DELETE CASCADE,
                    numero_predial_nacional TEXT NOT NULL,
                    predio_t_id BIGINT,
                    activo BOOLEAN DEFAULT TRUE,
                    creado_por TEXT,
                    creado_en TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            cur.execute(
                f"""
                ALTER TABLE IF EXISTS {app_schema}.asignacion_predio
                ADD COLUMN IF NOT EXISTS creado_por TEXT
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {app_schema}.asignacion_event_log (
                    id SERIAL PRIMARY KEY,
                    asignacion_id BIGINT REFERENCES {app_schema}.asignacion(id) ON DELETE CASCADE,
                    evento TEXT,
                    usuario TEXT,
                    mensaje TEXT,
                    creado_en TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            cur.execute(
                f"""
                ALTER TABLE IF EXISTS {app_schema}.asignacion
                ADD COLUMN IF NOT EXISTS work_datasetname TEXT
                """
            )
            cur.execute(
                f"""
                ALTER TABLE IF EXISTS {app_schema}.asignacion
                ADD COLUMN IF NOT EXISTS predios_soporte_extra INTEGER NOT NULL DEFAULT 0
                """
            )
            cur.execute(
                f"""
                ALTER TABLE IF EXISTS {app_schema}.asignacion
                ADD COLUMN IF NOT EXISTS coordinador_asignado_id BIGINT
                """
            )
            cur.execute(
                f"""
                ALTER TABLE IF EXISTS {app_schema}.asignacion
                ADD COLUMN IF NOT EXISTS enlace_control_calidad TEXT
                """
            )
            cur.execute(
                f"""
                ALTER TABLE IF EXISTS {app_schema}.asignacion
                ADD COLUMN IF NOT EXISTS enlace_soporte TEXT
                """
            )
            cur.execute(
                f"""
                ALTER TABLE IF EXISTS {app_schema}.asignacion
                ADD COLUMN IF NOT EXISTS enlace_digitalizacion TEXT
                """
            )
            cur.execute(
                f"""
                ALTER TABLE IF EXISTS {app_schema}.asignacion
                ADD COLUMN IF NOT EXISTS fecha_fin_asignada DATE
                """
            )
            cur.execute(
                f"""
                ALTER TABLE IF EXISTS {app_schema}.asignacion
                ADD COLUMN IF NOT EXISTS usuario_reconocedor_id BIGINT,
                ADD COLUMN IF NOT EXISTS usuario_reconocedor TEXT
                """
            )
            cur.execute(
                """
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_asignacion_coordinador'
                """
            )
            if not cur.fetchone():
                cur.execute(
                    f"""
                    ALTER TABLE {app_schema}.asignacion
                    ADD CONSTRAINT fk_asignacion_coordinador
                    FOREIGN KEY (coordinador_asignado_id)
                    REFERENCES {app_schema}.users(id_global)
                    ON DELETE SET NULL
                    """
                )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {app_schema}.asignacion_export_job (
                    id BIGSERIAL PRIMARY KEY,
                    asignacion_id BIGINT NOT NULL REFERENCES {app_schema}.asignacion(id) ON DELETE CASCADE,
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
                f"""
                CREATE TABLE IF NOT EXISTS {app_schema}.asignacion_retorno (
                    id BIGSERIAL PRIMARY KEY,
                    asignacion_id BIGINT NOT NULL REFERENCES {app_schema}.asignacion(id) ON DELETE CASCADE,
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
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_asignacion_predio_asignacion
                ON {app_schema}.asignacion_predio (asignacion_id)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_asignacion_predio_nacional
                ON {app_schema}.asignacion_predio (numero_predial_nacional)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_asig_predio_lookup
                ON {app_schema}.asignacion_predio (asignacion_id, numero_predial_nacional)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_asig_event_log_lookup
                ON {app_schema}.asignacion_event_log (asignacion_id, id)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_asig_estado_user
                ON {app_schema}.asignacion (estado, usuario_asignado)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_asig_exp_job_lookup
                ON {app_schema}.asignacion_export_job (asignacion_id, formato, estado, id)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_asig_exp_job_status
                ON {app_schema}.asignacion_export_job (estado, id)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_asig_exp_job_expiry
                ON {app_schema}.asignacion_export_job (expira_en)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_asig_retorno_lookup
                ON {app_schema}.asignacion_retorno (asignacion_id, id)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_asig_retorno_version
                ON {app_schema}.asignacion_retorno (asignacion_id, version)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_asig_retorno_status
                ON {app_schema}.asignacion_retorno (estado, id)
                """
            )
            cur.execute(
                f"""
                ALTER TABLE IF EXISTS {app_schema}.asignacion_retorno
                ADD COLUMN IF NOT EXISTS expected_predios INTEGER NOT NULL DEFAULT 0
                """
            )
            cur.execute(
                f"""
                ALTER TABLE IF EXISTS {app_schema}.asignacion_retorno
                ADD COLUMN IF NOT EXISTS covered_predios INTEGER NOT NULL DEFAULT 0
                """
            )
            cur.execute(
                f"""
                ALTER TABLE IF EXISTS {app_schema}.asignacion_retorno
                ADD COLUMN IF NOT EXISTS archivo_nombre_original TEXT,
                ADD COLUMN IF NOT EXISTS archivo_nombre_guardado TEXT,
                ADD COLUMN IF NOT EXISTS archivo_sha256 TEXT,
                ADD COLUMN IF NOT EXISTS correlation_id TEXT
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_asig_retorno_sha_asig
                ON {app_schema}.asignacion_retorno (asignacion_id, archivo_sha256)
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {app_schema}.notificaciones (
                    id SERIAL PRIMARY KEY,
                    cod_tramite TEXT,
                    id_asignacion BIGINT REFERENCES {app_schema}.asignacion(id) ON DELETE SET NULL,
                    id_usuario_destino BIGINT NOT NULL,
                    id_usuario_origen BIGINT,
                    rol_origen TEXT,
                    rol_destino TEXT,
                    tipo TEXT DEFAULT 'asignacion',
                    titulo TEXT NOT NULL,
                    mensaje TEXT NOT NULL,
                    url_destino TEXT,
                    prioridad TEXT DEFAULT 'normal',
                    fecha_limite TIMESTAMPTZ,
                    metadata JSONB,
                    leido BOOLEAN DEFAULT FALSE,
                    archivado BOOLEAN DEFAULT FALSE,
                    fecha_creacion TIMESTAMPTZ DEFAULT now(),
                    fecha_lectura TIMESTAMPTZ
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_notificaciones_usuario_destino
                ON {app_schema}.notificaciones (id_usuario_destino, archivado, leido)
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {app_schema}.asignacion_comentario (
                    id SERIAL PRIMARY KEY,
                    asignacion_id BIGINT REFERENCES {app_schema}.asignacion(id) ON DELETE CASCADE,
                    usuario_id BIGINT REFERENCES {app_schema}.users(id_global) ON DELETE SET NULL,
                    usuario TEXT,
                    rol TEXT,
                    comentario TEXT NOT NULL,
                    estado_origen TEXT,
                    estado_destino TEXT,
                    creado_en TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_asignacion_comentario_lookup
                ON {app_schema}.asignacion_comentario (asignacion_id)
                """
            )
            cur.execute(
                f"""
                ALTER TABLE IF EXISTS {app_schema}.asignacion
                ADD COLUMN IF NOT EXISTS enlace_devolucion TEXT
                """
            )
            cur.execute(
                f"""
                ALTER TABLE IF EXISTS {app_schema}.asignacion_comentario
                ADD COLUMN IF NOT EXISTS enlace TEXT
                """
            )
            if in_transaction:
                cur.execute("RELEASE SAVEPOINT ensure_asig_tables_sp")
        except Exception as exc:
            if in_transaction:
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT ensure_asig_tables_sp")
                except Exception as rollback_exc:
                    logger.warning("Failed to rollback to savepoint: %s", rollback_exc)
            logger.warning("ensure_asignacion_tables: DDL omitido/fallido por contencion de locks: %s", exc)
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


def get_export_job(conn, *args, **kwargs) -> Optional[dict]:
    tenant = None
    pos_args = list(args)
    if pos_args and not isinstance(pos_args[0], int):
        tenant = pos_args.pop(0)
    job_id = pos_args[0] if len(pos_args) > 0 else kwargs.get("job_id")

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        ensure_asignacion_tables(conn, tenant)
        cur.execute(
            f"""
            SELECT *
            FROM {app_schema}.asignacion_export_job
            WHERE id = %s
            """,
            (job_id,),
        )
        return cur.fetchone()


def list_export_jobs_for_asignacion(conn, *args, **kwargs) -> list[dict]:
    tenant = None
    pos_args = list(args)
    if pos_args and not isinstance(pos_args[0], int):
        tenant = pos_args.pop(0)
    asignacion_id = pos_args[0] if len(pos_args) > 0 else kwargs.get("asignacion_id")
    limit = pos_args[1] if len(pos_args) > 1 else kwargs.get("limit", 20)

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        ensure_asignacion_tables(conn, tenant)
        cur.execute(
            f"""
            SELECT *
            FROM {app_schema}.asignacion_export_job
            WHERE asignacion_id = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (asignacion_id, limit),
        )
        return cur.fetchall()


def get_active_export_job(conn, *args, **kwargs) -> Optional[dict]:
    tenant = None
    pos_args = list(args)
    if pos_args and not isinstance(pos_args[0], int):
        tenant = pos_args.pop(0)
    asignacion_id = pos_args[0] if len(pos_args) > 0 else kwargs.get("asignacion_id")
    formato = pos_args[1] if len(pos_args) > 1 else kwargs.get("formato")

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        ensure_asignacion_tables(conn, tenant)
        cur.execute(
            f"""
            SELECT *
            FROM {app_schema}.asignacion_export_job
            WHERE asignacion_id = %s
              AND formato = %s
              AND estado IN ('PENDING', 'RUNNING')
            ORDER BY id DESC
            LIMIT 1
            """,
            (asignacion_id, formato),
        )
        return cur.fetchone()


def get_or_create_active_export_job(conn, *args, **kwargs) -> tuple[dict, bool]:
    tenant = None
    pos_args = list(args)
    if pos_args and not isinstance(pos_args[0], int):
        tenant = pos_args.pop(0)
    asignacion_id = pos_args[0] if len(pos_args) > 0 else kwargs.get("asignacion_id")
    formato = pos_args[1] if len(pos_args) > 1 else kwargs.get("formato")
    created_by = pos_args[2] if len(pos_args) > 2 else kwargs.get("created_by")

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        ensure_asignacion_tables(conn, tenant)

        cur.execute(
            f"""
            SELECT id
            FROM {app_schema}.asignacion
            WHERE id = %s
            FOR UPDATE
            """,
            (asignacion_id,),
        )
        asignacion = cur.fetchone()
        if not asignacion:
            raise ValueError(f"Asignacion no encontrada: {asignacion_id}")

        cur.execute(
            f"""
            SELECT *
            FROM {app_schema}.asignacion_export_job
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
            return existing, False

        cur.execute(
            f"""
            INSERT INTO {app_schema}.asignacion_export_job (
                asignacion_id, formato, estado, progreso, mensaje, created_by
            )
            VALUES (%s, %s, 'PENDING', 0, 'En cola', %s)
            RETURNING *
            """,
            (asignacion_id, formato, created_by),
        )
        created = cur.fetchone()
    return created, True


def update_export_job_progress(conn, *args, **kwargs) -> Optional[dict]:
    tenant = None
    pos_args = list(args)
    if pos_args and not isinstance(pos_args[0], int):
        tenant = pos_args.pop(0)
    job_id = pos_args[0] if len(pos_args) > 0 else kwargs.get("job_id")
    progreso = pos_args[1] if len(pos_args) > 1 else kwargs.get("progreso")
    mensaje = pos_args[2] if len(pos_args) > 2 else kwargs.get("mensaje")

    progreso = max(0, min(int(progreso), 100))

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        ensure_asignacion_tables(conn, tenant)
        cur.execute(
            f"""
            UPDATE {app_schema}.asignacion_export_job
            SET progreso = %s,
                mensaje = COALESCE(%s, mensaje)
            WHERE id = %s
            RETURNING *
            """,
            (progreso, mensaje, job_id),
        )
        return cur.fetchone()


def mark_export_job_running(conn, *args, **kwargs) -> Optional[dict]:
    tenant = None
    pos_args = list(args)
    if pos_args and not isinstance(pos_args[0], int):
        tenant = pos_args.pop(0)
    job_id = pos_args[0] if len(pos_args) > 0 else kwargs.get("job_id")
    mensaje = pos_args[1] if len(pos_args) > 1 else kwargs.get("mensaje")

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        ensure_asignacion_tables(conn, tenant)
        cur.execute(
            f"""
            UPDATE {app_schema}.asignacion_export_job
            SET estado = 'RUNNING',
                progreso = GREATEST(progreso, 5),
                mensaje = COALESCE(%s, mensaje),
                iniciado_en = COALESCE(iniciado_en, now())
            WHERE id = %s
            RETURNING *
            """,
            (mensaje, job_id),
        )
        return cur.fetchone()


def mark_export_job_done(conn, *args, **kwargs) -> Optional[dict]:
    tenant = None
    pos_args = list(args)
    if pos_args and not isinstance(pos_args[0], int):
        tenant = pos_args.pop(0)
    job_id = pos_args[0] if len(pos_args) > 0 else kwargs.get("job_id")
    archivo_path = pos_args[1] if len(pos_args) > 1 else kwargs.get("archivo_path")
    archivo_nombre = pos_args[2] if len(pos_args) > 2 else kwargs.get("archivo_nombre")
    archivo_size = pos_args[3] if len(pos_args) > 3 else kwargs.get("archivo_size")

    ttl_hours = kwargs.get("ttl_hours", 24)
    if ttl_hours is None:
        ttl_hours = 24
    ttl_hours = max(1, int(ttl_hours))
    mensaje = kwargs.get("mensaje")

    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        ensure_asignacion_tables(conn, tenant)
        cur.execute(
            f"""
            UPDATE {app_schema}.asignacion_export_job
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
        return cur.fetchone()


def mark_export_job_error(conn, *args, **kwargs) -> Optional[dict]:
    tenant = None
    pos_args = list(args)
    if pos_args and not isinstance(pos_args[0], int):
        tenant = pos_args.pop(0)
    job_id = pos_args[0] if len(pos_args) > 0 else kwargs.get("job_id")
    error_msg = pos_args[1] if len(pos_args) > 1 else kwargs.get("error_msg")
    mensaje = pos_args[2] if len(pos_args) > 2 else kwargs.get("mensaje")

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        ensure_asignacion_tables(conn, tenant)
        cur.execute(
            f"""
            UPDATE {app_schema}.asignacion_export_job
            SET estado = 'ERROR',
                mensaje = COALESCE(%s, mensaje),
                error_msg = %s,
                finalizado_en = now()
            WHERE id = %s
            RETURNING *
            """,
            (mensaje, error_msg, job_id),
        )
        return cur.fetchone()


def _asig_event_log_has_usuario_id(conn, app_schema: str = "arbimaps_app") -> bool:
    global _ASIG_EVENT_LOG_HAS_USUARIO_ID
    if _ASIG_EVENT_LOG_HAS_USUARIO_ID is not None:
        return _ASIG_EVENT_LOG_HAS_USUARIO_ID

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = 'asignacion_event_log'
              AND column_name = 'usuario_id'
            LIMIT 1
            """,
            (app_schema,),
        )
        _ASIG_EVENT_LOG_HAS_USUARIO_ID = bool(cur.fetchone())
    return _ASIG_EVENT_LOG_HAS_USUARIO_ID


def insert_asignacion_event(conn, *args, **kwargs) -> None:
    tenant = None
    if len(args) == 5:
        tenant, asignacion_id, evento, mensaje, usuario = args
    elif len(args) == 4:
        asignacion_id, evento, mensaje, usuario = args
    else:
        tenant = kwargs.get("tenant")
        asignacion_id = kwargs.get("asignacion_id")
        evento = kwargs.get("evento")
        mensaje = kwargs.get("mensaje")
        usuario = kwargs.get("usuario")

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    usuario_id: Optional[int] = None
    if usuario and _asig_event_log_has_usuario_id(conn, app_schema):
        with conn.cursor(cursor_factory=RealDictCursor) as cur_user:
            cur_user.execute(
                f"""
                SELECT id_global
                FROM {app_schema}.users
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
        if _asig_event_log_has_usuario_id(conn, app_schema):
            cur.execute(
                f"""
                INSERT INTO {app_schema}.asignacion_event_log (asignacion_id, evento, usuario, mensaje, usuario_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (asignacion_id, evento, usuario, mensaje, usuario_id),
            )
        else:
            cur.execute(
                f"""
                INSERT INTO {app_schema}.asignacion_event_log (asignacion_id, evento, usuario, mensaje)
                VALUES (%s, %s, %s, %s)
                """,
                (asignacion_id, evento, usuario, mensaje),
            )


def safe_log_event(*args, **kwargs) -> None:
    if len(args) >= 5:
        # new multitenant signature: safe_log_event(conn, tenant, asignacion_id, evento, mensaje, usuario)
        conn = args[0]
        tenant = args[1]
        asignacion_id = args[2]
        evento = args[3]
        mensaje = args[4]
        usuario = args[5] if len(args) > 5 else kwargs.get("usuario")
        
        in_transaction = not conn.autocommit
        try:
            ensure_asignacion_tables(conn, tenant)
            with conn.cursor() as sp_cur:
                if in_transaction:
                    sp_cur.execute("SAVEPOINT safe_log_event_sp")
                try:
                    insert_asignacion_event(conn, tenant, asignacion_id, evento, mensaje, usuario)
                    if in_transaction:
                        sp_cur.execute("RELEASE SAVEPOINT safe_log_event_sp")
                except Exception as exc:
                    if in_transaction:
                        sp_cur.execute("ROLLBACK TO SAVEPOINT safe_log_event_sp")
                    pg_code = str(getattr(exc, "pgcode", "") or "")
                    if pg_code == pg_errorcodes.INVALID_TEXT_REPRESENTATION:
                        fallback_evento = "CREADA"
                        fallback_mensaje = f"[{evento}] {mensaje or ''}".strip()
                        if in_transaction:
                            sp_cur.execute("SAVEPOINT safe_log_event_fallback_sp")
                        try:
                            insert_asignacion_event(conn, tenant, asignacion_id, fallback_evento, fallback_mensaje, usuario)
                            if in_transaction:
                                sp_cur.execute("RELEASE SAVEPOINT safe_log_event_fallback_sp")
                        except Exception as fallback_exc:
                            if in_transaction:
                                sp_cur.execute("ROLLBACK TO SAVEPOINT safe_log_event_fallback_sp")
                            raise fallback_exc
                    else:
                        raise exc
        except Exception as exc:
            logger.warning(
                "safe_log_event (multitenant) failed asignacion_id=%s evento=%s usuario=%s error=%s",
                asignacion_id,
                evento,
                usuario,
                exc,
            )
    else:
        # old signature: safe_log_event(asignacion_id, evento, mensaje, usuario)
        if len(args) == 4:
            asignacion_id, evento, mensaje, usuario = args
        else:
            asignacion_id = kwargs.get("asignacion_id")
            evento = kwargs.get("evento")
            mensaje = kwargs.get("mensaje")
            usuario = kwargs.get("usuario")
            
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


def fetch_predios_asignados(conn, *args, **kwargs) -> list[dict]:
    tenant = None
    if len(args) == 2:
        tenant, numeros = args
    elif len(args) == 1:
        numeros = args[0]
    else:
        tenant = kwargs.get("tenant")
        numeros = kwargs.get("numeros")

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT ap.numero_predial_nacional, a.usuario_asignado, ap.asignacion_id
            FROM {app_schema}.asignacion_predio ap
            JOIN {app_schema}.asignacion a ON ap.asignacion_id = a.id
            WHERE ap.numero_predial_nacional = ANY(%s)
              AND ap.activo IS DISTINCT FROM FALSE
              AND a.estado IS DISTINCT FROM 'CERRADA'
            """,
            (numeros,),
        )
        return cur.fetchall()


def update_asignacion_fields(*args, **kwargs) -> None:
    conn = None
    tenant = None
    if len(args) >= 3:
        conn = args[0]
        tenant = args[1]
        asignacion_id = args[2]
        has_conn = True
    else:
        asignacion_id = args[0] if len(args) > 0 else kwargs.get("asignacion_id")
        tenant = kwargs.get("tenant")
        has_conn = False

    estado = kwargs.get("estado")
    work_datasetname = kwargs.get("work_datasetname")
    error_msg = kwargs.get("error_msg")
    predios_soporte_extra = kwargs.get("predios_soporte_extra")
    enlace_control_calidad = kwargs.get("enlace_control_calidad")
    enlace_soporte = kwargs.get("enlace_soporte")
    enlace_digitalizacion = kwargs.get("enlace_digitalizacion")
    enlace_devolucion = kwargs.get("enlace_devolucion")
    usuario_reconocedor = kwargs.get("usuario_reconocedor")
    usuario_reconocedor_id = kwargs.get("usuario_reconocedor_id")

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

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
    if enlace_control_calidad is not None:
        sets.append("enlace_control_calidad=%s")
        params.append(enlace_control_calidad)
    if enlace_soporte is not None:
        sets.append("enlace_soporte=%s")
        params.append(enlace_soporte)
    if enlace_digitalizacion is not None:
        sets.append("enlace_digitalizacion=%s")
        params.append(enlace_digitalizacion)
    if enlace_devolucion is not None:
        sets.append("enlace_devolucion=%s")
        params.append(enlace_devolucion)
    if usuario_reconocedor is not None:
        sets.append("usuario_reconocedor=%s")
        params.append(usuario_reconocedor)
    if usuario_reconocedor_id is not None:
        sets.append("usuario_reconocedor_id=%s")
        params.append(usuario_reconocedor_id)
    if not sets:
        return
    params.append(asignacion_id)
    sql = f"UPDATE {app_schema}.asignacion SET {', '.join(sets)} WHERE id=%s"

    if has_conn:
        with conn.cursor() as cur:
            ensure_asignacion_tables(conn, tenant)
            cur.execute(sql, tuple(params))
    else:
        with db_conn() as conn:
            with conn.cursor() as cur:
                ensure_asignacion_tables(conn, tenant)
                cur.execute(sql, tuple(params))
            conn.commit()


def list_usuarios_disponibles(
    conn,
    tenant=None,
    *,
    supervisor_id: int | None = None,
    only_reconocedores: bool = False,
) -> list[dict]:
    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    filters: list[str] = []
    params: list[object] = []
    if only_reconocedores:
        filters.append("LOWER(COALESCE(u.rol, '')) = 'reconocedor'")
    if supervisor_id is not None:
        filters.append("NULLIF(TRIM(u.supervisor), '') = %s::text")
        params.append(supervisor_id)

    extra_where = ""
    if filters:
        extra_where = " AND " + " AND ".join(filters)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
                u.id_global,
                u.username,
                u.first_name,
                u.last_name,
                u.rol,
                u.supervisor
            FROM {app_schema}.users u
            LEFT JOIN (
                SELECT DISTINCT a.usuario_asignado
                FROM {app_schema}.asignacion a
                JOIN {app_schema}.asignacion_predio ap
                  ON ap.asignacion_id = a.id
                 AND ap.activo IS DISTINCT FROM FALSE
                WHERE a.estado IS DISTINCT FROM 'CERRADA'
            ) a ON a.usuario_asignado = u.username
            WHERE u.activo IS TRUE
              AND a.usuario_asignado IS NULL
              {extra_where}
            ORDER BY u.first_name, u.last_name, u.username
            """,
            tuple(params),
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
    app_schema = "arbimaps_app"
    if schema_main and not isinstance(schema_main, str) and hasattr(schema_main, "schemas"):
        app_schema = schema_main.schemas.app

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
              p.{numero_field} AS numero_predial_nacional,
              (
                SELECT a.usuario_asignado
                FROM {app_schema}.asignacion a
                JOIN {app_schema}.asignacion_predio ap ON ap.asignacion_id = a.id
                WHERE ap.numero_predial_nacional = p.{numero_field}
                  AND ap.activo IS DISTINCT FROM FALSE
                  AND a.estado IS DISTINCT FROM 'CERRADA'
                LIMIT 1
              ) AS asignado_a,
              (
                SELECT a.creado_por
                FROM {app_schema}.asignacion a
                JOIN {app_schema}.asignacion_predio ap2 ON ap2.asignacion_id = a.id
                WHERE ap2.numero_predial_nacional = p.{numero_field}
                  AND ap2.activo IS DISTINCT FROM FALSE
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


def list_eventos_asignacion(conn, *args, **kwargs) -> list[dict]:
    tenant = None
    if len(args) == 2:
        tenant, asignacion_id = args
    elif len(args) == 1:
        asignacion_id = args[0]
    else:
        tenant = kwargs.get("tenant")
        asignacion_id = kwargs.get("asignacion_id")

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT id, asignacion_id, evento, usuario, mensaje, creado_en
            FROM {app_schema}.asignacion_event_log
            WHERE asignacion_id = %s
            ORDER BY id ASC
            """,
            (asignacion_id,),
        )
        return cur.fetchall()


def allocate_asignacion_retorno_version(conn, *args, **kwargs) -> int:
    tenant = None
    if len(args) == 2:
        tenant, asignacion_id = args
    elif len(args) == 1:
        asignacion_id = args[0]
    else:
        tenant = kwargs.get("tenant")
        asignacion_id = kwargs.get("asignacion_id")

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        ensure_asignacion_tables(conn, tenant, force=True)
        cur.execute(
            f"""
            SELECT id
            FROM {app_schema}.asignacion
            WHERE id = %s
            FOR UPDATE
            """,
            (asignacion_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Asignacion no encontrada: {asignacion_id}")
        cur.execute(
            f"""
            SELECT COALESCE(MAX(version), 0) + 1 AS next_version
            FROM {app_schema}.asignacion_retorno
            WHERE asignacion_id = %s
            """,
            (asignacion_id,),
        )
        next_row = cur.fetchone() or {}
        return int(next_row.get("next_version") or 1)


def crear_notificacion(
    conn,
    *,
    tenant=None,
    cod_tramite=None,
    id_asignacion=None,
    id_usuario_destino: int,
    id_usuario_origen: int | None,
    rol_origen=None,
    rol_destino=None,
    tipo="asignacion",
    titulo: str,
    mensaje: str,
    url_destino=None,
    prioridad="normal",
    fecha_limite=None,
    metadata=None,
):
    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    metadata_value = json.dumps(metadata, ensure_ascii=False) if metadata is not None else None
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {app_schema}.notificaciones (
                cod_tramite,
                id_asignacion,
                id_usuario_destino,
                id_usuario_origen,
                rol_origen,
                rol_destino,
                tipo,
                titulo,
                mensaje,
                url_destino,
                prioridad,
                fecha_limite,
                metadata
            )
            VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb
            )
            """,
            (
                cod_tramite,
                id_asignacion,
                id_usuario_destino,
                id_usuario_origen,
                rol_origen,
                rol_destino,
                tipo,
                titulo,
                mensaje,
                url_destino,
                prioridad,
                fecha_limite,
                metadata_value,
            ),
        )


def safe_crear_notificacion(conn, tenant=None, **kwargs) -> bool:
    """
    Intenta crear la notificacion sin romper la transaccion principal.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT notif_savepoint")
            try:
                crear_notificacion(conn, tenant=tenant, **kwargs)
                cur.execute("RELEASE SAVEPOINT notif_savepoint")
                return True
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT notif_savepoint")
                cur.execute("RELEASE SAVEPOINT notif_savepoint")
                logger.exception("No se pudo crear la notificacion")
                return False
    except Exception:
        logger.exception("No se pudo preparar el savepoint de notificaciones")
        return False


def create_asignacion_retorno(conn, *args, **kwargs) -> dict:
    tenant = None
    if len(args) >= 4:
        tenant, asignacion_id, version, datasetname_retorno = args[:4]
    elif len(args) == 3:
        asignacion_id, version, datasetname_retorno = args
    else:
        tenant = kwargs.get("tenant")
        asignacion_id = kwargs.get("asignacion_id")
        version = kwargs.get("version")
        datasetname_retorno = kwargs.get("datasetname_retorno")

    archivo_nombre_original = kwargs.get("archivo_nombre_original")
    archivo_nombre_guardado = kwargs.get("archivo_nombre_guardado")
    archivo_sha256 = kwargs.get("archivo_sha256")
    correlation_id = kwargs.get("correlation_id")
    creado_por = kwargs.get("creado_por")

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        ensure_asignacion_tables(conn, tenant, force=True)
        cur.execute(
            f"""
            INSERT INTO {app_schema}.asignacion_retorno (
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


def update_asignacion_retorno(conn, *args, **kwargs) -> Optional[dict]:
    tenant = None
    if len(args) == 2:
        tenant, retorno_id = args
    elif len(args) == 1:
        retorno_id = args[0]
    else:
        tenant = kwargs.get("tenant")
        retorno_id = kwargs.get("retorno_id")

    estado = kwargs.get("estado")
    resultado_validacion = kwargs.get("resultado_validacion")
    removed_predios = kwargs.get("removed_predios")
    synced_predios = kwargs.get("synced_predios")
    error_msg = kwargs.get("error_msg")
    sincronizado_en_now = kwargs.get("sincronizado_en_now", False)

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

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
        ensure_asignacion_tables(conn, tenant, force=True)
        cur.execute(
            f"""
            UPDATE {app_schema}.asignacion_retorno
            SET {', '.join(sets)}
            WHERE id = %s
            RETURNING *
            """,
            tuple(params),
        )
        return cur.fetchone()


def get_asignacion_work_dataset(conn, *args, **kwargs) -> Optional[dict]:
    tenant = None
    if len(args) == 2:
        tenant, asignacion_id = args
    elif len(args) == 1:
        asignacion_id = args[0]
    else:
        tenant = kwargs.get("tenant")
        asignacion_id = kwargs.get("asignacion_id")

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT id, work_datasetname
            FROM {app_schema}.asignacion
            WHERE id = %s
            """,
            (asignacion_id,),
        )
        return cur.fetchone()


def get_recent_retorno_by_sha256(conn, *args, **kwargs) -> Optional[dict]:
    tenant = None
    if len(args) == 3:
        tenant, asignacion_id, archivo_sha256 = args
    elif len(args) == 2:
        if isinstance(args[0], (int, str)) or args[0] is None:
            asignacion_id, archivo_sha256 = args
        else:
            tenant, asignacion_id = args
            archivo_sha256 = kwargs.get("archivo_sha256")
    else:
        tenant = kwargs.get("tenant")
        asignacion_id = kwargs.get("asignacion_id")
        archivo_sha256 = kwargs.get("archivo_sha256")

    if not archivo_sha256:
        return None

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT *
            FROM {app_schema}.asignacion_retorno
            WHERE asignacion_id = %s
              AND archivo_sha256 = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (asignacion_id, archivo_sha256),
        )
        return cur.fetchone()


def get_asignacion_for_paquete(conn, *args, **kwargs) -> Optional[dict]:
    tenant = None
    if len(args) == 2:
        tenant, asignacion_id = args
    elif len(args) == 1:
        asignacion_id = args[0]
    else:
        tenant = kwargs.get("tenant")
        asignacion_id = kwargs.get("asignacion_id")

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT id, work_datasetname, datasetname_main, titulo, usuario_asignado
            FROM {app_schema}.asignacion
            WHERE id = %s
            """,
            (asignacion_id,),
        )
        return cur.fetchone()


def list_asignaciones(conn, tenant=None) -> list[dict]:
    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Evita que el endpoint quede "colgado" por bloqueos DDL/locks largos.
        cur.execute("SET LOCAL lock_timeout = '2s'")
        cur.execute("SET LOCAL statement_timeout = '20s'")
        cur.execute(
            f"""
            SELECT
                a.*,
                CASE
                    WHEN COALESCE(pub_main.publicado_main, FALSE) THEN 'SINCRONIZADO'
                    WHEN a.estado::text = 'CERRADA' THEN a.estado::text
                    ELSE a.estado::text
                END AS estado_resuelto,
                COALESCE(coo.first_name, cu.first_name) AS coord_first_name,
                COALESCE(coo.last_name, cu.last_name) AS coord_last_name,
                COALESCE(coo.username, a.creado_por) AS creado_por,
                cu.rol AS creado_por_rol,
                au.first_name AS asignado_first_name,
                au.last_name AS asignado_last_name,
                CASE
                    WHEN COALESCE(pub_main.publicado_main, FALSE) AND COALESCE(NULLIF(BTRIM(a.work_datasetname::text), ''), '') = ''
                        THEN GREATEST(COALESCE(ret.synced_predios, 0), COALESCE(ret.covered_predios, 0))
                    ELSE stats.total_activos
                END AS total_activos,
                CASE
                    WHEN COALESCE(pub_main.publicado_main, FALSE) AND COALESCE(NULLIF(BTRIM(a.work_datasetname::text), ''), '') = ''
                        THEN GREATEST(COALESCE(ret.expected_predios, 0) - COALESCE(ret.covered_predios, 0), 0)
                    ELSE stats.total_inactivos
                END AS total_inactivos,
                CASE
                    WHEN COALESCE(pub_main.publicado_main, FALSE) AND COALESCE(NULLIF(BTRIM(a.work_datasetname::text), ''), '') = ''
                        THEN GREATEST(COALESCE(ret.synced_predios, 0) - COALESCE(ret.covered_predios, 0), 0)
                    ELSE GREATEST(
                        COALESCE(a.predios_soporte_extra, 0),
                        COALESCE(ret.synced_predios, 0) - COALESCE(stats.total_activos, 0),
                        COALESCE(stats.total_nuevos_raw, 0)
                    )
                END AS total_nuevos
            FROM {app_schema}.asignacion a
            LEFT JOIN {app_schema}.users cu ON cu.username = a.creado_por
            LEFT JOIN {app_schema}.users au ON au.username = a.usuario_asignado
            LEFT JOIN {app_schema}.users coo ON coo.id_global = a.coordinador_asignado_id
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*) FILTER (WHERE ap.activo IS DISTINCT FROM FALSE) AS total_activos,
                    COUNT(*) FILTER (WHERE ap.activo IS FALSE) AS total_inactivos,
                    COUNT(*) FILTER (WHERE ap.predio_t_id IS NULL) AS total_nuevos_raw
                FROM {app_schema}.asignacion_predio ap
                WHERE ap.asignacion_id = a.id
            ) stats ON TRUE
            LEFT JOIN LATERAL (
                SELECT ar.synced_predios, ar.expected_predios, ar.covered_predios
                FROM {app_schema}.asignacion_retorno ar
                WHERE ar.asignacion_id = a.id
                  AND ar.estado IN ('SINCRONIZADO', 'VALIDADO')
                ORDER BY ar.id DESC
                LIMIT 1
            ) ret ON TRUE
            LEFT JOIN LATERAL (
                SELECT TRUE AS publicado_main
                FROM {app_schema}.asignacion_event_log el
                WHERE el.asignacion_id = a.id
                  AND (
                        el.evento::text = 'PUBLICACION_MAIN'
                     OR el.mensaje LIKE '[PUBLICACION_MAIN]%'
                  )
                ORDER BY el.id DESC
                LIMIT 1
            ) pub_main ON TRUE
            WHERE a.estado::text <> 'CERRADA'
               OR COALESCE(pub_main.publicado_main, FALSE)
            ORDER BY a.id DESC
            """
        )
        return cur.fetchall()


def get_asignacion_detalle(conn, *args, **kwargs) -> Optional[dict]:
    tenant = None
    if len(args) == 2:
        tenant, asignacion_id = args
    elif len(args) == 1:
        asignacion_id = args[0]
    else:
        tenant = kwargs.get("tenant")
        asignacion_id = kwargs.get("asignacion_id")

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
                a.*,
                CASE
                    WHEN COALESCE(pub_main.publicado_main, FALSE) THEN 'SINCRONIZADO'
                    WHEN a.estado::text = 'CERRADA' THEN a.estado::text
                    ELSE a.estado::text
                END AS estado_resuelto,
                COALESCE(coo.first_name, cu.first_name) AS coord_first_name,
                COALESCE(coo.last_name, cu.last_name) AS coord_last_name,
                COALESCE(coo.username, a.creado_por) AS creado_por,
                cu.rol AS creado_por_rol,
                au.first_name AS asignado_first_name,
                au.last_name AS asignado_last_name,
                CASE
                    WHEN COALESCE(pub_main.publicado_main, FALSE) AND COALESCE(NULLIF(BTRIM(a.work_datasetname::text), ''), '') = ''
                        THEN GREATEST(COALESCE(ret.synced_predios, 0), COALESCE(ret.covered_predios, 0))
                    ELSE stats.total_activos
                END AS total_activos,
                CASE
                    WHEN COALESCE(pub_main.publicado_main, FALSE) AND COALESCE(NULLIF(BTRIM(a.work_datasetname::text), ''), '') = ''
                        THEN GREATEST(COALESCE(ret.expected_predios, 0) - COALESCE(ret.covered_predios, 0), 0)
                    ELSE stats.total_inactivos
                END AS total_inactivos,
                CASE
                    WHEN COALESCE(pub_main.publicado_main, FALSE) AND COALESCE(NULLIF(BTRIM(a.work_datasetname::text), ''), '') = ''
                        THEN GREATEST(COALESCE(ret.synced_predios, 0) - COALESCE(ret.covered_predios, 0), 0)
                    ELSE GREATEST(
                        COALESCE(a.predios_soporte_extra, 0),
                        COALESCE(ret.synced_predios, 0) - COALESCE(stats.total_activos, 0),
                        COALESCE(stats.total_nuevos_raw, 0)
                    )
                END AS total_nuevos
            FROM {app_schema}.asignacion a
            LEFT JOIN {app_schema}.users cu ON cu.username = a.creado_por
            LEFT JOIN {app_schema}.users au ON au.username = a.usuario_asignado
            LEFT JOIN {app_schema}.users coo ON coo.id_global = a.coordinador_asignado_id
            LEFT JOIN (
                SELECT
                    ap.asignacion_id,
                    COUNT(*) FILTER (WHERE ap.activo IS DISTINCT FROM FALSE) AS total_activos,
                    COUNT(*) FILTER (WHERE ap.activo IS FALSE) AS total_inactivos,
                    COUNT(*) FILTER (WHERE ap.predio_t_id IS NULL) AS total_nuevos_raw
                FROM {app_schema}.asignacion_predio ap
                GROUP BY ap.asignacion_id
            ) stats ON stats.asignacion_id = a.id
            LEFT JOIN LATERAL (
                SELECT ar.synced_predios, ar.expected_predios, ar.covered_predios
                FROM {app_schema}.asignacion_retorno ar
                WHERE ar.asignacion_id = a.id
                  AND ar.estado IN ('SINCRONIZADO', 'VALIDADO')
                ORDER BY ar.id DESC
                LIMIT 1
            ) ret ON TRUE
            LEFT JOIN LATERAL (
                SELECT TRUE AS publicado_main
                FROM {app_schema}.asignacion_event_log el
                WHERE el.asignacion_id = a.id
                  AND (
                        el.evento::text = 'PUBLICACION_MAIN'
                     OR el.mensaje LIKE '[PUBLICACION_MAIN]%'
                  )
                ORDER BY el.id DESC
                LIMIT 1
            ) pub_main ON TRUE
            WHERE a.id = %s
            LIMIT 1
            """,
            (asignacion_id,),
        )
        return cur.fetchone()


def list_predios_asignacion(conn, *args, **kwargs) -> list[dict]:
    tenant = None
    if len(args) == 2:
        tenant, asignacion_id = args
    elif len(args) == 1:
        asignacion_id = args[0]
    else:
        tenant = kwargs.get("tenant")
        asignacion_id = kwargs.get("asignacion_id")

    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
                ap.id,
                ap.numero_predial_nacional,
                ap.predio_t_id,
                ap.activo,
                ap.creado_por,
                ap.creado_en
            FROM {app_schema}.asignacion_predio ap
            WHERE ap.asignacion_id = %s
            ORDER BY ap.activo DESC, ap.numero_predial_nacional ASC
            """,
            (asignacion_id,),
        )
        return cur.fetchall()


def insert_asignacion_comentario(
    conn,
    tenant,
    asignacion_id: int,
    usuario_id: Optional[int],
    usuario: Optional[str],
    rol: Optional[str],
    comentario: str,
    estado_origen: Optional[str],
    estado_destino: Optional[str],
    enlace: Optional[str] = None
) -> None:
    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {app_schema}.asignacion_comentario (
                asignacion_id, usuario_id, usuario, rol, comentario, estado_origen, estado_destino, enlace
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                asignacion_id,
                usuario_id,
                usuario,
                rol,
                comentario,
                estado_origen,
                estado_destino,
                enlace
            ),
        )


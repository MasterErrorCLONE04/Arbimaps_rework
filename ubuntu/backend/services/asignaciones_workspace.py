import logging
import os
import tempfile
from typing import Callable, List, Optional
from psycopg2 import errorcodes, sql
from psycopg2.extras import RealDictCursor

from services import asignaciones_export as export_service
from services import asignaciones_workspace_schema as workspace_schema_service
from services import asignaciones_workspace_sql as workspace_sql_service
from tenants.context import TenantContext
from tenants.sql import app_table, tenant_table, work_table


_ARB_DIRECT_PREDIO_TABLES = (
    ("arb_avaluovalor", "arb_predio_avaluo"),
    ("arb_direccion", "arb_predio_direccion"),
    ("arb_informacionph", "arb_predio"),
    ("arb_marca", "predio"),
    ("arb_novedadfmivalor", "arb_predio_novedad_fmi"),
    ("arb_novedadnumeropredialvalor", "arb_predio_novedad_numero_predial"),
    ("arb_referenciaregistralsistemaantiguovalor", "arb_predio_referencia_registral_sistema_antiguo"),
    ("arb_terrenohistorico", "predio"),
    ("arb_predio_tramite", "predio"),
    ("arb_puntoreferencia", "predio"),
    ("arb_terreno", "predio"),
    ("arb_derechointeresadofuente", "predio"),
)

_ARB_ATTACHMENT_SPECS = (
    ("arb_adjuntofuenteadministrativavalor", "arb_derechointeresadofuente", "arb_derechointersdfnte_fa_adjunto"),
    ("arb_adjuntointeresadovalor", "arb_derechointeresadofuente", "arb_derechointersdfnte_i_adjunto"),
    ("arb_adjuntopuntoreferenciavalor", "arb_puntoreferencia", "arb_puntoreferencia_adjunto"),
    ("arb_adjuntoterrenovalor", "arb_terreno", "arb_terreno_adjunto"),
)

_ARB_SCHEMA_PARITY_TABLES = frozenset(
    {
        "arb_predio",
        "arb_construccion",
        "arb_unidadconstruccion",
        "arb_caracteristicasunidadconstruccion",
        "arb_adjuntounidadconstruccionvalor",
        "arb_tramite",
        *[name for name, _ in _ARB_DIRECT_PREDIO_TABLES],
        *[name for name, _, _ in _ARB_ATTACHMENT_SPECS],
    }
)

_ARB_TILI_TID_REQUIRED_TABLES = frozenset(
    {
        "arb_construccion",
        "arb_unidadconstruccion",
        "arb_caracteristicasunidadconstruccion",
        "arb_puntoreferencia",
        "arb_terreno",
        "arb_derechointeresadofuente",
        "arb_tramite",
    }
)


logger = logging.getLogger(__name__)


def _arb_disable_workspace_unique_constraints(
    conn,
    tenant: TenantContext,
    schema_work: str,
) -> None:
    """
    Re-scope unique constraints/indexes in workspace to include t_basket.
    This keeps per-dataset integrity in shared workspace instead of dropping uniqueness.
    """
    schema_sql = (schema_work or "").strip().strip('"')
    if not schema_sql:
        raise export_service.ExportServiceError(
            status_code=500,
            detail="schema_work no definido para ajustar integridad del workspace Arbimaps.",
        )

    with conn.cursor() as cur:
        try:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"ddl_{schema_sql}",))
        except Exception as exc:
            pg_code = str(getattr(exc, "pgcode", "") or "")
            if pg_code in {errorcodes.LOCK_NOT_AVAILABLE, errorcodes.DEADLOCK_DETECTED}:
                raise export_service.ExportServiceError(
                    status_code=503,
                    detail=f"Alta concurrencia transaccional en {schema_sql}. El sistema esta ajustando reglas temporalmente. Reintente en unos segundos.",
                ) from exc
            raise

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                rel.relname AS table_name,
                con.conname AS constraint_name,
                COALESCE(
                    ARRAY_AGG(att.attname ORDER BY k.ord)
                    FILTER (WHERE att.attname IS NOT NULL),
                    '{}'::text[]
                ) AS columns
            FROM pg_constraint con
            JOIN pg_class rel
              ON rel.oid = con.conrelid
            JOIN pg_namespace n
              ON n.oid = rel.relnamespace
            LEFT JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
              ON TRUE
            LEFT JOIN pg_attribute att
              ON att.attrelid = rel.oid
             AND att.attnum = k.attnum
            WHERE n.nspname = %s
              AND con.contype = 'u'
            GROUP BY rel.relname, con.conname
            ORDER BY rel.relname, con.conname
            """,
            (schema_sql,),
        )
        unique_constraints = cur.fetchall() or []

    for row in unique_constraints:
        table_name = str(row.get("table_name") or "").strip()
        constraint_name = str(row.get("constraint_name") or "").strip()
        if not table_name or not constraint_name or table_name.startswith("t_ili2db"):
            continue

        columns = [str(c).strip() for c in (row.get("columns") or []) if c]
        if not columns:
            continue
        if "t_basket" in columns:
            continue
        if "t_basket" not in set(_get_table_columns(conn, schema_sql, table_name)):
            continue

        cols_sql = sql.SQL(", ").join(sql.Identifier(col) for col in [*columns, "t_basket"])
        try:
            with conn.cursor() as cur:
                cur.execute("SAVEPOINT ws_scope_uq")
                cur.execute(
                    sql.SQL("ALTER TABLE {}.{} DROP CONSTRAINT IF EXISTS {} CASCADE").format(
                        sql.Identifier(schema_sql),
                        sql.Identifier(table_name),
                        sql.Identifier(constraint_name),
                    )
                )
                cur.execute(
                    sql.SQL("ALTER TABLE {}.{} ADD CONSTRAINT {} UNIQUE ({})").format(
                        sql.Identifier(schema_sql),
                        sql.Identifier(table_name),
                        sql.Identifier(constraint_name),
                        cols_sql,
                    )
                )
                cur.execute("RELEASE SAVEPOINT ws_scope_uq")
        except Exception as exc:
            with conn.cursor() as cur:
                cur.execute("ROLLBACK TO SAVEPOINT ws_scope_uq")
                cur.execute("RELEASE SAVEPOINT ws_scope_uq")
            pg_code = str(getattr(exc, "pgcode", "") or "")
            if pg_code in {
                errorcodes.INSUFFICIENT_PRIVILEGE,
                errorcodes.LOCK_NOT_AVAILABLE,
                errorcodes.DEADLOCK_DETECTED,
            }:
                logger.warning(
                    "Workspace integrity rescope skipped for constraint %s.%s.%s (%s): %s",
                    schema_sql,
                    table_name,
                    constraint_name,
                    pg_code or "no_pgcode",
                    exc,
                )
                continue
            if pg_code == errorcodes.UNIQUE_VIOLATION:
                raise export_service.ExportServiceError(
                    status_code=409,
                    detail=(
                        f"No se pudo ajustar integridad en {schema_sql}.{table_name}.{constraint_name} "
                        "porque hay duplicados dentro del mismo dataset (t_basket)."
                    ),
                ) from exc
            raise export_service.ExportServiceError(
                status_code=500,
                detail=(
                    f"Fallo al ajustar constraint unico {schema_sql}.{table_name}.{constraint_name}: "
                    f"{exc}"
                ),
            ) from exc

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                c.relname AS table_name,
                i.relname AS index_name,
                COALESCE(
                    ARRAY_AGG(att.attname ORDER BY k.ord)
                    FILTER (WHERE k.attnum > 0 AND att.attname IS NOT NULL),
                    '{}'::text[]
                ) AS columns,
                COALESCE(BOOL_OR(k.attnum = 0), false) AS has_expression,
                pg_get_expr(ix.indpred, ix.indrelid) AS predicate
            FROM pg_index ix
            JOIN pg_class i
              ON i.oid = ix.indexrelid
            JOIN pg_class c
              ON c.oid = ix.indrelid
            JOIN pg_namespace n
              ON n.oid = c.relnamespace
            LEFT JOIN LATERAL unnest(ix.indkey::int2[]) WITH ORDINALITY AS k(attnum, ord)
              ON TRUE
            LEFT JOIN pg_attribute att
              ON att.attrelid = c.oid
             AND att.attnum = k.attnum
            WHERE n.nspname = %s
              AND ix.indisunique = TRUE
              AND ix.indisprimary = FALSE
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_constraint con
                  WHERE con.conindid = ix.indexrelid
              )
            GROUP BY c.relname, i.relname, ix.indpred, ix.indrelid
            ORDER BY c.relname, i.relname
            """,
            (schema_sql,),
        )
        unique_indexes = cur.fetchall() or []

    for row in unique_indexes:
        table_name = str(row.get("table_name") or "").strip()
        index_name = str(row.get("index_name") or "").strip()
        if not table_name or not index_name or table_name.startswith("t_ili2db"):
            continue

        columns = [str(c).strip() for c in (row.get("columns") or []) if c]
        has_expression = bool(row.get("has_expression"))
        predicate = str(row.get("predicate") or "").strip()
        if not columns:
            continue
        if "t_basket" in columns:
            continue
        if has_expression:
            continue
        if "t_basket" not in set(_get_table_columns(conn, schema_sql, table_name)):
            continue

        cols_sql = sql.SQL(", ").join(sql.Identifier(col) for col in [*columns, "t_basket"])
        create_stmt = sql.SQL("CREATE UNIQUE INDEX {} ON {}.{} ({})").format(
            sql.Identifier(index_name),
            sql.Identifier(schema_sql),
            sql.Identifier(table_name),
            cols_sql,
        )
        if predicate:
            create_stmt = create_stmt + sql.SQL(" WHERE ") + sql.SQL(predicate)

        try:
            with conn.cursor() as cur:
                cur.execute("SAVEPOINT ws_scope_ui")
                cur.execute(
                    sql.SQL("DROP INDEX IF EXISTS {}.{} CASCADE").format(
                        sql.Identifier(schema_sql),
                        sql.Identifier(index_name),
                    )
                )
                cur.execute(create_stmt)
                cur.execute("RELEASE SAVEPOINT ws_scope_ui")
        except Exception as exc:
            with conn.cursor() as cur:
                cur.execute("ROLLBACK TO SAVEPOINT ws_scope_ui")
                cur.execute("RELEASE SAVEPOINT ws_scope_ui")
            pg_code = str(getattr(exc, "pgcode", "") or "")
            if pg_code in {
                errorcodes.INSUFFICIENT_PRIVILEGE,
                errorcodes.LOCK_NOT_AVAILABLE,
                errorcodes.DEADLOCK_DETECTED,
            }:
                logger.warning(
                    "Workspace integrity rescope skipped for index %s.%s (%s): %s",
                    schema_sql,
                    index_name,
                    pg_code or "no_pgcode",
                    exc,
                )
                continue
            if pg_code == errorcodes.UNIQUE_VIOLATION:
                raise export_service.ExportServiceError(
                    status_code=409,
                    detail=(
                        f"No se pudo ajustar integridad en index {schema_sql}.{index_name} "
                        "porque hay duplicados dentro del mismo dataset (t_basket)."
                    ),
                ) from exc
            raise export_service.ExportServiceError(
                status_code=500,
                detail=f"Fallo al ajustar unique index {schema_sql}.{index_name}: {exc}",
            ) from exc

    conn.commit()


def _ensure_workspace_enum_tables_populated(conn, tenant: TenantContext, schema_main: str, schema_work: str) -> None:
    """
    Copia los registros de las tablas de dominio (las que terminan en 'tipo')
    desde el esquema principal (schema_main) al esquema de trabajo (schema_work)
    si estas están vacías, para que ili2pg pueda traducir correctamente las enumeraciones.
    """
    with conn.cursor() as cur:
        try:
            # Buscar todas las tablas del esquema principal que terminen en 'tipo'
            cur.execute(
                """
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = %s AND table_name LIKE '%%tipo'
                """,
                (schema_main,)
            )
            main_tables = set(row[0] for row in cur.fetchall())
            if not main_tables:
                return

            # Buscar todas las tablas del esquema de trabajo que terminen en 'tipo'
            cur.execute(
                """
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = %s AND table_name LIKE '%%tipo'
                """,
                (schema_work,)
            )
            work_tables = set(row[0] for row in cur.fetchall())

            # Solo procesar tablas existentes en ambos esquemas
            tables_to_populate = sorted(list(main_tables.intersection(work_tables)))

            for table in tables_to_populate:
                try:
                    logger.info("Sincronizando tabla de enum %s.%s desde %s", schema_work, table, schema_main)
                    cur.execute(f"INSERT INTO {schema_work}.{table} SELECT * FROM {schema_main}.{table} ON CONFLICT DO NOTHING")
                except Exception as table_err:
                    logger.warning("Fallo al poblar la tabla enum individual %s.%s: %s", schema_work, table, table_err)
        except Exception as e:
            logger.warning("Error general poblando tablas de dominio en workspace: %s", e)


def _qualify(schema: str, table: str) -> str:
    schema = (schema or "").strip().strip('"')
    if not schema:
        return table
    return f"{schema}.{table}"


def _actualizar_predio_ids_desde_workspace_conn(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    schema_work: str,
) -> None:
    workspace_ctx = workspace_schema_service.get_workspace_context(schema_work)
    predio_table = _qualify(schema_work, workspace_ctx.predio_table)
    numero_field = workspace_ctx.predio_numero_field
    with conn.cursor() as cur:
        asignacion_predio_table = app_table(tenant, "asignacion_predio")
        cur.execute(
            f"""
            UPDATE {asignacion_predio_table} ap
            SET predio_t_id = p.t_id
            FROM {predio_table} p
            WHERE BTRIM(ap.numero_predial_nacional::text) = BTRIM(p.{numero_field}::text)
              AND ap.asignacion_id = %s
            """,
            (asignacion_id,),
        )


def actualizar_predio_ids_desde_workspace(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    *,
    strict: bool = False,
) -> None:
    try:
        _actualizar_predio_ids_desde_workspace_conn(conn, tenant, asignacion_id, tenant.schemas.work)
    except Exception as exc:
        logger.exception(
            "actualizar_predio_ids_desde_workspace failed asignacion_id=%s tenant=%s strict=%s",
            asignacion_id,
            tenant.municipality_code,
            strict,
        )
        if strict:
            raise export_service.ExportServiceError(
                status_code=500,
                detail=(
                    f"No fue posible actualizar predio_t_id desde workspace para asignacion {asignacion_id}: {exc}"
                ),
            ) from exc


def prune_workspace_predios(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    work_datasetname: str,
    schema_work: str,
    *,
    keep_new_informal_predios: bool = False,
) -> int:
    if not work_datasetname:
        return 0
    workspace_ctx = workspace_schema_service.get_workspace_context(schema_work)
    if workspace_ctx.model_name == "arb":
        return _prune_workspace_predios_arb(
            conn,
            tenant,
            asignacion_id,
            work_datasetname,
            schema_work,
            keep_new_informal_predios=keep_new_informal_predios,
        )
    predio_table = _qualify(schema_work, workspace_ctx.predio_table)
    numero_field = workspace_ctx.predio_numero_field
    with conn.cursor() as cur:
        asignacion_predio_table = app_table(tenant, "asignacion_predio")
        cur.execute(
            f"""
            DELETE FROM {predio_table} wp
            USING {_qualify(schema_work, 't_ili2db_basket')} wb,
                  {_qualify(schema_work, 't_ili2db_dataset')} wd
            WHERE wp.t_basket = wb.t_id
              AND wb.dataset = wd.t_id
              AND wd.datasetname = %s
              AND NOT EXISTS (
                  SELECT 1
                  FROM {asignacion_predio_table} ap
                  WHERE ap.asignacion_id = %s
                    AND ap.activo IS DISTINCT FROM FALSE
                    AND BTRIM(ap.numero_predial_nacional::text) = BTRIM(wp.{numero_field}::text)
              )
            """,
            (work_datasetname, asignacion_id),
        )
        return cur.rowcount or 0


def _schema_table_names(conn, schema_name: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
            """,
            (schema_name,),
        )
        return {str(row[0]).strip() for row in (cur.fetchall() or []) if row and row[0]}


def _arb_new_informal_predio_condition_sql(conn, schema_work: str, alias: str = "p") -> str:
    predio_cols = set(_get_table_columns(conn, schema_work, "arb_predio"))
    conditions: List[str] = []
    if "condicion_predio" in predio_cols:
        conditions.append(f"LOWER(BTRIM({alias}.condicion_predio::text)) = 'informal'")
    if "id_operacion" in predio_cols:
        conditions.append(f"LEFT(LOWER(BTRIM({alias}.id_operacion::text)), 5) = 'nuevo'")
    if not conditions:
        return "FALSE"
    return "(" + " OR ".join(conditions) + ")"


def _prune_workspace_predios_arb(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    work_datasetname: str,
    schema_work: str,
    *,
    keep_new_informal_predios: bool = False,
) -> int:
    existing_tables = _schema_table_names(conn, schema_work)
    required_tables = {"arb_predio", "t_ili2db_basket", "t_ili2db_dataset"}
    if not required_tables.issubset(existing_tables):
        return 0

    predio_table = _qualify(schema_work, "arb_predio")
    basket_table = _qualify(schema_work, "t_ili2db_basket")
    dataset_table = _qualify(schema_work, "t_ili2db_dataset")

    def has_table(table_name: str) -> bool:
        return table_name in existing_tables

    with conn.cursor() as cur:
        keep_new_filter = ""
        if keep_new_informal_predios:
            new_informal_sql = _arb_new_informal_predio_condition_sql(conn, schema_work, alias="p")
            keep_new_filter = f" AND NOT {new_informal_sql}"

        has_matriz_table = "arb_estructuraprediomatriznpn" in existing_tables
        has_origen_table = "arb_estructurapredioorigennpn" in existing_tables

        matriz_origen_sql = ""
        if has_matriz_table:
            matriz_origen_sql += f"""
                OR EXISTS (
                    SELECT 1
                    FROM "{schema_work}".arb_estructuraprediomatriznpn pm
                    JOIN "{schema_work}".arb_predio p_parent ON (
                        REGEXP_REPLACE(pm.numero_predial_nacional::text, '[^0-9]', '', 'g') IN (
                            REGEXP_REPLACE(p_parent.numero_predial::text, '[^0-9]', '', 'g'),
                            REGEXP_REPLACE(p_parent.numero_predial_anterior::text, '[^0-9]', '', 'g')
                        )
                    )
                    WHERE pm.predio = p.t_id
                      AND BTRIM(ap.numero_predial_nacional::text) = BTRIM(p_parent.numero_predial::text)
                )
            """
        if has_origen_table:
            matriz_origen_sql += f"""
                OR EXISTS (
                    SELECT 1
                    FROM "{schema_work}".arb_estructurapredioorigennpn po
                    JOIN "{schema_work}".arb_predio p_parent ON (
                        REGEXP_REPLACE(po.numero_predial_nacional::text, '[^0-9]', '', 'g') IN (
                            REGEXP_REPLACE(p_parent.numero_predial::text, '[^0-9]', '', 'g'),
                            REGEXP_REPLACE(p_parent.numero_predial_anterior::text, '[^0-9]', '', 'g')
                        )
                    )
                    WHERE po.predio = p.t_id
                      AND BTRIM(ap.numero_predial_nacional::text) = BTRIM(p_parent.numero_predial::text)
                )
            """

        # DEBUG LOGGING FOR DESENGLOVE VALIDATION
        import sys
        print("=== DEBUG DESENGLOVE SYNC ===", file=sys.stderr, flush=True)
        try:
            asignacion_predio_table = app_table(tenant, "asignacion_predio")
            cur.execute(f"SELECT numero_predial_nacional FROM {asignacion_predio_table} WHERE asignacion_id = %s", (asignacion_id,))
            rows_ap = cur.fetchall()
            print(f"Asignacion predios: {[r[0] for r in rows_ap]}", file=sys.stderr, flush=True)

            cur.execute(f"SELECT t_id, numero_predial, condicion_predio, numero_predial_anterior FROM {predio_table}")
            rows_p = cur.fetchall()
            print(f"Workspace predios: {[{'t_id': r[0], 'numero_predial': r[1], 'condicion_predio': r[2], 'numero_predial_anterior': r[3]} for r in rows_p]}", file=sys.stderr, flush=True)

            print("=== WORKSPACE ESTRI TABLAS ===", file=sys.stderr, flush=True)
            for table in sorted(existing_tables):
                if not table.startswith("arb_estructura"):
                    continue
                try:
                    cur.execute(f'SELECT COUNT(*) FROM "{schema_work}"."{table}"')
                    cnt = cur.fetchone()[0]
                    if cnt > 0:
                        cur.execute(f'SELECT * FROM "{schema_work}"."{table}"')
                        cols = [desc[0] for desc in cur.description]
                        rows = cur.fetchall()
                        print(f"Table: {table} (count: {cnt})", file=sys.stderr, flush=True)
                        print(f"  Columns: {cols}", file=sys.stderr, flush=True)
                        for r in rows:
                            row_dict = {}
                            for col, val in zip(cols, r):
                                if hasattr(val, 'desc') or isinstance(val, (bytes, bytearray)):
                                    row_dict[col] = "<geom/binary>"
                                else:
                                    row_dict[col] = str(val)
                            print(f"  Row: {row_dict}", file=sys.stderr, flush=True)
                except Exception as t_err:
                    print(f"Error querying table {table}: {t_err}", file=sys.stderr, flush=True)

        except Exception as log_err:
            print(f"Error logging debug info: {log_err}", file=sys.stderr, flush=True)

        cur.execute("DROP TABLE IF EXISTS _arb_ws_unassigned_predio")
        asignacion_predio_table = app_table(tenant, "asignacion_predio")
        cur.execute(
            f"""
            CREATE TEMP TABLE _arb_ws_unassigned_predio AS
            SELECT p.t_id
            FROM {predio_table} p
            JOIN {basket_table} b ON b.t_id = p.t_basket
            JOIN {dataset_table} d ON d.t_id = b.dataset
            WHERE d.datasetname = %s
              AND NOT EXISTS (
                  SELECT 1
                  FROM {asignacion_predio_table} ap
                  WHERE ap.asignacion_id = %s
                    AND ap.activo IS DISTINCT FROM FALSE
                    AND (
                        BTRIM(ap.numero_predial_nacional::text) = BTRIM(p.numero_predial::text)
                        {matriz_origen_sql}
                    )
              )
              {keep_new_filter}
            """,
            (work_datasetname, asignacion_id),
        )
        cur.execute("SELECT COUNT(*) FROM _arb_ws_unassigned_predio")
        removed_predios = int((cur.fetchone() or [0])[0] or 0)
        if removed_predios <= 0:
            return 0

        if has_table("arb_construccion"):
            cur.execute("DROP TABLE IF EXISTS _arb_ws_unassigned_construccion")
            cur.execute(
                f"""
                CREATE TEMP TABLE _arb_ws_unassigned_construccion AS
                SELECT c.t_id
                FROM {_qualify(schema_work, 'arb_construccion')} c
                JOIN _arb_ws_unassigned_predio p ON p.t_id = c.predio
                """
            )
        else:
            cur.execute("DROP TABLE IF EXISTS _arb_ws_unassigned_construccion")
            cur.execute("CREATE TEMP TABLE _arb_ws_unassigned_construccion (t_id bigint)")

        if has_table("arb_unidadconstruccion"):
            cur.execute("DROP TABLE IF EXISTS _arb_ws_unassigned_unidad")
            cur.execute(
                f"""
                CREATE TEMP TABLE _arb_ws_unassigned_unidad AS
                SELECT
                    u.t_id,
                    u.caracteristicasunidadconstruccion
                FROM {_qualify(schema_work, 'arb_unidadconstruccion')} u
                JOIN _arb_ws_unassigned_construccion c ON c.t_id = u.construccion
                """
            )
        else:
            cur.execute("DROP TABLE IF EXISTS _arb_ws_unassigned_unidad")
            cur.execute(
                "CREATE TEMP TABLE _arb_ws_unassigned_unidad (t_id bigint, caracteristicasunidadconstruccion bigint)"
            )

        for table_name, predio_fk in _ARB_DIRECT_PREDIO_TABLES:
            if not has_table(table_name):
                continue
            cur.execute(
                f"""
                DELETE FROM {_qualify(schema_work, table_name)} t
                USING _arb_ws_unassigned_predio p
                WHERE t.{predio_fk} = p.t_id
                """
            )

        if has_table("arb_tramite") and has_table("arb_predio_tramite"):
            cur.execute(
                f"""
                DELETE FROM {_qualify(schema_work, 'arb_tramite')} t
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM {_qualify(schema_work, 'arb_predio_tramite')} pt
                    WHERE pt.tramite = t.t_id
                )
                """
            )

        for attachment_table, parent_table, attachment_fk in _ARB_ATTACHMENT_SPECS:
            if not has_table(attachment_table) or not has_table(parent_table):
                continue
            parent_fk = "predio"
            if parent_table == "arb_derechointeresadofuente":
                parent_fk = "predio"
            elif parent_table == "arb_puntoreferencia":
                parent_fk = "predio"
            elif parent_table == "arb_terreno":
                parent_fk = "predio"
            cur.execute(
                f"""
                DELETE FROM {_qualify(schema_work, attachment_table)} a
                USING {_qualify(schema_work, parent_table)} p,
                      _arb_ws_unassigned_predio up
                WHERE a.{attachment_fk} = p.t_id
                  AND p.{parent_fk} = up.t_id
                """
            )

        if has_table("arb_adjuntounidadconstruccionvalor"):
            cur.execute(
                f"""
                DELETE FROM {_qualify(schema_work, 'arb_adjuntounidadconstruccionvalor')} a
                USING _arb_ws_unassigned_unidad u
                WHERE a.arb_unidadconstruccion_adjunto = u.t_id
                """
            )

        if has_table("arb_puntoreferencia"):
            cur.execute(
                f"""
                DELETE FROM {_qualify(schema_work, 'arb_puntoreferencia')} p
                USING _arb_ws_unassigned_predio up
                WHERE p.predio = up.t_id
                """
            )

        if has_table("arb_terreno"):
            cur.execute(
                f"""
                DELETE FROM {_qualify(schema_work, 'arb_terreno')} t
                USING _arb_ws_unassigned_predio up
                WHERE t.predio = up.t_id
                """
            )

        if has_table("arb_derechointeresadofuente"):
            cur.execute(
                f"""
                DELETE FROM {_qualify(schema_work, 'arb_derechointeresadofuente')} d
                USING _arb_ws_unassigned_predio up
                WHERE d.predio = up.t_id
                """
            )

        if has_table("arb_unidadconstruccion"):
            cur.execute(
                f"""
                DELETE FROM {_qualify(schema_work, 'arb_unidadconstruccion')} u
                USING _arb_ws_unassigned_unidad du
                WHERE u.t_id = du.t_id
                """
            )

        if has_table("arb_caracteristicasunidadconstruccion"):
            cur.execute(
                f"""
                DELETE FROM {_qualify(schema_work, 'arb_caracteristicasunidadconstruccion')} c
                WHERE c.t_id IN (
                    SELECT DISTINCT u.caracteristicasunidadconstruccion
                    FROM _arb_ws_unassigned_unidad u
                    WHERE u.caracteristicasunidadconstruccion IS NOT NULL
                )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM {_qualify(schema_work, 'arb_unidadconstruccion')} wu
                    WHERE wu.caracteristicasunidadconstruccion = c.t_id
                  )
                """
            )

        if has_table("arb_construccion"):
            cur.execute(
                f"""
                DELETE FROM {_qualify(schema_work, 'arb_construccion')} c
                USING _arb_ws_unassigned_construccion dc
                WHERE c.t_id = dc.t_id
                """
            )

        cur.execute(
            f"""
            DELETE FROM {predio_table} p
            USING _arb_ws_unassigned_predio up
            WHERE p.t_id = up.t_id
            """
        )

    return removed_predios


def _get_predio_updatable_columns(conn, schema_main: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = 'ilc_predio'
            ORDER BY ordinal_position
            """,
            (schema_main,),
        )
        cols = [row[0] for row in cur.fetchall()]
    excluded = {"t_id", "t_basket", "t_ili_tid", "numero_predial_nacional"}
    return [c for c in cols if c not in excluded]


def _get_table_columns(conn, schema_name: str, table_name: str) -> list[str]:
    with conn.cursor() as cur:
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
        return [str(row[0]).strip() for row in (cur.fetchall() or []) if row and row[0]]


def _get_common_table_columns(
    conn,
    schema_main: str,
    schema_work: str,
    table_name: str,
    *,
    exclude: Optional[set[str]] = None,
) -> list[str]:
    excluded = exclude or set()
    main_cols = set(_get_table_columns(conn, schema_main, table_name))
    work_cols = _get_table_columns(conn, schema_work, table_name)
    return [col for col in work_cols if col in main_cols and col not in excluded]


def _arb_create_sync_basket_map(conn, schema_main: str, schema_work: str, work_datasetname: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS _arb_sync_basket_map")
        cur.execute(
            f"""
            CREATE TEMP TABLE _arb_sync_basket_map AS
            SELECT
                wb.t_id AS work_basket,
                mb.t_id AS main_basket,
                wb.topic AS topicname,
                wb.t_ili_tid AS basket_tid
            FROM {_qualify(schema_work, 't_ili2db_basket')} wb
            JOIN {_qualify(schema_work, 't_ili2db_dataset')} wd
              ON wd.t_id = wb.dataset
            JOIN {_qualify(schema_main, 't_ili2db_basket')} mb
              ON mb.topic = wb.topic
            WHERE wd.datasetname = %s
            """,
            (work_datasetname,),
        )
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {_qualify(schema_work, 't_ili2db_basket')} wb
            JOIN {_qualify(schema_work, 't_ili2db_dataset')} wd
              ON wd.t_id = wb.dataset
            LEFT JOIN _arb_sync_basket_map bm
              ON bm.work_basket = wb.t_id
            WHERE wd.datasetname = %s
              AND bm.main_basket IS NULL
            """,
            (work_datasetname,),
        )
        missing = int((cur.fetchone() or [0])[0] or 0)
    if missing > 0:
        raise export_service.ExportServiceError(
            status_code=409,
            detail=(
                f"No se pudieron mapear {missing} basket(s) del workspace {schema_work}:{work_datasetname} "
                f"hacia {schema_main}. Verifica t_ili_tid de baskets en ambos schemas."
            ),
        )


def _arb_prepare_diagnostic_predio_map(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    work_datasetname: str,
    schema_main: str,
    schema_work: str,
) -> dict:
    selected_count = _arb_create_sync_selected_predio_scope(
        conn,
        tenant,
        asignacion_id,
        work_datasetname,
        schema_work,
        include_new_informal_predios=True,
    )

    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS _arb_sync_predio_map")
        cur.execute(
            f"""
            CREATE TEMP TABLE _arb_sync_predio_map AS
            SELECT
                sp.work_predio_t_id,
                mp.t_id AS main_predio_t_id,
                sp.numero_predial_nacional
            FROM _arb_sync_selected_predio sp
            JOIN {_qualify(schema_main, 'arb_predio')} mp
              ON BTRIM(mp.numero_predial::text) = BTRIM(sp.numero_predial_nacional::text)
            """
        )
        cur.execute("SELECT COUNT(*) FROM _arb_sync_predio_map")
        mapped_count = int((cur.fetchone() or [0])[0] or 0)

    return {
        "selected_predios": selected_count,
        "mapped_predios": mapped_count,
    }


def _arb_create_sync_selected_predio_scope(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    work_datasetname: str,
    schema_work: str,
    *,
    include_new_informal_predios: bool = False,
) -> int:
    asignacion_predio_table = app_table(tenant, "asignacion_predio")
    scope_condition = f"""
    EXISTS (
        SELECT 1
        FROM {asignacion_predio_table} ap
        WHERE ap.asignacion_id = %s
          AND ap.activo IS DISTINCT FROM FALSE
          AND BTRIM(ap.numero_predial_nacional::text) = BTRIM(wp.numero_predial::text)
    )
    """
    if include_new_informal_predios:
        new_informal_sql = _arb_new_informal_predio_condition_sql(conn, schema_work, alias="wp")
        scope_condition = f"({scope_condition} OR {new_informal_sql})"
    else:
        scope_condition = f"({scope_condition})"

    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS _arb_sync_selected_predio")
        cur.execute(
            f"""
            CREATE TEMP TABLE _arb_sync_selected_predio AS
            SELECT
                wp.t_id AS work_predio_t_id,
                BTRIM(wp.numero_predial::text) AS numero_predial_nacional,
                wp.t_basket AS work_basket
            FROM {_qualify(schema_work, 'arb_predio')} wp
            JOIN {_qualify(schema_work, 't_ili2db_basket')} wb
              ON wb.t_id = wp.t_basket
            JOIN {_qualify(schema_work, 't_ili2db_dataset')} wd
              ON wd.t_id = wb.dataset
            WHERE wd.datasetname = %s
              AND {scope_condition}
            """,
            (work_datasetname, asignacion_id),
        )
        cur.execute("SELECT COUNT(*) FROM _arb_sync_selected_predio")
        return int((cur.fetchone() or [0])[0] or 0)


def _arb_assert_sync_selected_predio_unique(conn, schema_work: str, work_datasetname: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT numero_predial_nacional, COUNT(*)::int AS total
            FROM _arb_sync_selected_predio
            GROUP BY numero_predial_nacional
            HAVING COUNT(*) > 1
            ORDER BY COUNT(*) DESC, numero_predial_nacional
            LIMIT 5
            """
        )
        duplicate_rows = cur.fetchall() or []

    if duplicate_rows:
        preview = ", ".join(f"{row[0]} ({row[1]})" for row in duplicate_rows if row and row[0])
        raise export_service.ExportServiceError(
            status_code=409,
            detail=(
                f"El retorno XTF contiene predios duplicados dentro del scope a sincronizar en "
                f"{schema_work}:{work_datasetname}. Ejemplos: {preview}."
            ),
        )


def _arb_validate_workspace_assignment_coverage(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    work_datasetname: str,
    schema_work: str,
    *,
    allow_missing_predios: bool = False,
) -> dict:
    with conn.cursor() as cur:
        asignacion_predio_table = app_table(tenant, "asignacion_predio")
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT BTRIM(ap.numero_predial_nacional::text))
            FROM {asignacion_predio_table} ap
            WHERE ap.asignacion_id = %s
              AND ap.activo IS DISTINCT FROM FALSE
            """,
            (asignacion_id,),
        )
        expected_predios = int((cur.fetchone() or [0])[0] or 0)

        cur.execute(
            f"""
            SELECT COUNT(DISTINCT BTRIM(p.numero_predial::text))
            FROM {_qualify(schema_work, 'arb_predio')} p
            JOIN {_qualify(schema_work, 't_ili2db_basket')} b
              ON b.t_id = p.t_basket
            JOIN {_qualify(schema_work, 't_ili2db_dataset')} d
              ON d.t_id = b.dataset
            JOIN (
                SELECT DISTINCT BTRIM(ap.numero_predial_nacional::text) AS numero_predial_nacional
                FROM {asignacion_predio_table} ap
                WHERE ap.asignacion_id = %s
                  AND ap.activo IS DISTINCT FROM FALSE
            ) ap
              ON ap.numero_predial_nacional = BTRIM(p.numero_predial::text)
            WHERE d.datasetname = %s
            """,
            (asignacion_id, work_datasetname),
        )
        covered_predios = int((cur.fetchone() or [0])[0] or 0)

        cur.execute(
            f"""
            SELECT
                BTRIM(p.numero_predial::text) AS numero_predial_nacional,
                COUNT(*) AS total
            FROM {_qualify(schema_work, 'arb_predio')} p
            JOIN {_qualify(schema_work, 't_ili2db_basket')} b
              ON b.t_id = p.t_basket
            JOIN {_qualify(schema_work, 't_ili2db_dataset')} d
              ON d.t_id = b.dataset
            JOIN (
                SELECT DISTINCT BTRIM(ap.numero_predial_nacional::text) AS numero_predial_nacional
                FROM {asignacion_predio_table} ap
                WHERE ap.asignacion_id = %s
                  AND ap.activo IS DISTINCT FROM FALSE
            ) ap
              ON ap.numero_predial_nacional = BTRIM(p.numero_predial::text)
            WHERE d.datasetname = %s
            GROUP BY BTRIM(p.numero_predial::text)
            HAVING COUNT(*) > 1
            ORDER BY total DESC, numero_predial_nacional
            LIMIT 5
            """,
            (asignacion_id, work_datasetname),
        )
        duplicate_rows = cur.fetchall() or []

        cur.execute(
            f"""
            SELECT ap.numero_predial_nacional
            FROM (
                SELECT DISTINCT BTRIM(ap.numero_predial_nacional::text) AS numero_predial_nacional
                FROM {asignacion_predio_table} ap
                WHERE ap.asignacion_id = %s
                  AND ap.activo IS DISTINCT FROM FALSE
            ) ap
            LEFT JOIN (
                SELECT DISTINCT BTRIM(p.numero_predial::text) AS numero_predial_nacional
                FROM {_qualify(schema_work, 'arb_predio')} p
                JOIN {_qualify(schema_work, 't_ili2db_basket')} b
                  ON b.t_id = p.t_basket
                JOIN {_qualify(schema_work, 't_ili2db_dataset')} d
                  ON d.t_id = b.dataset
                JOIN {asignacion_predio_table} ap2
                  ON BTRIM(ap2.numero_predial_nacional::text) = BTRIM(p.numero_predial::text)
                 AND ap2.asignacion_id = %s
                 AND ap2.activo IS DISTINCT FROM FALSE
                WHERE d.datasetname = %s
            ) cov
              ON cov.numero_predial_nacional = ap.numero_predial_nacional
            WHERE cov.numero_predial_nacional IS NULL
            ORDER BY ap.numero_predial_nacional
            LIMIT 5
            """,
            (asignacion_id, asignacion_id, work_datasetname),
        )
        missing_rows = [str(row[0]).strip() for row in (cur.fetchall() or []) if row and row[0]]

    if duplicate_rows:
        dup_preview = ", ".join(f"{row[0]} ({row[1]})" for row in duplicate_rows if row and row[0])
        raise export_service.ExportServiceError(
            status_code=409,
            detail=(
                f"El retorno XTF contiene predios duplicados dentro de {schema_work}:{work_datasetname}. "
                f"Debe existir un solo registro por numero predial. Ejemplos: {dup_preview}."
            ),
        )

    missing_predios = max(expected_predios - covered_predios, 0)

    if missing_predios > 0 and not allow_missing_predios:
        missing_preview = ", ".join(missing_rows)
        suffix = f" Ejemplos faltantes: {missing_preview}." if missing_preview else ""
        raise export_service.ExportServiceError(
            status_code=409,
            detail=(
                f"El retorno XTF esta incompleto para sincronizar: contiene {covered_predios} "
                f"predio(s) validos de los {expected_predios} predios activos requeridos por la asignacion "
                f"(faltan {missing_predios}).{suffix}"
            ),
        )

    return {
        "expected_predios": expected_predios,
        "covered_predios": covered_predios,
        "missing_predios": missing_predios,
        "missing_predios_preview": missing_rows,
    }


def _arb_sync_predios_to_main(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    work_datasetname: str,
    schema_main: str,
    schema_work: str,
) -> int:
    coverage = _arb_validate_workspace_assignment_coverage(
        conn,
        tenant,
        asignacion_id,
        work_datasetname,
        schema_work,
    )
    expected_predios = int(coverage.get("expected_predios") or 0)

    work_predio = "arb_predio"
    numero_field = "numero_predial"
    update_cols = _get_common_table_columns(
        conn,
        schema_main,
        schema_work,
        work_predio,
        exclude={"t_id", "t_basket", "t_ili_tid", numero_field},
    )

    selected_count = _arb_create_sync_selected_predio_scope(
        conn,
        tenant,
        asignacion_id,
        work_datasetname,
        schema_work,
        include_new_informal_predios=True,
    )

    if selected_count <= 0:
        return 0

    _arb_assert_sync_selected_predio_unique(conn, schema_work, work_datasetname)

    if expected_predios > 0 and selected_count < expected_predios:
        raise export_service.ExportServiceError(
            status_code=409,
            detail=(
                f"El retorno XTF no materializo todo el scope esperado: {selected_count}/{expected_predios} "
                "predio(s) despues del recorte del dataset temporal."
            ),
        )

    set_parts = [f"{col} = src.{col}" for col in update_cols]
    set_parts.append("t_basket = src.main_basket")
    tid_match = (
        "COALESCE(NULLIF(BTRIM(mp.t_ili_tid::text), ''), '') <> '' "
        "AND BTRIM(mp.t_ili_tid::text) = BTRIM(src.t_ili_tid::text)"
    )
    npn_match = f"BTRIM(mp.{numero_field}::text) = BTRIM(src.{numero_field}::text)"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {_qualify(schema_main, work_predio)} AS mp
            SET {', '.join(set_parts)}
            FROM (
                SELECT wp.*, bm.main_basket
                FROM {_qualify(schema_work, work_predio)} wp
                JOIN _arb_sync_selected_predio sp
                  ON sp.work_predio_t_id = wp.t_id
                JOIN _arb_sync_basket_map bm
                  ON bm.work_basket = wp.t_basket
            ) AS src
            WHERE ({tid_match}) OR ({npn_match})
            """
        )

    insert_copy_cols = _get_common_table_columns(
        conn,
        schema_main,
        schema_work,
        work_predio,
        exclude={"t_id", "t_basket"},
    )
    insert_cols = insert_copy_cols + ["t_basket"]
    select_exprs = [f"wp.{col}" for col in insert_copy_cols] + ["bm.main_basket"]
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {_qualify(schema_main, work_predio)} ({', '.join(insert_cols)})
            SELECT {', '.join(select_exprs)}
            FROM {_qualify(schema_work, work_predio)} wp
            JOIN _arb_sync_selected_predio sp
              ON sp.work_predio_t_id = wp.t_id
            JOIN _arb_sync_basket_map bm
              ON bm.work_basket = wp.t_basket
            WHERE NOT EXISTS (
                SELECT 1
                FROM {_qualify(schema_main, work_predio)} mp
                WHERE (
                    COALESCE(NULLIF(BTRIM(wp.t_ili_tid::text), ''), '') <> ''
                    AND COALESCE(NULLIF(BTRIM(mp.t_ili_tid::text), ''), '') <> ''
                    AND BTRIM(mp.t_ili_tid::text) = BTRIM(wp.t_ili_tid::text)
                )
                OR BTRIM(mp.{numero_field}::text) = BTRIM(wp.{numero_field}::text)
            )
            """
        )

        cur.execute("DROP TABLE IF EXISTS _arb_sync_predio_map")
        cur.execute(
            f"""
            CREATE TEMP TABLE _arb_sync_predio_map AS
            SELECT
                sp.work_predio_t_id,
                mp.t_id AS main_predio_t_id,
                sp.numero_predial_nacional
            FROM _arb_sync_selected_predio sp
            JOIN {_qualify(schema_main, work_predio)} mp
              ON BTRIM(mp.{numero_field}::text) = BTRIM(sp.numero_predial_nacional::text)
            """
        )
        cur.execute("SELECT COUNT(*) FROM _arb_sync_predio_map")
        mapped_count = int((cur.fetchone() or [0])[0] or 0)
        if mapped_count != selected_count:
            raise export_service.ExportServiceError(
                status_code=409,
                detail=(
                    f"No se pudieron resolver todos los predios del retorno arb en {schema_main}: "
                    f"{mapped_count}/{selected_count}."
                ),
            )

    _arb_validate_sync_identity_fields(conn, schema_main, schema_work, work_datasetname)

    with conn.cursor() as cur:
        asignacion_predio_table = app_table(tenant, "asignacion_predio")
        cur.execute(
            f"""
            UPDATE {asignacion_predio_table} ap
            SET predio_t_id = pm.main_predio_t_id
            FROM _arb_sync_predio_map pm
            WHERE ap.asignacion_id = %s
              AND BTRIM(ap.numero_predial_nacional::text) = BTRIM(pm.numero_predial_nacional::text)
            """,
            (asignacion_id,),
        )

    return mapped_count


def _arb_assert_schema_parity(conn, schema_main: str, schema_work: str) -> None:
    existing_main = _schema_table_names(conn, schema_main)
    existing_work = _schema_table_names(conn, schema_work)
    missing = sorted(table for table in _ARB_SCHEMA_PARITY_TABLES if table in existing_work and table not in existing_main)
    if missing:
        raise export_service.ExportServiceError(
            status_code=500,
            detail=(
                f"El schema principal '{schema_main}' no tiene todas las tablas Arbimaps presentes en "
                f"'{schema_work}'. Faltan: {', '.join(missing)}."
            ),
        )


def _arb_validate_sync_identity_fields(conn, schema_main: str, schema_work: str, work_datasetname: str) -> None:
    existing_main = _schema_table_names(conn, schema_main)
    existing_work = _schema_table_names(conn, schema_work)
    issues: list[str] = []

    def _append_issue(table_name: str, count: int, reason: str) -> None:
        if count > 0:
            issues.append(f"{table_name}: {count} fila(s) {reason}")

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {_qualify(schema_work, 't_ili2db_basket')} b
            JOIN {_qualify(schema_work, 't_ili2db_dataset')} d
              ON d.t_id = b.dataset
            WHERE d.datasetname = %s
              AND COALESCE(NULLIF(BTRIM(b.t_ili_tid::text), ''), '') = ''
            """,
            (work_datasetname,),
        )
        _append_issue("t_ili2db_basket", int((cur.fetchone() or [0])[0] or 0), "sin t_ili_tid en workspace")

    for table_name in _ARB_TILI_TID_REQUIRED_TABLES:
        if table_name not in existing_work:
            continue
        work_cols = set(_get_table_columns(conn, schema_work, table_name))
        main_cols = set(_get_table_columns(conn, schema_main, table_name)) if table_name in existing_main else set()
        if "t_ili_tid" not in work_cols:
            issues.append(f"{table_name}: tabla workspace sin columna t_ili_tid")
            continue
        if table_name in existing_main and "t_ili_tid" not in main_cols:
            issues.append(f"{table_name}: tabla principal sin columna t_ili_tid")
            continue

        count_query = None
        if table_name in {"arb_puntoreferencia", "arb_terreno", "arb_derechointeresadofuente"}:
            count_query = f"""
                SELECT COUNT(*)
                FROM {_qualify(schema_work, table_name)} t
                JOIN _arb_sync_predio_map pm ON pm.work_predio_t_id = t.predio
                WHERE COALESCE(NULLIF(BTRIM(t.t_ili_tid::text), ''), '') = ''
            """
        elif table_name == "arb_construccion":
            count_query = f"""
                SELECT COUNT(*)
                FROM {_qualify(schema_work, table_name)} t
                JOIN _arb_sync_predio_map pm ON pm.work_predio_t_id = t.predio
                WHERE COALESCE(NULLIF(BTRIM(t.t_ili_tid::text), ''), '') = ''
            """
        elif table_name == "arb_tramite":
            count_query = f"""
                SELECT COUNT(*)
                FROM {_qualify(schema_work, 'arb_tramite')} t
                JOIN {_qualify(schema_work, 'arb_predio_tramite')} pt ON pt.tramite = t.t_id
                JOIN _arb_sync_predio_map pm ON pm.work_predio_t_id = pt.predio
                WHERE COALESCE(NULLIF(BTRIM(t.t_ili_tid::text), ''), '') = ''
            """
        elif table_name == "arb_unidadconstruccion":
            count_query = f"""
                SELECT COUNT(*)
                FROM {_qualify(schema_work, table_name)} u
                JOIN {_qualify(schema_work, 'arb_construccion')} c ON c.t_id = u.construccion
                JOIN _arb_sync_predio_map pm ON pm.work_predio_t_id = c.predio
                WHERE COALESCE(NULLIF(BTRIM(u.t_ili_tid::text), ''), '') = ''
            """
        elif table_name == "arb_caracteristicasunidadconstruccion":
            count_query = f"""
                SELECT COUNT(DISTINCT cc.t_id)
                FROM {_qualify(schema_work, table_name)} cc
                JOIN {_qualify(schema_work, 'arb_unidadconstruccion')} u
                  ON u.caracteristicasunidadconstruccion = cc.t_id
                JOIN {_qualify(schema_work, 'arb_construccion')} c
                  ON c.t_id = u.construccion
                JOIN _arb_sync_predio_map pm
                  ON pm.work_predio_t_id = c.predio
                WHERE COALESCE(NULLIF(BTRIM(cc.t_ili_tid::text), ''), '') = ''
            """
        if not count_query:
            continue
        with conn.cursor() as cur:
            cur.execute(count_query)
            _append_issue(table_name, int((cur.fetchone() or [0])[0] or 0), "sin t_ili_tid util para sincronización")

    if issues:
        raise export_service.ExportServiceError(
            status_code=409,
            detail="Workspace Arbimaps inválido para sincronizar: " + "; ".join(issues),
        )


def _arb_count_direct_child_rows(conn, schema_name: str, table_name: str, predio_fk: str, *, use_main_ids: bool) -> int:
    predio_ref = "main_predio_t_id" if use_main_ids else "work_predio_t_id"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {_qualify(schema_name, table_name)} t
            JOIN _arb_sync_predio_map pm
              ON t.{predio_fk} = pm.{predio_ref}
            """
        )
        return int((cur.fetchone() or [0])[0] or 0)


def _arb_count_attachment_rows(
    conn,
    schema_name: str,
    table_name: str,
    parent_table: str,
    attachment_fk: str,
    *,
    use_main_ids: bool,
    parent_predio_fk: str = "predio",
) -> int:
    predio_ref = "main_predio_t_id" if use_main_ids else "work_predio_t_id"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {_qualify(schema_name, table_name)} a
            JOIN {_qualify(schema_name, parent_table)} p
              ON p.t_id = a.{attachment_fk}
            JOIN _arb_sync_predio_map pm
              ON p.{parent_predio_fk} = pm.{predio_ref}
            """
        )
        return int((cur.fetchone() or [0])[0] or 0)


def _arb_validate_post_sync_counts(conn, schema_main: str, schema_work: str) -> None:
    existing_main = _schema_table_names(conn, schema_main)
    existing_work = _schema_table_names(conn, schema_work)
    mismatches: list[str] = []

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM _arb_sync_predio_map")
        expected_predios = int((cur.fetchone() or [0])[0] or 0)
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {_qualify(schema_main, 'arb_predio')} p
            JOIN _arb_sync_predio_map pm
              ON p.t_id = pm.main_predio_t_id
            """
        )
        main_predios = int((cur.fetchone() or [0])[0] or 0)
    if main_predios != expected_predios:
        mismatches.append(f"arb_predio={main_predios}/{expected_predios}")

    for table_name, predio_fk in _ARB_DIRECT_PREDIO_TABLES:
        if table_name not in existing_main or table_name not in existing_work:
            continue
        work_count = _arb_count_direct_child_rows(conn, schema_work, table_name, predio_fk, use_main_ids=False)
        main_count = _arb_count_direct_child_rows(conn, schema_main, table_name, predio_fk, use_main_ids=True)
        if work_count != main_count:
            mismatches.append(f"{table_name}={main_count}/{work_count}")

    if {"arb_construccion", "arb_unidadconstruccion"}.issubset(existing_main) and {
        "arb_construccion",
        "arb_unidadconstruccion",
    }.issubset(existing_work):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM {_qualify(schema_work, 'arb_unidadconstruccion')} u
                JOIN {_qualify(schema_work, 'arb_construccion')} c ON c.t_id = u.construccion
                JOIN _arb_sync_predio_map pm ON pm.work_predio_t_id = c.predio
                """
            )
            work_uc = int((cur.fetchone() or [0])[0] or 0)
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM {_qualify(schema_main, 'arb_unidadconstruccion')} u
                JOIN {_qualify(schema_main, 'arb_construccion')} c ON c.t_id = u.construccion
                JOIN _arb_sync_predio_map pm ON pm.main_predio_t_id = c.predio
                """
            )
            main_uc = int((cur.fetchone() or [0])[0] or 0)
        if work_uc != main_uc:
            mismatches.append(f"arb_unidadconstruccion={main_uc}/{work_uc}")

    if {"arb_caracteristicasunidadconstruccion", "arb_unidadconstruccion", "arb_construccion"}.issubset(existing_main) and {
        "arb_caracteristicasunidadconstruccion",
        "arb_unidadconstruccion",
        "arb_construccion",
    }.issubset(existing_work):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(DISTINCT cc.t_id)
                FROM {_qualify(schema_work, 'arb_caracteristicasunidadconstruccion')} cc
                JOIN {_qualify(schema_work, 'arb_unidadconstruccion')} u
                  ON u.caracteristicasunidadconstruccion = cc.t_id
                JOIN {_qualify(schema_work, 'arb_construccion')} c
                  ON c.t_id = u.construccion
                JOIN _arb_sync_predio_map pm
                  ON pm.work_predio_t_id = c.predio
                """
            )
            work_cuc = int((cur.fetchone() or [0])[0] or 0)
            cur.execute(
                f"""
                SELECT COUNT(DISTINCT cc.t_id)
                FROM {_qualify(schema_main, 'arb_caracteristicasunidadconstruccion')} cc
                JOIN {_qualify(schema_main, 'arb_unidadconstruccion')} u
                  ON u.caracteristicasunidadconstruccion = cc.t_id
                JOIN {_qualify(schema_main, 'arb_construccion')} c
                  ON c.t_id = u.construccion
                JOIN _arb_sync_predio_map pm
                  ON pm.main_predio_t_id = c.predio
                """
            )
            main_cuc = int((cur.fetchone() or [0])[0] or 0)
        if work_cuc != main_cuc:
            mismatches.append(f"arb_caracteristicasunidadconstruccion={main_cuc}/{work_cuc}")

    if "arb_adjuntounidadconstruccionvalor" in existing_main and "arb_adjuntounidadconstruccionvalor" in existing_work:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM {_qualify(schema_work, 'arb_adjuntounidadconstruccionvalor')} a
                JOIN {_qualify(schema_work, 'arb_unidadconstruccion')} u
                  ON u.t_id = a.arb_unidadconstruccion_adjunto
                JOIN {_qualify(schema_work, 'arb_construccion')} c
                  ON c.t_id = u.construccion
                JOIN _arb_sync_predio_map pm
                  ON pm.work_predio_t_id = c.predio
                """
            )
            work_adj_uc = int((cur.fetchone() or [0])[0] or 0)
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM {_qualify(schema_main, 'arb_adjuntounidadconstruccionvalor')} a
                JOIN {_qualify(schema_main, 'arb_unidadconstruccion')} u
                  ON u.t_id = a.arb_unidadconstruccion_adjunto
                JOIN {_qualify(schema_main, 'arb_construccion')} c
                  ON c.t_id = u.construccion
                JOIN _arb_sync_predio_map pm
                  ON pm.main_predio_t_id = c.predio
                """
            )
            main_adj_uc = int((cur.fetchone() or [0])[0] or 0)
        if work_adj_uc != main_adj_uc:
            mismatches.append(f"arb_adjuntounidadconstruccionvalor={main_adj_uc}/{work_adj_uc}")

    for table_name, parent_table, parent_fk in _ARB_ATTACHMENT_SPECS:
        if table_name not in existing_main or table_name not in existing_work or parent_table not in existing_main or parent_table not in existing_work:
            continue
        work_count = _arb_count_attachment_rows(
            conn,
            schema_work,
            table_name,
            parent_table,
            parent_fk,
            use_main_ids=False,
        )
        main_count = _arb_count_attachment_rows(
            conn,
            schema_main,
            table_name,
            parent_table,
            parent_fk,
            use_main_ids=True,
        )
        if work_count != main_count:
            mismatches.append(f"{table_name}={main_count}/{work_count}")

    if mismatches:
        raise export_service.ExportServiceError(
            status_code=409,
            detail=(
                "La sincronización Arbimaps terminó con conteos inconsistentes frente al workspace: "
                + ", ".join(mismatches)
            ),
        )


def _arb_collect_post_sync_count_pairs(conn, schema_main: str, schema_work: str) -> tuple[list[dict], list[str]]:
    existing_main = _schema_table_names(conn, schema_main)
    existing_work = _schema_table_names(conn, schema_work)
    comparisons: list[dict] = []
    mismatches: list[str] = []

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM _arb_sync_predio_map")
        expected_predios = int((cur.fetchone() or [0])[0] or 0)
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {_qualify(schema_main, 'arb_predio')} p
            JOIN _arb_sync_predio_map pm
              ON p.t_id = pm.main_predio_t_id
            """
        )
        main_predios = int((cur.fetchone() or [0])[0] or 0)

    comparisons.append(
        {
            "table": "arb_predio",
            "workspace": expected_predios,
            "main": main_predios,
            "status": "ok" if main_predios == expected_predios else "mismatch",
        }
    )
    if main_predios != expected_predios:
        mismatches.append(f"arb_predio={main_predios}/{expected_predios}")

    for table_name, predio_fk in _ARB_DIRECT_PREDIO_TABLES:
        if table_name not in existing_main or table_name not in existing_work:
            comparisons.append(
                {
                    "table": table_name,
                    "workspace": None,
                    "main": None,
                    "status": "missing_schema",
                }
            )
            continue
        work_count = _arb_count_direct_child_rows(conn, schema_work, table_name, predio_fk, use_main_ids=False)
        main_count = _arb_count_direct_child_rows(conn, schema_main, table_name, predio_fk, use_main_ids=True)
        comparisons.append(
            {
                "table": table_name,
                "workspace": work_count,
                "main": main_count,
                "status": "ok" if work_count == main_count else "mismatch",
            }
        )
        if work_count != main_count:
            mismatches.append(f"{table_name}={main_count}/{work_count}")

    if {"arb_construccion", "arb_unidadconstruccion"}.issubset(existing_main) and {
        "arb_construccion",
        "arb_unidadconstruccion",
    }.issubset(existing_work):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM {_qualify(schema_work, 'arb_unidadconstruccion')} u
                JOIN {_qualify(schema_work, 'arb_construccion')} c ON c.t_id = u.construccion
                JOIN _arb_sync_predio_map pm ON pm.work_predio_t_id = c.predio
                """
            )
            work_uc = int((cur.fetchone() or [0])[0] or 0)
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM {_qualify(schema_main, 'arb_unidadconstruccion')} u
                JOIN {_qualify(schema_main, 'arb_construccion')} c ON c.t_id = u.construccion
                JOIN _arb_sync_predio_map pm ON pm.main_predio_t_id = c.predio
                """
            )
            main_uc = int((cur.fetchone() or [0])[0] or 0)
        comparisons.append(
            {
                "table": "arb_unidadconstruccion",
                "workspace": work_uc,
                "main": main_uc,
                "status": "ok" if work_uc == main_uc else "mismatch",
            }
        )
        if work_uc != main_uc:
            mismatches.append(f"arb_unidadconstruccion={main_uc}/{work_uc}")
    else:
        comparisons.append(
            {
                "table": "arb_unidadconstruccion",
                "workspace": None,
                "main": None,
                "status": "missing_schema",
            }
        )

    if {"arb_caracteristicasunidadconstruccion", "arb_unidadconstruccion", "arb_construccion"}.issubset(existing_main) and {
        "arb_caracteristicasunidadconstruccion",
        "arb_unidadconstruccion",
        "arb_construccion",
    }.issubset(existing_work):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(DISTINCT cc.t_id)
                FROM {_qualify(schema_work, 'arb_caracteristicasunidadconstruccion')} cc
                JOIN {_qualify(schema_work, 'arb_unidadconstruccion')} u
                  ON u.caracteristicasunidadconstruccion = cc.t_id
                JOIN {_qualify(schema_work, 'arb_construccion')} c
                  ON c.t_id = u.construccion
                JOIN _arb_sync_predio_map pm
                  ON pm.work_predio_t_id = c.predio
                """
            )
            work_cuc = int((cur.fetchone() or [0])[0] or 0)
            cur.execute(
                f"""
                SELECT COUNT(DISTINCT cc.t_id)
                FROM {_qualify(schema_main, 'arb_caracteristicasunidadconstruccion')} cc
                JOIN {_qualify(schema_main, 'arb_unidadconstruccion')} u
                  ON u.caracteristicasunidadconstruccion = cc.t_id
                JOIN {_qualify(schema_main, 'arb_construccion')} c
                  ON c.t_id = u.construccion
                JOIN _arb_sync_predio_map pm
                  ON pm.main_predio_t_id = c.predio
                """
            )
            main_cuc = int((cur.fetchone() or [0])[0] or 0)
        comparisons.append(
            {
                "table": "arb_caracteristicasunidadconstruccion",
                "workspace": work_cuc,
                "main": main_cuc,
                "status": "ok" if work_cuc == main_cuc else "mismatch",
            }
        )
        if work_cuc != main_cuc:
            mismatches.append(f"arb_caracteristicasunidadconstruccion={main_cuc}/{work_cuc}")
    else:
        comparisons.append(
            {
                "table": "arb_caracteristicasunidadconstruccion",
                "workspace": None,
                "main": None,
                "status": "missing_schema",
            }
        )

    if "arb_adjuntounidadconstruccionvalor" in existing_main and "arb_adjuntounidadconstruccionvalor" in existing_work:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM {_qualify(schema_work, 'arb_adjuntounidadconstruccionvalor')} a
                JOIN {_qualify(schema_work, 'arb_unidadconstruccion')} u
                  ON u.t_id = a.arb_unidadconstruccion_adjunto
                JOIN {_qualify(schema_work, 'arb_construccion')} c
                  ON c.t_id = u.construccion
                JOIN _arb_sync_predio_map pm
                  ON pm.work_predio_t_id = c.predio
                """
            )
            work_adj_uc = int((cur.fetchone() or [0])[0] or 0)
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM {_qualify(schema_main, 'arb_adjuntounidadconstruccionvalor')} a
                JOIN {_qualify(schema_main, 'arb_unidadconstruccion')} u
                  ON u.t_id = a.arb_unidadconstruccion_adjunto
                JOIN {_qualify(schema_main, 'arb_construccion')} c
                  ON c.t_id = u.construccion
                JOIN _arb_sync_predio_map pm
                  ON pm.main_predio_t_id = c.predio
                """
            )
            main_adj_uc = int((cur.fetchone() or [0])[0] or 0)
        comparisons.append(
            {
                "table": "arb_adjuntounidadconstruccionvalor",
                "workspace": work_adj_uc,
                "main": main_adj_uc,
                "status": "ok" if work_adj_uc == main_adj_uc else "mismatch",
            }
        )
        if work_adj_uc != main_adj_uc:
            mismatches.append(f"arb_adjuntounidadconstruccionvalor={main_adj_uc}/{work_adj_uc}")
    else:
        comparisons.append(
            {
                "table": "arb_adjuntounidadconstruccionvalor",
                "workspace": None,
                "main": None,
                "status": "missing_schema",
            }
        )

    for table_name, parent_table, parent_fk in _ARB_ATTACHMENT_SPECS:
        if table_name not in existing_main or table_name not in existing_work or parent_table not in existing_main or parent_table not in existing_work:
            comparisons.append(
                {
                    "table": table_name,
                    "workspace": None,
                    "main": None,
                    "status": "missing_schema",
                }
            )
            continue
        work_count = _arb_count_attachment_rows(
            conn,
            schema_work,
            table_name,
            parent_table,
            parent_fk,
            use_main_ids=False,
        )
        main_count = _arb_count_attachment_rows(
            conn,
            schema_main,
            table_name,
            parent_table,
            parent_fk,
            use_main_ids=True,
        )
        comparisons.append(
            {
                "table": table_name,
                "workspace": work_count,
                "main": main_count,
                "status": "ok" if work_count == main_count else "mismatch",
            }
        )
        if work_count != main_count:
            mismatches.append(f"{table_name}={main_count}/{work_count}")

    return comparisons, mismatches


def _arb_validate_workspace_dataset_health(conn, schema_work: str, work_datasetname: str) -> None:
    existing_work = _schema_table_names(conn, schema_work)
    issues: list[str] = []

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {_qualify(schema_work, 't_ili2db_basket')} b
            JOIN {_qualify(schema_work, 't_ili2db_dataset')} d
              ON d.t_id = b.dataset
            WHERE d.datasetname = %s
              AND COALESCE(NULLIF(BTRIM(b.t_ili_tid::text), ''), '') = ''
            """,
            (work_datasetname,),
        )
        missing_basket_tid = int((cur.fetchone() or [0])[0] or 0)
        if missing_basket_tid > 0:
            issues.append(f"baskets_sin_tili_tid={missing_basket_tid}")

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {_qualify(schema_work, 'arb_predio')} p
            JOIN {_qualify(schema_work, 't_ili2db_basket')} b
              ON b.t_id = p.t_basket
            JOIN {_qualify(schema_work, 't_ili2db_dataset')} d
              ON d.t_id = b.dataset
            WHERE d.datasetname = %s
              AND COALESCE(NULLIF(BTRIM(p.numero_predial), ''), '') = ''
            """,
            (work_datasetname,),
        )
        invalid_predio_num = int((cur.fetchone() or [0])[0] or 0)
        if invalid_predio_num > 0:
            issues.append(f"predios_sin_numero_predial={invalid_predio_num}")

    for table_name in existing_work:
        cols = set(_get_table_columns(conn, schema_work, table_name))
        if "t_basket" not in cols or table_name == "t_ili2db_basket":
            continue
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM {_qualify(schema_work, table_name)} t
                LEFT JOIN {_qualify(schema_work, 't_ili2db_basket')} b
                  ON b.t_id = t.t_basket
                WHERE t.t_basket IS NOT NULL
                  AND b.t_id IS NULL
                """,
            )
            invalid_tbasket = int((cur.fetchone() or [0])[0] or 0)
            if invalid_tbasket > 0:
                issues.append(f"{table_name}_sin_t_basket={invalid_tbasket}")

    if issues:
        raise export_service.ExportServiceError(
            status_code=409,
            detail=(
                f"Workspace Arbimaps inválido en {schema_work}:{work_datasetname}. "
                + ", ".join(issues)
            ),
        )


def validate_workspace_dataset_health(
    schema_work: str,
    work_datasetname: str,
    *,
    conn,
    tenant: TenantContext,
) -> None:
    if not work_datasetname:
        raise export_service.ExportServiceError(
            status_code=400,
            detail="Dataset de workspace no definido para validar.",
        )

    workspace_ctx = workspace_schema_service.get_workspace_context(schema_work)
    if workspace_ctx.model_name != "arb":
        return

    _arb_validate_workspace_dataset_health(conn, schema_work, work_datasetname)


def validate_workspace_assignment_coverage(
    asignacion_id: int,
    schema_work: str,
    work_datasetname: str,
    *,
    conn,
    tenant: TenantContext,
    allow_missing_predios: bool = False,
) -> dict:
    if not work_datasetname:
        raise export_service.ExportServiceError(
            status_code=400,
            detail="Dataset de workspace no definido para validar cobertura de asignacion.",
        )

    workspace_ctx = workspace_schema_service.get_workspace_context(schema_work)
    if workspace_ctx.model_name != "arb":
        expected_predios = assignment_active_predio_count(conn, tenant, asignacion_id)
        return {
            "expected_predios": expected_predios,
            "covered_predios": 0,
            "missing_predios": expected_predios,
            "missing_predios_preview": [],
        }

    return _arb_validate_workspace_assignment_coverage(
        conn,
        tenant,
        asignacion_id,
        work_datasetname,
        schema_work,
        allow_missing_predios=allow_missing_predios,
    )


def _arb_mark_missing_assignment_predios_inactive(
    conn,
    asignacion_id: int,
    work_datasetname: str,
    schema_work: str,
    *,
    preview_limit: int = 10,
) -> dict:
    if not work_datasetname:
        return {
            "missing_predios": 0,
            "deactivated_predios": 0,
            "preview_predios": [],
        }

    preview_size = max(int(preview_limit or 0), 1)
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS _arb_ws_missing_assignment_predio")
        asignacion_predio_table = app_table(tenant, "asignacion_predio")
        cur.execute(
            f"""
            CREATE TEMP TABLE _arb_ws_missing_assignment_predio AS
            SELECT DISTINCT BTRIM(ap.numero_predial_nacional::text) AS numero_predial_nacional
            FROM {asignacion_predio_table} ap
            WHERE ap.asignacion_id = %s
              AND ap.activo IS DISTINCT FROM FALSE
              AND NOT EXISTS (
                  SELECT 1
                  FROM {_qualify(schema_work, 'arb_predio')} p
                  JOIN {_qualify(schema_work, 't_ili2db_basket')} b
                    ON b.t_id = p.t_basket
                  JOIN {_qualify(schema_work, 't_ili2db_dataset')} d
                    ON d.t_id = b.dataset
                  WHERE d.datasetname = %s
                    AND BTRIM(p.numero_predial::text) = BTRIM(ap.numero_predial_nacional::text)
              )
            """,
            (asignacion_id, work_datasetname),
        )
        cur.execute("SELECT COUNT(*) FROM _arb_ws_missing_assignment_predio")
        missing_predios = int((cur.fetchone() or [0])[0] or 0)
        if missing_predios <= 0:
            return {
                "missing_predios": 0,
                "deactivated_predios": 0,
                "preview_predios": [],
            }

        cur.execute(
            """
            SELECT numero_predial_nacional
            FROM _arb_ws_missing_assignment_predio
            ORDER BY numero_predial_nacional
            LIMIT %s
            """,
            (preview_size,),
        )
        preview_predios = [
            str(row[0]).strip()
            for row in (cur.fetchall() or [])
            if row and row[0] is not None and str(row[0]).strip()
        ]

        cur.execute(
            f"""
            UPDATE {asignacion_predio_table} ap
            SET activo = FALSE
            FROM _arb_ws_missing_assignment_predio mp
            WHERE ap.asignacion_id = %s
              AND ap.activo IS DISTINCT FROM FALSE
              AND BTRIM(ap.numero_predial_nacional::text) = mp.numero_predial_nacional
            """,
            (asignacion_id,),
        )

    return {
        "missing_predios": missing_predios,
        "deactivated_predios": missing_predios,
        "preview_predios": preview_predios,
    }


def mark_missing_assignment_predios_inactive(
    conn,
    asignacion_id: int,
    schema_work: str,
    work_datasetname: str,
    *,
    preview_limit: int = 10,
) -> dict:
    if not work_datasetname:
        return {
            "missing_predios": 0,
            "deactivated_predios": 0,
            "preview_predios": [],
        }

    workspace_ctx = workspace_schema_service.get_workspace_context(schema_work)
    if workspace_ctx.model_name != "arb":
        return {
            "missing_predios": 0,
            "deactivated_predios": 0,
            "preview_predios": [],
        }

    return _arb_mark_missing_assignment_predios_inactive(
        conn,
        asignacion_id,
        work_datasetname,
        schema_work,
        preview_limit=preview_limit,
    )


def _arb_replace_direct_child_table(
    conn,
    schema_main: str,
    schema_work: str,
    table_name: str,
    predio_fk: str,
) -> int:
    existing_main = _schema_table_names(conn, schema_main)
    existing_work = _schema_table_names(conn, schema_work)
    if table_name not in existing_main or table_name not in existing_work:
        return 0

    copy_cols = _get_common_table_columns(
        conn,
        schema_main,
        schema_work,
        table_name,
        exclude={"t_id", "t_basket", predio_fk},
    )
    insert_cols = list(copy_cols) + [predio_fk]
    select_exprs = [f"w.{col}" for col in copy_cols] + ["pm.main_predio_t_id"]
    main_cols = set(_get_table_columns(conn, schema_main, table_name))
    work_cols = set(_get_table_columns(conn, schema_work, table_name))
    if "t_basket" in main_cols and "t_basket" in work_cols:
        insert_cols.append("t_basket")
        select_exprs.append("bm.main_basket")

    with conn.cursor() as cur:
        cur.execute(
            f"""
            DELETE FROM {_qualify(schema_main, table_name)} t
            USING _arb_sync_predio_map pm
            WHERE t.{predio_fk} = pm.main_predio_t_id
            """
        )
        cur.execute(
            f"""
            INSERT INTO {_qualify(schema_main, table_name)} ({', '.join(insert_cols)})
            SELECT {', '.join(select_exprs)}
            FROM {_qualify(schema_work, table_name)} w
            JOIN _arb_sync_predio_map pm
              ON w.{predio_fk} = pm.work_predio_t_id
            LEFT JOIN _arb_sync_basket_map bm
              ON bm.work_basket = w.t_basket
            ORDER BY w.t_id
            """
        )
        return cur.rowcount or 0


def _arb_replace_attachment_table(
    conn,
    schema_main: str,
    schema_work: str,
    table_name: str,
    parent_table: str,
    attachment_fk: str,
    *,
    parent_predio_fk: str = "predio",
) -> int:
    existing_main = _schema_table_names(conn, schema_main)
    existing_work = _schema_table_names(conn, schema_work)
    required = {table_name, parent_table}
    if not required.issubset(existing_main) or not required.issubset(existing_work):
        return 0

    copy_cols = _get_common_table_columns(
        conn,
        schema_main,
        schema_work,
        table_name,
        exclude={"t_id", "t_basket", attachment_fk},
    )
    insert_cols = list(copy_cols) + [attachment_fk]
    select_exprs = [f"w.{col}" for col in copy_cols] + ["mp.t_id"]
    main_cols = set(_get_table_columns(conn, schema_main, table_name))
    work_cols = set(_get_table_columns(conn, schema_work, table_name))
    if "t_basket" in main_cols and "t_basket" in work_cols:
        insert_cols.append("t_basket")
        select_exprs.append("bm.main_basket")

    with conn.cursor() as cur:
        cur.execute(
            f"""
            DELETE FROM {_qualify(schema_main, table_name)} a
            USING {_qualify(schema_main, parent_table)} p,
                  _arb_sync_predio_map pm
            WHERE a.{attachment_fk} = p.t_id
              AND p.{parent_predio_fk} = pm.main_predio_t_id
            """
        )
        cur.execute(
            f"""
            INSERT INTO {_qualify(schema_main, table_name)} ({', '.join(insert_cols)})
            SELECT {', '.join(select_exprs)}
            FROM {_qualify(schema_work, table_name)} w
            JOIN {_qualify(schema_work, parent_table)} wp
              ON wp.t_id = w.{attachment_fk}
            JOIN _arb_sync_predio_map pm_pred
              ON wp.{parent_predio_fk} = pm_pred.work_predio_t_id
            JOIN {_qualify(schema_main, parent_table)} mp
              ON BTRIM(mp.t_ili_tid::text) = BTRIM(wp.t_ili_tid::text)
            LEFT JOIN _arb_sync_basket_map bm
              ON bm.work_basket = w.t_basket
            """
        )
        return cur.rowcount or 0


def _arb_sync_construccion_stack(conn, schema_main: str, schema_work: str) -> None:
    existing_main = _schema_table_names(conn, schema_main)
    existing_work = _schema_table_names(conn, schema_work)
    if "arb_construccion" not in existing_main or "arb_construccion" not in existing_work:
        return
    has_cuc_main = {"arb_unidadconstruccion", "arb_caracteristicasunidadconstruccion"}.issubset(existing_main)
    has_cuc_work = {"arb_unidadconstruccion", "arb_caracteristicasunidadconstruccion"}.issubset(existing_work)
    has_cuc = has_cuc_main and has_cuc_work

    with conn.cursor() as cur:
        if "arb_adjuntounidadconstruccionvalor" in existing_main:
            cur.execute(
                f"""
                DELETE FROM {_qualify(schema_main, 'arb_adjuntounidadconstruccionvalor')} a
                USING {_qualify(schema_main, 'arb_unidadconstruccion')} u,
                      {_qualify(schema_main, 'arb_construccion')} c,
                      _arb_sync_predio_map pm
                WHERE a.arb_unidadconstruccion_adjunto = u.t_id
                  AND u.construccion = c.t_id
                  AND c.predio = pm.main_predio_t_id
                """
            )

        if has_cuc_main:
            cur.execute("DROP TABLE IF EXISTS _arb_sync_old_cuc")
            cur.execute(
                f"""
                CREATE TEMP TABLE _arb_sync_old_cuc AS
                SELECT DISTINCT c.t_id
                FROM {_qualify(schema_main, 'arb_caracteristicasunidadconstruccion')} c
                JOIN {_qualify(schema_main, 'arb_unidadconstruccion')} u
                  ON u.caracteristicasunidadconstruccion = c.t_id
                JOIN {_qualify(schema_main, 'arb_construccion')} mc
                  ON mc.t_id = u.construccion
                JOIN _arb_sync_predio_map pm
                  ON pm.main_predio_t_id = mc.predio
                """
            )

        if "arb_unidadconstruccion" in existing_main:
            cur.execute(
                f"""
                DELETE FROM {_qualify(schema_main, 'arb_unidadconstruccion')} u
                USING {_qualify(schema_main, 'arb_construccion')} c,
                      _arb_sync_predio_map pm
                WHERE u.construccion = c.t_id
                  AND c.predio = pm.main_predio_t_id
                """
            )

        if has_cuc_main:
            cur.execute(
                f"""
                DELETE FROM {_qualify(schema_main, 'arb_caracteristicasunidadconstruccion')} c
                WHERE c.t_id IN (SELECT t_id FROM _arb_sync_old_cuc)
                """
            )

        cur.execute(
            f"""
            DELETE FROM {_qualify(schema_main, 'arb_construccion')} c
            USING _arb_sync_predio_map pm
            WHERE c.predio = pm.main_predio_t_id
            """
        )

    if has_cuc:
        copy_cols = _get_common_table_columns(
            conn,
            schema_main,
            schema_work,
            "arb_caracteristicasunidadconstruccion",
            exclude={"t_id", "t_basket"},
        )
        insert_cols = list(copy_cols)
        select_exprs = [f"c.{col}" for col in copy_cols]
        main_cols = set(_get_table_columns(conn, schema_main, "arb_caracteristicasunidadconstruccion"))
        work_cols = set(_get_table_columns(conn, schema_work, "arb_caracteristicasunidadconstruccion"))
        if "t_basket" in main_cols and "t_basket" in work_cols:
            insert_cols.append("t_basket")
            select_exprs.append("bm.main_basket")

        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {_qualify(schema_main, 'arb_caracteristicasunidadconstruccion')} ({', '.join(insert_cols)})
                SELECT DISTINCT {', '.join(select_exprs)}
                FROM {_qualify(schema_work, 'arb_caracteristicasunidadconstruccion')} c
                JOIN {_qualify(schema_work, 'arb_unidadconstruccion')} u
                  ON u.caracteristicasunidadconstruccion = c.t_id
                JOIN {_qualify(schema_work, 'arb_construccion')} wc
                  ON wc.t_id = u.construccion
                JOIN _arb_sync_predio_map pm
                  ON pm.work_predio_t_id = wc.predio
                LEFT JOIN _arb_sync_basket_map bm
                  ON bm.work_basket = c.t_basket
                """
            )

    _arb_replace_direct_child_table(conn, schema_main, schema_work, "arb_construccion", "predio")

    if "arb_unidadconstruccion" not in existing_main or "arb_unidadconstruccion" not in existing_work:
        return

    constru_main_cols = set(_get_table_columns(conn, schema_main, "arb_construccion"))
    constru_work_cols = set(_get_table_columns(conn, schema_work, "arb_construccion"))
    constru_order_work: list[str] = []
    constru_order_main: list[str] = []
    for col in ("t_ili_tid", "identificador", "codigo", "etiqueta"):
        if col in constru_main_cols and col in constru_work_cols:
            constru_order_work.append(f"COALESCE(NULLIF(BTRIM(wc.{col}::text), ''), '')")
            constru_order_main.append(f"COALESCE(NULLIF(BTRIM(mc.{col}::text), ''), '')")
    constru_order_work.append("wc.t_id")
    constru_order_main.append("mc.t_id")

    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS _arb_sync_construccion_map")
        cur.execute(
            f"""
            CREATE TEMP TABLE _arb_sync_construccion_map AS
            WITH work_ranked AS (
                SELECT
                    wc.t_id AS work_construccion_t_id,
                    pm.main_predio_t_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY pm.main_predio_t_id
                        ORDER BY {', '.join(constru_order_work)}
                    ) AS rn
                FROM {_qualify(schema_work, 'arb_construccion')} wc
                JOIN _arb_sync_predio_map pm
                  ON pm.work_predio_t_id = wc.predio
            ),
            main_ranked AS (
                SELECT
                    mc.t_id AS main_construccion_t_id,
                    mc.predio AS main_predio_t_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY mc.predio
                        ORDER BY {', '.join(constru_order_main)}
                    ) AS rn
                FROM {_qualify(schema_main, 'arb_construccion')} mc
                JOIN _arb_sync_predio_map pm
                  ON pm.main_predio_t_id = mc.predio
            )
            SELECT
                w.work_construccion_t_id,
                m.main_construccion_t_id
            FROM work_ranked w
            JOIN main_ranked m
              ON m.main_predio_t_id = w.main_predio_t_id
             AND m.rn = w.rn
            """
        )

    copy_cols = _get_common_table_columns(
        conn,
        schema_main,
        schema_work,
        "arb_unidadconstruccion",
        exclude={"t_id", "t_basket", "construccion", "caracteristicasunidadconstruccion"},
    )
    insert_cols = list(copy_cols) + ["construccion", "caracteristicasunidadconstruccion"]
    select_exprs = [f"u.{col}" for col in copy_cols] + ["mc.t_id", "mcc.t_id" if has_cuc else "NULL"]
    main_cols = set(_get_table_columns(conn, schema_main, "arb_unidadconstruccion"))
    work_cols = set(_get_table_columns(conn, schema_work, "arb_unidadconstruccion"))
    if "t_basket" in main_cols and "t_basket" in work_cols:
        insert_cols.append("t_basket")
        select_exprs.append("bm.main_basket")

    cuc_join_sql = ""
    if has_cuc:
        cuc_join_sql = (
            f"LEFT JOIN {_qualify(schema_work, 'arb_caracteristicasunidadconstruccion')} wcc "
            f"ON wcc.t_id = u.caracteristicasunidadconstruccion "
            f"LEFT JOIN {_qualify(schema_main, 'arb_caracteristicasunidadconstruccion')} mcc "
            f"ON BTRIM(mcc.t_ili_tid::text) = BTRIM(wcc.t_ili_tid::text)"
        )

    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {_qualify(schema_main, 'arb_unidadconstruccion')} ({', '.join(insert_cols)})
            SELECT {', '.join(select_exprs)}
            FROM {_qualify(schema_work, 'arb_unidadconstruccion')} u
            JOIN {_qualify(schema_work, 'arb_construccion')} wc
              ON wc.t_id = u.construccion
            JOIN _arb_sync_construccion_map cm
              ON cm.work_construccion_t_id = wc.t_id
            JOIN {_qualify(schema_main, 'arb_construccion')} mc
              ON mc.t_id = cm.main_construccion_t_id
            {cuc_join_sql}
            LEFT JOIN _arb_sync_basket_map bm
              ON bm.work_basket = u.t_basket
            ORDER BY u.t_id
            """
        )

    unidad_main_cols = set(_get_table_columns(conn, schema_main, "arb_unidadconstruccion"))
    unidad_work_cols = set(_get_table_columns(conn, schema_work, "arb_unidadconstruccion"))
    unidad_order_work: list[str] = []
    unidad_order_main: list[str] = []
    for col in ("t_ili_tid", "identificador", "codigo"):
        if col in unidad_main_cols and col in unidad_work_cols:
            unidad_order_work.append(f"COALESCE(NULLIF(BTRIM(wu.{col}::text), ''), '')")
            unidad_order_main.append(f"COALESCE(NULLIF(BTRIM(mu.{col}::text), ''), '')")
    unidad_order_work.append("wu.t_id")
    unidad_order_main.append("mu.t_id")

    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS _arb_sync_unidad_map")
        cur.execute(
            f"""
            CREATE TEMP TABLE _arb_sync_unidad_map AS
            WITH work_ranked AS (
                SELECT
                    wu.t_id AS work_unidad_t_id,
                    cm.main_construccion_t_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY cm.main_construccion_t_id
                        ORDER BY {', '.join(unidad_order_work)}
                    ) AS rn
                FROM {_qualify(schema_work, 'arb_unidadconstruccion')} wu
                JOIN _arb_sync_construccion_map cm
                  ON cm.work_construccion_t_id = wu.construccion
            ),
            main_ranked AS (
                SELECT
                    mu.t_id AS main_unidad_t_id,
                    mu.construccion AS main_construccion_t_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY mu.construccion
                        ORDER BY {', '.join(unidad_order_main)}
                    ) AS rn
                FROM {_qualify(schema_main, 'arb_unidadconstruccion')} mu
                JOIN _arb_sync_construccion_map cm
                  ON cm.main_construccion_t_id = mu.construccion
            )
            SELECT
                w.work_unidad_t_id,
                m.main_unidad_t_id
            FROM work_ranked w
            JOIN main_ranked m
              ON m.main_construccion_t_id = w.main_construccion_t_id
             AND m.rn = w.rn
            """
        )

    if "arb_adjuntounidadconstruccionvalor" in existing_main and "arb_adjuntounidadconstruccionvalor" in existing_work:
        copy_cols = _get_common_table_columns(
            conn,
            schema_main,
            schema_work,
            "arb_adjuntounidadconstruccionvalor",
            exclude={"t_id", "t_basket", "arb_unidadconstruccion_adjunto"},
        )
        insert_cols = list(copy_cols) + ["arb_unidadconstruccion_adjunto"]
        select_exprs = [f"a.{col}" for col in copy_cols] + ["mu.t_id"]
        main_cols = set(_get_table_columns(conn, schema_main, "arb_adjuntounidadconstruccionvalor"))
        work_cols = set(_get_table_columns(conn, schema_work, "arb_adjuntounidadconstruccionvalor"))
        if "t_basket" in main_cols and "t_basket" in work_cols:
            insert_cols.append("t_basket")
            select_exprs.append("bm.main_basket")

        with conn.cursor() as cur:
            cur.execute(
                f"""
            INSERT INTO {_qualify(schema_main, 'arb_adjuntounidadconstruccionvalor')} ({', '.join(insert_cols)})
            SELECT {', '.join(select_exprs)}
            FROM {_qualify(schema_work, 'arb_adjuntounidadconstruccionvalor')} a
            JOIN {_qualify(schema_work, 'arb_unidadconstruccion')} wu
              ON wu.t_id = a.arb_unidadconstruccion_adjunto
            JOIN {_qualify(schema_work, 'arb_construccion')} wc
              ON wc.t_id = wu.construccion
            JOIN _arb_sync_unidad_map um
              ON um.work_unidad_t_id = wu.t_id
            JOIN {_qualify(schema_main, 'arb_unidadconstruccion')} mu
              ON mu.t_id = um.main_unidad_t_id
            LEFT JOIN _arb_sync_basket_map bm
              ON bm.work_basket = a.t_basket
            ORDER BY a.t_id
            """
        )


def _arb_sync_tramite_stack(conn, schema_main: str, schema_work: str) -> None:
    existing_main = _schema_table_names(conn, schema_main)
    existing_work = _schema_table_names(conn, schema_work)
    if "arb_tramite" not in existing_main or "arb_tramite" not in existing_work:
        return
    if "arb_predio_tramite" not in existing_main or "arb_predio_tramite" not in existing_work:
        return

    with conn.cursor() as cur:
        # 1. Insert new tramites from work to main schema, matching on t_ili_tid
        cur.execute(
            f"""
            INSERT INTO {_qualify(schema_main, 'arb_tramite')} (
                t_basket, t_ili_tid, entidad, fecha_radicacion, numero_radicacion, 
                numero_resolucion, fecha_resolucion, fecha_inscripcion, dato_rectificar, 
                dato_complementar, fecha_tramite, fecha_aprobacion, tercero_interesado, 
                codigos_asociados, tipo_pedido_solicitud, numero_tramite_link, asesor, 
                tramite_asociado_padre, predios_resultantes, considerando, created_user, 
                created_date, last_user, last_date, aplica_efectos_registrales, 
                numero_solicitud, numero_tramite, codigo_inicial, tipo_tramite, 
                tipo_mutacion, subtipo_mutacion, tramite, clasificacion_mutacion, 
                resuelta, observacion
            )
            SELECT DISTINCT
                bm.main_basket, w.t_ili_tid, w.entidad, w.fecha_radicacion, w.numero_radicacion, 
                w.numero_resolucion, w.fecha_resolucion, w.fecha_inscripcion, w.dato_rectificar, 
                w.dato_complementar, w.fecha_tramite, w.fecha_aprobacion, w.tercero_interesado, 
                w.codigos_asociados, w.tipo_pedido_solicitud, w.numero_tramite_link, w.asesor, 
                w.tramite_asociado_padre, w.predios_resultantes, w.considerando, w.created_user, 
                w.created_date, w.last_user, w.last_date, w.aplica_efectos_registrales, 
                w.numero_solicitud, w.numero_tramite, w.codigo_inicial, w.tipo_tramite, 
                w.tipo_mutacion, w.subtipo_mutacion, w.tramite, w.clasificacion_mutacion, 
                w.resuelta, w.observacion
            FROM {_qualify(schema_work, 'arb_tramite')} w
            JOIN {_qualify(schema_work, 'arb_predio_tramite')} pt ON pt.tramite = w.t_id
            JOIN _arb_sync_predio_map pm ON pm.work_predio_t_id = pt.predio
            LEFT JOIN _arb_sync_basket_map bm ON bm.work_basket = w.t_basket
            WHERE NOT EXISTS (
                SELECT 1
                FROM {_qualify(schema_main, 'arb_tramite')} m
                WHERE m.t_ili_tid = w.t_ili_tid
            )
            """
        )

        # 2. Update existing tramites in main schema
        cur.execute(
            f"""
            UPDATE {_qualify(schema_main, 'arb_tramite')} m
            SET entidad = w.entidad,
                fecha_radicacion = w.fecha_radicacion,
                numero_radicacion = w.numero_radicacion,
                numero_resolucion = w.numero_resolucion,
                fecha_resolucion = w.fecha_resolucion,
                fecha_inscripcion = w.fecha_inscripcion,
                dato_rectificar = w.dato_rectificar,
                dato_complementar = w.dato_complementar,
                fecha_tramite = w.fecha_tramite,
                fecha_aprobacion = w.fecha_aprobacion,
                tercero_interesado = w.tercero_interesado,
                codigos_asociados = w.codigos_asociados,
                tipo_pedido_solicitud = w.tipo_pedido_solicitud,
                numero_tramite_link = w.numero_tramite_link,
                asesor = w.asesor,
                tramite_asociado_padre = w.tramite_asociado_padre,
                predios_resultantes = w.predios_resultantes,
                considerando = w.considerando,
                last_user = w.last_user,
                last_date = w.last_date,
                aplica_efectos_registrales = w.aplica_efectos_registrales,
                numero_solicitud = w.numero_solicitud,
                numero_tramite = w.numero_tramite,
                codigo_inicial = w.codigo_inicial,
                tipo_tramite = w.tipo_tramite,
                tipo_mutacion = w.tipo_mutacion,
                subtipo_mutacion = w.subtipo_mutacion,
                tramite = w.tramite,
                clasificacion_mutacion = w.clasificacion_mutacion,
                resuelta = w.resuelta,
                observacion = w.observacion
            FROM {_qualify(schema_work, 'arb_tramite')} w
            JOIN {_qualify(schema_work, 'arb_predio_tramite')} pt ON pt.tramite = w.t_id
            JOIN _arb_sync_predio_map pm ON pm.work_predio_t_id = pt.predio
            WHERE m.t_ili_tid = w.t_ili_tid
            """
        )

        # 3. Create temp mapping table _arb_sync_tramite_map
        cur.execute("DROP TABLE IF EXISTS _arb_sync_tramite_map")
        cur.execute(
            f"""
            CREATE TEMP TABLE _arb_sync_tramite_map AS
            SELECT w.t_id AS work_tramite_t_id, m.t_id AS main_tramite_t_id
            FROM {_qualify(schema_work, 'arb_tramite')} w
            JOIN {_qualify(schema_main, 'arb_tramite')} m ON m.t_ili_tid = w.t_ili_tid
            """
        )

        # 4. Delete existing arb_predio_tramite rows in main schema for these predios
        cur.execute(
            f"""
            DELETE FROM {_qualify(schema_main, 'arb_predio_tramite')} pt
            USING _arb_sync_predio_map pm
            WHERE pt.predio = pm.main_predio_t_id
            """
        )

        # 5. Insert new arb_predio_tramite rows using maps
        cur.execute(
            f"""
            INSERT INTO {_qualify(schema_main, 'arb_predio_tramite')} (t_basket, predio, tramite)
            SELECT bm.main_basket, pm.main_predio_t_id, tm.main_tramite_t_id
            FROM {_qualify(schema_work, 'arb_predio_tramite')} pt
            JOIN _arb_sync_predio_map pm ON pm.work_predio_t_id = pt.predio
            JOIN _arb_sync_tramite_map tm ON tm.work_tramite_t_id = pt.tramite
            LEFT JOIN _arb_sync_basket_map bm ON bm.work_basket = pt.t_basket
            """
        )


def _sync_workspace_arb_to_main(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    work_datasetname: str,
    schema_main: str,
    schema_work: str,
) -> int:
    existing_main = _schema_table_names(conn, schema_main)
    existing_work = _schema_table_names(conn, schema_work)
    required = {"arb_predio", "t_ili2db_basket", "t_ili2db_dataset"}
    if not required.issubset(existing_main):
        raise export_service.ExportServiceError(
            status_code=500,
            detail=f"El schema principal '{schema_main}' no tiene la estructura Arbimaps requerida para sincronizar.",
        )
    if not required.issubset(existing_work):
        raise export_service.ExportServiceError(
            status_code=500,
            detail=f"El schema workspace '{schema_work}' no tiene la estructura Arbimaps requerida para sincronizar.",
        )

    _arb_assert_schema_parity(conn, schema_main, schema_work)
    _arb_create_sync_basket_map(conn, schema_main, schema_work, work_datasetname)
    synced_predios = _arb_sync_predios_to_main(conn, tenant, asignacion_id, work_datasetname, schema_main, schema_work)

    direct_predio_tables = [
        ("arb_avaluovalor", "arb_predio_avaluo"),
        ("arb_direccion", "arb_predio_direccion"),
        ("arb_informacionph", "arb_predio"),
        ("arb_marca", "predio"),
        ("arb_novedadfmivalor", "arb_predio_novedad_fmi"),
        ("arb_novedadnumeropredialvalor", "arb_predio_novedad_numero_predial"),
        ("arb_referenciaregistralsistemaantiguovalor", "arb_predio_referencia_registral_sistema_antiguo"),
        ("arb_terrenohistorico", "predio"),
        ("arb_puntoreferencia", "predio"),
        ("arb_terreno", "predio"),
        ("arb_derechointeresadofuente", "predio"),
    ]
    for table_name, predio_fk in direct_predio_tables:
        _arb_replace_direct_child_table(conn, schema_main, schema_work, table_name, predio_fk)

    _arb_sync_construccion_stack(conn, schema_main, schema_work)
    _arb_sync_tramite_stack(conn, schema_main, schema_work)

    attachment_specs = [
        ("arb_adjuntofuenteadministrativavalor", "arb_derechointeresadofuente", "arb_derechointersdfnte_fa_adjunto"),
        ("arb_adjuntointeresadovalor", "arb_derechointeresadofuente", "arb_derechointersdfnte_i_adjunto"),
        ("arb_adjuntopuntoreferenciavalor", "arb_puntoreferencia", "arb_puntoreferencia_adjunto"),
        ("arb_adjuntoterrenovalor", "arb_terreno", "arb_terreno_adjunto"),
    ]
    for table_name, parent_table, parent_fk in attachment_specs:
        _arb_replace_attachment_table(conn, schema_main, schema_work, table_name, parent_table, parent_fk)

    _arb_validate_post_sync_counts(conn, schema_main, schema_work)
    return synced_predios


def sync_workspace_predios_to_main(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    work_datasetname: str,
    schema_main: str,
    schema_work: str,
) -> int:
    if not work_datasetname:
        return 0
    workspace_ctx = workspace_schema_service.get_workspace_context(schema_work)
    if workspace_ctx.model_name == "arb":
        return _sync_workspace_arb_to_main(
            conn,
            tenant,
            asignacion_id,
            work_datasetname,
            schema_main,
            schema_work,
        )
    update_cols = _get_predio_updatable_columns(conn, schema_main)
    if not update_cols:
        return 0

    set_clause = sql.SQL(", ").join(
        [
            sql.SQL("{col} = src.{col}").format(col=sql.Identifier(col))
            for col in update_cols
        ]
    )
    query = sql.SQL(
        """
        UPDATE {main_predio} AS mp
        SET {set_clause}
        FROM (
            SELECT wp.*
            FROM {work_predio} wp
            JOIN {work_basket} wb ON wb.t_id = wp.t_basket
            JOIN {work_dataset} wd ON wd.t_id = wb.dataset
            JOIN {asignacion_predio} ap
              ON BTRIM(ap.numero_predial_nacional::text) = BTRIM(wp.numero_predial_nacional::text)
            WHERE ap.asignacion_id = %s
              AND ap.activo IS DISTINCT FROM FALSE
              AND wd.datasetname = %s
        ) AS src
        WHERE BTRIM(mp.numero_predial_nacional::text) = BTRIM(src.numero_predial_nacional::text)
        """
    ).format(
        main_predio=sql.Identifier(schema_main, "ilc_predio"),
        work_predio=sql.Identifier(schema_work, "ilc_predio"),
        work_basket=sql.Identifier(schema_work, "t_ili2db_basket"),
        work_dataset=sql.Identifier(schema_work, "t_ili2db_dataset"),
        asignacion_predio=sql.SQL(app_table(tenant, "asignacion_predio")),
        set_clause=set_clause,
    )

    with conn.cursor() as cur:
        cur.execute(query, (asignacion_id, work_datasetname))
        return cur.rowcount or 0


def workspace_dataset_exists(
    conn,
    tenant: TenantContext,
    datasetname: str,
) -> bool:
    if not datasetname:
        return False

    dataset_table = tenant_table(tenant, "t_ili2db_dataset", schema_name="work")

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT 1
            FROM {dataset_table}
            WHERE datasetname = %s
            LIMIT 1
            """,
            (datasetname,),
        )
        return cur.fetchone() is not None


def workspace_dataset_assignment_predio_count(
    conn,
    tenant: TenantContext,
    datasetname: str,
    asignacion_id: int,
) -> int:
    if not datasetname:
        return 0

    workspace_ctx = workspace_schema_service.get_workspace_context(tenant.schemas.work)
    predio_table = work_table(tenant, workspace_ctx.predio_table)
    basket_table = tenant_table(tenant, "t_ili2db_basket", schema_name="work")
    dataset_table = tenant_table(tenant, "t_ili2db_dataset", schema_name="work")
    asignacion_predio_table = app_table(tenant, "asignacion_predio")
    numero_field = workspace_ctx.predio_numero_field

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT p.{numero_field})
            FROM {predio_table} p
            JOIN {basket_table} b ON b.t_id = p.t_basket
            JOIN {dataset_table} d ON d.t_id = b.dataset
            JOIN {asignacion_predio_table} ap
              ON BTRIM(ap.numero_predial_nacional::text) = BTRIM(p.{numero_field}::text)
            WHERE d.datasetname = %s
              AND ap.asignacion_id = %s
              AND ap.activo IS DISTINCT FROM FALSE
            """,
            (datasetname, asignacion_id),
        )
        row = cur.fetchone()
        return int((row[0] if row else 0) or 0)


def workspace_dataset_total_predio_count(
    conn,
    tenant: TenantContext,
    datasetname: str,
) -> int:
    if not datasetname:
        return 0

    workspace_ctx = workspace_schema_service.get_workspace_context(tenant.schemas.work)
    predio_table = work_table(tenant, workspace_ctx.predio_table)
    basket_table = tenant_table(tenant, "t_ili2db_basket", schema_name="work")
    dataset_table = tenant_table(tenant, "t_ili2db_dataset", schema_name="work")

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {predio_table} p
            JOIN {basket_table} b ON b.t_id = p.t_basket
            JOIN {dataset_table} d ON d.t_id = b.dataset
            WHERE d.datasetname = %s
            """,
            (datasetname,),
        )
        row = cur.fetchone()
        return int((row[0] if row else 0) or 0)


def assignment_active_predio_count(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
) -> int:
    asignacion_predio_table = app_table(tenant, "asignacion_predio")

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT ap.numero_predial_nacional)
            FROM {asignacion_predio_table} ap
            WHERE ap.asignacion_id = %s
              AND ap.activo IS DISTINCT FROM FALSE
            """,
            (asignacion_id,),
        )
        row = cur.fetchone()
        return int((row[0] if row else 0) or 0)


def _dataset_exists_in_schema(conn, schema_name: str, datasetname: str) -> bool:
    if not datasetname:
        return False
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT 1
            FROM {_qualify(schema_name, 't_ili2db_dataset')}
            WHERE datasetname = %s
            LIMIT 1
            """,
            (datasetname,),
        )
        return bool(cur.fetchone())


def _count_dataset_baskets(conn, schema_name: str, datasetname: str) -> int:
    if not datasetname:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {_qualify(schema_name, 't_ili2db_basket')} b
            JOIN {_qualify(schema_name, 't_ili2db_dataset')} d
              ON d.t_id = b.dataset
            WHERE d.datasetname = %s
            """,
            (datasetname,),
        )
        row = cur.fetchone()
        return int((row[0] if row else 0) or 0)


def _count_dataset_predios(conn, schema_name: str, datasetname: str, predio_table: str, numero_field: str) -> int:
    if not datasetname:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT p.{numero_field})
            FROM {_qualify(schema_name, predio_table)} p
            JOIN {_qualify(schema_name, 't_ili2db_basket')} b
              ON b.t_id = p.t_basket
            JOIN {_qualify(schema_name, 't_ili2db_dataset')} d
              ON d.t_id = b.dataset
            WHERE d.datasetname = %s
            """,
            (datasetname,),
        )
        row = cur.fetchone()
        return int((row[0] if row else 0) or 0)


def _count_main_assigned_predios(
    conn,
    tenant: TenantContext,
    schema_main: str,
    asignacion_id: int,
) -> int:
    with conn.cursor() as cur:
        asignacion_predio_table = app_table(tenant, "asignacion_predio")
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT p.numero_predial)
            FROM {_qualify(schema_main, 'arb_predio')} p
            JOIN {asignacion_predio_table} ap
              ON BTRIM(ap.numero_predial_nacional::text) = BTRIM(p.numero_predial::text)
            WHERE ap.asignacion_id = %s
              AND ap.activo IS DISTINCT FROM FALSE
            """,
            (asignacion_id,),
        )
        row = cur.fetchone()
        return int((row[0] if row else 0) or 0)


def run_arb_workspace_smoke_test(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    *,
    schema_main: str,
    schema_work: str,
) -> dict:
    workspace_ctx = workspace_schema_service.ensure_workspace_schema_ready(
        conn,
        tenant,
        schema_work=schema_work,
    )
    if workspace_ctx.model_name != "arb":
        raise export_service.ExportServiceError(
            status_code=400,
            detail=(
                f"El smoke test Arbimaps requiere un workspace arb, pero '{schema_work}' "
                f"resuelve al modelo '{workspace_ctx.model_name}'."
            ),
        )

    result = {
        "status": "ok",
        "context": {
            "model": "arb",
            "schema_main": schema_main,
            "schema_work": schema_work,
        },
        "assignment": {},
        "counts": {},
        "checks": [],
        "warnings": [],
        "table_counts": [],
    }

    def add_check(name: str, ok: bool, detail: str) -> None:
        result["checks"].append({"name": name, "ok": ok, "detail": detail})

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        asignacion_table = app_table(tenant, "asignacion")
        cur.execute(
            f"""
            SELECT
                a.id,
                a.estado,
                a.titulo,
                a.usuario_asignado,
                a.creado_por,
                a.datasetname_main,
                a.work_datasetname,
                a.error_msg
            FROM {asignacion_table} a
            WHERE a.id = %s
            LIMIT 1
            """,
            (asignacion_id,),
        )
        asignacion = cur.fetchone()

        if not asignacion:
            raise export_service.ExportServiceError(
                status_code=404,
                detail=f"Asignacion {asignacion_id} no encontrada.",
            )

        with conn.cursor() as cur:
            asignacion_predio_table = app_table(tenant, "asignacion_predio")
            cur.execute(
                f"""
                SELECT COUNT(DISTINCT ap.numero_predial_nacional)
                FROM {asignacion_predio_table} ap
                WHERE ap.asignacion_id = %s
                  AND ap.activo IS DISTINCT FROM FALSE
                """,
                (asignacion_id,),
            )
            expected_predios = int(((cur.fetchone() or [0])[0]) or 0)

        datasetname_main = (asignacion.get("datasetname_main") or "").strip()
        work_datasetname = (asignacion.get("work_datasetname") or "").strip()
        result["assignment"] = {
            "id": int(asignacion.get("id") or asignacion_id),
            "estado": asignacion.get("estado"),
            "titulo": asignacion.get("titulo"),
            "usuario_asignado": asignacion.get("usuario_asignado"),
            "creado_por": asignacion.get("creado_por"),
            "datasetname_main": datasetname_main,
            "work_datasetname": work_datasetname,
            "error_msg": asignacion.get("error_msg"),
        }

        result["counts"]["expected_predios"] = expected_predios
        result["counts"]["main_assigned_predios"] = _count_main_assigned_predios(conn, tenant, schema_main, asignacion_id)
        result["counts"]["main_dataset_baskets"] = _count_dataset_baskets(conn, schema_main, datasetname_main)
        result["counts"]["main_dataset_predios"] = _count_dataset_predios(
            conn,
            schema_main,
            datasetname_main,
            "arb_predio",
            "numero_predial",
        )

        if not datasetname_main:
            result["warnings"].append("La asignacion no tiene datasetname_main definido.")
        if not work_datasetname:
            result["warnings"].append("La asignacion no tiene work_datasetname definido.")

        workspace_exists = _dataset_exists_in_schema(conn, schema_work, work_datasetname)
        add_check(
            "workspace_dataset_exists",
            workspace_exists,
            (
                f"Dataset {schema_work}:{work_datasetname} encontrado."
                if workspace_exists
                else f"Dataset {schema_work}:{work_datasetname} no existe."
            ),
        )

        if workspace_exists:
            result["counts"]["workspace_dataset_baskets"] = _count_dataset_baskets(conn, schema_work, work_datasetname)
            result["counts"]["workspace_dataset_predios"] = _count_dataset_predios(
                conn,
                schema_work,
                work_datasetname,
                "arb_predio",
                "numero_predial",
            )
            result["counts"]["workspace_assignment_predios"] = workspace_dataset_assignment_predio_count(
                conn,
                tenant,
                work_datasetname,
                asignacion_id,
            )
            soporte_extra = max(
                int(result["counts"]["workspace_dataset_predios"] or 0)
                - int(result["counts"]["workspace_assignment_predios"] or 0),
                0,
            )
            result["counts"]["workspace_support_predios"] = soporte_extra
            if soporte_extra > 0:
                result["warnings"].append(
                    f"El workspace contiene {soporte_extra} predio(s) de soporte fuera de la asignacion."
                )
        else:
            result["counts"]["workspace_dataset_baskets"] = 0
            result["counts"]["workspace_dataset_predios"] = 0
            result["counts"]["workspace_assignment_predios"] = 0
            result["counts"]["workspace_support_predios"] = 0

        try:
            _arb_assert_schema_parity(conn, schema_main, schema_work)
        except export_service.ExportServiceError as exc:
            add_check("schema_parity", False, exc.detail)
        else:
            add_check("schema_parity", True, f"{schema_main} y {schema_work} tienen la paridad Arbimaps minima esperada.")

        if workspace_exists:
            try:
                _arb_validate_workspace_dataset_health(conn, schema_work, work_datasetname)
            except export_service.ExportServiceError as exc:
                add_check("workspace_health", False, exc.detail)
            else:
                add_check(
                    "workspace_health",
                    True,
                    f"Workspace {schema_work}:{work_datasetname} valido para Arbimaps.",
                )

            try:
                _arb_create_sync_basket_map(conn, schema_main, schema_work, work_datasetname)
            except export_service.ExportServiceError as exc:
                add_check("basket_mapping", False, exc.detail)
                result["counts"]["mapped_baskets"] = 0
            else:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM _arb_sync_basket_map")
                    mapped_baskets = int((cur.fetchone() or [0])[0] or 0)
                result["counts"]["mapped_baskets"] = mapped_baskets
                add_check(
                    "basket_mapping",
                    True,
                    f"Mapeo de baskets listo: {mapped_baskets} basket(s) del workspace resueltos hacia {schema_main}.",
                )

            scope_counts = _arb_prepare_diagnostic_predio_map(
                conn,
                tenant,
                asignacion_id,
                work_datasetname,
                schema_main,
                schema_work,
            )
            result["counts"]["selected_predios_scope"] = int(scope_counts.get("selected_predios") or 0)
            result["counts"]["mapped_predios_scope"] = int(scope_counts.get("mapped_predios") or 0)
            mapped_scope_ok = (
                result["counts"]["mapped_predios_scope"] >= result["counts"]["selected_predios_scope"]
                and result["counts"]["selected_predios_scope"] > 0
            )
            add_check(
                "predio_mapping_scope",
                mapped_scope_ok,
                (
                    f"Predios del scope listos para sync: {result['counts']['mapped_predios_scope']}/"
                    f"{result['counts']['selected_predios_scope']}."
                    if mapped_scope_ok
                    else (
                        f"Predios del scope sin resolver completamente: "
                        f"{result['counts']['mapped_predios_scope']}/"
                        f"{result['counts']['selected_predios_scope']}."
                    )
                ),
            )

            if result["counts"]["selected_predios_scope"] > 0:
                try:
                    _arb_validate_sync_identity_fields(conn, schema_main, schema_work, work_datasetname)
                except export_service.ExportServiceError as exc:
                    add_check("sync_identity_fields", False, exc.detail)
                else:
                    add_check(
                        "sync_identity_fields",
                        True,
                        "Las columnas t_ili_tid y llaves de identidad requeridas estan listas para sincronizar.",
                    )

                comparisons, mismatches = _arb_collect_post_sync_count_pairs(conn, schema_main, schema_work)
                result["table_counts"] = comparisons
                if mismatches:
                    add_check(
                        "post_sync_count_parity",
                        False,
                        "Conteos inconsistentes entre workspace y principal: " + ", ".join(mismatches),
                    )
                else:
                    add_check(
                        "post_sync_count_parity",
                        True,
                        "Los conteos del workspace y del schema principal coinciden para el scope asignado.",
                    )

        conn.rollback()

    has_error = any(not check.get("ok") for check in result["checks"])
    if has_error:
        result["status"] = "error"
    elif result["warnings"]:
        result["status"] = "warning"
    return result


def remove_workspace_dataset(
    conn,
    tenant: TenantContext,
    datasetname: str,
    schema_work: str,
) -> dict:
    """
    Delete all rows tied to a workspace dataset via t_basket, then remove baskets and dataset.
    This keeps b_asignaciones free of stale rows that block re-assignment by t_id.
    """
    result = {
        "dataset_name": datasetname,
        "dataset_id": None,
        "rows_deleted": 0,
        "baskets_deleted": 0,
        "dataset_deleted": 0,
    }
    if not datasetname:
        return result

    dataset_table = sql.Identifier(schema_work, "t_ili2db_dataset")
    basket_table = sql.Identifier(schema_work, "t_ili2db_basket")

    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT t_id FROM {} WHERE datasetname = %s LIMIT 1").format(dataset_table),
            (datasetname,),
        )
        row = cur.fetchone()
        if not row:
            return result

        if isinstance(row, dict):
            dataset_id = row.get("t_id")
        else:
            dataset_id = row[0]
        if dataset_id is None:
            return result
        result["dataset_id"] = int(dataset_id)

        cur.execute(
            """
            SELECT table_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND column_name = 't_basket'
            GROUP BY table_name
            ORDER BY table_name
            """,
            (schema_work,),
        )
        basket_tables = []
        for r in (cur.fetchall() or []):
            if not r:
                continue
            if isinstance(r, dict):
                name = r.get("table_name")
            else:
                name = r[0]
            if name:
                basket_tables.append(name)

        rows_deleted = 0
        # Iterative cleanup: some tables depend on others via FK and cannot be
        # deleted in a single fixed order.
        for _ in range(30):
            pass_deleted = 0
            for table_name in basket_tables:
                cur.execute("SAVEPOINT ws_del_sp")
                try:
                    cur.execute(
                        sql.SQL(
                            """
                            DELETE FROM {target}
                            WHERE t_basket IN (
                                SELECT t_id
                                FROM {basket}
                                WHERE dataset = %s
                            )
                            """
                        ).format(
                            target=sql.Identifier(schema_work, table_name),
                            basket=basket_table,
                        ),
                        (dataset_id,),
                    )
                    pass_deleted += int(cur.rowcount or 0)
                    cur.execute("RELEASE SAVEPOINT ws_del_sp")
                except Exception:
                    cur.execute("ROLLBACK TO SAVEPOINT ws_del_sp")
                    cur.execute("RELEASE SAVEPOINT ws_del_sp")
            rows_deleted += pass_deleted
            if pass_deleted == 0:
                break

        cur.execute(
            sql.SQL("DELETE FROM {} WHERE dataset = %s").format(basket_table),
            (dataset_id,),
        )
        baskets_deleted = int(cur.rowcount or 0)

        cur.execute(
            sql.SQL("DELETE FROM {} WHERE t_id = %s").format(dataset_table),
            (dataset_id,),
        )
        dataset_deleted = int(cur.rowcount or 0)

    result["rows_deleted"] = rows_deleted
    result["baskets_deleted"] = baskets_deleted
    result["dataset_deleted"] = dataset_deleted
    return result


def cleanup_orphan_workspace_datasets(
    conn,
    tenant: TenantContext,
    schema_work: str,
    *,
    limit: int = 25,
) -> dict:
    """
    Remove workspace datasets with no active assignment reference.
    """
    max_items = max(int(limit or 0), 1)
    cleaned: list[dict] = []
    with conn.cursor() as cur:
        asignacion_table = app_table(tenant, "asignacion")
        cur.execute(
            sql.SQL(
                """
                SELECT d.datasetname
                FROM {} d
                LEFT JOIN {} a
                  ON BTRIM(a.work_datasetname::text) = BTRIM(d.datasetname::text)
                 AND a.estado IS DISTINCT FROM 'CERRADA'
                WHERE a.id IS NULL
                ORDER BY d.datasetname
                LIMIT %s
                """
            ).format(
                sql.Identifier(schema_work, "t_ili2db_dataset"),
                sql.SQL(asignacion_table),
            ),
            (max_items,),
        )
        orphan_rows = [str(r[0]).strip() for r in (cur.fetchall() or []) if r and r[0]]

    for ds_name in orphan_rows:
        cleanup = remove_workspace_dataset(conn, tenant, ds_name, schema_work)
        if int(cleanup.get("dataset_deleted") or 0) > 0:
            cleaned.append(cleanup)

    return {
        "detected": len(orphan_rows),
        "cleaned": len(cleaned),
        "items": cleaned,
    }


def build_workspace_for_assignment(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    *,
    schema_main: str,
    schema_work: str,
    datasetname_main: str,
    work_datasetname: str,
    ili2pg_cmd: str,
    timeout_sec: int,
    basket_tids_to_use: Optional[List[str]] = None,
    export_main_by_dataset: bool = False,
) -> dict:
    workspace_ctx = workspace_schema_service.ensure_workspace_schema_ready(
        conn,
        tenant,
        schema_work=schema_work,
    )
    expected_predios = assignment_active_predio_count(conn, tenant, asignacion_id)
    if expected_predios <= 0:
        raise export_service.ExportServiceError(
            status_code=400,
            detail=f"La asignacion {asignacion_id} no tiene predios activos para construir workspace.",
        )

    datasetname_main = (datasetname_main or "").strip()
    work_datasetname = (work_datasetname or "").strip()
    if not datasetname_main:
        raise export_service.ExportServiceError(
            status_code=400,
            detail="La asignacion no tiene dataset origen para construir workspace.",
        )
    if not work_datasetname:
        raise export_service.ExportServiceError(
            status_code=400,
            detail="La asignacion no tiene dataset de workspace definido.",
        )

    if workspace_ctx.build_strategy == "legacy_sql":
        _ensure_workspace_enum_tables_populated(conn, tenant, schema_main, schema_work)
        result = workspace_sql_service.run_insertar_predios_for_asignacion(
            conn,
            tenant,
            asignacion_id,
            dataset_name=work_datasetname,
            schema_work=schema_work,
        )
        actualizar_predio_ids_desde_workspace(conn, tenant, asignacion_id)
        conn.commit()

        predios_dataset = workspace_dataset_total_predio_count(conn, tenant, work_datasetname)
        predios_asignacion = workspace_dataset_assignment_predio_count(
            conn,
            tenant,
            work_datasetname,
            asignacion_id,
        )
        predios_soporte_extra = max(predios_dataset - predios_asignacion, 0)

        return {
            "dataset_name": work_datasetname,
            "checkout_mode": "legacy_sql",
            "expected_predios": expected_predios,
            "predios_cargados": predios_dataset,
            "predios_asignacion": predios_asignacion,
            "predios_soporte_extra": predios_soporte_extra,
            "removed_predios": 0,
            "has_integrity_warnings": predios_soporte_extra > 0 or predios_asignacion != expected_predios,
        }

    if workspace_dataset_exists(conn, tenant, work_datasetname):
        remove_workspace_dataset(conn, tenant, work_datasetname, schema_work)
        conn.commit()

    if workspace_ctx.model_name == "arb":
        _arb_disable_workspace_unique_constraints(conn, tenant, schema_work)

    checkout_mode = "baskets"
    with tempfile.TemporaryDirectory() as td:
        xtf_path = os.path.join(td, f"workspace_build_{asignacion_id}.xtf")
        
        basket_ids = [bid for bid in (basket_tids_to_use or []) if bid]
        if not basket_ids and not export_main_by_dataset:
            try:
                basket_ids = export_service._list_assignment_basket_bids(
                    conn,
                    tenant,
                    schema_main,
                    asignacion_id,
                    datasetname_main,
                )
            except Exception:
                pass

        if export_main_by_dataset or not basket_ids:
            checkout_mode = "dataset_full" if workspace_ctx.model_name == "arb" else "dataset"
            export_service.ili2pg_export_by_dataset(
                tenant,
                schema_main,
                datasetname_main,
                xtf_path,
                ili2pg_cmd=ili2pg_cmd,
                timeout_sec=timeout_sec,
            )
        else:
            export_service.ili2pg_export(
                tenant,
                schema_main,
                basket_ids,
                xtf_path,
                ili2pg_cmd=ili2pg_cmd,
                timeout_sec=timeout_sec,
            )

        _ensure_workspace_enum_tables_populated(conn, tenant, schema_main, schema_work)
        export_service.ili2pg_import(
            conn,
            tenant,
            schema_work,
            work_datasetname,
            xtf_path,
            ili2pg_cmd=ili2pg_cmd,
            timeout_sec=timeout_sec,
        )

    removed_predios = prune_workspace_predios(conn, tenant, asignacion_id, work_datasetname, schema_work)
    if workspace_ctx.model_name == "arb":
        _arb_validate_workspace_dataset_health(conn, schema_work, work_datasetname)
    actualizar_predio_ids_desde_workspace(conn, tenant, asignacion_id)
    conn.commit()

    predios_dataset = workspace_dataset_total_predio_count(conn, tenant, work_datasetname)
    predios_asignacion = workspace_dataset_assignment_predio_count(
        conn,
        tenant,
        work_datasetname,
        asignacion_id,
)
    predios_soporte_extra = max(predios_dataset - predios_asignacion, 0)

    if predios_asignacion < expected_predios:
        raise export_service.ExportServiceError(
            status_code=409,
            detail=(
                f"Workspace incompleto para construir: {predios_asignacion}/{expected_predios} "
                f"predios activos en {schema_work}:{work_datasetname}."
            ),
        )

    return {
        "dataset_name": work_datasetname,
        "checkout_mode": checkout_mode,
        "expected_predios": expected_predios,
        "predios_cargados": predios_dataset,
        "predios_asignacion": predios_asignacion,
        "predios_soporte_extra": predios_soporte_extra,
        "removed_predios": removed_predios,
        "has_integrity_warnings": predios_soporte_extra > 0 or predios_asignacion != expected_predios,
    }


def ensure_workspace_ready_for_export(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    created_by: Optional[str],
    *,
    schema_main: str,
    schema_work: str,
    datasetname_main_default: str,
    ili2pg_cmd: str,
    timeout_sec: int,
    required_topics: Optional[List[str]] = None,
    update_asignacion_fields: Callable[..., None],
    safe_log_event: Callable[[int, str, Optional[str], Optional[str]], None],
) -> str:
    workspace_ctx = workspace_schema_service.ensure_workspace_schema_ready(
        conn,
        tenant,
        schema_work=schema_work,
    )
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        asignacion_table = app_table(tenant, "asignacion")
        cur.execute(
            f"""
            SELECT id, work_datasetname, datasetname_main
            FROM {asignacion_table}
            WHERE id = %s
            """,
            (asignacion_id,),
        )
        asignacion = cur.fetchone()

    if not asignacion:
        raise export_service.ExportServiceError(status_code=404, detail="Asignacion no encontrada.")

    work_dataset = (asignacion.get("work_datasetname") or "").strip()
    if not work_dataset:
        raise export_service.ExportServiceError(
            status_code=400,
            detail="La asignacion no tiene workspace definido.",
        )

    expected_predios = assignment_active_predio_count(conn, tenant, asignacion_id)
    if expected_predios <= 0:
        raise export_service.ExportServiceError(
            status_code=400,
            detail=(
                f"La asignacion {asignacion_id} no tiene predios activos para exportar."
            ),
        )

    workspace_is_b_asig = workspace_ctx.build_strategy == "legacy_sql"

    if workspace_dataset_exists(conn, tenant, work_dataset):
        predios_count = workspace_dataset_assignment_predio_count(
            conn,
            tenant,
            work_dataset,
            asignacion_id,
        )
        total_predios = workspace_dataset_total_predio_count(conn, tenant, work_dataset)
        if predios_count >= expected_predios:
            if workspace_ctx.model_name == "arb":
                try:
                    _arb_validate_workspace_dataset_health(conn, schema_work, work_dataset)
                except export_service.ExportServiceError as exc:
                    safe_log_event(
                        asignacion_id,
                        "WORKSPACE_ARB_INVALIDO",
                        (
                            f"Workspace {work_dataset} requiere reconstruccion por validacion Arbimaps: "
                            f"{exc.detail}"
                        ),
                        created_by,
                    )
                else:
                    return work_dataset
            else:
                return work_dataset
        evento = "WORKSPACE_DATASET_VACIO" if predios_count == 0 else "WORKSPACE_DATASET_INCOMPLETO"
        msg = (
            f"Dataset {work_dataset} existe en {schema_work} con {predios_count}/{expected_predios} "
            f"predios activos de la asignacion y {total_predios} predio(s) totales. "
            f"Se intentara reconstruir."
        )
        safe_log_event(
            asignacion_id,
            evento,
            msg,
            created_by,
        )

    # En b_asignaciones la reconstruccion debe ser completa desde predios seleccionados,
    # usando el SQL de workspace (no checkout parcial por ili2pg).
    if workspace_is_b_asig:
        _ensure_workspace_enum_tables_populated(conn, tenant, schema_main, schema_work)
        result = workspace_sql_service.run_insertar_predios_for_asignacion(
            conn,
            tenant,
            asignacion_id,
            dataset_name=work_dataset,
            schema_work=schema_work,
        )
        actualizar_predio_ids_desde_workspace(conn, tenant, asignacion_id)
        conn.commit()
        dataset_sql = (result.get("dataset_name") or work_dataset or "").strip()
        if not dataset_sql:
            dataset_sql = work_dataset

        final_predios = workspace_dataset_assignment_predio_count(
            conn,
            tenant,
            dataset_sql,
            asignacion_id,
        )
        if final_predios < expected_predios:
            safe_log_event(
                asignacion_id,
                "WORKSPACE_ON_DEMAND_INCOMPLETO",
                (
                    f"Workspace {dataset_sql} incompleto para exportacion: "
                    f"{final_predios}/{expected_predios} predios activos."
                ),
                created_by,
            )
            raise export_service.ExportServiceError(
                status_code=409,
                detail=(
                    f"Workspace incompleto para exportar: {final_predios}/{expected_predios} "
                    f"predios activos en {schema_work}:{dataset_sql}."
                ),
            )

        try:
            if workspace_ctx.model_name != "arb":
                export_service._run_validate_derecho_with_retry(conn, schema_work, dataset_sql)
                export_service._run_validate_agrup_with_retry(conn, schema_work, dataset_sql)
        except export_service.ExportServiceError as exc:
            safe_log_event(
                asignacion_id,
                "WORKSPACE_ON_DEMAND_INTEGRITY_ERROR",
                (
                    f"Workspace {dataset_sql} con integridad incompleta tras reconstruccion SQL: "
                    f"{exc.detail}"
                ),
                created_by,
            )
            raise

        try:
            predios_soporte_extra = int(result.get("predios_soporte_extra") or 0)
        except Exception:
            predios_soporte_extra = 0

        update_asignacion_fields(
            asignacion_id,
            estado="EN_CAMPO" if workspace_ctx.model_name == "arb" else "EN_TRABAJO",
            error_msg=None,
            work_datasetname=dataset_sql,
            predios_soporte_extra=predios_soporte_extra,
        )
        safe_log_event(
            asignacion_id,
            "WORKSPACE_ON_DEMAND_SQL",
            (
                f"Workspace {dataset_sql} reconstruido por SQL completo. "
                f"Semilla={result.get('seed_predios', 0)} "
                f"cargados={result.get('predios_cargados', 0)} "
                f"asignacion={result.get('predios_asignacion', 0)} "
                f"soporte_extra={predios_soporte_extra}."
            ),
            created_by,
        )
        return dataset_sql

    datasetname_main = (asignacion.get("datasetname_main") or datasetname_main_default or "").strip()
    if not datasetname_main:
        raise export_service.ExportServiceError(
            status_code=400,
            detail="La asignacion no tiene dataset origen para reconstruir workspace.",
        )

    with tempfile.TemporaryDirectory() as td:
        xtf_path = os.path.join(td, f"workspace_on_demand_{asignacion_id}.xtf")
        checkout_mode = "dataset"
        try:
            checkout_mode = export_service.ili2pg_export_assignment(
                conn,
                tenant,
                schema=schema_main,
                asignacion_id=asignacion_id,
                datasetname=datasetname_main,
                xtf_path=xtf_path,
                required_topics=required_topics,
                apply_dataset_sanitizers=False,
                ili2pg_cmd=ili2pg_cmd,
                timeout_sec=timeout_sec,
            )
        except export_service.ExportServiceError as exc:
            detail = (exc.detail or "").lower() if isinstance(exc.detail, str) else ""
            if "no tiene baskets" not in detail:
                raise
            export_service.ili2pg_export_by_dataset(
                tenant,
                schema_main,
                datasetname_main,
                xtf_path,
                ili2pg_cmd=ili2pg_cmd,
                timeout_sec=timeout_sec,
            )
            checkout_mode = "dataset_fallback_empty_assignment"

        if workspace_ctx.model_name == "arb":
            _arb_disable_workspace_unique_constraints(conn, tenant, schema_work)

        _ensure_workspace_enum_tables_populated(conn, tenant, schema_main, schema_work)
        try:
            export_service.ili2pg_import(
                conn,
                tenant,
                schema_work,
                work_dataset,
                xtf_path,
                ili2pg_cmd=ili2pg_cmd,
                timeout_sec=timeout_sec,
            )
        except export_service.ExportServiceError:
            if not workspace_dataset_exists(conn, tenant, work_dataset):
                raise

    removed_predios = prune_workspace_predios(conn, tenant, asignacion_id, work_dataset, schema_work)
    actualizar_predio_ids_desde_workspace(conn, tenant, asignacion_id)
    conn.commit()

    final_predios = workspace_dataset_assignment_predio_count(
        conn,
        tenant,
        work_dataset,
        asignacion_id,
    )
    if final_predios < expected_predios:
        safe_log_event(
            asignacion_id,
            "WORKSPACE_ON_DEMAND_INCOMPLETO",
            (
                f"Workspace {work_dataset} incompleto para exportacion: "
                f"{final_predios}/{expected_predios} predios activos."
            ),
            created_by,
        )
        raise export_service.ExportServiceError(
            status_code=409,
            detail=(
                f"Workspace incompleto para exportar: {final_predios}/{expected_predios} "
                f"predios activos en {schema_work}:{work_dataset}."
            ),
        )

    update_asignacion_fields(
        asignacion_id,
        estado="EN_CAMPO" if workspace_ctx.model_name == "arb" else "EN_TRABAJO",
        error_msg=None,
    )
    safe_log_event(
        asignacion_id,
        "WORKSPACE_ON_DEMAND",
        (
            f"Workspace {work_dataset} creado bajo demanda para exportacion. "
            f"Modo checkout: {checkout_mode}. "
            f"Removidos {removed_predios} no asignados."
        ),
        created_by,
    )
    return work_dataset

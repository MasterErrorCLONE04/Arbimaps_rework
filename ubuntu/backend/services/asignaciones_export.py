import os
import shlex
import subprocess
import shutil
import time
import traceback
import uuid
import glob
from typing import List, Optional

from core.asignaciones import ASIG_MODEL_CONTEXT, ILI2PG_TIMEOUT_SEC
from core.db import db_conn, get_db_params


class ExportServiceError(Exception):
    def __init__(self, detail: str, status_code: int = 500):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _safe_int_env(name: str, default: int, minimum: int = 0) -> int:
    raw = (os.getenv(name, "") or "").strip()
    try:
        value = int(raw) if raw else default
    except Exception:
        value = default
    return value if value >= minimum else default


def _qualify(schema: str, table: str) -> str:
    schema = (schema or "").strip().strip('"')
    if not schema:
        return table
    return f"{schema}.{table}"


def _resolve_assignment_predio_source(schema: str) -> tuple[str, str]:
    return ASIG_MODEL_CONTEXT.predio_table, ASIG_MODEL_CONTEXT.predio_numero_field


def _resolve_assignment_export_model(schema: str) -> str:
    return ASIG_MODEL_CONTEXT.name


def _resolve_ili2pg_cmd(ili2pg_cmd: str) -> str:
    cmd_text = (ili2pg_cmd or "").strip()
    if cmd_text:
        return cmd_text

    env_cmd = (os.getenv("ILI2PG_CMD", "") or "").strip()
    if env_cmd:
        return env_cmd

    java_bin = (os.getenv("JAVA_BIN", "") or "").strip() or "/usr/bin/java"
    java_exists = shutil.which(java_bin) is not None or os.path.exists(java_bin)
    if not java_exists:
        return ""

    jar_candidates: list[str] = []
    env_jar = (os.getenv("ILI2PG_JAR", "") or "").strip()
    if env_jar:
        jar_candidates.append(env_jar)
    jar_candidates.extend(
        [
            "/opt/ili2pg/ili2pg-5.1.0.jar",
            "/opt/ili2pg/ili2pg.jar",
        ]
    )
    jar_candidates.extend(sorted(glob.glob("/opt/ili2pg/ili2pg-*.jar"), reverse=True))

    seen = set()
    for jar_path in jar_candidates:
        if not jar_path or jar_path in seen:
            continue
        seen.add(jar_path)
        if os.path.exists(jar_path):
            return f"{java_bin} -jar {jar_path}"

    return ""


def _ensure_ili2pg_runtime_available(ili2pg_cmd: str) -> None:
    cmd_text = (ili2pg_cmd or "").strip()
    if cmd_text:
        parts = shlex.split(cmd_text)
        if not parts:
            raise ExportServiceError(
                status_code=500,
                detail="ILI2PG_CMD está vacío. Define un comando válido para ejecutar ili2pg.",
            )
        binary = parts[0]
        if shutil.which(binary) is None and not os.path.exists(binary):
            raise ExportServiceError(
                status_code=500,
                detail=f"ILI2PG_CMD inválido: no existe el ejecutable base '{binary}'.",
            )
        if "-jar" in parts:
            jar_index = parts.index("-jar") + 1
            if jar_index >= len(parts):
                raise ExportServiceError(
                    status_code=500,
                    detail="ILI2PG_CMD inválido: falta la ruta del .jar después de '-jar'.",
                )
            jar_path = parts[jar_index]
            if not os.path.exists(jar_path):
                raise ExportServiceError(
                    status_code=500,
                    detail=f"ILI2PG_CMD inválido: no existe el jar '{jar_path}'.",
                )
        return

    if shutil.which("ili2pg") is None:
        raise ExportServiceError(
            status_code=500,
            detail=(
                "No se encontró el ejecutable 'ili2pg'. "
                "Configura ILI2PG_CMD o instala ili2pg en el PATH del servicio."
            ),
        )


def _tail_lines(text: str, *, max_lines: int = 120) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    lines = raw.splitlines()
    if len(lines) <= max_lines:
        return raw
    head_n = max(20, max_lines // 3)
    tail_n = max(20, max_lines // 2)
    if head_n + tail_n > max_lines:
        tail_n = max_lines - head_n

    head = lines[:head_n]
    tail = lines[-tail_n:]

    # Keep key diagnostic lines from the omitted middle block so root causes
    # are visible even when stderr is long.
    middle = lines[head_n:-tail_n] if tail_n > 0 else lines[head_n:]
    key_tokens = ("error", "exception", "failed", "failure", "invalid", "violation", "fatal")
    key_lines: list[str] = []
    for ln in middle:
        low = ln.lower()
        if any(tok in low for tok in key_tokens):
            key_lines.append(ln)
        if len(key_lines) >= 12:
            break

    omitted = len(lines) - (len(head) + len(tail))
    parts = ["\n".join(head)]
    parts.append(f"[... {omitted} linea(s) omitida(s) ...]")
    if key_lines:
        parts.append("[lineas clave]")
        parts.extend(key_lines)
    parts.append("\n".join(tail))
    return "\n".join(part for part in parts if part)


def _extract_error_highlights(text: str, *, max_lines: int = 12) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    tokens = (
        "error",
        "exception",
        "failed",
        "failure",
        "fatal",
        "not found",
        "invalid",
        "violation",
        "severe",
        "traceback",
        "ili2dbexception",
    )
    highlights: list[str] = []
    for ln in raw.splitlines():
        low = ln.lower()
        if any(tok in low for tok in tokens):
            highlights.append(ln.strip())
        if len(highlights) >= max_lines:
            break
    return "\n".join(highlights)


def _build_ili2pg_env() -> dict:
    env = os.environ.copy()
    extra_opts = (os.getenv("ILI2PG_JAVA_TOOL_OPTIONS", "") or "").strip()
    xmx_mb = (os.getenv("ILI2PG_JAVA_XMX_MB", "") or "").strip()
    if xmx_mb.isdigit() and int(xmx_mb) > 0:
        xmx_opt = f"-Xmx{xmx_mb}m"
        if xmx_opt not in extra_opts:
            extra_opts = f"{extra_opts} {xmx_opt}".strip()
    if not extra_opts:
        return env

    current_opts = (env.get("JAVA_TOOL_OPTIONS", "") or "").strip()
    if current_opts:
        env["JAVA_TOOL_OPTIONS"] = f"{current_opts} {extra_opts}".strip()
    else:
        env["JAVA_TOOL_OPTIONS"] = extra_opts
    return env



def _row_get(row, idx: int, default=None):
    try:
        if row is None:
            return default
        if isinstance(row, (list, tuple)):
            return row[idx] if 0 <= idx < len(row) else default
        return row[idx]
    except Exception:
        return default


def _stage_error_detail(stage: str, exc: Exception) -> str:
    location = ""
    try:
        tb = traceback.extract_tb(exc.__traceback__)
        if tb:
            frame = tb[-1]
            location = f"{os.path.basename(frame.filename)}:{frame.lineno}"
    except Exception:
        location = ""

    if location:
        return f"[{stage}] {exc.__class__.__name__} en {location}: {exc}"
    return f"[{stage}] {exc.__class__.__name__}: {exc}"


def _run_stage(stage: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ExportServiceError:
        raise
    except Exception as exc:
        raise ExportServiceError(status_code=500, detail=_stage_error_detail(stage, exc)) from exc


def _resolve_model_dir() -> Optional[str]:
    # El directorio de modelos está en backend/resource/model
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base_dir, "resource", "model")
    if os.path.exists(path):
        return path
    return None


def run_ili2pg(args: list[str], *, ili2pg_cmd: str = "", timeout_sec: int = ILI2PG_TIMEOUT_SEC) -> None:
    cmd_text = _resolve_ili2pg_cmd(ili2pg_cmd)
    _ensure_ili2pg_runtime_available(cmd_text)
    if cmd_text:
        base = shlex.split(cmd_text)
        if args:
            args = base + args[1:]
        else:
            args = base
    try:
        subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout_sec,
            env=_build_ili2pg_env(),
        )
    except subprocess.TimeoutExpired:
        raise ExportServiceError(
            status_code=500,
            detail=f"ili2pg superó el tiempo límite de {timeout_sec} segundos.",
        )
    except FileNotFoundError:
        raise ExportServiceError(
            status_code=500,
            detail=(
                "No se encontró el ejecutable 'ili2pg'. "
                "Configura la variable de entorno ILI2PG_CMD con la ruta correcta "
                "o añade ili2pg al PATH del servicio."
            ),
        )
    except subprocess.CalledProcessError as e:
        stderr = _tail_lines(e.stderr or "", max_lines=120)
        stdout = _tail_lines(e.stdout or "", max_lines=80)
        summary = _extract_error_highlights((e.stderr or "") + "\n" + (e.stdout or ""))
        detail = f"ili2pg falló (exit={e.returncode})."
        if summary:
            detail += f" Causa probable:\n{summary}"
        if stderr:
            detail += f" STDERR: {stderr}"
        if stdout:
            detail += f" STDOUT: {stdout}"
        raise ExportServiceError(status_code=500, detail=detail)


def db_env():
    params = get_db_params()
    return {
        "host": str(params.get("host", "")),
        "port": str(params.get("port", "5432")),
        "dbname": str(params.get("dbname", "")),
        "user": str(params.get("user", "")),
        "password": str(params.get("password", "")),
    }


def _fetch_dataset_basket_ids(schema: str, datasetname: str) -> List[int]:
    basket_table = _qualify(schema, "t_ili2db_basket")
    dataset_table = _qualify(schema, "t_ili2db_dataset")
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT b.t_id
                FROM {basket_table} b
                JOIN {dataset_table} d ON d.t_id = b.dataset
                WHERE d.datasetname = %s
                ORDER BY b.t_id
                """,
                (datasetname,),
            )
            return [int(row[0]) for row in (cur.fetchall() or []) if row and row[0] is not None]


def _ensure_dataset_object_tili_tids(schema: str, datasetname: str) -> None:
    if not datasetname:
        return

    basket_table = _qualify(schema, "t_ili2db_basket")
    dataset_table = _qualify(schema, "t_ili2db_dataset")

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.table_name, c.data_type
                FROM information_schema.columns c
                WHERE c.table_schema = %s
                  AND c.column_name = 't_ili_tid'
                  AND EXISTS (
                    SELECT 1
                    FROM information_schema.columns cb
                    WHERE cb.table_schema = c.table_schema
                      AND cb.table_name = c.table_name
                      AND cb.column_name = 't_basket'
                  )
                ORDER BY c.table_name
                """,
                (schema,),
            )
            rows = cur.fetchall() or []

            for table_name, data_type in rows:
                target = _qualify(schema, str(table_name))
                if str(data_type).lower() == "uuid":
                    cur.execute(
                        f"""
                        UPDATE {target} t
                        SET t_ili_tid = (md5(CONCAT(%s, '_', %s, '_', t.t_id::text)))::uuid
                        FROM {basket_table} b
                        JOIN {dataset_table} d ON d.t_id = b.dataset
                        WHERE t.t_basket = b.t_id
                          AND d.datasetname = %s
                          AND t.t_ili_tid IS NULL
                        """,
                        (datasetname, table_name, datasetname),
                    )
                else:
                    cur.execute(
                        f"""
                        UPDATE {target} t
                        SET t_ili_tid = CONCAT(%s, '_', %s, '_', t.t_id)
                        FROM {basket_table} b
                        JOIN {dataset_table} d ON d.t_id = b.dataset
                        WHERE t.t_basket = b.t_id
                          AND d.datasetname = %s
                          AND (t.t_ili_tid IS NULL OR NULLIF(TRIM(t.t_ili_tid::text), '') IS NULL)
                        """,
                        (datasetname, table_name, datasetname),
                    )
        conn.commit()


def _validate_dataset_cuc_integrity(schema: str, datasetname: str) -> None:
    if not datasetname:
        return

    basket_table = _qualify(schema, "t_ili2db_basket")
    dataset_table = _qualify(schema, "t_ili2db_dataset")
    cuc_tables = [
        "cuc_calificacionconvencional",
        "cuc_tipologiaconstruccion",
        "cuc_tipologianoconvencional",
        "cuc_calificacion_unidadconstruccion",
    ]

    with db_conn() as conn:
        with conn.cursor() as cur:
            for table_name in cuc_tables:
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = %s
                      AND table_name = %s
                      AND column_name = 't_ili_tid'
                    LIMIT 1
                    """,
                    (schema, table_name),
                )
                if cur.fetchone() is None:
                    continue

                target = _qualify(schema, table_name)
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (
                            WHERE NULLIF(TRIM(c.t_ili_tid::text), '') IS NULL
                        ) AS oid_vacio
                    FROM {target} c
                    JOIN {basket_table} b ON b.t_id = c.t_basket
                    JOIN {dataset_table} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                    """,
                    (datasetname,),
                )
                row = cur.fetchone() or (0, 0)
                total = int(_row_get(row, 0, 0) or 0)
                oid_vacio = int(_row_get(row, 1, 0) or 0)
                if total > 0 and oid_vacio > 0:
                    raise ExportServiceError(
                        status_code=409,
                        detail=(
                            f"Dataset '{datasetname}' invalido para exportar: "
                            f"{table_name}.t_ili_tid vacio en {oid_vacio}/{total} filas."
                        ),
                    )

            cur.execute(
                """
                SELECT kcu.column_name, ccu.table_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = %s
                  AND tc.table_name = 'cuc_calificacion_unidadconstruccion'
                  AND ccu.column_name = 't_id'
                  AND (
                    kcu.column_name LIKE '%%tipologia%%'
                    OR kcu.column_name LIKE '%%calificacionconvencional%%'
                    OR kcu.column_name LIKE '%%caracteristicasunidadconstruccion%%'
                  )
                ORDER BY kcu.column_name
                """,
                (schema,),
            )
            fk_rows = cur.fetchall() or []

            for fk_col, parent_table in fk_rows:
                parent_qual = _qualify(schema, str(parent_table))
                fk_col_sql = str(fk_col).replace('"', '""')
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = %s
                      AND table_name = %s
                      AND column_name = 't_basket'
                    LIMIT 1
                    """,
                    (schema, parent_table),
                )
                if cur.fetchone() is None:
                    continue

                cur.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM { _qualify(schema, 'cuc_calificacion_unidadconstruccion') } c
                    JOIN {basket_table} cb ON cb.t_id = c.t_basket
                    JOIN {dataset_table} cd ON cd.t_id = cb.dataset
                    LEFT JOIN (
                        SELECT p.t_id
                        FROM {parent_qual} p
                        JOIN {basket_table} pb ON pb.t_id = p.t_basket
                        JOIN {dataset_table} pd ON pd.t_id = pb.dataset
                        WHERE pd.datasetname = %s
                    ) p ON p.t_id = c."{fk_col_sql}"
                    WHERE cd.datasetname = %s
                      AND c."{fk_col_sql}" IS NOT NULL
                      AND p.t_id IS NULL
                    """,
                    (datasetname, datasetname),
                )
                missing = int((cur.fetchone() or [0])[0] or 0)
                if missing > 0:
                    raise ExportServiceError(
                        status_code=409,
                        detail=(
                            f"Dataset '{datasetname}' invalido para exportar: "
                            f"{missing} referencia(s) huerfana(s) en "
                            f"cuc_calificacion_unidadconstruccion.{fk_col} "
                            f"-> {parent_table}.t_id."
                        ),
                    )


def _sanitize_dataset_derecho_links(schema: str, datasetname: str) -> None:
    if not datasetname:
        return

    required = {
        "ilc_derecho",
        "col_rrrfuente",
        "col_rrrinteresado",
        "t_ili2db_basket",
        "t_ili2db_dataset",
    }
    optional = {
        "ilc_interesado",
        "cr_agrupacioninteresados",
    }
    tracked_tables = sorted(required | optional)
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '3s'")
            cur.execute("SET LOCAL statement_timeout = '180s'")
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = ANY(%s)
                """,
                (schema, tracked_tables),
            )
            available = {str(r[0]) for r in (cur.fetchall() or []) if r and r[0]}
            if not required.issubset(available):
                return

            derecho = _qualify(schema, "ilc_derecho")
            rrr_fuente = _qualify(schema, "col_rrrfuente")
            rrr_inter = _qualify(schema, "col_rrrinteresado")
            basket = _qualify(schema, "t_ili2db_basket")
            dataset = _qualify(schema, "t_ili2db_dataset")

            # Remove orphan RRR rows first.
            cur.execute(
                f"""
                DELETE FROM {rrr_fuente} rf
                USING {basket} b, {dataset} d
                WHERE rf.t_basket = b.t_id
                  AND b.dataset = d.t_id
                  AND d.datasetname = %s
                  AND NOT EXISTS (
                    SELECT 1
                    FROM {derecho} dr
                    JOIN {basket} db ON db.t_id = dr.t_basket
                    JOIN {dataset} dd ON dd.t_id = db.dataset
                    WHERE dd.datasetname = %s
                      AND dr.t_id = rf.rrr
                  )
                """,
                (datasetname, datasetname),
            )

            cur.execute(
                f"""
                DELETE FROM {rrr_inter} ri
                USING {basket} b, {dataset} d
                WHERE ri.t_basket = b.t_id
                  AND b.dataset = d.t_id
                  AND d.datasetname = %s
                  AND NOT EXISTS (
                    SELECT 1
                    FROM {derecho} dr
                    JOIN {basket} db ON db.t_id = dr.t_basket
                    JOIN {dataset} dd ON dd.t_id = db.dataset
                    WHERE dd.datasetname = %s
                      AND dr.t_id = ri.rrr
                  )
                """,
                (datasetname, datasetname),
            )

            # Keep ilc_derecho rows untouched here.
            # Multiplicity is validated later with explicit 409 errors, to avoid
            # masking copy issues by deleting derechos and leaving predios with 0 rrr.
            # Importante: no borrar relaciones ri por referencias de interesado fuera
            # del dataset. Esas referencias se deben rehidratar/remapear, no eliminar.
            # Borrar aqui termina dejando ILC_Derecho sin interesado/fuente.

            # No destructive pruning here. Rehydration must repair links without
            # deleting core assignment entities.
        conn.commit()


def _rehydrate_dataset_derecho_links_from_source(
    schema: str,
    datasetname: str,
    *,
    source_schema: str = "",
) -> None:
    if not datasetname:
        return
    if (schema or "").strip().lower() != (ASIG_MODEL_CONTEXT.schema_work or "").strip().lower():
        return

    source_schema = (source_schema or ASIG_MODEL_CONTEXT.schema_main).strip().strip('"')
    if not source_schema:
        return

    required_target = {
        "ilc_derecho",
        "col_rrrinteresado",
        "col_rrrfuente",
        "ilc_interesado",
        "cr_agrupacioninteresados",
        "ilc_fuenteadministrativa",
        "t_ili2db_basket",
        "t_ili2db_dataset",
    }
    required_source = {
        "ilc_derecho",
        "col_rrrinteresado",
        "col_rrrfuente",
        "ilc_interesado",
        "cr_agrupacioninteresados",
        "ilc_fuenteadministrativa",
        "t_ili2db_basket",
    }

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '3s'")
            cur.execute("SET LOCAL statement_timeout = '600s'")
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = ANY(%s)
                """,
                (schema, list(required_target)),
            )
            target_available = {str(r[0]) for r in (cur.fetchall() or []) if r and r[0]}
            if not required_target.issubset(target_available):
                return

            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = ANY(%s)
                """,
                (source_schema, list(required_source)),
            )
            source_available = {str(r[0]) for r in (cur.fetchall() or []) if r and r[0]}
            if not required_source.issubset(source_available):
                return

            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = %s
                      AND table_name = 'col_miembros'
                )
                """,
                (source_schema,),
            )
            has_members_source = bool((cur.fetchone() or [False])[0])

            t_basket = _qualify(schema, "t_ili2db_basket")
            t_dataset = _qualify(schema, "t_ili2db_dataset")
            t_derecho = _qualify(schema, "ilc_derecho")
            t_rrri = _qualify(schema, "col_rrrinteresado")
            t_rrrf = _qualify(schema, "col_rrrfuente")
            t_inter = _qualify(schema, "ilc_interesado")
            t_agrup = _qualify(schema, "cr_agrupacioninteresados")
            t_fuente = _qualify(schema, "ilc_fuenteadministrativa")

            s_basket = _qualify(source_schema, "t_ili2db_basket")
            s_derecho = _qualify(source_schema, "ilc_derecho")
            s_rrri = _qualify(source_schema, "col_rrrinteresado")
            s_rrrf = _qualify(source_schema, "col_rrrfuente")
            s_inter = _qualify(source_schema, "ilc_interesado")
            s_agrup = _qualify(source_schema, "cr_agrupacioninteresados")
            s_fuente = _qualify(source_schema, "ilc_fuenteadministrativa")
            s_miembros = _qualify(source_schema, "col_miembros")

            # Do not auto-create/rebuild baskets on export.
            # Validate that required topics already exist in the assignment dataset.
            cur.execute(
                f"""
                WITH ds_derechos AS (
                    SELECT
                        COALESCE(sd.t_id, dr.t_id) AS source_id,
                        dr.t_id AS target_id
                    FROM {t_derecho} dr
                    JOIN {t_basket} b ON b.t_id = dr.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    LEFT JOIN {s_derecho} sd
                      ON dr.t_ili_tid IS NOT NULL
                     AND sd.t_ili_tid = dr.t_ili_tid
                    WHERE d.datasetname = %s
                ),
                src_baskets AS (
                    SELECT ri.t_basket AS source_basket
                    FROM {s_rrri} ri
                    JOIN ds_derechos dd ON dd.source_id = ri.rrr
                    UNION
                    SELECT rf.t_basket AS source_basket
                    FROM {s_rrrf} rf
                    JOIN ds_derechos dd ON dd.source_id = rf.rrr
                    UNION
                    SELECT i.t_basket AS source_basket
                    FROM {s_rrri} ri
                    JOIN ds_derechos dd ON dd.source_id = ri.rrr
                    JOIN {s_inter} i ON i.t_id = ri.interesado_ilc_interesado
                    WHERE ri.interesado_ilc_interesado IS NOT NULL
                    UNION
                    SELECT a.t_basket AS source_basket
                    FROM {s_rrri} ri
                    JOIN ds_derechos dd ON dd.source_id = ri.rrr
                    JOIN {s_agrup} a ON a.t_id = ri.interesado_cr_agrupacioninteresados
                    WHERE ri.interesado_cr_agrupacioninteresados IS NOT NULL
                    UNION
                    SELECT fa.t_basket AS source_basket
                    FROM {s_rrrf} rf
                    JOIN ds_derechos dd ON dd.source_id = rf.rrr
                    JOIN {s_fuente} fa ON fa.t_id = rf.fuente_administrativa
                    WHERE rf.fuente_administrativa IS NOT NULL
                ),
                topics AS (
                    SELECT DISTINCT sb.topic
                    FROM src_baskets x
                    JOIN {s_basket} sb ON sb.t_id = x.source_basket
                ),
                missing AS (
                    SELECT t.topic
                    FROM topics t
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM {t_basket} tb
                        JOIN {t_dataset} td ON td.t_id = tb.dataset
                        WHERE tb.topic = t.topic
                          AND td.datasetname = %s
                    )
                )
                SELECT
                    COALESCE(array_agg(m.topic ORDER BY m.topic), ARRAY[]::text[]) AS missing_topics,
                    COUNT(*)::int AS missing_count
                FROM missing m
                """,
                (datasetname, datasetname),
            )
            row = cur.fetchone() or ([], 0)
            missing_topics = list(row[0] or [])
            missing_count = int(row[1] or 0)
            if missing_count > 0:
                sample = ", ".join(missing_topics[:10])
                raise ExportServiceError(
                    status_code=409,
                    detail=(
                        f"Dataset '{datasetname}' invalido para exportar: faltan {missing_count} "
                        f"topic(s) de basket requeridos por relaciones RRR. "
                        f"Muestra topics: {sample if sample else 'sin muestra'}."
                    ),
                )

            # 1) Build source->target id maps to avoid cross-dataset t_id collisions.
            cur.execute("DROP TABLE IF EXISTS _rehyd_map_inter")
            cur.execute("DROP TABLE IF EXISTS _rehyd_map_agrup")
            cur.execute("DROP TABLE IF EXISTS _rehyd_map_fuente")
            cur.execute("DROP TABLE IF EXISTS _rehyd_map_rrri")
            cur.execute("DROP TABLE IF EXISTS _rehyd_map_rrrf")
            cur.execute(
                "CREATE TEMP TABLE _rehyd_map_inter(source_id bigint PRIMARY KEY, target_id bigint NOT NULL)"
            )
            cur.execute(
                "CREATE TEMP TABLE _rehyd_map_agrup(source_id bigint PRIMARY KEY, target_id bigint NOT NULL)"
            )
            cur.execute(
                "CREATE TEMP TABLE _rehyd_map_fuente(source_id bigint PRIMARY KEY, target_id bigint NOT NULL)"
            )
            cur.execute(
                "CREATE TEMP TABLE _rehyd_map_rrri(source_id bigint PRIMARY KEY, target_id bigint NOT NULL)"
            )
            cur.execute(
                "CREATE TEMP TABLE _rehyd_map_rrrf(source_id bigint PRIMARY KEY, target_id bigint NOT NULL)"
            )

            # Seed agrupacion map with every group already present in dataset.
            # This allows member rehydration even when a group was copied outside
            # the derecho->rrr traversal.
            cur.execute(
                f"""
                WITH ds_agrup AS (
                    SELECT a.t_id AS target_id, NULLIF(BTRIM(a.t_ili_tid::text), '') AS target_tid
                    FROM {t_agrup} a
                    JOIN {t_basket} b ON b.t_id = a.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                )
                INSERT INTO _rehyd_map_agrup(source_id, target_id)
                SELECT COALESCE(sa.t_id, ds.target_id) AS source_id, ds.target_id
                FROM ds_agrup ds
                LEFT JOIN {s_agrup} sa
                  ON ds.target_tid IS NOT NULL
                 AND NULLIF(BTRIM(sa.t_ili_tid::text), '') = ds.target_tid
                ON CONFLICT (source_id) DO UPDATE
                SET target_id = EXCLUDED.target_id
                """,
                (datasetname,),
            )

            # Parent map: ilc_interesado
            cur.execute(
                f"""
                WITH ds_derechos AS (
                    SELECT
                        COALESCE(sd.t_id, dr.t_id) AS source_id,
                        dr.t_id AS target_id
                    FROM {t_derecho} dr
                    JOIN {t_basket} b ON b.t_id = dr.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    LEFT JOIN {s_derecho} sd
                      ON dr.t_ili_tid IS NOT NULL
                     AND sd.t_ili_tid = dr.t_ili_tid
                    WHERE d.datasetname = %s
                ),
                src_ids AS (
                    SELECT DISTINCT ri.interesado_ilc_interesado AS source_id
                    FROM {s_rrri} ri
                    JOIN ds_derechos dd ON dd.source_id = ri.rrr
                    WHERE ri.interesado_ilc_interesado IS NOT NULL
                ),
                in_ds AS (
                    SELECT i.t_id AS source_id
                    FROM {t_inter} i
                    JOIN {t_basket} b ON b.t_id = i.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                need_clone AS (
                    SELECT s.source_id
                    FROM src_ids s
                    LEFT JOIN in_ds d ON d.source_id = s.source_id
                    WHERE d.source_id IS NULL
                ),
                base AS (
                    SELECT COALESCE(MAX(t_id), 0) AS mx
                    FROM {t_inter}
                ),
                clone_ids AS (
                    SELECT n.source_id, base.mx + ROW_NUMBER() OVER (ORDER BY n.source_id) AS target_id
                    FROM need_clone n, base
                ),
                direct_ids AS (
                    SELECT s.source_id, s.source_id AS target_id
                    FROM src_ids s
                    LEFT JOIN need_clone n ON n.source_id = s.source_id
                    WHERE n.source_id IS NULL
                )
                INSERT INTO _rehyd_map_inter(source_id, target_id)
                SELECT source_id, target_id FROM direct_ids
                UNION ALL
                SELECT source_id, target_id FROM clone_ids
                ON CONFLICT (source_id) DO UPDATE SET target_id = EXCLUDED.target_id
                """,
                (datasetname, datasetname),
            )

            # Parent map: cr_agrupacioninteresados
            cur.execute(
                f"""
                WITH ds_derechos AS (
                    SELECT
                        COALESCE(sd.t_id, dr.t_id) AS source_id,
                        dr.t_id AS target_id
                    FROM {t_derecho} dr
                    JOIN {t_basket} b ON b.t_id = dr.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    LEFT JOIN {s_derecho} sd
                      ON dr.t_ili_tid IS NOT NULL
                     AND sd.t_ili_tid = dr.t_ili_tid
                    WHERE d.datasetname = %s
                ),
                src_ids AS (
                    SELECT DISTINCT ri.interesado_cr_agrupacioninteresados AS source_id
                    FROM {s_rrri} ri
                    JOIN ds_derechos dd ON dd.source_id = ri.rrr
                    WHERE ri.interesado_cr_agrupacioninteresados IS NOT NULL
                ),
                in_ds AS (
                    SELECT a.t_id AS source_id
                    FROM {t_agrup} a
                    JOIN {t_basket} b ON b.t_id = a.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                need_clone AS (
                    SELECT s.source_id
                    FROM src_ids s
                    LEFT JOIN in_ds d ON d.source_id = s.source_id
                    WHERE d.source_id IS NULL
                ),
                base AS (
                    SELECT COALESCE(MAX(t_id), 0) AS mx
                    FROM {t_agrup}
                ),
                clone_ids AS (
                    SELECT n.source_id, base.mx + ROW_NUMBER() OVER (ORDER BY n.source_id) AS target_id
                    FROM need_clone n, base
                ),
                direct_ids AS (
                    SELECT s.source_id, s.source_id AS target_id
                    FROM src_ids s
                    LEFT JOIN need_clone n ON n.source_id = s.source_id
                    WHERE n.source_id IS NULL
                )
                INSERT INTO _rehyd_map_agrup(source_id, target_id)
                SELECT source_id, target_id FROM direct_ids
                UNION ALL
                SELECT source_id, target_id FROM clone_ids
                ON CONFLICT (source_id) DO UPDATE SET target_id = EXCLUDED.target_id
                """,
                (datasetname, datasetname),
            )

            # Parent map: ilc_fuenteadministrativa
            cur.execute(
                f"""
                WITH ds_derechos AS (
                    SELECT
                        COALESCE(sd.t_id, dr.t_id) AS source_id,
                        dr.t_id AS target_id
                    FROM {t_derecho} dr
                    JOIN {t_basket} b ON b.t_id = dr.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    LEFT JOIN {s_derecho} sd
                      ON dr.t_ili_tid IS NOT NULL
                     AND sd.t_ili_tid = dr.t_ili_tid
                    WHERE d.datasetname = %s
                ),
                src_ids AS (
                    SELECT DISTINCT rf.fuente_administrativa AS source_id
                    FROM {s_rrrf} rf
                    JOIN ds_derechos dd ON dd.source_id = rf.rrr
                    WHERE rf.fuente_administrativa IS NOT NULL
                ),
                in_ds AS (
                    SELECT f.t_id AS source_id
                    FROM {t_fuente} f
                    JOIN {t_basket} b ON b.t_id = f.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                need_clone AS (
                    SELECT s.source_id
                    FROM src_ids s
                    LEFT JOIN in_ds d ON d.source_id = s.source_id
                    WHERE d.source_id IS NULL
                ),
                base AS (
                    SELECT COALESCE(MAX(t_id), 0) AS mx
                    FROM {t_fuente}
                ),
                clone_ids AS (
                    SELECT n.source_id, base.mx + ROW_NUMBER() OVER (ORDER BY n.source_id) AS target_id
                    FROM need_clone n, base
                ),
                direct_ids AS (
                    SELECT s.source_id, s.source_id AS target_id
                    FROM src_ids s
                    LEFT JOIN need_clone n ON n.source_id = s.source_id
                    WHERE n.source_id IS NULL
                )
                INSERT INTO _rehyd_map_fuente(source_id, target_id)
                SELECT source_id, target_id FROM direct_ids
                UNION ALL
                SELECT source_id, target_id FROM clone_ids
                ON CONFLICT (source_id) DO UPDATE SET target_id = EXCLUDED.target_id
                """,
                (datasetname, datasetname),
            )

            # Link map: col_rrrinteresado
            cur.execute(
                f"""
                WITH ds_derechos AS (
                    SELECT
                        COALESCE(sd.t_id, dr.t_id) AS source_id,
                        dr.t_id AS target_id
                    FROM {t_derecho} dr
                    JOIN {t_basket} b ON b.t_id = dr.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    LEFT JOIN {s_derecho} sd
                      ON dr.t_ili_tid IS NOT NULL
                     AND sd.t_ili_tid = dr.t_ili_tid
                    WHERE d.datasetname = %s
                ),
                src_ids AS (
                    SELECT DISTINCT ri.t_id AS source_id
                    FROM {s_rrri} ri
                    JOIN ds_derechos dd ON dd.source_id = ri.rrr
                ),
                in_ds AS (
                    SELECT ri.t_id AS source_id
                    FROM {t_rrri} ri
                    JOIN {t_basket} b ON b.t_id = ri.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                need_clone AS (
                    SELECT s.source_id
                    FROM src_ids s
                    LEFT JOIN in_ds d ON d.source_id = s.source_id
                    WHERE d.source_id IS NULL
                ),
                base AS (
                    SELECT COALESCE(MAX(t_id), 0) AS mx
                    FROM {t_rrri}
                ),
                clone_ids AS (
                    SELECT n.source_id, base.mx + ROW_NUMBER() OVER (ORDER BY n.source_id) AS target_id
                    FROM need_clone n, base
                ),
                direct_ids AS (
                    SELECT s.source_id, s.source_id AS target_id
                    FROM src_ids s
                    LEFT JOIN need_clone n ON n.source_id = s.source_id
                    WHERE n.source_id IS NULL
                )
                INSERT INTO _rehyd_map_rrri(source_id, target_id)
                SELECT source_id, target_id FROM direct_ids
                UNION ALL
                SELECT source_id, target_id FROM clone_ids
                ON CONFLICT (source_id) DO UPDATE SET target_id = EXCLUDED.target_id
                """,
                (datasetname, datasetname),
            )

            # Link map: col_rrrfuente
            cur.execute(
                f"""
                WITH ds_derechos AS (
                    SELECT
                        COALESCE(sd.t_id, dr.t_id) AS source_id,
                        dr.t_id AS target_id
                    FROM {t_derecho} dr
                    JOIN {t_basket} b ON b.t_id = dr.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    LEFT JOIN {s_derecho} sd
                      ON dr.t_ili_tid IS NOT NULL
                     AND sd.t_ili_tid = dr.t_ili_tid
                    WHERE d.datasetname = %s
                ),
                src_ids AS (
                    SELECT DISTINCT rf.t_id AS source_id
                    FROM {s_rrrf} rf
                    JOIN ds_derechos dd ON dd.source_id = rf.rrr
                ),
                in_ds AS (
                    SELECT rf.t_id AS source_id
                    FROM {t_rrrf} rf
                    JOIN {t_basket} b ON b.t_id = rf.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                need_clone AS (
                    SELECT s.source_id
                    FROM src_ids s
                    LEFT JOIN in_ds d ON d.source_id = s.source_id
                    WHERE d.source_id IS NULL
                ),
                base AS (
                    SELECT COALESCE(MAX(t_id), 0) AS mx
                    FROM {t_rrrf}
                ),
                clone_ids AS (
                    SELECT n.source_id, base.mx + ROW_NUMBER() OVER (ORDER BY n.source_id) AS target_id
                    FROM need_clone n, base
                ),
                direct_ids AS (
                    SELECT s.source_id, s.source_id AS target_id
                    FROM src_ids s
                    LEFT JOIN need_clone n ON n.source_id = s.source_id
                    WHERE n.source_id IS NULL
                )
                INSERT INTO _rehyd_map_rrrf(source_id, target_id)
                SELECT source_id, target_id FROM direct_ids
                UNION ALL
                SELECT source_id, target_id FROM clone_ids
                ON CONFLICT (source_id) DO UPDATE SET target_id = EXCLUDED.target_id
                """,
                (datasetname, datasetname),
            )

            # 2) Parents referenced by RRR links (with mapped t_id).
            cur.execute(
                f"""
                WITH ds_derechos AS (
                    SELECT
                        COALESCE(sd.t_id, dr.t_id) AS source_id,
                        dr.t_id AS target_id
                    FROM {t_derecho} dr
                    JOIN {t_basket} b ON b.t_id = dr.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    LEFT JOIN {s_derecho} sd
                      ON dr.t_ili_tid IS NOT NULL
                     AND sd.t_ili_tid = dr.t_ili_tid
                    WHERE d.datasetname = %s
                ),
                src AS (
                    SELECT DISTINCT i.*
                    FROM {s_rrri} ri
                    JOIN ds_derechos dd ON dd.source_id = ri.rrr
                    JOIN {s_inter} i ON i.t_id = ri.interesado_ilc_interesado
                    WHERE ri.interesado_ilc_interesado IS NOT NULL
                )
                INSERT INTO {t_inter}
                SELECT (jsonb_populate_record(
                    NULL::{t_inter},
                    to_jsonb(s) || jsonb_build_object(
                        't_id', m.target_id,
                        't_basket', tb.t_id,
                        't_ili_tid', ((md5(CONCAT(
                            random()::text, clock_timestamp()::text, '_rehyd_inter_', m.target_id::text
                        )))::uuid)::text
                    )
                )).*
                FROM src s
                JOIN _rehyd_map_inter m ON m.source_id = s.t_id
                JOIN {s_basket} sb ON sb.t_id = s.t_basket
                JOIN {t_basket} tb ON tb.topic = sb.topic
                JOIN {t_dataset} td ON td.t_id = tb.dataset
                LEFT JOIN {t_inter} t ON t.t_id = m.target_id
                WHERE td.datasetname = %s
                  AND t.t_id IS NULL
                ON CONFLICT (documento_identidad) DO UPDATE
                SET t_basket = EXCLUDED.t_basket
                """,
                (datasetname, datasetname),
            )

            # Expand grouped-interesado map recursively so nested subgroup members
            # can be rehydrated as well (prevents parent groups ending with <2 members).
            cur.execute(
                f"""
                WITH RECURSIVE expanded(source_id) AS (
                    SELECT source_id
                    FROM _rehyd_map_agrup
                    UNION
                    SELECT DISTINCT m.interesado_cr_agrupacioninteresados
                    FROM {source_schema}.col_miembros m
                    JOIN expanded e ON e.source_id = m.agrupacion
                    WHERE m.interesado_cr_agrupacioninteresados IS NOT NULL
                ),
                src_ids AS (
                    SELECT DISTINCT source_id
                    FROM expanded
                    WHERE source_id IS NOT NULL
                ),
                missing_map AS (
                    SELECT s.source_id
                    FROM src_ids s
                    LEFT JOIN _rehyd_map_agrup m ON m.source_id = s.source_id
                    WHERE m.source_id IS NULL
                ),
                in_ds AS (
                    SELECT a.t_id AS source_id
                    FROM {t_agrup} a
                    JOIN {t_basket} b ON b.t_id = a.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                need_clone AS (
                    SELECT m.source_id
                    FROM missing_map m
                    LEFT JOIN in_ds d ON d.source_id = m.source_id
                    WHERE d.source_id IS NULL
                ),
                base AS (
                    SELECT GREATEST(
                        COALESCE((SELECT MAX(t_id) FROM {t_agrup}), 0),
                        COALESCE((SELECT MAX(target_id) FROM _rehyd_map_agrup), 0)
                    ) AS mx
                ),
                clone_ids AS (
                    SELECT n.source_id, base.mx + ROW_NUMBER() OVER (ORDER BY n.source_id) AS target_id
                    FROM need_clone n, base
                ),
                direct_ids AS (
                    SELECT m.source_id, m.source_id AS target_id
                    FROM missing_map m
                    LEFT JOIN need_clone n ON n.source_id = m.source_id
                    WHERE n.source_id IS NULL
                )
                INSERT INTO _rehyd_map_agrup(source_id, target_id)
                SELECT source_id, target_id FROM direct_ids
                UNION ALL
                SELECT source_id, target_id FROM clone_ids
                ON CONFLICT (source_id) DO UPDATE SET target_id = EXCLUDED.target_id
                """,
                (datasetname,),
            )

            # Expand ilc_interesado map from group members as well.
            # Some groups reference interesados only through col_miembros
            # (not directly via col_rrrinteresado).
            if has_members_source:
                cur.execute(
                    f"""
                    WITH src_ids AS (
                        SELECT DISTINCT m.interesado_ilc_interesado AS source_id
                        FROM {s_miembros} m
                        JOIN _rehyd_map_agrup ga ON ga.source_id = m.agrupacion
                        WHERE m.interesado_ilc_interesado IS NOT NULL
                    ),
                    missing_map AS (
                        SELECT s.source_id
                        FROM src_ids s
                        LEFT JOIN _rehyd_map_inter mi ON mi.source_id = s.source_id
                        WHERE mi.source_id IS NULL
                    ),
                    in_ds AS (
                        SELECT i.t_id AS source_id
                        FROM {t_inter} i
                        JOIN {t_basket} b ON b.t_id = i.t_basket
                        JOIN {t_dataset} d ON d.t_id = b.dataset
                        WHERE d.datasetname = %s
                    ),
                    need_clone AS (
                        SELECT m.source_id
                        FROM missing_map m
                        LEFT JOIN in_ds d ON d.source_id = m.source_id
                        WHERE d.source_id IS NULL
                    ),
                    base AS (
                        SELECT GREATEST(
                            COALESCE((SELECT MAX(t_id) FROM {t_inter}), 0),
                            COALESCE((SELECT MAX(target_id) FROM _rehyd_map_inter), 0)
                        ) AS mx
                    ),
                    clone_ids AS (
                        SELECT n.source_id, base.mx + ROW_NUMBER() OVER (ORDER BY n.source_id) AS target_id
                        FROM need_clone n, base
                    ),
                    direct_ids AS (
                        SELECT m.source_id, m.source_id AS target_id
                        FROM missing_map m
                        LEFT JOIN need_clone n ON n.source_id = m.source_id
                        WHERE n.source_id IS NULL
                    )
                    INSERT INTO _rehyd_map_inter(source_id, target_id)
                    SELECT source_id, target_id FROM direct_ids
                    UNION ALL
                    SELECT source_id, target_id FROM clone_ids
                    ON CONFLICT (source_id) DO UPDATE SET target_id = EXCLUDED.target_id
                    """,
                    (datasetname,),
                )

            # Ensure all mapped ilc_interesado rows exist in target dataset.
            cur.execute(
                f"""
                WITH src AS (
                    SELECT DISTINCT i.*
                    FROM {s_inter} i
                    JOIN _rehyd_map_inter m ON m.source_id = i.t_id
                )
                INSERT INTO {t_inter}
                SELECT (jsonb_populate_record(
                    NULL::{t_inter},
                    to_jsonb(s) || jsonb_build_object(
                        't_id', m.target_id,
                        't_basket', tb.t_id,
                        't_ili_tid', ((md5(CONCAT(
                            random()::text, clock_timestamp()::text, '_rehyd_inter_map_', m.target_id::text
                        )))::uuid)::text
                    )
                )).*
                FROM src s
                JOIN _rehyd_map_inter m ON m.source_id = s.t_id
                JOIN {s_basket} sb ON sb.t_id = s.t_basket
                JOIN {t_basket} tb ON tb.topic = sb.topic
                JOIN {t_dataset} td ON td.t_id = tb.dataset
                LEFT JOIN {t_inter} t ON t.t_id = m.target_id
                WHERE td.datasetname = %s
                  AND t.t_id IS NULL
                ON CONFLICT (documento_identidad) DO UPDATE
                SET t_basket = EXCLUDED.t_basket
                """,
                (datasetname,),
            )

            # Remap by documento_identidad to avoid dangling _rehyd_map_inter rows
            # when unique constraints skip inserts with existing identities.
            cur.execute(
                f"""
                WITH
                src AS (
                    SELECT DISTINCT
                        i.t_id AS source_id,
                        NULLIF(
                            UPPER(REGEXP_REPLACE(BTRIM(i.documento_identidad::text), '[^0-9A-Z]+', '', 'g')),
                            ''
                        ) AS doc_key
                    FROM {s_inter} i
                    JOIN _rehyd_map_inter m ON m.source_id = i.t_id
                ),
                matched AS (
                    SELECT
                        src.source_id,
                        MIN(t.t_id) AS target_id
                    FROM src
                    JOIN {t_inter} t
                      ON src.doc_key IS NOT NULL
                     AND NULLIF(
                           UPPER(REGEXP_REPLACE(BTRIM(t.documento_identidad::text), '[^0-9A-Z]+', '', 'g')),
                           ''
                         ) = src.doc_key
                    JOIN {t_basket} tb ON tb.t_id = t.t_basket
                    JOIN {t_dataset} td ON td.t_id = tb.dataset
                    WHERE td.datasetname = %s
                    GROUP BY src.source_id
                )
                UPDATE _rehyd_map_inter m
                SET target_id = mt.target_id
                FROM matched mt
                WHERE m.source_id = mt.source_id
                  AND m.target_id IS DISTINCT FROM mt.target_id
                """,
                (datasetname,),
            )

            cur.execute(
                f"""
                WITH ds_derechos AS (
                    SELECT
                        COALESCE(sd.t_id, dr.t_id) AS source_id,
                        dr.t_id AS target_id
                    FROM {t_derecho} dr
                    JOIN {t_basket} b ON b.t_id = dr.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    LEFT JOIN {s_derecho} sd
                      ON dr.t_ili_tid IS NOT NULL
                     AND sd.t_ili_tid = dr.t_ili_tid
                    WHERE d.datasetname = %s
                ),
                src AS (
                    SELECT DISTINCT a.*
                    FROM {s_rrri} ri
                    JOIN ds_derechos dd ON dd.source_id = ri.rrr
                    JOIN {s_agrup} a ON a.t_id = ri.interesado_cr_agrupacioninteresados
                    WHERE ri.interesado_cr_agrupacioninteresados IS NOT NULL
                )
                INSERT INTO {t_agrup}
                SELECT (jsonb_populate_record(
                    NULL::{t_agrup},
                    to_jsonb(s) || jsonb_build_object(
                        't_id', m.target_id,
                        't_basket', tb.t_id,
                        't_ili_tid', ((md5(CONCAT(
                            random()::text, clock_timestamp()::text, '_rehyd_agrup_', m.target_id::text
                        )))::uuid)::text
                    )
                )).*
                FROM src s
                JOIN _rehyd_map_agrup m ON m.source_id = s.t_id
                JOIN {s_basket} sb ON sb.t_id = s.t_basket
                JOIN {t_basket} tb ON tb.topic = sb.topic
                JOIN {t_dataset} td ON td.t_id = tb.dataset
                LEFT JOIN {t_agrup} t ON t.t_id = m.target_id
                WHERE td.datasetname = %s
                  AND t.t_id IS NULL
                ON CONFLICT (t_id) DO NOTHING
                """,
                (datasetname, datasetname),
            )

            cur.execute(
                f"""
                WITH ds_derechos AS (
                    SELECT
                        COALESCE(sd.t_id, dr.t_id) AS source_id,
                        dr.t_id AS target_id
                    FROM {t_derecho} dr
                    JOIN {t_basket} b ON b.t_id = dr.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    LEFT JOIN {s_derecho} sd
                      ON dr.t_ili_tid IS NOT NULL
                     AND sd.t_ili_tid = dr.t_ili_tid
                    WHERE d.datasetname = %s
                ),
                src AS (
                    SELECT DISTINCT fa.*
                    FROM {s_rrrf} rf
                    JOIN ds_derechos dd ON dd.source_id = rf.rrr
                    JOIN {s_fuente} fa ON fa.t_id = rf.fuente_administrativa
                    WHERE rf.fuente_administrativa IS NOT NULL
                )
                INSERT INTO {t_fuente}
                SELECT (jsonb_populate_record(
                    NULL::{t_fuente},
                    to_jsonb(s) || jsonb_build_object(
                        't_id', m.target_id,
                        't_basket', tb.t_id,
                        't_ili_tid', ((md5(CONCAT(
                            random()::text, clock_timestamp()::text, '_rehyd_fuente_', m.target_id::text
                        )))::uuid)::text
                    )
                )).*
                FROM src s
                JOIN _rehyd_map_fuente m ON m.source_id = s.t_id
                JOIN {s_basket} sb ON sb.t_id = s.t_basket
                JOIN {t_basket} tb ON tb.topic = sb.topic
                JOIN {t_dataset} td ON td.t_id = tb.dataset
                LEFT JOIN {t_fuente} t ON t.t_id = m.target_id
                WHERE td.datasetname = %s
                  AND t.t_id IS NULL
                ON CONFLICT (t_id) DO NOTHING
                """,
                (datasetname, datasetname),
            )

            # 3) Missing RRR links themselves (with mapped parent ids).
            cur.execute(
                f"""
                WITH ds_derechos AS (
                    SELECT
                        COALESCE(sd.t_id, dr.t_id) AS source_id,
                        dr.t_id AS target_id
                    FROM {t_derecho} dr
                    JOIN {t_basket} b ON b.t_id = dr.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    LEFT JOIN {s_derecho} sd
                      ON dr.t_ili_tid IS NOT NULL
                     AND sd.t_ili_tid = dr.t_ili_tid
                    WHERE d.datasetname = %s
                ),
                src AS (
                    SELECT
                        ri.*,
                        dd.target_id AS target_rrr
                    FROM {s_rrri} ri
                    JOIN ds_derechos dd ON dd.source_id = ri.rrr
                )
                INSERT INTO {t_rrri}
                SELECT (jsonb_populate_record(
                    NULL::{t_rrri},
                    to_jsonb(s) || jsonb_build_object(
                        't_id', mr.target_id,
                        't_basket', tb.t_id,
                        'rrr', s.target_rrr,
                        'interesado_ilc_interesado', CASE WHEN s.interesado_ilc_interesado IS NULL THEN NULL ELSE mi.target_id END,
                        'interesado_cr_agrupacioninteresados', CASE WHEN s.interesado_cr_agrupacioninteresados IS NULL THEN NULL ELSE ma.target_id END,
                        't_ili_tid', ((md5(CONCAT(
                            random()::text, clock_timestamp()::text, '_rehyd_rrri_', mr.target_id::text
                        )))::uuid)::text
                    )
                )).*
                FROM src s
                JOIN _rehyd_map_rrri mr ON mr.source_id = s.t_id
                LEFT JOIN _rehyd_map_inter mi ON mi.source_id = s.interesado_ilc_interesado
                LEFT JOIN _rehyd_map_agrup ma ON ma.source_id = s.interesado_cr_agrupacioninteresados
                JOIN {s_basket} sb ON sb.t_id = s.t_basket
                JOIN {t_basket} tb ON tb.topic = sb.topic
                JOIN {t_dataset} td ON td.t_id = tb.dataset
                WHERE td.datasetname = %s
                  AND (s.interesado_ilc_interesado IS NULL OR mi.target_id IS NOT NULL)
                  AND (s.interesado_cr_agrupacioninteresados IS NULL OR ma.target_id IS NOT NULL)
                ON CONFLICT (t_id) DO UPDATE
                SET
                    t_basket = EXCLUDED.t_basket,
                    rrr = EXCLUDED.rrr,
                    interesado_ilc_interesado = EXCLUDED.interesado_ilc_interesado,
                    interesado_cr_agrupacioninteresados = EXCLUDED.interesado_cr_agrupacioninteresados
                """,
                (datasetname, datasetname),
            )

            cur.execute(
                f"""
                WITH ds_derechos AS (
                    SELECT
                        COALESCE(sd.t_id, dr.t_id) AS source_id,
                        dr.t_id AS target_id
                    FROM {t_derecho} dr
                    JOIN {t_basket} b ON b.t_id = dr.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    LEFT JOIN {s_derecho} sd
                      ON dr.t_ili_tid IS NOT NULL
                     AND sd.t_ili_tid = dr.t_ili_tid
                    WHERE d.datasetname = %s
                ),
                src AS (
                    SELECT
                        rf.*,
                        dd.target_id AS target_rrr
                    FROM {s_rrrf} rf
                    JOIN ds_derechos dd ON dd.source_id = rf.rrr
                )
                INSERT INTO {t_rrrf}
                SELECT (jsonb_populate_record(
                    NULL::{t_rrrf},
                    to_jsonb(s) || jsonb_build_object(
                        't_id', mr.target_id,
                        't_basket', tb.t_id,
                        'rrr', s.target_rrr,
                        'fuente_administrativa', CASE WHEN s.fuente_administrativa IS NULL THEN NULL ELSE mf.target_id END,
                        't_ili_tid', ((md5(CONCAT(
                            random()::text, clock_timestamp()::text, '_rehyd_rrrf_', mr.target_id::text
                        )))::uuid)::text
                    )
                )).*
                FROM src s
                JOIN _rehyd_map_rrrf mr ON mr.source_id = s.t_id
                LEFT JOIN _rehyd_map_fuente mf ON mf.source_id = s.fuente_administrativa
                JOIN {s_basket} sb ON sb.t_id = s.t_basket
                JOIN {t_basket} tb ON tb.topic = sb.topic
                JOIN {t_dataset} td ON td.t_id = tb.dataset
                WHERE td.datasetname = %s
                  AND (s.fuente_administrativa IS NULL OR mf.target_id IS NOT NULL)
                ON CONFLICT (t_id) DO UPDATE
                SET
                    t_basket = EXCLUDED.t_basket,
                    rrr = EXCLUDED.rrr,
                    fuente_administrativa = EXCLUDED.fuente_administrativa
                """,
                (datasetname, datasetname),
            )

            # 4) Ensure grouped interesados keep valid members after id remap.
            cur.execute(
                """
                SELECT
                    EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = %s AND table_name = 'col_miembros'
                    ) AS has_target,
                    EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = %s AND table_name = 'col_miembros'
                    ) AS has_source
                """,
                (schema, source_schema),
            )
            has_members_target, has_members_source = cur.fetchone() or (False, False)
            if bool(has_members_target) and bool(has_members_source):
                t_miembros = _qualify(schema, "col_miembros")
                s_miembros = _qualify(source_schema, "col_miembros")
                cur.execute(
                    f"""
                    WITH src AS (
                        SELECT
                            m.*,
                            ma.target_id AS target_agrupacion,
                            COALESCE(mi.target_id, m.interesado_ilc_interesado) AS target_interesado,
                            COALESCE(mag.target_id, m.interesado_cr_agrupacioninteresados) AS target_agrup_interesado,
                            tb.t_id AS target_basket
                        FROM {s_miembros} m
                        JOIN _rehyd_map_agrup ma ON ma.source_id = m.agrupacion
                        JOIN {s_basket} sb ON sb.t_id = m.t_basket
                        JOIN {t_basket} tb ON tb.topic = sb.topic
                        JOIN {t_dataset} td ON td.t_id = tb.dataset
                        LEFT JOIN _rehyd_map_inter mi ON mi.source_id = m.interesado_ilc_interesado
                        LEFT JOIN _rehyd_map_agrup mag ON mag.source_id = m.interesado_cr_agrupacioninteresados
                        WHERE td.datasetname = %s
                          AND (
                                (m.interesado_ilc_interesado IS NULL OR mi.target_id IS NOT NULL)
                            AND (m.interesado_cr_agrupacioninteresados IS NULL OR mag.target_id IS NOT NULL)
                          )
                    ),
                    dedup AS (
                        SELECT DISTINCT ON (
                            target_agrupacion,
                            COALESCE(target_interesado, -1),
                            COALESCE(target_agrup_interesado, -1)
                        ) *
                        FROM src
                        ORDER BY
                            target_agrupacion,
                            COALESCE(target_interesado, -1),
                            COALESCE(target_agrup_interesado, -1),
                            t_id
                    ),
                    missing AS (
                        SELECT d.*
                        FROM dedup d
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM {t_miembros} tm
                            JOIN {t_basket} tmb ON tmb.t_id = tm.t_basket
                            JOIN {t_dataset} tmd ON tmd.t_id = tmb.dataset
                            WHERE tmd.datasetname = %s
                              AND tm.agrupacion = d.target_agrupacion
                              AND COALESCE(tm.interesado_ilc_interesado, -1) = COALESCE(d.target_interesado, -1)
                              AND COALESCE(tm.interesado_cr_agrupacioninteresados, -1) = COALESCE(d.target_agrup_interesado, -1)
                        )
                    ),
                    base AS (
                        SELECT COALESCE(MAX(t_id), 0) AS mx
                        FROM {t_miembros}
                    ),
                    payload AS (
                        SELECT
                            m.*,
                            base.mx + ROW_NUMBER() OVER (ORDER BY m.target_agrupacion, m.t_id) AS target_id
                        FROM missing m, base
                    )
                    INSERT INTO {t_miembros}
                    SELECT (jsonb_populate_record(
                        NULL::{t_miembros},
                        to_jsonb(p) || jsonb_build_object(
                            't_id', p.target_id,
                            't_basket', p.target_basket,
                            'agrupacion', p.target_agrupacion,
                            'interesado_ilc_interesado', p.target_interesado,
                            'interesado_cr_agrupacioninteresados', p.target_agrup_interesado,
                            't_ili_tid', ((md5(CONCAT(
                                random()::text, clock_timestamp()::text, '_rehyd_miembros_', p.target_id::text
                            )))::uuid)::text
                        )
                    )).*
                    FROM payload p
                    ON CONFLICT (t_id) DO NOTHING
                    """,
                    (datasetname, datasetname),
                )
        conn.commit()


def _validate_dataset_derecho_multiplicity(schema: str, datasetname: str) -> None:
    if not datasetname:
        return
    derecho = _qualify(schema, "ilc_derecho")
    rrr_fuente = _qualify(schema, "col_rrrfuente")
    rrr_inter = _qualify(schema, "col_rrrinteresado")
    basket = _qualify(schema, "t_ili2db_basket")
    dataset = _qualify(schema, "t_ili2db_dataset")
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                WITH invalid AS (
                    SELECT dr.t_id
                    FROM {derecho} dr
                    JOIN {basket} b ON b.t_id = dr.t_basket
                    JOIN {dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                      AND (
                        NOT EXISTS (
                          SELECT 1
                          FROM {rrr_inter} ri
                          JOIN {basket} ib ON ib.t_id = ri.t_basket
                          JOIN {dataset} idd ON idd.t_id = ib.dataset
                          WHERE idd.datasetname = %s
                            AND ri.rrr = dr.t_id
                        )
                        OR NOT EXISTS (
                          SELECT 1
                          FROM {rrr_fuente} rf
                          JOIN {basket} fb ON fb.t_id = rf.t_basket
                          JOIN {dataset} fdd ON fdd.t_id = fb.dataset
                          WHERE fdd.datasetname = %s
                            AND rf.rrr = dr.t_id
                        )
                      )
                )
                SELECT COUNT(*) FROM invalid
                """,
                (datasetname, datasetname, datasetname),
            )
            invalid_count = int((cur.fetchone() or [0])[0] or 0)
            if invalid_count <= 0:
                return

            cur.execute(
                f"""
                WITH invalid AS (
                    SELECT dr.t_id
                    FROM {derecho} dr
                    JOIN {basket} b ON b.t_id = dr.t_basket
                    JOIN {dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                      AND (
                        NOT EXISTS (
                          SELECT 1
                          FROM {rrr_inter} ri
                          JOIN {basket} ib ON ib.t_id = ri.t_basket
                          JOIN {dataset} idd ON idd.t_id = ib.dataset
                          WHERE idd.datasetname = %s
                            AND ri.rrr = dr.t_id
                        )
                        OR NOT EXISTS (
                          SELECT 1
                          FROM {rrr_fuente} rf
                          JOIN {basket} fb ON fb.t_id = rf.t_basket
                          JOIN {dataset} fdd ON fdd.t_id = fb.dataset
                          WHERE fdd.datasetname = %s
                            AND rf.rrr = dr.t_id
                        )
                      )
                    ORDER BY dr.t_id
                    LIMIT 20
                )
                SELECT t_id FROM invalid
                """,
                (datasetname, datasetname, datasetname),
            )
            sample = [str(r[0]) for r in (cur.fetchall() or []) if r and r[0] is not None]
            raise ExportServiceError(
                status_code=409,
                detail=(
                    f"Dataset '{datasetname}' invalido para exportar: "
                    f"{invalid_count} derecho(s) sin interesado/fuente_administrativa. "
                    f"Muestra t_id: {', '.join(sample) if sample else 'sin muestra'}."
                ),
            )


def _validate_dataset_predio_rrr_multiplicity(schema: str, datasetname: str) -> None:
    if not datasetname:
        return

    required = {
        "ilc_predio",
        "ilc_derecho",
        "t_ili2db_basket",
        "t_ili2db_dataset",
    }
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = ANY(%s)
                """,
                (schema, list(required)),
            )
            available = {str(r[0]) for r in (cur.fetchall() or []) if r and r[0]}
            if not required.issubset(available):
                return

            predio = _qualify(schema, "ilc_predio")
            derecho = _qualify(schema, "ilc_derecho")
            basket = _qualify(schema, "t_ili2db_basket")
            dataset = _qualify(schema, "t_ili2db_dataset")

            cur.execute(
                f"""
                WITH predios AS (
                    SELECT p.t_id, p.numero_predial_nacional, p.t_ili_tid
                    FROM {predio} p
                    JOIN {basket} b ON b.t_id = p.t_basket
                    JOIN {dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                conteo AS (
                    SELECT
                        p.t_id,
                        p.numero_predial_nacional,
                        p.t_ili_tid,
                        COUNT(dr.t_id)::int AS derechos_count
                    FROM predios p
                    LEFT JOIN {derecho} dr
                      ON dr.unidad = p.t_id
                    LEFT JOIN {basket} db ON db.t_id = dr.t_basket
                    LEFT JOIN {dataset} dd
                      ON dd.t_id = db.dataset
                     AND dd.datasetname = %s
                    WHERE dr.t_id IS NULL OR dd.t_id IS NOT NULL
                    GROUP BY p.t_id, p.numero_predial_nacional, p.t_ili_tid
                )
                SELECT
                    COUNT(*) FILTER (WHERE derechos_count = 0) AS sin_rrr,
                    COUNT(*) FILTER (WHERE derechos_count > 1) AS con_multiples,
                    COUNT(*) FILTER (WHERE derechos_count <> 1) AS invalidos_total
                FROM conteo
                """,
                (datasetname, datasetname),
            )
            row = cur.fetchone() or (0, 0, 0)
            sin_rrr = int(_row_get(row, 0, 0) or 0)
            con_multiples = int(_row_get(row, 1, 0) or 0)
            invalidos_total = int(_row_get(row, 2, 0) or 0)
            if invalidos_total <= 0:
                return

            cur.execute(
                f"""
                WITH predios AS (
                    SELECT p.t_id, p.numero_predial_nacional, p.t_ili_tid
                    FROM {predio} p
                    JOIN {basket} b ON b.t_id = p.t_basket
                    JOIN {dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                conteo AS (
                    SELECT
                        p.t_id,
                        p.numero_predial_nacional,
                        p.t_ili_tid,
                        COUNT(dr.t_id)::int AS derechos_count
                    FROM predios p
                    LEFT JOIN {derecho} dr
                      ON dr.unidad = p.t_id
                    LEFT JOIN {basket} db ON db.t_id = dr.t_basket
                    LEFT JOIN {dataset} dd
                      ON dd.t_id = db.dataset
                     AND dd.datasetname = %s
                    WHERE dr.t_id IS NULL OR dd.t_id IS NOT NULL
                    GROUP BY p.t_id, p.numero_predial_nacional, p.t_ili_tid
                )
                SELECT t_id, numero_predial_nacional, t_ili_tid, derechos_count
                FROM conteo
                WHERE derechos_count <> 1
                ORDER BY derechos_count, numero_predial_nacional NULLS LAST, t_id
                LIMIT 25
                """,
                (datasetname, datasetname),
            )
            sample_rows = cur.fetchall() or []
            sample = "; ".join(
                [
                    f"t_id={_row_get(r,0,'NULL')}, npn={_row_get(r,1,'NULL') or 'NULL'}, tid={_row_get(r,2,'NULL') or 'NULL'}, derechos={_row_get(r,3,'NULL')}"
                    for r in sample_rows
                    if r
                ]
            )
            raise ExportServiceError(
                status_code=409,
                detail=(
                    f"Dataset '{datasetname}' invalido para exportar: "
                    f"rol rrr de ILC_Predio requiere cardinalidad 1..1 y se detectaron "
                    f"{invalidos_total} predio(s) fuera de regla "
                    f"(sin rrr={sin_rrr}, con >1 rrr={con_multiples}). "
                    f"Muestra: {sample if sample else 'sin muestra'}."
                ),
            )




def _sanitize_dataset_predio_core_from_source(
    schema: str,
    datasetname: str,
    *,
    source_schema: str = "",
) -> None:
    if not datasetname:
        return
    if (schema or "").strip().lower() != (ASIG_MODEL_CONTEXT.schema_work or "").strip().lower():
        return

    source_schema = (source_schema or ASIG_MODEL_CONTEXT.schema_main).strip().strip('"')
    if not source_schema:
        return

    required_target = {
        "ilc_predio",
        "extdireccion",
        "ilc_datosadicionaleslevantamientocatastral",
        "t_ili2db_basket",
        "t_ili2db_dataset",
    }
    required_source = {
        "ilc_predio",
        "extdireccion",
        "ilc_datosadicionaleslevantamientocatastral",
        "t_ili2db_basket",
    }

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = ANY(%s)
                """,
                (schema, list(required_target)),
            )
            target_available = {str(r[0]) for r in (cur.fetchall() or []) if r and r[0]}
            if not required_target.issubset(target_available):
                return

            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = ANY(%s)
                """,
                (source_schema, list(required_source)),
            )
            source_available = {str(r[0]) for r in (cur.fetchall() or []) if r and r[0]}
            if not required_source.issubset(source_available):
                return

            t_basket = _qualify(schema, "t_ili2db_basket")
            t_dataset = _qualify(schema, "t_ili2db_dataset")
            t_predio = _qualify(schema, "ilc_predio")
            t_dir = _qualify(schema, "extdireccion")
            t_datos = _qualify(schema, "ilc_datosadicionaleslevantamientocatastral")

            s_basket = _qualify(source_schema, "t_ili2db_basket")
            s_predio = _qualify(source_schema, "ilc_predio")
            s_dir = _qualify(source_schema, "extdireccion")
            s_datos = _qualify(source_schema, "ilc_datosadicionaleslevantamientocatastral")

            cur.execute("DROP TABLE IF EXISTS _rehyd_map_predio")
            cur.execute(
                "CREATE TEMP TABLE _rehyd_map_predio(target_id bigint PRIMARY KEY, source_id bigint NOT NULL)"
            )

            cur.execute(
                f"""
                WITH target_predios AS (
                    SELECT p.t_id AS target_id, p.t_ili_tid, p.numero_predial_nacional
                    FROM {t_predio} p
                    JOIN {t_basket} b ON b.t_id = p.t_basket
                    JOIN {t_dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                matches AS (
                    SELECT
                        tp.target_id,
                        sp.t_id AS source_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY tp.target_id
                            ORDER BY
                                CASE
                                    WHEN tp.t_ili_tid IS NOT NULL AND sp.t_ili_tid = tp.t_ili_tid THEN 0
                                    ELSE 1
                                END,
                                sp.t_id
                        ) AS rn
                    FROM target_predios tp
                    JOIN {s_predio} sp
                      ON (
                            tp.t_ili_tid IS NOT NULL
                        AND sp.t_ili_tid = tp.t_ili_tid
                      )
                      OR (
                            tp.numero_predial_nacional IS NOT NULL
                        AND sp.numero_predial_nacional = tp.numero_predial_nacional
                      )
                      OR (
                            sp.t_id = tp.target_id
                      )
                )
                INSERT INTO _rehyd_map_predio(target_id, source_id)
                SELECT target_id, source_id
                FROM matches
                WHERE rn = 1
                ON CONFLICT (target_id) DO UPDATE SET source_id = EXCLUDED.source_id
                """,
                (datasetname,),
            )

            # Keep exactly one direccion per predio in dataset.
            cur.execute(
                f"""
                WITH ranked AS (
                    SELECT
                        d.t_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY d.ilc_predio_direccion
                            ORDER BY d.t_id
                        ) AS rn
                    FROM {t_dir} d
                    JOIN {t_basket} b ON b.t_id = d.t_basket
                    JOIN {t_dataset} ds ON ds.t_id = b.dataset
                    WHERE ds.datasetname = %s
                )
                DELETE FROM {t_dir} d
                USING ranked r
                WHERE d.t_id = r.t_id
                  AND r.rn > 1
                """,
                (datasetname,),
            )

            cur.execute(
                f"""
                WITH missing_predios AS (
                    SELECT p.t_id AS target_predio, mp.source_id AS source_predio
                    FROM {t_predio} p
                    JOIN {t_basket} b ON b.t_id = p.t_basket
                    JOIN {t_dataset} ds ON ds.t_id = b.dataset
                    JOIN _rehyd_map_predio mp ON mp.target_id = p.t_id
                    LEFT JOIN {t_dir} d ON d.ilc_predio_direccion = p.t_id
                    LEFT JOIN {t_basket} db ON db.t_id = d.t_basket
                    LEFT JOIN {t_dataset} dd ON dd.t_id = db.dataset AND dd.datasetname = %s
                    WHERE ds.datasetname = %s
                    GROUP BY p.t_id, mp.source_id
                    HAVING COUNT(dd.t_id) = 0
                ),
                src AS (
                    SELECT
                        mp.target_predio,
                        sd.*,
                        tb.t_id AS target_basket
                    FROM missing_predios mp
                    JOIN LATERAL (
                        SELECT s.*
                        FROM {s_dir} s
                        WHERE s.ilc_predio_direccion = mp.source_predio
                        ORDER BY s.t_id
                        LIMIT 1
                    ) sd ON TRUE
                    JOIN {s_basket} sb ON sb.t_id = sd.t_basket
                    JOIN {t_basket} tb ON tb.topic = sb.topic
                    JOIN {t_dataset} td ON td.t_id = tb.dataset
                    WHERE td.datasetname = %s
                ),
                base AS (
                    SELECT COALESCE(MAX(t_id), 0) AS mx
                    FROM {t_dir}
                ),
                payload AS (
                    SELECT
                        src.*,
                        base.mx + ROW_NUMBER() OVER (ORDER BY src.target_predio, src.t_id) AS target_id
                    FROM src, base
                )
                INSERT INTO {t_dir}
                SELECT (jsonb_populate_record(
                    NULL::{t_dir},
                    to_jsonb(p) || jsonb_build_object(
                        't_id', p.target_id,
                        't_basket', p.target_basket,
                        'ilc_predio_direccion', p.target_predio,
                        't_ili_tid', ((md5(CONCAT(
                            random()::text, clock_timestamp()::text, '_rehyd_direccion_', p.target_id::text
                        )))::uuid)::text
                    )
                )).*
                FROM payload p
                ON CONFLICT (t_id) DO NOTHING
                """,
                (datasetname, datasetname, datasetname),
            )

            # Keep exactly one datos_adicionales per predio in dataset.
            cur.execute(
                f"""
                WITH ranked AS (
                    SELECT
                        x.t_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY x.ilc_predio
                            ORDER BY x.t_id
                        ) AS rn
                    FROM {t_datos} x
                    JOIN {t_basket} b ON b.t_id = x.t_basket
                    JOIN {t_dataset} ds ON ds.t_id = b.dataset
                    WHERE ds.datasetname = %s
                )
                DELETE FROM {t_datos} x
                USING ranked r
                WHERE x.t_id = r.t_id
                  AND r.rn > 1
                """,
                (datasetname,),
            )

            cur.execute(
                f"""
                WITH missing_predios AS (
                    SELECT p.t_id AS target_predio, mp.source_id AS source_predio
                    FROM {t_predio} p
                    JOIN {t_basket} b ON b.t_id = p.t_basket
                    JOIN {t_dataset} ds ON ds.t_id = b.dataset
                    JOIN _rehyd_map_predio mp ON mp.target_id = p.t_id
                    LEFT JOIN {t_datos} x ON x.ilc_predio = p.t_id
                    LEFT JOIN {t_basket} xb ON xb.t_id = x.t_basket
                    LEFT JOIN {t_dataset} xd ON xd.t_id = xb.dataset AND xd.datasetname = %s
                    WHERE ds.datasetname = %s
                    GROUP BY p.t_id, mp.source_id
                    HAVING COUNT(xd.t_id) = 0
                ),
                src AS (
                    SELECT
                        mp.target_predio,
                        sx.*,
                        tb.t_id AS target_basket
                    FROM missing_predios mp
                    JOIN LATERAL (
                        SELECT s.*
                        FROM {s_datos} s
                        WHERE s.ilc_predio = mp.source_predio
                        ORDER BY s.t_id
                        LIMIT 1
                    ) sx ON TRUE
                    JOIN {s_basket} sb ON sb.t_id = sx.t_basket
                    JOIN {t_basket} tb ON tb.topic = sb.topic
                    JOIN {t_dataset} td ON td.t_id = tb.dataset
                    WHERE td.datasetname = %s
                ),
                base AS (
                    SELECT COALESCE(MAX(t_id), 0) AS mx
                    FROM {t_datos}
                ),
                payload AS (
                    SELECT
                        src.*,
                        base.mx + ROW_NUMBER() OVER (ORDER BY src.target_predio, src.t_id) AS target_id
                    FROM src, base
                )
                INSERT INTO {t_datos}
                SELECT (jsonb_populate_record(
                    NULL::{t_datos},
                    to_jsonb(p) || jsonb_build_object(
                        't_id', p.target_id,
                        't_basket', p.target_basket,
                        'ilc_predio', p.target_predio,
                        't_ili_tid', ((md5(CONCAT(
                            random()::text, clock_timestamp()::text, '_rehyd_datos_', p.target_id::text
                        )))::uuid)::text
                    )
                )).*
                FROM payload p
                ON CONFLICT (t_id) DO NOTHING
                """,
                (datasetname, datasetname, datasetname),
            )

        conn.commit()


def _validate_dataset_predio_aux_multiplicity(schema: str, datasetname: str) -> None:
    if not datasetname:
        return

    required = {
        "ilc_predio",
        "extdireccion",
        "ilc_datosadicionaleslevantamientocatastral",
        "t_ili2db_basket",
        "t_ili2db_dataset",
    }
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = ANY(%s)
                """,
                (schema, list(required)),
            )
            available = {str(r[0]) for r in (cur.fetchall() or []) if r and r[0]}
            if not required.issubset(available):
                return

            predio = _qualify(schema, "ilc_predio")
            direccion = _qualify(schema, "extdireccion")
            datos = _qualify(schema, "ilc_datosadicionaleslevantamientocatastral")
            basket = _qualify(schema, "t_ili2db_basket")
            dataset = _qualify(schema, "t_ili2db_dataset")

            cur.execute(
                f"""
                WITH predios AS (
                    SELECT p.t_id, p.numero_predial_nacional, p.t_ili_tid
                    FROM {predio} p
                    JOIN {basket} b ON b.t_id = p.t_basket
                    JOIN {dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                conteo AS (
                    SELECT
                        p.t_id,
                        p.numero_predial_nacional,
                        p.t_ili_tid,
                        COUNT(DISTINCT CASE WHEN ddd.t_id IS NOT NULL THEN d.t_id END)::int AS direccion_count,
                        COUNT(DISTINCT CASE WHEN ddx.t_id IS NOT NULL THEN x.t_id END)::int AS datos_count
                    FROM predios p
                    LEFT JOIN {direccion} d ON d.ilc_predio_direccion = p.t_id
                    LEFT JOIN {basket} dbd ON dbd.t_id = d.t_basket
                    LEFT JOIN {dataset} ddd ON ddd.t_id = dbd.dataset AND ddd.datasetname = %s
                    LEFT JOIN {datos} x ON x.ilc_predio = p.t_id
                    LEFT JOIN {basket} dbx ON dbx.t_id = x.t_basket
                    LEFT JOIN {dataset} ddx ON ddx.t_id = dbx.dataset AND ddx.datasetname = %s
                    GROUP BY p.t_id, p.numero_predial_nacional, p.t_ili_tid
                )
                SELECT
                    COUNT(*) FILTER (WHERE direccion_count <> 1) AS direccion_invalida,
                    COUNT(*) FILTER (WHERE datos_count <> 1) AS datos_invalido,
                    COUNT(*) FILTER (WHERE direccion_count <> 1 OR datos_count <> 1) AS invalidos_total
                FROM conteo
                """,
                (datasetname, datasetname, datasetname),
            )
            row = cur.fetchone() or (0, 0, 0)
            direccion_invalida = int(_row_get(row, 0, 0) or 0)
            datos_invalido = int(_row_get(row, 1, 0) or 0)
            invalidos_total = int(_row_get(row, 2, 0) or 0)
            if invalidos_total <= 0:
                return

            cur.execute(
                f"""
                WITH predios AS (
                    SELECT p.t_id, p.numero_predial_nacional, p.t_ili_tid
                    FROM {predio} p
                    JOIN {basket} b ON b.t_id = p.t_basket
                    JOIN {dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                conteo AS (
                    SELECT
                        p.t_id,
                        p.numero_predial_nacional,
                        p.t_ili_tid,
                        COUNT(DISTINCT CASE WHEN ddd.t_id IS NOT NULL THEN d.t_id END)::int AS direccion_count,
                        COUNT(DISTINCT CASE WHEN ddx.t_id IS NOT NULL THEN x.t_id END)::int AS datos_count
                    FROM predios p
                    LEFT JOIN {direccion} d ON d.ilc_predio_direccion = p.t_id
                    LEFT JOIN {basket} dbd ON dbd.t_id = d.t_basket
                    LEFT JOIN {dataset} ddd ON ddd.t_id = dbd.dataset AND ddd.datasetname = %s
                    LEFT JOIN {datos} x ON x.ilc_predio = p.t_id
                    LEFT JOIN {basket} dbx ON dbx.t_id = x.t_basket
                    LEFT JOIN {dataset} ddx ON ddx.t_id = dbx.dataset AND ddx.datasetname = %s
                    GROUP BY p.t_id, p.numero_predial_nacional, p.t_ili_tid
                )
                SELECT t_id, numero_predial_nacional, t_ili_tid, direccion_count, datos_count
                FROM conteo
                WHERE direccion_count <> 1 OR datos_count <> 1
                ORDER BY numero_predial_nacional NULLS LAST, t_id
                LIMIT 20
                """,
                (datasetname, datasetname, datasetname),
            )
            sample_rows = cur.fetchall() or []
            sample = "; ".join(
                [
                    f"t_id={_row_get(r,0,'NULL')}, npn={_row_get(r,1,'NULL') or 'NULL'}, tid={_row_get(r,2,'NULL') or 'NULL'}, direccion={_row_get(r,3,'NULL')}, datos={_row_get(r,4,'NULL')}"
                    for r in sample_rows
                    if r
                ]
            )
            raise ExportServiceError(
                status_code=409,
                detail=(
                    f"Dataset '{datasetname}' invalido para exportar: "
                    f"cardinalidad de ILC_Predio fuera de regla "
                    f"(direccion!=1: {direccion_invalida}, datos_adicionales!=1: {datos_invalido}). "
                    f"Muestra: {sample if sample else 'sin muestra'}."
                ),
            )


def _sanitize_dataset_predio_aux_cardinality(schema: str, datasetname: str) -> None:
    if not datasetname:
        return

    required = {
        "ilc_predio",
        "extdireccion",
        "ilc_datosadicionaleslevantamientocatastral",
        "t_ili2db_basket",
        "t_ili2db_dataset",
    }
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '3s'")
            cur.execute("SET LOCAL statement_timeout = '180s'")
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = ANY(%s)
                """,
                (schema, list(required)),
            )
            available = {str(r[0]) for r in (cur.fetchall() or []) if r and r[0]}
            if not required.issubset(available):
                return

            predio = _qualify(schema, "ilc_predio")
            direccion = _qualify(schema, "extdireccion")
            datos = _qualify(schema, "ilc_datosadicionaleslevantamientocatastral")
            basket = _qualify(schema, "t_ili2db_basket")
            dataset = _qualify(schema, "t_ili2db_dataset")

            cur.execute(
                f"""
                WITH predios AS (
                    SELECT p.t_id
                    FROM {predio} p
                    JOIN {basket} b ON b.t_id = p.t_basket
                    JOIN {dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                ranked AS (
                    SELECT
                        d.t_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY d.ilc_predio_direccion
                            ORDER BY d.t_id
                        ) AS rn
                    FROM {direccion} d
                    JOIN predios p ON p.t_id = d.ilc_predio_direccion
                    JOIN {basket} b ON b.t_id = d.t_basket
                    JOIN {dataset} ds ON ds.t_id = b.dataset
                    WHERE ds.datasetname = %s
                )
                DELETE FROM {direccion} d
                USING ranked r
                WHERE d.t_id = r.t_id
                  AND r.rn > 1
                """,
                (datasetname, datasetname),
            )

            cur.execute(
                f"""
                WITH predios AS (
                    SELECT p.t_id
                    FROM {predio} p
                    JOIN {basket} b ON b.t_id = p.t_basket
                    JOIN {dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                ranked AS (
                    SELECT
                        x.t_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY x.ilc_predio
                            ORDER BY x.t_id
                        ) AS rn
                    FROM {datos} x
                    JOIN predios p ON p.t_id = x.ilc_predio
                    JOIN {basket} b ON b.t_id = x.t_basket
                    JOIN {dataset} ds ON ds.t_id = b.dataset
                    WHERE ds.datasetname = %s
                )
                DELETE FROM {datos} x
                USING ranked r
                WHERE x.t_id = r.t_id
                  AND r.rn > 1
                """,
                (datasetname, datasetname),
            )

        conn.commit()


def _sanitize_dataset_agrup_miembros_cardinality(schema: str, datasetname: str) -> None:
    if not datasetname:
        return

    required = {
        "cr_agrupacioninteresados",
        "col_miembros",
        "col_rrrinteresado",
        "t_ili2db_basket",
        "t_ili2db_dataset",
    }
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '3s'")
            cur.execute("SET LOCAL statement_timeout = '600s'")
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = ANY(%s)
                """,
                (schema, list(required)),
            )
            available = {str(r[0]) for r in (cur.fetchall() or []) if r and r[0]}
            if not required.issubset(available):
                return

            agrup = _qualify(schema, "cr_agrupacioninteresados")
            miembros = _qualify(schema, "col_miembros")
            rrri = _qualify(schema, "col_rrrinteresado")
            basket = _qualify(schema, "t_ili2db_basket")
            dataset = _qualify(schema, "t_ili2db_dataset")

            # 1) Collapse simple groups (exactly one direct interesado) into direct rrri.
            cur.execute(
                f"""
                WITH grupos AS (
                    SELECT g.t_id
                    FROM {agrup} g
                    JOIN {basket} b ON b.t_id = g.t_basket
                    JOIN {dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                conteo AS (
                    SELECT
                        g.t_id,
                        COUNT(m.*)::int AS miembros_count,
                        COUNT(*) FILTER (WHERE m.interesado_ilc_interesado IS NOT NULL)::int AS inter_count,
                        COUNT(*) FILTER (WHERE m.interesado_cr_agrupacioninteresados IS NOT NULL)::int AS subagr_count,
                        MIN(m.interesado_ilc_interesado) FILTER (WHERE m.interesado_ilc_interesado IS NOT NULL) AS solo_interesado
                    FROM grupos g
                    LEFT JOIN {miembros} m ON m.agrupacion = g.t_id
                    GROUP BY g.t_id
                ),
                single_ok AS (
                    SELECT t_id AS agrup_id, solo_interesado
                    FROM conteo
                    WHERE miembros_count = 1
                      AND inter_count = 1
                      AND subagr_count = 0
                      AND solo_interesado IS NOT NULL
                )
                ,
                target AS (
                    SELECT
                        ri.t_id AS ri_id,
                        s.solo_interesado
                    FROM {rrri} ri
                    JOIN {basket} b ON b.t_id = ri.t_basket
                    JOIN {dataset} d ON d.t_id = b.dataset
                    JOIN single_ok s ON s.agrup_id = ri.interesado_cr_agrupacioninteresados
                    WHERE d.datasetname = %s
                )
                UPDATE {rrri} ri
                SET
                    interesado_ilc_interesado = COALESCE(ri.interesado_ilc_interesado, t.solo_interesado),
                    interesado_cr_agrupacioninteresados = NULL
                FROM target t
                WHERE ri.t_id = t.ri_id
                """,
                (datasetname, datasetname),
            )

            # 2) Drop rrri rows still pointing to groups with <2 members.
            cur.execute(
                f"""
                WITH grupos AS (
                    SELECT g.t_id
                    FROM {agrup} g
                    JOIN {basket} b ON b.t_id = g.t_basket
                    JOIN {dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                invalid AS (
                    SELECT g.t_id
                    FROM grupos g
                    LEFT JOIN {miembros} m ON m.agrupacion = g.t_id
                    GROUP BY g.t_id
                    HAVING COUNT(m.*) < 2
                )
                DELETE FROM {rrri} ri
                USING invalid i, {basket} b, {dataset} d
                WHERE ri.t_basket = b.t_id
                  AND b.dataset = d.t_id
                  AND d.datasetname = %s
                  AND ri.interesado_cr_agrupacioninteresados = i.t_id
                """,
                (datasetname, datasetname),
            )

            # 3) Remove orphan/invalid members and invalid groups themselves.
            cur.execute(
                f"""
                WITH grupos AS (
                    SELECT g.t_id
                    FROM {agrup} g
                    JOIN {basket} b ON b.t_id = g.t_basket
                    JOIN {dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                invalid AS (
                    SELECT g.t_id
                    FROM grupos g
                    LEFT JOIN {miembros} m ON m.agrupacion = g.t_id
                    GROUP BY g.t_id
                    HAVING COUNT(m.*) < 2
                )
                DELETE FROM {miembros} m
                USING invalid i
                WHERE m.agrupacion = i.t_id
                """,
                (datasetname,),
            )

            cur.execute(
                f"""
                WITH grupos AS (
                    SELECT g.t_id
                    FROM {agrup} g
                    JOIN {basket} b ON b.t_id = g.t_basket
                    JOIN {dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                invalid AS (
                    SELECT g.t_id
                    FROM grupos g
                    LEFT JOIN {miembros} m ON m.agrupacion = g.t_id
                    GROUP BY g.t_id
                    HAVING COUNT(m.*) < 2
                )
                DELETE FROM {agrup} g
                USING invalid i
                WHERE g.t_id = i.t_id
                """,
                (datasetname,),
            )

            # 4) Clean any rrri left without interested after collapsing/deletion.
            cur.execute(
                f"""
                DELETE FROM {rrri} ri
                USING {basket} b, {dataset} d
                WHERE ri.t_basket = b.t_id
                  AND b.dataset = d.t_id
                  AND d.datasetname = %s
                  AND ri.interesado_ilc_interesado IS NULL
                  AND ri.interesado_cr_agrupacioninteresados IS NULL
                """,
                (datasetname,),
            )
        conn.commit()


def _validate_dataset_agrup_miembros_multiplicity(schema: str, datasetname: str) -> None:
    if not datasetname:
        return

    required = {
        "cr_agrupacioninteresados",
        "col_miembros",
        "t_ili2db_basket",
        "t_ili2db_dataset",
    }
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = ANY(%s)
                """,
                (schema, list(required)),
            )
            available = {str(r[0]) for r in (cur.fetchall() or []) if r and r[0]}
            if not required.issubset(available):
                return

            agrup = _qualify(schema, "cr_agrupacioninteresados")
            miembros = _qualify(schema, "col_miembros")
            basket = _qualify(schema, "t_ili2db_basket")
            dataset = _qualify(schema, "t_ili2db_dataset")

            cur.execute(
                f"""
                WITH grupos AS (
                    SELECT g.t_id
                    FROM {agrup} g
                    JOIN {basket} b ON b.t_id = g.t_basket
                    JOIN {dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                conteo AS (
                    SELECT g.t_id, COUNT(m.*)::int AS miembros_count
                    FROM grupos g
                    LEFT JOIN {miembros} m ON m.agrupacion = g.t_id
                    GROUP BY g.t_id
                )
                SELECT COUNT(*)
                FROM conteo
                WHERE miembros_count < 2
                """,
                (datasetname,),
            )
            invalidos = int((cur.fetchone() or [0])[0] or 0)
            if invalidos <= 0:
                return

            cur.execute(
                f"""
                WITH grupos AS (
                    SELECT g.t_id
                    FROM {agrup} g
                    JOIN {basket} b ON b.t_id = g.t_basket
                    JOIN {dataset} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                ),
                conteo AS (
                    SELECT g.t_id, COUNT(m.*)::int AS miembros_count
                    FROM grupos g
                    LEFT JOIN {miembros} m ON m.agrupacion = g.t_id
                    GROUP BY g.t_id
                )
                SELECT t_id, miembros_count
                FROM conteo
                WHERE miembros_count < 2
                ORDER BY t_id
                LIMIT 20
                """,
                (datasetname,),
            )
            sample_rows = cur.fetchall() or []
            sample = ", ".join(
                [f"agrup={_row_get(r,0,'NULL')} miembros={_row_get(r,1,'NULL')}" for r in sample_rows if r]
            )
            raise ExportServiceError(
                status_code=409,
                detail=(
                    f"Dataset '{datasetname}' invalido para exportar: "
                    f"{invalidos} agrupacion(es) con miembros insuficientes (minimo 2). "
                    f"Muestra: {sample if sample else 'sin muestra'}."
                ),
            )



def _augment_export_basket_ids_with_references(
    schema: str,
    datasetname: str,
    basket_ids: List[int],
) -> List[int]:
    base_ids = [int(b) for b in (basket_ids or []) if b is not None]
    if not datasetname:
        return sorted(set(base_ids))

    required = {"t_ili2db_basket", "t_ili2db_dataset"}
    optional = {
        "ilc_predio",
        "extdireccion",
        "ilc_datosadicionaleslevantamientocatastral",
        "ilc_derecho",
        "col_rrrinteresado",
        "ilc_interesado",
        "cr_agrupacioninteresados",
        "col_miembros",
        "col_rrrfuente",
        "ilc_fuenteadministrativa",
        "arb_predio",
        "arb_construccion",
        "arb_unidadconstruccion",
        "arb_terreno",
        "arb_derechointeresadofuente",
    }
    tracked_tables = sorted(required | optional)
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = ANY(%s)
                """,
                (schema, tracked_tables),
            )
            available = {str(r[0]) for r in (cur.fetchall() or []) if r and r[0]}
            if not required.issubset(available):
                return sorted(set(base_ids))

            basket = _qualify(schema, "t_ili2db_basket")
            dataset = _qualify(schema, "t_ili2db_dataset")
            extra_ids: set[int] = set()

            def _add_ids(query: str):
                cur.execute(query, (datasetname,))
                for row in cur.fetchall() or []:
                    if row and row[0] is not None:
                        extra_ids.add(int(row[0]))

            if {"ilc_predio", "extdireccion"}.issubset(available):
                predio = _qualify(schema, "ilc_predio")
                direccion = _qualify(schema, "extdireccion")
                _add_ids(
                    f"""
                    WITH predios AS (
                        SELECT p.t_id
                        FROM {predio} p
                        JOIN {basket} b ON b.t_id = p.t_basket
                        JOIN {dataset} d ON d.t_id = b.dataset
                        WHERE d.datasetname = %s
                    )
                    SELECT DISTINCT d.t_basket
                    FROM {direccion} d
                    JOIN predios p ON p.t_id = d.ilc_predio_direccion
                    WHERE d.t_basket IS NOT NULL
                    """
                )

            if {"ilc_predio", "ilc_datosadicionaleslevantamientocatastral"}.issubset(available):
                predio = _qualify(schema, "ilc_predio")
                datos = _qualify(schema, "ilc_datosadicionaleslevantamientocatastral")
                _add_ids(
                    f"""
                    WITH predios AS (
                        SELECT p.t_id
                        FROM {predio} p
                        JOIN {basket} b ON b.t_id = p.t_basket
                        JOIN {dataset} d ON d.t_id = b.dataset
                        WHERE d.datasetname = %s
                    )
                    SELECT DISTINCT x.t_basket
                    FROM {datos} x
                    JOIN predios p ON p.t_id = x.ilc_predio
                    WHERE x.t_basket IS NOT NULL
                    """
                )

            if {"ilc_derecho", "col_rrrinteresado", "ilc_interesado"}.issubset(available):
                derecho = _qualify(schema, "ilc_derecho")
                rrri = _qualify(schema, "col_rrrinteresado")
                inter = _qualify(schema, "ilc_interesado")
                _add_ids(
                    f"""
                    WITH RECURSIVE derechos AS (
                        SELECT dr.t_id
                        FROM {derecho} dr
                        JOIN {basket} b ON b.t_id = dr.t_basket
                        JOIN {dataset} d ON d.t_id = b.dataset
                        WHERE d.datasetname = %s
                    )
                    SELECT DISTINCT i.t_basket
                    FROM {rrri} ri
                    JOIN derechos dr ON dr.t_id = ri.rrr
                    JOIN {inter} i ON i.t_id = ri.interesado_ilc_interesado
                    WHERE ri.interesado_ilc_interesado IS NOT NULL
                      AND i.t_basket IS NOT NULL
                    """
                )

            if {"ilc_derecho", "col_rrrinteresado", "cr_agrupacioninteresados"}.issubset(available):
                derecho = _qualify(schema, "ilc_derecho")
                rrri = _qualify(schema, "col_rrrinteresado")
                agrup = _qualify(schema, "cr_agrupacioninteresados")
                _add_ids(
                    f"""
                    WITH RECURSIVE derechos AS (
                        SELECT dr.t_id
                        FROM {derecho} dr
                        JOIN {basket} b ON b.t_id = dr.t_basket
                        JOIN {dataset} d ON d.t_id = b.dataset
                        WHERE d.datasetname = %s
                    )
                    SELECT DISTINCT a.t_basket
                    FROM {rrri} ri
                    JOIN derechos dr ON dr.t_id = ri.rrr
                    JOIN {agrup} a ON a.t_id = ri.interesado_cr_agrupacioninteresados
                    WHERE ri.interesado_cr_agrupacioninteresados IS NOT NULL
                      AND a.t_basket IS NOT NULL
                    """
                )

            if {"ilc_derecho", "col_rrrfuente", "ilc_fuenteadministrativa"}.issubset(available):
                derecho = _qualify(schema, "ilc_derecho")
                rrrf = _qualify(schema, "col_rrrfuente")
                fuente = _qualify(schema, "ilc_fuenteadministrativa")
                _add_ids(
                    f"""
                    WITH RECURSIVE derechos AS (
                        SELECT dr.t_id
                        FROM {derecho} dr
                        JOIN {basket} b ON b.t_id = dr.t_basket
                        JOIN {dataset} d ON d.t_id = b.dataset
                        WHERE d.datasetname = %s
                    )
                    SELECT DISTINCT f.t_basket
                    FROM {rrrf} rf
                    JOIN derechos dr ON dr.t_id = rf.rrr
                    JOIN {fuente} f ON f.t_id = rf.fuente_administrativa
                    WHERE rf.fuente_administrativa IS NOT NULL
                      AND f.t_basket IS NOT NULL
                    """
                )

            if {"ilc_derecho", "col_rrrinteresado", "col_miembros"}.issubset(available):
                derecho = _qualify(schema, "ilc_derecho")
                rrri = _qualify(schema, "col_rrrinteresado")
                miembros = _qualify(schema, "col_miembros")
                q = f"""
                    WITH RECURSIVE derechos AS (
                        SELECT dr.t_id
                        FROM {derecho} dr
                        JOIN {basket} b ON b.t_id = dr.t_basket
                        JOIN {dataset} d ON d.t_id = b.dataset
                        WHERE d.datasetname = %s
                    ),
                    seed AS (
                        SELECT DISTINCT ri.interesado_cr_agrupacioninteresados AS agrup_id
                        FROM {rrri} ri
                        JOIN derechos dr ON dr.t_id = ri.rrr
                        WHERE ri.interesado_cr_agrupacioninteresados IS NOT NULL
                    ),
                    grupos AS (
                        SELECT agrup_id FROM seed
                        UNION
                        SELECT m.interesado_cr_agrupacioninteresados
                        FROM {miembros} m
                        JOIN grupos g ON g.agrup_id = m.agrupacion
                        WHERE m.interesado_cr_agrupacioninteresados IS NOT NULL
                    )
                    SELECT DISTINCT m.t_basket
                    FROM {miembros} m
                    JOIN grupos g ON g.agrup_id = m.agrupacion
                    WHERE m.t_basket IS NOT NULL
                """
                _add_ids(q)
                if "ilc_interesado" in available:
                    inter = _qualify(schema, "ilc_interesado")
                    _add_ids(
                        f"""
                        WITH RECURSIVE derechos AS (
                            SELECT dr.t_id
                            FROM {derecho} dr
                            JOIN {basket} b ON b.t_id = dr.t_basket
                            JOIN {dataset} d ON d.t_id = b.dataset
                            WHERE d.datasetname = %s
                        ),
                        seed AS (
                            SELECT DISTINCT ri.interesado_cr_agrupacioninteresados AS agrup_id
                            FROM {rrri} ri
                            JOIN derechos dr ON dr.t_id = ri.rrr
                            WHERE ri.interesado_cr_agrupacioninteresados IS NOT NULL
                        ),
                        grupos AS (
                            SELECT agrup_id FROM seed
                            UNION
                            SELECT m.interesado_cr_agrupacioninteresados
                            FROM {miembros} m
                            JOIN grupos g ON g.agrup_id = m.agrupacion
                            WHERE m.interesado_cr_agrupacioninteresados IS NOT NULL
                        )
                        SELECT DISTINCT i.t_basket
                        FROM {miembros} m
                        JOIN grupos g ON g.agrup_id = m.agrupacion
                        JOIN {inter} i ON i.t_id = m.interesado_ilc_interesado
                        WHERE m.interesado_ilc_interesado IS NOT NULL
                          AND i.t_basket IS NOT NULL
                        """
                    )
                if "cr_agrupacioninteresados" in available:
                    agrup = _qualify(schema, "cr_agrupacioninteresados")
                    _add_ids(
                        f"""
                        WITH RECURSIVE derechos AS (
                            SELECT dr.t_id
                            FROM {derecho} dr
                            JOIN {basket} b ON b.t_id = dr.t_basket
                            JOIN {dataset} d ON d.t_id = b.dataset
                            WHERE d.datasetname = %s
                        ),
                        seed AS (
                            SELECT DISTINCT ri.interesado_cr_agrupacioninteresados AS agrup_id
                            FROM {rrri} ri
                            JOIN derechos dr ON dr.t_id = ri.rrr
                            WHERE ri.interesado_cr_agrupacioninteresados IS NOT NULL
                        ),
                        grupos AS (
                            SELECT agrup_id FROM seed
                            UNION
                            SELECT m.interesado_cr_agrupacioninteresados
                            FROM {miembros} m
                            JOIN grupos g ON g.agrup_id = m.agrupacion
                            WHERE m.interesado_cr_agrupacioninteresados IS NOT NULL
                        )
                        SELECT DISTINCT a.t_basket
                        FROM {miembros} m
                        JOIN grupos g ON g.agrup_id = m.agrupacion
                        JOIN {agrup} a ON a.t_id = m.interesado_cr_agrupacioninteresados
                        WHERE m.interesado_cr_agrupacioninteresados IS NOT NULL
                          AND a.t_basket IS NOT NULL
                        """
                    )
                    
            if {"arb_predio", "arb_construccion"}.issubset(available):
                predio = _qualify(schema, "arb_predio")
                construccion = _qualify(schema, "arb_construccion")
                _add_ids(
                    f"""
                    WITH predios AS (
                        SELECT p.t_id
                        FROM {predio} p
                        JOIN {basket} b ON b.t_id = p.t_basket
                        JOIN {dataset} d ON d.t_id = b.dataset
                        WHERE d.datasetname = %s
                    )
                    SELECT DISTINCT c.t_basket
                    FROM {construccion} c
                    JOIN predios p ON p.t_id = c.predio
                    WHERE c.t_basket IS NOT NULL
                    """
                )
                if "arb_unidadconstruccion" in available:
                    unidad = _qualify(schema, "arb_unidadconstruccion")
                    _add_ids(
                        f"""
                        WITH predios AS (
                            SELECT p.t_id
                            FROM {predio} p
                            JOIN {basket} b ON b.t_id = p.t_basket
                            JOIN {dataset} d ON d.t_id = b.dataset
                            WHERE d.datasetname = %s
                        ),
                        construcciones AS (
                            SELECT c.t_id
                            FROM {construccion} c
                            JOIN predios p ON p.t_id = c.predio
                        )
                        SELECT DISTINCT u.t_basket
                        FROM {unidad} u
                        JOIN construcciones c ON c.t_id = u.construccion
                        WHERE u.t_basket IS NOT NULL
                        """
                    )

            if {"arb_predio", "arb_terreno"}.issubset(available):
                predio = _qualify(schema, "arb_predio")
                terreno = _qualify(schema, "arb_terreno")
                _add_ids(
                    f"""
                    WITH predios AS (
                        SELECT p.t_id
                        FROM {predio} p
                        JOIN {basket} b ON b.t_id = p.t_basket
                        JOIN {dataset} d ON d.t_id = b.dataset
                        WHERE d.datasetname = %s
                    )
                    SELECT DISTINCT t.t_basket
                    FROM {terreno} t
                    JOIN predios p ON p.t_id = t.predio
                    WHERE t.t_basket IS NOT NULL
                    """
                )

            if {"arb_predio", "arb_derechointeresadofuente"}.issubset(available):
                predio = _qualify(schema, "arb_predio")
                derecho = _qualify(schema, "arb_derechointeresadofuente")
                _add_ids(
                    f"""
                    WITH predios AS (
                        SELECT p.t_id
                        FROM {predio} p
                        JOIN {basket} b ON b.t_id = p.t_basket
                        JOIN {dataset} d ON d.t_id = b.dataset
                        WHERE d.datasetname = %s
                    )
                    SELECT DISTINCT df.t_basket
                    FROM {derecho} df
                    JOIN predios p ON p.t_id = df.predio
                    WHERE df.t_basket IS NOT NULL
                    """
                )

            merged = sorted(set(base_ids) | extra_ids)
            if not merged:
                return merged

            # Defensive filter: never export baskets that belong to another dataset.
            cur.execute(
                f"""
                SELECT b.t_id
                FROM {basket} b
                JOIN {dataset} d ON d.t_id = b.dataset
                WHERE d.datasetname = %s
                  AND b.t_id = ANY(%s)
                ORDER BY b.t_id
                """,
                (datasetname, merged),
            )
            allowed = [
                int(row[0])
                for row in (cur.fetchall() or [])
                if row and row[0] is not None
            ]
            return allowed

def _ensure_basket_tili_tids(schema: str, basket_ids: List[int]) -> None:
    if not basket_ids:
        return
    basket_table = _qualify(schema, "t_ili2db_basket")
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT t_id, NULLIF(TRIM(t_ili_tid), '') AS t_ili_tid
                FROM {basket_table}
                WHERE t_id = ANY(%s)
                ORDER BY t_id
                """,
                (basket_ids,),
            )
            rows = cur.fetchall() or []
            present_ids = {
                int(_row_get(row, 0))
                for row in rows
                if _row_get(row, 0, None) is not None
            }
            missing_ids = [
                int(_row_get(row, 0))
                for row in rows
                if _row_get(row, 0, None) is not None and not _row_get(row, 1, None)
            ]

            not_found = sorted(set(int(bid) for bid in basket_ids) - present_ids)
            if not_found:
                raise ExportServiceError(
                    status_code=400,
                    detail=f"No existen baskets {not_found} en {schema}.",
                )

            if not missing_ids:
                return

            for basket_id in missing_ids:
                cur.execute(
                    f"""
                    UPDATE {basket_table}
                    SET t_ili_tid = %s
                    WHERE t_id = %s
                      AND (t_ili_tid IS NULL OR TRIM(t_ili_tid) = '')
                    """,
                    (str(uuid.uuid4()), basket_id),
                )
        conn.commit()


def _fetch_basket_bids(schema: str, basket_ids: List[int]) -> List[str]:
    if not basket_ids:
        return []
    basket_table = _qualify(schema, "t_ili2db_basket")
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT NULLIF(TRIM(t_ili_tid), '') AS basket_bid
                FROM {basket_table}
                WHERE t_id = ANY(%s)
                ORDER BY t_id
                """,
                (basket_ids,),
            )
            bids = [
                str(row[0]).strip()
                for row in (cur.fetchall() or [])
                if row and row[0] is not None and str(row[0]).strip()
            ]
    if len(bids) != len(basket_ids):
        raise ExportServiceError(
            status_code=500,
            detail="No fue posible determinar BID (t_ili_tid) para todos los baskets.",
        )
    return bids


def ili2pg_export(
    schema: str,
    basket_ids: List[str],
    xtf_path: str,
    *,
    ili2pg_cmd: str = "",
    timeout_sec: int = ILI2PG_TIMEOUT_SEC,
):
    db = db_env()
    model_dir = _resolve_model_dir()
    basket_list = [
        str(b).strip()
        for b in (basket_ids or [])
        if b is not None and str(b).strip()
    ]
    if not basket_list:
        raise ExportServiceError(status_code=400, detail="No se definieron baskets para exportar.")
    baskets_arg = ";".join(basket_list)
    
    cmd_args = [
        "ili2pg",
        "--export",
        "--dbhost",
        db["host"],
        "--dbport",
        db["port"],
        "--dbusr",
        db["user"],
        "--dbpwd",
        db["password"],
        "--dbdatabase",
        db["dbname"],
        "--dbschema",
        schema,
        "--baskets",
        baskets_arg,
    ]
    if model_dir:
        cmd_args.extend(["--modeldir", model_dir])
    cmd_args.append(xtf_path)
    
    run_ili2pg(
        cmd_args,
        ili2pg_cmd=ili2pg_cmd,
        timeout_sec=timeout_sec,
    )


def _is_missing_t_basket_error(detail: str) -> bool:
    return "basket wise export requires column t_basket" in (detail or "").lower()


def _is_multiplicity_role_error(detail: str) -> bool:
    return "validate multiplicity of role" in (detail or "").lower()


def _is_derecho_missing_links_error(detail: str) -> bool:
    text = (detail or "").lower()
    return "derecho(s) sin interesado/fuente_administrativa" in text


def _is_agrup_multiplicity_error(detail: str) -> bool:
    text = (detail or "").lower()
    return "agrupacion(es) con miembros insuficientes" in text


def _is_lock_retryable_export_error(detail: str) -> bool:
    text = (detail or "").lower()
    return (
        "locknotavailable" in text
        or "lock timeout" in text
        or "canceling statement due to lock timeout" in text
    )


def _run_rehydrate_derecho_with_retry(schema: str, datasetname: str) -> None:
    retries = _safe_int_env("ASIG_REHYDRATE_LOCK_RETRIES", 3, minimum=0)
    backoff_ms = _safe_int_env("ASIG_REHYDRATE_LOCK_BACKOFF_MS", 1200, minimum=200)
    attempt = 0
    while True:
        attempt += 1
        try:
            _run_stage(
                "rehydrate_dataset_derecho_links_from_source",
                _rehydrate_dataset_derecho_links_from_source,
                schema,
                datasetname,
            )
            return
        except ExportServiceError as exc:
            detail = exc.detail if isinstance(exc.detail, str) else ""
            if attempt <= retries and _is_lock_retryable_export_error(detail):
                time.sleep((backoff_ms * attempt) / 1000.0)
                continue
            raise


def _run_validate_derecho_with_retry(schema: str, datasetname: str) -> None:
    try:
        _run_stage("validate_dataset_derecho_multiplicity", _validate_dataset_derecho_multiplicity, schema, datasetname)
    except ExportServiceError as exc:
        detail = exc.detail if isinstance(exc.detail, str) else ""
        if not _is_derecho_missing_links_error(detail):
            raise
        _run_rehydrate_derecho_with_retry(schema, datasetname)
        _run_stage("sanitize_dataset_derecho_links_retry", _sanitize_dataset_derecho_links, schema, datasetname)
        _run_stage(
            "validate_dataset_derecho_multiplicity_retry",
            _validate_dataset_derecho_multiplicity,
            schema,
            datasetname,
        )


def _run_validate_agrup_with_retry(schema: str, datasetname: str) -> None:
    try:
        _run_stage(
            "validate_dataset_agrup_miembros_multiplicity",
            _validate_dataset_agrup_miembros_multiplicity,
            schema,
            datasetname,
        )
    except ExportServiceError as exc:
        detail = exc.detail if isinstance(exc.detail, str) else ""
        if not _is_agrup_multiplicity_error(detail):
            raise
        _run_rehydrate_derecho_with_retry(schema, datasetname)
        _run_stage(
            "validate_dataset_agrup_miembros_multiplicity_retry",
            _validate_dataset_agrup_miembros_multiplicity,
            schema,
            datasetname,
        )


def _prepare_export_dataset_legacy_disabled(schema: str, datasetname: str) -> None:
    _run_stage("ensure_dataset_object_tili_tids", _ensure_dataset_object_tili_tids, schema, datasetname)
    _run_stage("sanitize_dataset_derecho_links_pre", _sanitize_dataset_derecho_links, schema, datasetname)
    _run_rehydrate_derecho_with_retry(schema, datasetname)
    _run_stage("sanitize_dataset_derecho_links_post", _sanitize_dataset_derecho_links, schema, datasetname)
    _run_stage(
        "sanitize_dataset_predio_core_from_source",
        _sanitize_dataset_predio_core_from_source,
        schema,
        datasetname,
    )
    _run_stage(
        "sanitize_dataset_predio_aux_cardinality",
        _sanitize_dataset_predio_aux_cardinality,
        schema,
        datasetname,
    )
    _run_stage(
        "sanitize_dataset_agrup_miembros_cardinality",
        _sanitize_dataset_agrup_miembros_cardinality,
        schema,
        datasetname,
    )
    _run_validate_derecho_with_retry(schema, datasetname)
    _run_stage(
        "validate_dataset_predio_rrr_multiplicity",
        _validate_dataset_predio_rrr_multiplicity,
        schema,
        datasetname,
    )
    _run_stage(
        "validate_dataset_predio_aux_multiplicity",
        _validate_dataset_predio_aux_multiplicity,
        schema,
        datasetname,
    )
    _run_stage(
        "validate_dataset_agrup_miembros_multiplicity",
        _validate_dataset_agrup_miembros_multiplicity,
        schema,
        datasetname,
    )
    _run_stage("validate_dataset_cuc_integrity", _validate_dataset_cuc_integrity, schema, datasetname)


def _prepare_export_dataset_arb(schema: str, datasetname: str) -> None:
    # Arbimaps no usa la rehidratacion/saneamiento del modelo ILC.
    # Solo asegura identificadores de exportacion y deja la consistencia
    # estructural a cargo del workspace Arbimaps.
    _run_stage("ensure_dataset_object_tili_tids", _ensure_dataset_object_tili_tids, schema, datasetname)


def _export_dataset_baskets_with_fallback(
    schema: str,
    datasetname: str,
    xtf_path: str,
    *,
    ili2pg_cmd: str,
    timeout_sec: int,
) -> None:
    basket_ids = _run_stage("fetch_dataset_basket_ids", _fetch_dataset_basket_ids, schema, datasetname)
    basket_ids = _run_stage(
        "augment_export_basket_ids_with_references",
        _augment_export_basket_ids_with_references,
        schema,
        datasetname,
        basket_ids,
    )
    _run_stage("ensure_basket_tili_tids", _ensure_basket_tili_tids, schema, basket_ids)
    basket_bids = _run_stage("fetch_basket_bids", _fetch_basket_bids, schema, basket_ids)
    if not basket_ids:
        raise ExportServiceError(
            status_code=400,
            detail=f"El dataset '{datasetname}' no tiene baskets para exportar en {schema}.",
        )
    _run_stage(
        "ili2pg_export_baskets",
        ili2pg_export,
        schema=schema,
        basket_ids=basket_bids,
        xtf_path=xtf_path,
        ili2pg_cmd=ili2pg_cmd,
        timeout_sec=timeout_sec,
    )


def _prepare_assignment_export_legacy_disabled(schema: str, datasetname: str, *, apply_dataset_sanitizers: bool) -> None:
    raise ExportServiceError(
        status_code=500,
        detail="La exportacion legacy Leiva ya no esta soportada en el modulo de asignaciones.",
    )


def _prepare_assignment_export_arb(schema: str, datasetname: str, *, apply_dataset_sanitizers: bool) -> None:
    # Arbimaps siempre debe garantizar identificadores exportables aunque
    # no use el pipeline de saneamiento del modelo Leiva.
    _prepare_export_dataset_arb(schema, datasetname)


def _export_assignment_baskets_with_fallback(
    schema: str,
    asignacion_id: int,
    datasetname: str,
    xtf_path: str,
    *,
    required_topics: Optional[List[str]],
    ili2pg_cmd: str,
    timeout_sec: int,
) -> str:
    basket_bids = _run_stage(
        "list_assignment_basket_bids",
        _list_assignment_basket_bids,
        schema=schema,
        asignacion_id=asignacion_id,
        datasetname=datasetname,
        required_topics=required_topics,
    )
    if not basket_bids:
        raise ExportServiceError(
            status_code=400,
            detail=f"La asignación {asignacion_id} no tiene baskets válidos para exportar.",
        )

    try:
        _run_stage(
            "ili2pg_export_baskets",
            ili2pg_export,
            schema=schema,
            basket_ids=basket_bids,
            xtf_path=xtf_path,
            ili2pg_cmd=ili2pg_cmd,
            timeout_sec=timeout_sec,
        )
        return "baskets"
    except ExportServiceError as e:
        detail = e.detail if isinstance(e.detail, str) else ""
        if not (_is_missing_t_basket_error(detail) or _is_multiplicity_role_error(detail)):
            raise

        _run_stage(
            "ili2pg_export_dataset_fallback",
            ili2pg_export_by_dataset,
            schema=schema,
            datasetname=datasetname,
            xtf_path=xtf_path,
            ili2pg_cmd=ili2pg_cmd,
            timeout_sec=timeout_sec,
        )
        return "dataset_fallback"


def ili2pg_export_by_dataset(
    schema: str,
    datasetname: str,
    xtf_path: str,
    *,
    ili2pg_cmd: str = "",
    timeout_sec: int = 600,
):
    if not datasetname:
        raise ExportServiceError(status_code=400, detail="Dataset no definido para exportar.")
    db = db_env()
    model_dir = _resolve_model_dir()
    cmd_args = [
        "ili2pg",
        "--export",
        "--dbhost",
        db["host"],
        "--dbport",
        db["port"],
        "--dbusr",
        db["user"],
        "--dbpwd",
        db["password"],
        "--dbdatabase",
        db["dbname"],
        "--dbschema",
        schema,
        "--dataset",
        datasetname,
    ]
    if model_dir:
        cmd_args.extend(["--modeldir", model_dir])
    cmd_args.append(xtf_path)

    run_ili2pg(
        cmd_args,
        ili2pg_cmd=ili2pg_cmd,
        timeout_sec=timeout_sec,
    )


def ili2pg_export_dataset(
    schema: str,
    datasetname: str,
    xtf_path: str,
    *,
    ili2pg_cmd: str = "",
    timeout_sec: int = 600,
):
    if not datasetname:
        raise ExportServiceError(status_code=400, detail="Dataset no definido para exportar.")
    try:
        _prepare_export_dataset_arb(schema, datasetname)

        _export_dataset_baskets_with_fallback(
            schema,
            datasetname,
            xtf_path,
            ili2pg_cmd=ili2pg_cmd,
            timeout_sec=timeout_sec,
        )
    except ExportServiceError as e:
        detail = e.detail if isinstance(e.detail, str) else ""
        if not _is_missing_t_basket_error(detail):
            raise
        ili2pg_export_by_dataset(
            schema=schema,
            datasetname=datasetname,
            xtf_path=xtf_path,
            ili2pg_cmd=ili2pg_cmd,
            timeout_sec=timeout_sec,
        )


def _list_assignment_basket_bids(
    schema: str,
    asignacion_id: int,
    datasetname: str,
    required_topics: Optional[List[str]] = None,
) -> List[str]:
    normalized_schema = (schema or "").strip().strip('"').lower()
    arb_work = (ASIG_MODEL_CONTEXT.schema_work or "").strip().strip('"').lower()
    predio_table_name, numero_field = _resolve_assignment_predio_source(schema)
    predio_table = _qualify(schema, predio_table_name)
    basket_table = _qualify(schema, "t_ili2db_basket")
    dataset_table = _qualify(schema, "t_ili2db_dataset")
    basket_ids: set[int] = set()

    with db_conn() as conn:
        with conn.cursor() as cur:
            # For assignment workspaces in b_asignaciones_arb, use all dataset baskets.
            # Exporting only predio baskets from a pruned workspace can leave
            # cross-topic references out. For workspaces, export the whole
            # dataset basket set that already belongs to the assignment.
            if normalized_schema in {arb_work}:
                cur.execute(
                    f"""
                    SELECT DISTINCT b.t_id
                    FROM {basket_table} b
                    JOIN {dataset_table} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                    """,
                    (datasetname,),
                )
                for row in cur.fetchall() or []:
                    if row and row[0] is not None:
                        basket_ids.add(int(row[0]))

                basket_ids_list = sorted(basket_ids)
                basket_ids_list = _augment_export_basket_ids_with_references(schema, datasetname, basket_ids_list)
                _ensure_basket_tili_tids(schema, basket_ids_list)
                return _fetch_basket_bids(schema, basket_ids_list)

            cur.execute(
                f"""
                SELECT DISTINCT b.t_id
                FROM {predio_table} p
                JOIN {basket_table} b ON b.t_id = p.t_basket
                JOIN {dataset_table} d ON d.t_id = b.dataset
                JOIN arbimaps_app.asignacion_predio ap
                  ON BTRIM(ap.numero_predial_nacional::text) = BTRIM(p.{numero_field}::text)
                 AND ap.asignacion_id = %s
                 AND ap.activo IS DISTINCT FROM FALSE
                WHERE d.datasetname = %s
                """,
                (asignacion_id, datasetname),
            )
            for row in cur.fetchall() or []:
                if row and row[0] is not None:
                    basket_ids.add(int(row[0]))

            topic_list = [topic.strip() for topic in (required_topics or []) if topic and topic.strip()]
            if topic_list and not basket_ids:
                cur.execute(
                    f"""
                    SELECT DISTINCT b.t_id
                    FROM {basket_table} b
                    JOIN {dataset_table} d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                      AND b.topic = ANY(%s)
                    """,
                    (datasetname, topic_list),
                )
                for row in cur.fetchall() or []:
                    if row and row[0] is not None:
                        basket_ids.add(int(row[0]))

    basket_ids_list = sorted(basket_ids)
    _ensure_basket_tili_tids(schema, basket_ids_list)
    return _fetch_basket_bids(schema, basket_ids_list)


def ili2pg_export_assignment(
    schema: str,
    asignacion_id: int,
    datasetname: str,
    xtf_path: str,
    *,
    required_topics: Optional[List[str]] = None,
    apply_dataset_sanitizers: bool = False,
    ili2pg_cmd: str = "",
    timeout_sec: int = 600,
):
    if not datasetname:
        raise ExportServiceError(status_code=400, detail="Dataset no definido para exportar.")

    _prepare_assignment_export_arb(
        schema,
        datasetname,
        apply_dataset_sanitizers=apply_dataset_sanitizers,
    )

    normalized_schema = (schema or "").strip().strip('"').lower()
    arb_work = (ASIG_MODEL_CONTEXT.schema_work or "").strip().strip('"').lower()

    if normalized_schema and normalized_schema == arb_work:
        # Cuando exportamos desde el esquema de trabajo (workspace), debemos forzar
        # la exportación por el datasetname específico de la asignación.
        # Dado que relajamos los Unique Constraints para permitir concurrencia, 
        # exportar por --baskets (t_ili_tid) arrastraría información de otras 
        # asignaciones que compartan el mismo contenedor transitoriamente.
        ili2pg_export_by_dataset(
            schema,
            datasetname,
            xtf_path,
            ili2pg_cmd=ili2pg_cmd,
            timeout_sec=timeout_sec,
        )
        return "dataset_full"

    return _export_assignment_baskets_with_fallback(
        schema,
        asignacion_id,
        datasetname,
        xtf_path,
        required_topics=required_topics,
        ili2pg_cmd=ili2pg_cmd,
        timeout_sec=timeout_sec,
    )


def ili2pg_import(
    schema: str,
    datasetname: str,
    xtf_path: str,
    *,
    ili2pg_cmd: str = "",
    timeout_sec: int = 600,
):
    from core.asignaciones import ASIG_MODEL_CONTEXT
    from services.asignaciones_workspace import _arb_disable_workspace_unique_constraints

    normalized_schema = (schema or "").strip().strip('"').lower()
    arb_work = (ASIG_MODEL_CONTEXT.schema_work or "").strip().strip('"').lower()

    if normalized_schema and normalized_schema == arb_work:
        # Al importar datos de retorno de campo (XTF) al workspace, es vital
        # desactivar las llaves únicas para evitar colisiones transaccionales
        # con otras asignaciones que se procesan en paralelo.
        _arb_disable_workspace_unique_constraints(schema)

    db = db_env()
    model_dir = _resolve_model_dir()
    cmd_args = [
        "ili2pg",
        "--replace",
        "--dbhost",
        db["host"],
        "--dbport",
        db["port"],
        "--dbusr",
        db["user"],
        "--dbpwd",
        db["password"],
        "--dbdatabase",
        db["dbname"],
        "--dbschema",
        schema,
        "--dataset",
        datasetname,
        "--disableValidation",
    ]
    if model_dir:
        cmd_args.extend(["--modeldir", model_dir])
    cmd_args.append(xtf_path)

    run_ili2pg(
        cmd_args,
        ili2pg_cmd=ili2pg_cmd,
        timeout_sec=timeout_sec,
    )


def ogr_export_gdb(
    schema: str,
    datasetname: str,
    gdb_path: str,
    *,
    asignacion_id: Optional[int] = None,
) -> None:
    if not datasetname:
        raise ExportServiceError(status_code=400, detail="Dataset no definido para exportar GDB.")
    db = db_env()
    conn_str = (
        f"PG:host={db['host']} port={db['port']} dbname={db['dbname']} "
        f"user={db['user']} password={db['password']}"
    )
    predio_table_name, numero_field = _resolve_assignment_predio_source(schema)
    ds_escaped = datasetname.replace("'", "''")
    if asignacion_id is not None:
        sql = (
            f"SELECT p.* FROM {schema}.{predio_table_name} p "
            f"JOIN {schema}.t_ili2db_basket b ON b.t_id = p.t_basket "
            f"JOIN {schema}.t_ili2db_dataset d ON d.t_id = b.dataset "
            f"JOIN arbimaps_app.asignacion_predio ap "
            f"  ON BTRIM(ap.numero_predial_nacional::text) = BTRIM(p.{numero_field}::text) "
            f" AND ap.asignacion_id = {int(asignacion_id)} "
            f" AND ap.activo IS DISTINCT FROM FALSE "
            f"WHERE d.datasetname = '{ds_escaped}'"
        )
    else:
        sql = (
            f"SELECT p.* FROM {schema}.{predio_table_name} p "
            f"JOIN {schema}.t_ili2db_basket b ON b.t_id = p.t_basket "
            f"JOIN {schema}.t_ili2db_dataset d ON d.t_id = b.dataset "
            f"WHERE d.datasetname = '{ds_escaped}'"
        )
    try:
        subprocess.run(
            ["ogr2ogr", "-f", "FileGDB", gdb_path, conn_str, "-sql", sql, "-nln", predio_table_name],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        stdout = (e.stdout or "").strip()
        detail = "ogr2ogr falló al exportar GDB."
        if stderr:
            detail += f" STDERR: {stderr}"
        if stdout:
            detail += f" STDOUT: {stdout}"
        raise ExportServiceError(status_code=500, detail=detail)


def ogr_export_gpkg(
    schema: str,
    datasetname: str,
    gpkg_path: str,
    *,
    asignacion_id: Optional[int] = None,
) -> None:
    if not datasetname:
        raise ExportServiceError(status_code=400, detail="Dataset no definido para exportar GPKG.")
    db = db_env()
    conn_str = (
        f"PG:host={db['host']} port={db['port']} dbname={db['dbname']} "
        f"user={db['user']} password={db['password']}"
    )
    predio_table_name, numero_field = _resolve_assignment_predio_source(schema)
    ds_escaped = datasetname.replace("'", "''")
    if asignacion_id is not None:
        sql_query = (
            f"SELECT p.* FROM {schema}.{predio_table_name} p "
            f"JOIN {schema}.t_ili2db_basket b ON b.t_id = p.t_basket "
            f"JOIN {schema}.t_ili2db_dataset d ON d.t_id = b.dataset "
            f"JOIN arbimaps_app.asignacion_predio ap "
            f"  ON BTRIM(ap.numero_predial_nacional::text) = BTRIM(p.{numero_field}::text) "
            f" AND ap.asignacion_id = {int(asignacion_id)} "
            f" AND ap.activo IS DISTINCT FROM FALSE "
            f"WHERE d.datasetname = '{ds_escaped}'"
        )
    else:
        sql_query = (
            f"SELECT p.* FROM {schema}.{predio_table_name} p "
            f"JOIN {schema}.t_ili2db_basket b ON b.t_id = p.t_basket "
            f"JOIN {schema}.t_ili2db_dataset d ON d.t_id = b.dataset "
            f"WHERE d.datasetname = '{ds_escaped}'"
        )
    try:
        subprocess.run(
            ["ogr2ogr", "-f", "GPKG", gpkg_path, conn_str, "-sql", sql_query, "-nln", predio_table_name],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        stdout = (e.stdout or "").strip()
        detail = "ogr2ogr fallo al exportar GPKG."
        if stderr:
            detail += f" STDERR: {stderr}"
        if stdout:
            detail += f" STDOUT: {stdout}"
        raise ExportServiceError(status_code=500, detail=detail)

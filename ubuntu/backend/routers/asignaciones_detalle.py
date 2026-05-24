import logging
import os
import re
import shutil
import tempfile
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from core.asignaciones import (
    ASIG_MODEL_CONTEXT,
    ILI2PG_CMD,
    ILI2PG_TIMEOUT_SEC,
)
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from psycopg2 import errorcodes
from psycopg2.extras import RealDictCursor

from repositories import asignaciones_repo
from routers.auth import require_assignment_roles
from routers.db import db_conn
from services import asignaciones_export as export_service
from services import asignaciones_workspace as workspace_service
from services.xtf_validation_service import XTFValidationService
from quality_rules.components import COMPONENTS
from quality_rules.loader import load_rule_group

router = APIRouter(prefix="/asignaciones", tags=["asignaciones-detalle"])
logger = logging.getLogger(__name__)
xtf_validation_service = XTFValidationService()


def _assignment_user_scope(user: Optional[dict]) -> tuple[str, str]:
    role = str(
        (user or {}).get("role")
        or (user or {}).get("rol")
        or (user or {}).get("role_code")
        or ""
    ).strip().lower()
    username = str((user or {}).get("username") or "").strip().lower()
    return role, username


def _ensure_assignment_owner_access(user: Optional[dict], asignacion: Optional[dict]) -> None:
    role, username = _assignment_user_scope(user)
    if role not in {"digitalizador", "reconocedor"}:
        return
    owner = str((asignacion or {}).get("usuario_asignado") or "").strip().lower()
    if not owner or owner != username:
        raise HTTPException(
            status_code=403,
            detail="La asignacion no le pertenece al usuario autenticado.",
        )


def _read_schema_main() -> str:
    value = (ASIG_MODEL_CONTEXT.schema_main or "").strip()
    if not value:
        raise RuntimeError("schema_main no configurado para asignaciones arb.")
    return value


def _read_schema_work() -> str:
    value = (ASIG_MODEL_CONTEXT.schema_work or "").strip()
    if not value:
        raise RuntimeError("schema_work no configurado para asignaciones arb.")
    return value


def _read_datasetname_main_default() -> str:
    return (ASIG_MODEL_CONTEXT.datasetname_main_default or "").strip()


def _read_required_baskets() -> set[str]:
    return set(ASIG_MODEL_CONTEXT.required_baskets or ())


class BasketInfo(BaseModel):
    dataset_id: Optional[int] = None
    datasetname: Optional[str] = None
    basket_id: Optional[int] = None
    basket_tid: Optional[str] = None
    topicname: Optional[str] = None
    total_predios: int = 0
    is_required: bool = False


class DatasetInfo(BaseModel):
    dataset_id: Optional[int] = None
    datasetname: Optional[str] = None
    baskets: List[BasketInfo] = Field(default_factory=list)


class AsignacionEvento(BaseModel):
    id: int | str
    asignacion_id: int | str
    evento: Optional[str] = None
    mensaje: Optional[str] = None
    usuario: Optional[str] = None
    creado_en: Optional[datetime] = None


class AsignacionPredioDetalle(BaseModel):
    id: int | str
    numero_predial_nacional: str
    predio_t_id: Optional[int] = None
    activo: Optional[bool] = None
    creado_por: Optional[str] = None
    creado_en: Optional[datetime] = None


class AsignacionDetalleResponse(BaseModel):
    id: int | str
    estado: Optional[str] = None
    fecha_creacion: Optional[datetime] = None
    coordinador: Optional[str] = None
    usuario_asignado: Optional[str] = None
    titulo: Optional[str] = None
    observaciones: Optional[str] = None
    datasetname_main: Optional[str] = None
    work_datasetname: Optional[str] = None
    error_msg: Optional[str] = None
    total_asignados: int = 0
    total_eliminados: int = 0
    total_nuevos: int = 0
    predios: List[AsignacionPredioDetalle] = Field(default_factory=list)


def _maybe_int(value) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(value: str, *, fallback: str) -> str:
    text = (value or "").strip()
    if _IDENT_RE.match(text):
        return text
    return fallback


def _qident(value: str) -> str:
    clean = _safe_ident(value, fallback="")
    if not clean:
        raise ValueError(f"Identificador SQL invalido: {value!r}")
    return f'"{clean}"'


def _table_column_specs(cur, schema: str, table: str) -> list[dict]:
    cur.execute(
        """
        SELECT column_name, data_type, udt_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    return list(cur.fetchall() or [])


def _projection_for_alias(alias: str, specs: list[dict]) -> str:
    parts: list[str] = []
    for col in specs:
        name = str(col.get("column_name") or "").strip()
        if not name:
            continue
        qname = _qident(name)
        udt_name = str(col.get("udt_name") or "").strip().lower()
        if udt_name in {"geometry", "geography"}:
            parts.append(f"ST_AsGeoJSON({alias}.{qname})::json AS {qname}")
        else:
            parts.append(f"{alias}.{qname}")
    return ", ".join(parts) if parts else f"{alias}.*"


def _fetch_rows(
    cur,
    *,
    schema: str,
    table: str,
    where_sql: str = "",
    params: tuple[Any, ...] = (),
    order_sql: str = "",
    limit: Optional[int] = None,
) -> list[dict]:
    safe_schema = _safe_ident(schema, fallback="b_asignaciones_arb")
    safe_table = _safe_ident(table, fallback=table)
    specs = _table_column_specs(cur, safe_schema, safe_table)
    if not specs:
        return []

    projection = _projection_for_alias("x", specs)
    sql = f"SELECT {projection} FROM {_qident(safe_schema)}.{_qident(safe_table)} x"
    if where_sql:
        sql += f" WHERE {where_sql}"
    if order_sql:
        sql += f" ORDER BY {order_sql}"
    if limit is not None and int(limit) > 0:
        sql += f" LIMIT {int(limit)}"

    cur.execute(sql, params)
    return list(cur.fetchall() or [])


def _columns_set(specs: list[dict]) -> set[str]:
    return {str(col.get("column_name") or "").strip() for col in specs}


def _find_first_column(specs: list[dict], candidates: list[str]) -> Optional[str]:
    cols = _columns_set(specs)
    for candidate in candidates:
        if candidate in cols:
            return candidate
    return None


def _fetch_rows_by_fk_candidates(
    cur,
    *,
    schema: str,
    table_candidates: list[str],
    fk_candidates: list[str],
    fk_value: Any,
    order_sql: str = 'x."t_id" ASC',
) -> list[dict]:
    if fk_value is None:
        return []
    target = str(fk_value)
    for table in table_candidates:
        safe_table = _safe_ident(table, fallback="")
        if not safe_table:
            continue
        specs = _table_column_specs(cur, schema, safe_table)
        if not specs:
            continue
        fk_col = _find_first_column(specs, fk_candidates)
        if not fk_col:
            continue
        rows = _fetch_rows(
            cur,
            schema=schema,
            table=safe_table,
            where_sql=f'x.{_qident(fk_col)}::text = %s',
            params=(target,),
            order_sql=order_sql,
        )
        if rows:
            return rows
    return []


def _fetch_rows_by_fk_any_candidates(
    cur,
    *,
    schema: str,
    table_candidates: list[str],
    fk_candidates: list[str],
    fk_values: list[Any],
    order_sql: str = 'x."t_id" ASC',
) -> list[dict]:
    values = [str(v) for v in fk_values if v is not None and str(v).strip()]
    if not values:
        return []
    for table in table_candidates:
        safe_table = _safe_ident(table, fallback="")
        if not safe_table:
            continue
        specs = _table_column_specs(cur, schema, safe_table)
        if not specs:
            continue
        fk_col = _find_first_column(specs, fk_candidates)
        if not fk_col:
            continue
        rows = _fetch_rows(
            cur,
            schema=schema,
            table=safe_table,
            where_sql=f'x.{_qident(fk_col)}::text = ANY(%s::text[])',
            params=(values,),
            order_sql=order_sql,
        )
        if rows:
            return rows
    return []


def _first_non_empty(row: dict, *keys: str):
    for key in keys:
        if key in row:
            value = row.get(key)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
    return None


def _build_full_name(row: dict) -> str:
    nombre = " ".join(
        str(v).strip()
        for v in (
            _first_non_empty(row, "primer_nombre", "i_primer_nombre"),
            _first_non_empty(row, "segundo_nombre", "i_segundo_nombre"),
            _first_non_empty(row, "primer_apellido", "i_primer_apellido"),
            _first_non_empty(row, "segundo_apellido", "i_segundo_apellido"),
        )
        if v is not None and str(v).strip()
    ).strip()
    razon_social = _first_non_empty(row, "razon_social", "i_razon_social")
    return str(razon_social or nombre or "").strip()


def _resolve_domain_name(
    cur,
    *,
    schema: str,
    table_candidates: list[str],
    raw_value: Any,
) -> Optional[str]:
    if raw_value is None or str(raw_value).strip() == "":
        return None
    target = str(raw_value).strip()
    schema_candidates = []
    for s in (schema, _safe_ident(_read_schema_main(), fallback="a_base_principal")):
        safe_s = _safe_ident(s, fallback="")
        if safe_s and safe_s not in schema_candidates:
            schema_candidates.append(safe_s)

    for table in table_candidates:
        safe_table = _safe_ident(table, fallback="")
        if not safe_table:
            continue
        for schema_name in schema_candidates:
            specs = _table_column_specs(cur, schema_name, safe_table)
            if not specs:
                continue
            columns = {str(c.get("column_name") or "").strip() for c in specs}
            value_col = next(
                (
                    col
                    for col in ("dispname", "nombre", "descripcion", "label", "codigo", "valor")
                    if col in columns
                ),
                None,
            )
            if not value_col:
                continue

            key_cols = [c for c in ("t_id", "ilicode", "codigo", "valor") if c in columns]
            for key_col in key_cols:
                cur.execute(
                    f"""
                    SELECT { _qident(value_col) }::text AS nombre
                    FROM {_qident(schema_name)}.{_qident(safe_table)}
                    WHERE {_qident(key_col)}::text = %s
                    LIMIT 1
                    """,
                    (target,),
                )
                row = cur.fetchone() or {}
                nombre = row.get("nombre")
                if nombre is not None and str(nombre).strip():
                    return str(nombre).strip()
    return None


def _is_required_basket_name(value: Optional[str]) -> bool:
    if not value:
        return False
    return value.strip() in _read_required_baskets()


def _raise_http_from_export_error(exc: Exception, *, stage: Optional[str] = None) -> None:
    stage_prefix = f"[{stage}] " if stage else ""
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, export_service.ExportServiceError):
        detail = exc.detail
        if stage_prefix and isinstance(detail, str):
            detail = f"{stage_prefix}{detail}"
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc

    pg_code = str(getattr(exc, "pgcode", "") or "")
    if pg_code == errorcodes.UNIQUE_VIOLATION:
        raise HTTPException(
            status_code=409,
            detail=f"{stage_prefix}Conflicto de unicidad en base de datos: {_error_detail(exc)}",
        ) from exc
    if pg_code in {
        errorcodes.FOREIGN_KEY_VIOLATION,
        errorcodes.NOT_NULL_VIOLATION,
        errorcodes.CHECK_VIOLATION,
    }:
        raise HTTPException(
            status_code=409,
            detail=f"{stage_prefix}Conflicto de integridad de datos: {_error_detail(exc)}",
        ) from exc
    if pg_code in {errorcodes.LOCK_NOT_AVAILABLE, errorcodes.DEADLOCK_DETECTED}:
        raise HTTPException(
            status_code=503,
            detail=f"{stage_prefix}Conflicto transaccional temporal en base de datos: {_error_detail(exc)}",
        ) from exc
    if pg_code == errorcodes.SERIALIZATION_FAILURE:
        raise HTTPException(
            status_code=409,
            detail=f"{stage_prefix}Conflicto de serializacion de transaccion: {_error_detail(exc)}",
        ) from exc

    if isinstance(exc, ValueError):
        message = str(exc) or "Valor invalido."
        status_code = 404 if "asignacion no encontrada" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=f"{stage_prefix}{message}") from exc

    raise HTTPException(
        status_code=500,
        detail=f"{stage_prefix}No se pudo procesar el retorno XTF: {_error_detail(exc)}",
    ) from exc


def _error_detail(exc: Exception) -> str:
    if isinstance(exc, export_service.ExportServiceError):
        return str(exc.detail)
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return str(exc) or exc.__class__.__name__


def _build_retorno_datasetname(work_datasetname: str, version: int) -> str:
    base = (work_datasetname or "").strip()
    if not base:
        raise ValueError("No se puede construir dataset temporal sin work_datasetname.")
    return f"{base}_ret_{int(version):02d}"


def _ili2pg_import(schema: str, datasetname: str, xtf_path: str):
    try:
        return export_service.ili2pg_import(
            schema,
            datasetname,
            xtf_path,
            ili2pg_cmd=ILI2PG_CMD,
            timeout_sec=ILI2PG_TIMEOUT_SEC,
        )
    except Exception as exc:
        _raise_http_from_export_error(exc, stage="ili2pg_import")


def _is_retorno_xtf_validation_required() -> bool:
    value = (os.getenv("ASIG_RETORNO_REQUIRE_XTF_VALIDATION", "1") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _is_production_runtime() -> bool:
    value = (os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "production")) or "").strip().lower()
    return value in {"prod", "production"}


def _allow_retorno_sync_on_validator_infra_error() -> bool:
    value = (os.getenv("ASIG_RETORNO_ALLOW_VALIDATOR_INFRA_ERROR", "0") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _allow_retorno_sync_with_missing_predios() -> bool:
    value = (os.getenv("ASIG_RETORNO_ALLOW_MISSING_PREDIOS", "0") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _retorno_correlation_id(asignacion_id: int) -> str:
    return f"ret-sync-{asignacion_id}-{uuid4().hex[:12]}"


def _log_sync_event(
    event: str,
    *,
    correlation_id: str,
    asignacion_id: int,
    retorno_id: Optional[int],
    retorno_dataset: Optional[str],
    stage: str,
    status: str,
    duration_ms: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    payload: Dict[str, Any] = {
        "event": event,
        "correlation_id": correlation_id,
        "asignacion_id": asignacion_id,
        "retorno_id": retorno_id,
        "retorno_datasetname": retorno_dataset,
        "stage": stage,
        "status": status,
    }
    if duration_ms is not None:
        payload["duration_ms"] = int(duration_ms)
    if extra:
        payload.update(extra)
    logger.info(json.dumps(payload, ensure_ascii=False))


def _copy_upload_and_sha256(upload_file: UploadFile, dst_path: str) -> str:
    digest = hashlib.sha256()
    with open(dst_path, "wb") as out:
        while True:
            chunk = upload_file.file.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
    return digest.hexdigest()


def _is_validator_infra_error_result(result: dict) -> bool:
    text_parts: List[str] = []
    message = str(result.get("message") or "").strip()
    if message:
        text_parts.append(message.lower())

    errors = result.get("errors")
    if isinstance(errors, list):
        for item in errors:
            if isinstance(item, dict):
                msg = str(item.get("message") or "").strip()
            else:
                msg = str(item or "").strip()
            if msg:
                text_parts.append(msg.lower())

    combined = "\n".join(text_parts)
    signatures = (
        "unable to initialize main class",
        "could not find or load main class",
        "classnotfoundexception",
        "unable to access jarfile",
        "unsupportedclassversionerror",
        "java.lang.noclassdeffounderror",
        "no main manifest attribute",
    )
    return any(sig in combined for sig in signatures)


def _xtf_validation_note(result: Optional[dict]) -> str:
    if not result:
        return "status=not_run"
    status = str(result.get("status") or "unknown").strip().lower()
    error_items = result.get("errors") if isinstance(result.get("errors"), list) else []
    message = str(result.get("message") or "").strip()
    note = f"status={status}"
    if error_items:
        note = f"{note}, errores={len(error_items)}"
    if message:
        note = f"{note}, detalle={message}"
    return note[:240] + "..." if len(note) > 243 else note


def _xtf_validation_error_preview(result: Optional[dict], *, limit: Optional[int] = None) -> str:
    if not result:
        return ""
    errors = result.get("errors")
    if not isinstance(errors, list):
        return ""
    preview: List[str] = []
    for item in errors:
        if isinstance(item, dict):
            message = str(item.get("message") or "").strip()
            rule = str(item.get("rule") or "").strip()
            object_ref = str(item.get("object_id") or "").strip()
            if rule:
                message = f"[regla {rule}] {message}"
            if object_ref:
                message = f"{message} (objeto {object_ref})"
        else:
            message = str(item or "").strip()
        if message:
            preview.append(message)
        if limit is not None and len(preview) >= max(int(limit), 1):
            break
    return "\n".join(f"{idx + 1}. {msg}" for idx, msg in enumerate(preview))


def _history_error_message(
    stage: str,
    exc: Exception,
    *,
    validation_result: Optional[dict] = None,
) -> str:
    detail = _error_detail(exc)
    parts = [f"Fallo en etapa {stage}: {detail}"]
    if validation_result:
        parts.append(f"Validacion XTF: {_xtf_validation_note(validation_result)}")
        preview = _xtf_validation_error_preview(validation_result, limit=None)
        if preview:
            parts.append(f"Errores detectados: {preview}")
    return " | ".join(parts)


def _quality_rules_catalog() -> list[dict]:
    catalog: list[dict] = []
    for component_slug, component in COMPONENTS.items():
        default_ids = sorted(str(rid) for rid in (component.default_rule_ids or []))
        definitions_map: dict[str, str] = {}
        try:
            definitions = load_rule_group(component_slug)
            definitions_map = {
                str(defn.rule_id): str(defn.description or "").strip()
                for defn in definitions
            }
        except Exception:
            definitions_map = {}

        rules = [
            {
                "rule_id": rid,
                "description": definitions_map.get(rid) or "Sin descripcion cargada.",
            }
            for rid in default_ids
        ]

        catalog.append(
            {
                "component": component_slug,
                "rules": rules,
                "total_rules": len(rules),
            }
        )
    return catalog


def _validator_pipeline_labels() -> list[str]:
    labels = ["ili2_validator"]
    labels.extend(f"quality_rules:{item['component']}" for item in _quality_rules_catalog())
    return labels


def _extract_rule_ids_from_validation(result: Optional[dict], *, limit: int = 6) -> list[str]:
    if not result:
        return []
    errors = result.get("errors")
    if not isinstance(errors, list):
        return []

    found: list[str] = []
    for item in errors:
        rule_id = ""
        if isinstance(item, dict):
            rule_id = str(item.get("rule") or "").strip()
        if rule_id and rule_id not in found:
            found.append(rule_id)
        if len(found) >= max(limit, 1):
            break
    return found


def _validation_history_message(result: Optional[dict]) -> str:
    pipeline = ", ".join(_validator_pipeline_labels())
    rule_ids = _extract_rule_ids_from_validation(result)
    rules_text = f" Reglas con hallazgos: {', '.join(rule_ids)}." if rule_ids else ""
    return (
        f"Resultado validacion XTF: {_xtf_validation_note(result)}. "
        f"Validadores ejecutados: {pipeline}.{rules_text}"
    )


@router.get("/validadores-xtf")
def listar_validadores_xtf(
    _user: dict = Depends(require_assignment_roles("admin", "coordinador", "digitalizador")),
):
    service = xtf_validation_service
    return {
        "pipeline": _validator_pipeline_labels(),
        "ili2_validator": {
            "jar_path": str(getattr(service, "validator_jar", "") or ""),
            "models": str(getattr(service, "models", "") or ""),
            "model_dir": str(getattr(service, "model_dir", "") or ""),
            "extra_args": list(getattr(service, "extra_args", []) or []),
        },
        "quality_rules": _quality_rules_catalog(),
    }


def _validate_retorno_xtf_rules(xtf_path: str) -> dict:
    service = xtf_validation_service

    try:
        if hasattr(service, "validate_file_path") and callable(getattr(service, "validate_file_path")):
            result = service.validate_file_path(xtf_path)
        elif hasattr(service, "validate_xtf_path") and callable(getattr(service, "validate_xtf_path")):
            # Compatibilidad con variantes antiguas del servicio.
            result = service.validate_xtf_path(xtf_path)
        elif hasattr(service, "_validate_xtf") and callable(getattr(service, "_validate_xtf")):
            # Fallback para despliegues legacy: _validate_xtf(job_id, file_path)
            result = service._validate_xtf(f"retorno-{uuid4().hex[:8]}", Path(xtf_path))
        else:
            raise export_service.ExportServiceError(
                status_code=503,
                detail="El servicio de validacion XTF no expone una interfaz compatible."
            )
    except Exception as exc:
        raise export_service.ExportServiceError(
            status_code=409,
            detail=f"Fallo critico del validador procesando el archivo: {exc}. El XTF podria tener errores graves de formato o integridad."
        )

    if not isinstance(result, dict):
        raise export_service.ExportServiceError(
            status_code=409,
            detail=(
                "El validador retorno una respuesta no valida. "
                "No se puede continuar con la sincronizacion."
            ),
        )

    status = str(result.get("status") or "").strip().lower()

    if status in {"failed", "invalid"}:
        message = str(result.get("message") or "Validacion XTF fallida.").strip()
        try:
            preview = _xtf_validation_error_preview(result)
        except Exception:
            preview = ""
        detail = f"El retorno XTF no supero la validacion de calidad/consistencia ({status}). {message}"
        if preview:
            detail = f"{detail} Errores: {preview}."
        raise export_service.ExportServiceError(status_code=409, detail=detail)

    if status == "error":
        if (
            not _is_production_runtime()
            and _is_validator_infra_error_result(result)
            and _allow_retorno_sync_on_validator_infra_error()
        ):
            return result
        message = str(result.get("message") or "Validacion XTF fallida.").strip()
        try:
            preview = _xtf_validation_error_preview(result)
        except Exception:
            preview = ""
        detail = f"El retorno XTF no supero la validacion de calidad/consistencia ({status}). {message}"
        if preview:
            detail = f"{detail} Errores: {preview}."
        raise export_service.ExportServiceError(status_code=409, detail=detail)

    if status == "skipped" and (_is_retorno_xtf_validation_required() or _is_production_runtime()):
        message = str(result.get("message") or "Validacion XTF omitida por infraestructura.").strip()
        raise export_service.ExportServiceError(
            status_code=503,
            detail=(
                "No fue posible ejecutar la validacion XTF requerida antes de sincronizar. "
                f"{message}"
            ),
        )

    if _is_production_runtime() and status != "success":
        raise export_service.ExportServiceError(
            status_code=409,
            detail=(
                "La sincronizacion en produccion requiere validacion XTF exitosa "
                f"(status=success). Estado recibido: {status or 'unknown'}."
            ),
        )

    return result


def _ensure_workspace_ready_for_export(asignacion_id: int, created_by: Optional[str]) -> str:
    try:
        return workspace_service.ensure_workspace_ready_for_export(
            asignacion_id,
            created_by,
            schema_main=_read_schema_main(),
            schema_work=_read_schema_work(),
            datasetname_main_default=_read_datasetname_main_default(),
            ili2pg_cmd=ILI2PG_CMD,
            timeout_sec=ILI2PG_TIMEOUT_SEC,
            required_topics=sorted(_read_required_baskets()),
            update_asignacion_fields=asignaciones_repo.update_asignacion_fields,
            safe_log_event=asignaciones_repo.safe_log_event,
        )
    except Exception as exc:
        _raise_http_from_export_error(exc, stage="ensure_workspace_ready_for_export")


@router.get("/datasets", response_model=List[DatasetInfo])
def listar_datasets_disponibles(
    _user: dict = Depends(require_assignment_roles("admin", "coordinador")),
):
    try:
        with db_conn() as conn:
            dataset_rows, basket_rows, predio_count_rows = asignaciones_repo.fetch_datasets_baskets_predio_counts(
                conn,
                _read_schema_main(),
                model_context=ASIG_MODEL_CONTEXT,
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudieron cargar los datasets: {e}")

    predio_counts: dict[int, int] = {}
    for row in predio_count_rows:
        t_basket = _maybe_int(row.get("t_basket"))
        if t_basket is not None:
            predio_counts[t_basket] = int(row.get("total_predios") or 0)

    grouped: dict[int, DatasetInfo] = {}
    for row in dataset_rows:
        dataset_id = _maybe_int(row.get("dataset_id"))
        grouped[dataset_id or 0] = DatasetInfo(
            dataset_id=dataset_id,
            datasetname=row.get("datasetname"),
            baskets=[],
        )

    for row in basket_rows:
        dataset_id = _maybe_int(row.get("dataset_id"))
        key = dataset_id or 0
        if key not in grouped:
            grouped[key] = DatasetInfo(dataset_id=dataset_id, datasetname=None, baskets=[])
        ds_entry = grouped[key]
        topic = row.get("topicname")
        ds_entry.baskets.append(
            BasketInfo(
                dataset_id=dataset_id,
                datasetname=ds_entry.datasetname,
                basket_id=_maybe_int(row.get("basket_id")),
                basket_tid=row.get("basket_tid"),
                topicname=topic,
                total_predios=predio_counts.get(_maybe_int(row.get("basket_id")) or -1, 0),
                is_required=_is_required_basket_name(topic),
            )
        )

    return list(grouped.values())


@router.get("/{asignacion_id}/eventos", response_model=List[AsignacionEvento])
def listar_eventos_asignacion(
    asignacion_id: int,
    _user: dict = Depends(require_assignment_roles("admin", "coordinador", "digitalizador", "reconocedor")),
):
    with db_conn() as conn:
        asignaciones_repo.ensure_asignacion_tables(conn)
        asignacion = asignaciones_repo.get_asignacion_detalle(conn, asignacion_id)
        if not asignacion:
            raise HTTPException(status_code=404, detail="Asignacion no encontrada.")
        _ensure_assignment_owner_access(_user, asignacion)
        rows = asignaciones_repo.list_eventos_asignacion(conn, asignacion_id)
    return rows


@router.get("/{asignacion_id}/detalle", response_model=AsignacionDetalleResponse)
def obtener_detalle_asignacion(
    asignacion_id: int,
    _user: dict = Depends(require_assignment_roles("admin", "coordinador", "digitalizador", "reconocedor")),
):
    with db_conn() as conn:
        asignaciones_repo.ensure_asignacion_tables(conn)
        asignacion = asignaciones_repo.get_asignacion_detalle(conn, asignacion_id)
        if not asignacion:
            raise HTTPException(status_code=404, detail="Asignacion no encontrada.")
        _ensure_assignment_owner_access(_user, asignacion)
        predios_rows = asignaciones_repo.list_predios_asignacion(conn, asignacion_id)

    def _display_name(first_name: Optional[str], last_name: Optional[str], username: Optional[str]) -> Optional[str]:
        full_name = " ".join(part for part in (first_name, last_name) if part).strip()
        if full_name and username:
            return f"{full_name} ({username})"
        return full_name or username

    predios: List[AsignacionPredioDetalle] = []
    for row in predios_rows:
        predios.append(
            AsignacionPredioDetalle(
                id=row.get("id"),
                numero_predial_nacional=row.get("numero_predial_nacional") or "",
                predio_t_id=_maybe_int(row.get("predio_t_id")),
                activo=row.get("activo"),
                creado_por=row.get("creado_por"),
                creado_en=row.get("creado_en"),
            )
        )

    return AsignacionDetalleResponse(
        id=asignacion.get("id"),
        estado=asignacion.get("estado"),
        fecha_creacion=asignacion.get("creado_en"),
        coordinador=_display_name(
            asignacion.get("coord_first_name"),
            asignacion.get("coord_last_name"),
            asignacion.get("creado_por"),
        ),
        usuario_asignado=_display_name(
            asignacion.get("asignado_first_name"),
            asignacion.get("asignado_last_name"),
            asignacion.get("usuario_asignado"),
        ),
        titulo=asignacion.get("titulo"),
        observaciones=asignacion.get("observaciones"),
        datasetname_main=asignacion.get("datasetname_main"),
        work_datasetname=asignacion.get("work_datasetname"),
        error_msg=asignacion.get("error_msg"),
        total_asignados=int(asignacion.get("total_activos") or 0),
        total_eliminados=int(asignacion.get("total_inactivos") or 0),
        total_nuevos=int(asignacion.get("total_nuevos") or 0),
        predios=predios,
    )


@router.get("/{asignacion_id}/scope-geojson")
def obtener_scope_geojson_asignacion(
    asignacion_id: int,
    user: dict = Depends(require_assignment_roles("admin", "coordinador", "digitalizador", "reconocedor")),
):
    schema_work = _safe_ident(_read_schema_work(), fallback="b_asignaciones_arb")
    predio_numero_field = _safe_ident(
        (ASIG_MODEL_CONTEXT.predio_numero_field or "numero_predial").strip(),
        fallback="numero_predial",
    )

    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            asignaciones_repo.ensure_asignacion_tables(conn)
            cur.execute(
                """
                SELECT id, usuario_asignado, work_datasetname
                FROM arbimaps_app.asignacion
                WHERE id = %s
                LIMIT 1
                """,
                (asignacion_id,),
            )
            asignacion = cur.fetchone() or {}
            if not asignacion:
                raise HTTPException(status_code=404, detail="Asignacion no encontrada.")
            _ensure_assignment_owner_access(user, asignacion)

            work_datasetname = str(asignacion.get("work_datasetname") or "").strip()
            if not work_datasetname:
                raise HTTPException(
                    status_code=400,
                    detail="La asignacion no tiene workspace definido.",
                )

            predio_specs = _table_column_specs(cur, schema_work, "arb_predio")
            if not predio_specs:
                raise HTTPException(
                    status_code=404,
                    detail=f"No existe tabla arb_predio en {schema_work}.",
                )

            predio_geom_col = next(
                (
                    str(col.get("column_name") or "").strip()
                    for col in predio_specs
                    if str(col.get("udt_name") or "").strip().lower() in {"geometry", "geography"}
                ),
                None,
            )

            predio_geom_sql = (
                f'ST_AsGeoJSON(p.{_qident(predio_geom_col)})::json'
                if predio_geom_col
                else "NULL::json"
            )

            cur.execute(
                f"""
                WITH ap_sel AS (
                    SELECT DISTINCT
                        ap.predio_t_id,
                        NULLIF(BTRIM(ap.numero_predial_nacional::text), '') AS numero_predial_nacional
                    FROM arbimaps_app.asignacion_predio ap
                    WHERE ap.asignacion_id = %s
                      AND ap.activo IS DISTINCT FROM FALSE
                )
                SELECT DISTINCT ON (p."t_id")
                    p."t_id" AS predio_t_id,
                    b."t_id" AS basket_id,
                    BTRIM(p.{_qident(predio_numero_field)}::text) AS numero_predial_nacional,
                    {predio_geom_sql} AS geometry
                FROM {_qident(schema_work)}."arb_predio" p
                JOIN {_qident(schema_work)}."t_ili2db_basket" b
                  ON b."t_id" = p."t_basket"
                JOIN {_qident(schema_work)}."t_ili2db_dataset" d
                  ON d."t_id" = b."dataset"
                JOIN ap_sel ap
                  ON (
                        ap.predio_t_id IS NOT NULL
                    AND ap.predio_t_id = p."t_id"
                  )
                  OR (
                        ap.predio_t_id IS NULL
                    AND ap.numero_predial_nacional IS NOT NULL
                    AND ap.numero_predial_nacional = BTRIM(p.{_qident(predio_numero_field)}::text)
                  )
                WHERE d."datasetname" = %s
                ORDER BY p."t_id" ASC
                """,
                (asignacion_id, work_datasetname),
            )
            predio_rows = cur.fetchall() or []

            terrain_rows: list[dict] = []
            uc_rows: list[dict] = []
            basket_ids: list[int] = []
            cur.execute(
                f"""
                SELECT b."t_id"
                FROM {_qident(schema_work)}."t_ili2db_basket" b
                JOIN {_qident(schema_work)}."t_ili2db_dataset" d
                  ON d."t_id" = b."dataset"
                WHERE d."datasetname" = %s
                ORDER BY b."t_id" ASC
                """,
                (work_datasetname,),
            )
            basket_ids = [
                v
                for v in (_maybe_int((row or {}).get("t_id")) for row in (cur.fetchall() or []))
                if isinstance(v, int)
            ]

            terrain_specs = _table_column_specs(cur, schema_work, "arb_terreno")
            if terrain_specs:
                terrain_cols = {str(col.get("column_name") or "").strip() for col in terrain_specs}
                terrain_geom_col = next(
                    (
                        str(col.get("column_name") or "").strip()
                        for col in terrain_specs
                        if str(col.get("udt_name") or "").strip().lower() in {"geometry", "geography"}
                    ),
                    None,
                )
                if terrain_geom_col and "predio" in terrain_cols:
                    cur.execute(
                        f"""
                        WITH ap_sel AS (
                            SELECT DISTINCT
                                ap.predio_t_id,
                                NULLIF(BTRIM(ap.numero_predial_nacional::text), '') AS numero_predial_nacional
                            FROM arbimaps_app.asignacion_predio ap
                            WHERE ap.asignacion_id = %s
                              AND ap.activo IS DISTINCT FROM FALSE
                        )
                        SELECT
                            t."t_id" AS terreno_t_id,
                            t."predio" AS predio_t_id,
                            b."t_id" AS basket_id,
                            BTRIM(p.{_qident(predio_numero_field)}::text) AS numero_predial_nacional,
                            ST_AsGeoJSON(t.{_qident(terrain_geom_col)})::json AS geometry
                        FROM {_qident(schema_work)}."arb_terreno" t
                        JOIN {_qident(schema_work)}."arb_predio" p
                          ON p."t_id" = t."predio"
                        JOIN {_qident(schema_work)}."t_ili2db_basket" b
                          ON b."t_id" = p."t_basket"
                        JOIN {_qident(schema_work)}."t_ili2db_dataset" d
                          ON d."t_id" = b."dataset"
                        JOIN ap_sel ap
                          ON (
                                ap.predio_t_id IS NOT NULL
                            AND ap.predio_t_id = p."t_id"
                          )
                          OR (
                                ap.predio_t_id IS NULL
                            AND ap.numero_predial_nacional IS NOT NULL
                            AND ap.numero_predial_nacional = BTRIM(p.{_qident(predio_numero_field)}::text)
                          )
                        WHERE d."datasetname" = %s
                        ORDER BY t."t_id" ASC
                        """,
                        (asignacion_id, work_datasetname),
                    )
                    terrain_rows = cur.fetchall() or []

            uc_specs = _table_column_specs(cur, schema_work, "arb_unidadconstruccion")
            constru_specs = _table_column_specs(cur, schema_work, "arb_construccion")
            if uc_specs and constru_specs:
                uc_cols = {str(col.get("column_name") or "").strip() for col in uc_specs}
                constru_cols = {str(col.get("column_name") or "").strip() for col in constru_specs}
                uc_geom_col = next(
                    (
                        str(col.get("column_name") or "").strip()
                        for col in uc_specs
                        if str(col.get("udt_name") or "").strip().lower() in {"geometry", "geography"}
                    ),
                    None,
                )
                if uc_geom_col and "construccion" in uc_cols and "predio" in constru_cols:
                    cur.execute(
                        f"""
                        WITH ap_sel AS (
                            SELECT DISTINCT
                                ap.predio_t_id,
                                NULLIF(BTRIM(ap.numero_predial_nacional::text), '') AS numero_predial_nacional
                            FROM arbimaps_app.asignacion_predio ap
                            WHERE ap.asignacion_id = %s
                              AND ap.activo IS DISTINCT FROM FALSE
                        )
                        SELECT
                            uc."t_id" AS unidad_construccion_t_id,
                            uc."construccion" AS construccion_t_id,
                            c."predio" AS predio_t_id,
                            b."t_id" AS basket_id,
                            BTRIM(p.{_qident(predio_numero_field)}::text) AS numero_predial_nacional,
                            ST_AsGeoJSON(uc.{_qident(uc_geom_col)})::json AS geometry
                        FROM {_qident(schema_work)}."arb_unidadconstruccion" uc
                        JOIN {_qident(schema_work)}."arb_construccion" c
                          ON c."t_id" = uc."construccion"
                        JOIN {_qident(schema_work)}."arb_predio" p
                          ON p."t_id" = c."predio"
                        JOIN {_qident(schema_work)}."t_ili2db_basket" b
                          ON b."t_id" = p."t_basket"
                        JOIN {_qident(schema_work)}."t_ili2db_dataset" d
                          ON d."t_id" = b."dataset"
                        JOIN ap_sel ap
                          ON (
                                ap.predio_t_id IS NOT NULL
                            AND ap.predio_t_id = p."t_id"
                          )
                          OR (
                                ap.predio_t_id IS NULL
                            AND ap.numero_predial_nacional IS NOT NULL
                            AND ap.numero_predial_nacional = BTRIM(p.{_qident(predio_numero_field)}::text)
                          )
                        WHERE d."datasetname" = %s
                        ORDER BY uc."t_id" ASC
                        """,
                        (asignacion_id, work_datasetname),
                    )
                    uc_rows = cur.fetchall() or []

    predio_features = [
        {
            "type": "Feature",
            "geometry": row.get("geometry"),
            "properties": {
                "predio_t_id": _maybe_int(row.get("predio_t_id")),
                "basket_id": _maybe_int(row.get("basket_id")),
                "numero_predial_nacional": row.get("numero_predial_nacional"),
            },
        }
        for row in predio_rows
    ]

    terrain_features = [
        {
            "type": "Feature",
            "geometry": row.get("geometry"),
            "properties": {
                "terreno_t_id": _maybe_int(row.get("terreno_t_id")),
                "predio_t_id": _maybe_int(row.get("predio_t_id")),
                "basket_id": _maybe_int(row.get("basket_id")),
                "numero_predial_nacional": row.get("numero_predial_nacional"),
            },
        }
        for row in terrain_rows
        if row.get("geometry")
    ]

    uc_features = [
        {
            "type": "Feature",
            "geometry": row.get("geometry"),
            "properties": {
                "unidad_construccion_t_id": _maybe_int(row.get("unidad_construccion_t_id")),
                "construccion_t_id": _maybe_int(row.get("construccion_t_id")),
                "predio_t_id": _maybe_int(row.get("predio_t_id")),
                "basket_id": _maybe_int(row.get("basket_id")),
                "numero_predial_nacional": row.get("numero_predial_nacional"),
            },
        }
        for row in uc_rows
        if row.get("geometry")
    ]

    return {
        "asignacion_id": asignacion_id,
        "schema_work": schema_work,
        "work_datasetname": work_datasetname,
        "predios": {
            "type": "FeatureCollection",
            "features": predio_features,
        },
        "terrenos": {
            "type": "FeatureCollection",
            "features": terrain_features,
        },
        "unidades_construccion": {
            "type": "FeatureCollection",
            "features": uc_features,
        },
        "totals": {
            "predios": len(predio_features),
            "terrenos": len(terrain_features),
            "unidades_construccion": len(uc_features),
        },
        "basket_ids": basket_ids,
    }


@router.get("/{asignacion_id}/predios/{predio_t_id}/detalle-completo")
def obtener_detalle_predio_completo_asignacion(
    asignacion_id: int,
    predio_t_id: int,
    user: dict = Depends(require_assignment_roles("admin", "coordinador", "digitalizador", "reconocedor")),
):
    schema_work = _safe_ident(_read_schema_work(), fallback="b_asignaciones_arb")

    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            asignaciones_repo.ensure_asignacion_tables(conn)
            cur.execute(
                """
                SELECT
                    a.id,
                    a.usuario_asignado,
                    a.work_datasetname,
                    ap.activo,
                    ap.numero_predial_nacional
                FROM arbimaps_app.asignacion a
                JOIN arbimaps_app.asignacion_predio ap
                  ON ap.asignacion_id = a.id
                WHERE a.id = %s
                  AND ap.predio_t_id = %s
                LIMIT 1
                """,
                (asignacion_id, predio_t_id),
            )
            rel = cur.fetchone() or {}
            if not rel:
                raise HTTPException(
                    status_code=404,
                    detail="El predio no pertenece a la asignacion indicada.",
                )
            if rel.get("activo") is False:
                raise HTTPException(
                    status_code=404,
                    detail="El predio esta inactivo en la asignacion.",
                )
            _ensure_assignment_owner_access(user, rel)

            numero_predial_rel = str(rel.get("numero_predial_nacional") or "").strip()
            work_datasetname = str(rel.get("work_datasetname") or "").strip()
            predio_numero_field = _safe_ident(
                (ASIG_MODEL_CONTEXT.predio_numero_field or "numero_predial").strip(),
                fallback="numero_predial",
            )
            safe_schema = _safe_ident(schema_work, fallback="b_asignaciones_arb")

            predio_rows: list[dict] = []
            if numero_predial_rel and work_datasetname:
                predio_rows = _fetch_rows(
                    cur,
                    schema=safe_schema,
                    table="arb_predio",
                    where_sql=(
                        f'BTRIM(x.{_qident(predio_numero_field)}::text) = BTRIM(%s::text) '
                        f'AND EXISTS ('
                        f'  SELECT 1 '
                        f'  FROM {_qident(safe_schema)}."t_ili2db_basket" b '
                        f'  JOIN {_qident(safe_schema)}."t_ili2db_dataset" d '
                        f'    ON d."t_id" = b."dataset" '
                        f'  WHERE b."t_id" = x."t_basket" '
                        f'    AND d."datasetname" = %s'
                        f')'
                    ),
                    params=(numero_predial_rel, work_datasetname),
                    limit=1,
                )

            if not predio_rows and numero_predial_rel:
                predio_rows = _fetch_rows(
                    cur,
                    schema=safe_schema,
                    table="arb_predio",
                    where_sql=f'BTRIM(x.{_qident(predio_numero_field)}::text) = BTRIM(%s::text)',
                    params=(numero_predial_rel,),
                    limit=1,
                )

            if not predio_rows and numero_predial_rel:
                predio_rows = _fetch_rows(
                    cur,
                    schema=safe_schema,
                    table="arb_predio",
                    where_sql='BTRIM(x."numero_predial_anterior"::text) = BTRIM(%s::text)',
                    params=(numero_predial_rel,),
                    limit=1,
                )

            if not predio_rows:
                predio_rows = _fetch_rows(
                    cur,
                    schema=safe_schema,
                    table="arb_predio",
                    where_sql='x."t_id"::text = %s',
                    params=(str(predio_t_id),),
                    limit=1,
                )
            if not predio_rows:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"Predio {predio_t_id} no encontrado en {schema_work}. "
                        f"NPN asociado: {numero_predial_rel or '-'}."
                    ),
                )
            predio = dict(predio_rows[0] or {})
            workspace_predio_t_id = _maybe_int(_first_non_empty(predio, "t_id")) or predio_t_id
            numero_predial = _first_non_empty(predio, "numero_predial_nacional", "numero_predial")
            if numero_predial and not predio.get("numero_predial_nacional"):
                predio["numero_predial_nacional"] = str(numero_predial)

            # Resolver dominios para evitar exponer codigos crudos (ej: 863).
            condicion_predio_raw = _first_non_empty(predio, "condicion_predio")
            predio["condicion_predio_nombre"] = _resolve_domain_name(
                cur,
                schema=schema_work,
                table_candidates=[
                    "arb_condicionprediotipo",
                    "ilc_condicionprediotipo",
                    "col_condicionprediotipo",
                ],
                raw_value=condicion_predio_raw,
            ) or _first_non_empty(predio, "condicion_predio_nombre", "condicion_predio")

            tipo_predio_raw = _first_non_empty(predio, "tipo_predio", "tipo")
            predio["tipo_predio_nombre"] = _resolve_domain_name(
                cur,
                schema=schema_work,
                table_candidates=[
                    "arb_prediotipo",
                    "ilc_prediotipo",
                    "col_prediotipo",
                ],
                raw_value=tipo_predio_raw,
            ) or _first_non_empty(predio, "tipo_predio_nombre", "tipo_predio", "tipo")

            destinacion_raw = _first_non_empty(predio, "destinacion_economica")
            predio["destinacion_economica_nombre"] = _resolve_domain_name(
                cur,
                schema=schema_work,
                table_candidates=[
                    "arb_destinacioneconomicatipo",
                    "ilc_destinacioneconomicatipo",
                    "col_destinacioneconomicatipo",
                ],
                raw_value=destinacion_raw,
            ) or _first_non_empty(
                predio,
                "destinacion_economica_nombre",
                "destinacion_economica",
            )

            estado_fmi_raw = _first_non_empty(predio, "estado_fmi")
            predio["estado_fmi_nombre"] = _resolve_domain_name(
                cur,
                schema=schema_work,
                table_candidates=[
                    "arb_estadofmitipo",
                    "ilc_estadofmitipo",
                ],
                raw_value=estado_fmi_raw,
            ) or _first_non_empty(predio, "estado_fmi_nombre", "estado_fmi")

            direcciones = _fetch_rows(
                cur,
                schema=schema_work,
                table="arb_direccion",
                where_sql='x."arb_predio_direccion"::text = %s',
                params=(str(workspace_predio_t_id),),
                order_sql='x."t_id" ASC',
            )

            datos_adicionales = _fetch_rows_by_fk_candidates(
                cur,
                schema=schema_work,
                table_candidates=[
                    "arb_datosadicionaleslevantamientocatastral",
                    "ilc_datosadicionaleslevantamientocatastral",
                ],
                fk_candidates=["predio", "ilc_predio", "arb_predio", "predio_id"],
                fk_value=workspace_predio_t_id,
            )
            for row in datos_adicionales:
                resultado_visita_raw = _first_non_empty(row, "resultado_visita")
                row["resultado_visita_nombre"] = _resolve_domain_name(
                    cur,
                    schema=schema_work,
                    table_candidates=[
                        "arb_resultadovisitatipo",
                        "ilc_resultadovisitatipo",
                    ],
                    raw_value=resultado_visita_raw,
                ) or _first_non_empty(row, "resultado_visita_nombre", "resultado_visita")
            datos_adicionales_ids = [
                _first_non_empty(row, "t_id") for row in datos_adicionales if _first_non_empty(row, "t_id") is not None
            ]

            contacto_visita = _fetch_rows_by_fk_candidates(
                cur,
                schema=schema_work,
                table_candidates=["arb_contactovisita", "ilc_contactovisita"],
                fk_candidates=["predio", "ilc_predio", "arb_predio", "predio_id"],
                fk_value=workspace_predio_t_id,
            )
            if not contacto_visita and datos_adicionales_ids:
                contacto_visita = _fetch_rows_by_fk_any_candidates(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_contactovisita", "ilc_contactovisita"],
                    fk_candidates=[
                        "datos_adicionales",
                        "ilc_datos_adicionales",
                        "arb_datos_adicionales",
                        "datos_adicionales_id",
                    ],
                    fk_values=datos_adicionales_ids,
                )

            novedad_fmi = _fetch_rows_by_fk_candidates(
                cur,
                schema=schema_work,
                table_candidates=["arb_novedadfmi", "ilc_novedadfmi"],
                fk_candidates=["predio", "ilc_predio", "arb_predio", "predio_id"],
                fk_value=workspace_predio_t_id,
            )
            if not novedad_fmi and datos_adicionales_ids:
                novedad_fmi = _fetch_rows_by_fk_any_candidates(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_novedadfmi", "ilc_novedadfmi"],
                    fk_candidates=[
                        "datos_adicionales",
                        "ilc_dtsdcnltmntctstral_novedad_fmi",
                        "ilc_datos_adicionales",
                        "arb_datos_adicionales",
                    ],
                    fk_values=datos_adicionales_ids,
                )

            estructura_novedad_np = []
            if numero_predial:
                estructura_novedad_np = _fetch_rows_by_fk_candidates(
                    cur,
                    schema=schema_work,
                    table_candidates=[
                        "arb_estructuranovedadnumeropredial",
                        "ilc_estructuranovedadnumeropredial",
                    ],
                    fk_candidates=["numero_predial", "numero_predial_nacional"],
                    fk_value=numero_predial,
                )

            construcciones = _fetch_rows(
                cur,
                schema=schema_work,
                table="arb_construccion",
                where_sql='x."predio"::text = %s',
                params=(str(workspace_predio_t_id),),
                order_sql='x."t_id" ASC',
            )
            construccion_by_id: dict[str, dict] = {}
            for cons in construcciones:
                cons_id = _first_non_empty(cons, "t_id")
                if cons_id is not None:
                    construccion_by_id[str(cons_id)] = cons
                cons["numero_predial_nacional"] = numero_predial
                tipo_cons_val = _first_non_empty(cons, "tipo_construccion")
                cons["tipo_construccion_nombre"] = _resolve_domain_name(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_tipoconstrucciontipo"],
                    raw_value=tipo_cons_val,
                ) or _first_non_empty(cons, "tipo_construccion_nombre", "tipo_construccion")
                estado_cons_val = _first_non_empty(cons, "estado_construccion")
                cons["estado_construccion_nombre"] = _resolve_domain_name(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_estadoconstrucciontipo"],
                    raw_value=estado_cons_val,
                ) or _first_non_empty(cons, "estado_construccion_nombre", "estado_construccion")

            construccion_ids = [str(c.get("t_id")) for c in construcciones if c.get("t_id") is not None]
            unidades: list[dict] = []
            if construccion_ids:
                unidades = _fetch_rows(
                    cur,
                    schema=schema_work,
                    table="arb_unidadconstruccion",
                    where_sql='x."construccion"::text = ANY(%s::text[])',
                    params=(construccion_ids,),
                    order_sql='x."t_id" ASC',
                )

            caracteristica_ids = list(
                {
                    str(_first_non_empty(u, "caracteristicasunidadconstruccion"))
                    for u in unidades
                    if _first_non_empty(u, "caracteristicasunidadconstruccion") is not None
                }
            )
            caracteristicas_map: dict[str, dict] = {}
            if caracteristica_ids:
                caracteristicas_rows = _fetch_rows(
                    cur,
                    schema=schema_work,
                    table="arb_caracteristicasunidadconstruccion",
                    where_sql='x."t_id"::text = ANY(%s::text[])',
                    params=(caracteristica_ids,),
                )
                for row in caracteristicas_rows:
                    rid = _first_non_empty(row, "t_id")
                    if rid is not None:
                        caracteristicas_map[str(rid)] = row

            unidades_enriquecidas: list[dict] = []
            for unidad in unidades:
                unidad = dict(unidad)
                construccion_id = _first_non_empty(unidad, "construccion", "construccion_id", "cr_construccion")
                cons = construccion_by_id.get(str(construccion_id)) if construccion_id is not None else None
                caracteristica_id = _first_non_empty(unidad, "caracteristicasunidadconstruccion")
                caracteristica = (
                    caracteristicas_map.get(str(caracteristica_id))
                    if caracteristica_id is not None
                    else None
                )

                unidad["construccion_id"] = construccion_id
                unidad["construccion_identificador"] = (
                    _first_non_empty(cons or {}, "identificador", "codigo", "t_ili_tid")
                    or (f"CONS-{construccion_id}" if construccion_id is not None else None)
                )
                unidad["construccion_codigo"] = _first_non_empty(cons or {}, "codigo", "identificador")
                unidad["numero_predial_nacional"] = numero_predial
                unidad["caracteristica_identificador"] = _first_non_empty(
                    caracteristica or {},
                    "identificador",
                )

                unidad["tipo_construccion_nombre"] = (
                    _first_non_empty(cons or {}, "tipo_construccion_nombre")
                    or _first_non_empty(cons or {}, "tipo_construccion")
                    or "Construccion"
                )
                unidad["tipo_calificacion_clase"] = unidad["tipo_construccion_nombre"]
                unidad["tipo_calificacion_resumen"] = unidad["tipo_construccion_nombre"]

                unidad["tipo_planta_nombre"] = _resolve_domain_name(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_construccionplantatipo"],
                    raw_value=_first_non_empty(unidad, "tipo_planta"),
                ) or _first_non_empty(unidad, "tipo_planta_nombre", "tipo_planta")

                unidad["relacion_superficie_nombre"] = _resolve_domain_name(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_relacionsuperficietipo", "col_relacionsuperficietipo"],
                    raw_value=_first_non_empty(unidad, "relacion_superficie"),
                ) or _first_non_empty(unidad, "relacion_superficie_nombre", "relacion_superficie")

                unidad["estado_unidad_construccion_nombre"] = _resolve_domain_name(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_estadoconstrucciontipo"],
                    raw_value=_first_non_empty(unidad, "estado_unidad_construccion"),
                ) or _first_non_empty(
                    unidad,
                    "estado_unidad_construccion_nombre",
                    "estado_unidad_construccion",
                )

                tipo_uc_val = _first_non_empty(
                    caracteristica or {},
                    "tipo_unidad_construccion",
                )
                unidad["tipo_unidad_construccion_nombre"] = _resolve_domain_name(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_unidadconstrucciontipo"],
                    raw_value=tipo_uc_val,
                ) or _first_non_empty(
                    unidad,
                    "tipo_unidad_construccion_nombre",
                    "tipo_unidad_construccion",
                )
                unidades_enriquecidas.append(unidad)

            derechos_rows = _fetch_rows(
                cur,
                schema=schema_work,
                table="arb_derechointeresadofuente",
                where_sql='x."predio"::text = %s',
                params=(str(workspace_predio_t_id),),
                order_sql='x."t_id" ASC',
            )
            if not derechos_rows:
                derechos_rows = _fetch_rows_by_fk_candidates(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_derecho", "ilc_derecho"],
                    fk_candidates=["predio", "unidad", "baunit", "predio_id"],
                    fk_value=workspace_predio_t_id,
                )

            derecho_ids = [
                _first_non_empty(row, "t_id", "derecho_id")
                for row in derechos_rows
                if _first_non_empty(row, "t_id", "derecho_id") is not None
            ]
            rrr_interesado = _fetch_rows_by_fk_any_candidates(
                cur,
                schema=schema_work,
                table_candidates=["col_rrrinteresado", "arb_rrrinteresado"],
                fk_candidates=["rrr", "derecho", "derecho_id"],
                fk_values=derecho_ids,
            )
            
            tramites = _fetch_rows(
                cur,
                schema=schema_work,
                table="arb_tramite",
                where_sql='x."predio"::text = %s',
                params=(str(workspace_predio_t_id),),
                order_sql='x."t_id" ASC',
            )

            marcas = _fetch_rows(
                cur,
                schema=schema_work,
                table="arb_marca",
                where_sql='x."predio"::text = %s',
                params=(str(workspace_predio_t_id),),
                order_sql='x."t_id" ASC',
            )

            puntos_referencia = _fetch_rows(
                cur,
                schema=schema_work,
                table="arb_puntoreferencia",
                where_sql='x."predio"::text = %s',
                params=(str(workspace_predio_t_id),),
                order_sql='x."t_id" ASC',
            )

            novedad_numero_predial_valor = _fetch_rows_by_fk_candidates(
                cur,
                schema=schema_work,
                table_candidates=["arb_novedadnumeropredialvalor"],
                fk_candidates=["arb_predio_novedad_numero_predial", "predio"],
                fk_value=workspace_predio_t_id,
                order_sql='x."t_id" ASC',
            )

            novedad_fmi_valor = _fetch_rows_by_fk_candidates(
                cur,
                schema=schema_work,
                table_candidates=["arb_novedadfmivalor"],
                fk_candidates=["arb_predio_novedad_fmi", "predio"],
                fk_value=workspace_predio_t_id,
                order_sql='x."t_id" ASC',
            )

            referencias_registrales = _fetch_rows_by_fk_candidates(
                cur,
                schema=schema_work,
                table_candidates=["arb_referenciaregistralsistemaantiguovalor"],
                fk_candidates=["arb_predio_referencia_registral_sistema_antiguo", "predio"],
                fk_value=workspace_predio_t_id,
                order_sql='x."t_id" ASC',
            )

            interesados: list[dict] = []
            fuentes_admin: list[dict] = []

            for d in derechos_rows:
                item = dict(d)
                item["numero_predial_nacional"] = numero_predial
                item["primer_nombre"] = _first_non_empty(item, "primer_nombre", "i_primer_nombre")
                item["segundo_nombre"] = _first_non_empty(item, "segundo_nombre", "i_segundo_nombre")
                item["primer_apellido"] = _first_non_empty(item, "primer_apellido", "i_primer_apellido")
                item["segundo_apellido"] = _first_non_empty(item, "segundo_apellido", "i_segundo_apellido")
                item["razon_social"] = _first_non_empty(item, "razon_social", "i_razon_social")
                item["documento_identidad"] = _first_non_empty(
                    item,
                    "documento_identidad",
                    "i_documento_identidad",
                )
                item["cuota_participacion"] = _first_non_empty(
                    item,
                    "cuota_participacion",
                    "d_cuota_participacion",
                    "fraccion",
                    "d_fraccion",
                )
                item["telefono"] = _first_non_empty(item, "telefono", "i_telefono")
                item["correo_electronico"] = _first_non_empty(
                    item,
                    "correo_electronico",
                    "i_correo_electronico",
                )
                item["direccion_residencia"] = _first_non_empty(
                    item,
                    "direccion_residencia",
                    "i_direccion_residencia",
                )
                item["domicilio_notificacion"] = _first_non_empty(
                    item,
                    "domicilio_notificacion",
                    "i_domicilio_notificacion",
                )
                item["autoriza_notificacion_correo"] = _first_non_empty(
                    item,
                    "autoriza_notificacion_correo",
                    "i_autoriza_notificacion_correo",
                )
                item["autorreconocimiento_etnico"] = _first_non_empty(
                    item,
                    "autorreconocimiento_etnico",
                    "i_autorreconocimiento_etnico",
                )
                item["autorreconocimiento_campesino"] = _first_non_empty(
                    item,
                    "autorreconocimiento_campesino",
                    "i_autorreconocimiento_campesino",
                )
                item["departamento_nombre"] = _first_non_empty(
                    item,
                    "departamento_nombre",
                    "i_departamento_nombre",
                    "i_departamento",
                )
                item["municipio_nombre"] = _first_non_empty(
                    item,
                    "municipio_nombre",
                    "i_municipio_nombre",
                    "i_municipio",
                )
                nombre_completo = _build_full_name(item)
                if nombre_completo:
                    item["nombre_completo"] = nombre_completo

                d_tipo = _first_non_empty(item, "d_tipo", "tipo_derecho", "tipo")
                fa_tipo = _first_non_empty(item, "fa_tipo", "tipo_fuente_administrativa")
                i_tipo_doc = _first_non_empty(item, "i_tipo_documento", "tipo_documento")
                i_tipo = _first_non_empty(item, "i_tipo", "tipo_persona")
                i_grupo = _first_non_empty(item, "i_grupo_etnico", "grupo_etnico")
                i_naturaleza = _first_non_empty(item, "naturaleza_juridica", "i_naturaleza_juridica")
                i_codigo_nat = _first_non_empty(item, "codigo_naturaleza_juridica", "i_codigo_naturaleza_juridica")
                i_sexo = _first_non_empty(item, "i_sexo", "sexo")
                i_estado_disp = _first_non_empty(item, "estado_disponibilidad")

                item["tipo_derecho"] = d_tipo
                item["tipo_derecho_nombre"] = _resolve_domain_name(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_derechotipo"],
                    raw_value=d_tipo,
                ) or _first_non_empty(item, "tipo_derecho_nombre")

                item["tipo_fuente_administrativa"] = fa_tipo
                item["tipo_fuente_administrativa_nombre"] = _resolve_domain_name(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_fuenteadministrativatipo"],
                    raw_value=fa_tipo,
                ) or _first_non_empty(item, "tipo_fuente_administrativa_nombre")

                item["tipo_documento_nombre"] = _resolve_domain_name(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_interesadodocumentotipo"],
                    raw_value=i_tipo_doc,
                ) or _first_non_empty(item, "tipo_documento_nombre")

                item["tipo_persona"] = i_tipo
                item["tipo_persona_nombre"] = _resolve_domain_name(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_interesadotipo"],
                    raw_value=i_tipo,
                ) or _first_non_empty(item, "tipo_persona_nombre")

                item["grupo_etnico_nombre"] = _resolve_domain_name(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_grupoetnicotipo"],
                    raw_value=i_grupo,
                ) or _first_non_empty(item, "grupo_etnico_nombre")

                item["naturaleza_juridica_nombre"] = _resolve_domain_name(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_naturalezajuridicatipo"],
                    raw_value=i_naturaleza,
                ) or _first_non_empty(item, "naturaleza_juridica_nombre")

                item["codigo_naturaleza_juridica_nombre"] = _resolve_domain_name(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_codigonaturalezajuridicatipo"],
                    raw_value=i_codigo_nat,
                ) or _first_non_empty(item, "codigo_naturaleza_juridica_nombre")
                item["codigo_naturaleza_juridica"] = _first_non_empty(
                    item,
                    "codigo_naturaleza_juridica",
                    "i_codigo_naturaleza_juridica",
                )

                item["sexo_nombre"] = _resolve_domain_name(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_sexotipo"],
                    raw_value=i_sexo,
                ) or _first_non_empty(item, "sexo_nombre", "sexo")

                item["estado_disponibilidad_nombre"] = _resolve_domain_name(
                    cur,
                    schema=schema_work,
                    table_candidates=["arb_estadodisponibilidadtipo", "col_estadodisponibilidadtipo"],
                    raw_value=i_estado_disp,
                ) or _first_non_empty(item, "estado_disponibilidad_nombre", "estado_disponibilidad")

                item["fecha_inicio_tenencia"] = _first_non_empty(
                    item,
                    "fecha_inicio_tenencia",
                    "d_fecha_inicio_tenencia",
                )
                item["posesion_ancestral_tradicional"] = _first_non_empty(
                    item,
                    "posesion_ancestral_tradicional",
                    "d_posesion_ancestral_tradicional",
                )
                item["descripcion_derecho"] = _first_non_empty(item, "descripcion_derecho", "d_descripcion")
                item["descripcion_fuente"] = _first_non_empty(
                    item,
                    "descripcion_fuente",
                    "fa_descripcion",
                    "descripcion_fuente_administrativa",
                )
                item["observacion_fuente_administrativa"] = _first_non_empty(
                    item,
                    "observacion_fuente_administrativa",
                    "fa_observacion",
                )
                item["numero_fuente"] = _first_non_empty(item, "numero_fuente", "fa_numero_fuente")
                item["ente_emisor"] = _first_non_empty(item, "ente_emisor", "fa_ente_emisor")
                item["oficina_origen"] = _first_non_empty(item, "oficina_origen", "fa_oficina_origen")
                item["nombre_escritura"] = _first_non_empty(item, "nombre_escritura", "fa_nombre_escritura")
                item["ciudad_origen"] = _first_non_empty(item, "ciudad_origen", "fa_ciudad_origen")

                interesados.append(item)
                fuentes_admin.append(
                    {
                        "tipo_fuente_administrativa_nombre": item.get("tipo_fuente_administrativa_nombre"),
                        "numero_fuente": item.get("numero_fuente"),
                        "ente_emisor": item.get("ente_emisor"),
                        "oficina_origen": item.get("oficina_origen"),
                        "nombre_escritura": item.get("nombre_escritura"),
                        "ciudad_origen": item.get("ciudad_origen"),
                        "estado_disponibilidad_nombre": item.get("estado_disponibilidad_nombre"),
                        "descripcion_fuente": item.get("descripcion_fuente"),
                        "observacion_fuente_administrativa": item.get("observacion_fuente_administrativa"),
                    }
                )

            for cons in construcciones:
                cons_id = cons.get("t_id")
                cons["unidades"] = [
                    u for u in unidades_enriquecidas if str(u.get("construccion_id")) == str(cons_id)
                ]

    return {
        "predio": predio,
        "direcciones": direcciones,
        "construcciones": construcciones,
        "unidades_construccion": unidades_enriquecidas,
        "interesados": interesados,
        "derechos": derechos_rows,
        "fuente_administrativa": fuentes_admin,
        "uebaunit": [],
        "novedad_fmi": novedad_fmi,
        "datos_adicionales": datos_adicionales,
        "estructura_novedad_np": estructura_novedad_np,
        "contacto_visita": contacto_visita,
        "rrr_interesado": rrr_interesado,
        "tramites": tramites,
        "marcas": marcas,
        "puntos_referencia": puntos_referencia,
        "novedad_numero_predial_valor": novedad_numero_predial_valor,
        "novedad_fmi_valor": novedad_fmi_valor,
        "referencias_registrales": referencias_registrales,
        "schema_work": schema_work,
    }


def _procesar_retorno_xtf(
    asignacion_id: int,
    archivo: UploadFile,
    user: dict,
    *,
    publish_to_main: bool,
) -> dict:
    role = str((user or {}).get("role") or (user or {}).get("rol") or (user or {}).get("role_code") or "").strip().lower()
    if role in {"digitalizador", "reconocedor"}:
        publish_to_main = False

    if not archivo.filename:
        raise HTTPException(status_code=400, detail="Debes cargar un archivo XTF.")
    if not archivo.filename.lower().endswith(".xtf"):
        raise HTTPException(status_code=400, detail="El archivo debe tener extension .xtf.")

    try:
        with db_conn() as conn:
            asignacion = asignaciones_repo.get_asignacion_work_dataset(conn, asignacion_id)
    except Exception as exc:
        _raise_http_from_export_error(exc, stage="read_assignment")

    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignacion no encontrada.")

    work_dataset = (asignacion.get("work_datasetname") or "").strip()
    if not work_dataset:
        raise HTTPException(status_code=400, detail="La asignacion no tiene workspace definido.")

    usuario_log = user.get("username") if isinstance(user, dict) else None
    correlation_id = _retorno_correlation_id(asignacion_id)
    work_dataset = _ensure_workspace_ready_for_export(asignacion_id, usuario_log)
    try:
        with db_conn() as conn_cleanup:
            cleanup_result = workspace_service.cleanup_orphan_workspace_datasets(
                conn_cleanup,
                _read_schema_work(),
                limit=25,
            )
            conn_cleanup.commit()
        _log_sync_event(
            "workspace_orphan_cleanup",
            correlation_id=correlation_id,
            asignacion_id=asignacion_id,
            retorno_id=None,
            retorno_dataset=None,
            stage="pre_sync_cleanup",
            status="ok",
            extra=cleanup_result,
        )
    except Exception as cleanup_exc:
        logger.warning("orphan workspace cleanup skipped for asignacion_id=%s: %s", asignacion_id, cleanup_exc)

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xtf")
    tmp_path = tmp_file.name
    tmp_file.close()
    step_start = time.monotonic()

    retorno_id: Optional[int] = None
    retorno_version: Optional[int] = None
    retorno_dataset: Optional[str] = None
    removed_predios = 0
    removed_assignment_predios = 0
    removed_assignment_preview: List[str] = []
    synced_predios = 0
    predios_nuevos_sync = 0
    synced_predios_preview: List[str] = []
    coverage_result = {
        "expected_predios": 0,
        "covered_predios": 0,
        "missing_predios": 0,
        "missing_predios_preview": [],
    }
    archivo_sha256 = ""
    xtf_validation_result: Optional[dict] = None
    stage = "init"
    pending_events: List[Tuple[str, str, Optional[str]]] = []

    try:
        stage = "write_tmp_xtf"
        archivo_sha256 = _copy_upload_and_sha256(archivo, tmp_path)
        _log_sync_event(
            "retorno_xtf_written",
            correlation_id=correlation_id,
            asignacion_id=asignacion_id,
            retorno_id=retorno_id,
            retorno_dataset=retorno_dataset,
            stage=stage,
            status="ok",
            duration_ms=int((time.monotonic() - step_start) * 1000),
            extra={
                "archivo_sha256": archivo_sha256,
                "filename": archivo.filename,
                "publish_to_main": publish_to_main,
            },
        )

        stage = "create_retorno_record"
        with db_conn() as conn:
            conn.autocommit = False
            try:
                asignaciones_repo.ensure_asignacion_tables(conn)
                existente = asignaciones_repo.get_recent_retorno_by_sha256(conn, asignacion_id, archivo_sha256)
                if existente:
                    existing_id = _maybe_int(existente.get("id"))
                    existing_status = str(existente.get("estado") or "").strip().upper()
                    if existing_id is not None and existing_status in {"SINCRONIZADO", "VALIDADO", "CARGADO"}:
                        raise HTTPException(
                            status_code=409,
                            detail=(
                                "El archivo XTF ya fue procesado recientemente para esta asignacion. "
                                f"retorno_id={existing_id}, estado={existing_status}."
                            ),
                        )
                retorno_version = asignaciones_repo.allocate_asignacion_retorno_version(conn, asignacion_id)
                if publish_to_main:
                    retorno_dataset = _build_retorno_datasetname(work_dataset, retorno_version)
                else:
                    retorno_dataset = work_dataset
                retorno_row = asignaciones_repo.create_asignacion_retorno(
                    conn,
                    asignacion_id,
                    retorno_version,
                    retorno_dataset,
                    archivo_nombre_original=archivo.filename,
                    archivo_nombre_guardado=f"{retorno_dataset}.xtf",
                    archivo_sha256=archivo_sha256,
                    correlation_id=correlation_id,
                    creado_por=usuario_log,
                )
                retorno_id = _maybe_int(retorno_row.get("id"))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        stage = "validate_xtf_rules"
        xtf_validation_result = _validate_retorno_xtf_rules(tmp_path)

        stage = "sync_pipeline"
        with db_conn() as conn:
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", (asignacion_id,))

                target_dataset = retorno_dataset or work_dataset
                if not publish_to_main:
                    stage = "replace_workspace_dataset"
                    workspace_service.remove_workspace_dataset(
                        conn,
                        work_dataset,
                        _read_schema_work(),
                    )

                stage = "ili2pg_import"
                _ili2pg_import(_read_schema_work(), target_dataset, tmp_path)

                stage = "prune_workspace_predios"
                removed_predios = workspace_service.prune_workspace_predios(
                    conn,
                    asignacion_id,
                    target_dataset,
                    _read_schema_work(),
                    keep_new_informal_predios=True,
                )
                if removed_predios > 0:
                    raise export_service.ExportServiceError(
                        status_code=409,
                        detail=(
                            f"El retorno contiene {removed_predios} predio(s) no autorizados o ajenos a la "
                            "asignacion. Limpie la canasta de trabajo en campo antes de sincronizar."
                        ),
                    )
                stage = "validate_workspace_dataset_health"
                workspace_service.validate_workspace_dataset_health(
                    _read_schema_work(),
                    target_dataset,
                    conn=conn,
                )
                stage = "validate_workspace_assignment_coverage"
                allow_missing_predios = _allow_retorno_sync_with_missing_predios()
                coverage_result = workspace_service.validate_workspace_assignment_coverage(
                    asignacion_id,
                    _read_schema_work(),
                    target_dataset,
                    conn=conn,
                    allow_missing_predios=allow_missing_predios,
                )

                removed_assignment_predios = int(coverage_result.get("missing_predios") or 0)
                removed_assignment_preview = [
                    str(item).strip()
                    for item in (coverage_result.get("missing_predios_preview") or [])
                    if item is not None and str(item).strip()
                ]
                if removed_assignment_predios > 0 and allow_missing_predios:
                    stage = "mark_missing_assignment_predios_inactive"
                    deactivation_result = workspace_service.mark_missing_assignment_predios_inactive(
                        conn,
                        asignacion_id,
                        _read_schema_work(),
                        target_dataset,
                    )
                    removed_assignment_predios = int(
                        deactivation_result.get("deactivated_predios") or removed_assignment_predios
                    )
                    removed_assignment_preview = [
                        str(item).strip()
                        for item in (deactivation_result.get("preview_predios") or [])
                        if item is not None and str(item).strip()
                    ]
                    stage = "validate_workspace_assignment_coverage_post_deactivate"
                    coverage_result = workspace_service.validate_workspace_assignment_coverage(
                        asignacion_id,
                        _read_schema_work(),
                        target_dataset,
                        conn=conn,
                        allow_missing_predios=False,
                    )
                elif removed_assignment_predios > 0:
                    raise export_service.ExportServiceError(
                        status_code=409,
                        detail=(
                            f"Cobertura de retorno incompleta para sincronizar: "
                            f"{coverage_result.get('covered_predios', 0)}/"
                            f"{coverage_result.get('expected_predios', 0)} predios activos."
                        ),
                    )

                if retorno_id is not None:
                    stage = "update_retorno_validado"
                    removed_assignment_text = (
                        f" Predios eliminados detectados en retorno: {removed_assignment_predios}."
                        if removed_assignment_predios > 0
                        else " Predios eliminados detectados en retorno: 0."
                    )
                    validation_stage_text = (
                        "Dataset temporal validado antes de sincronizar a main. "
                        if publish_to_main
                        else "Workspace validado antes de registrar sincronizacion local. "
                    )
                    asignaciones_repo.update_asignacion_retorno(
                        conn,
                        retorno_id,
                        estado="VALIDADO",
                        resultado_validacion=(
                            f"Validacion XTF previa: {_xtf_validation_note(xtf_validation_result)}. "
                            f"{validation_stage_text}"
                            f"Cobertura {coverage_result.get('covered_predios', 0)}/"
                            f"{coverage_result.get('expected_predios', 0)} predios activos."
                            f"{removed_assignment_text}"
                        ),
                        removed_predios=removed_predios,
                        error_msg=None,
                    )

                if publish_to_main:
                    stage = "sync_workspace_predios_to_main"
                    synced_predios = workspace_service.sync_workspace_predios_to_main(
                        conn,
                        asignacion_id,
                        target_dataset,
                        _read_schema_main(),
                        _read_schema_work(),
                        effective_role=role,
                    )
                    with conn.cursor() as cur:
                        cur.execute("SELECT to_regclass('pg_temp._arb_sync_predio_map')")
                        has_sync_map = bool((cur.fetchone() or [None])[0])
                    if has_sync_map:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                SELECT numero_predial_nacional
                                FROM _arb_sync_predio_map
                                ORDER BY numero_predial_nacional
                                LIMIT 10
                                """
                            )
                            synced_predios_preview = [
                                str(row[0]).strip() for row in (cur.fetchall() or []) if row and row[0]
                            ]
                    else:
                        synced_predios_preview = []

                    with conn.cursor() as cur:
                        cur.execute("SELECT to_regclass('pg_temp._arb_sync_selected_predio')")
                        has_sync_scope = bool((cur.fetchone() or [None])[0])
                        if has_sync_scope:
                            cur.execute(
                                """
                                SELECT COUNT(*)
                                FROM _arb_sync_selected_predio sp
                                WHERE NOT EXISTS (
                                    SELECT 1
                                    FROM arbimaps_app.asignacion_predio ap
                                    WHERE ap.asignacion_id = %s
                                      AND ap.activo IS DISTINCT FROM FALSE
                                      AND BTRIM(ap.numero_predial_nacional::text) =
                                          BTRIM(sp.numero_predial_nacional::text)
                                )
                                """,
                                (asignacion_id,),
                            )
                            predios_nuevos_sync = int((cur.fetchone() or [0])[0] or 0)
                        else:
                            expected_predios_scope = int(coverage_result.get("expected_predios") or 0)
                            predios_nuevos_sync = max(int(synced_predios or 0) - expected_predios_scope, 0)
                        cur.execute(
                            """
                            UPDATE arbimaps_app.asignacion
                            SET predios_soporte_extra = %s
                            WHERE id = %s
                            """
                            ,
                            (predios_nuevos_sync, asignacion_id),
                        )
                else:
                    stage = "refresh_workspace_predio_ids"
                    workspace_service.actualizar_predio_ids_desde_workspace(
                        asignacion_id,
                        _read_schema_work(),
                        conn=conn,
                    )
                    work_schema_sql = _qident(_read_schema_work())
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            UPDATE arbimaps_app.asignacion
                            SET predios_soporte_extra = GREATEST(
                                (
                                    SELECT COUNT(DISTINCT BTRIM(p.numero_predial::text))
                                    FROM {work_schema_sql}.arb_predio p
                                    JOIN {work_schema_sql}.t_ili2db_basket b
                                      ON b.t_id = p.t_basket
                                    JOIN {work_schema_sql}.t_ili2db_dataset d
                                      ON d.t_id = b.dataset
                                    WHERE d.datasetname = %s
                                ) - %s,
                                0
                            )
                            , estado = 'PENDIENTE_PUBLICACION'
                            WHERE id = %s
                            """,
                            (
                                target_dataset,
                                int(coverage_result.get("covered_predios") or 0),
                                asignacion_id,
                            ),
                        )

                if retorno_id is not None:
                    stage = "update_retorno_sincronizado"
                    preview_text = (
                        f" Muestra predios sincronizados: {', '.join(synced_predios_preview)}."
                        if publish_to_main and synced_predios_preview
                        else ""
                    )
                    removed_assignment_text = (
                        f" Predios eliminados detectados en retorno: {removed_assignment_predios}."
                        if removed_assignment_predios > 0
                        else " Predios eliminados detectados en retorno: 0."
                    )
                    asignaciones_repo.update_asignacion_retorno(
                        conn,
                        retorno_id,
                        estado="SINCRONIZADO",
                        resultado_validacion=(
                            (
                                "Retorno validado y sincronizado al schema principal. "
                                f"Validacion XTF: {_xtf_validation_note(xtf_validation_result)}. "
                                f"Cobertura {coverage_result.get('covered_predios', 0)}/"
                                f"{coverage_result.get('expected_predios', 0)}. "
                                f"Sincronizados {synced_predios} predio(s). "
                                f"Removidos {removed_predios} no asignados."
                                f"{removed_assignment_text}"
                                f"{preview_text}"
                            )
                            if publish_to_main
                            else (
                                "Retorno validado y sincronizado en workspace; pendiente publicacion a main. "
                                f"Validacion XTF: {_xtf_validation_note(xtf_validation_result)}. "
                                f"Cobertura {coverage_result.get('covered_predios', 0)}/"
                                f"{coverage_result.get('expected_predios', 0)}. "
                                f"Removidos {removed_predios} no asignados."
                                f"{removed_assignment_text}"
                            )
                        ),
                        removed_predios=removed_predios,
                        synced_predios=synced_predios,
                        error_msg=None,
                        sincronizado_en_now=True,
                    )
                pending_events = [
                    (
                        "RETORNO_XTF_CARGADO",
                        (
                            f"[{correlation_id}] Se cargo archivo retorno {archivo.filename} "
                            f"(version {retorno_version}, dataset temporal {retorno_dataset})."
                        ),
                        usuario_log,
                    ),
                    (
                        "RETORNO_XTF_IMPORTADO",
                        (
                            (
                                f"[{correlation_id}] Retorno XTF importado en dataset temporal {retorno_dataset}. "
                                f"Workspace oficial preservado: {work_dataset}."
                            )
                            if publish_to_main
                            else (
                                f"[{correlation_id}] Retorno XTF importado y aplicado en workspace {work_dataset}. "
                                "Pendiente publicacion a main."
                            )
                        ),
                        usuario_log,
                    ),
                    (
                        "RETORNO_XTF_VALIDACION_REGLAS",
                        f"[{correlation_id}] {_validation_history_message(xtf_validation_result)}",
                        usuario_log,
                    ),
                    (
                        "RETORNO_XTF_VALIDADO",
                        (
                            f"[{correlation_id}] Dataset temporal {retorno_dataset} validado antes de sincronizar."
                            if publish_to_main
                            else f"[{correlation_id}] Workspace {work_dataset} validado y listo para publicacion a main."
                        ),
                        usuario_log,
                    ),
                ]
                if removed_assignment_predios > 0:
                    removed_preview_text = (
                        f" Ejemplos: {', '.join(removed_assignment_preview)}."
                        if removed_assignment_preview
                        else ""
                    )
                    pending_events.append(
                        (
                            "RETORNO_PREDIOS_ELIMINADOS",
                            (
                                f"[{correlation_id}] Retorno reporta {removed_assignment_predios} predio(s) eliminados del scope asignado. "
                                "Se marcaron como inactivos en arbimaps_app.asignacion_predio."
                                f"{removed_preview_text}"
                            ),
                            usuario_log,
                        )
                    )
                if publish_to_main:
                    pending_events.append(
                        (
                            "PUBLICACION_MAIN",
                            (
                                f"[{correlation_id}] Sincronizados {synced_predios} predio(s) desde {retorno_dataset} "
                                f"a {_read_schema_main()}. Removidos {removed_predios} no asignados."
                                f" Predios nuevos detectados: {predios_nuevos_sync}."
                                f" Eliminados en retorno: {removed_assignment_predios}."
                                + (
                                    f" Muestra predios: {', '.join(synced_predios_preview)}."
                                    if synced_predios_preview
                                    else ""
                                )
                            ),
                            usuario_log,
                        )
                    )
                else:
                    pending_events.append(
                        (
                            "CARGA_WORKSPACE",
                            (
                                f"[{correlation_id}] Workspace {work_dataset} sincronizado en {_read_schema_work()} "
                                "y pendiente publicacion a main. "
                                f"Cobertura {coverage_result.get('covered_predios', 0)}/"
                                f"{coverage_result.get('expected_predios', 0)}. "
                                f"Removidos {removed_predios} no asignados. "
                                f"Eliminados en retorno: {removed_assignment_predios}."
                            ),
                            usuario_log,
                        )
                    )
                for evento, mensaje, usuario in pending_events:
                    asignaciones_repo.insert_asignacion_event(conn, asignacion_id, evento, mensaje, usuario)
                stage = "commit_sync_pipeline"
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        _log_sync_event(
            "retorno_sync_completed" if publish_to_main else "retorno_workspace_sync_completed",
            correlation_id=correlation_id,
            asignacion_id=asignacion_id,
            retorno_id=retorno_id,
            retorno_dataset=retorno_dataset,
            stage="done",
            status="ok",
            duration_ms=int((time.monotonic() - step_start) * 1000),
            extra={
                "synced_predios": synced_predios,
                "expected_predios": int(coverage_result.get("expected_predios") or 0),
                "covered_predios": int(coverage_result.get("covered_predios") or 0),
                "removed_assignment_predios": removed_assignment_predios,
                "publish_to_main": publish_to_main,
            },
        )
    except Exception as exc:
        try:
            asignaciones_repo.safe_log_event(
                asignacion_id,
                "RETORNO_XTF_VALIDACION_ERROR",
                (
                    f"[{correlation_id}] "
                    + _history_error_message(stage, exc, validation_result=xtf_validation_result)
                ),
                usuario_log,
            )
        except Exception:
            pass

        if retorno_id is not None:
            try:
                with db_conn() as conn:
                    conn.autocommit = False
                    try:
                        asignaciones_repo.update_asignacion_retorno(
                            conn,
                            retorno_id,
                            estado="ERROR",
                            error_msg=f"[{stage}] {_error_detail(exc)}",
                        )
                        conn.commit()
                    except Exception:
                        conn.rollback()
            except Exception:
                pass

        logger.exception(
            "retorno_xtf_error asignacion_id=%s stage=%s retorno_id=%s retorno_dataset=%s",
            asignacion_id,
            stage,
            retorno_id,
            retorno_dataset,
        )
        _log_sync_event(
            "retorno_sync_failed" if publish_to_main else "retorno_workspace_sync_failed",
            correlation_id=correlation_id,
            asignacion_id=asignacion_id,
            retorno_id=retorno_id,
            retorno_dataset=retorno_dataset,
            stage=stage,
            status="error",
            duration_ms=int((time.monotonic() - step_start) * 1000),
            extra={"error": _error_detail(exc), "publish_to_main": publish_to_main},
        )
        _raise_http_from_export_error(exc, stage=stage)
    finally:
        archivo.file.close()
        if publish_to_main and retorno_dataset:
            try:
                with db_conn() as conn_cleanup:
                    cleanup_tmp = workspace_service.remove_workspace_dataset(
                        conn_cleanup,
                        retorno_dataset,
                        _read_schema_work(),
                    )
                    conn_cleanup.commit()
                _log_sync_event(
                    "retorno_tmp_dataset_cleanup",
                    correlation_id=correlation_id,
                    asignacion_id=asignacion_id,
                    retorno_id=retorno_id,
                    retorno_dataset=retorno_dataset,
                    stage="cleanup_tmp_dataset",
                    status="ok",
                    extra=cleanup_tmp,
                )
            except Exception as cleanup_exc:
                logger.warning(
                    "tmp retorno dataset cleanup skipped asignacion_id=%s dataset=%s error=%s",
                    asignacion_id,
                    retorno_dataset,
                    cleanup_exc,
                )
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return {
        "asignacion_id": asignacion_id,
        "work_datasetname": work_dataset,
        "retorno_id": retorno_id,
        "retorno_version": retorno_version,
        "retorno_datasetname": retorno_dataset,
        "correlation_id": correlation_id,
        "archivo_sha256": archivo_sha256,
        "removed_predios_workspace": removed_predios,
        "removed_predios_asignacion": removed_assignment_predios,
        "removed_predios_asignacion_preview": removed_assignment_preview,
        "synced_predios_main": synced_predios,
        "expected_predios_asignacion": int(coverage_result.get("expected_predios") or 0),
        "covered_predios_retorno": int(coverage_result.get("covered_predios") or 0),
        "validation_summary": {
            "note": _xtf_validation_note(xtf_validation_result),
            "pipeline": _validator_pipeline_labels(),
            "rules_with_issues": _extract_rule_ids_from_validation(xtf_validation_result),
        },
        "message": (
            (
                "Retorno XTF importado en dataset temporal, validado y sincronizado. "
                f"Predios eliminados detectados y desactivados: {removed_assignment_predios}."
            )
            if publish_to_main
            else (
                "Retorno XTF sincronizado en workspace y pendiente publicacion main. "
                f"Predios eliminados detectados y desactivados: {removed_assignment_predios}."
            )
        ),
    }


@router.post("/{asignacion_id}/retorno-xtf")
def importar_retorno_xtf(
    asignacion_id: int,
    archivo: UploadFile = File(...),
    user: dict = Depends(require_assignment_roles("admin", "coordinador")),
):
    return _procesar_retorno_xtf(
        asignacion_id,
        archivo,
        user,
        publish_to_main=True,
    )


@router.post("/{asignacion_id}/retorno-xtf-workspace")
def importar_retorno_xtf_workspace(
    asignacion_id: int,
    archivo: UploadFile = File(...),
    user: dict = Depends(
        require_assignment_roles("admin", "coordinador", "digitalizador", "reconocedor")
    ),
):
    return _procesar_retorno_xtf(
        asignacion_id,
        archivo,
        user,
        publish_to_main=False,
    )

@router.get("/{id}/predios/{predio_t_id}/detalle-basico")
def obtener_detalle_basico_predio(
    id: int,
    predio_t_id: int,
    user: dict = Depends(require_assignment_roles("admin", "coordinador", "digitalizador", "reconocedor"))
):
    schema_work = _safe_ident((ASIG_MODEL_CONTEXT.schema_work or "b_asignaciones_arb").strip(), fallback="b_asignaciones_arb")
    predio_table = _safe_ident((ASIG_MODEL_CONTEXT.predio_table or "arb_predio").strip(), fallback="arb_predio")
    predio_numero_field = _safe_ident((ASIG_MODEL_CONTEXT.predio_numero_field or "numero_predial").strip(), fallback="numero_predial")

    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. Verificar asignacion
            cur.execute("SELECT usuario_asignado, work_datasetname FROM arbimaps_app.asignacion WHERE id = %s", (id,))
            asig = cur.fetchone()
            if not asig:
                raise HTTPException(status_code=404, detail="Asignación no encontrada")
                
            usuario_asignado = str(asig.get("usuario_asignado") or "").strip().lower()
            work_datasetname = str(asig.get("work_datasetname") or "").strip()
            
            # Verificación de rol
            role = str(user.get("role") or user.get("role_code") or user.get("rol") or "").strip().lower()
            if role in {"digitalizador", "reconocedor"}:
                username = str(user.get("username") or "").strip().lower()
                if usuario_asignado != username:
                    raise HTTPException(status_code=403, detail="La asignación no le pertenece")
                    
            # 2. Buscar relacion asignacion_predio
            cur.execute(
                """
                SELECT numero_predial_nacional 
                FROM arbimaps_app.asignacion_predio 
                WHERE predio_t_id = %s AND asignacion_id = %s AND activo = TRUE
                LIMIT 1
                """,
                (predio_t_id, id)
            )
            ap = cur.fetchone()
            if not ap:
                raise HTTPException(status_code=404, detail="El predio no está asociado a esta asignación")
                
            numero_predial_nacional = str(ap.get("numero_predial_nacional") or "").strip()

            # 3. Localizar el predio en la canasta de trabajo
            workspace_predio_t_id = None
            if numero_predial_nacional and work_datasetname:
                cur.execute(
                    f"""
                    SELECT p.t_id
                    FROM {schema_work}.{predio_table} p
                    JOIN {schema_work}.t_ili2db_basket b ON b.t_id = p.t_basket
                    JOIN {schema_work}.t_ili2db_dataset d ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                      AND BTRIM(p.{predio_numero_field}::text) = BTRIM(%s::text)
                    ORDER BY p.t_id DESC
                    LIMIT 1
                    """,
                    (work_datasetname, numero_predial_nacional)
                )
                row = cur.fetchone()
                if row and row.get("t_id") is not None:
                    workspace_predio_t_id = int(row["t_id"])
                    
            if workspace_predio_t_id is None and numero_predial_nacional:
                cur.execute(
                    f"""
                    SELECT p.t_id
                    FROM {schema_work}.{predio_table} p
                    WHERE BTRIM(p.{predio_numero_field}::text) = BTRIM(%s::text)
                    ORDER BY p.t_id DESC
                    LIMIT 1
                    """,
                    (numero_predial_nacional,)
                )
                row = cur.fetchone()
                if row and row.get("t_id") is not None:
                    workspace_predio_t_id = int(row["t_id"])

            if workspace_predio_t_id is None:
                cur.execute(
                    f"SELECT t_id FROM {schema_work}.{predio_table} WHERE t_id = %s LIMIT 1",
                    (predio_t_id,)
                )
                row = cur.fetchone()
                if row and row.get("t_id") is not None:
                    workspace_predio_t_id = int(row["t_id"])
                    
            if not workspace_predio_t_id:
                raise HTTPException(status_code=404, detail="No se encontró el predio en la canasta de trabajo")

            # 4. Extraer datos básicos
            cur.execute(
                f"""
                SELECT 
                    numero_predial, 
                    area_registral_m2, 
                    condicion_predio, 
                    destinacion_economica, 
                    tipo as tipo_predio,
                    area_catastral_terreno
                FROM {schema_work}.{predio_table}
                WHERE t_id = %s
                """,
                (workspace_predio_t_id,)
            )
            datos_predio = cur.fetchone()
            
            if not datos_predio:
                raise HTTPException(status_code=404, detail="Datos del predio no encontrados")

            # Mapear los resultados
            return {
                "status": "success",
                "predio": {
                    "numero_predial_nacional": numero_predial_nacional,
                    "numero_predial": datos_predio.get("numero_predial"),
                    "area_registral_m2": float(datos_predio.get("area_registral_m2")) if datos_predio.get("area_registral_m2") is not None else None,
                    "area_catastral_terreno": float(datos_predio.get("area_catastral_terreno")) if datos_predio.get("area_catastral_terreno") is not None else None,
                    "condicion_predio": datos_predio.get("condicion_predio"),
                    "destinacion_economica": datos_predio.get("destinacion_economica"),
                    "tipo_predio": datos_predio.get("tipo_predio")
                }
            }

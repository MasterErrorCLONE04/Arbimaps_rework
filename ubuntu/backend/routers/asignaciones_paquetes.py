import logging
import os
import shutil
import tempfile
from threading import Thread
import traceback
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import uuid4

from core.asignaciones import (
    ASIG_EXPORT_JOB_DIR,
    ASIG_EXPORT_JOB_TTL_HOURS,
    ASIG_SKIP_WORKSPACE,
    DATASETNAME_MAIN_DEFAULT,
    ILI2PG_CMD,
    ILI2PG_TIMEOUT_SEC,
    REQUIRED_BASKETS,
    assignment_access_denied_detail,
    can_access_assignment_model,
)
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse

from repositories import asignaciones_repo
from routers.auth import get_current_tenant, get_current_user, get_user_role, normalize_role, check_admin_soporte_isolation
from services import asignaciones_export as export_service
from services import asignaciones_workspace as workspace_service
from tenants import TenantContext, get_connection_manager, get_tenant_db_connection

router = APIRouter(prefix="/asignaciones", tags=["asignaciones-export"])
logger = logging.getLogger(__name__)

JOB_FORMAT = Literal["xtf", "gdb", "gpkg"]


def _require_assignment_access(user: Optional[dict], *allowed_roles: str) -> None:
    role = normalize_role(get_user_role(user or {}))
    if role == "soporte":
        return
    allowed = {normalize_role(item) for item in allowed_roles if item}
    if allowed and role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Rol '{role}' sin permisos para esta accion",
        )
    if not can_access_assignment_model(user or {}, role=role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=assignment_access_denied_detail(),
        )


def _ensure_assignment_owner_access(user: Optional[dict], asignacion: Optional[dict]) -> None:
    role = str(
        (user or {}).get("role")
        or (user or {}).get("rol")
        or (user or {}).get("role_code")
        or ""
    ).strip().lower()
    username = str((user or {}).get("username") or "").strip().lower()
    if role not in {"digitalizador", "reconocedor"}:
        return
    owner = str((asignacion or {}).get("usuario_asignado") or "").strip().lower()
    if not owner or owner != username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La asignacion no le pertenece al usuario autenticado.",
        )


def _read_schema_main(tenant: TenantContext) -> str:
    value = (tenant.schemas.main or "").strip()
    if not value:
        raise RuntimeError("tenant.schemas.main no configurado.")
    return value


def _read_schema_work(tenant: TenantContext) -> str:
    value = (tenant.schemas.work or "").strip()
    if not value:
        raise RuntimeError("tenant.schemas.work no configurado.")
    return value


def _read_datasetname_main_default() -> str:
    return (DATASETNAME_MAIN_DEFAULT or "").strip()


def _read_required_baskets() -> set[str]:
    return set(REQUIRED_BASKETS or ())


def _raise_http_from_export_error(exc: Exception) -> None:
    if isinstance(exc, export_service.ExportServiceError):
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if isinstance(exc, HTTPException):
        raise exc
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=_error_detail(exc),
    ) from exc


def _error_detail(exc: Exception) -> str:
    if isinstance(exc, export_service.ExportServiceError):
        return str(exc.detail)
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return str(exc) or exc.__class__.__name__


def _ensure_package_export_supported() -> None:
    # Este router se deja acoplado al flujo Arb, pero ya sin contexto global mutable.
    return


def _ensure_package_export_supported_http() -> None:
    try:
        _ensure_package_export_supported()
    except Exception as exc:
        _raise_http_from_export_error(exc)


def _ensure_assignment_access(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    user: Optional[dict],
) -> dict:
    asignaciones_repo.ensure_asignacion_tables(conn, tenant)
    asignacion = asignaciones_repo.get_asignacion_for_paquete(conn, tenant, asignacion_id)
    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignacion no encontrada.")
    _ensure_assignment_owner_access(user, asignacion)
    check_admin_soporte_isolation(conn, tenant, user, asignacion_id)
    return asignacion


def _safe_log_event(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    evento: str,
    mensaje: Optional[str],
    usuario: Optional[str],
) -> None:
    asignaciones_repo.safe_log_event(conn, tenant, asignacion_id, evento, mensaje, usuario)


def _ensure_workspace_ready_for_export_raw(
    tenant: TenantContext,
    connection_manager,
    asignacion_id: int,
    created_by: Optional[str],
) -> str:
    _ensure_package_export_supported()

    def _update_asignacion_fields_wrapper(target_asignacion_id: int, **kwargs) -> None:
        with connection_manager.connection(tenant) as conn:
            conn.autocommit = False
            try:
                asignaciones_repo.update_asignacion_fields(
                    conn,
                    tenant,
                    target_asignacion_id,
                    **kwargs,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _safe_log_event_wrapper(
        target_asignacion_id: int,
        evento: str,
        mensaje: Optional[str],
        usuario: Optional[str],
    ) -> None:
        with connection_manager.connection(tenant) as conn:
            conn.autocommit = False
            try:
                asignaciones_repo.safe_log_event(
                    conn,
                    tenant,
                    target_asignacion_id,
                    evento,
                    mensaje,
                    usuario,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    with connection_manager.connection(tenant) as conn:
        return workspace_service.ensure_workspace_ready_for_export(
            conn,
            tenant,
            asignacion_id,
            created_by,
            schema_main=_read_schema_main(tenant),
            schema_work=_read_schema_work(tenant),
            datasetname_main_default=_read_datasetname_main_default(),
            ili2pg_cmd=ILI2PG_CMD,
            timeout_sec=ILI2PG_TIMEOUT_SEC,
            required_topics=sorted(_read_required_baskets()),
            update_asignacion_fields=_update_asignacion_fields_wrapper,
            safe_log_event=_safe_log_event_wrapper,
        )


def _ensure_workspace_ready_for_export(
    tenant: TenantContext,
    connection_manager,
    asignacion_id: int,
    created_by: Optional[str],
) -> str:
    try:
        return _ensure_workspace_ready_for_export_raw(
            tenant,
            connection_manager,
            asignacion_id,
            created_by,
        )
    except Exception as exc:
        _raise_http_from_export_error(exc)


def _get_asignacion_for_export(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    user: Optional[dict],
) -> dict:
    asignacion = asignaciones_repo.get_asignacion_for_paquete(conn, tenant, asignacion_id)
    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignacion no encontrada.")
    _ensure_assignment_owner_access(user, asignacion)
    return asignacion


def _resolve_export_context(
    conn,
    tenant: TenantContext,
    connection_manager,
    asignacion_id: int,
    created_by: Optional[str],
    user: Optional[dict],
) -> tuple[str, str, dict]:
    _ensure_package_export_supported()
    asignacion = _get_asignacion_for_export(conn, tenant, asignacion_id, user)

    if ASIG_SKIP_WORKSPACE:
        dataset = str(asignacion.get("datasetname_main") or "").strip()
        if not dataset:
            raise export_service.ExportServiceError(
                status_code=400,
                detail="La asignacion no tiene dataset principal para exportar.",
            )
        return _read_schema_main(tenant), dataset, asignacion

    dataset = str(asignacion.get("work_datasetname") or "").strip()
    if not dataset:
        raise export_service.ExportServiceError(
            status_code=400,
            detail="La asignacion no tiene workspace disponible para exportar.",
        )

    dataset = _ensure_workspace_ready_for_export_raw(
        tenant,
        connection_manager,
        asignacion_id,
        created_by,
    )
    return _read_schema_work(tenant), dataset, asignacion


def _job_output_dir(tenant: TenantContext) -> str:
    base_dir = ASIG_EXPORT_JOB_DIR or os.path.join(tempfile.gettempdir(), "asignacion_exports")
    tenant_dir = os.path.join(base_dir, tenant.municipality_code)
    output_dir = os.path.join(tenant_dir, "jobs")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def _mark_job_failed(
    connection_manager,
    tenant: TenantContext,
    job_id: int,
    asignacion_id: int,
    created_by: Optional[str],
    exc: Exception,
) -> None:
    detail = _error_detail(exc)
    logger.exception(
        "Export job failed before persistence update job_id=%s asignacion_id=%s formato_error=%s",
        job_id,
        asignacion_id,
        detail,
    )
    if not isinstance(exc, export_service.ExportServiceError):
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
        if tb:
            if len(tb) > 6000:
                tb = tb[-6000:]
            detail = f"{detail}\nTRACEBACK:\n{tb}"

    try:
        with connection_manager.connection(tenant) as conn:
            conn.autocommit = False
            try:
                asignaciones_repo.mark_export_job_error(
                    conn,
                    tenant,
                    job_id,
                    detail,
                    mensaje="Exportacion fallida",
                )
                _safe_log_event(conn, tenant, asignacion_id, "PAQUETE_JOB_ERROR", detail, created_by)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
    except Exception:
        logger.exception(
            "No se pudo persistir estado ERROR del export job job_id=%s asignacion_id=%s",
            job_id,
            asignacion_id,
        )


def _process_export_job(
    connection_manager,
    tenant: TenantContext,
    job_id: int,
    asignacion_id: int,
    formato: JOB_FORMAT,
    created_by: Optional[str],
) -> None:
    tmp_dir: Optional[str] = None
    try:
        logger.info(
            "Iniciando export job job_id=%s asignacion_id=%s formato=%s tenant=%s",
            job_id,
            asignacion_id,
            formato,
            tenant.municipality_code,
        )
        artifact_suffix = f"{tenant.municipality_code}_{asignacion_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex}"

        with connection_manager.connection(tenant) as conn:
            conn.autocommit = False
            try:
                asignaciones_repo.mark_export_job_running(conn, tenant, job_id, mensaje="Preparando exportacion")
                asignaciones_repo.update_export_job_progress(
                    conn,
                    tenant,
                    job_id,
                    10,
                    mensaje="Validando contexto de workspace",
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        with connection_manager.connection(tenant) as conn:
            schema, dataset, asignacion = _resolve_export_context(
                conn,
                tenant,
                connection_manager,
                asignacion_id,
                created_by,
                None,
            )

        with connection_manager.connection(tenant) as conn:
            conn.autocommit = False
            try:
                asignaciones_repo.update_export_job_progress(
                    conn,
                    tenant,
                    job_id,
                    35,
                    mensaje=f"Contexto listo ({schema}:{dataset})",
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        output_dir = _job_output_dir(tenant)

        if formato == "xtf":
            file_path = os.path.join(output_dir, f"asignacion_{artifact_suffix}.xtf")
            with connection_manager.connection(tenant) as conn:
                export_mode = export_service.ili2pg_export_assignment(
                    conn,
                    tenant,
                    schema=schema,
                    asignacion_id=asignacion_id,
                    datasetname=dataset,
                    xtf_path=file_path,
                    required_topics=sorted(_read_required_baskets()),
                    ili2pg_cmd=ILI2PG_CMD,
                    timeout_sec=ILI2PG_TIMEOUT_SEC,
                )
            file_name = (
                f"asignacion_{tenant.municipality_code}_{asignacion_id}_"
                f"{(asignacion.get('usuario_asignado') or '').strip()}_{uuid4().hex[:8]}.xtf"
            )
            done_msg = f"XTF generado. Modo: {export_mode}."
        elif formato == "gdb":
            tmp_dir = tempfile.mkdtemp(prefix=f"asig_{artifact_suffix}_", dir=output_dir)
            gdb_name = f"asignacion_{artifact_suffix}.gdb"
            gdb_dir = os.path.join(tmp_dir, gdb_name)
            export_service.ogr_export_gdb(
                tenant,
                schema=schema,
                datasetname=dataset,
                gdb_path=gdb_dir,
                asignacion_id=asignacion_id,
            )
            zip_base = os.path.join(output_dir, f"asignacion_{artifact_suffix}")
            file_path = shutil.make_archive(zip_base, "zip", tmp_dir, gdb_name)
            file_name = f"asignacion_{tenant.municipality_code}_{asignacion_id}_{uuid4().hex[:8]}_gdb.zip"
            done_msg = "GDB generado."
        else:
            file_path = os.path.join(output_dir, f"asignacion_{artifact_suffix}.gpkg")
            export_service.ogr_export_gpkg(
                tenant,
                schema=schema,
                datasetname=dataset,
                gpkg_path=file_path,
                asignacion_id=asignacion_id,
            )
            file_name = f"asignacion_{tenant.municipality_code}_{asignacion_id}_{uuid4().hex[:8]}.gpkg"
            done_msg = "GPKG generado."

        if not os.path.exists(file_path):
            raise RuntimeError("No se encontro archivo de salida generado.")

        file_size = os.path.getsize(file_path)
        with connection_manager.connection(tenant) as conn:
            conn.autocommit = False
            try:
                asignaciones_repo.mark_export_job_done(
                    conn,
                    tenant,
                    job_id,
                    archivo_path=file_path,
                    archivo_nombre=file_name,
                    archivo_size=file_size,
                    ttl_hours=ASIG_EXPORT_JOB_TTL_HOURS,
                    mensaje=done_msg,
                )
                _safe_log_event(conn, tenant, asignacion_id, "PAQUETE_JOB_DONE", done_msg, created_by)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
    except Exception as exc:
        logger.exception(
            "Excepcion ejecutando export job job_id=%s asignacion_id=%s formato=%s",
            job_id,
            asignacion_id,
            formato,
        )
        _mark_job_failed(connection_manager, tenant, job_id, asignacion_id, created_by, exc)
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/{asignacion_id}/paquete/jobs", status_code=status.HTTP_202_ACCEPTED)
def crear_job_paquete_asignacion(
    request: Request,
    asignacion_id: int,
    background: BackgroundTasks,
    formato: JOB_FORMAT = "xtf",
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    _ensure_package_export_supported_http()
    _require_assignment_access(user, "admin", "coordinador", "lider_reconocimiento")
    _ensure_assignment_access(conn, tenant, asignacion_id, user)
    created_by = user.get("username") if isinstance(user, dict) else None

    try:
        job, created = asignaciones_repo.get_or_create_active_export_job(
            conn,
            tenant,
            asignacion_id,
            formato,
            created_by,
        )
        if created:
            _safe_log_event(
                conn,
                tenant,
                asignacion_id,
                "PAQUETE_JOB_CREADO",
                f"Job {job['id']} creado para formato {formato}.",
                created_by,
            )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        _raise_http_from_export_error(exc)

    if not created:
        return {
            "job_id": job.get("id"),
            "estado": job.get("estado"),
            "formato": job.get("formato"),
            "message": "Ya existe un job activo para esta asignacion y formato.",
        }

    connection_manager = get_connection_manager(request.app)
    Thread(
        target=_process_export_job,
        args=(
            connection_manager,
            tenant,
            int(job["id"]),
            asignacion_id,
            formato,
            created_by,
        ),
        daemon=True,
    ).start()

    return {
        "job_id": job.get("id"),
        "estado": job.get("estado"),
        "formato": job.get("formato"),
        "status_url": f"/asignaciones/export-jobs/{job.get('id')}",
        "download_url": f"/asignaciones/export-jobs/{job.get('id')}/download",
    }


@router.get("/export-jobs/{job_id}")
def ver_job_paquete(
    job_id: int,
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    _require_assignment_access(user, "admin", "coordinador", "lider_reconocimiento")
    job = asignaciones_repo.get_export_job(conn, tenant, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    response = dict(job)
    response["status_url"] = f"/asignaciones/export-jobs/{job_id}"
    response["download_url"] = f"/asignaciones/export-jobs/{job_id}/download"
    return response


@router.get("/{asignacion_id}/paquete/jobs")
def listar_jobs_paquete_asignacion(
    asignacion_id: int,
    limit: int = 20,
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    _require_assignment_access(user, "admin", "coordinador", "lider_reconocimiento")
    _ensure_assignment_access(conn, tenant, asignacion_id, user)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    rows = asignaciones_repo.list_export_jobs_for_asignacion(conn, tenant, asignacion_id, limit=limit)
    return rows


@router.get("/export-jobs/{job_id}/download")
def descargar_job_paquete(
    job_id: int,
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    _require_assignment_access(user, "admin", "coordinador", "lider_reconocimiento")
    job = asignaciones_repo.get_export_job(conn, tenant, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    estado_job = str(job.get("estado") or "").upper()
    if estado_job != "DONE":
        raise HTTPException(status_code=409, detail=f"El job aun no esta listo. Estado actual: {estado_job}")

    expira_en = job.get("expira_en")
    if expira_en is not None:
        now_utc = datetime.now(timezone.utc)
        exp_utc = expira_en
        if getattr(exp_utc, "tzinfo", None) is None:
            exp_utc = exp_utc.replace(tzinfo=timezone.utc)
        if exp_utc < now_utc:
            raise HTTPException(status_code=410, detail="El archivo del job ya expiro.")

    file_path = job.get("archivo_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=410, detail="Archivo no disponible para descarga.")

    file_name = job.get("archivo_nombre") or os.path.basename(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    media_type = {
        ".xtf": "application/xml",
        ".zip": "application/zip",
        ".gpkg": "application/geopackage+sqlite3",
    }.get(ext, "application/octet-stream")

    return FileResponse(file_path, media_type=media_type, filename=file_name)


@router.get("/{asignacion_id}/paquete")
def descargar_paquete_asignacion(
    request: Request,
    asignacion_id: int,
    background: BackgroundTasks,
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    _require_assignment_access(user, "admin", "coordinador", "lider_reconocimiento")
    created_by = user.get("username") if isinstance(user, dict) else None
    try:
        export_schema, export_dataset, asignacion = _resolve_export_context(
            conn,
            tenant,
            request.app.state.tenant_connection_manager,
            asignacion_id,
            created_by,
            user,
        )
    except Exception as exc:
        _raise_http_from_export_error(exc)

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xtf")
    tmp_path = tmp_file.name
    tmp_file.close()
    try:
        export_mode = export_service.ili2pg_export_assignment(
            conn,
            tenant,
            schema=export_schema,
            asignacion_id=asignacion_id,
            datasetname=export_dataset,
            xtf_path=tmp_path,
            required_topics=sorted(_read_required_baskets()),
            ili2pg_cmd=ILI2PG_CMD,
            timeout_sec=ILI2PG_TIMEOUT_SEC,
        )
    except Exception:
        os.unlink(tmp_path)
        raise

    try:
        _safe_log_event(
            conn,
            tenant,
            asignacion_id,
            "PAQUETE_DESCARGADO",
            (
                f"Paquete exportado para {export_dataset} "
                f"({'main' if export_schema == _read_schema_main(tenant) else 'work'}). "
                f"Modo: {export_mode}."
            ),
            created_by,
        )
        conn.commit()
    except Exception:
        conn.rollback()

    filename_parts = [
        "asignacion",
        str(asignacion_id),
        asignacion.get("usuario_asignado") or "",
    ]
    filename = "_".join(filter(None, filename_parts)) + ".xtf"

    background.add_task(os.remove, tmp_path)
    return FileResponse(
        tmp_path,
        media_type="application/xml",
        filename=filename,
        background=background,
    )


@router.get("/{asignacion_id}/paquete-gdb")
def descargar_paquete_asignacion_gdb(
    request: Request,
    asignacion_id: int,
    background: BackgroundTasks,
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    _ensure_package_export_supported_http()
    _require_assignment_access(user, "admin", "coordinador", "lider_reconocimiento")
    asignacion = _get_asignacion_for_export(conn, tenant, asignacion_id, user)

    export_dataset = asignacion.get("datasetname_main") if ASIG_SKIP_WORKSPACE else asignacion.get("work_datasetname")
    if ASIG_SKIP_WORKSPACE and not export_dataset:
        raise HTTPException(
            status_code=400,
            detail="La asignacion no tiene dataset principal para exportar.",
        )
    if (not ASIG_SKIP_WORKSPACE) and (not export_dataset):
        raise HTTPException(
            status_code=400,
            detail="La asignacion no tiene workspace disponible para exportar.",
        )
    if not ASIG_SKIP_WORKSPACE:
        export_dataset = _ensure_workspace_ready_for_export(
            tenant,
            request.app.state.tenant_connection_manager,
            asignacion_id,
            user.get("username") if isinstance(user, dict) else None,
        )

    tmp_dir = tempfile.mkdtemp()
    gdb_dir = os.path.join(tmp_dir, "asignacion.gdb")

    try:
        export_service.ogr_export_gdb(
            tenant,
            schema=_read_schema_main(tenant) if ASIG_SKIP_WORKSPACE else _read_schema_work(tenant),
            datasetname=export_dataset,
            gdb_path=gdb_dir,
            asignacion_id=asignacion_id,
        )
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    zip_base = os.path.join(tmp_dir, f"asignacion_{asignacion_id}")
    zip_path = shutil.make_archive(zip_base, "zip", tmp_dir, "asignacion.gdb")

    try:
        _safe_log_event(
            conn,
            tenant,
            asignacion_id,
            "PAQUETE_GDB_DESCARGADO",
            (
                f"Paquete GDB exportado para {export_dataset} "
                f"({'main' if ASIG_SKIP_WORKSPACE else 'work'})."
            ),
            user.get("username") if isinstance(user, dict) else None,
        )
        conn.commit()
    except Exception:
        conn.rollback()

    filename_parts = [
        "asignacion",
        str(asignacion_id),
        asignacion.get("usuario_asignado") or "",
        "gdb",
    ]
    filename = "_".join(filter(None, filename_parts)) + ".zip"

    background.add_task(shutil.rmtree, tmp_dir, True)
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
        background=background,
    )


@router.get("/{asignacion_id}/paquete-gpkg")
def descargar_paquete_asignacion_gpkg(
    request: Request,
    asignacion_id: int,
    background: BackgroundTasks,
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    _ensure_package_export_supported_http()
    _require_assignment_access(user, "admin", "coordinador", "lider_reconocimiento")
    asignacion = _get_asignacion_for_export(conn, tenant, asignacion_id, user)

    export_schema = _read_schema_work(tenant)
    export_dataset = asignacion.get("work_datasetname")
    if ASIG_SKIP_WORKSPACE:
        export_schema = _read_schema_main(tenant)
        export_dataset = asignacion.get("datasetname_main")
        if not export_dataset:
            raise HTTPException(
                status_code=400,
                detail="La asignacion no tiene dataset principal para exportar.",
            )
    else:
        if not export_dataset:
            raise HTTPException(
                status_code=400,
                detail="La asignacion no tiene workspace disponible para exportar.",
            )
        export_dataset = _ensure_workspace_ready_for_export(
            tenant,
            request.app.state.tenant_connection_manager,
            asignacion_id,
            user.get("username") if isinstance(user, dict) else None,
        )

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".gpkg")
    gpkg_path = tmp_file.name
    tmp_file.close()
    try:
        export_service.ogr_export_gpkg(
            tenant,
            export_schema,
            export_dataset,
            gpkg_path,
            asignacion_id=asignacion_id,
        )
    except Exception:
        if os.path.exists(gpkg_path):
            os.unlink(gpkg_path)
        raise

    try:
        _safe_log_event(
            conn,
            tenant,
            asignacion_id,
            "PAQUETE_GPKG_DESCARGADO",
            f"Paquete GPKG exportado para {export_dataset} ({export_schema}).",
            user.get("username") if isinstance(user, dict) else None,
        )
        conn.commit()
    except Exception:
        conn.rollback()

    background.add_task(os.remove, gpkg_path)
    return FileResponse(
        gpkg_path,
        media_type="application/geopackage+sqlite3",
        filename="data.gpkg",
        background=background,
    )

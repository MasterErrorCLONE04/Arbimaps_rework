import os
import shutil
import tempfile
import traceback
from datetime import datetime, timezone
from typing import Literal, Optional

from core.asignaciones import (
    ASIG_MODEL_CONTEXT,
    ASIG_EXPORT_JOB_DIR,
    ASIG_EXPORT_JOB_TTL_HOURS,
    ASIG_SKIP_WORKSPACE,
    ILI2PG_CMD,
    ILI2PG_TIMEOUT_SEC,
)
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse

from repositories import asignaciones_repo
from routers.auth import require_assignment_roles
from routers.db import db_conn
from services import asignaciones_export as export_service
from services import asignaciones_workspace as workspace_service

router = APIRouter(prefix="/asignaciones", tags=["asignaciones-export"])

JOB_FORMAT = Literal["xtf", "gdb", "gpkg"]


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


def _raise_http_from_export_error(exc: Exception) -> None:
    if isinstance(exc, export_service.ExportServiceError):
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    raise exc


def _error_detail(exc: Exception) -> str:
    if isinstance(exc, export_service.ExportServiceError):
        return str(exc.detail)
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return str(exc) or exc.__class__.__name__


def _safe_log_event(asignacion_id: int, evento: str, mensaje: Optional[str], usuario: Optional[str]) -> None:
    asignaciones_repo.safe_log_event(asignacion_id, evento, mensaje, usuario)


def _ensure_package_export_supported() -> None:
    if ASIG_MODEL_CONTEXT.name != "arb":
        raise export_service.ExportServiceError(
            status_code=501,
            detail=f"La exportacion de paquetes no esta implementada para el modelo {ASIG_MODEL_CONTEXT.name}.",
        )


def _ensure_package_export_supported_http() -> None:
    try:
        _ensure_package_export_supported()
    except Exception as exc:
        _raise_http_from_export_error(exc)


def _ensure_workspace_ready_for_export_raw(asignacion_id: int, created_by: Optional[str]) -> str:
    _ensure_package_export_supported()
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
        safe_log_event=_safe_log_event,
    )


def _ensure_workspace_ready_for_export(asignacion_id: int, created_by: Optional[str]) -> str:
    try:
        return _ensure_workspace_ready_for_export_raw(asignacion_id, created_by)
    except Exception as exc:
        _raise_http_from_export_error(exc)


def _ili2pg_export_asignacion(schema: str, asignacion_id: int, datasetname: str, xtf_path: str) -> str:
    try:
        return export_service.ili2pg_export_assignment(
            schema=schema,
            asignacion_id=asignacion_id,
            datasetname=datasetname,
            xtf_path=xtf_path,
            required_topics=sorted(_read_required_baskets()),
            ili2pg_cmd=ILI2PG_CMD,
            timeout_sec=ILI2PG_TIMEOUT_SEC,
        )
    except Exception as exc:
        _raise_http_from_export_error(exc)


def _ogr_export_gdb(schema: str, datasetname: str, gdb_path: str, *, asignacion_id: Optional[int] = None) -> None:
    try:
        export_service.ogr_export_gdb(
            schema=schema,
            datasetname=datasetname,
            gdb_path=gdb_path,
            asignacion_id=asignacion_id,
        )
    except Exception as exc:
        _raise_http_from_export_error(exc)


def _ogr_export_gpkg(schema: str, datasetname: str, gpkg_path: str, *, asignacion_id: Optional[int] = None) -> None:
    try:
        export_service.ogr_export_gpkg(
            schema=schema,
            datasetname=datasetname,
            gpkg_path=gpkg_path,
            asignacion_id=asignacion_id,
        )
    except Exception as exc:
        _raise_http_from_export_error(exc)


def _get_asignacion_for_export(asignacion_id: int) -> Optional[dict]:
    with db_conn() as conn:
        return asignaciones_repo.get_asignacion_for_paquete(conn, asignacion_id)


def _resolve_export_context(asignacion_id: int, created_by: Optional[str]) -> tuple[str, str, dict]:
    _ensure_package_export_supported()
    asignacion = _get_asignacion_for_export(asignacion_id)
    if not asignacion:
        raise export_service.ExportServiceError(status_code=404, detail="Asignacion no encontrada.")

    if ASIG_SKIP_WORKSPACE:
        dataset = (asignacion.get("datasetname_main") or "").strip()
        if not dataset:
            raise export_service.ExportServiceError(
                status_code=400,
                detail="La asignacion no tiene dataset principal para exportar.",
            )
        return _read_schema_main(), dataset, asignacion

    dataset = (asignacion.get("work_datasetname") or "").strip()
    if not dataset:
        raise export_service.ExportServiceError(
            status_code=400,
            detail="La asignacion no tiene workspace disponible para exportar.",
        )

    dataset = _ensure_workspace_ready_for_export_raw(asignacion_id, created_by)
    return _read_schema_work(), dataset, asignacion


def _job_output_dir() -> str:
    output_dir = ASIG_EXPORT_JOB_DIR or os.path.join(tempfile.gettempdir(), "asignacion_exports")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def _mark_job_failed(job_id: int, asignacion_id: int, created_by: Optional[str], exc: Exception) -> None:
    detail = _error_detail(exc)
    if not isinstance(exc, export_service.ExportServiceError):
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
        if tb:
            if len(tb) > 6000:
                tb = tb[-6000:]
            detail = f"{detail}\nTRACEBACK:\n{tb}"
    asignaciones_repo.mark_export_job_error(job_id, detail, mensaje="Exportacion fallida")
    _safe_log_event(asignacion_id, "PAQUETE_JOB_ERROR", detail, created_by)


def _process_export_job(job_id: int, asignacion_id: int, formato: JOB_FORMAT, created_by: Optional[str]) -> None:
    tmp_dir: Optional[str] = None
    try:
        asignaciones_repo.mark_export_job_running(job_id, mensaje="Preparando exportacion")
        asignaciones_repo.update_export_job_progress(job_id, 10, mensaje="Validando contexto de workspace")

        schema, dataset, asignacion = _resolve_export_context(asignacion_id, created_by)
        asignaciones_repo.update_export_job_progress(job_id, 35, mensaje=f"Contexto listo ({schema}:{dataset})")

        output_dir = _job_output_dir()
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        if formato == "xtf":
            file_path = os.path.join(output_dir, f"asignacion_{asignacion_id}_{ts}.xtf")
            export_mode = export_service.ili2pg_export_assignment(
                schema=schema,
                asignacion_id=asignacion_id,
                datasetname=dataset,
                xtf_path=file_path,
                required_topics=sorted(_read_required_baskets()),
                ili2pg_cmd=ILI2PG_CMD,
                timeout_sec=ILI2PG_TIMEOUT_SEC,
            )
            file_name = f"asignacion_{asignacion_id}_{(asignacion.get('usuario_asignado') or '').strip()}.xtf"
            done_msg = f"XTF generado. Modo: {export_mode}."
        elif formato == "gdb":
            tmp_dir = tempfile.mkdtemp(prefix=f"asig_{asignacion_id}_", dir=output_dir)
            gdb_dir = os.path.join(tmp_dir, "asignacion.gdb")
            export_service.ogr_export_gdb(
                schema=schema,
                datasetname=dataset,
                gdb_path=gdb_dir,
                asignacion_id=asignacion_id,
            )
            zip_base = os.path.join(output_dir, f"asignacion_{asignacion_id}_{ts}")
            file_path = shutil.make_archive(zip_base, "zip", tmp_dir, "asignacion.gdb")
            file_name = f"asignacion_{asignacion_id}_gdb.zip"
            done_msg = "GDB generado."
        else:
            file_path = os.path.join(output_dir, f"asignacion_{asignacion_id}_{ts}.gpkg")
            export_service.ogr_export_gpkg(
                schema=schema,
                datasetname=dataset,
                gpkg_path=file_path,
                asignacion_id=asignacion_id,
            )
            file_name = f"asignacion_{asignacion_id}.gpkg"
            done_msg = "GPKG generado."

        if not os.path.exists(file_path):
            raise RuntimeError("No se encontro archivo de salida generado.")

        file_size = os.path.getsize(file_path)
        asignaciones_repo.mark_export_job_done(
            job_id,
            archivo_path=file_path,
            archivo_nombre=file_name,
            archivo_size=file_size,
            ttl_hours=ASIG_EXPORT_JOB_TTL_HOURS,
            mensaje=done_msg,
        )
        _safe_log_event(asignacion_id, "PAQUETE_JOB_DONE", done_msg, created_by)
    except Exception as exc:
        _mark_job_failed(job_id, asignacion_id, created_by, exc)
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/{asignacion_id}/paquete/jobs", status_code=status.HTTP_202_ACCEPTED)
def crear_job_paquete_asignacion(
    asignacion_id: int,
    background: BackgroundTasks,
    formato: JOB_FORMAT = "xtf",
    user: dict = Depends(require_assignment_roles("admin", "coordinador")),
):
    _ensure_package_export_supported_http()
    created_by = user.get("username") if isinstance(user, dict) else None

    asignacion = _get_asignacion_for_export(asignacion_id)
    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignacion no encontrada.")

    job, created = asignaciones_repo.get_or_create_active_export_job(asignacion_id, formato, created_by)
    if not created:
        return {
            "job_id": job.get("id"),
            "estado": job.get("estado"),
            "formato": job.get("formato"),
            "message": "Ya existe un job activo para esta asignacion y formato.",
        }

    background.add_task(_process_export_job, int(job["id"]), asignacion_id, formato, created_by)

    _safe_log_event(
        asignacion_id,
        "PAQUETE_JOB_CREADO",
        f"Job {job['id']} creado para formato {formato}.",
        created_by,
    )

    return {
        "job_id": job.get("id"),
        "estado": job.get("estado"),
        "formato": job.get("formato"),
        "status_url": f"/asignaciones/export-jobs/{job.get('id')}",
        "download_url": f"/asignaciones/export-jobs/{job.get('id')}/download",
    }


@router.get("/export-jobs/{job_id}")
def ver_job_paquete(job_id: int, _user: dict = Depends(require_assignment_roles("admin", "coordinador"))):
    job = asignaciones_repo.get_export_job(job_id)
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
    _user: dict = Depends(require_assignment_roles("admin", "coordinador")),
):
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    rows = asignaciones_repo.list_export_jobs_for_asignacion(asignacion_id, limit=limit)
    return rows


@router.get("/export-jobs/{job_id}/download")
def descargar_job_paquete(job_id: int, _user: dict = Depends(require_assignment_roles("admin", "coordinador"))):
    job = asignaciones_repo.get_export_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    estado_job = (job.get("estado") or "").upper()
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
    asignacion_id: int,
    background: BackgroundTasks,
    user: dict = Depends(require_assignment_roles("admin", "coordinador")),
):
    created_by = user.get("username") if isinstance(user, dict) else None
    try:
        export_schema, export_dataset, asignacion = _resolve_export_context(asignacion_id, created_by)
    except Exception as exc:
        _raise_http_from_export_error(exc)

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xtf")
    tmp_path = tmp_file.name
    tmp_file.close()
    try:
        export_mode = _ili2pg_export_asignacion(
            export_schema,
            asignacion_id,
            export_dataset,
            tmp_path,
        )
    except Exception:
        os.unlink(tmp_path)
        raise

    _safe_log_event(
        asignacion_id,
        "PAQUETE_DESCARGADO",
        (
            f"Paquete exportado para {export_dataset} "
            f"({'main' if export_schema == _read_schema_main() else 'work'}). "
            f"Modo: {export_mode}."
        ),
        created_by,
    )

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
    asignacion_id: int,
    background: BackgroundTasks,
    user: dict = Depends(require_assignment_roles("admin", "coordinador")),
):
    _ensure_package_export_supported_http()
    asignacion = _get_asignacion_for_export(asignacion_id)
    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignacion no encontrada.")

    work_dataset = asignacion.get("datasetname_main") if ASIG_SKIP_WORKSPACE else asignacion.get("work_datasetname")
    if ASIG_SKIP_WORKSPACE and not work_dataset:
        raise HTTPException(
            status_code=400,
            detail="La asignacion no tiene dataset principal para exportar.",
        )
    if (not ASIG_SKIP_WORKSPACE) and (not work_dataset):
        raise HTTPException(
            status_code=400,
            detail="La asignacion no tiene workspace disponible para exportar.",
        )
    if not ASIG_SKIP_WORKSPACE:
        work_dataset = _ensure_workspace_ready_for_export(
            asignacion_id,
            user.get("username") if isinstance(user, dict) else None,
        )

    tmp_dir = tempfile.mkdtemp()
    gdb_dir = os.path.join(tmp_dir, "asignacion.gdb")

    try:
        _ogr_export_gdb(
            _read_schema_main() if ASIG_SKIP_WORKSPACE else _read_schema_work(),
            work_dataset,
            gdb_dir,
            asignacion_id=asignacion_id,
        )
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    zip_base = os.path.join(tmp_dir, f"asignacion_{asignacion_id}")
    zip_path = shutil.make_archive(zip_base, "zip", tmp_dir, "asignacion.gdb")

    _safe_log_event(
        asignacion_id,
        "PAQUETE_GDB_DESCARGADO",
        f"Paquete GDB exportado para {work_dataset} ({'main' if ASIG_SKIP_WORKSPACE else 'work'}).",
        user.get("username") if isinstance(user, dict) else None,
    )

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
    asignacion_id: int,
    background: BackgroundTasks,
    user: dict = Depends(require_assignment_roles("admin", "coordinador")),
):
    _ensure_package_export_supported_http()
    asignacion = _get_asignacion_for_export(asignacion_id)
    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignacion no encontrada.")

    export_schema = _read_schema_work()
    export_dataset = asignacion.get("work_datasetname")
    if ASIG_SKIP_WORKSPACE:
        export_schema = _read_schema_main()
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
            asignacion_id,
            user.get("username") if isinstance(user, dict) else None,
        )

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".gpkg")
    gpkg_path = tmp_file.name
    tmp_file.close()
    try:
        _ogr_export_gpkg(export_schema, export_dataset, gpkg_path, asignacion_id=asignacion_id)
    except Exception:
        if os.path.exists(gpkg_path):
            os.unlink(gpkg_path)
        raise

    _safe_log_event(
        asignacion_id,
        "PAQUETE_GPKG_DESCARGADO",
        f"Paquete GPKG exportado para {export_dataset} ({export_schema}).",
        user.get("username") if isinstance(user, dict) else None,
    )

    background.add_task(os.remove, gpkg_path)
    return FileResponse(
        gpkg_path,
        media_type="application/geopackage+sqlite3",
        filename="data.gpkg",
        background=background,
    )

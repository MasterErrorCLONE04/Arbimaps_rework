import logging
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from routers.auth import require_user
from services.sincronizacion_mergin import LocalPostgresConnectionService, zip_analyzer, staging_importer
from services.sincronizacion_mergin import staging_to_target_etl

log = logging.getLogger(__name__)
connection_service = LocalPostgresConnectionService()

router = APIRouter(
    prefix="/api/sincronizacion-mergin",
    tags=["Sincronizacion Mergin"],
    dependencies=[Depends(require_user)],
)


class ConnectionPayload(BaseModel):
    host: str = Field(..., min_length=1)
    port: int = Field(5432, ge=1, le=65535)
    user: str = Field(..., min_length=1)
    password: str = ""
    database: str = Field(..., min_length=1)


class DetectionPayload(BaseModel):
    hosts: List[str]
    ports: List[int]


class ApplyEtlPayload(ConnectionPayload):
    staging_schema: str = Field(..., min_length=1)
    target_schema: str = Field(..., min_length=1)
    mode: str = Field(..., min_length=1)


@router.post("/test-connection")
def test_connection(payload: ConnectionPayload):
    log.info("test-connection payload host=%s port=%s user=%s database=%s", payload.host, payload.port, payload.user, payload.database)
    try:
        params = connection_service.build_params(host=payload.host, port=payload.port, user=payload.user, password=payload.password, database=payload.database)
        databases = connection_service.test_connection_and_list_databases(params)
        return {"ok": True, "message": "Conexion exitosa.", "databases": databases}
    except Exception as exc:
        log.exception("Error real en test-connection")
        return JSONResponse(status_code=400, content={"ok": False, "error_type": type(exc).__name__, "message": connection_service.to_public_error(exc), "detail": {"repr": repr(exc), "pgerror": getattr(exc, "pgerror", None)}})


@router.post("/list-schemas")
def list_schemas(payload: ConnectionPayload):
    log.info("list-schemas payload host=%s port=%s user=%s database=%s", payload.host, payload.port, payload.user, payload.database)
    try:
        params = connection_service.build_params(host=payload.host, port=payload.port, user=payload.user, password=payload.password, database=payload.database)
        schemas = connection_service.list_schemas(params)
        return {"ok": True, "database": payload.database, "message": f"Esquemas encontrados en la base de datos '{payload.database}'.", "schemas": schemas}
    except Exception as exc:
        log.exception("Error real en list-schemas")
        return JSONResponse(status_code=400, content={"ok": False, "error_type": type(exc).__name__, "message": connection_service.to_public_error(exc)})


@router.post("/detect-local-connections")
async def detect_local_connections(payload: DetectionPayload):
    try:
        results = await connection_service.detect_open_ports(payload.hosts, payload.ports)
        return {"ok": True, "results": results}
    except Exception:
        log.exception("Error durante la deteccion de puertos")
        raise HTTPException(status_code=500, detail="Error interno durante la deteccion.")


@router.post("/analyze-zip")
async def analyze_zip(file: UploadFile = File(...)):
    try:
        return await zip_analyzer.analyze_uploaded_zip(file)
    except Exception as exc:
        log.exception("Error real en analyze-zip")
        return JSONResponse(status_code=400, content={"ok": False, "error_type": type(exc).__name__, "message": str(exc), "detail": {"repr": repr(exc), "pgerror": getattr(exc, "pgerror", None)}})


@router.post("/import-staging")
async def import_staging(
    zip_file: UploadFile = File(...),
    host: str = Form(...),
    port: int = Form(...),
    user: str = Form(...),
    password: str = Form(""),
    database: str = Form(...),
    target_schema: str = Form(...),
    staging_schema: str = Form(...),
    mode: str = Form(...),
    replace: bool = Form(False),
):
    try:
        return await staging_importer.import_uploaded_zip_to_staging(zip_file=zip_file, host=host, port=port, user=user, password=password, database=database, target_schema=target_schema, staging_schema=staging_schema, mode=mode, replace=replace)
    except Exception as exc:
        log.exception("Error real en import-staging")
        return JSONResponse(status_code=400, content={"ok": False, "error_type": type(exc).__name__, "message": str(exc), "detail": {"repr": repr(exc), "pgerror": getattr(exc, "pgerror", None)}})


@router.post("/apply-etl")
def apply_etl(payload: ApplyEtlPayload):
    try:
        return staging_to_target_etl.run_staging_to_target_etl(
            host=payload.host,
            port=payload.port,
            user=payload.user,
            password=payload.password,
            database=payload.database,
            staging_schema=payload.staging_schema,
            target_schema=payload.target_schema,
            mode=payload.mode,
        )
    except Exception as exc:
        log.exception("Error real en apply-etl")
        return JSONResponse(status_code=400, content={"ok": False, "error_type": type(exc).__name__, "message": str(exc), "detail": {"repr": repr(exc), "pgerror": getattr(exc, "pgerror", None)}})

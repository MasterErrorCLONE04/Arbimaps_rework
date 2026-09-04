import json
import os

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from services.validation_excel_report import MIME_TYPE as EXCEL_MIME_TYPE
from services.xtf_validation_service import XTFValidationService
from routers.auth import get_user

router = APIRouter(prefix="/validacion", tags=["Validación"])
templates = Jinja2Templates(directory="templates")

_xtf_service: XTFValidationService | None = None


def _get_base_path(request: Request) -> str:
    root_path = (request.scope.get("root_path") or "").rstrip("/")
    if root_path:
        return root_path
    return os.getenv("APP_BASE_PATH", "").rstrip("/")


def _get_xtf_service() -> XTFValidationService:
    global _xtf_service
    if _xtf_service is None:
        _xtf_service = XTFValidationService()
    return _xtf_service


def _parse_selected_predios(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    raw_str = str(raw).strip()
    if not raw_str or raw_str in ("[]", "null", "none"):
        return None
    try:
        data = json.loads(raw_str)
        if isinstance(data, list):
            items = []
            for x in data:
                if isinstance(x, dict):
                    cand = str(x.get("tid") or x.get("numero_predial") or x.get("id_operacion") or "").strip()
                    if cand:
                        items.append(cand)
                else:
                    cand = str(x).strip()
                    if cand:
                        items.append(cand)
            return items if items else None
    except Exception:
        pass
    items = [x.strip() for x in raw_str.split(",") if x.strip()]
    return items if items else None


@router.post("/xtf/inspeccionar")
def inspeccionar_xtf(
    request: Request,
    file: UploadFile = File(...),
):
    try:
        if not file.filename or not file.filename.lower().endswith(".xtf"):
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "Solo se permiten archivos con extensión .xtf",
                    "predios": [],
                    "total_predios": 0,
                },
            )

        predios = _get_xtf_service().extract_predios(file)
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "filename": file.filename,
                "total_predios": len(predios),
                "predios": predios,
            },
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Error al inspeccionar el archivo: {exc}",
                "predios": [],
                "total_predios": 0,
            },
        )


@router.get("/xtf", response_class=HTMLResponse)
def vista_validacion_xtf(request: Request):
    return templates.TemplateResponse(
        "validacion_xtf.html",
        {
            "request": request,
            "result": None,
            "error": None,
            "rp": _get_base_path(request),
        },
    )


@router.post("/xtf/subir", response_class=HTMLResponse)
def subir_xtf(
    request: Request,
    file: UploadFile = File(...),
    selected_predios: str | None = Form(None),
):
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="No se recibió archivo.")

        if not file.filename.lower().endswith(".xtf"):
            return templates.TemplateResponse(
                "validacion_xtf.html",
                {
                    "request": request,
                    "result": None,
                    "error": "Solo se permiten archivos con extensión .xtf",
                    "rp": _get_base_path(request),
                },
                status_code=400,
            )

        user = get_user(request) or {}
        parsed_predios = _parse_selected_predios(selected_predios)
        result = _get_xtf_service().save_xtf(
            file,
            municipality_code=user.get("municipality_code"),
            selected_predios=parsed_predios,
            username=user.get("username"),
        )

        return templates.TemplateResponse(
            "validacion_xtf.html",
            {
                "request": request,
                "result": result,
                "error": None,
                "rp": _get_base_path(request),
            },
        )

    except Exception as e:
        return templates.TemplateResponse(
            "validacion_xtf.html",
            {
                "request": request,
                "result": None,
                "error": f"Error al subir el archivo: {str(e)}",
                "rp": _get_base_path(request),
            },
            status_code=500,
        )


@router.get("/xtf/{job_id}/reporte.pdf")
def descargar_reporte_xtf(job_id: str, component: str | None = None):
    try:
        pdf_bytes, filename = _get_xtf_service().build_pdf_report(job_id, component=component)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/xtf/{job_id}/errores.xlsx")
def descargar_errores_xtf_excel(
    request: Request,
    job_id: str,
    component: str | None = None,
):
    try:
        user = get_user(request) if request else {}
        username = user.get("username") if user else None
        excel_bytes, filename = _get_xtf_service().build_excel_report(
            job_id,
            component=component,
            username=username,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return Response(
        content=excel_bytes,
        media_type=EXCEL_MIME_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )

import os

from fastapi import APIRouter, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services.xtf_validation_service import XTFValidationService

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


@router.get("/xtf", response_class=HTMLResponse)
async def vista_validacion_xtf(request: Request):
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
async def subir_xtf(request: Request, file: UploadFile = File(...)):
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

        result = await _get_xtf_service().save_xtf(file)

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

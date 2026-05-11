import json
import os
import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Form, Request, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from psycopg2.extras import RealDictCursor

from core.asignaciones import (
    ASIG_MODEL_CONTEXT,
    can_access_assignment_model,
    is_assignment_internal_rollout_active,
    is_assignment_internal_user,
)
from routers.auth import COOKIE_NAME, DEFAULT_ROLE, get_user, get_user_role, normalize_role, signer
from routers.db import db_conn
from routers.security import verify_password
from services.xtf_validation_service import XTFValidationService


router = APIRouter()
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
xtf_service = XTFValidationService()

# si alg�n d�a usas /api
BASE_PATH = os.getenv("APP_BASE_PATH", "").rstrip("/")
ASIGNACIONES_ROLES = {"admin", "coordinador"}


# -------------------------------------------------
# Helpers
# -------------------------------------------------

def get_base_path(request: Request) -> str:
    """
    Obtiene el root_path real (nginx proxy) o APP_BASE_PATH
    """
    root_path = request.scope.get("root_path", "")
    root_path = root_path.rstrip("/")

    if root_path:
        return root_path

    return BASE_PATH


def with_root_path(request: Request, path: str) -> str:
    base = get_base_path(request)

    if not base:
        return path

    return f"{base}{path}"


def _effective_role(user: dict[str, Any]) -> str:
    try:
        role = get_user_role(user)
    except Exception:
        role = (user.get("role") or DEFAULT_ROLE)
    return normalize_role(role or DEFAULT_ROLE)


def _can_access_asignaciones(user: dict[str, Any]) -> bool:
    role = _effective_role(user)
    if role in ASIGNACIONES_ROLES:
        return can_access_assignment_model(user, role=role)

    username = str(user.get("username") or "").strip().lower()
    if username in {"admin", "administrador"}:
        return can_access_assignment_model(user, role="admin")

    return False


def _session_json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        try:
            return int(value)
        except Exception:
            return str(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8")
        except Exception:
            return str(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _render_panel(
    request: Request,
    user: dict[str, Any],
    view: str,
    status_code: int = 200,
    **extra_context,
):
    """
    Render central del panel
    """
    role = _effective_role(user)
    can_access_asignaciones = _can_access_asignaciones(user)
    context: dict[str, object] = {
        "request": request,
        "user": user.get("username") or user.get("email") or "usuario",
        "rp": get_base_path(request),
        "view": view,
        "effective_role": role,
        "can_access_asignaciones": can_access_asignaciones,
        "asig_model_name": ASIG_MODEL_CONTEXT.name,
        "asig_schema_main": (ASIG_MODEL_CONTEXT.schema_main or "").strip(),
        "asig_schema_work": (ASIG_MODEL_CONTEXT.schema_work or "").strip(),
        "asig_supports_package_export": ASIG_MODEL_CONTEXT.name in {"leiva", "arb"},
        "asig_supports_retorno_xtf": ASIG_MODEL_CONTEXT.name in {"leiva", "arb"},
        "asig_internal_rollout_active": is_assignment_internal_rollout_active(ASIG_MODEL_CONTEXT.name),
        "asig_internal_access_granted": is_assignment_internal_user(user, role=role),
        "visor_geoserver_layers": os.getenv(
            "VISOR_GEOSERVER_LAYERS",
            "A_Base_Principal:Base_Principal",
        ),
    }

    context.update(extra_context)

    return templates.TemplateResponse("panel.html", context, status_code=status_code)


# -------------------------------------------------
# LOGIN
# -------------------------------------------------

@router.get("/")
def home(request: Request):

    user = get_user(request)

    if user:
        return RedirectResponse(
            url=with_root_path(request, "/panel"),
            status_code=302
        )

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": "",
            "rp": get_base_path(request)
        }
    )


@router.get("/login")
def login_get(request: Request):

    user = get_user(request)

    if user:
        return RedirectResponse(
            url=with_root_path(request, "/panel"),
            status_code=302
        )

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": "",
            "rp": get_base_path(request)
        }
    )


@router.post("/login")
def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    remember: str | None = Form(None),
):
    username = (username or "").strip()
    password = password or ""
    user = None
    try:
        with db_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                      u.id_global,
                      u.username,
                      u.email,
                      u.first_name,
                      u.last_name,
                      u.password_hash,
                      u.activo,
                      r.itf_code AS role_code
                    FROM arbimaps_app.users u
                    JOIN arbimaps_app.roles r ON r.t_id = u.rol_id
                    WHERE u.username = %s
                    """,
                    (username,),
                )
                user = cur.fetchone()
    except Exception:
        logger.exception("Login DB connection error for username=%s", username)
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Error de conexion. Intenta nuevamente en unos minutos.",
                "rp": get_base_path(request),
            },
            status_code=503,
        )

    if not user or not user["activo"]:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Usuario o password invalidos",
                "rp": get_base_path(request),
            },
            status_code=401,
        )

    try:
        valid_password = bool(user["password_hash"]) and verify_password(password, user["password_hash"])
    except Exception:
        valid_password = False

    if not valid_password:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Usuario o password invalidos",
                "rp": get_base_path(request),
            },
            status_code=401,
        )

    role_code = (user["role_code"] or DEFAULT_ROLE).strip() or DEFAULT_ROLE

    session_user = {
        "id_global": _session_json_safe(user.get("id_global")),
        "username": _session_json_safe(user.get("username")),
        "email": _session_json_safe(user.get("email")),
        "first_name": _session_json_safe(user.get("first_name")),
        "last_name": _session_json_safe(user.get("last_name")),
        "role": role_code,
        "auth_source": "local",
    }

    resp = RedirectResponse(
        url=with_root_path(request, "/panel"),
        status_code=302
    )

    try:
        signed = signer.sign(json.dumps(session_user).encode("utf-8")).decode("utf-8")
    except Exception:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Error interno al crear la sesion. Intenta nuevamente.",
                "rp": get_base_path(request),
            },
            status_code=500,
        )

    resp.set_cookie(
        COOKIE_NAME,
        signed,
        httponly=True,
        samesite="lax",
        path="/",
    )

    return resp


@router.get("/logout")
def logout(request: Request):

    resp = RedirectResponse(
        url=with_root_path(request, "/"),
        status_code=302
    )

    resp.delete_cookie(COOKIE_NAME, path="/")

    return resp


# -------------------------------------------------
# PANEL
# -------------------------------------------------

@router.get("/panel")
@router.get("/panel/")
def panel(request: Request):

    user = get_user(request)

    if not user:
        return RedirectResponse(
            url=with_root_path(request, "/login"),
            status_code=302
        )

    return _render_panel(request, user, view="visor")


@router.get("/panel/buscar")
def panel_buscar(request: Request):

    user = get_user(request)

    if not user:
        return RedirectResponse(
            url=with_root_path(request, "/login"),
            status_code=302
        )

    return _render_panel(request, user, view="buscar")


# -------------------------------------------------
# DOCUMENTOS (BOX)
# -------------------------------------------------

@router.get("/panel/soportes/explorar")
def soportes_explorar(request: Request):

    user = get_user(request)

    if not user:
        return RedirectResponse(
            url=with_root_path(request, "/login"),
            status_code=302
        )

    return _render_panel(request, user, view="box_explorer")


# -------------------------------------------------
# BUSCAR PREDIO
# -------------------------------------------------

@router.get("/panel/buscar/predio/{predio_id}")
def panel_buscar_predio(request: Request, predio_id: int):

    user = get_user(request)

    if not user:
        return RedirectResponse(
            url=with_root_path(request, "/login"),
            status_code=302
        )

    return _render_panel(
        request,
        user,
        view="buscar_predio",
        predio_id=predio_id
    )


# -------------------------------------------------
# ASIGNACIONES
# -------------------------------------------------

@router.get("/panel/asignaciones")
def panel_asignaciones(request: Request):
    user = get_user(request)

    if not user:
        return RedirectResponse(
            url=with_root_path(request, "/login"),
            status_code=302
        )

    if not _can_access_asignaciones(user):
        return RedirectResponse(
            url=with_root_path(request, "/panel"),
            status_code=302
        )

    return RedirectResponse(
        url=with_root_path(request, "/panel/asignaciones/cargas"),
        status_code=307
    )


@router.get("/panel/asignaciones/cargas")
def panel_asignaciones_cargas(request: Request):

    user = get_user(request)

    if not user:
        return RedirectResponse(
            url=with_root_path(request, "/login"),
            status_code=302
        )

    if not _can_access_asignaciones(user):
        return RedirectResponse(
            url=with_root_path(request, "/panel"),
            status_code=302
        )

    return _render_panel(
        request,
        user,
        view="asignaciones",
        asig_tab="cargas"
    )


@router.get("/panel/asignaciones/ver")
def panel_asignaciones_ver(request: Request):

    user = get_user(request)

    if not user:
        return RedirectResponse(
            url=with_root_path(request, "/login"),
            status_code=302
        )

    if not _can_access_asignaciones(user):
        return RedirectResponse(
            url=with_root_path(request, "/panel"),
            status_code=302
        )

    return _render_panel(
        request,
        user,
        view="asignaciones",
        asig_tab="ver"
    )


@router.get("/panel/asignaciones/detalle")
def panel_asignaciones_detalle(request: Request):

    user = get_user(request)

    if not user:
        return RedirectResponse(
            url=with_root_path(request, "/login"),
            status_code=302
        )

    if not _can_access_asignaciones(user):
        return RedirectResponse(
            url=with_root_path(request, "/panel"),
            status_code=302
        )

    return _render_panel(
        request,
        user,
        view="asignaciones",
        asig_tab="detalle"
    )


@router.get("/panel/asignaciones/edicion")
def panel_asignaciones_edicion(request: Request):

    user = get_user(request)

    if not user:
        return RedirectResponse(
            url=with_root_path(request, "/login"),
            status_code=302
        )

    if not _can_access_asignaciones(user):
        return RedirectResponse(
            url=with_root_path(request, "/panel"),
            status_code=302
        )

    subview = (request.query_params.get("subview") or "").strip().lower()
    asig_tab = "editar_predio" if subview == "editar_predio" else "edicion"

    return _render_panel(
        request,
        user,
        view="asignaciones",
        asig_tab=asig_tab
    )


# -------------------------------------------------
# USUARIOS
# -------------------------------------------------

@router.get("/panel/usuarios")
def panel_usuarios(request: Request):

    user = get_user(request)

    if not user:
        return RedirectResponse(
            url=with_root_path(request, "/login"),
            status_code=302
        )

    return _render_panel(request, user, view="usuarios")

# -------------------------------------------------
# validaciones_xtf
# -------------------------------------------------

@router.get("/panel/validacion-xtf")
def panel_validacion_xtf(request: Request):

    user = get_user(request)

    if not user:
        return RedirectResponse(
            url=with_root_path(request, "/login"),
            status_code=302
        )

    return _render_panel(request, user, view="validacion_xtf")


@router.post("/panel/validacion-xtf")
async def panel_validacion_xtf_upload(request: Request, file: UploadFile = File(...)):

    user = get_user(request)

    if not user:
        return RedirectResponse(
            url=with_root_path(request, "/login"),
            status_code=302
        )

    error = None
    result = None
    status_code = 200

    if not file.filename:
        error = "No se recibió archivo."
        status_code = 400
    elif not file.filename.lower().endswith(".xtf"):
        error = "Solo se permiten archivos con extensión .xtf"
        status_code = 400
    else:
        try:
            result = await xtf_service.save_xtf(file)
        except Exception as exc:
            error = f"Error al subir el archivo: {exc}"
            status_code = 500

    return _render_panel(
        request,
        user,
        view="validacion_xtf",
        status_code=status_code,
        result=result,
        error=error,
    )

# -------------------------------------------------
# DEBUG
# -------------------------------------------------

@router.get("/debug/me")
def debug_me(request: Request):

    user = get_user(request)

    if not user:
        return {"user": None, "effective_role": None}

    role = get_user_role(user)

    return {
        "user": user,
        "effective_role": role
    }

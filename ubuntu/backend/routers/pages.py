import os
import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from core.asignaciones import (
    can_access_assignment_model,
    is_assignment_internal_rollout_active,
    is_assignment_internal_user,
)
from routers.auth import (
    DEFAULT_ROLE,
    build_session_payload,
    clear_session_cookie,
    get_current_tenant_from_session,
    get_user,
    get_user_role,
    normalize_role,
    set_session_cookie,
    sign_session_payload,
)
from services.session_auth import authenticate_user_for_tenant
from services.xtf_validation_service import XTFValidationService
from tenants import TenantContext, get_connection_manager, get_registry


router = APIRouter()
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
xtf_service = XTFValidationService()

# si algn da usas /api
BASE_PATH = os.getenv("APP_BASE_PATH", "").rstrip("/")
ASIGNACIONES_ROLES = {"admin", "coordinador", "digitalizador", "reconocedor", "soporte", "lider_reconocimiento"}


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


def _default_visor_geoserver_layers(tenant: TenantContext | None) -> str:
    if tenant is not None:
        configured_layers = str(tenant.geoserver_layers or "").strip()
        if configured_layers:
            return configured_layers

        workspace = str(tenant.geoserver_workspace or "").strip()
        if workspace:
            return f"{workspace}:Base_Principal"

    return os.getenv("VISOR_GEOSERVER_LAYERS", "A_Base_Principal:Base_Principal")


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
    tenant = _safe_get_current_tenant(request)
    context: dict[str, object] = {
        "request": request,
        "user": user.get("username") or user.get("email") or "usuario",
        "current_user_id": user.get("id_global"),
        "current_username": user.get("username") or user.get("email") or "usuario",
        "rp": get_base_path(request),
        "view": view,
        "effective_role": role,
        "can_access_asignaciones": can_access_asignaciones,
        "asig_model_name": "arb",
        "asig_schema_main": (tenant.schemas.main if tenant else "").strip(),
        "asig_schema_work": (tenant.schemas.work if tenant else "").strip(),
        "asig_supports_package_export": True,
        "asig_supports_retorno_xtf": True,
        "asig_internal_rollout_active": is_assignment_internal_rollout_active("arb"),
        "asig_internal_access_granted": is_assignment_internal_user(user, role=role),
        "visor_geoserver_layers": _default_visor_geoserver_layers(tenant),
        "current_municipality_code": user.get("municipality_code"),
        "current_municipality_name": user.get("municipality_name"),
    }

    context.update(extra_context)

    return templates.TemplateResponse("panel.html", context, status_code=status_code)


def _active_municipalities(request: Request) -> list[dict[str, str]]:
    registry = get_registry(request.app)
    return [
        {"code": config.code, "name": config.name}
        for config in registry.active()
    ]


def _login_template_context(
    request: Request,
    *,
    error: str = "",
    municipality_code: str = "",
    username: str = "",
) -> dict[str, Any]:
    return {
        "request": request,
        "error": error,
        "rp": get_base_path(request),
        "municipalities": _active_municipalities(request),
        "municipality_code": municipality_code,
        "username": username,
    }


def _safe_get_current_tenant(request: Request) -> TenantContext | None:
    try:
        return get_current_tenant_from_session(request)
    except Exception:
        return None


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
        _login_template_context(request)
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
        _login_template_context(request)
    )


@router.post("/login")
def login_post(
    request: Request,
    municipality_code: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    remember: str | None = Form(None),
):
    print("LOGIN POST ENTERED - municipality_code:", municipality_code, "username:", username, flush=True)
    municipality_code = (municipality_code or "").strip().lower()
    username = (username or "").strip()
    password = password or ""
    registry = get_registry(request.app)

    try:
        municipality = registry.require_active(municipality_code)
        tenant = TenantContext.from_config(municipality)
    except Exception as exc:
        print("LOGIN POST RESOLVE TENANT EXCEPTION:", exc, flush=True)
        logger.exception("Error resolving tenant for code %r: %s", municipality_code, exc)
        return templates.TemplateResponse(
            "login.html",
            _login_template_context(
                request,
                error="Municipio invalido o inactivo.",
                municipality_code=municipality_code,
                username=username,
            ),
            status_code=400,
        )

    manager = get_connection_manager(request.app)
    if manager is None:
        logger.error("ConnectionManager no inicializado durante login")
        return templates.TemplateResponse(
            "login.html",
            _login_template_context(
                request,
                error="Servicio de autenticacion no disponible.",
                municipality_code=municipality_code,
                username=username,
            ),
            status_code=500,
        )
    user = None
    try:
        user = authenticate_user_for_tenant(
            request,
            tenant,
            username=username,
            password=password,
        )
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        logger.exception(
            "Login DB connection error municipality=%s username=%s",
            municipality_code,
            username,
        )
        return templates.TemplateResponse(
            "login.html",
            _login_template_context(
                request,
                error="Error de conexion. Intenta nuevamente en unos minutos.",
                municipality_code=municipality_code,
                username=username,
            ),
            status_code=503,
        )

    if not user:
        return templates.TemplateResponse(
            "login.html",
            _login_template_context(
                request,
                error="Usuario o password invalidos",
                municipality_code=municipality_code,
                username=username,
            ),
            status_code=401,
        )

    role_code = (user["role_code"] or DEFAULT_ROLE).strip() or DEFAULT_ROLE

    session_user = build_session_payload(
        user_id=_session_json_safe(user.get("id_global")),
        username=_session_json_safe(user.get("username")),
        email=_session_json_safe(user.get("email")),
        first_name=_session_json_safe(user.get("first_name")),
        last_name=_session_json_safe(user.get("last_name")),
        role=role_code,
        municipality_code=tenant.municipality_code,
        municipality_name=tenant.municipality_name,
        remember=bool(remember),
    )

    resp = RedirectResponse(
        url=with_root_path(request, "/panel"),
        status_code=302
    )

    try:
        signed = sign_session_payload(session_user)
    except Exception:
        return templates.TemplateResponse(
            "login.html",
            _login_template_context(
                request,
                error="Error interno al crear la sesion. Intenta nuevamente.",
                municipality_code=municipality_code,
                username=username,
            ),
            status_code=500,
        )

    set_session_cookie(resp, signed, remember=bool(remember))

    return resp


@router.get("/logout")
def logout(request: Request):

    resp = RedirectResponse(
        url=with_root_path(request, "/"),
        status_code=302
    )

    clear_session_cookie(resp)

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

    role = _effective_role(user)
    if role in {"admin", "soporte"}:
        return RedirectResponse(
            url=with_root_path(request, "/panel/asignaciones/cargas"),
            status_code=307
        )
    else:
        return RedirectResponse(
            url=with_root_path(request, "/panel/asignaciones/ver"),
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

    role = _effective_role(user)
    if role not in {"admin", "soporte"}:
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

    raise HTTPException(
        status_code=404,
        detail="La página de edición no está disponible."
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

    if _effective_role(user) not in {"admin", "coordinador", "soporte"}:
        return RedirectResponse(
            url=with_root_path(request, "/panel"),
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
async def panel_validacion_xtf_upload(
    request: Request,
    file: UploadFile = File(...),
):

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
            result = await xtf_service.save_xtf(
                file,
                municipality_code=user.get("municipality_code"),
            )
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
# NOTIFICACIONES
# -------------------------------------------------

@router.get("/panel/notificaciones")
def panel_notificaciones(request: Request):

    user = get_user(request)

    if not user:
        return RedirectResponse(
            url=with_root_path(request, "/login"),
            status_code=302
        )

    return _render_panel(request, user, view="notificaciones")

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
        "effective_role": role,
        "municipality_code": user.get("municipality_code"),
        "municipality_name": user.get("municipality_name"),
    }

# -------------------------------------------------
# PANEL DE CONTROL DE SEGUIMIENTO
# -------------------------------------------------

@router.get("/panel/panel_control")
def panel_panel_control(request: Request):

    user = get_user(request)

    if not user:
        return RedirectResponse(
            url=with_root_path(request, "/login"),
            status_code=302
        )

    return _render_panel(request, user, view="panel_control")


# -------------------------------------------------
# SOLICITUDES DE ASIGNACION
# -------------------------------------------------

@router.get("/panel/solicitudes_asignaciones")
def panel_solicitudes_asignaciones(request: Request):

    user = get_user(request)

    if not user:
        return RedirectResponse(
            url=with_root_path(request, "/login"),
            status_code=302
        )

    if _effective_role(user) != "coordinador":
        return RedirectResponse(
            url=with_root_path(request, "/panel"),
            status_code=302
        )

    return _render_panel(request, user, view="solicitudes_asignaciones")

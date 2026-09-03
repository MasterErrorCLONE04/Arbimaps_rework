from datetime import datetime, timezone
import logging
import os
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from psycopg2.extras import RealDictCursor

from tenants import TenantContext, ConnectionManagerError, get_connection_manager, app_table
from services.session_auth import (
    DEFAULT_ROLE,
    build_session_payload,
    get_current_tenant_from_session,
    get_current_user_from_session,
    set_session_cookie,
    sign_session_payload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sso", tags=["sso"])

SHARED_JWT_SECRET = os.getenv("SHARED_JWT_SECRET", "super_secret_arbimaps_jwt_key_2026")
PHP_WEB_URL = os.getenv("PHP_WEB_URL", "http://localhost/neiva/Arbimaps/index.php")


@router.get("/redirect-to-php")
def redirect_to_php(
    request: Request,
    target: str = Query("dashboardcopy", description="Página destino en Web PHP"),
):
    try:
        current_user = get_current_user_from_session(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    username = current_user.get("username")
    user_id = current_user.get("user_id") or current_user.get("id_global")
    role_code = current_user.get("role_code") or current_user.get("role")

    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sesión sin usuario válido.",
        )

    now = int(time.time())
    payload = {
        "iss": "arbimaps_python_gis",
        "sub": username,
        "user_id": user_id,
        "role": role_code,
        "iat": now,
        "exp": now + 60,
        "jti": str(uuid.uuid4()),
    }

    try:
        sso_token = jwt.encode(payload, SHARED_JWT_SECRET, algorithm="HS256")
    except Exception as exc:
        logger.exception("Error generando token JWT SSO: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al generar token SSO.",
        ) from exc

    base_url = PHP_WEB_URL.rstrip("/")
    target_url = f"{base_url}?action=sso_login&sso_token={sso_token}&page={target}"

    return RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)


@router.get("/login")
def sso_login(
    request: Request,
    token: str = Query(..., description="Token JWT SSO enviado desde la plataforma PHP"),
):
    try:
        payload = jwt.decode(token, SHARED_JWT_SECRET, algorithms=["HS256"])
    except JWTError as exc:
        logger.warning("Token JWT SSO inválido o expirado: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token SSO inválido o expirado.",
        ) from exc

    username = str(payload.get("sub") or "").strip()
    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload JWT sin usuario ('sub').",
        )

    try:
        tenant = get_current_tenant_from_session(request)
    except HTTPException:
        from tenants.dependencies import get_municipality_registry
        registry = get_municipality_registry(request)
        muni_code = os.getenv("DEFAULT_MUNICIPALITY_CODE", "neiva").strip().lower()
        if registry.has(muni_code) and registry.is_active(muni_code):
            tenant = TenantContext.from_config(registry.get(muni_code))
        else:
            active_configs = registry.active()
            if not active_configs:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="No hay municipio activo configurado.",
                )
            tenant = TenantContext.from_config(active_configs[0])

    manager = get_connection_manager(request.app)
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ConnectionManager no inicializado.",
        )

    try:
        with manager.connection(tenant) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT
                      u.id_global,
                      u.username,
                      u.email,
                      u.first_name,
                      u.last_name,
                      u.activo,
                      COALESCE(r.itf_code, u.rol, 'consulta') AS role_code,
                      COALESCE(r.permite_python, true) AS permite_python
                    FROM {app_table(tenant, 'users')} u
                    LEFT JOIN {app_table(tenant, 'roles')} r ON r.t_id = u.rol_id OR r.itf_code = u.rol
                    WHERE (u.username = %s OR u.email = %s OR u.first_name = %s)
                      AND u.activo = true
                    LIMIT 1
                    """,
                    (username, username, username),
                )
                user = cur.fetchone()
    except Exception as exc:
        logger.exception("Error al consultar usuario SSO en base de datos: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Error al consultar usuario en base de datos: {exc}",
        ) from exc

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario '{username}' no encontrado o inactivo en la base de datos.",
        )

    if user.get("permite_python") is False:
        role_disp = user.get("role_code") or "desconocido"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Acceso denegado: El rol '{role_disp}' no tiene permisos para la plataforma GIS.",
        )

    role_code = user.get("role_code") or DEFAULT_ROLE

    session_user = build_session_payload(
        user_id=user.get("id_global"),
        username=user.get("username"),
        email=user.get("email"),
        first_name=user.get("first_name"),
        last_name=user.get("last_name"),
        role=role_code,
        municipality_code=tenant.municipality_code,
        municipality_name=tenant.municipality_name,
    )

    signed = sign_session_payload(session_user)
    response = RedirectResponse(url="/panel", status_code=status.HTTP_302_FOUND)
    set_session_cookie(response, signed)

    return response

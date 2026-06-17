from typing import Any

from fastapi import HTTPException, Request, status

from core.asignaciones import assignment_access_denied_detail, can_access_assignment_model
from services.session_auth import (
    COOKIE_NAME,
    DEFAULT_ROLE,
    SESSION_VERSION,
    build_session_payload,
    clear_session_cookie,
    get_current_tenant_from_session,
    get_current_user_from_session,
    get_session_payload,
    set_session_cookie,
    sign_session_payload,
    signer,
)

ROLE_ALIASES = {
    "administrador": "admin",
    "administrator": "admin",
    "coord": "coordinador",
    "coordinator": "coordinador",
}


def normalize_role(role: str | None) -> str:
    value = (role or "").strip().lower()
    mapped = ROLE_ALIASES.get(value)
    if mapped:
        return mapped

    if value.startswith("admin") or value.startswith("administr"):
        return "admin"
    if value.startswith("coordinador") or value.startswith("coord"):
        return "coordinador"

    return value


def get_current_tenant(request: Request):
    return get_current_tenant_from_session(request)


def get_current_user(request: Request) -> dict[str, Any]:
    return get_current_user_from_session(request)


def get_user(request: Request) -> dict[str, Any] | None:
    try:
        return get_current_user_from_session(request)
    except HTTPException:
        return None


def require_user(request: Request) -> dict[str, Any]:
    return get_current_user_from_session(request)


def get_user_role(user: dict[str, Any]) -> str:
    role = normalize_role(
        user.get("role_code")
        or user.get("role")
        or user.get("rol")
    )
    if role:
        return role
    return normalize_role(DEFAULT_ROLE)


def require_roles(*allowed_roles: str):
    allowed = {normalize_role(r) for r in allowed_roles if r and str(r).strip()}

    def _dependency(request: Request) -> dict[str, Any]:
        user = require_user(request)
        role = normalize_role(get_user_role(user))
        if allowed and role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Rol '{role}' sin permisos para esta accion",
            )
        return user

    return _dependency


def require_assignment_roles(*allowed_roles: str):
    allowed = {normalize_role(r) for r in allowed_roles if r and str(r).strip()}

    def _dependency(request: Request) -> dict[str, Any]:
        user = require_user(request)
        role = normalize_role(get_user_role(user))
        if allowed and role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Rol '{role}' sin permisos para esta accion",
            )
        if not can_access_assignment_model(user, role=role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=assignment_access_denied_detail(),
            )
        return user

    return _dependency


def check_admin_soporte_isolation(conn, tenant, user: dict, assignment_id: int) -> None:
    role = normalize_role(get_user_role(user))
    if role not in {"admin", "soporte"}:
        return

    # Derive app_schema
    app_schema = "arbimaps_app"
    if tenant is not None:
        if hasattr(tenant, "schemas") and tenant.schemas and hasattr(tenant.schemas, "app"):
            app_schema = tenant.schemas.app
        elif isinstance(tenant, str):
            app_schema = tenant

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT cu.rol
            FROM {app_schema}.asignacion a
            LEFT JOIN {app_schema}.users cu ON cu.username = a.creado_por
            WHERE a.id = %s
            """,
            (assignment_id,)
        )
        row = cur.fetchone()
        if not row:
            return

        creator_role = normalize_role(row[0] or "")
        if not creator_role:
            return

        if role == "admin" and creator_role == "soporte":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acceso denegado: este trabajo fue creado por un usuario de Soporte y no puede ser accedido por un Administrador."
            )
        if role == "soporte" and creator_role == "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acceso denegado: este trabajo fue creado por un Administrador y no puede ser accedido por un usuario de Soporte."
            )

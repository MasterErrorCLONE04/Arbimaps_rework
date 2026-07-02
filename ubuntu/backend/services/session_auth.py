import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import Response
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from psycopg2.extras import RealDictCursor

from routers.security import verify_password
from tenants import (
    ConnectionManagerError,
    MunicipalityConfigError,
    MunicipalityInactiveError,
    MunicipalityNotFoundError,
    TenantContext,
    app_table,
    get_connection_manager,
    get_registry,
)


def _get_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


import sys

COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "session_user")

SECRET = os.getenv("SESSION_SECRET")
if not SECRET or SECRET == "cambia-esto-por-una-clave-larga":
    if (
        "PYTEST_CURRENT_TEST" in os.environ
        or "pytest" in sys.modules
        or any("pytest" in arg for arg in sys.argv)
    ):
        SECRET = "test-secret-key-for-testing-purposes-only-32-chars-long"
    else:
        raise RuntimeError(
            "La variable de entorno SESSION_SECRET no esta configurada o usa el valor por defecto inseguro. "
            "Es obligatoria para asegurar la integridad de las sesiones en produccion."
        )

SESSION_VERSION = 2
DEFAULT_ROLE = os.getenv("DEFAULT_ROLE", "digitalizador")
SESSION_MAX_AGE_SECONDS = int(os.getenv("SESSION_MAX_AGE_SECONDS", "43200"))
SESSION_REMEMBER_MAX_AGE_SECONDS = int(
    os.getenv("SESSION_REMEMBER_MAX_AGE_SECONDS", str(60 * 60 * 24 * 14))
)
SESSION_COOKIE_SECURE = _get_bool_env("SESSION_COOKIE_SECURE", True)
SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "lax").strip().lower() or "lax"
SESSION_COOKIE_PATH = os.getenv("SESSION_COOKIE_PATH", "/") or "/"

signer = TimestampSigner(SECRET)


def _tenant_gis_payload(tenant: TenantContext) -> dict[str, Any]:
    return {
        "geoserver_base_url": tenant.geoserver_base_url,
        "geoserver_workspace": tenant.geoserver_workspace,
        "wms_base_url": tenant.wms_base_url,
        "geoserver_layers": tenant.geoserver_layers,
    }


def _bind_tenant_state(request: Request, tenant: TenantContext) -> None:
    request.state.tenant_context = tenant
    request.state.tenant = tenant
    request.state.db = tenant.db
    request.state.schemas = tenant.schemas
    request.state.gis = _tenant_gis_payload(tenant)
    request.state.session_tenant_code = tenant.municipality_code


def _bind_user_state(request: Request, user: dict[str, Any]) -> None:
    request.state.current_user = user
    request.state.user = user


def _qualified_app_table(tenant: TenantContext, table_name: str) -> str:
    try:
        return app_table(tenant, table_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Schema tenant invalido.",
        ) from exc


def build_session_payload(
    *,
    user_id: Any,
    username: Any,
    email: Any,
    first_name: Any,
    last_name: Any,
    role: Any,
    municipality_code: str,
    municipality_name: str,
    remember: bool = False,
) -> dict[str, Any]:
    return {
        "session_version": SESSION_VERSION,
        "auth_source": "local",
        "user_id": user_id,
        "id_global": user_id,
        "username": username,
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "role": role,
        "municipality_code": municipality_code,
        "municipality_name": municipality_name,
        "remember": remember,
    }


def sign_session_payload(payload: dict[str, Any]) -> str:
    return signer.sign(json.dumps(payload).encode("utf-8")).decode("utf-8")


def set_session_cookie(response: Response, signed_payload: str, *, remember: bool = False) -> None:
    max_age = SESSION_REMEMBER_MAX_AGE_SECONDS if remember else SESSION_MAX_AGE_SECONDS
    response.set_cookie(
        COOKIE_NAME,
        signed_payload,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite=SESSION_COOKIE_SAMESITE,
        path=SESSION_COOKIE_PATH,
        max_age=max_age,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path=SESSION_COOKIE_PATH)


def get_session_payload(request: Request) -> dict[str, Any] | None:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        payload, signed_at = signer.unsign(
            raw,
            max_age=SESSION_REMEMBER_MAX_AGE_SECONDS,
            return_timestamp=True,
        )
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict):
            return None
        max_age = (
            SESSION_REMEMBER_MAX_AGE_SECONDS
            if data.get("remember")
            else SESSION_MAX_AGE_SECONDS
        )
        age_seconds = (datetime.now(timezone.utc) - signed_at).total_seconds()
        if age_seconds > max_age:
            return None
        return data if isinstance(data, dict) else None
    except (BadSignature, SignatureExpired, Exception):
        return None


def get_current_tenant_from_session(request: Request) -> TenantContext:
    cached = getattr(request.state, "tenant_context", None)
    if isinstance(cached, TenantContext):
        return cached

    payload = get_session_payload(request)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesion no valida o inexistente.",
        )

    municipality_code = str(payload.get("municipality_code") or "").strip().lower()
    if not municipality_code:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesion sin municipio asociado.",
        )

    registry = get_registry(request.app)
    try:
        config = registry.require_active(municipality_code)
    except MunicipalityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Municipio de sesion no registrado.",
        ) from exc
    except MunicipalityInactiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Municipio de sesion inactivo.",
        ) from exc
    except MunicipalityConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    tenant = TenantContext.from_config(config)
    _bind_tenant_state(request, tenant)
    return tenant


def _fetch_active_user_for_tenant(request: Request, tenant: TenantContext) -> dict[str, Any]:
    payload = get_session_payload(request) or {}
    user_id = payload.get("user_id", payload.get("id_global"))
    username = str(payload.get("username") or "").strip()

    if user_id is None or not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesion incompleta.",
        )

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
                    """
                    SELECT
                      u.id_global,
                      u.username,
                      u.email,
                      u.first_name,
                      u.last_name,
                      u.activo,
                      r.itf_code AS role_code
                    FROM {users_table} u
                    JOIN {roles_table} r ON r.t_id = u.rol_id
                    WHERE u.id_global = %s
                      AND u.username = %s
                    LIMIT 1
                    """.format(
                        users_table=_qualified_app_table(tenant, "users"),
                        roles_table=_qualified_app_table(tenant, "roles"),
                    ),
                    (user_id, username),
                )
                row = cur.fetchone()
    except ConnectionManagerError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No fue posible validar la sesion contra la base municipal.",
        ) from exc

    if not row or not row.get("activo"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no valido para el municipio autenticado.",
        )

    return {
        "session_version": payload.get("session_version", SESSION_VERSION),
        "auth_source": payload.get("auth_source", "local"),
        "user_id": row.get("id_global"),
        "id_global": row.get("id_global"),
        "username": row.get("username"),
        "email": row.get("email"),
        "first_name": row.get("first_name"),
        "last_name": row.get("last_name"),
        "role": row.get("role_code") or payload.get("role") or DEFAULT_ROLE,
        "role_code": row.get("role_code"),
        "municipality_code": tenant.municipality_code,
        "municipality_name": tenant.municipality_name,
    }


def get_current_user_from_session(request: Request) -> dict[str, Any]:
    cached = getattr(request.state, "current_user", None)
    if isinstance(cached, dict):
        return cached

    tenant = get_current_tenant_from_session(request)
    user = _fetch_active_user_for_tenant(request, tenant)
    _bind_user_state(request, user)
    return user


def authenticate_user_for_tenant(
    request: Request,
    tenant: TenantContext,
    *,
    username: str,
    password: str,
) -> dict[str, Any] | None:
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
                    FROM {users_table} u
                    JOIN {roles_table} r ON r.t_id = u.rol_id
                    WHERE u.username = %s
                    LIMIT 1
                    """.format(
                        users_table=_qualified_app_table(tenant, "users"),
                        roles_table=_qualified_app_table(tenant, "roles"),
                    ),
                    (username,),
                )
                user = cur.fetchone()
    except ConnectionManagerError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No fue posible validar las credenciales contra la base municipal.",
        ) from exc

    if not user or not user.get("activo"):
        return None

    password_hash = user.get("password_hash")
    if not password_hash or not verify_password(password, password_hash):
        return None

    return user

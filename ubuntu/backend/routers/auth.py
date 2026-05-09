import json
import os
from typing import Any

from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, Signer
from psycopg2.extras import RealDictCursor

from core.asignaciones import assignment_access_denied_detail, can_access_assignment_model
from routers.db import db_conn

COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "session_user")
SECRET = os.getenv("SESSION_SECRET", "cambia-esto-por-una-clave-larga")
signer = Signer(SECRET)

DEFAULT_ROLE = os.getenv("DEFAULT_ROLE", "digitalizador")

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

    # Accept common DB variants like:
    # - administrador, administrador_municipal, admin_local
    # - coordinador_zona, coord_mpio
    if value.startswith("admin") or value.startswith("administr"):
        return "admin"
    if value.startswith("coordinador") or value.startswith("coord"):
        return "coordinador"

    return value


def get_user(request: Request) -> dict[str, Any] | None:
    """
    Lee el usuario autenticado desde la cookie de sesión.

    Estructura esperada (creada en pages.py):
      {
        "id_global": ...,
        "username": "...",
        "email": "...",
        "first_name": "...",
        "last_name": "...",
        "role": "admin|coordinador|digitalizador|reconocedor",
        "auth_source": "local"
      }
    """
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        payload = signer.unsign(raw).decode("utf-8")
        return json.loads(payload)
    except (BadSignature, Exception):
        return None


def require_user(request: Request) -> dict[str, Any]:
    user = get_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
        )
    return user


def _get_user_record_by_id(user_id: int) -> dict | None:
    """
    Devuelve el registro activo del usuario y su rol desde arbimaps_app.
    """
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
                  u.activo,
                  r.itf_code AS role_code
                FROM arbimaps_app.users u
                JOIN arbimaps_app.roles r ON r.t_id = u.rol_id
                WHERE u.id_global = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
    if not row or not row.get("activo"):
        return None
    return row


def get_user_role(user: dict[str, Any]) -> str:
    """
    Rol efectivo del usuario.

    - Primero: rol en Postgres (join users/roles usando id_global).
    - Si falla, usa el rol que viene en la cookie.
    - Si tampoco hay, retorna DEFAULT_ROLE.
    """
    user_id = user.get("id_global")
    if user_id is not None:
        try:
            row = _get_user_record_by_id(int(user_id))
        except Exception:
            row = None
        if row and row.get("role_code"):
            return normalize_role(row["role_code"])

    role = normalize_role(
        user.get("role")
        or user.get("rol")
        or user.get("role_code")
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
                detail=f"Rol '{role}' sin permisos para esta acción",
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
                detail=f"Rol '{role}' sin permisos para esta acciÃ³n",
            )
        if not can_access_assignment_model(user, role=role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=assignment_access_denied_detail(),
            )
        return user

    return _dependency

import logging
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from psycopg2 import IntegrityError
from psycopg2.extras import RealDictCursor

from routers.auth import get_current_tenant, get_current_user, get_user_role
from routers.security import hash_password
from tenants import TenantContext, get_tenant_db_connection

router = APIRouter(prefix="/usuarios", tags=["usuarios"])
logger = logging.getLogger(__name__)

ALLOWED_ROLES = ("admin", "coordinador", "digitalizador", "reconocedor")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validated_identifier(name: str) -> str:
    value = (name or "").strip()
    if not IDENT_RE.match(value):
        raise HTTPException(status_code=500, detail="Identificador tenant invalido.")
    return value


def _app_table(tenant: TenantContext, table_name: str) -> str:
    schema = _validated_identifier(tenant.schemas.app)
    table = _validated_identifier(table_name)
    return f"{schema}.{table}"


def _rollback_safely(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def _require_admin(user: dict[str, Any]) -> None:
    role = get_user_role(user)
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Rol '{role}' sin permisos para esta accion",
        )


def _normalized_role(value: str) -> str:
    role = (value or "").strip().lower()
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Rol invalido")
    return role


def _normalized_email(value: str | None) -> str | None:
    email = value.strip() if value else None
    if email and "@" not in email:
        raise HTTPException(status_code=400, detail="Email invalido")
    return email


def _get_role_id(conn, tenant: TenantContext, role_code: str) -> int:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"SELECT t_id FROM {_app_table(tenant, 'roles')} WHERE itf_code = %s",
            (role_code,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="Rol invalido")
    return int(row["t_id"])


class UsuarioCreate(BaseModel):
    username: str = Field(min_length=3)
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    rol: str
    email: str | None = None
    activo: bool = True
    password: str | None = None


class UsuarioUpdate(BaseModel):
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    rol: str
    email: str | None = None
    activo: bool = True
    password: str | None = None


@router.get("/roles")
def listar_roles(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    _require_admin(current_user)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT itf_code
                FROM {_app_table(tenant, 'roles')}
                ORDER BY itf_code
                """
            )
            rows = cur.fetchall()
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception(
            "Error listando roles municipality=%s schema=%s",
            tenant.municipality_code,
            tenant.schemas.app,
        )
        raise HTTPException(status_code=500, detail=f"Error consultando roles: {exc}") from exc

    names = [r["itf_code"] for r in rows]
    return [name for name in names if name in ALLOWED_ROLES]


@router.post("/", status_code=status.HTTP_201_CREATED)
def crear_usuario(
    body: UsuarioCreate,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    _require_admin(current_user)
    role = _normalized_role(body.rol)
    email = _normalized_email(body.email)
    username = body.username.strip()
    if not body.password:
        raise HTTPException(status_code=400, detail="Debe especificar una contraseña inicial")

    pwd_hash = hash_password(body.password)
    try:
        role_id = _get_role_id(conn, tenant, role)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT 1 FROM {_app_table(tenant, 'users')} WHERE username = %s",
                (username,),
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Ya existe un usuario con ese username en la BD.",
                )

            cur.execute(
                f"""
                INSERT INTO {_app_table(tenant, 'users')}
                  (username, email, first_name, last_name,
                   rol, rol_id, activo, password_hash)
                VALUES
                  (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id_global, username, email, first_name, last_name, rol, activo, creado_en
                """,
                (
                    username,
                    email,
                    body.first_name.strip(),
                    body.last_name.strip(),
                    role,
                    role_id,
                    bool(body.activo),
                    pwd_hash,
                ),
            )
            row = cur.fetchone()
        conn.commit()
        return row
    except HTTPException:
        _rollback_safely(conn)
        raise
    except IntegrityError as exc:
        _rollback_safely(conn)
        raise HTTPException(status_code=400, detail="No fue posible crear el usuario por restriccion de integridad.") from exc
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception(
            "Error creando usuario municipality=%s schema=%s username=%s",
            tenant.municipality_code,
            tenant.schemas.app,
            username,
        )
        raise HTTPException(status_code=500, detail=f"Error guardando en BD: {exc}") from exc


@router.get("/")
def listar_usuarios(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    _require_admin(current_user)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT id_global, username, email, first_name, last_name,
                       rol, activo, creado_en
                FROM {_app_table(tenant, 'users')}
                ORDER BY id_global
                """
            )
            return cur.fetchall()
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception(
            "Error listando usuarios municipality=%s schema=%s",
            tenant.municipality_code,
            tenant.schemas.app,
        )
        raise HTTPException(status_code=500, detail=f"Error consultando usuarios: {exc}") from exc


@router.put("/{id_global}")
def actualizar_usuario(
    id_global: int,
    body: UsuarioUpdate,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    _require_admin(current_user)
    role = _normalized_role(body.rol)
    email = _normalized_email(body.email)
    pwd_hash = hash_password(body.password) if body.password else None

    try:
        role_id = _get_role_id(conn, tenant, role)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE {_app_table(tenant, 'users')}
                SET
                  email = %s,
                  first_name = %s,
                  last_name = %s,
                  rol = %s,
                  rol_id = %s,
                  password_hash = COALESCE(%s, password_hash),
                  activo = %s
                WHERE id_global = %s
                RETURNING id_global, username, email, first_name, last_name,
                          rol, activo, creado_en
                """,
                (
                    email,
                    body.first_name.strip(),
                    body.last_name.strip(),
                    role,
                    role_id,
                    pwd_hash,
                    bool(body.activo),
                    id_global,
                ),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Usuario no encontrado")
        conn.commit()
        return row
    except HTTPException:
        _rollback_safely(conn)
        raise
    except IntegrityError as exc:
        _rollback_safely(conn)
        raise HTTPException(status_code=400, detail="No fue posible actualizar el usuario por restriccion de integridad.") from exc
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception(
            "Error actualizando usuario municipality=%s schema=%s id_global=%s",
            tenant.municipality_code,
            tenant.schemas.app,
            id_global,
        )
        raise HTTPException(status_code=500, detail=f"Error actualizando usuario: {exc}") from exc


@router.delete("/{id_global}")
def eliminar_usuario(
    id_global: int,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    _require_admin(current_user)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE {_app_table(tenant, 'users')}
                SET activo = FALSE
                WHERE id_global = %s
                RETURNING id_global, username
                """,
                (id_global,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Usuario no encontrado")
        conn.commit()
        return {"detail": f"Usuario {row['username']} eliminado"}
    except HTTPException:
        _rollback_safely(conn)
        raise
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception(
            "Error eliminando usuario municipality=%s schema=%s id_global=%s",
            tenant.municipality_code,
            tenant.schemas.app,
            id_global,
        )
        raise HTTPException(status_code=500, detail=f"Error eliminando usuario: {exc}") from exc

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from routers.auth import require_roles
from routers.db import db_conn
from routers.security import hash_password

router = APIRouter(prefix="/usuarios", tags=["usuarios"])

# Roles permitidos en la app
ALLOWED_ROLES = ("admin", "coordinador", "digitalizador", "reconocedor")


def _get_role_id(rol_code: str) -> int:
    rol_code = rol_code.lower().strip()
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT t_id FROM arbimaps_app.roles WHERE itf_code = %s",
                (rol_code,),
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
    password: str | None = None  # contraseña inicial opcional


class UsuarioUpdate(BaseModel):
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    rol: str
    email: str | None = None
    activo: bool = True
    password: str | None = None  # permite redefinir contraseña


@router.get("/roles")
def listar_roles():
    """Usado por usuarios.html para llenar el <select>."""
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT itf_code
                FROM arbimaps_app.roles
                ORDER BY itf_code
                """
            )
            rows = cur.fetchall()

    names = [r["itf_code"] for r in rows]
    # Filtrar a los roles que realmente usamos en la app
    names = [n for n in names if n in ALLOWED_ROLES]
    return names


@router.post("/", status_code=status.HTTP_201_CREATED)
def crear_usuario(
    body: UsuarioCreate,
    _admin: dict = Depends(require_roles("admin")),
):
    rol = body.rol.lower().strip()
    if rol not in ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Rol invalido")

    email = body.email.strip() if body.email else None
    if email and "@" not in email:
        raise HTTPException(status_code=400, detail="Email invalido")

    if not body.password:
        raise HTTPException(status_code=400, detail="Debe especificar una contraseña inicial")

    role_id = _get_role_id(rol)
    pwd_hash = hash_password(body.password)

    try:
        with db_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # evitar duplicados por username
                cur.execute(
                    "SELECT 1 FROM arbimaps_app.users WHERE username = %s",
                    (body.username,),
                )
                if cur.fetchone():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Ya existe un usuario con ese username en la BD.",
                    )

                cur.execute(
                    """
                    INSERT INTO arbimaps_app.users
                      (username, email, first_name, last_name,
                       rol, rol_id, activo, password_hash)
                    VALUES
                      (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id_global, username, email, first_name, last_name, rol, activo, creado_en
                    """,
                    (
                        body.username.strip(),
                        email,
                        body.first_name.strip(),
                        body.last_name.strip(),
                        rol,
                        role_id,
                        bool(body.activo),
                        pwd_hash,
                    ),
                )
                row = cur.fetchone()
                conn.commit()

        return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error guardando en BD: {e}")


@router.get("/")
def listar_usuarios():
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id_global, username, email, first_name, last_name,
                       rol, activo, creado_en
                FROM arbimaps_app.users
                ORDER BY id_global
                """
            )
            rows = cur.fetchall()
    return rows


@router.put("/{id_global}")
def actualizar_usuario(
    id_global: int,
    body: UsuarioUpdate,
    _admin: dict = Depends(require_roles("admin")),
):
    rol = body.rol.lower().strip()
    if rol not in ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Rol invalido")

    email = body.email.strip() if body.email else None
    if email and "@" not in email:
        raise HTTPException(status_code=400, detail="Email invalido")

    role_id = _get_role_id(rol)
    pwd_hash = hash_password(body.password) if body.password else None

    try:
        with db_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE arbimaps_app.users
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
                        rol,
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
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error actualizando usuario: {e}")


@router.delete("/{id_global}")
def eliminar_usuario(
    id_global: int,
    _admin: dict = Depends(require_roles("admin")),
):
    """
    Marca como inactivo al usuario en la BD (no lo borra físicamente).
    """
    try:
        with db_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE arbimaps_app.users
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
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error eliminando usuario: {e}")

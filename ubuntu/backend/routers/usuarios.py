import json
import logging
import re
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from psycopg2 import IntegrityError
from psycopg2.extras import Json, RealDictCursor

from routers.auth import get_current_tenant, get_current_user, get_user_role
from routers.security import hash_password
from tenants import TenantContext, get_tenant_db_connection
import repositories.asignaciones_repo as asignaciones_repo

router = APIRouter(prefix="/usuarios", tags=["usuarios"])
logger = logging.getLogger(__name__)

ALLOWED_ROLES = ("admin", "coordinador", "digitalizador", "reconocedor", "lider_tecnico", "lider_reconocimiento", "consulta", "consolidador", "soporte")
USERNAME_PREFIX_BY_ROLE = {
    "admin": "Admin_",
    "soporte": "Sop_",
    "coordinador": "Coord_",
    "lider_reconocimiento": "Lider_",
    "lider_tecnico": "Lider_",
    "reconocedor": "Rec_",
    "digitalizador": "Dig_",
    "consulta": "Cons_",
    "consolidador": "Conso_",
}
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
    if role not in {"admin", "soporte"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Rol '{role}' sin permisos para esta accion",
        )


def _require_admin_or_coordinador(user: dict[str, Any]) -> str:
    role = get_user_role(user)
    if role not in {"admin", "coordinador", "soporte", "lider_tecnico", "lider_reconocimiento"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Rol '{role}' sin permisos para esta accion",
        )
    return role


def _current_user_id(user: dict[str, Any]) -> int:
    try:
        value = user.get("id_global")
        if value is not None:
            return int(value)
    except (TypeError, ValueError):
        pass
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No fue posible identificar el usuario autenticado.",
    )


def _coordinator_scoped_body(user: dict[str, Any], body: "EquipoTrabajoUpsert") -> "EquipoTrabajoUpsert":
    role = get_user_role(user)
    if role == "coordinador":
        coordinator_id = _current_user_id(user)
        if int(body.coordinador_id) != coordinator_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes administrar equipos de otro coordinador.",
            )
    return body


def _require_own_equipo_if_coordinador(user: dict[str, Any], equipo: dict[str, Any]) -> None:
    if get_user_role(user) == "coordinador":
        if int(equipo.get("coordinador_id") or 0) != _current_user_id(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes administrar equipos de otro coordinador.",
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

def _username_prefix_for_role(role: str) -> str:
    normalized = _normalized_role(role)
    prefix = USERNAME_PREFIX_BY_ROLE.get(normalized)
    if not prefix:
        raise HTTPException(status_code=400, detail="No hay estructura de username definida para este rol.")
    return prefix


def _generate_next_username(cur, tenant: TenantContext, role: str) -> str:
    normalized = _normalized_role(role)
    prefix = _username_prefix_for_role(normalized)
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{tenant.schemas.app}:users:{normalized}",))
    pattern = f"^{re.escape(prefix)}([0-9]+)$"
    cur.execute(
        f"""
        WITH nombres AS (
            SELECT username
            FROM {_app_table(tenant, 'users')}
            WHERE username ~* %s
            UNION ALL
            SELECT username
            FROM {_app_table(tenant, 'solicitud_creacion_usuario')}
            WHERE estado = 'PENDIENTE'
              AND username ~* %s
        )
        SELECT COALESCE(MAX((substring(username from %s))::int), 0) AS max_num
        FROM nombres
        """,
        (pattern, pattern, pattern),
    )
    row = cur.fetchone() or {}
    next_num = int(row.get("max_num") or 0) + 1
    return f"{prefix}{next_num:03d}"


def _generate_next_cuadrilla_name(cur, tenant: TenantContext, coordinador_id: int) -> str:
    coordinator_id = int(coordinador_id)
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{tenant.schemas.app}:equipos_trabajo:{coordinator_id}",))
    pattern = r"^Cuadrilla_([0-9]+)$"
    cur.execute(
        f"""
        SELECT COALESCE(MAX((substring(nombre from %s))::int), 0) AS max_num
        FROM {_app_table(tenant, 'equipos_trabajo')}
        WHERE coordinador_id = %s
          AND nombre ~* %s
        """,
        (pattern, coordinator_id, pattern),
    )
    row = cur.fetchone() or {}
    next_num = int(row.get("max_num") or 0) + 1
    return f"Cuadrilla_{next_num:02d}"
def _validate_supervisor_id(conn, tenant: TenantContext, supervisor_id: int | None) -> int | None:
    if supervisor_id is None:
        return None
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT id_global, rol, activo
            FROM {_app_table(tenant, 'users')}
            WHERE id_global = %s
            """,
            (supervisor_id,),
        )
        row = cur.fetchone()
    if not row or not row.get("activo") or (row.get("rol") or "").lower() != "coordinador":
        raise HTTPException(status_code=400, detail="El supervisor debe ser un usuario coordinador activo.")
    return int(supervisor_id)


def _clear_reconocedores_supervisor(cur, tenant: TenantContext, supervisor_id: int) -> int:
    cur.execute(
        f"""
        UPDATE {_app_table(tenant, 'users')}
        SET supervisor = NULL
        WHERE NULLIF(TRIM(supervisor), '') = %s::text
          AND LOWER(COALESCE(rol, '')) = 'reconocedor'
        """,
        (str(supervisor_id),),
    )
    return cur.rowcount or 0


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


def _json_snapshot(value: Any) -> Json:
    return Json(value, dumps=lambda obj: json.dumps(obj, default=str, ensure_ascii=False))


def _backup_equipo_trabajo(
    cur,
    tenant: TenantContext,
    equipo: dict[str, Any],
    integrantes: list[dict[str, Any]],
    deleted_by: str | None,
) -> None:
    cur.execute(
        f"""
        INSERT INTO {_app_table(tenant, 'equipos_trabajo_backup')}
          (equipo_id_original, datos_equipo, datos_reconocedores, fecha_eliminacion, eliminado_por)
        VALUES
          (%s, %s, %s, COALESCE(%s, CURRENT_TIMESTAMP AT TIME ZONE 'America/Bogota'), %s)
        """,
        (
            equipo.get("equipo_id_original") or equipo.get("t_id") or equipo.get("equipo_id") or equipo.get("id"),
            _json_snapshot(equipo),
            _json_snapshot(integrantes),
            equipo.get("fecha_eliminacion"),
            deleted_by,
        ),
    )


class UsuarioCreate(BaseModel):
    username: str | None = Field(default=None, min_length=3)
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    rol: str
    email: str | None = None
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    supervisor_id: int | None = None
    activo: bool = True
    password: str | None = None

    @model_validator(mode="after")
    def _validate_contract_dates(self) -> "UsuarioCreate":
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValueError("La fecha de finalizacion no puede ser anterior al inicio del contrato.")
        return self


class UsuarioUpdate(BaseModel):
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    rol: str
    email: str | None = None
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    supervisor_id: int | None = None
    activo: bool = True
    password: str | None = None

    @model_validator(mode="after")
    def _validate_contract_dates(self) -> "UsuarioUpdate":
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValueError("La fecha de finalizacion no puede ser anterior al inicio del contrato.")
        return self


class EquipoTrabajoUpsert(BaseModel):
    nombre: str | None = Field(default=None, min_length=1)
    coordinador_id: int
    zona_id: int
    reconocedor_ids: list[int] = Field(default_factory=list)


def _fetch_equipo_trabajo(cur, tenant: TenantContext, equipo_id: int) -> dict[str, Any] | None:
    cur.execute(
        f"""
        SELECT
          et.t_id AS equipo_id,
          et.nombre,
          et.coordinador_id,
          u.username AS coordinador_username,
          et.zona_id,
          z.nombre AS zona_nombre,
          et.fecha_creacion,
          COALESCE(
            json_agg(
              json_build_object(
                'id_global', rec.id_global,
                'username', rec.username,
                'first_name', rec.first_name,
                'last_name', rec.last_name
              )
              ORDER BY rec.first_name, rec.last_name, rec.username
            ) FILTER (WHERE rec.id_global IS NOT NULL),
            '[]'::json
          ) AS reconocedores
        FROM {_app_table(tenant, 'equipos_trabajo')} et
        LEFT JOIN {_app_table(tenant, 'users')} u
          ON u.id_global = et.coordinador_id
        LEFT JOIN {_app_table(tenant, 'zonas_intervencion')} z
          ON z.t_id = et.zona_id
        LEFT JOIN {_app_table(tenant, 'equipo_reconocedores')} er
          ON er.equipo_id = et.t_id
        LEFT JOIN {_app_table(tenant, 'users')} rec
          ON rec.id_global = er.reconocedor_id
        WHERE et.t_id = %s
        GROUP BY
          et.t_id,
          et.nombre,
          et.coordinador_id,
          u.username,
          et.zona_id,
          z.nombre,
          et.fecha_creacion
        """,
        (equipo_id,),
    )
    return cur.fetchone()


def _validate_equipo_payload(
    cur,
    tenant: TenantContext,
    body: EquipoTrabajoUpsert,
    equipo_id: int | None = None,
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    cur.execute(
        f"""
        SELECT id_global, username, first_name, last_name, rol, activo
        FROM {_app_table(tenant, 'users')}
        WHERE id_global = %s
        """,
        (body.coordinador_id,),
    )
    coordinador = cur.fetchone()
    if not coordinador or not coordinador.get("activo") or (coordinador.get("rol") or "").lower() != "coordinador":
        raise HTTPException(status_code=400, detail="El encargado debe ser un usuario coordinador activo.")

    cur.execute(
        f"""
        SELECT t_id, nombre
        FROM {_app_table(tenant, 'zonas_intervencion')}
        WHERE t_id = %s
        """,
        (body.zona_id,),
    )
    zona = cur.fetchone()
    if not zona:
        raise HTTPException(status_code=400, detail="La zona de intervención no existe.")

    reconocedor_ids = [int(rid) for rid in body.reconocedor_ids if int(rid) > 0]
    reconocedor_ids = list(dict.fromkeys(reconocedor_ids))
    if reconocedor_ids:
        cur.execute(
            f"""
            SELECT id_global, username, first_name, last_name, rol, activo, supervisor
            FROM {_app_table(tenant, 'users')}
            WHERE id_global = ANY(%s)
            """,
            (reconocedor_ids,),
        )
        reconocedores = cur.fetchall()
        reconocedores_by_id = {int(row["id_global"]): row for row in reconocedores}
        missing = [rid for rid in reconocedor_ids if rid not in reconocedores_by_id]
        if missing:
            raise HTTPException(status_code=400, detail="Uno o más reconocedores no existen.")
        invalid = [
            rid for rid, row in reconocedores_by_id.items()
            if not row.get("activo") or (row.get("rol") or "").lower() != "reconocedor"
        ]
        if invalid:
            raise HTTPException(status_code=400, detail="Solo se permiten usuarios reconocedores activos.")

        coordinador_id_str = str(body.coordinador_id)
        not_under_coordinator = [
            rid for rid, row in reconocedores_by_id.items()
            if (str(row.get("supervisor") or "").strip() != coordinador_id_str)
        ]
        if not_under_coordinator:
            raise HTTPException(status_code=400, detail="Solo se permiten reconocedores que pertenezcan a ese coordinador.")

        cur.execute(
            f"""
            SELECT reconocedor_id, equipo_id
            FROM {_app_table(tenant, 'equipo_reconocedores')}
            WHERE reconocedor_id = ANY(%s)
            """,
            (reconocedor_ids,),
        )
        asignados = cur.fetchall()
        if equipo_id is None:
            if asignados:
                raise HTTPException(status_code=400, detail="Hay reconocedores que ya pertenecen a otra cuadrilla.")
        else:
            conflictos = [row for row in asignados if int(row["equipo_id"]) != int(equipo_id)]
            if conflictos:
                raise HTTPException(status_code=400, detail="Hay reconocedores que ya pertenecen a otra cuadrilla.")

    return coordinador, zona


def _sync_equipo_reconocedores(cur, tenant: TenantContext, equipo_id: int, reconocedor_ids: list[int]) -> None:
    cur.execute(
        f"DELETE FROM {_app_table(tenant, 'equipo_reconocedores')} WHERE equipo_id = %s",
        (equipo_id,),
    )
    if reconocedor_ids:
        for rid in reconocedor_ids:
            cur.execute(
                f"""
                INSERT INTO {_app_table(tenant, 'equipo_reconocedores')}
                  (equipo_id, reconocedor_id)
                VALUES (%s, %s)
                """,
                (equipo_id, rid),
            )


@router.get("/roles")
def listar_roles(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    _require_admin_or_coordinador(current_user)
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



@router.get("/siguiente-username")
def obtener_siguiente_username(
    rol: str,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    _require_admin_or_coordinador(current_user)
    role = _normalized_role(rol)
    try:
        asignaciones_repo.ensure_asignacion_tables(conn, tenant)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            username = _generate_next_username(cur, tenant, role)
        conn.commit()
        return {"username": username, "rol": role, "prefix": _username_prefix_for_role(role)}
    except HTTPException:
        _rollback_safely(conn)
        raise
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception(
            "Error generando username municipality=%s schema=%s role=%s",
            tenant.municipality_code,
            tenant.schemas.app,
            role,
        )
        raise HTTPException(status_code=500, detail=f"Error generando username: {exc}") from exc

@router.post("/", status_code=status.HTTP_201_CREATED)
def crear_usuario(
    body: UsuarioCreate,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    role_caller = get_user_role(current_user)
    if role_caller not in {"admin", "soporte", "coordinador"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Rol '{role_caller}' sin permisos para esta accion",
        )
    role = _normalized_role(body.rol)
    if role_caller == "coordinador":
        if role not in {"reconocedor", "digitalizador"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Como coordinador solo puedes crear usuarios con rol reconocedor o digitalizador.",
            )
        body.supervisor_id = _current_user_id(current_user)

    email = _normalized_email(body.email)
    supervisor_id = getattr(body, "supervisor_id", None)
    supervisor_id = _validate_supervisor_id(conn, tenant, supervisor_id) if role in {"reconocedor", "digitalizador"} else None
    username = ""
    if not body.password:
        raise HTTPException(status_code=400, detail="Debe especificar una contraseña inicial")

    pwd_hash = hash_password(body.password)
    try:
        role_id = _get_role_id(conn, tenant, role)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            username = body.username.strip() if body.username else ""
            if not username:
                username = _generate_next_username(cur, tenant, role)

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
                   rol, rol_id, supervisor, activo, password_hash, fecha_inicio, fecha_fin)
                VALUES
                  (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id_global, username, email, first_name, last_name, rol, activo,
                          creado_en, supervisor, fecha_inicio, fecha_fin
                """,
                (
                    username,
                    email,
                    body.first_name.strip(),
                    body.last_name.strip(),
                    role,
                    role_id,
                    supervisor_id,
                    bool(body.activo),
                    pwd_hash,
                    body.fecha_inicio,
                    body.fecha_fin,
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
    role = _require_admin_or_coordinador(current_user)
    where_scope = ""
    params: tuple[Any, ...] = ()
    if role in {"lider_reconocimiento", "lider_tecnico"}:
        where_scope = """
                WHERE LOWER(COALESCE(u.rol, '')) IN ('reconocedor', 'digitalizador', 'coordinador')
        """
        params = ()
    elif role == "coordinador":
        where_scope = """
                WHERE (
                    (LOWER(COALESCE(u.rol, '')) IN ('reconocedor', 'digitalizador')
                     AND NULLIF(TRIM(u.supervisor), '') = %s::text)
                    OR (LOWER(COALESCE(u.rol, '')) = 'coordinador' AND u.id_global = %s)
                )
        """
        params = (_current_user_id(current_user), _current_user_id(current_user))
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                  u.id_global,
                  u.username,
                  u.email,
                  u.first_name,
                  u.last_name,
                  u.rol,
                  u.activo,
                  u.creado_en,
                  u.fecha_inicio,
                  u.fecha_fin,
                  sup.id_global AS supervisor_id,
                  u.supervisor AS supervisor_raw,
                  COALESCE(
                    NULLIF(TRIM(CONCAT_WS(' ', sup.first_name, sup.last_name)), ''),
                    sup.username,
                    NULLIF(TRIM(u.supervisor), '')
                  ) AS supervisor_encargado
                FROM {_app_table(tenant, 'users')} u
                LEFT JOIN {_app_table(tenant, 'users')} sup
                  ON sup.id_global::text = NULLIF(TRIM(u.supervisor), '')
                {where_scope}
                ORDER BY u.id_global
                """,
                params,
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


@router.get("/equipos-trabajo")
def listar_equipos_trabajo(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    role = _require_admin_or_coordinador(current_user)
    where_scope = ""
    params: tuple[Any, ...] = ()
    if role == "coordinador":
        where_scope = "WHERE et.coordinador_id = %s"
        params = (_current_user_id(current_user),)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                  et.t_id AS equipo_id,
                  et.nombre,
                  et.coordinador_id,
                  u.username AS coordinador_username,
                  et.zona_id,
                  z.nombre AS zona_nombre,
                  et.fecha_creacion,
                  COALESCE(
                    json_agg(
                      json_build_object(
                        'id_global', rec.id_global,
                        'username', rec.username,
                        'first_name', rec.first_name,
                        'last_name', rec.last_name
                      )
                      ORDER BY rec.first_name, rec.last_name, rec.username
                    ) FILTER (WHERE rec.id_global IS NOT NULL),
                    '[]'::json
                  ) AS reconocedores
                FROM {_app_table(tenant, 'equipos_trabajo')} et
                LEFT JOIN {_app_table(tenant, 'users')} u
                  ON u.id_global = et.coordinador_id
                LEFT JOIN {_app_table(tenant, 'zonas_intervencion')} z
                  ON z.t_id = et.zona_id
                LEFT JOIN {_app_table(tenant, 'equipo_reconocedores')} er
                  ON er.equipo_id = et.t_id
                LEFT JOIN {_app_table(tenant, 'users')} rec
                  ON rec.id_global = er.reconocedor_id
                {where_scope}
                GROUP BY
                  et.t_id,
                  et.nombre,
                  et.coordinador_id,
                  u.username,
                  et.zona_id,
                  z.nombre,
                  et.fecha_creacion
                ORDER BY et.fecha_creacion DESC, et.nombre
                """,
                params,
            )
            return cur.fetchall()
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception(
            "Error listando equipos de trabajo municipality=%s schema=%s",
            tenant.municipality_code,
            tenant.schemas.app,
        )
        raise HTTPException(status_code=500, detail=f"Error consultando equipos de trabajo: {exc}") from exc


@router.get("/zonas-intervencion")
def listar_zonas_intervencion(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    _require_admin_or_coordinador(current_user)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT t_id, nombre
                FROM {_app_table(tenant, 'zonas_intervencion')}
                ORDER BY nombre
                """
            )
            return cur.fetchall()
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception(
            "Error listando zonas de intervencion municipality=%s schema=%s",
            tenant.municipality_code,
            tenant.schemas.app,
        )
        raise HTTPException(status_code=500, detail=f"Error consultando zonas de intervención: {exc}") from exc


@router.get("/reconocedores-disponibles")
def listar_reconocedores_disponibles(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
    exclude_equipo_id: int | None = None,
    coordinador_id: int | None = None,
):
    role = _require_admin_or_coordinador(current_user)
    if role == "coordinador":
        current_coordinator_id = _current_user_id(current_user)
        if coordinador_id is not None and int(coordinador_id) != current_coordinator_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes consultar reconocedores de otro coordinador.",
            )
        coordinador_id = current_coordinator_id
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                  u.id_global,
                  u.username,
                  u.first_name,
                  u.last_name,
                  u.supervisor
                FROM {_app_table(tenant, 'users')} u
                WHERE LOWER(COALESCE(u.rol, '')) = 'reconocedor'
                  AND u.activo = TRUE
                  AND (%s IS NULL OR NULLIF(TRIM(u.supervisor), '') = %s::text)
                  AND NOT EXISTS (
                    SELECT 1
                    FROM {_app_table(tenant, 'equipo_reconocedores')} er
                    WHERE er.reconocedor_id = u.id_global
                      AND (%s IS NULL OR er.equipo_id <> %s)
                  )
                ORDER BY u.first_name, u.last_name, u.username
                """,
                (coordinador_id, coordinador_id, exclude_equipo_id, exclude_equipo_id),
            )
            return cur.fetchall()
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception(
            "Error listando reconocedores disponibles municipality=%s schema=%s",
            tenant.municipality_code,
            tenant.schemas.app,
        )
        raise HTTPException(status_code=500, detail=f"Error consultando reconocedores disponibles: {exc}") from exc


@router.get("/{id_global}/asignaciones")
def listar_asignaciones_usuario(
    id_global: int,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    role = _require_admin_or_coordinador(current_user)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT id_global, username, first_name, last_name, rol, supervisor
                FROM {_app_table(tenant, 'users')}
                WHERE id_global = %s
                """,
                (id_global,),
            )
            usuario = cur.fetchone()
            if not usuario:
                raise HTTPException(status_code=404, detail="Usuario no encontrado")

            if role == "coordinador":
                target_role = _normalized_role(usuario.get("rol") or "")
                target_supervisor = str(usuario.get("supervisor") or "").strip()
                current_id = str(_current_user_id(current_user))
                is_subordinate = (
                    target_role in {"reconocedor", "digitalizador"}
                    and target_supervisor == current_id
                )
                is_self = str(usuario.get("id_global")) == current_id
                if not (is_subordinate or is_self):
                    raise HTTPException(
                        status_code=403,
                        detail="No tienes permisos para ver a este usuario o sus asignaciones."
                    )

            user_role = _normalized_role(usuario.get("rol") or "")
            if user_role not in {"reconocedor", "digitalizador"}:
                return {
                    "mostrar_cargas": False,
                    "pendientes": [],
                    "entregadas": [],
                }

            cur.execute(
                f"""
                SELECT
                  a.id,
                  a.titulo,
                  a.estado::text AS estado,
                  a.fecha_fin_asignada,
                  a.creado_en,
                  COALESCE(
                    NULLIF(TRIM(CONCAT_WS(' ', coord.first_name, coord.last_name)), ''),
                    coord.username,
                    a.creado_por
                  ) AS coordinador,
                  COALESCE(ap_s.total_predios, 0)::int AS total_predios
                FROM {_app_table(tenant, 'asignacion')} a
                LEFT JOIN {_app_table(tenant, 'users')} coord
                  ON coord.id_global = a.coordinador_asignado_id
                  OR coord.username = a.creado_por
                LEFT JOIN LATERAL (
                  SELECT COUNT(*) FILTER (WHERE ap.activo IS DISTINCT FROM FALSE) AS total_predios
                  FROM {_app_table(tenant, 'asignacion_predio')} ap
                  WHERE ap.asignacion_id = a.id
                ) ap_s ON TRUE
                WHERE a.usuario_asignado = %s
                ORDER BY a.fecha_fin_asignada NULLS LAST, a.creado_en DESC
                """,
                (usuario["username"],),
            )
            rows = cur.fetchall()
    except HTTPException:
        _rollback_safely(conn)
        raise
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception(
            "Error consultando asignaciones usuario municipality=%s schema=%s id_global=%s",
            tenant.municipality_code,
            tenant.schemas.app,
            id_global,
        )
        raise HTTPException(status_code=500, detail=f"Error consultando asignaciones del usuario: {exc}") from exc

    def _serialize(row: dict[str, Any]) -> dict[str, Any]:
        fecha_fin = row.get("fecha_fin_asignada")
        creado_en = row.get("creado_en")
        return {
            "id": row.get("id"),
            "titulo": row.get("titulo") or f"Asignacion {row.get('id')}",
            "estado": row.get("estado"),
            "fecha_fin_asignada": fecha_fin.isoformat() if hasattr(fecha_fin, "isoformat") else fecha_fin,
            "fecha_creacion": creado_en.isoformat() if hasattr(creado_en, "isoformat") else creado_en,
            "coordinador": row.get("coordinador") or "Sin coordinador",
            "total_predios": int(row.get("total_predios") or 0),
        }

    pendientes: list[dict[str, Any]] = []
    entregadas: list[dict[str, Any]] = []
    for row in rows:
        item = _serialize(row)
        if str(row.get("estado") or "").upper() == "SINCRONIZADO":
            entregadas.append(item)
        else:
            pendientes.append(item)

    return {
        "mostrar_cargas": True,
        "pendientes": pendientes,
        "entregadas": entregadas,
    }


@router.post("/equipos-trabajo", status_code=status.HTTP_201_CREATED)
def crear_equipo_trabajo(
    body: EquipoTrabajoUpsert,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    _require_admin_or_coordinador(current_user)
    body = _coordinator_scoped_body(current_user, body)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _validate_equipo_payload(cur, tenant, body, None)
            nombre_equipo = body.nombre.strip() if getattr(body, "nombre", None) else ""
            if not nombre_equipo:
                nombre_equipo = _generate_next_cuadrilla_name(cur, tenant, body.coordinador_id)
            cur.execute(
                f"""
                INSERT INTO {_app_table(tenant, 'equipos_trabajo')}
                  (nombre, coordinador_id, zona_id, fecha_creacion)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP AT TIME ZONE 'America/Bogota')
                RETURNING t_id
                """,
                (nombre_equipo, body.coordinador_id, body.zona_id),
            )
            row = cur.fetchone()
            equipo_id = int(row["t_id"])
            _sync_equipo_reconocedores(cur, tenant, equipo_id, list(dict.fromkeys([int(x) for x in body.reconocedor_ids if int(x) > 0])))
            detalle = _fetch_equipo_trabajo(cur, tenant, equipo_id)
        conn.commit()
        return detalle or {"equipo_id": equipo_id}
    except HTTPException:
        _rollback_safely(conn)
        raise
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception(
            "Error creando equipo de trabajo municipality=%s schema=%s",
            tenant.municipality_code,
            tenant.schemas.app,
        )
        raise HTTPException(status_code=500, detail=f"Error creando equipo de trabajo: {exc}") from exc



@router.get("/equipos-trabajo/siguiente-nombre")
def obtener_siguiente_nombre_equipo_trabajo(
    coordinador_id: int,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    _require_admin_or_coordinador(current_user)
    if get_user_role(current_user) == "coordinador":
        current_coordinator_id = _current_user_id(current_user)
        if int(coordinador_id) != current_coordinator_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes generar cuadrillas para otro coordinador.")
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _validate_supervisor_id(conn, tenant, coordinador_id)
            nombre = _generate_next_cuadrilla_name(cur, tenant, coordinador_id)
        conn.commit()
        return {"nombre": nombre, "coordinador_id": int(coordinador_id)}
    except HTTPException:
        _rollback_safely(conn)
        raise
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception(
            "Error generando nombre de cuadrilla municipality=%s schema=%s coordinador_id=%s",
            tenant.municipality_code,
            tenant.schemas.app,
            coordinador_id,
        )
        raise HTTPException(status_code=500, detail=f"Error generando nombre de cuadrilla: {exc}") from exc
@router.put("/equipos-trabajo/{id_global}")
def actualizar_equipo_trabajo(
    id_global: int,
    body: EquipoTrabajoUpsert,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    _require_admin_or_coordinador(current_user)
    body = _coordinator_scoped_body(current_user, body)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT t_id, nombre, coordinador_id
                FROM {_app_table(tenant, 'equipos_trabajo')}
                WHERE t_id = %s
                FOR UPDATE
                """,
                (id_global,),
            )
            equipo = cur.fetchone()
            if not equipo:
                raise HTTPException(status_code=404, detail="Equipo de trabajo no encontrado")
            _require_own_equipo_if_coordinador(current_user, equipo)

            _validate_equipo_payload(cur, tenant, body, id_global)
            cur.execute(
                f"""
                UPDATE {_app_table(tenant, 'equipos_trabajo')}
                SET nombre = %s,
                    coordinador_id = %s,
                    zona_id = %s
                WHERE t_id = %s
                """,
                ((body.nombre or equipo.get("nombre") or "").strip(), body.coordinador_id, body.zona_id, id_global),
            )
            _sync_equipo_reconocedores(cur, tenant, id_global, list(dict.fromkeys([int(x) for x in body.reconocedor_ids if int(x) > 0])))
            detalle = _fetch_equipo_trabajo(cur, tenant, id_global)
        conn.commit()
        return detalle or {"equipo_id": id_global}
    except HTTPException:
        _rollback_safely(conn)
        raise
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception(
            "Error actualizando equipo de trabajo municipality=%s schema=%s id_global=%s",
            tenant.municipality_code,
            tenant.schemas.app,
            id_global,
        )
        raise HTTPException(status_code=500, detail=f"Error actualizando equipo de trabajo: {exc}") from exc


@router.delete("/equipos-trabajo/{id_global}")
def eliminar_equipo_trabajo(
    id_global: int,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    _require_admin_or_coordinador(current_user)
    deleted_by = str(current_user.get("username") or "").strip() or None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT *
                FROM {_app_table(tenant, 'equipos_trabajo')}
                WHERE t_id = %s
                FOR UPDATE
                """,
                (id_global,),
            )
            equipo = cur.fetchone()
            if not equipo:
                raise HTTPException(status_code=404, detail="Equipo de trabajo no encontrado")
            _require_own_equipo_if_coordinador(current_user, equipo)

            cur.execute(
                f"""
                SELECT
                  et.*,
                  u.username AS coordinador_username,
                  z.nombre AS zona_nombre
                FROM {_app_table(tenant, 'equipos_trabajo')} et
                LEFT JOIN {_app_table(tenant, 'users')} u
                  ON u.id_global = et.coordinador_id
                LEFT JOIN {_app_table(tenant, 'zonas_intervencion')} z
                  ON z.t_id = et.zona_id
                WHERE et.t_id = %s
                """,
                (id_global,),
            )
            equipo_detalle = cur.fetchone() or dict(equipo)

            cur.execute(
                f"""
                SELECT
                  er.equipo_id,
                  er.reconocedor_id,
                  rec.id_global,
                  rec.username,
                  rec.first_name,
                  rec.last_name,
                  rec.email,
                  rec.rol
                FROM {_app_table(tenant, 'equipo_reconocedores')} er
                LEFT JOIN {_app_table(tenant, 'users')} rec
                  ON rec.id_global = er.reconocedor_id
                WHERE er.equipo_id = %s
                ORDER BY rec.first_name, rec.last_name, rec.username
                """,
                (id_global,),
            )
            integrantes = cur.fetchall()

            _backup_equipo_trabajo(cur, tenant, equipo_detalle, integrantes, deleted_by)

            cur.execute(
                f"DELETE FROM {_app_table(tenant, 'equipo_reconocedores')} WHERE equipo_id = %s",
                (id_global,),
            )
            cur.execute(
                f"DELETE FROM {_app_table(tenant, 'equipos_trabajo')} WHERE t_id = %s",
                (id_global,),
            )

        conn.commit()
        return {"status": "ok", "message": "Equipo de trabajo eliminado y respaldado correctamente."}
    except HTTPException:
        _rollback_safely(conn)
        raise
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception(
            "Error eliminando equipo de trabajo municipality=%s schema=%s id_global=%s",
            tenant.municipality_code,
            tenant.schemas.app,
            id_global,
        )
        raise HTTPException(status_code=500, detail=f"Error eliminando equipo de trabajo: {exc}") from exc


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
    supervisor_id = getattr(body, "supervisor_id", None)
    supervisor_id = _validate_supervisor_id(conn, tenant, supervisor_id) if role == "reconocedor" else None
    pwd_hash = hash_password(body.password) if body.password else None

    try:
        role_id = _get_role_id(conn, tenant, role)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT rol
                FROM {_app_table(tenant, 'users')}
                WHERE id_global = %s
                """,
                (id_global,),
            )
            current_user_row = cur.fetchone()
            if not current_user_row:
                raise HTTPException(status_code=404, detail="Usuario no encontrado")

            previous_role = _normalized_role(current_user_row.get("rol") or "consulta")
            cur.execute(
                f"""
                UPDATE {_app_table(tenant, 'users')}
                SET
                  email = %s,
                  first_name = %s,
                  last_name = %s,
                  rol = %s,
                  rol_id = %s,
                  supervisor = %s,
                  password_hash = COALESCE(%s, password_hash),
                  fecha_inicio = %s,
                  fecha_fin = %s,
                  activo = %s
                WHERE id_global = %s
                RETURNING id_global, username, email, first_name, last_name,
                          rol, activo, creado_en, supervisor, fecha_inicio, fecha_fin
                """,
                (
                    email,
                    body.first_name.strip(),
                    body.last_name.strip(),
                    role,
                    role_id,
                    supervisor_id,
                    pwd_hash,
                    body.fecha_inicio,
                    body.fecha_fin,
                    bool(body.activo),
                    id_global,
                ),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Usuario no encontrado")

            if previous_role in {"coordinador", "lider_reconocimiento"} and role not in {"coordinador", "lider_reconocimiento"}:
                _clear_reconocedores_supervisor(cur, tenant, id_global)
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


# Solicitud de creación de usuario schemas y endpoints
class SolicitudCreacionUsuarioCreate(BaseModel):
    username: str | None = Field(default=None, min_length=3)
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    rol: str
    email: str | None = None
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    supervisor_id: int | None = None

    @model_validator(mode="after")
    def _validate_role_and_dates(self) -> "SolicitudCreacionUsuarioCreate":
        role = (self.rol or "").strip().lower()
        if role not in {"coordinador", "reconocedor", "digitalizador"}:
            raise ValueError("El rol solicitado debe ser coordinador, reconocedor o digitalizador.")
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValueError("La fecha de finalización no puede ser anterior al inicio del contrato.")
        return self


class SolicitudCreacionUsuarioAprobar(BaseModel):
    password: str = Field(min_length=4)


class SolicitudCreacionUsuarioRechazar(BaseModel):
    comentarios_soporte: str = Field(min_length=1)


@router.post("/solicitudes", status_code=status.HTTP_201_CREATED)
def crear_solicitud_creacion_usuario(
    body: SolicitudCreacionUsuarioCreate,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    # Validar rol
    _require_admin_or_coordinador(current_user)
    # Asegurar DDL
    asignaciones_repo.ensure_asignacion_tables(conn, tenant)
    
    username = ""
    role = body.rol.strip().lower()
    email = _normalized_email(body.email)
    
    creator_id = _current_user_id(current_user)
    creator_username = current_user.get("username", "Líder")
    
    # Si rol es reconocedor, supervisor es obligatorio y debe validarse
    supervisor_id = body.supervisor_id
    if role == "reconocedor":
        if supervisor_id is None:
            raise HTTPException(status_code=400, detail="El supervisor es obligatorio para el rol de reconocedor.")
        supervisor_id = _validate_supervisor_id(conn, tenant, supervisor_id)
    else:
        supervisor_id = None  # No aplica supervisor para otros roles en la solicitud
        
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            username = _generate_next_username(cur, tenant, role)
            # Validar que username no exista en users
            cur.execute(
                f"SELECT 1 FROM {_app_table(tenant, 'users')} WHERE username = %s",
                (username,),
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Ya existe un usuario con ese username en la BD.",
                )
            
            # Validar que username no tenga solicitud PENDIENTE
            cur.execute(
                f"SELECT 1 FROM {_app_table(tenant, 'solicitud_creacion_usuario')} WHERE username = %s AND estado = 'PENDIENTE'",
                (username,),
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Ya existe una solicitud pendiente de creación para este username.",
                )

            # Insertar solicitud
            cur.execute(
                f"""
                INSERT INTO {_app_table(tenant, 'solicitud_creacion_usuario')}
                  (username, email, first_name, last_name, rol, fecha_inicio, fecha_fin, supervisor_id, creado_por_id, estado)
                VALUES
                  (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDIENTE')
                RETURNING id, username, email, first_name, last_name, rol, fecha_inicio, fecha_fin, supervisor_id, creado_por_id, estado, creado_en
                """,
                (
                    username,
                    email,
                    body.first_name.strip(),
                    body.last_name.strip(),
                    role,
                    body.fecha_inicio,
                    body.fecha_fin,
                    supervisor_id,
                    creator_id,
                ),
            )
            solicitud = cur.fetchone()
            solicitud_id = solicitud["id"]

            # Notificar a todos los usuarios con rol 'soporte' o 'admin' activos
            cur.execute(
                f"""
                SELECT id_global FROM {_app_table(tenant, 'users')}
                WHERE activo = TRUE AND LOWER(rol) IN ('soporte', 'admin')
                """
            )
            soporte_users = cur.fetchall()
            
            for s_user in soporte_users:
                # Insertar en tabla notificaciones
                cur.execute(
                    f"""
                    INSERT INTO {_app_table(tenant, 'notificaciones')}
                      (id_usuario_destino, id_usuario_origen, rol_origen, rol_destino, tipo, titulo, mensaje, url_destino, prioridad)
                    VALUES
                      (%s, %s, %s, %s, 'usuario_creacion_solicitud', %s, %s, '/panel/usuarios', 'alta')
                    """,
                    (
                        s_user["id_global"],
                        creator_id,
                        get_user_role(current_user),
                        "soporte",
                        "Nueva solicitud de creación de usuario",
                        f"El líder {creator_username} solicita crear al usuario {username} ({role.upper()}).",
                    ),
                )
        conn.commit()
        return solicitud
    except HTTPException:
        _rollback_safely(conn)
        raise
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception("Error creando solicitud de usuario")
        raise HTTPException(status_code=500, detail=f"Error en base de datos: {exc}")


@router.get("/solicitudes")
def listar_solicitudes_creacion_usuario(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    role = _require_admin_or_coordinador(current_user)
    asignaciones_repo.ensure_asignacion_tables(conn, tenant)
    
    where_clause = ""
    params = ()
    
    # Líderes y coordinadores ven solo sus solicitudes creadas
    if role in {"coordinador", "lider_reconocimiento"}:
        where_clause = "WHERE scu.creado_por_id = %s"
        params = (_current_user_id(current_user),)
        
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT 
                  scu.id,
                  scu.username,
                  scu.email,
                  scu.first_name,
                  scu.last_name,
                  scu.rol,
                  scu.fecha_inicio,
                  scu.fecha_fin,
                  scu.supervisor_id,
                  scu.creado_por_id,
                  scu.estado,
                  scu.creado_en,
                  scu.comentarios_soporte,
                  COALESCE(
                    NULLIF(TRIM(CONCAT_WS(' ', sup.first_name, sup.last_name)), ''),
                    sup.username,
                    scu.supervisor_id::text
                  ) AS supervisor_name,
                  COALESCE(
                    NULLIF(TRIM(CONCAT_WS(' ', creador.first_name, creador.last_name)), ''),
                    creador.username,
                    scu.creado_por_id::text
                  ) AS creador_name
                FROM {_app_table(tenant, 'solicitud_creacion_usuario')} scu
                LEFT JOIN {_app_table(tenant, 'users')} sup ON sup.id_global = scu.supervisor_id
                LEFT JOIN {_app_table(tenant, 'users')} creador ON creador.id_global = scu.creado_por_id
                {where_clause}
                ORDER BY scu.creado_en DESC, scu.id DESC
                """,
                params,
            )
            return cur.fetchall()
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception("Error listando solicitudes de creación")
        raise HTTPException(status_code=500, detail=f"Error consultando BD: {exc}")


@router.post("/solicitudes/{id}/aprobar")
def aprobar_solicitud_creacion_usuario(
    id: int,
    body: SolicitudCreacionUsuarioAprobar,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    # Solo admin y soporte pueden aprobar
    _require_admin(current_user)
    asignaciones_repo.ensure_asignacion_tables(conn, tenant)
    
    pwd_hash = hash_password(body.password)
    support_id = _current_user_id(current_user)
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT * FROM {_app_table(tenant, 'solicitud_creacion_usuario')}
                WHERE id = %s FOR UPDATE
                """,
                (id,),
            )
            solicitud = cur.fetchone()
            if not solicitud:
                raise HTTPException(status_code=404, detail="Solicitud no encontrada.")
            if solicitud["estado"] != "PENDIENTE":
                raise HTTPException(status_code=400, detail="Esta solicitud ya no está pendiente.")
                
            username = solicitud["username"]
            role = solicitud["rol"]
            
            # Verificar username en users
            cur.execute(
                f"SELECT 1 FROM {_app_table(tenant, 'users')} WHERE username = %s",
                (username,),
            )
            if cur.fetchone():
                raise HTTPException(status_code=400, detail=f"El username '{username}' ya está registrado.")

            # Obtener ID del rol
            role_id = _get_role_id(conn, tenant, role)
            
            # Crear usuario real en tabla users
            cur.execute(
                f"""
                INSERT INTO {_app_table(tenant, 'users')}
                  (username, email, first_name, last_name, rol, rol_id, supervisor, activo, password_hash, fecha_inicio, fecha_fin)
                VALUES
                  (%s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s)
                RETURNING id_global
                """,
                (
                    username,
                    solicitud["email"],
                    solicitud["first_name"],
                    solicitud["last_name"],
                    role,
                    role_id,
                    solicitud["supervisor_id"],
                    pwd_hash,
                    solicitud["fecha_inicio"],
                    solicitud["fecha_fin"],
                ),
            )
            new_user = cur.fetchone()
            
            # Actualizar estado de solicitud
            cur.execute(
                f"""
                UPDATE {_app_table(tenant, 'solicitud_creacion_usuario')}
                SET estado = 'APROBADA'
                WHERE id = %s
                """,
                (id,),
            )
            
            # Notificar al creador de la solicitud
            if solicitud["creado_por_id"]:
                cur.execute(
                    f"""
                    INSERT INTO {_app_table(tenant, 'notificaciones')}
                      (id_usuario_destino, id_usuario_origen, rol_origen, rol_destino, tipo, titulo, mensaje, prioridad)
                    VALUES
                      (%s, %s, 'soporte', 'lider_reconocimiento', 'solicitud_creacion_aprobada', %s, %s, 'normal')
                    """,
                    (
                        solicitud["creado_por_id"],
                        support_id,
                        "Solicitud de usuario aprobada",
                        f"Tu solicitud para crear al usuario {username} ({role.upper()}) ha sido aprobada.",
                    ),
                )
        conn.commit()
        return {"status": "ok", "detail": f"Usuario {username} creado y aprobado."}
    except HTTPException:
        _rollback_safely(conn)
        raise
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception("Error al aprobar solicitud")
        raise HTTPException(status_code=500, detail=f"Error en base de datos: {exc}")


@router.post("/solicitudes/{id}/rechazar")
def rechazar_solicitud_creacion_usuario(
    id: int,
    body: SolicitudCreacionUsuarioRechazar,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    _require_admin(current_user)
    asignaciones_repo.ensure_asignacion_tables(conn, tenant)
    
    support_id = _current_user_id(current_user)
    comentarios = body.comentarios_soporte.strip()
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT * FROM {_app_table(tenant, 'solicitud_creacion_usuario')}
                WHERE id = %s FOR UPDATE
                """,
                (id,),
            )
            solicitud = cur.fetchone()
            if not solicitud:
                raise HTTPException(status_code=404, detail="Solicitud no encontrada.")
            if solicitud["estado"] != "PENDIENTE":
                raise HTTPException(status_code=400, detail="Esta solicitud ya no está pendiente.")
                
            # Actualizar estado de solicitud
            cur.execute(
                f"""
                UPDATE {_app_table(tenant, 'solicitud_creacion_usuario')}
                SET estado = 'RECHAZADA',
                    comentarios_soporte = %s
                WHERE id = %s
                """,
                (comentarios, id),
            )
            
            # Notificar al creador de la solicitud
            if solicitud["creado_por_id"]:
                cur.execute(
                    f"""
                    INSERT INTO {_app_table(tenant, 'notificaciones')}
                      (id_usuario_destino, id_usuario_origen, rol_origen, rol_destino, tipo, titulo, mensaje, prioridad)
                    VALUES
                      (%s, %s, 'soporte', 'lider_reconocimiento', 'solicitud_creacion_rechazada', %s, %s, 'alta')
                    """,
                    (
                        solicitud["creado_por_id"],
                        support_id,
                        "Solicitud de usuario rechazada",
                        f"Tu solicitud para crear al usuario {solicitud['username']} fue rechazada. Motivo: {comentarios}",
                    ),
                )
        conn.commit()
        return {"status": "ok", "detail": f"Solicitud {id} rechazada."}
    except HTTPException:
        _rollback_safely(conn)
        raise
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception("Error al rechazar solicitud")
        raise HTTPException(status_code=500, detail=f"Error en base de datos: {exc}")

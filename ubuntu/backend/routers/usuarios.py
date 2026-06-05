import json
import logging
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from psycopg2 import IntegrityError
from psycopg2.extras import Json, RealDictCursor

from routers.auth import get_current_tenant, get_current_user, get_user_role
from routers.security import hash_password
from tenants import TenantContext, get_tenant_db_connection

router = APIRouter(prefix="/usuarios", tags=["usuarios"])
logger = logging.getLogger(__name__)

ALLOWED_ROLES = ("admin", "coordinador", "digitalizador", "reconocedor", "lider_reconocimiento", "consulta", "consolidador", "soporte")
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
          (%s, %s, %s, COALESCE(%s, CURRENT_TIMESTAMP), %s)
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
    username: str = Field(min_length=3)
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    rol: str
    email: str | None = None
    supervisor_id: int | None = None
    activo: bool = True
    password: str | None = None


class UsuarioUpdate(BaseModel):
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    rol: str
    email: str | None = None
    supervisor_id: int | None = None
    activo: bool = True
    password: str | None = None


class EquipoTrabajoUpsert(BaseModel):
    nombre: str = Field(min_length=1)
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
    supervisor_id = getattr(body, "supervisor_id", None)
    supervisor_id = _validate_supervisor_id(conn, tenant, supervisor_id) if role == "reconocedor" else None
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
                   rol, rol_id, supervisor, activo, password_hash)
                VALUES
                  (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id_global, username, email, first_name, last_name, rol, activo, creado_en, supervisor
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
                SELECT
                  u.id_global,
                  u.username,
                  u.email,
                  u.first_name,
                  u.last_name,
                  u.rol,
                  u.activo,
                  u.creado_en,
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
                ORDER BY u.id_global
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


@router.get("/equipos-trabajo")
def listar_equipos_trabajo(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    _require_admin(current_user)
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
                GROUP BY
                  et.t_id,
                  et.nombre,
                  et.coordinador_id,
                  u.username,
                  et.zona_id,
                  z.nombre,
                  et.fecha_creacion
                ORDER BY et.fecha_creacion DESC, et.nombre
                """
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
    _require_admin(current_user)
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
    _require_admin(current_user)
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


@router.post("/equipos-trabajo", status_code=status.HTTP_201_CREATED)
def crear_equipo_trabajo(
    body: EquipoTrabajoUpsert,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    _require_admin(current_user)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _validate_equipo_payload(cur, tenant, body, None)
            cur.execute(
                f"""
                INSERT INTO {_app_table(tenant, 'equipos_trabajo')}
                  (nombre, coordinador_id, zona_id, fecha_creacion)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING t_id
                """,
                (body.nombre.strip(), body.coordinador_id, body.zona_id),
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


@router.put("/equipos-trabajo/{id_global}")
def actualizar_equipo_trabajo(
    id_global: int,
    body: EquipoTrabajoUpsert,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    _require_admin(current_user)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT t_id, nombre
                FROM {_app_table(tenant, 'equipos_trabajo')}
                WHERE t_id = %s
                FOR UPDATE
                """,
                (id_global,),
            )
            equipo = cur.fetchone()
            if not equipo:
                raise HTTPException(status_code=404, detail="Equipo de trabajo no encontrado")

            _validate_equipo_payload(cur, tenant, body, id_global)
            cur.execute(
                f"""
                UPDATE {_app_table(tenant, 'equipos_trabajo')}
                SET nombre = %s,
                    coordinador_id = %s,
                    zona_id = %s
                WHERE t_id = %s
                """,
                (body.nombre.strip(), body.coordinador_id, body.zona_id, id_global),
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
    _require_admin(current_user)
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
                  activo = %s
                WHERE id_global = %s
                RETURNING id_global, username, email, first_name, last_name,
                          rol, activo, creado_en, supervisor
                """,
                (
                    email,
                    body.first_name.strip(),
                    body.last_name.strip(),
                    role,
                    role_id,
                    supervisor_id,
                    pwd_hash,
                    bool(body.activo),
                    id_global,
                ),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Usuario no encontrado")

            if previous_role == "coordinador" and role != "coordinador":
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

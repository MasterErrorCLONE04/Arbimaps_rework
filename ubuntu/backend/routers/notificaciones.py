from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor

from routers.auth import require_user, get_current_tenant
from tenants import get_tenant_db_connection, TenantContext

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])


def _get_user_id(user: dict) -> int:
    try:
        user_id = user.get("id_global")
        if user_id is None:
            raise ValueError("id_global no disponible")
        return int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Usuario no autenticado.")


@router.get("/mis-notificaciones")
def mis_notificaciones(
    limit: int = 50,
    user: dict = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    user_id = _get_user_id(user)
    limit = max(1, min(int(limit or 50), 100))
    app_schema = tenant.schemas.app if tenant else "arbimaps_app"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT *
            FROM {app_schema}.notificaciones
            WHERE id_usuario_destino = %s
              AND archivado = FALSE
            ORDER BY leido ASC, fecha_creacion DESC, id DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        return cur.fetchall()


@router.get("/no-leidas")
def contar_no_leidas(
    user: dict = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    user_id = _get_user_id(user)
    app_schema = tenant.schemas.app if tenant else "arbimaps_app"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM {app_schema}.notificaciones
            WHERE id_usuario_destino = %s
              AND archivado = FALSE
              AND leido = FALSE
            """,
            (user_id,),
        )
        row = cur.fetchone() or {}
        return {"total": int(row.get("total") or 0)}


@router.post("/{notificacion_id}/leer")
def marcar_leida(
    notificacion_id: int,
    user: dict = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    user_id = _get_user_id(user)
    app_schema = tenant.schemas.app if tenant else "arbimaps_app"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            UPDATE {app_schema}.notificaciones
            SET leido = TRUE,
                fecha_lectura = COALESCE(fecha_lectura, now())
            WHERE id = %s
              AND id_usuario_destino = %s
            RETURNING *
            """,
            (notificacion_id, user_id),
        )
        row = cur.fetchone()
    conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail="Notificacion no encontrada.")
    return row


@router.post("/leer-todas")
def marcar_todas_leidas(
    user: dict = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    user_id = _get_user_id(user)
    app_schema = tenant.schemas.app if tenant else "arbimaps_app"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            UPDATE {app_schema}.notificaciones
            SET leido = TRUE,
                fecha_lectura = COALESCE(fecha_lectura, now())
            WHERE id_usuario_destino = %s
              AND archivado = FALSE
              AND leido = FALSE
            RETURNING id
            """,
            (user_id,),
        )
        rows = cur.fetchall()
    conn.commit()

    return {"actualizadas": len(rows)}


@router.post("/{notificacion_id}/archivar")
def archivar_notificacion(
    notificacion_id: int,
    user: dict = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    user_id = _get_user_id(user)
    app_schema = tenant.schemas.app if tenant else "arbimaps_app"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            UPDATE {app_schema}.notificaciones
            SET archivado = TRUE
            WHERE id = %s
              AND id_usuario_destino = %s
            RETURNING *
            """,
            (notificacion_id, user_id),
        )
        row = cur.fetchone()
    conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail="Notificacion no encontrada.")
    return row

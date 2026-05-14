import logging
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from psycopg2.extras import RealDictCursor

from routers.auth import get_current_tenant, get_current_user
from tenants import TenantContext, get_tenant_db_connection

router = APIRouter(prefix="/visor", tags=["visor"])
logger = logging.getLogger(__name__)

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quoted_identifier(name: str) -> str:
    value = (name or "").strip()
    if not IDENT_RE.match(value):
        raise HTTPException(status_code=500, detail="Schema tenant invalido.")
    return value


def _table_name(tenant: TenantContext, table: str) -> str:
    schema = _quoted_identifier(tenant.schemas.main)
    table_name = _quoted_identifier(table)
    return f"{schema}.{table_name}"


def _execute_fetchone(conn, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("Error ejecutando consulta readonly de visor")
        raise HTTPException(
            status_code=500,
            detail="Error consultando informacion del visor.",
        ) from exc


def _execute_fetchall(conn, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("Error ejecutando consulta readonly de visor")
        raise HTTPException(
            status_code=500,
            detail="Error consultando informacion del visor.",
        ) from exc


@router.get("/project-extent")
def project_extent(
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    """
    Extension espacial del proyecto basada en arb_terreno.
    Se usa para centrar el mapa sin depender de un bbox fijo.
    """
    sql = f"""
    SELECT
      MIN(ST_XMin(geometria)) AS xmin,
      MIN(ST_YMin(geometria)) AS ymin,
      MAX(ST_XMax(geometria)) AS xmax,
      MAX(ST_YMax(geometria)) AS ymax
    FROM {_table_name(tenant, 'arb_terreno')}
    WHERE geometria IS NOT NULL;
    """

    row = _execute_fetchone(conn, sql)

    if not row:
        return JSONResponse({"error": "No se encontro extension espacial"}, status_code=404)

    keys = ("xmin", "ymin", "xmax", "ymax")
    if any(row.get(k) is None for k in keys):
        return JSONResponse({"error": "No se encontro extension espacial"}, status_code=404)

    extent = [float(row["xmin"]), float(row["ymin"]), float(row["xmax"]), float(row["ymax"])]
    if extent[0] >= extent[2] or extent[1] >= extent[3]:
        return JSONResponse({"error": "Extension espacial invalida"}, status_code=500)

    return {"extent": extent}


@router.get("/terreno/detalle")
def terreno_detalle(
    terreno_id: int = Query(...),
    _user: Annotated[dict[str, Any], Depends(get_current_user)] = None,
    tenant: Annotated[TenantContext, Depends(get_current_tenant)] = None,
    conn=Depends(get_tenant_db_connection),
):
    """
    Ficha para visor al seleccionar un terreno:
    - terreno (arb_terreno)
    - predio asociado (arb_predio)
    - catalogo de condicion (arb_condicionprediotipo)
    """
    sql = f"""
    SELECT
      t.t_id AS terreno_id,
      ST_AsGeoJSON(t.geometria)::json AS terreno_geom,
      p.t_id AS predio_id,
      p.numero_predial AS numero_predial_nacional,
      p.matricula_inmobiliaria,
      p.condicion_predio,
      c.dispname AS condicion_predio_nombre,
      p.tipo,
      p.destinacion_economica
    FROM {_table_name(tenant, 'arb_terreno')} t
    LEFT JOIN {_table_name(tenant, 'arb_predio')} p ON p.t_id = t.predio
    LEFT JOIN {_table_name(tenant, 'arb_condicionprediotipo')} c
      ON c.t_id::text = p.condicion_predio::text
    WHERE t.t_id = %s
    LIMIT 1;
    """

    row = _execute_fetchone(conn, sql, (terreno_id,))

    if not row:
        return JSONResponse({"error": "Terreno no encontrado"}, status_code=404)

    return row


@router.get("/dashboard/condicion-predio")
def dashboard_condicion_predio(
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
    conn=Depends(get_tenant_db_connection),
):
    """
    Conteo agregado para dashboard por condicion de predio.
    """
    sql = f"""
    SELECT
      COALESCE(c.dispname, 'SIN_DATO') AS condicion_predio,
      COUNT(*)::bigint AS total
    FROM {_table_name(tenant, 'arb_predio')} p
    LEFT JOIN {_table_name(tenant, 'arb_condicionprediotipo')} c
      ON c.t_id::text = p.condicion_predio::text
    GROUP BY 1
    ORDER BY total DESC;
    """

    rows = _execute_fetchall(conn, sql)

    return {"items": rows}

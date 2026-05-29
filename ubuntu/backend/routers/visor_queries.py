from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from psycopg2.extras import RealDictCursor

from routers.auth import get_current_tenant, require_user
from tenants import TenantContext, get_connection_manager, main_table

router = APIRouter(prefix="/visor", tags=["visor"])


def _main_table(tenant: TenantContext, table_name: str) -> str:
    return main_table(tenant, table_name)


@router.get("/project-extent")
def project_extent(
    request: Request,
    _user: str = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
):
    """
    Extensión espacial del proyecto basada en arb_terreno.
    Se usa para centrar el mapa sin depender de un bbox fijo.
    """
    sql = f"""
    SELECT
      MIN(ST_XMin(geometria)) AS xmin,
      MIN(ST_YMin(geometria)) AS ymin,
      MAX(ST_XMax(geometria)) AS xmax,
      MAX(ST_YMax(geometria)) AS ymax
    FROM {_main_table(tenant, 'arb_terreno')}
    WHERE geometria IS NOT NULL;
    """

    connection_manager = get_connection_manager(request.app)
    with connection_manager.connection(tenant) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            row = cur.fetchone()

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
    request: Request,
    terreno_id: int = Query(...),
    _user: str = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
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
    FROM {_main_table(tenant, 'arb_terreno')} t
    LEFT JOIN {_main_table(tenant, 'arb_predio')} p ON p.t_id = t.predio
    LEFT JOIN {_main_table(tenant, 'arb_condicionprediotipo')} c
      ON c.t_id::text = p.condicion_predio::text
    WHERE t.t_id = %s
    LIMIT 1;
    """

    connection_manager = get_connection_manager(request.app)
    with connection_manager.connection(tenant) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (terreno_id,))
            row = cur.fetchone()

    if not row:
        return JSONResponse({"error": "Terreno no encontrado"}, status_code=404)

    return row


@router.get("/dashboard/condicion-predio")
def dashboard_condicion_predio(
    request: Request,
    _user: str = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
):
    """
    Conteo agregado para dashboard por condicion de predio.
    """
    sql = f"""
    SELECT
      COALESCE(c.dispname, 'SIN_DATO') AS condicion_predio,
      COUNT(*)::bigint AS total
    FROM {_main_table(tenant, 'arb_predio')} p
    LEFT JOIN {_main_table(tenant, 'arb_condicionprediotipo')} c
      ON c.t_id::text = p.condicion_predio::text
    GROUP BY 1
    ORDER BY total DESC;
    """

    connection_manager = get_connection_manager(request.app)
    with connection_manager.connection(tenant) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()

    return {"items": rows}


@router.get("/total-predios")
def obtenertotalpredios(
    request: Request,
    _user: str = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
):
    """
    Obtiene el conteo total de registros en la tabla arb_predio.
    """
    # Debug: Confirmando que este endpoint esta activo
    sql = f"SELECT COUNT(*)::int AS total FROM {_main_table(tenant, 'arb_predio')}"
    connection_manager = get_connection_manager(request.app)
    with connection_manager.connection(tenant) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            row = cur.fetchone()
    return row

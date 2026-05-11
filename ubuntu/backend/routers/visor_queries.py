import os

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from psycopg2.extras import RealDictCursor

from routers.auth import require_user
from routers.db import db_conn, t

router = APIRouter(prefix="/visor", tags=["visor"])
VISOR_DATA_SCHEMA = os.getenv("VISOR_DATA_SCHEMA", os.getenv("DATA_SCHEMA", "leiva"))


@router.get("/project-extent")
def project_extent(_user: str = Depends(require_user)):
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
    FROM {t('arb_terreno', schema=VISOR_DATA_SCHEMA)}
    WHERE geometria IS NOT NULL;
    """

    with db_conn() as conn:
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
    terreno_id: int = Query(...),
    _user: str = Depends(require_user),
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
    FROM {t('arb_terreno', schema=VISOR_DATA_SCHEMA)} t
    LEFT JOIN {t('arb_predio', schema=VISOR_DATA_SCHEMA)} p ON p.t_id = t.predio
    LEFT JOIN {t('arb_condicionprediotipo', schema=VISOR_DATA_SCHEMA)} c
      ON c.t_id::text = p.condicion_predio::text
    WHERE t.t_id = %s
    LIMIT 1;
    """

    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (terreno_id,))
            row = cur.fetchone()

    if not row:
        return JSONResponse({"error": "Terreno no encontrado"}, status_code=404)

    return row


@router.get("/dashboard/condicion-predio")
def dashboard_condicion_predio(_user: str = Depends(require_user)):
    """
    Conteo agregado para dashboard por condicion de predio.
    """
    sql = f"""
    SELECT
      COALESCE(c.dispname, 'SIN_DATO') AS condicion_predio,
      COUNT(*)::bigint AS total
    FROM {t('arb_predio', schema=VISOR_DATA_SCHEMA)} p
    LEFT JOIN {t('arb_condicionprediotipo', schema=VISOR_DATA_SCHEMA)} c
      ON c.t_id::text = p.condicion_predio::text
    GROUP BY 1
    ORDER BY total DESC;
    """

    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()

    return {"items": rows}

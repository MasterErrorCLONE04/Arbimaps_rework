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
      COALESCE(NULLIF(p.id_operacion::text, ''), p.numero_predial::text) AS id_operacion,
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


@router.get("/terreno/seleccion")
def terreno_seleccion_por_coordenada(
    request: Request,
    x: float = Query(...),
    y: float = Query(...),
    tolerance: float = Query(2.0, ge=0.0),
    _user: str = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
):
    """
    Selecciona el terreno que intersecta el punto dado en EPSG:9377 y
    devuelve la ficha minima para el popup del visor.
    """
    sql = f"""
    SELECT
      t.t_id AS terreno_id,
      ST_AsGeoJSON(t.geometria)::json AS terreno_geom,
      p.t_id AS predio_id,
      COALESCE(NULLIF(p.id_operacion::text, ''), p.numero_predial::text) AS id_operacion,
      p.numero_predial AS numero_predial_nacional,
      p.matricula_inmobiliaria
    FROM {_main_table(tenant, 'arb_terreno')} t
    LEFT JOIN {_main_table(tenant, 'arb_predio')} p ON p.t_id = t.predio
    WHERE
      ST_Intersects(t.geometria, ST_SetSRID(ST_Point(%s, %s), 9377))
      OR ST_DWithin(t.geometria, ST_SetSRID(ST_Point(%s, %s), 9377), %s)
    ORDER BY
      CASE WHEN ST_Intersects(t.geometria, ST_SetSRID(ST_Point(%s, %s), 9377)) THEN 0 ELSE 1 END,
      ST_Distance(t.geometria, ST_SetSRID(ST_Point(%s, %s), 9377)) ASC,
      ST_Area(t.geometria) ASC NULLS LAST,
      t.t_id ASC
    LIMIT 1;
    """

    connection_manager = get_connection_manager(request.app)
    with connection_manager.connection(tenant) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (x, y, x, y, tolerance, x, y, x, y))
            row = cur.fetchone()

    if not row:
        return JSONResponse({"error": "Terreno no encontrado"}, status_code=404)

    return row


@router.get("/terrenos/snap")
def terrenos_snap(
    request: Request,
    minx: float = Query(...),
    miny: float = Query(...),
    maxx: float = Query(...),
    maxy: float = Query(...),
    layers: str = Query("arb_terreno"),
    limit: int = Query(1500, ge=1, le=5000),
    _user: str = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
):
    """
    Geometrias de apoyo para snapping de medicion en el visor.
    Devuelve solo las capas permitidas y visibles dentro del bbox en EPSG:9377.
    """
    allowed_layers = {
        "arb_terreno": "Terreno",
        "arb_construccion": "Construccion",
        "arb_unidadconstruccion": "Unidad construccion",
    }
    requested_layers = [
        item.strip().lower()
        for item in str(layers or "").split(",")
        if item.strip()
    ]
    selected_layers = [
        layer_name for layer_name in requested_layers if layer_name in allowed_layers
    ] or ["arb_terreno"]

    union_sql_parts = []
    for layer_name in selected_layers:
        table_name = _main_table(tenant, layer_name)
        union_sql_parts.append(
            f"""
            SELECT
              '{layer_name}'::text AS source_layer,
              t_id,
              ST_AsGeoJSON(geometria)::json AS geometry
            FROM {table_name}
            WHERE geometria && ST_MakeEnvelope(%s, %s, %s, %s, 9377)
            """
        )

    sql = f"""
    SELECT *
    FROM (
      {" UNION ALL ".join(union_sql_parts)}
    ) snap_features
    ORDER BY source_layer, t_id
    LIMIT %s;
    """
    params = []
    for _layer_name in selected_layers:
        params.extend([minx, miny, maxx, maxy])
    params.append(limit)

    connection_manager = get_connection_manager(request.app)
    with connection_manager.connection(tenant) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()

    features = [
        {
            "type": "Feature",
            "id": f'{row["source_layer"]}.{row["t_id"]}',
            "geometry": row["geometry"],
            "properties": {
                "t_id": row["t_id"],
                "source_layer": row["source_layer"],
            },
        }
        for row in rows
        if row.get("geometry")
    ]
    return {"type": "FeatureCollection", "features": features}


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

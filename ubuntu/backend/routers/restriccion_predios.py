import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

from routers.auth import get_current_tenant, get_current_user, require_user
from tenants import TenantContext, get_connection_manager, main_table, app_table
from repositories.asignaciones_repo import ensure_asignacion_tables

router = APIRouter(prefix="/restriccion-predios", tags=["restriccion_predios"])
logger = logging.getLogger(__name__)

class RestringirBody(BaseModel):
    numero_predial_nacional: str
    motivo: Optional[str] = None

class LiberarBody(BaseModel):
    numero_predial_nacional: str

@router.get("/list")
def listar_restricciones(
    request: Request,
    _user: str = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
):
    """
    Obtener listado de predios restringidos para el tenant actual.
    """
    connection_manager = get_connection_manager(request.app)
    with connection_manager.connection(tenant) as conn:
        ensure_asignacion_tables(conn, tenant)
        app_schema = tenant.schemas.app
        sql = f"""
        SELECT 
            id,
            predio_t_id,
            numero_predial_nacional,
            motivo,
            creado_por,
            creado_en
        FROM {app_schema}.restriccion_predio
        ORDER BY creado_en DESC
        """
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            
    # Serializar fechas a formato ISO
    for r in rows:
        if r.get("creado_en"):
            r["creado_en"] = r["creado_en"].isoformat()
            
    return rows

@router.post("/restringir")
def restringir_predio(
    request: Request,
    body: RestringirBody,
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
):
    """
    Restringir un predio para evitar su asignación.
    """
    numero = body.numero_predial_nacional.strip()
    motivo = (body.motivo or "").strip() or None
    creado_por = user.get("username") if isinstance(user, dict) else str(user)
    
    if not numero:
        raise HTTPException(status_code=400, detail="Debe indicar el número predial nacional.")
        
    connection_manager = get_connection_manager(request.app)
    with connection_manager.connection(tenant) as conn:
        ensure_asignacion_tables(conn, tenant)
        app_schema = tenant.schemas.app
        main_schema = tenant.schemas.main
        
        with conn.cursor() as cur:
            # 1. Verificar si el predio existe en la tabla arb_predio
            cur.execute(
                f"SELECT t_id FROM {main_schema}.arb_predio WHERE numero_predial = %s LIMIT 1",
                (numero,)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail=f"El predio con número predial '{numero}' no existe en la base de datos catastral."
                )
            predio_t_id = row[0]
            
            # 2. Verificar si ya está restringido
            cur.execute(
                f"SELECT 1 FROM {app_schema}.restriccion_predio WHERE numero_predial_nacional = %s LIMIT 1",
                (numero,)
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=400,
                    detail=f"El predio '{numero}' ya se encuentra restringido."
                )
                
            # 3. Insertar la restricción
            cur.execute(
                f"""
                INSERT INTO {app_schema}.restriccion_predio 
                (predio_t_id, numero_predial_nacional, motivo, creado_por)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (predio_t_id, numero, motivo, creado_por)
            )
            conn.commit()
            
    return {"message": f"Predio {numero} restringido exitosamente."}

@router.post("/liberar")
def liberar_predio(
    request: Request,
    body: LiberarBody,
    _user: str = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
):
    """
    Eliminar la restricción de un predio.
    """
    numero = body.numero_predial_nacional.strip()
    if not numero:
        raise HTTPException(status_code=400, detail="Debe indicar el número predial nacional.")
        
    connection_manager = get_connection_manager(request.app)
    with connection_manager.connection(tenant) as conn:
        ensure_asignacion_tables(conn, tenant)
        app_schema = tenant.schemas.app
        
        with conn.cursor() as cur:
            # 1. Verificar si existe la restricción
            cur.execute(
                f"SELECT 1 FROM {app_schema}.restriccion_predio WHERE numero_predial_nacional = %s LIMIT 1",
                (numero,)
            )
            if not cur.fetchone():
                raise HTTPException(
                    status_code=404,
                    detail=f"No se encontró una restricción activa para el predio '{numero}'."
                )
                
            # 2. Eliminar la restricción
            cur.execute(
                f"DELETE FROM {app_schema}.restriccion_predio WHERE numero_predial_nacional = %s",
                (numero,)
            )
            conn.commit()
            
    return {"message": f"Restricción del predio {numero} eliminada."}

@router.get("/geometrias")
def obtener_geometrias_restringidas(
    request: Request,
    _user: str = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
):
    """
    Obtener las geometrías en GeoJSON de los predios restringidos.
    """
    connection_manager = get_connection_manager(request.app)
    with connection_manager.connection(tenant) as conn:
        ensure_asignacion_tables(conn, tenant)
        app_schema = tenant.schemas.app
        main_schema = tenant.schemas.main
        
        sql = f"""
        SELECT 
          rp.id,
          rp.numero_predial_nacional,
          rp.motivo,
          ST_AsGeoJSON(t.geometria)::json AS geometry
        FROM {app_schema}.restriccion_predio rp
        JOIN {main_schema}.arb_predio p ON p.t_id = rp.predio_t_id
        JOIN {main_schema}.arb_terreno t ON t.predio = p.t_id
        WHERE t.geometria IS NOT NULL
        """
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            
    features = [
        {
            "type": "Feature",
            "id": f"restriccion_predio.{row['id']}",
            "geometry": row["geometry"],
            "properties": {
                "id": row["id"],
                "numero_predial_nacional": row["numero_predial_nacional"],
                "motivo": row["motivo"] or "",
            }
        }
        for row in rows
        if row.get("geometry")
    ]
    
    return {"type": "FeatureCollection", "features": features}

from fastapi import APIRouter, Depends, HTTPException
import logging
from psycopg2.extras import RealDictCursor

from tenants import app_table, get_tenant_db_connection
from tenants.context import TenantContext
from tenants.dependencies import get_tenant_context_from_session
from routers.auth import get_current_user_from_session, check_admin_soporte_isolation

def verify_historial_isolation(
    assignment_id: str,
    conn = Depends(get_tenant_db_connection),
    tenant: TenantContext = Depends(get_tenant_context_from_session),
    user: dict = Depends(get_current_user_from_session),
):
    try:
        asig_id = int(assignment_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de asignacion invalido")
    check_admin_soporte_isolation(conn, tenant, user, asig_id)

router = APIRouter(
    prefix="/api/workflow/asignaciones",
    tags=["Historial Asignaciones (Solo Lectura)"],
    dependencies=[Depends(verify_historial_isolation)]
)
logger = logging.getLogger(__name__)

@router.get("/{assignment_id}/historial/predios")
def get_historial_predios(
    assignment_id: str,
    tenant: TenantContext = Depends(get_tenant_context_from_session),
    conn = Depends(get_tenant_db_connection),
):
    """
    Obtiene la fotografia inicial e inmutable de los predios guardados en b_asignaciones_his
    al momento exacto en que se creo la asignacion.
    """
    schema_history = getattr(getattr(tenant, "schemas", None), "work_history", "b_asignaciones_his")
    asignacion_table = app_table(tenant, "asignacion")
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Obtener el dataset de la asignacion
        cur.execute(
            f"SELECT work_datasetname, numero_predial_nacional FROM {asignacion_table} WHERE id = %s",
            (int(assignment_id),)
        )
        asig_row = cur.fetchone()
        if not asig_row:
            raise HTTPException(status_code=404, detail="Asignación no encontrada.")

        work_datasetname = asig_row.get("work_datasetname")
        if not work_datasetname:
            # Fallback por id
            work_datasetname = f"asig_{assignment_id}"

        # Verificar si existe el esquema de historial
        cur.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
            (schema_history,)
        )
        if not cur.fetchone():
            return {"assignment_id": int(assignment_id), "predios_historicos": [], "total": 0}

        # Consultar predios en b_asignaciones_his
        sql = f"""
            SELECT 
                p.t_id,
                p.numero_predial,
                p.numero_predial_anterior,
                p.area_catastral_terreno,
                p.observaciones,
                d.datasetname
            FROM {schema_history}.arb_predio p
            JOIN {schema_history}.t_ili2db_basket b ON b.t_id = p.t_basket
            JOIN {schema_history}.t_ili2db_dataset d ON d.t_id = b.dataset
            WHERE d.datasetname = %s
            ORDER BY p.numero_predial;
        """
        try:
            cur.execute(sql, (work_datasetname,))
            predios = cur.fetchall() or []
        except Exception as exc:
            logger.warning("Error al consultar predios historicos en %s: %s", schema_history, exc)
            predios = []

    return {
        "assignment_id": int(assignment_id),
        "schema_history": schema_history,
        "datasetname": work_datasetname,
        "total": len(predios),
        "predios_historicos": predios
    }

@router.get("/{assignment_id}/historial/predio/{npn}")
def get_historial_predio_detalle(
    assignment_id: str,
    npn: str,
    tenant: TenantContext = Depends(get_tenant_context_from_session),
    conn = Depends(get_tenant_db_connection),
):
    """
    Obtiene los detalles del predio e informacion original inmutable desde b_asignaciones_his.
    """
    schema_history = getattr(getattr(tenant, "schemas", None), "work_history", "b_asignaciones_his")
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
            (schema_history,)
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Esquema de historial {schema_history} no encontrado.")

        sql = f"""
            SELECT 
                p.*,
                d.datasetname
            FROM {schema_history}.arb_predio p
            JOIN {schema_history}.t_ili2db_basket b ON b.t_id = p.t_basket
            JOIN {schema_history}.t_ili2db_dataset d ON d.t_id = b.dataset
            WHERE p.numero_predial = %s
            LIMIT 1;
        """
        cur.execute(sql, (npn,))
        predio = cur.fetchone()
        if not predio:
            raise HTTPException(status_code=404, detail=f"Predio {npn} no encontrado en el historial {schema_history}.")

    return {
        "assignment_id": int(assignment_id),
        "schema_history": schema_history,
        "predio_historico": predio
    }

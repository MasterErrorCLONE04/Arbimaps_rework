from fastapi import APIRouter, Depends
from psycopg2.extras import RealDictCursor

from routers.auth import get_current_tenant, require_user
from tenants import TenantContext, get_tenant_db_connection, main_table

router = APIRouter(prefix="/resumenp", tags=["resumen_proyecto"])


@router.get("/proyecto")
def resumen_proyecto(
    _user: str = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Resumen general del proyecto:
    - total de predios
    - distribucion por condicion de predio
    - distribucion por tipo de predio
    - distribucion por destinacion economica
    - distribucion por tipo de planta (unidad de construccion)
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        predio_table = main_table(tenant, "arb_predio")
        terreno_table = main_table(tenant, "arb_terreno")
        construccion_table = main_table(tenant, "arb_construccion")
        unidad_construccion_table = main_table(tenant, "arb_unidadconstruccion")

        sql_total_terrenos = f"""
        SELECT COUNT(*)::bigint AS total
        FROM {terreno_table};
        """
        cur.execute(sql_total_terrenos)
        total_terrenos = int((cur.fetchone() or {}).get("total") or 0)

        sql_total_construcciones = f"""
        SELECT COUNT(*)::bigint AS total
        FROM {construccion_table};
        """
        cur.execute(sql_total_construcciones)
        total_construcciones = int((cur.fetchone() or {}).get("total") or 0)

        sql_total_unidades = f"""
        SELECT COUNT(*)::bigint AS total
        FROM {unidad_construccion_table};
        """
        cur.execute(sql_total_unidades)
        total_unidades_construccion = int((cur.fetchone() or {}).get("total") or 0)

        # 1) Distribucion por condicion del predio
        condicion_predio_table = main_table(tenant, "arb_condicionprediotipo")
        sql_condicion = f"""
        SELECT
          COALESCE(c.dispname, 'SIN_DATO') AS condicion_predio,
          COUNT(*)::bigint AS total
        FROM {predio_table} p
        LEFT JOIN {condicion_predio_table} c
          ON c.t_id::text = p.condicion_predio::text
        GROUP BY 1
        ORDER BY total DESC;
        """
        cur.execute(sql_condicion)
        condicion_rows = cur.fetchall()

        # 2) Distribucion por tipo de predio (unidad administrativa basica)
        predio_tipo_table = main_table(tenant, "arb_prediotipo")
        sql_tipo = f"""
        SELECT
          COALESCE(tip.dispname, 'SIN_DATO') AS tipo_predio,
          COUNT(*)::bigint AS total
        FROM {predio_table} p
        LEFT JOIN {predio_tipo_table} tip
          ON tip.t_id = p.tipo::bigint
        GROUP BY 1
        ORDER BY total DESC;
        """
        cur.execute(sql_tipo)
        tipo_rows = cur.fetchall()

        # 3) Distribucion por destinacion economica
        destinacion_economica_table = main_table(tenant, "arb_destinacioneconomicatipo")
        sql_dest = f"""
        SELECT
          COALESCE(d.dispname, 'SIN_DATO') AS destinacion_economica,
          COUNT(*)::bigint AS total
        FROM {predio_table} p
        LEFT JOIN {destinacion_economica_table} d
          ON d.t_id = p.destinacion_economica::bigint
        GROUP BY 1
        ORDER BY total DESC;
        """
        cur.execute(sql_dest)
        dest_rows = cur.fetchall()

        # 4) Distribucion por tipo de planta (arb_unidadconstruccion)
        construccion_planta_tipo_table = main_table(tenant, "arb_construccionplantatipo")
        sql_tipo_planta = f"""
        SELECT
          COALESCE(tp.dispname, 'SIN_DATO') AS tipo_planta,
          COUNT(*)::bigint AS total
        FROM {unidad_construccion_table} uc
        LEFT JOIN {construccion_planta_tipo_table} tp
          ON tp.t_id = uc.tipo_planta::bigint
        GROUP BY 1
        ORDER BY total DESC;
        """
        cur.execute(sql_tipo_planta)
        tipo_planta_rows = cur.fetchall()

    total_predios = int(sum(int(r.get("total", 0)) for r in condicion_rows))

    return {
        "total_predios": total_predios,
        "total_terrenos": total_terrenos,
        "total_construcciones": total_construcciones,
        "total_unidades_construccion": total_unidades_construccion,
        "condicion": condicion_rows,
        "tipo": tipo_rows,
        "destinacion_economica": dest_rows,
        "tipo_planta": tipo_planta_rows,
    }

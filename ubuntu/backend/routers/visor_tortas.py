import os

from fastapi import APIRouter, Depends
from psycopg2.extras import RealDictCursor

from routers.auth import require_user
from routers.db import db_conn, t

router = APIRouter(prefix="/resumenp", tags=["resumen_proyecto"])
VISOR_DATA_SCHEMA = os.getenv("VISOR_DATA_SCHEMA", os.getenv("DATA_SCHEMA", "leiva"))


@router.get("/proyecto")
def resumen_proyecto(_user: str = Depends(require_user)):
    """
    Resumen general del proyecto:
    - total de predios
    - distribución por condición de predio
    - distribución por tipo de predio
    - distribución por destinación económica
    - distribución por tipo de planta (unidad de construcción)
    """
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1) Distribución por condición del predio
            sql_condicion = f"""
            SELECT
              COALESCE(c.dispname, 'SIN_DATO') AS condicion_predio,
              COUNT(*)::bigint AS total
            FROM {t('arb_predio', schema=VISOR_DATA_SCHEMA)} p
            LEFT JOIN {t('arb_condicionprediotipo', schema=VISOR_DATA_SCHEMA)} c
              ON c.t_id::text = p.condicion_predio::text
            GROUP BY 1
            ORDER BY total DESC;
            """
            cur.execute(sql_condicion)
            condicion_rows = cur.fetchall()

            # 2) Distribución por tipo de predio (unidad administrativa básica)
            sql_tipo = f"""
            SELECT
              COALESCE(tip.dispname, 'SIN_DATO') AS tipo_predio,
              COUNT(*)::bigint AS total
            FROM {t('arb_predio', schema=VISOR_DATA_SCHEMA)} p
            LEFT JOIN {t('arb_prediotipo', schema=VISOR_DATA_SCHEMA)} tip
              ON tip.t_id = p.tipo::bigint
            GROUP BY 1
            ORDER BY total DESC;
            """
            cur.execute(sql_tipo)
            tipo_rows = cur.fetchall()

            # 3) Distribución por destinación económica
            sql_dest = f"""
            SELECT
              COALESCE(d.dispname, 'SIN_DATO') AS destinacion_economica,
              COUNT(*)::bigint AS total
            FROM {t('arb_predio', schema=VISOR_DATA_SCHEMA)} p
            LEFT JOIN {t('arb_destinacioneconomicatipo', schema=VISOR_DATA_SCHEMA)} d
              ON d.t_id = p.destinacion_economica::bigint
            GROUP BY 1
            ORDER BY total DESC;
            """
            cur.execute(sql_dest)
            dest_rows = cur.fetchall()

            # 4) Distribución por tipo de planta (arb_unidadconstruccion)
            sql_tipo_planta = f"""
            SELECT
              COALESCE(tp.dispname, 'SIN_DATO') AS tipo_planta,
              COUNT(*)::bigint AS total
            FROM {t('arb_unidadconstruccion', schema=VISOR_DATA_SCHEMA)} uc
            LEFT JOIN {t('arb_construccionplantatipo', schema=VISOR_DATA_SCHEMA)} tp
              ON tp.t_id = uc.tipo_planta::bigint
            GROUP BY 1
            ORDER BY total DESC;
            """
            cur.execute(sql_tipo_planta)
            tipo_planta_rows = cur.fetchall()

    total_predios = int(sum(int(r.get("total", 0)) for r in condicion_rows))

    return {
        "total_predios": total_predios,
        "condicion": condicion_rows,
        "tipo": tipo_rows,
        "destinacion_economica": dest_rows,
        "tipo_planta": tipo_planta_rows,
    }



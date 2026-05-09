from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor

from routers.auth import require_user
from routers.db import db_conn

router = APIRouter(prefix="/editar-predio", tags=["Editar predio"])


@router.get("/arb-predio")
def obtener_arb_predio_para_edicion(
    predio_t_id: int = Query(...),
    _user: dict = Depends(require_user),
):
    sql = """
        SELECT
            p.t_id,
            p.numero_predial
        FROM a_base_principal.arb_predio AS p
        WHERE p.t_id = %s
        LIMIT 1;
    """

    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (predio_t_id,))
            row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="No se encontro el predio en a_base_principal.arb_predio.",
        )

    return {
        "t_id": row["t_id"],
        "numero_predial": row["numero_predial"],
        "numero_predial_nacional": row["numero_predial"],
    }
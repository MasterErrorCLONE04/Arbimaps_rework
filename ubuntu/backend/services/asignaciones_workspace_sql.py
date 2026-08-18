import logging
from app.db import get_db_connection
from services.asignaciones_workspace_f_r1_r2 import (
    crear_schema_workspace_f_r1_r2,
    importar_predio_f_r1_r2_a_workspace,
    importar_predios_f_r1_r2_a_workspace,
    _ensure_workspace_tables_exist
)

logger = logging.getLogger(__name__)


def run_insertar_predios_for_asignacion(
    tenant: str,
    npns: list[str],
    resolved_schema_work: str,
    t_basket_id: int
):
    """
    Inserta una lista de predios (por NPN) en las tablas de trabajo (formato_f, r1, r2)
    de una asignación (workspace) usando SQL directo.
    
    Aplica inserción masiva por conjunto (bulk) y fallback por predio con SAVEPOINTs
    para prevenir abortos de transacción (psycopg2.errors.InFailedSqlTransaction).
    """
    if not npns:
        return {"inserted": 0, "errors": []}

    logger.info(f"Insertando {len(npns)} predios en {resolved_schema_work} (basket_id={t_basket_id})")

    inserted = 0
    errors = []

    with get_db_connection() as conn:
        _ensure_workspace_tables_exist(conn, resolved_schema_work)

        # 1. Intentar inserción masiva (bulk) primero si hay más de 1 predio
        if len(npns) > 1:
            try:
                inserted = importar_predios_f_r1_r2_a_workspace(conn, tenant, npns, resolved_schema_work, t_basket_id)
                return {"inserted": inserted, "errors": []}
            except Exception as batch_err:
                logger.warning(f"La inserción masiva falló ({batch_err}), procediendo predio a predio con SAVEPOINTs...")
                try:
                    conn.rollback()
                except Exception:
                    pass

        # 2. Fallback / inserción individual con SAVEPOINT por predio para evitar InFailedSqlTransaction
        inserted = 0
        for idx, npn in enumerate(npns):
            sp_name = f"sp_predio_{idx}"
            try:
                with conn.cursor() as cur:
                    cur.execute(f"SAVEPOINT {sp_name};")
                importar_predio_f_r1_r2_a_workspace(conn, tenant, npn, resolved_schema_work, t_basket_id)
                with conn.cursor() as cur:
                    cur.execute(f"RELEASE SAVEPOINT {sp_name};")
                inserted += 1
            except Exception as e:
                try:
                    with conn.cursor() as cur:
                        cur.execute(f"ROLLBACK TO SAVEPOINT {sp_name};")
                except Exception:
                    pass
                logger.error(f"Error al importar predio {npn}: {e}")
                errors.append({"npn": npn, "error": str(e)})

    return {"inserted": inserted, "errors": errors}

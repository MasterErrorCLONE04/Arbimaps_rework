import sys
import time
import psycopg2
from psycopg2.extras import RealDictCursor

# Add /app to python path
sys.path.append("/app")

from core.db.connection import get_db_params
from tenants import TenantContext
from tenants.registry import MunicipalityRegistry
from services import asignaciones_workspace_sql as workspace_sql_service

def verify_records(conn, schema_work, dataset_name):
    """
    Queries the tables in the workspace schema to show the copied records counts.
    """
    from core.asignaciones import get_assignment_model_context
    model_ctx = get_assignment_model_context()
    is_arb = (model_ctx.predio_table == "arb_predio")

    if is_arb:
        tables = [
            "arb_predio",
            "arb_direccion",
            "arb_derechointeresadofuente",
            "arb_construccion",
            "arb_unidadconstruccion"
        ]
    else:
        tables = [
            "ilc_predio",
            "ilc_derecho",
            "extdireccion",
            "ilc_datosadicionaleslevantamientocatastral",
            "ilc_construccion",
            "ilc_unidadconstruccion"
        ]
    
    print("\n--- Workspace Record Verification ---")
    with conn.cursor() as cur:
        # Get the dataset t_id
        cur.execute(
            f"SELECT t_id FROM {schema_work}.t_ili2db_dataset WHERE datasetname = %s",
            (dataset_name,)
        )
        row = cur.fetchone()
        if not row:
            print(f"ERROR: Dataset '{dataset_name}' not found in t_ili2db_dataset!")
            return
        dataset_id = row[0]
        print(f"Dataset ID: {dataset_id} for '{dataset_name}'")

        # Let's count elements in each table belonging to the workspace baskets
        cur.execute(
            f"SELECT t_id FROM {schema_work}.t_ili2db_basket WHERE dataset = %s",
            (dataset_id,)
        )
        basket_ids = [r[0] for r in cur.fetchall()]
        print(f"Basket IDs in workspace: {basket_ids}")
        
        if not basket_ids:
            print("WARNING: No baskets found for this dataset!")
            return

        for table in tables:
            try:
                cur.execute(
                    f"SELECT COUNT(*) FROM {schema_work}.{table} WHERE t_basket = ANY(%s)",
                    (basket_ids,)
                )
                cnt = cur.fetchone()[0]
                print(f"  {table:45} : {cnt} records")
            except Exception as e:
                print(f"  {table:45} : Error/Not found ({str(e).strip()})")

def main():
    # 1. Parse arguments
    asig_id = 11
    if len(sys.argv) > 1:
        try:
            asig_id = int(sys.argv[1])
        except ValueError:
            print(f"Invalid assignment ID: {sys.argv[1]}. Using default: 11.")

    print(f"Running SQL checkout optimization test for Assignment ID: {asig_id}")

    # 2. Get connection and check assignment
    params = get_db_params()
    params['dbname'] = 'neiva'
    
    conn = psycopg2.connect(**params)
    conn.autocommit = False
    
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, titulo, work_datasetname, estado FROM arbimaps_app.asignacion WHERE id = %s", (asig_id,))
            asig = cur.fetchone()
            if not asig:
                print(f"ERROR: Assignment {asig_id} not found in database!")
                cur.execute("SELECT id, titulo, work_datasetname, estado FROM arbimaps_app.asignacion LIMIT 10")
                print("Available assignments:")
                for row in cur.fetchall():
                    print(f"  ID: {row[0]}, Title: {row[1]}, Dataset: {row[2]}, Status: {row[3]}")
                sys.exit(1)
            
            print(f"Found Assignment - Title: {asig[1]}, Work Dataset: {asig[2]}, Status: {asig[3]}")
            
            # Check number of active predios
            cur.execute(
                "SELECT count(*) FROM arbimaps_app.asignacion_predio WHERE asignacion_id = %s AND (activo IS NOT FALSE)",
                (asig_id,)
            )
            cnt = cur.fetchone()[0]
            print(f"Active predios in assignment: {cnt}")
            if cnt == 0:
                print("ERROR: Assignment has 0 active predios. Cannot perform checkout test.")
                sys.exit(1)

        # 3. Resolve tenant
        registry = MunicipalityRegistry.from_sources()
        tenant = TenantContext.from_config(registry.get("neiva"))
        
        # Determine dataset name to write to
        dataset_name = asig[2] if asig[2] else f"asig_{asig_id}"

        # 4. Run native SQL checkout
        print("\nStarting run_insertar_predios_for_asignacion...")
        start_time = time.time()
        
        # Execute the function
        result = workspace_sql_service.run_insertar_predios_for_asignacion(
            conn,
            tenant,
            asig_id,
            dataset_name=dataset_name,
            schema_work=tenant.schemas.work
        )
        
        elapsed = time.time() - start_time
        print(f"SQL Checkout completed in: {elapsed:.4f} seconds!")
        
        # Commit the transaction so we can verify records in the schema
        conn.commit()
        
        print("\nFunction result summary:")
        for k, v in result.items():
            print(f"  {k}: {v}")
            
        # 5. Query and count tables in workspace schema
        verify_records(conn, tenant.schemas.work, dataset_name)
        
    except Exception as e:
        conn.rollback()
        import traceback
        print("\nAn error occurred during test execution:")
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    main()

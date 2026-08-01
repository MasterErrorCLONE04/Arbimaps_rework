import sys
import psycopg2
from psycopg2.extras import RealDictCursor

# Append /app to sys.path so we can import from core
sys.path.append("/app")
from core.db.connection import get_db_params

def cleanup():
    params = get_db_params()
    # Explicitly connect to 'neiva' database inside the container
    params['dbname'] = 'neiva'
    
    print("Connecting to database with params:", {k: (v if k != 'password' else '***') for k, v in params.items()})
    
    conn = psycopg2.connect(**params)
    conn.autocommit = False # We want a transaction block
    
    try:
        with conn.cursor() as cur:
            # 1. Disable constraints/triggers
            print("Disabling triggers and foreign key checks...")
            cur.execute("SET session_replication_role = 'replica';")
            
            # 2. Select 100 random predios and keep them
            print("Selecting 100 predios to keep...")
            cur.execute("CREATE TEMP TABLE kept_predios AS SELECT t_id FROM a_base_principal.arb_predio LIMIT 100;")
            
            # Check how many predios we are keeping
            cur.execute("SELECT count(*) FROM kept_predios;")
            kept_count = cur.fetchone()[0]
            print(f"Keeping {kept_count} predios.")
            if kept_count == 0:
                print("Error: No predios found in database to keep!")
                return
            
            # 3. Query all foreign keys in the schema a_base_principal
            print("Querying foreign key relationships...")
            cur.execute("""
                SELECT
                    tc.table_name AS source_table,
                    kcu.column_name AS source_column,
                    ccu.table_name AS target_table,
                    ccu.column_name AS target_column
                FROM
                    information_schema.table_constraints AS tc
                    JOIN information_schema.key_column_usage AS kcu
                      ON tc.constraint_name = kcu.constraint_name
                      AND tc.table_schema = kcu.table_schema
                    JOIN information_schema.constraint_column_usage AS ccu
                      ON ccu.constraint_name = tc.constraint_name
                      AND ccu.table_schema = tc.table_schema
                WHERE
                    tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_schema = 'a_base_principal'
                    AND ccu.table_schema = 'a_base_principal';
            """)
            fkeys = cur.fetchall()
            print(f"Found {len(fkeys)} foreign key relationships in a_base_principal.")
            
            # 4. Perform fixed-point deletion loop
            iteration = 0
            while True:
                iteration += 1
                total_deleted = 0
                print(f"--- Iteration {iteration} ---")
                
                # Delete from arb_predio itself in the first iteration
                if iteration == 1:
                    print("Deleting non-kept predios from arb_predio...")
                    cur.execute("DELETE FROM a_base_principal.arb_predio WHERE t_id NOT IN (SELECT t_id FROM kept_predios);")
                    print(f"Deleted {cur.rowcount} non-kept predios.")
                    total_deleted += cur.rowcount
                
                for fkey in fkeys:
                    source_table, source_column, target_table, target_column = fkey
                    
                    # Special optimization: if target_table is arb_predio and target_column is t_id, we can compare directly with kept_predios
                    if target_table == 'arb_predio' and target_column == 't_id':
                        sql = f"""
                            DELETE FROM a_base_principal.{source_table}
                            WHERE {source_column} IS NOT NULL
                              AND {source_column} NOT IN (SELECT t_id FROM kept_predios);
                        """
                    else:
                        sql = f"""
                            DELETE FROM a_base_principal.{source_table}
                            WHERE {source_column} IS NOT NULL
                              AND {source_column} NOT IN (
                                  SELECT {target_column} FROM a_base_principal.{target_table} WHERE {target_column} IS NOT NULL
                              );
                        """
                    
                    cur.execute(sql)
                    deleted = cur.rowcount
                    if deleted > 0:
                        print(f"Deleted {deleted} rows from {source_table} (foreign key {source_column} -> {target_table}.{target_column})")
                        total_deleted += deleted
                
                print(f"Total deleted in iteration {iteration}: {total_deleted}")
                if total_deleted == 0:
                    print("Fixed point reached. No more rows deleted.")
                    break
            
            # 5. Reset session role
            cur.execute("SET session_replication_role = 'origin';")
            
        print("Committing transaction...")
        conn.commit()
        print("Database cleanup completed successfully!")
        
        # Verify counts of some main tables
        with conn.cursor() as cur:
            for tbl in ['arb_predio', 'arb_terreno', 'arb_construccion', 'arb_unidadconstruccion']:
                cur.execute(f"SELECT count(*) FROM a_base_principal.{tbl};")
                cnt = cur.fetchone()[0]
                print(f"Table a_base_principal.{tbl}: {cnt} rows remaining")
                
    except Exception as e:
        print("Error during cleanup. Rolling back changes...")
        conn.rollback()
        raise e
    finally:
        conn.close()

if __name__ == "__main__":
    cleanup()

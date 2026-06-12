from core.db.connection import get_db_params
import psycopg2

def list_assignments():
    p = get_db_params()
    p['dbname'] = 'programacion' # sucre DB
    conn = psycopg2.connect(**p)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, estado, usuario_asignado, usuario_reconocedor, creado_por, enlace_devolucion 
                FROM arbimaps_app.asignacion 
                WHERE usuario_asignado = 'juanita_rodriguez' OR usuario_reconocedor = 'juanita_rodriguez'
                ORDER BY id DESC LIMIT 20;
            """)
            print("Assignments for juanita_rodriguez:")
            for row in cur.fetchall():
                print(row)
    finally:
        conn.close()

if __name__ == "__main__":
    list_assignments()

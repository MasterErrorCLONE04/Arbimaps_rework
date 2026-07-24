import psycopg2
from core.db.connection import get_db_params

def main():
    params = get_db_params()
    conn = psycopg2.connect(**params)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, titulo, usuario_asignado, usuario_asignado_id, usuario_reconocedor, usuario_reconocedor_id, estado FROM arbimaps_app.asignacion")
            print("=== TODAS LAS ASIGNACIONES ===")
            for row in cur.fetchall():
                print(row)
    finally:
        conn.close()

if __name__ == "__main__":
    main()

import os
import psycopg2
from psycopg2.extras import RealDictCursor

conn = psycopg2.connect(
    host=os.environ.get("DB_HOST", "db"),
    port=os.environ.get("DB_PORT", 5432),
    dbname=os.environ.get("DB_NAME", "neiva"),
    user=os.environ.get("DB_USER", "postgres"),
    password=os.environ.get("DB_PASSWORD", "Arbitrium2026*")
)
cur = conn.cursor(cursor_factory=RealDictCursor)

cur.execute("""
    SELECT column_name FROM information_schema.columns 
    WHERE table_schema = 'a_base_principal' AND table_name = 'arb_predio'
    ORDER BY ordinal_position;
""")
cols = [r['column_name'] for r in cur.fetchall()]
print("COLUMNAS DE arb_predio:", cols)

npn = '410010107000001070946000000000'

cur.execute("""
    SELECT t_id, numero_predial, nombre 
    FROM a_base_principal.arb_predio 
    WHERE numero_predial = %s;
""", (npn,))

predios = cur.fetchall()
print("\nPREDIOS ENCONTRADOS:", [dict(p) for p in predios])

if predios:
    pid = predios[0]['t_id']
    print(f"\nBuscando en arb_direccion para arb_predio_direccion = {pid}:")
    cur.execute("""
        SELECT * FROM a_base_principal.arb_direccion 
        WHERE arb_predio_direccion::text = %s::text;
    """, (str(pid),))
    direcciones = cur.fetchall()
    print("DIRECCIONES ENCONTRADAS:", len(direcciones))
    for d in direcciones:
        print(dict(d))
else:
    print(f"\nBuscando si existe algo parecido a {npn}:")
    cur.execute("""
        SELECT t_id, numero_predial FROM a_base_principal.arb_predio 
        WHERE numero_predial LIKE %s LIMIT 5;
    """, (f"%{npn[-10:]}%",))
    print(cur.fetchall())

conn.close()


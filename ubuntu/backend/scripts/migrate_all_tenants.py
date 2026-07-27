import psycopg2
from main import app
from tenants import get_registry
from repositories.asignaciones_repo import ensure_asignacion_tables

registry = get_registry(app)
for cfg in registry.active():
    code = cfg.code
    print(f"Sincronizando: {code}")
    try:
        t = registry.get(code)
        db = t.db
        conn = psycopg2.connect(
            host=db.host,
            port=db.port,
            database=db.db_name,
            user=db.user,
            password=db.password
        )
        ensure_asignacion_tables(conn, t, force=True)
        conn.commit()
        conn.close()
        print(f"Tenant {code} OK")
    except Exception as e:
        print(f"Tenant {code} failed: {e}")

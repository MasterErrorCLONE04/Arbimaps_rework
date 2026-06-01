import sys
import json
import psycopg2
from psycopg2.extras import RealDictCursor

# We need to run inside the docker container because it has python environment and code.
sys.path.append("/app")

from routers.asignaciones_detalle import obtener_detalle_predio_completo_asignacion

# Mock TenantContext
class MockSchemas:
    def __init__(self, work):
        self.work = work
        self.app = "arbimaps_app"
        self.main = "b_asignaciones_arb"
        self.history = "b_asignaciones_arb"
        self.workflow = "b_asignaciones_arb"

class MockTenantContext:
    def __init__(self, tenant_id, work):
        self.tenant_id = tenant_id
        self.schemas = MockSchemas(work)
    def get_id(self):
        return self.tenant_id

tenant = MockTenantContext("default", "b_asignaciones_arb")

# Mock User
user = {"username": "admin", "role": "admin", "role_code": "admin"}

# Connect to database directly
conn = psycopg2.connect(
    host="db",
    port=5432,
    database="programacion",
    user="postgres",
    password="Arbitrium2026*",
    cursor_factory=RealDictCursor
)

try:
    res = obtener_detalle_predio_completo_asignacion(
        asignacion_id=135,
        predio_t_id=36867,
        user=user,
        tenant=tenant,
        conn=conn
    )
    print("API Response successfully obtained:")
    # Print only construcciones and units
    print(json.dumps({
        "construcciones": res.get("construcciones"),
        "unidades_construccion": res.get("unidades_construccion")
    }, indent=2, default=str))
except Exception as e:
    import traceback
    print("Error calling function:")
    traceback.print_exc()
finally:
    conn.close()

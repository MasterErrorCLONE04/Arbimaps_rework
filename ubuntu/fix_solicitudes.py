import sys

filepath = 'backend/routers/asignaciones.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

target1 = """def crear_solicitud(
    body: SolicitudCrearBody,
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):"""

rep1 = """def crear_solicitud(
    body: SolicitudCrearBody,
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    _ensure_asignacion_tables(conn, tenant)"""

if target1 in content:
    content = content.replace(target1, rep1)
else:
    print("Error: target1 not found")
    sys.exit(1)

target2 = """def listar_solicitudes(
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):"""

rep2 = """def listar_solicitudes(
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    _ensure_asignacion_tables(conn, tenant)"""

if target2 in content:
    content = content.replace(target2, rep2)
else:
    print("Error: target2 not found")
    sys.exit(1)

target3 = """def obtener_solicitud(
    id: int,
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):"""

rep3 = """def obtener_solicitud(
    id: int,
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    _ensure_asignacion_tables(conn, tenant)"""

if target3 in content:
    content = content.replace(target3, rep3)
else:
    print("Error: target3 not found")
    sys.exit(1)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("Fix completed!")

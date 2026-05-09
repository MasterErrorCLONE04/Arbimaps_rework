import os
from dotenv import load_dotenv
from mergin import MerginClient

# ==============================
# 🔐 CARGAR CONFIGURACIÓN
# ==============================
load_dotenv()

url = os.getenv("MERGIN_URL")
username = os.getenv("MERGIN_USERNAME")
password = os.getenv("MERGIN_PASSWORD")
workspace = os.getenv("MERGIN_WORKSPACE")

print(f"Conectando a: {url}")
print(f"Workspace objetivo: {workspace}")

# ==============================
# 🔌 CONEXIÓN
# ==============================
client = MerginClient(url)
client.login(username, password)

# ==============================
# 📦 OBTENER PROYECTOS
# ==============================
projects = client.projects_list()

# ==============================
# 🎯 FILTRAR SOLO LOS DEL WORKSPACE
# ==============================
filtered_projects = [
    p for p in projects if p["namespace"] == workspace
]

print("\n==============================")
print("🎯 PROYECTOS DE TRABAJO")
print("==============================\n")

if not filtered_projects:
    print("⚠️ No se encontraron proyectos en este workspace\n")
else:
    for p in filtered_projects:
        print(f"{p['namespace']}/{p['name']} - versión: {p['version']}")

print("\n==============================")
print(f"Total proyectos encontrados: {len(filtered_projects)}")
print("==============================\n")

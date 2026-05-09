import sys
sys.path.append("/home/ubuntu/backend")

import os
import shutil

from routers.box_client import create_folder, upload_file
from mergin import MerginClient
from dotenv import load_dotenv

print("🚀 INICIO SCRIPT")

# ==============================
# 🔐 CONFIG
# ==============================
load_dotenv("/home/ubuntu/mergin_sync/.env")

MERGIN_URL = os.getenv("MERGIN_URL")
MERGIN_USERNAME = os.getenv("MERGIN_USERNAME")
MERGIN_PASSWORD = os.getenv("MERGIN_PASSWORD")

ROOT_FOLDER_ID = "376705885660"  # ID de la carpeta raíz en Box donde se crearán los proyectos
TEMP_BASE = "/home/ubuntu/mergin_sync/temp"

TARGET_WORKSPACE = "Reconocimiento Predial"

os.makedirs(TEMP_BASE, exist_ok=True)

# ==============================
# 🔌 CONEXIÓN
# ==============================
print(f"🔌 Conectando a Mergin: {MERGIN_URL}")
client = MerginClient(MERGIN_URL)
client.login(MERGIN_USERNAME, MERGIN_PASSWORD)
print("✅ Login Mergin OK")

# ==============================
# 📋 LISTAR PROYECTOS
# ==============================
projects = client.projects_list()

print(f"\n🔎 Buscando proyectos en: {TARGET_WORKSPACE}\n")

for project in projects:
    try:
        if project["namespace"] != TARGET_WORKSPACE:
            continue

        full_project_name = f"{project['namespace']}/{project['name']}"
        project_name = project["name"]

        print("\n======================================")
        print(f"🚀 Procesando: {full_project_name}")
        print("======================================")

        LOCAL_PATH = f"{TEMP_BASE}/{project_name}"

        # ==============================
        # 🧹 LIMPIEZA PREVIA
        # ==============================
        if os.path.exists(LOCAL_PATH):
            print("🧹 Eliminando carpeta anterior...")
            shutil.rmtree(LOCAL_PATH)

        # ==============================
        # 📥 DESCARGA
        # ==============================
        print("📥 Descargando...")
        client.download_project(full_project_name, LOCAL_PATH)
        print("✅ Descarga completa")

        # ==============================
        # 🔍 CLASIFICACIÓN
        # ==============================
        photo_files = {}
        data_files = {}

        for root, dirs, files in os.walk(LOCAL_PATH):
            for file in files:
                full_path = os.path.join(root, file)
                folder_name = os.path.basename(root)

                if file.lower().endswith((".jpg", ".jpeg", ".png")):
                    photo_files.setdefault(folder_name, []).append(full_path)
                else:
                    data_files.setdefault(folder_name, []).append(full_path)

        # ==============================
        # 📊 RESULTADO
        # ==============================
        print("\n📊 RESULTADO:")

        total_photos = sum(len(v) for v in photo_files.values())
        total_data = sum(len(v) for v in data_files.values())

        print(f"📸 Fotos: {total_photos}")
        print(f"📦 Data: {total_data}")

        # ==============================
        # 📤 SUBIR A BOX
        # ==============================
        print("\n📤 Subiendo a Box...\n")

        VERSION = f"v{project.get('version', 'auto')}"

        project_folder_id = create_folder(ROOT_FOLDER_ID, project_name)
        version_folder_id = create_folder(project_folder_id, VERSION)

        data_folder_id = create_folder(version_folder_id, "data")
        photos_folder_id = create_folder(version_folder_id, "fotos")

        # ==============================
        # 📦 DATA
        # ==============================
        for category, files in data_files.items():
            category_folder_id = create_folder(data_folder_id, category)

            for file_path in files:
                print(f"⬆️ DATA: {file_path}")
                try:
                    uploaded_id = upload_file(category_folder_id, file_path)
                    if uploaded_id:
                        print(f"✅ DATA OK: {file_path}")
                    else:
                        print(f"⚠️ DATA SIN ID: {file_path}")
                except Exception as e:
                    print(f"❌ ERROR DATA {file_path}: {e}")

        # ==============================
        # 📸 FOTOS
        # ==============================
        for category, files in photo_files.items():
            category_folder_id = create_folder(photos_folder_id, category)

            for file_path in files:
                print(f"⬆️ FOTO: {file_path}")
                try:
                    uploaded_id = upload_file(category_folder_id, file_path)
                    if uploaded_id:
                        print(f"✅ FOTO OK: {file_path}")
                    else:
                        print(f"⚠️ FOTO SIN ID: {file_path}")
                except Exception as e:
                    print(f"❌ ERROR FOTO {file_path}: {e}")

        print("✅ SUBIDA COMPLETA")

        # ==============================
        # 🧹 LIMPIEZA FINAL
        # ==============================
        print("🧹 Eliminando archivos locales...")

        if os.path.exists(LOCAL_PATH):
            shutil.rmtree(LOCAL_PATH)
            print("✅ Carpeta eliminada")
        else:
            print("⚠️ No se encontró carpeta")

    except Exception as e:
        print(f"❌ ERROR PROCESANDO PROYECTO {project.get('name', 'SIN_NOMBRE')}: {e}")

print("\n🎉 PROCESO COMPLETO FINALIZADO\n")
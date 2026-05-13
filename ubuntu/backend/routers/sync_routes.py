from fastapi import APIRouter
import threading
import os
import shutil
import tempfile

from mergin import MerginClient
from dotenv import load_dotenv

from services.mergin_service import process_local_project_for_carpeteo
from routers.box_client import create_folder, upload_file

router = APIRouter()

load_dotenv("/app/.env")
load_dotenv("/mergin_sync/.env")

# estado global
progress = {
    "total": 0,
    "current": 0,
    "project": "",
    "status": "idle"
}

process_lock = threading.Lock()


# =========================================================
# 📁 CARPETEO NUEVO (POR NPN)
# =========================================================
def run_carpeteo():
    global progress

    if not process_lock.acquire(blocking=False):
        print("⚠️ Ya hay un proceso ejecutándose")
        return

    try:
        print("📁 INICIANDO CARPETEO POR NPN")

        MERGIN_URL = os.getenv("MERGIN_URL")
        MERGIN_USERNAME = os.getenv("MERGIN_USERNAME")
        MERGIN_PASSWORD = os.getenv("MERGIN_PASSWORD")

        # ✅ Aquí le dejas el root nuevo
        ROOT_FOLDER_ID = os.getenv("BOX_ROOT_FOLDER_ID", "377319267695")
        TARGET_WORKSPACE = "Reconocimiento Predial"
        TEMP_BASE = "/mergin_sync/temp_carpeteo"

        os.makedirs(TEMP_BASE, exist_ok=True)

        client = MerginClient(MERGIN_URL)
        client.login(MERGIN_USERNAME, MERGIN_PASSWORD)

        projects = client.projects_list()
        filtered = [p for p in projects if p["namespace"] == TARGET_WORKSPACE]

        progress["total"] = len(filtered)
        progress["current"] = 0
        progress["status"] = "running"
        progress["project"] = "Iniciando carpeteo..."

        for p in filtered:
            project_name = p["name"]
            full_project_name = f"{p['namespace']}/{p['name']}"
            local_project_path = os.path.join(TEMP_BASE, project_name)

            print("\n======================================")
            print(f"🚀 CARPETEO PROYECTO: {full_project_name}")
            print("======================================")

            progress["current"] += 1
            progress["project"] = project_name

            try:
                # limpiar si quedó algo anterior
                if os.path.exists(local_project_path):
                    shutil.rmtree(local_project_path)

                print("📥 Descargando proyecto para carpeteo...")
                client.download_project(full_project_name, local_project_path)
                print("✅ Descarga completa")

                process_local_project_for_carpeteo(
                    local_project_path=local_project_path,
                    root_box_folder_id=ROOT_FOLDER_ID,
                    create_folder=create_folder,
                    upload_file=upload_file
                )

                print(f"✅ Carpeteo completado para {project_name}")

            except Exception as e:
                print(f"❌ Error procesando {project_name}: {e}")

            finally:
                if os.path.exists(local_project_path):
                    shutil.rmtree(local_project_path, ignore_errors=True)
                    print(f"🧹 Carpeta temporal eliminada: {local_project_path}")

        progress["status"] = "done"
        progress["project"] = ""

    except Exception as e:
        print("❌ ERROR EN CARPETEO:", str(e))
        progress["status"] = "error"
        progress["project"] = str(e)

    finally:
        process_lock.release()


# =========================================================
# 🚀 ENDPOINTS
# =========================================================

@router.post("/create-carpeteo")
def create_carpeteo_endpoint():
    if progress["status"] == "running":
        return {"message": "Ya hay un proceso en curso"}

    thread = threading.Thread(target=run_carpeteo, daemon=True)
    thread.start()

    return {"message": "Carpeteo iniciado"}


@router.get("/sync-status")
def sync_status():
    return progress


@router.post("/sync-projects")
def sync_projects():
    global progress

    if progress["status"] == "running":
        return {"message": "Ya hay un proceso en curso"}

    def run_sync():
        global progress

        if not process_lock.acquire(blocking=False):
            print("⚠️ Ya hay un proceso ejecutándose")
            return

        try:
            import subprocess

            print("🚀 INICIANDO SYNC (script externo)")

            progress["status"] = "running"
            progress["current"] = 0
            progress["total"] = 1
            progress["project"] = "Ejecutando sincronización..."

            with open("/mergin_sync/sync.log", "w") as stdout_file, \
                 open("/mergin_sync/sync_error.log", "w") as stderr_file:

                result = subprocess.run(
                    [
                        "python",
                        "/mergin_sync/download_project.py"
                    ],
                    stdout=stdout_file,
                    stderr=stderr_file,
                    check=False
                )

            if result.returncode == 0:
                print("✅ SYNC COMPLETADO")
                progress["status"] = "done"
                progress["current"] = 1
                progress["project"] = ""
            else:
                print("❌ SYNC FALLÓ")
                progress["status"] = "error"
                progress["project"] = "Revisa sync_error.log"

        except Exception as e:
            print("❌ ERROR EN SYNC:", str(e))
            progress["status"] = "error"
            progress["project"] = str(e)

        finally:
            process_lock.release()

    thread = threading.Thread(target=run_sync, daemon=True)
    thread.start()

    return {"message": "Sync iniciado"}
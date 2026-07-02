from fastapi import APIRouter
import os
import shutil
import subprocess
import threading

from dotenv import load_dotenv
from mergin import MerginClient

from routers.box_client import create_folder, upload_file
from services.mergin_service import process_local_project_for_carpeteo

router = APIRouter()

load_dotenv("/app/.env")
load_dotenv("/mergin_sync/.env")

progress = {
    "total": 0,
    "current": 0,
    "project": "",
    "status": "idle",
}

process_lock = threading.Lock()


def get_mergin_config():
    config = {
        "url": os.getenv("MERGIN_URL"),
        "username": os.getenv("MERGIN_USERNAME"),
        "password": os.getenv("MERGIN_PASSWORD"),
        "workspace": os.getenv("MERGIN_WORKSPACE", "Reconocimiento Predial").strip(),
    }
    missing = [key for key, value in config.items() if not value]
    if missing:
        raise RuntimeError(f"Faltan variables de Mergin: {', '.join(missing)}")
    return config


def project_temp_path(temp_base, project_name):
    temp_base = os.path.abspath(temp_base)
    local_path = os.path.abspath(os.path.join(temp_base, project_name))
    if not local_path.startswith(temp_base + os.sep):
        raise RuntimeError(f"Ruta temporal insegura para proyecto: {project_name}")
    return local_path


def remove_temp_path(local_path):
    if os.path.exists(local_path):
        shutil.rmtree(local_path, ignore_errors=True)
        print(f"Carpeta temporal eliminada: {local_path}")


def run_carpeteo():
    global progress

    if not process_lock.acquire(blocking=False):
        print("Ya hay un proceso ejecutandose")
        return

    try:
        print("INICIANDO CARPETEO POR NPN")

        config = get_mergin_config()
        root_folder_id = os.getenv("BOX_ROOT_FOLDER_ID", "377319267695").strip()
        temp_base = "/mergin_sync/temp_carpeteo"
        os.makedirs(temp_base, exist_ok=True)

        client = MerginClient(config["url"])
        client.login(config["username"], config["password"])

        projects = client.projects_list()
        filtered = [p for p in projects if p["namespace"] == config["workspace"]]
        failed_projects = 0

        progress["total"] = len(filtered)
        progress["current"] = 0
        progress["status"] = "running"
        progress["project"] = "Iniciando carpeteo..."

        if not filtered:
            raise RuntimeError(f"No se encontraron proyectos en el workspace: {config['workspace']}")

        for project in filtered:
            project_name = project["name"]
            full_project_name = f"{project['namespace']}/{project['name']}"
            local_project_path = project_temp_path(temp_base, project_name)

            print("\n======================================")
            print(f"CARPETEO PROYECTO: {full_project_name}")
            print("======================================")

            progress["current"] += 1
            progress["project"] = project_name

            try:
                remove_temp_path(local_project_path)

                print("Descargando proyecto para carpeteo...")
                client.download_project(full_project_name, local_project_path)
                print("Descarga completa")

                process_local_project_for_carpeteo(
                    local_project_path=local_project_path,
                    root_box_folder_id=root_folder_id,
                    create_folder=create_folder,
                    upload_file=upload_file,
                )

                print(f"Carpeteo completado para {project_name}")

            except Exception as exc:
                failed_projects += 1
                print(f"Error procesando {project_name}: {exc}")

            finally:
                remove_temp_path(local_project_path)

        if failed_projects:
            raise RuntimeError(f"Carpeteo terminado con {failed_projects} proyecto(s) fallidos")

        progress["status"] = "done"
        progress["project"] = ""

    except Exception as exc:
        print("ERROR EN CARPETEO:", str(exc))
        progress["status"] = "error"
        progress["project"] = str(exc)

    finally:
        process_lock.release()


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
            print("Ya hay un proceso ejecutandose")
            return

        try:
            print("INICIANDO SYNC (script externo)")

            progress["status"] = "running"
            progress["current"] = 0
            progress["total"] = 1
            progress["project"] = "Ejecutando sincronizacion..."

            with open("/mergin_sync/sync.log", "w", encoding="utf-8") as stdout_file, \
                 open("/mergin_sync/sync_error.log", "w", encoding="utf-8") as stderr_file:
                result = subprocess.run(
                    ["python", "/mergin_sync/download_project.py"],
                    stdout=stdout_file,
                    stderr=stderr_file,
                    check=False,
                )

            if result.returncode == 0:
                print("SYNC COMPLETADO")
                progress["status"] = "done"
                progress["current"] = 1
                progress["project"] = ""
            else:
                print("SYNC FALLO")
                progress["status"] = "error"
                progress["project"] = "Revisa sync_error.log"

        except Exception as exc:
            print("ERROR EN SYNC:", str(exc))
            progress["status"] = "error"
            progress["project"] = str(exc)

        finally:
            process_lock.release()

    thread = threading.Thread(target=run_sync, daemon=True)
    thread.start()

    return {"message": "Sync iniciado"}

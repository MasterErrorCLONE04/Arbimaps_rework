import os
import shutil
import sys

sys.path.append("/app")

from dotenv import load_dotenv
from mergin import MerginClient
from routers.box_client import create_folder, upload_file

print("INICIO SCRIPT MERGIN SYNC")

load_dotenv("/app/.env")
load_dotenv("/mergin_sync/.env")

MERGIN_URL = os.getenv("MERGIN_URL")
MERGIN_USERNAME = os.getenv("MERGIN_USERNAME")
MERGIN_PASSWORD = os.getenv("MERGIN_PASSWORD")
MERGIN_WORKSPACE = os.getenv("MERGIN_WORKSPACE", "Reconocimiento Predial").strip()
ROOT_FOLDER_ID = os.getenv("BOX_MERGIN_SYNC_ROOT_FOLDER_ID", "376705885660").strip()
TEMP_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "temp"))
PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff")


def require_config():
    missing = [
        name for name, value in {
            "MERGIN_URL": MERGIN_URL,
            "MERGIN_USERNAME": MERGIN_USERNAME,
            "MERGIN_PASSWORD": MERGIN_PASSWORD,
            "MERGIN_WORKSPACE": MERGIN_WORKSPACE,
            "BOX_MERGIN_SYNC_ROOT_FOLDER_ID": ROOT_FOLDER_ID,
        }.items()
        if not value
    ]

    if missing:
        raise RuntimeError(f"Faltan variables de entorno: {', '.join(missing)}")


def project_temp_path(project_name):
    local_path = os.path.abspath(os.path.join(TEMP_BASE, project_name))
    if not local_path.startswith(TEMP_BASE + os.sep):
        raise RuntimeError(f"Ruta temporal insegura para proyecto: {project_name}")
    return local_path


def remove_local_project(local_path):
    if os.path.exists(local_path):
        print(f"Eliminando carpeta temporal: {local_path}")
        shutil.rmtree(local_path)


def classify_files(local_path):
    photo_files = {}
    data_files = {}

    for root, dirs, files in os.walk(local_path):
        dirs[:] = [d for d in dirs if d != ".mergin"]

        for file_name in files:
            full_path = os.path.join(root, file_name)
            folder_name = os.path.basename(root)

            if file_name.lower().endswith(PHOTO_EXTENSIONS):
                photo_files.setdefault(folder_name, []).append(full_path)
            else:
                data_files.setdefault(folder_name, []).append(full_path)

    return photo_files, data_files


def upload_group(parent_folder_id, category, files, label):
    failures = 0
    category_folder_id = create_folder(parent_folder_id, category)

    for file_path in files:
        print(f"SUBIENDO {label}: {file_path}")
        try:
            uploaded_id = upload_file(category_folder_id, file_path)
            if uploaded_id:
                print(f"{label} OK: {file_path}")
            else:
                failures += 1
                print(f"{label} SIN ID: {file_path}")
        except Exception as exc:
            failures += 1
            print(f"ERROR {label} {file_path}: {exc}")

    return failures


def process_project(client, project):
    full_project_name = f"{project['namespace']}/{project['name']}"
    project_name = project["name"]
    local_path = project_temp_path(project_name)
    failures = 0

    print("\n======================================")
    print(f"Procesando: {full_project_name}")
    print("======================================")

    try:
        remove_local_project(local_path)

        print("Descargando proyecto...")
        client.download_project(full_project_name, local_path)
        print("Descarga completa")

        photo_files, data_files = classify_files(local_path)
        total_photos = sum(len(v) for v in photo_files.values())
        total_data = sum(len(v) for v in data_files.values())

        print("\nRESULTADO:")
        print(f"Fotos: {total_photos}")
        print(f"Data: {total_data}")

        print("\nSubiendo a Box...\n")
        version = f"v{project.get('version', 'auto')}"
        project_folder_id = create_folder(ROOT_FOLDER_ID, project_name)
        version_folder_id = create_folder(project_folder_id, version)
        data_folder_id = create_folder(version_folder_id, "data")
        photos_folder_id = create_folder(version_folder_id, "fotos")

        for category, files in data_files.items():
            failures += upload_group(data_folder_id, category, files, "DATA")

        for category, files in photo_files.items():
            failures += upload_group(photos_folder_id, category, files, "FOTO")

        if failures:
            raise RuntimeError(f"Proyecto {project_name} termino con {failures} archivo(s) fallidos")

        print("SUBIDA COMPLETA")
        return 0

    finally:
        remove_local_project(local_path)


def main():
    require_config()
    os.makedirs(TEMP_BASE, exist_ok=True)

    print(f"Conectando a Mergin: {MERGIN_URL}")
    client = MerginClient(MERGIN_URL)
    client.login(MERGIN_USERNAME, MERGIN_PASSWORD)
    print("Login Mergin OK")

    projects = client.projects_list()
    filtered_projects = [p for p in projects if p["namespace"] == MERGIN_WORKSPACE]

    print(f"\nBuscando proyectos en: {MERGIN_WORKSPACE}")
    print(f"Proyectos encontrados: {len(filtered_projects)}\n")

    if not filtered_projects:
        raise RuntimeError(f"No se encontraron proyectos en el workspace: {MERGIN_WORKSPACE}")

    failed_projects = 0

    for project in filtered_projects:
        try:
            process_project(client, project)
        except Exception as exc:
            failed_projects += 1
            print(f"ERROR PROCESANDO PROYECTO {project.get('name', 'SIN_NOMBRE')}: {exc}")

    if failed_projects:
        raise RuntimeError(f"Sync terminado con {failed_projects} proyecto(s) fallidos")

    print("\nPROCESO COMPLETO FINALIZADO\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR GENERAL: {exc}", file=sys.stderr)
        sys.exit(1)

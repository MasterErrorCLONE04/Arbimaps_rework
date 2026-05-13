import os
from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from dotenv import load_dotenv
from routers.box_client import get_client, clean_box_id

load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

router = APIRouter(prefix="/box", tags=["box"])

# raíz configurada
BOX_ROOT_FOLDER_ID = clean_box_id(os.getenv("BOX_ROOT_FOLDER_ID", "369427324549"))


# ===============================
# LISTAR ARCHIVOS
# ===============================
@router.get("/list")
def list_files(folder_id: str = ""):
    client = get_client()

    try:
        effective_folder_id = clean_box_id(folder_id or BOX_ROOT_FOLDER_ID)
        folder = client.folder(folder_id=effective_folder_id).get()

        items = []
        for item in client.folder(effective_folder_id).get_items(limit=1000):
            items.append({
                "id": item.id,
                "name": item.name,
                "type": item.type
            })

        return {
            "folder_id": effective_folder_id,
            "folder": folder.name,
            "items": items,
            "root_folder_id": BOX_ROOT_FOLDER_ID
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===============================
# SUBIR ARCHIVO
# ===============================
@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder_id: str = Form("")
):
    client = get_client()

    try:
        effective_folder_id = clean_box_id(folder_id or BOX_ROOT_FOLDER_ID)
        folder = client.folder(effective_folder_id)

        uploaded = folder.upload_stream(
            file.file,
            file.filename
        )

        return {
            "ok": True,
            "folder_id": effective_folder_id,
            "id": uploaded.id,
            "name": uploaded.name
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===============================
# SUBIR ARCHIVO DESDE QGIS
# ===============================
@router.post("/upload_qgis")
async def upload_qgis(file: UploadFile = File(None)):
    client = get_client()

    try:
        if not file:
            raise HTTPException(status_code=400, detail="Archivo no recibido")

        folder = client.folder(BOX_ROOT_FOLDER_ID)

        uploaded = folder.upload_stream(
            file.file,
            file.filename
        )

        return {
            "ok": True,
            "id": uploaded.id,
            "name": uploaded.name,
            "folder_id": BOX_ROOT_FOLDER_ID
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===============================
# CREAR CARPETA
# ===============================
@router.post("/mkdir")
def mkdir(
    name: str = Form(...),
    parent_id: str = Form("")
):
    client = get_client()

    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Falta 'name'")

    try:
        effective_parent_id = clean_box_id(parent_id or BOX_ROOT_FOLDER_ID)

        folder = client.folder(folder_id=effective_parent_id).create_subfolder(name.strip())

        return {
            "ok": True,
            "id": folder.id,
            "name": folder.name,
            "parent_id": effective_parent_id
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===============================
# GENERAR SHARED LINK
# ===============================
@router.get("/share")
def share_file(file_id: str):
    client = get_client()

    try:
        file_id = clean_box_id(file_id)
        f = client.file(file_id).get()

        if getattr(f, "shared_link", None) and f.shared_link:
            return {
                "file_id": file_id,
                "url": f.shared_link.get("url")
            }

        shared_url = client.file(file_id).get_shared_link(access="open")

        return {
            "file_id": file_id,
            "url": shared_url
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===============================
# RENOMBRAR ARCHIVOS Y CARPETAS
# ===============================
@router.post("/rename")
def rename_item(
    item_type: str = Form(...),
    item_id: str = Form(...),
    new_name: str = Form(...)
):
    client = get_client()

    try:
        item_id = clean_box_id(item_id)
        if item_type == "file":
            obj = client.file(item_id).update_info(data={"name": new_name})
        elif item_type == "folder":
            obj = client.folder(item_id).update_info(data={"name": new_name})
        else:
            raise HTTPException(status_code=400, detail="Tipo inválido")

        return {
            "id": obj.id,
            "name": obj.name
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===============================
# ABRIR / PREVIEW ITEM
# ===============================
@router.get("/open")
def open_item(item_type: str, item_id: str):
    client = get_client()

    try:
        item_id = clean_box_id(item_id)
        if item_type == "file":
            obj = client.file(item_id).get()
        elif item_type == "folder":
            obj = client.folder(item_id).get()
        else:
            raise HTTPException(status_code=400, detail="item_type debe ser file o folder")

        if obj.shared_link:
            url = obj.shared_link["url"]
        else:
            url = client.file(item_id).get_shared_link(access="open")

        token = url.split("/s/")[-1].split("?")[0]
        preview_url = f"https://app.box.com/embed/s/{token}"

        return {
            "type": item_type,
            "id": item_id,
            "name": obj.name,
            "url": url,
            "preview_url": preview_url
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
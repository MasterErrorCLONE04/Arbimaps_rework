from fastapi import APIRouter, UploadFile, File
from routers.box_client import get_client
import os

router = APIRouter(prefix="/docs/service", tags=["docs"])

BOX_ROOT_FOLDER_ID = os.getenv("BOX_ROOT_FOLDER_ID", "0")


# ===============================
# INFO DEL SERVICIO (QGIS VALIDATION)
# ===============================
@router.get("/")
def service_info():
    return {
        "valid": True,
        "name": "Arbimaps Document Service",
        "version": "1.0",
        "type": "document_repository",
        "operations": {
            "upload": {
                "method": "POST",
                "url": "https://arbitriumsas.arbimaps.com/api/docs/service/upload"
            },
            "list": {
                "method": "GET",
                "url": "https://arbitriumsas.arbimaps.com/api/docs/service/list"
            }
        }
    }


# ===============================
# VALIDAR SERVICIO
# ===============================
@router.get("/validate")
def validate():
    return {
        "valid": True,
        "message": "Service OK"
    }


# ===============================
# UPLOAD (QGIS)
# ===============================
@router.post("/upload")
async def upload_qgis(file: UploadFile = File(...)):

    client = get_client()

    try:

        folder = client.folder(BOX_ROOT_FOLDER_ID)

        uploaded = folder.upload_stream(
            file.file,
            file.filename
        )

        return {
            "success": True,
            "data": {
                "id": uploaded.id,
                "name": uploaded.name,
                "url": f"/api/box/open?item_type=file&item_id={uploaded.id}"
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ===============================
# LISTAR
# ===============================
@router.get("/list")
def list_files():

    client = get_client()

    try:

        items = []
        for item in client.folder(BOX_ROOT_FOLDER_ID).get_items(limit=1000):
            items.append({
                "id": item.id,
                "name": item.name,
                "type": item.type
            })

        return {
            "success": True,
            "files": items
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
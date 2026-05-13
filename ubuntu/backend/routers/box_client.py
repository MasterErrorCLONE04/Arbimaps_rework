from boxsdk import JWTAuth, Client, OAuth2
from boxsdk.exception import BoxAPIException
import os
import json

BOX_AUTH_MODE = os.getenv("BOX_AUTH_MODE", "jwt")
BOX_CONFIG_FILE = os.getenv("BOX_CONFIG_FILE", "/home/ubuntu/backend/box_config.json")
BOX_TOKENS_FILE = os.getenv("BOX_TOKENS_FILE", "/home/ubuntu/backend/tokens/box_oauth_tokens.json")


def clean_box_id(item_id: str) -> str:
    """Elimina cualquier prefijo o carácter no numérico de los IDs de Box."""
    if not item_id:
        return item_id
    
    s_id = str(item_id).strip()
    # Filtramos para dejar ÚNICAMENTE los números
    cleaned_id = "".join(filter(str.isdigit, s_id))
    
    print(f"DEBUG: ID Original: '{item_id}' -> ID Limpio: '{cleaned_id}'")
    return cleaned_id


def save_tokens(access_token, refresh_token):
    print("🔄 Nuevo access token generado")
    print("🔄 Nuevo refresh token generado")

    os.makedirs(os.path.dirname(BOX_TOKENS_FILE), exist_ok=True)

    data = {
        "access_token": access_token,
        "refresh_token": refresh_token
    }

    with open(BOX_TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)

    print(f"✅ Tokens actualizados en {BOX_TOKENS_FILE}")


def load_tokens():
    if os.path.exists(BOX_TOKENS_FILE):
        with open(BOX_TOKENS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("access_token"), data.get("refresh_token")

    return os.getenv("BOX_ACCESS_TOKEN"), os.getenv("BOX_REFRESH_TOKEN")


if BOX_AUTH_MODE == "oauth":
    access_token, refresh_token = load_tokens()

    auth = OAuth2(
        client_id=os.getenv("BOX_CLIENT_ID"),
        client_secret=os.getenv("BOX_CLIENT_SECRET"),
        access_token=access_token,
        refresh_token=refresh_token,
        store_tokens=save_tokens
    )
    client = Client(auth)
    print("✅ Box conectado en modo OAuth")
else:
    auth = JWTAuth.from_settings_file(BOX_CONFIG_FILE)
    client = Client(auth)
    print("✅ Box conectado en modo JWT")


def get_client():
    return client


def create_folder(parent_folder_id, folder_name):
    import time

    parent_folder_id = clean_box_id(parent_folder_id)
    for intento in range(3):
        try:
            folder = client.folder(parent_folder_id).create_subfolder(folder_name)
            print(f"📁 Carpeta creada: {folder_name} ({folder.id})")
            return folder.id

        except BoxAPIException as e:
            if e.status == 409:
                print(f"⚠️ La carpeta ya existe: {folder_name}. Buscando ID... intento {intento + 1}/3")

                try:
                    items = client.folder(parent_folder_id).get_items(limit=1000)
                    for item in items:
                        if item.type == "folder" and item.name == folder_name:
                            print(f"📁 Carpeta reutilizada: {folder_name} ({item.id})")
                            return item.id
                except Exception as inner_e:
                    print(f"⚠️ Error buscando carpeta existente: {inner_e}")

                time.sleep(1)
                continue

            print(f"❌ Error creando carpeta {folder_name}: {e}")
            raise e

        except Exception as e:
            print(f"❌ Error inesperado creando carpeta {folder_name}: {e}")
            raise e

    raise Exception(f"No se pudo crear ni reutilizar la carpeta '{folder_name}' en parent {parent_folder_id}")


def upload_file(folder_id, file_path):
    folder_id = clean_box_id(folder_id)
    file_name = os.path.basename(file_path)

    try:
        uploaded_file = client.folder(folder_id).upload(file_path)
        print(f"⬆️ Archivo subido: {file_name} ({uploaded_file.id})")
        return uploaded_file.id

    except BoxAPIException as e:
        if e.status == 409:
            print(f"⚠️ El archivo ya existe en Box: {file_name}. Reemplazando...")

            items = client.folder(folder_id).get_items(limit=1000)
            for item in items:
                if item.type == "file" and item.name == file_name:
                    updated_file = client.file(item.id).update_contents(file_path)
                    print(f"♻️ Archivo reemplazado: {file_name} ({updated_file.id})")
                    return updated_file.id

        print(f"❌ Error subiendo {file_name}: {e}")
        return None

    except Exception as e:
        print(f"❌ Error inesperado subiendo {file_name}: {e}")
        return None


def list_folder_items(folder_id):
    folder_id = clean_box_id(folder_id)
    try:
        items = client.folder(folder_id).get_items(limit=1000)

        result = []
        for item in items:
            result.append({
                "id": item.id,
                "name": item.name,
                "type": item.type
            })

        return result

    except Exception as e:
        print("❌ Error listando carpeta:", e)
        return []


def download_file(file_id, output_path):
    file_id = clean_box_id(file_id)
    try:
        with open(output_path, "wb") as f:
            client.file(file_id).download_to(f)

    except Exception as e:
        print("❌ Error descargando archivo:", e)
import os
from boxsdk import JWTAuth, Client

config = JWTAuth.from_settings_file("/home/ubuntu/backend/box_config.json")
client = Client(config)

folder_id = os.getenv("BOX_ROOT_FOLDER_ID", "369427324549")
if folder_id.startswith('d_'):
    folder_id = folder_id[2:]

file_path = "/tmp/prueba_box.txt"

# Crear archivo de prueba si no existe
if not os.path.exists(file_path):
    with open(file_path, "w") as f:
        f.write("Prueba de subida a Box")

with open(file_path, "rb") as f:
    uploaded = client.folder(folder_id).upload_stream(
        f,
        os.path.basename(file_path)
    )

print("Archivo subido a Box:", uploaded.id)

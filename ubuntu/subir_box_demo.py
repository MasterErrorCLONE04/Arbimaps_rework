import os
from boxsdk import JWTAuth, Client

config = JWTAuth.from_settings_file("/home/ubuntu/backend/box_config.json")
client = Client(config)

folder_id = os.getenv("BOX_ROOT_FOLDER_ID")

file_path = "/tmp/prueba_box.txt"

with open(file_path, "rb") as f:
    uploaded = client.folder(folder_id).upload_stream(
        f,
        os.path.basename(file_path)
    )

print("Archivo subido a Box:", uploaded.id)

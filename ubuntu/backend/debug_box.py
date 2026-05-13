import os
from boxsdk import JWTAuth, Client
from dotenv import load_dotenv

# Cargar .env de la carpeta actual
load_dotenv(".env")

def test_box():
    config_path = "box_config.json"
    if not os.path.exists(config_path):
        print(f"❌ No se encuentra {config_path}")
        return

    print(f"🔄 Conectando a Box usando {config_path}...")
    auth = JWTAuth.from_settings_file(config_path)
    client = Client(auth)

    try:
        me = client.user().get()
        print(f"✅ Conectado como: {me.name} (ID: {me.id})")
    except Exception as e:
        print(f"❌ Error de autenticación: {e}")
        return

    # ID que parece ser el correcto según el listado anterior
    target_id = "369427324549"
    
    print(f"🔎 Intentando obtener carpeta ID: {target_id}...")
    try:
        folder = client.folder(target_id).get()
        print(f"✅ CARPETA ENCONTRADA: {folder.name}")
        
        print("📁 Listando primeros 5 ítems:")
        items = folder.get_items(limit=5)
        for item in items:
            print(f" - [{item.type}] {item.name} (ID: {item.id})")
            
    except Exception as e:
        print(f"❌ ERROR AL ACCEDER A LA CARPETA: {e}")
        if hasattr(e, 'context_info'):
            print(f"📝 Context Info: {e.context_info}")

if __name__ == "__main__":
    test_box()

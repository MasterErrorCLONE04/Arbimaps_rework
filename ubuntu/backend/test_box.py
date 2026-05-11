from routers.box_client import get_client

client = get_client()
me = client.user().get()
print("OK Box conectado. Usuario:", me.name, "ID:", me.id)

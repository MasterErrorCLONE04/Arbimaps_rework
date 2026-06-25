import random
import itertools
from locust import HttpUser, task, between

user_counter = itertools.count(1)

class ArbimapsVisorUser(HttpUser):
    # Simula un tiempo de espera aleatorio más dinámico entre 0.5 y 2.5 segundos para reflejar exploración cartográfica activa
    wait_time = between(0.5, 2.5)

    def on_start(self):
        """
        Inicia sesión en la plataforma y almacena las cookies de sesión autenticadas.
        Aplica un parche para corregir el escape de cookies de Nginx/FastAPI.
        """
        idx = next(user_counter)
        self.username = f"user_stress_{(idx - 1) % 500 + 1}"
        self.password = "Arbitrium2026*"
        self.municipality = "sucre"
        
        # Realizar el login
        response = self.client.post("/login", data={
            "municipality_code": self.municipality,
            "username": self.username,
            "password": self.password
        }, allow_redirects=False)
        
        if response.status_code == 302:
            # Corregir el bug de escape de cookies en la respuesta
            set_cookie = response.headers.get("Set-Cookie", "")
            parts = set_cookie.split(";")
            session_user_part = parts[0].strip()
            if session_user_part.startswith("session_user="):
                val = session_user_part[len("session_user="):]
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                decoded_val = val.replace(r"\054", ",").replace('\\"', '"')
                self.client.cookies.clear()
                self.client.cookies.set("session_user", decoded_val, domain="desarrollo.arbimaps.com", path="/")
        else:
            print(f"Error de login para {self.username} en {self.municipality}: {response.status_code}")

    @task(3)
    def query_project_extent(self):
        """
        Tarea: Obtener la extensión del proyecto.
        """
        self.client.get("/visor/project-extent")

    @task(3)
    def query_total_predios(self):
        """
        Tarea: Obtener el total de predios.
        """
        self.client.get("/visor/total-predios")

    @task(3)
    def query_resumen_proyecto(self):
        """
        Tarea: Obtener el resumen general del proyecto.
        """
        self.client.get("/resumenp/proyecto")

    @task(25)
    def request_geoserver_wms(self):
        """
        Tarea: Simular la carga intensiva de teselas de mapa (WMS) al hacer zoom/desplazamiento.
        """
        # Para hacer la carga WMS más real, generamos coordenadas BBOX ligeramente distintas
        # simulando navegación por cuadrícula alrededor del casco urbano de Sucre
        x = round(random.uniform(-74.12, -74.08), 4)
        y = round(random.uniform(4.48, 4.52), 4)
        bbox = f"{x},{y},{x+0.01},{y+0.01}"
        
        wms_params = {
            "service": "WMS",
            "version": "1.1.1",
            "request": "GetMap",
            "layers": "SUCRE:SUCRE_CARTOGRAFIA",
            "styles": "",
            "bbox": bbox,
            "width": "256",
            "height": "256",
            "srs": "EPSG:4326",
            "format": "image/png",
            "transparent": "true"
        }
        self.client.get("/proxy/wms", params=wms_params)

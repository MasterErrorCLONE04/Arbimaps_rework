import random
import itertools
from locust import HttpUser, task, between

# Thread-safe counter to assign a unique user to each virtual user
user_counter = itertools.count(1)

class ArbimapsUser(HttpUser):
    # Simula un tiempo de espera aleatorio entre 1 y 5 segundos
    wait_time = between(1, 5)

    def on_start(self):
        """
        Inicia sesión en la plataforma y almacena las cookies de sesión autenticadas.
        Aplica un parche para corregir el escape de cookies de Nginx/FastAPI.
        """
        idx = next(user_counter)
        # Asigna secuencialmente uno de los 500 usuarios creados
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

    @task(2)
    def view_protected_endpoint(self):
        """
        Tarea: Consultar el endpoint de usuario protegido para verificar autenticación activa.
        """
        self.client.get("/api/protected")

    @task(3)
    def query_project_extent(self):
        """
        Tarea: Obtener la extensión del proyecto para el visor.
        """
        self.client.get("/visor/project-extent")

    @task(3)
    def query_total_predios(self):
        """
        Tarea: Obtener el total de predios para el visor.
        """
        self.client.get("/visor/total-predios")

    @task(3)
    def query_resumen_proyecto(self):
        """
        Tarea: Obtener el resumen general del proyecto.
        """
        self.client.get("/resumenp/proyecto")

    @task(5)
    def request_geoserver_wms(self):
        """
        Tarea: Simular la carga de teselas cartográficas (capas WMS) a través de GeoServer.
        """
        wms_params = {
            "service": "WMS",
            "version": "1.1.1",
            "request": "GetMap",
            "layers": "SUCRE:SUCRE_CARTOGRAFIA",
            "styles": "",
            "bbox": "-74.1,4.5,-74.0,4.6",
            "width": "256",
            "height": "256",
            "srs": "EPSG:4326",
            "format": "image/png",
            "transparent": "true"
        }
        self.client.get("/proxy/wms", params=wms_params)

    @task(2)
    def search_predio_restrictions(self):
        """
        Tarea: Obtener listado de restricciones de predios.
        """
        self.client.get("/restriccion-predios/list")

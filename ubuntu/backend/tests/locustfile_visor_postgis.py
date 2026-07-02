import random
import itertools
from locust import HttpUser, task, between

# Thread-safe counter to assign a unique user to each virtual user
user_counter = itertools.count(1)

class ArbimapsVisorPostGISUser(HttpUser):
    # Simula un tiempo de espera aleatorio más dinámico entre 0.5 y 2.5 segundos para reflejar exploración cartográfica activa
    wait_time = between(0.5, 2.5)

    def on_start(self):
        """
        Inicia sesión en la plataforma y almacena las cookies de sesión autenticadas.
        Obtiene la extensión geográfica (extent) del proyecto para realizar búsquedas espaciales válidas.
        """
        idx = next(user_counter)
        self.username = f"user_stress_{(idx - 1) % 500 + 1}"
        self.password = "Arbitrium2026*"
        self.municipality = "sucre"
        
        # Coordenadas por defecto (fallbacks en EPSG:9377 cerca del origen nacional 5M, 2M)
        self.xmin = 4990000.0
        self.ymin = 1990000.0
        self.xmax = 5010000.0
        self.ymax = 2010000.0
        
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
                
            # Obtener el extent del proyecto
            ext_response = self.client.get("/visor/project-extent")
            if ext_response.status_code == 200:
                try:
                    data = ext_response.json()
                    self.xmin = float(data["xmin"])
                    self.ymin = float(data["ymin"])
                    self.xmax = float(data["xmax"])
                    self.ymax = float(data["ymax"])
                except Exception as e:
                    print(f"Error parsing project extent: {e}")
        else:
            print(f"Error de login para {self.username} en {self.municipality}: {response.status_code}")

    @task(10)
    def query_terrenos_snap(self):
        """
        Tarea: Simular la solicitud de snapping al digitalizar/editar geometría.
        Envía un bounding box aleatorio y dinámico dentro de la extensión del proyecto.
        """
        # Elegir un centro aleatorio dentro del extent
        cx = random.uniform(self.xmin, self.xmax)
        cy = random.uniform(self.ymin, self.ymax)
        
        # Ventana de snapping de 100x100 metros
        half_width = 50.0
        minx = cx - half_width
        miny = cy - half_width
        maxx = cx + half_width
        maxy = cy + half_width
        
        params = {
            "minx": minx,
            "miny": miny,
            "maxx": maxx,
            "maxy": maxy,
            "layers": "arb_terreno,arb_construccion,arb_unidadconstruccion",
            "limit": 1000
        }
        
        self.client.get("/visor/terrenos/snap", params=params)

    @task(3)
    def query_condicion_predio_pie(self):
        """
        Tarea: Consultar el dashboard de condición de predio (gráfico de tortas/agregaciones del visor).
        """
        self.client.get("/visor/dashboard/condicion-predio")

    @task(3)
    def query_proyecto_resumen_tortas(self):
        """
        Tarea: Consultar el resumen de proyecto para gráficos de torta (visor_tortas.py).
        """
        self.client.get("/resumenp/proyecto")

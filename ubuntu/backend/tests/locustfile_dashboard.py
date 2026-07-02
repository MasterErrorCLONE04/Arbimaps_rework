import random
import itertools
from locust import HttpUser, task, between

# Thread-safe counter to assign a unique user to each virtual user
user_counter = itertools.count(1)

class ArbimapsDashboardUser(HttpUser):
    # Simula un tiempo de espera aleatorio entre 2 y 6 segundos para refrescar o consultar
    wait_time = between(2, 6)

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

    @task(1)
    def query_resumen_estados(self):
        """
        Tarea: Consultar el resumen de estados del panel de control.
        """
        self.client.get("/panel-control/resumen-estados")

    @task(1)
    def query_coordinadores(self):
        """
        Tarea: Consultar la distribución y listado de coordinadores.
        """
        self.client.get("/panel-control/coordinadores")

import itertools
import random
from locust import HttpUser, task, between

user_counter = itertools.count(1)

# List of common names and surnames to generate search queries
SEARCH_NAMES = ["JUAN", "MARIA", "PEDRO", "GOMEZ", "RODRIGUEZ", "LOPEZ", "MARTINEZ", "SANCHEZ", "PEREZ", "RAMIREZ"]
SEARCH_DIRECTIONS = ["CALLE", "CARRERA", "AVENIDA", "DIAGONAL", "TRANSVERSAL", "LOTE", "FINCA", "PREDIO"]

class ArbimapsSearchUser(HttpUser):
    # Simulates users actively typing and searching (between 1 and 3 seconds)
    wait_time = between(1, 3)

    def on_start(self):
        """
        Login logic.
        """
        idx = next(user_counter)
        self.username = f"user_stress_{(idx - 1) % 500 + 1}"
        self.password = "Arbitrium2026*"
        self.municipality = "sucre"
        
        response = self.client.post("/login", data={
            "municipality_code": self.municipality,
            "username": self.username,
            "password": self.password
        }, allow_redirects=False)
        
        if response.status_code == 302:
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

    @task(10)
    def search_by_name(self):
        """
        Search for property by owner name.
        """
        name = random.choice(SEARCH_NAMES)
        self.client.get(f"/predio/buscar?nombre={name}")

    @task(10)
    def search_by_direction(self):
        """
        Search for property by address/direction (triggers ILIKE and jsonb searches).
        """
        direction = random.choice(SEARCH_DIRECTIONS)
        self.client.get(f"/predio/buscar?direccion={direction}")

    @task(5)
    def search_by_national_id(self):
        """
        Search by national property number (exact search).
        """
        # Generate a random 30-digit cadastral number to simulate user input
        num = f"70001000000000000{random.randint(10000, 99999)}000000000"
        self.client.get(f"/predio/buscar?numero_predial={num}")

    @task(15)
    def query_property_detail(self):
        """
        Query detailed info of a property by random ID.
        We expect 404s if IDs do not exist, which we catch as successes if HTTP code is 404 or 200,
        isolating 500/503 errors.
        """
        predio_id = random.randint(1, 1000)
        with self.client.get(f"/predio/detalle?predio_id={predio_id}", catch_response=True) as response:
            if response.status_code in (200, 404):
                response.success()
            else:
                response.failure(f"Query property detail failed with status: {response.status_code}")

    @task(5)
    def query_unit_detail(self):
        """
        Query detailed info of construction units.
        """
        unit_id = random.randint(1, 500)
        self.client.get(f"/predio/unidad_detalle?unidad_id={unit_id}")

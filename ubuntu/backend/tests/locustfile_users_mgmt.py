import itertools
import random
from locust import HttpUser, task, between

class ArbimapsUsersMgmtUser(HttpUser):
    # Simulates admin/coordinators managing users (between 2 and 5 seconds wait time)
    wait_time = between(2, 5)

    def on_start(self):
        """
        Login logic as soporte (support user has admin rights to manage users).
        """
        self.username = "soporte"
        self.password = "password"
        self.municipality = "sucre"
        self.user_ids = []
        
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
    def query_users_list(self):
        """
        Query list of users and cache their global IDs.
        """
        resp = self.client.get("/usuarios/")
        if resp.status_code == 200:
            try:
                data = resp.json()
                self.user_ids = [str(item["id_global"]) for item in data if "id_global" in item]
            except Exception:
                pass

    @task(5)
    def query_roles(self):
        """
        Query available roles.
        """
        self.client.get("/usuarios/roles")

    @task(5)
    def query_available_surveyors(self):
        """
        Query available recognized surveyors.
        """
        self.client.get("/usuarios/reconocedores-disponibles")

    @task(1)
    def update_user_status(self):
        """
        Attempt to update user details concurrently.
        """
        if not self.user_ids:
            return
            
        user_id = random.choice(self.user_ids)
        url = f"/usuarios/{user_id}"
        
        payload = {
            "activo": True,
            "first_name": "StressTest",
            "last_name": f"User {random.randint(1, 1000)}"
        }
        
        with self.client.put(url, json=payload, catch_response=True) as response:
            if response.status_code in (200, 201, 204):
                response.success()
            elif response.status_code in (400, 403, 404, 409):
                # Valid rejection due to database schema locks or logic constraints
                response.success()
            else:
                response.failure(f"User update failed with status: {response.status_code}")

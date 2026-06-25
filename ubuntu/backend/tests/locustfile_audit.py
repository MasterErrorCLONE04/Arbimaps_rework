import itertools
import random
from locust import HttpUser, task, between

class ArbimapsAuditUser(HttpUser):
    # Simulates users querying assignment logs and audit history (between 1 and 3 seconds)
    wait_time = between(1, 3)

    def on_start(self):
        """
        Login logic.
        """
        self.username = "soporte"
        self.password = "password"
        self.municipality = "sucre"
        self.assignment_ids = []
        
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

    @task(5)
    def query_assignments_list(self):
        """
        Query assignments list and cache IDs.
        """
        resp = self.client.get("/asignaciones/listado")
        if resp.status_code == 200:
            try:
                data = resp.json()
                self.assignment_ids = [str(item["id"]) for item in data if "id" in item]
            except Exception:
                pass

    @task(15)
    def query_audit_logs(self):
        """
        Query audit logs for a random assignment.
        """
        if not self.assignment_ids:
            return
            
        assignment_id = random.choice(self.assignment_ids)
        url = f"/asignaciones/{assignment_id}/eventos"
        
        with self.client.get(url, catch_response=True) as response:
            if response.status_code in (200, 404):
                response.success()
            else:
                response.failure(f"Audit log query failed with status: {response.status_code}")

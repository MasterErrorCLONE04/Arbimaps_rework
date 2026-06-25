import itertools
import random
from locust import HttpUser, task, between

user_counter = itertools.count(1)

class ArbimapsWorkflowUser(HttpUser):
    # Simulates active workflow checks by coordinators/surveyors (between 1 and 4 seconds)
    wait_time = between(1, 4)

    def on_start(self):
        """
        Login logic. Alternates between support, coordinator and field surveyor roles.
        """
        idx = next(user_counter)
        self.assignment_ids = []
        
        # Alternate credentials to stress role-based access checks
        if idx % 3 == 0:
            self.username = "soporte"
            self.password = "password"
        elif idx % 3 == 1:
            self.username = "Reconocedor7"
            self.password = "admin123"
        else:
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
    def query_assignments_list(self):
        """
        Query assignments list. Caches returned IDs to use in transition tasks.
        """
        resp = self.client.get("/asignaciones/listado")
        if resp.status_code == 200:
            try:
                data = resp.json()
                self.assignment_ids = [str(item["id"]) for item in data if "id" in item]
            except Exception:
                pass

    @task(5)
    def query_available_users(self):
        """
        Query available users for assignments.
        """
        self.client.get("/asignaciones/usuarios-disponibles")

    @task(5)
    def query_requests(self):
        """
        Query active assignment requests.
        """
        self.client.get("/asignaciones/solicitudes")

    @task(1)
    def execute_workflow_transition(self):
        """
        Attempt a workflow transition. Catches business logic validations (400/409/403/404)
        as successes to isolate database or backend server exceptions (500/503).
        """
        if not self.assignment_ids:
            return
            
        assignment_id = random.choice(self.assignment_ids)
        # We hit the endpoint representing fieldwork startup as it has simple payloads
        url = f"/api/workflow/asignaciones/{assignment_id}/start-fieldwork"
        
        with self.client.post(url, catch_response=True) as response:
            if response.status_code in (200, 201):
                response.success()
            elif response.status_code in (400, 403, 404, 409):
                # Valid workflow state validation rejection
                response.success()
            else:
                # Actual server crash, DB pool failure, or 503 Service Unavailable
                response.failure(f"Workflow transition failed with status: {response.status_code}")

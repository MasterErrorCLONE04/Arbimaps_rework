import itertools
import random
from locust import HttpUser, task, between

user_counter = itertools.count(1)

class ArbimapsSyncUser(HttpUser):
    # Simulates mobile sync sync/upload check intervals (between 2 and 6 seconds)
    wait_time = between(2, 6)

    def on_start(self):
        """
        Login logic with cookie unescaping.
        """
        idx = next(user_counter)
        # Use sequentially assigned stress test users
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

    @task(30)
    def query_sync_status(self):
        """
        Simulate constant mobile poll of sync status.
        """
        self.client.get("/api/sync-status")

    @task(1)
    def trigger_carpeteo(self):
        """
        Simulate triggering of new carpeteo process.
        Returns 200 regardless of whether another is in progress.
        """
        self.client.post("/api/create-carpeteo")

    @task(1)
    def trigger_sync_projects(self):
        """
        Simulate triggering of project synchronization.
        """
        self.client.post("/api/sync-projects")

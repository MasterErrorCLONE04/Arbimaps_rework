import random
import itertools
from locust import HttpUser, task, between

# Thread-safe counter to assign a unique user to each virtual user
user_counter = itertools.count(1)

class ArbimapsWorkflowStressUser(HttpUser):
    # Simula acciones de transiciones de estado por parte de coordinadores y supervisores
    wait_time = between(1, 4)

    def on_start(self):
        """
        Inicia sesión alternando roles o usando usuarios secuenciales de estrés.
        Recupera el listado inicial de asignaciones y de digitalizadores disponibles.
        """
        idx = next(user_counter)
        self.assignment_ids = []
        self.digitalizador_ids = []
        
        # Alternamos credenciales para tener variedad de roles con permisos de transición
        if idx % 4 == 0:
            self.username = "soporte"
            self.password = "password"
        elif idx % 4 == 1:
            self.username = "Reconocedor7"
            self.password = "admin123"
        elif idx % 4 == 2:
            self.username = "coordinador"
            self.password = "admin123"
        else:
            self.username = f"user_stress_{(idx - 1) % 500 + 1}"
            self.password = "Arbitrium2026*"
            
        self.municipality = "sucre"
        
        # Login
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
                
            # Cargar lista inicial de asignaciones
            self._update_assignments()
            
            # Cargar lista de digitalizadores disponibles
            self._update_digitalizadores()
        else:
            print(f"Error de login para {self.username} en {self.municipality}: {response.status_code}")

    def _update_assignments(self):
        resp = self.client.get("/asignaciones/listado")
        if resp.status_code == 200:
            try:
                data = resp.json()
                self.assignment_ids = [str(item["id"]) for item in data if "id" in item]
            except Exception:
                pass

    def _update_digitalizadores(self):
        resp = self.client.get("/asignaciones/usuarios-disponibles")
        if resp.status_code == 200:
            try:
                users = resp.json()
                # Filtrar usuarios que tengan el rol de digitalizador
                self.digitalizador_ids = [
                    str(u["id_global"]) for u in users 
                    if u.get("rol") and str(u["rol"]).strip().lower() == "digitalizador"
                ]
            except Exception:
                pass

    @task(5)
    def refresh_lists(self):
        """
        Tarea periódica para refrescar el listado de asignaciones y usuarios disponibles.
        """
        self._update_assignments()
        self._update_digitalizadores()

    @task(2)
    def submit_for_qa_stress(self):
        """
        Tarea: Enviar asignación a Control de Calidad 1 (submit-for-qa).
        """
        if not self.assignment_ids:
            return
        assignment_id = random.choice(self.assignment_ids)
        url = f"/api/workflow/asignaciones/{assignment_id}/submit-for-qa"
        payload = {
            "enlace_control_calidad": "http://desarrollo.arbimaps.com/qa/stress-test",
            "comentario": "Estrés submit-for-qa"
        }
        self._post_transition(url, payload)

    @task(2)
    def approve_stress(self):
        """
        Tarea: Aprobar la asignación en Control de Calidad 1 (approve).
        """
        if not self.assignment_ids:
            return
        assignment_id = random.choice(self.assignment_ids)
        url = f"/api/workflow/asignaciones/{assignment_id}/approve"
        payload = {
            "comentario": "Estrés approve"
        }
        self._post_transition(url, payload)

    @task(2)
    def assign_digitalizador_stress(self):
        """
        Tarea: Asignar un digitalizador a la asignación (assign-digitalizador).
        """
        if not self.assignment_ids:
            return
        assignment_id = random.choice(self.assignment_ids)
        url = f"/api/workflow/asignaciones/{assignment_id}/assign-digitalizador"
        
        # Elegir un digitalizador de los descubiertos dinámicamente o fallback
        if self.digitalizador_ids:
            dig_id = random.choice(self.digitalizador_ids)
        else:
            dig_id = str(random.randint(1, 100)) # fallback
            
        payload = {
            "digitalizador_id": dig_id,
            "comentario": "Estrés reasignación a digitalizador"
        }
        self._post_transition(url, payload)

    @task(2)
    def lider_approve_stress(self):
        """
        Tarea: Aprobación final por líder/coordinador (lider-approve).
        """
        if not self.assignment_ids:
            return
        assignment_id = random.choice(self.assignment_ids)
        url = f"/api/workflow/asignaciones/{assignment_id}/lider-approve"
        payload = {
            "comentario": "Estrés lider-approve"
        }
        self._post_transition(url, payload)

    def _post_transition(self, url, json_payload):
        with self.client.post(url, json=json_payload, catch_response=True) as response:
            if response.status_code in (200, 201):
                response.success()
            elif response.status_code in (400, 403, 404, 409):
                # Rechazo controlado por reglas de negocio / estado no apto
                response.success()
            else:
                # Error real de base de datos, interbloqueo (deadlock) o caída de backend
                response.failure(f"Workflow transaction failed: HTTP {response.status_code} - {response.text}")

import random
import itertools
from locust import HttpUser, task, between

# Thread-safe counter to assign a unique user to each virtual user
user_counter = itertools.count(1)

class ArbimapsPrediosEditUser(HttpUser):
    # Simula el tiempo de edición activa y guardado de fichas por parte de digitalizadores/coordinadores
    wait_time = between(2, 5)

    def on_start(self):
        """
        Inicia sesión en la plataforma y almacena las cookies de sesión autenticadas.
        Alterna cuentas para asegurar permisos de edición y rol de coordinador/digitalizador.
        """
        idx = next(user_counter)
        self.assignment_ids = []
        
        # Alternamos credenciales para tener roles autorizados a editar predios
        if idx % 3 == 0:
            self.username = "soporte"
            self.password = "password"
        elif idx % 3 == 1:
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
                
            # Cargar lista de asignaciones iniciales
            self._update_assignments()
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

    @task(3)
    def edit_random_predio(self):
        """
        Tarea:
        1. Elige una asignación aleatoria.
        2. Consulta sus detalles (/asignaciones/{id}/detalle) para encontrar predio_t_ids activos.
        3. Envía una edición PUT con payload complejo a /predios/{predio_t_id}.
        """
        if not self.assignment_ids:
            self._update_assignments()
            if not self.assignment_ids:
                return
                
        assignment_id = random.choice(self.assignment_ids)
        
        # Consultar detalle para obtener los predios asociados
        detail_resp = self.client.get(f"/asignaciones/{assignment_id}/detalle")
        if detail_resp.status_code != 200:
            return
            
        try:
            detail_data = detail_resp.json()
            predios = detail_data.get("predios", [])
            # Filtrar predios activos que posean un predio_t_id válido
            active_predios = [
                p for p in predios 
                if p.get("activo") is not False and p.get("predio_t_id") is not None
            ]
        except Exception:
            return
            
        if not active_predios:
            return
            
        selected_predio = random.choice(active_predios)
        predio_t_id = int(selected_predio["predio_t_id"])
        
        # Payload de edición simulada
        payload = {
            "predio_id": predio_t_id,
            "asignacion_id": int(assignment_id),
            "csrf_token": "csrf_stress_test_token_dummy",
            "campos_editables": {
                "tipo": {"etiqueta": "tipo", "valor": str(random.choice([1, 2]))},
                "condicion_predio": {"etiqueta": "condicion_predio", "valor": str(random.choice([1, 2, 3]))},
                "destinacion_economica": {"etiqueta": "destinacion_economica", "valor": str(random.choice([1, 2, 3, 4]))}
            },
            "campos_ocultos": {},
            "checks": {},
            "archivos": {},
            "interesados": [],
            "visita": {
                "fecha_visita": "2026-07-01",
                "comentario": "Visita de reconocimiento estrés"
            }
        }
        
        headers = {
            "X-CSRF-Token": "csrf_stress_test_token_dummy",
            "Content-Type": "application/json"
        }
        
        url = f"/predios/{predio_t_id}"
        
        with self.client.put(url, json=payload, headers=headers, catch_response=True) as response:
            if response.status_code in (200, 201):
                response.success()
            elif response.status_code in (400, 403, 404, 409):
                # Errores esperados de validación (e.g. CSRF inválido en base de datos si está habilitado)
                # o asignación no perteneciente al usuario actual si es digitalizador.
                # Lo marcamos exitoso para aislar errores 500 reales.
                response.success()
            else:
                response.failure(f"Property edit PUT failed: HTTP {response.status_code} - {response.text}")

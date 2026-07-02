import random
import itertools
from locust import HttpUser, task, between

# Thread-safe counter to assign a unique user to each virtual user
user_counter = itertools.count(1)

class ArbimapsNotificationsUser(HttpUser):
    # Simula usuarios consultando periódicamente sus notificaciones (comportamiento tipo polling)
    wait_time = between(1, 3)

    def on_start(self):
        """
        Inicia sesión en la plataforma y almacena las cookies de sesión autenticadas.
        """
        idx = next(user_counter)
        self.username = f"user_stress_{(idx - 1) % 500 + 1}"
        self.password = "Arbitrium2026*"
        self.municipality = "sucre"
        self.notification_ids = []
        
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
                
            # Cargar primera tanda de notificaciones
            self._fetch_notifications()
        else:
            print(f"Error de login para {self.username} en {self.municipality}: {response.status_code}")

    def _fetch_notifications(self):
        resp = self.client.get("/notificaciones/mis-notificaciones?limit=50&archivado=false")
        if resp.status_code == 200:
            try:
                data = resp.json()
                self.notification_ids = [int(item["id"]) for item in data if "id" in item]
            except Exception:
                pass

    @task(15)
    def query_notifications(self):
        """
        Tarea: Consultar la bandeja de notificaciones del usuario (frecuente).
        """
        self._fetch_notifications()

    @task(3)
    def query_unread_count(self):
        """
        Tarea: Consultar el conteo rápido de no leídas para el indicador en la barra superior.
        """
        self.client.get("/notificaciones/no-leidas")

    @task(2)
    def read_all_notifications(self):
        """
        Tarea: Marcar todas las notificaciones como leídas concurrentemente.
        """
        self.client.post("/notificaciones/leer-todas")

    @task(4)
    def archive_single_notification(self):
        """
        Tarea: Archivar una notificación específica de las cargadas en memoria.
        """
        if not self.notification_ids:
            return
            
        notif_id = random.choice(self.notification_ids)
        url = f"/notificaciones/{notif_id}/archivar"
        
        with self.client.post(url, catch_response=True) as response:
            if response.status_code in (200, 201):
                # Eliminar de la lista local tras archivar exitosamente
                if notif_id in self.notification_ids:
                    self.notification_ids.remove(notif_id)
                response.success()
            elif response.status_code in (400, 404):
                # Notificación ya archivada o no encontrada
                response.success()
            else:
                response.failure(f"Archiving notification failed: HTTP {response.status_code}")

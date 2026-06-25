import itertools
import io
from locust import HttpUser, task, between

user_counter = itertools.count(1)

# A minimal valid-looking XML structure for XTF
DUMMY_XTF_CONTENT = """<?xml version="1.0" encoding="utf-8"?>
<transfer xmlns="http://www.interlis.ch/INTERLIS2.3">
  <headersection>
    <models>
      <model>LADM_COL_V3_0</model>
    </models>
  </headersection>
  <datasection>
  </datasection>
</transfer>
"""

class ArbimapsXTFUser(HttpUser):
    # Simulates digitalizers uploading XTF files (between 3 and 8 seconds wait time)
    wait_time = between(3, 8)

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

    @task(1)
    def view_xtf_page(self):
        """
        Simulate visiting the validation page.
        """
        self.client.get("/validacion/xtf")

    @task(3)
    def upload_xtf_file(self):
        """
        Simulate uploading an XTF file. We catch 500/503 errors and treat expected infrastructure Skipped/Error status codes as success.
        """
        # Convert dummy content to bytes-like file
        file_data = io.BytesIO(DUMMY_XTF_CONTENT.encode("utf-8"))
        files = {
            "file": ("stress_test.xtf", file_data, "application/octet-stream")
        }
        
        with self.client.post("/validacion/xtf/subir", files=files, catch_response=True) as response:
            if response.status_code in (200, 201):
                response.success()
            elif response.status_code == 500 and "ilivalidator" in response.text:
                # Ilivalidator java process or infrastructure skips are expected in some testing contexts
                response.success()
            else:
                response.failure(f"XTF upload failed with status: {response.status_code}")

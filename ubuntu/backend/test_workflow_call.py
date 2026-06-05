import requests
import psycopg2
from core.db.connection import get_db_params

def main():
    session = requests.Session()

    # 1. Log in
    login_url = "http://localhost:8000/login"
    payload = {
        "municipality_code": "sucre",
        "username": "juanita_rodriguez",
        "password": "Arbi123*"
    }
    print("Logging in...")
    res = session.post(login_url, data=payload)
    print("Login status code:", res.status_code)
    if res.status_code != 200:
        print("Login failed! Response:")
        print(res.text[:500])
        exit(1)

    # 2. Check assignment state before transition
    params = get_db_params()
    params['dbname'] = 'programacion' # sucre DB
    conn = psycopg2.connect(**params)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, estado, enlace_control_calidad FROM arbimaps_app.asignacion WHERE id = 144;")
            print("Before transition:", cur.fetchone())
    finally:
        conn.close()

    # 3. Call workflow endpoint
    workflow_url = "http://localhost:8000/api/workflow/asignaciones/144/submit-for-qa"
    json_data = {
        "enlace_control_calidad": "https://example.com/check-qa-link"
    }
    print("Executing workflow transition submit-for-qa...")
    res_wf = session.post(workflow_url, json=json_data)
    print("Workflow transition status code:", res_wf.status_code)
    print("Workflow transition response:", res_wf.json())

    # 4. Check assignment state after transition
    conn = psycopg2.connect(**params)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, estado, enlace_control_calidad FROM arbimaps_app.asignacion WHERE id = 144;")
            print("After transition in asignacion:", cur.fetchone())
            
            cur.execute("SELECT * FROM d_workflow.assignments WHERE assignment_id = '144';")
            print("After transition in d_workflow.assignments:", cur.fetchone())
            
            cur.execute("SELECT id_usuario_destino, titulo, mensaje, prioridad FROM arbimaps_app.notificaciones WHERE id_asignacion = 144 ORDER BY id DESC LIMIT 1;")
            print("Latest notification for assignment 144:", cur.fetchone())
    finally:
        conn.close()

if __name__ == "__main__":
    main()


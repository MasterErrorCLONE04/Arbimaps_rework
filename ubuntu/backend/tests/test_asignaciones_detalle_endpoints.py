from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.asignaciones_detalle import router
from routers.auth import get_current_user, get_current_tenant
from tenants.dependencies import get_tenant_db_connection
from tenants.models import MunicipalityDbConfig, MunicipalitySchemas
from tenants.context import TenantContext
import routers.asignaciones_detalle as asignaciones_detalle

app = FastAPI()
app.include_router(router)

def mock_get_tenant_context():
    return TenantContext(
        municipality_code="sucre",
        municipality_name="Sucre",
        db=MunicipalityDbConfig(
            host="db.example", port=5432, db_name="sucre", user="u", password="p"
        ),
        schemas=MunicipalitySchemas(app="arbimaps_app")
    )

def mock_get_current_user():
    return {"id_global": "user-123", "username": "juan_ramon", "role_code": "reconocedor"}

@pytest.fixture
def mock_db_connection(monkeypatch):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    # Store executed query to match fetchone results
    last_query = []

    def execute_mock(sql, params=None):
        last_query.append(sql)

    cur.execute = execute_mock

    def fetchone_mock():
        if not last_query:
            return None
        sql = last_query[-1]
        
        # Match Query 0 (_ensure_assignment_access) and Query 1 (main select)
        if "usuario_asignado," in sql or "a.creado_por," in sql:
            return {
                "id": 145,
                "estado": "DEVUELTO_CAMPO",
                "creado_en": None,
                "creado_por": "coord_asignado",
                "usuario_asignado": "juan_ramon",
                "enlace_control_calidad": "https://example.com/evidence",
                "titulo": "Asignacion de Prueba",
                "observaciones": "",
                "datasetname_main": "main_ds",
                "work_datasetname": "work_ds",
                "error_msg": None,
                "predios_soporte_extra": 0,
                "coord_username": "coord_asignado",
                "asignado_first_name": "Juan",
                "asignado_last_name": "Ramon",
            }
        
        # Match Query 2 (stats count)
        if "COUNT(*)" in sql:
            return {
                "total_activos": 1,
                "total_inactivos": 0,
                "total_nuevos_raw": 0,
            }

        # Match Query 3 (retorno)
        if "retorno" in sql:
            return {
                "synced_predios": 0,
                "expected_predios": 0,
                "covered_predios": 0,
            }

        # Match Query 4 (event_log)
        if "event_log" in sql:
            return None

        return None

    cur.fetchone = fetchone_mock

    def fetchall_mock():
        if not last_query:
            return []
        sql = last_query[-1]
        if "asignacion_comentario" in sql:
            return [
                {
                    "id": 1,
                    "asignacion_id": 145,
                    "usuario_id": 200,
                    "usuario": "juan_ramon",
                    "rol": "reconocedor",
                    "comentario": "Este es un comentario de prueba",
                    "estado_origen": "EN_CAMPO",
                    "estado_destino": "CONTROL_CALIDAD_1",
                    "creado_en": None
                }
            ]
        return []

    cur.fetchall = fetchall_mock

    monkeypatch.setattr(
        asignaciones_detalle.asignaciones_repo,
        "list_predios_asignacion",
        lambda conn, tenant, asignacion_id: [
            {
                "id": 1001,
                "numero_predial_nacional": "123456789012345678901234567890",
                "predio_t_id": 99,
                "activo": True,
                "creado_por": "juan_ramon",
                "creado_en": None,
            }
        ]
    )

    monkeypatch.setattr(
        asignaciones_detalle.asignaciones_repo,
        "ensure_asignacion_tables",
        lambda conn, tenant: None
    )

    app.dependency_overrides[get_current_tenant] = mock_get_tenant_context
    app.dependency_overrides[get_current_user] = mock_get_current_user
    app.dependency_overrides[get_tenant_db_connection] = lambda: conn
    return conn

def test_obtener_detalle_asignacion_includes_username(mock_db_connection):
    client = TestClient(app)
    response = client.get("/asignaciones/145/detalle")

    assert response.status_code == 200
    res_json = response.json()
    assert res_json["id"] == 145
    assert res_json["estado"] == "DEVUELTO_CAMPO"
    assert res_json["coordinador"] == "coord_asignado"
    assert res_json["usuario_asignado_username"] == "juan_ramon"
    assert res_json["enlace_control_calidad"] == "https://example.com/evidence"
    assert res_json["usuario_asignado"] == "Juan Ramon (juan_ramon)"

def test_obtener_detalle_asignacion_includes_comentarios(mock_db_connection):
    client = TestClient(app)
    response = client.get("/asignaciones/145/detalle")

    assert response.status_code == 200
    res_json = response.json()
    assert "comentarios" in res_json
    assert len(res_json["comentarios"]) == 1
    comment = res_json["comentarios"][0]
    assert comment["id"] == 1
    assert comment["comentario"] == "Este es un comentario de prueba"
    assert comment["rol"] == "reconocedor"
    assert comment["estado_origen"] == "EN_CAMPO"
    assert comment["estado_destino"] == "CONTROL_CALIDAD_1"


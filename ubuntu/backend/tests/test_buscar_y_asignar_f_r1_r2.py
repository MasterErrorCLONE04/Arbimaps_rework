import pytest
from unittest.mock import MagicMock
from repositories.asignaciones_repo import buscar_predios_estado, fetch_predios_metadata
from services.asignaciones_workspace import _importar_predios_f_r1_r2_si_faltan
from tenants import TenantContext
from tenants.models import MunicipalityDbConfig, MunicipalitySchemas

def make_tenant() -> TenantContext:
    return TenantContext(
        municipality_code="neiva",
        municipality_name="Neiva",
        db=MunicipalityDbConfig("localhost", 5432, "neiva", "postgres", "admin", sslmode="prefer"),
        schemas=MunicipalitySchemas(main="a_base_principal", work="b_asignaciones_arb"),
    )

def test_buscar_predios_estado_f_r1_r2_fallback():
    tenant = make_tenant()
    
    # Mock database cursor to return empty for a_base_principal, but return a row for f_r1_r2
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = [
        [],  # Primero para a_base_principal: vacío
        [{"numero_predial_nacional": "410010001000000010017000000000", "asignado_a": None, "asignado_por": None, "source_schema": "f_r1_r2"}]  # Segundo para f_r1_r2
    ]
    
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    rows = buscar_predios_estado(mock_conn, tenant.schemas.main, ["410010001000000010017000000000"])
    
    assert len(rows) == 1
    assert rows[0]["numero_predial_nacional"] == "410010001000000010017000000000"
    assert rows[0]["source_schema"] == "f_r1_r2"

def test_fetch_predios_metadata_f_r1_r2_fallback():
    tenant = make_tenant()
    
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = [
        [],  # Vacío en a_base_principal
        [{
            "numero_predial_nacional": "410010001000000010017000000000",
            "predio_t_id": None,
            "t_basket": None,
            "basket_id": None,
            "basket_tid": None,
            "topicname": "LADM_COL_V3_1",
            "basketname": None,
            "dataset_id": None,
            "datasetname_main": "f_r1_r2",
            "source_schema": "f_r1_r2"
        }]  # Fila en f_r1_r2
    ]
    
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    metadata = fetch_predios_metadata(mock_conn, tenant.schemas.main, ["410010001000000010017000000000"])
    
    assert len(metadata) == 1
    assert metadata[0]["numero_predial_nacional"] == "410010001000000010017000000000"
    assert metadata[0]["source_schema"] == "f_r1_r2"
    assert metadata[0]["datasetname_main"] == "f_r1_r2"

def test_importar_predios_f_r1_r2_si_faltan_skips_when_exists(monkeypatch):
    tenant = make_tenant()
    
    # Mocking check query to return 1 (meaning it already exists in workspace)
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = [
        (10,),  # Basket ID
        (1,),   # exists = True
    ]
    mock_cursor.fetchall.return_value = [("410010001000000010017000000000",)]
    
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    import_called = []
    def mock_import(conn, tenant, npn, schema_work, t_basket_id):
        import_called.append(npn)
        return True
        
    monkeypatch.setattr("services.asignaciones_workspace.importar_predio_f_r1_r2_a_workspace", mock_import)
    
    _importar_predios_f_r1_r2_si_faltan(mock_conn, tenant, 1, "b_asignaciones_arb", "asig_test")
    
    assert len(import_called) == 0  # No debe llamarse porque exists es True

def test_importar_predios_f_r1_r2_si_faltan_calls_import_when_missing(monkeypatch):
    tenant = make_tenant()
    
    # Mocking check query to return None (meaning it is missing from workspace)
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = [
        (10,),  # Basket ID
        None,   # exists = False
    ]
    mock_cursor.fetchall.return_value = [("410010001000000010017000000000",)]
    
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    import_called = []
    def mock_import(conn, tenant, npn, schema_work, t_basket_id):
        import_called.append(npn)
        return True
        
    monkeypatch.setattr("services.asignaciones_workspace.importar_predio_f_r1_r2_a_workspace", mock_import)
    
    _importar_predios_f_r1_r2_si_faltan(mock_conn, tenant, 1, "b_asignaciones_arb", "asig_test")
    
    assert len(import_called) == 1
    assert import_called[0] == "410010001000000010017000000000"

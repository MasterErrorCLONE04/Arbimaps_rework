import pytest
from unittest.mock import MagicMock

from tenants.models import MunicipalitySchemas
from services.asignaciones_workspace import (
    _ensure_work_history_schema_exists,
    _clonar_dataset_a_historial,
    remove_workspace_dataset
)

def test_municipality_schemas_has_work_history():
    schemas = MunicipalitySchemas()
    assert hasattr(schemas, "work_history")
    assert schemas.work_history == "b_asignaciones_his"

def test_ensure_work_history_schema_exists_calls_create_schema():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = None
    mock_cur.fetchall.return_value = [("arb_predio",)]

    _ensure_work_history_schema_exists(mock_conn, "b_asignaciones_arb", "b_asignaciones_his")

    mock_cur.execute.assert_any_call("CREATE SCHEMA IF NOT EXISTS b_asignaciones_his;")
    mock_cur.execute.assert_any_call("CREATE TABLE IF NOT EXISTS b_asignaciones_his.arb_predio (LIKE b_asignaciones_arb.arb_predio INCLUDING ALL);")

def test_clonar_dataset_a_historial_copies_all_baskets_and_tables():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = [1]
    mock_cur.fetchall.return_value = [("arb_predio",), ("arb_terreno",)]

    mock_tenant = MagicMock()
    mock_tenant.schemas.work = "b_asignaciones_arb"
    mock_tenant.schemas.work_history = "b_asignaciones_his"

    _clonar_dataset_a_historial(mock_conn, mock_tenant, "asig_test", "b_asignaciones_arb", "b_asignaciones_his")

    assert mock_cur.execute.call_count >= 4

def test_remove_workspace_dataset_history_safeguard_raises_error():
    mock_conn = MagicMock()
    mock_tenant = MagicMock()
    mock_tenant.schemas.work_history = "b_asignaciones_his"

    with pytest.raises(ValueError, match="El esquema histórico b_asignaciones_his es inmutable"):
        remove_workspace_dataset(mock_conn, mock_tenant, "asig_test", "b_asignaciones_his")

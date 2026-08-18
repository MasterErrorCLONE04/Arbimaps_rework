import pytest
from unittest.mock import MagicMock, patch
from services.asignaciones_workspace import workspace_service
from services.asignaciones_workspace_sql import run_insertar_predios_for_asignacion


def test_ensure_workspace_ready_for_export_integration():
    mock_db = MagicMock()
    mock_asignacion = MagicMock()
    mock_asignacion.id = 1
    mock_asignacion.tenant_id = "tenant_test"
    mock_asignacion.schema_work = "work_tenant_test_1"

    mock_db.query().filter().first.return_value = mock_asignacion

    with patch.object(workspace_service, 'get_or_create_basket_id', return_value=100), \
         patch.object(workspace_service, '_get_npns_for_asignacion', return_value=["npn_1", "npn_2"]), \
         patch('services.asignaciones_workspace_sql.run_insertar_predios_for_asignacion') as mock_run_sql:

        mock_run_sql.return_value = {"inserted": 2, "errors": []}

        result = workspace_service.ensure_workspace_ready_for_export(mock_db, 1, "work_tenant_test_1")

        assert result == {"inserted": 2, "errors": []}
        mock_run_sql.assert_called_once_with(
            tenant="tenant_test",
            npns=["npn_1", "npn_2"],
            resolved_schema_work="work_tenant_test_1",
            t_basket_id=100
        )


def test_run_insertar_predios_for_asignacion_empty():
    res = run_insertar_predios_for_asignacion("tenant", [], "work_schema", 1)
    assert res == {"inserted": 0, "errors": []}


@patch("services.asignaciones_workspace_sql.db_conn")
@patch("services.asignaciones_workspace_sql.importar_predios_f_r1_r2_a_workspace")
def test_run_insertar_predios_for_asignacion_bulk_success(mock_bulk, mock_get_conn):
    mock_conn = MagicMock()
    mock_get_conn.return_value.__enter__.return_value = mock_conn
    mock_bulk.return_value = 2

    res = run_insertar_predios_for_asignacion("tenant", ["npn1", "npn2"], "work_schema", 1)

    assert res["inserted"] == 2
    assert res["errors"] == []
    mock_bulk.assert_called_once()


@patch("services.asignaciones_workspace_sql.db_conn")
@patch("services.asignaciones_workspace_sql.importar_predios_f_r1_r2_a_workspace")
@patch("services.asignaciones_workspace_sql.importar_predio_f_r1_r2_a_workspace")
def test_run_insertar_predios_for_asignacion_partial_error(mock_import, mock_bulk, mock_get_conn):
    mock_conn = MagicMock()
    mock_get_conn.return_value.__enter__.return_value = mock_conn

    # Simular que bulk falla para que entre en fallback predio por predio
    mock_bulk.side_effect = Exception("Error en bulk insert")

    # Simular que npn1 funciona e npn2 lanza excepcion
    mock_import.side_effect = [None, Exception("Error en predio 2")]

    res = run_insertar_predios_for_asignacion("tenant", ["npn1", "npn2"], "work_schema", 1)

    assert res["inserted"] == 1
    assert len(res["errors"]) == 1
    assert res["errors"][0]["npn"] == "npn2"

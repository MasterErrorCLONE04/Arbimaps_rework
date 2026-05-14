from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.asignaciones_workflow import get_command_service, router
from routers.auth import get_current_user_from_session
from tenants.context import TenantContext
from tenants.dependencies import get_tenant_context_from_session
from tenants.models import MunicipalityDbConfig, MunicipalitySchemas
from workflow.enums import WorkflowRole, WorkflowState
from workflow.exceptions import InvalidTransitionError

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
    return {"id_global": "user-123", "username": "admin1", "role_code": "administrador"}


app.dependency_overrides[get_tenant_context_from_session] = mock_get_tenant_context
app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


@pytest.fixture
def mock_command_service():
    service = MagicMock()
    app.dependency_overrides[get_command_service] = lambda: service
    return service


def test_assign_assignment_success(mock_command_service):
    result = MagicMock()
    result.transition.assignment.assignment_id = "ASG-001"
    result.transition.assignment.workflow_state = WorkflowState.EN_CAMPO
    result.transition.assignment.assigned_user_id = "rec-01"
    result.transition.assignment.version = 2
    mock_command_service.execute_transition.return_value = result

    client = TestClient(app)
    response = client.post("/api/workflow/asignaciones/ASG-001/assign", json={"target_user_id": "rec-01"})

    assert response.status_code == 200
    assert response.json() == {
        "assignment_id": "ASG-001",
        "workflow_state": "EN_CAMPO",
        "assigned_user_id": "rec-01",
        "version": 2
    }

    call_kwargs = mock_command_service.execute_transition.call_args.kwargs
    assert call_kwargs["assignment_id"] == "ASG-001"
    assert call_kwargs["actor"].user_id == "user-123"
    assert call_kwargs["actor"].role == WorkflowRole.ADMINISTRADOR
    assert call_kwargs["metadata"] == {"target_user_id": "rec-01"}


def test_assign_assignment_not_found(mock_command_service):
    mock_command_service.execute_transition.side_effect = ValueError("Asignacion no encontrada")

    client = TestClient(app)
    response = client.post("/api/workflow/asignaciones/ASG-MISSING/assign", json={"target_user_id": "rec-01"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Asignacion no encontrada"}


def test_assign_assignment_invalid_transition(mock_command_service):
    mock_command_service.execute_transition.side_effect = InvalidTransitionError("No se puede ejecutar ASSIGN desde EN_CAMPO")

    client = TestClient(app)
    response = client.post("/api/workflow/asignaciones/ASG-001/assign", json={"target_user_id": "rec-01"})

    assert response.status_code == 400
    assert "No se puede ejecutar" in response.json()["detail"]


def test_assign_assignment_optimistic_locking_error(mock_command_service):
    mock_command_service.execute_transition.side_effect = RuntimeError("Optimistic locking failed")

    client = TestClient(app)
    response = client.post("/api/workflow/asignaciones/ASG-001/assign", json={"target_user_id": "rec-01"})

    assert response.status_code == 409
    assert response.json() == {"detail": "Optimistic locking failed"}
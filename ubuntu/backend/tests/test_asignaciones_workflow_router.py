from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.asignaciones_workflow import get_command_service, router
from routers.auth import get_current_user_from_session
from tenants.context import TenantContext
from tenants.dependencies import get_tenant_context_from_session, get_tenant_db_connection
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


def mock_get_tenant_db_connection():
    return MagicMock()


app.dependency_overrides[get_tenant_context_from_session] = mock_get_tenant_context
app.dependency_overrides[get_current_user_from_session] = mock_get_current_user
app.dependency_overrides[get_tenant_db_connection] = mock_get_tenant_db_connection

from routers.asignaciones_workflow import verify_assignment_isolation
app.dependency_overrides[verify_assignment_isolation] = lambda: None


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


def test_return_to_field_success(mock_command_service):
    result = MagicMock()
    result.transition.assignment.assignment_id = "1"
    result.transition.assignment.workflow_state = WorkflowState.DEVUELTO
    result.transition.assignment.assigned_user_id = "rec-01"
    result.transition.assignment.version = 3
    mock_command_service.execute_transition.return_value = result

    client = TestClient(app)
    response = client.post("/api/workflow/asignaciones/1/return-to-field")

    assert response.status_code == 200
    assert response.json() == {
        "assignment_id": "1",
        "workflow_state": "DEVUELTO",
        "assigned_user_id": "rec-01",
        "version": 3
    }


def test_approve_success(mock_command_service):
    result = MagicMock()
    result.transition.assignment.assignment_id = "1"
    result.transition.assignment.workflow_state = WorkflowState.APROBACION
    result.transition.assignment.assigned_user_id = "rec-01"
    result.transition.assignment.version = 3
    mock_command_service.execute_transition.return_value = result

    client = TestClient(app)
    response = client.post("/api/workflow/asignaciones/1/approve")

    assert response.status_code == 200
    assert response.json() == {
        "assignment_id": "1",
        "workflow_state": "APROBACION",
        "assigned_user_id": "rec-01",
        "version": 3
    }


def test_approve_notifies_support_creator(mock_command_service, monkeypatch):
    result = MagicMock()
    result.transition.assignment.assignment_id = "1"
    result.transition.assignment.workflow_state = WorkflowState.APROBACION
    result.transition.assignment.assigned_user_id = "rec-01"
    result.transition.assignment.version = 3
    mock_command_service.execute_transition.return_value = result

    # Mock DB cursor/queries
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Setup side effects for cur.fetchone
    # 1st fetchone: asig_row = creador_por_id: 999
    # 2nd fetchone: creator_row = rol: "soporte"
    mock_cur.fetchone.side_effect = [
        {
            "enlace_control_calidad": "https://example.com/evidence",
            "titulo": "My Job",
            "creado_por_id": 999
        },
        {
            "rol": "soporte"
        }
    ]
    mock_cur.fetchall.return_value = [] # no consolidadores

    app.dependency_overrides[get_tenant_db_connection] = lambda: mock_conn
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "123", "username": "admin1", "role_code": "administrador"}

    # Spy on safe_crear_notificacion
    notifications_sent = []
    def spy_safe_crear_notificacion(conn, tenant, id_asignacion, id_usuario_destino, id_usuario_origen, rol_origen, rol_destino, tipo, titulo, mensaje, url_destino, prioridad, metadata):
        notifications_sent.append({
            "id_asignacion": id_asignacion,
            "id_usuario_destino": id_usuario_destino,
            "rol_destino": rol_destino,
            "tipo": tipo,
            "titulo": titulo,
        })

    import routers.asignaciones_workflow as workflow_router
    monkeypatch.setattr(workflow_router.asignaciones_repo, "safe_crear_notificacion", spy_safe_crear_notificacion)
    monkeypatch.setattr(workflow_router.asignaciones_repo, "update_asignacion_fields", lambda *a, **k: None)

    try:
        client = TestClient(app)
        response = client.post("/api/workflow/asignaciones/1/approve")

        assert response.status_code == 200
        assert len(notifications_sent) == 1
        assert notifications_sent[0]["id_usuario_destino"] == 999
        assert notifications_sent[0]["rol_destino"] == "soporte"
        assert notifications_sent[0]["tipo"] == "soporte"
    finally:
        # Restore original dependency overrides
        app.dependency_overrides[get_tenant_db_connection] = mock_get_tenant_db_connection
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_submit_soporte_link_success(monkeypatch):
    # Mock connection, cursor, and query results
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Setup database fetch results for cursor:
    # 1. select query fetches details of the assignment
    # 2. select query fetches user role for notification target (coordinador)
    mock_cur.fetchone.side_effect = [
        {
            "coordinador_asignado_id": 100,
            "creado_por_id": 200,
            "creado_por": "creator_username",
            "estado": "GENERACION_XTF_CAMPO",
            "titulo": "Asignacion Test",
            "enlace_soporte": None
        },
        {
            "rol": "coordinador"
        }
    ]

    # Override dependencies
    app.dependency_overrides[get_tenant_db_connection] = lambda: mock_conn
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "200", "username": "soporte1", "role_code": "soporte"}

    notifications_sent = []
    def spy_safe_crear_notificacion(conn, tenant, id_asignacion, id_usuario_destino, id_usuario_origen, rol_origen, rol_destino, tipo, titulo, mensaje, url_destino, prioridad, metadata):
        notifications_sent.append({
            "id_asignacion": id_asignacion,
            "id_usuario_destino": id_usuario_destino,
            "id_usuario_origen": id_usuario_origen,
            "rol_origen": rol_origen,
            "rol_destino": rol_destino,
            "tipo": tipo,
            "titulo": titulo,
            "mensaje": mensaje,
            "url_destino": url_destino,
            "prioridad": prioridad,
            "metadata": metadata
        })

    import routers.asignaciones_workflow as workflow_router
    monkeypatch.setattr(workflow_router.asignaciones_repo, "safe_crear_notificacion", spy_safe_crear_notificacion)

    try:
        client = TestClient(app)
        response = client.post(
            "/api/workflow/asignaciones/123/submit-soporte-link",
            json={"enlace_soporte": "https://example.com/soporte-report"}
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "enlace_soporte": "https://example.com/soporte-report"
        }

        # Check DB update
        mock_cur.execute.assert_any_call(
            "UPDATE arbimaps_app.asignacion SET enlace_soporte = %s, enlace_devolucion = NULL WHERE id = %s",
            ("https://example.com/soporte-report", 123)
        )

        # Check notifications
        assert len(notifications_sent) == 1
        n = notifications_sent[0]
        assert n["id_asignacion"] == 123
        assert n["id_usuario_destino"] == 100
        assert n["id_usuario_origen"] == 200
        assert n["rol_origen"] == "soporte"
        assert n["rol_destino"] == "coordinador"
        assert n["titulo"] == "Enlace de soporte disponible"
        assert n["metadata"] == {
            "assignment_id": 123,
            "enlace_soporte": "https://example.com/soporte-report"
        }

    finally:
        # Restore original dependencies
        app.dependency_overrides[get_tenant_db_connection] = mock_get_tenant_db_connection
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_submit_soporte_link_forbidden():
    # Override user to reconocedor
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "123", "username": "reconocedor1", "role_code": "reconocedor"}
    try:
        client = TestClient(app)
        response = client.post(
            "/api/workflow/asignaciones/123/submit-soporte-link",
            json={"enlace_soporte": "https://example.com/soporte-report"}
        )
        assert response.status_code == 403
        assert "Solo usuarios con rol de soporte o admin" in response.json()["detail"]
    finally:
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_submit_soporte_link_invalid_state():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = {
        "coordinador_asignado_id": 100,
        "creado_por_id": 200,
        "creado_por": "creator_username",
        "estado": "CONTROL_CALIDAD_1",
        "titulo": "Asignacion Test",
        "enlace_soporte": None
    }
    app.dependency_overrides[get_tenant_db_connection] = lambda: mock_conn
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "200", "username": "soporte1", "role_code": "soporte"}
    try:
        client = TestClient(app)
        response = client.post(
            "/api/workflow/asignaciones/123/submit-soporte-link",
            json={"enlace_soporte": "https://example.com/soporte-report"}
        )
        assert response.status_code == 400
        assert "debe estar en estado GENERACION_XTF_CAMPO" in response.json()["detail"]
    finally:
        app.dependency_overrides[get_tenant_db_connection] = mock_get_tenant_db_connection
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_submit_soporte_link_already_exists():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = {
        "coordinador_asignado_id": 100,
        "creado_por_id": 200,
        "creado_por": "creator_username",
        "estado": "GENERACION_XTF_CAMPO",
        "titulo": "Asignacion Test",
        "enlace_soporte": "https://already-sent.com"
    }
    app.dependency_overrides[get_tenant_db_connection] = lambda: mock_conn
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "200", "username": "soporte1", "role_code": "soporte"}
    try:
        client = TestClient(app)
        response = client.post(
            "/api/workflow/asignaciones/123/submit-soporte-link",
            json={"enlace_soporte": "https://example.com/soporte-report"}
        )
        assert response.status_code == 400
        assert "ya ha sido enviado" in response.json()["detail"]
    finally:
        app.dependency_overrides[get_tenant_db_connection] = mock_get_tenant_db_connection
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_return_to_support_success(monkeypatch):
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.side_effect = [
        {
            "creado_por_id": 200,
            "creado_por": "creator_username",
            "estado": "GENERACION_XTF_CAMPO",
            "titulo": "Asignacion Test"
        },
        {
            "rol": "soporte"
        }
    ]

    app.dependency_overrides[get_tenant_db_connection] = lambda: mock_conn
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "100", "username": "coord1", "role_code": "coordinador"}

    notifications_sent = []
    def spy_safe_crear_notificacion(conn, tenant, id_asignacion, id_usuario_destino, id_usuario_origen, rol_origen, rol_destino, tipo, titulo, mensaje, url_destino, prioridad, metadata):
        notifications_sent.append({"id_usuario_destino": id_usuario_destino, "rol_destino": rol_destino})

    import routers.asignaciones_workflow as workflow_router
    monkeypatch.setattr(workflow_router.asignaciones_repo, "safe_crear_notificacion", spy_safe_crear_notificacion)

    try:
        client = TestClient(app)
        response = client.post("/api/workflow/asignaciones/123/return-to-support")
        assert response.status_code == 200
        mock_cur.execute.assert_any_call(
            "UPDATE arbimaps_app.asignacion SET enlace_soporte = NULL, enlace_devolucion = %s WHERE id = %s",
            (None, 123)
        )
        assert len(notifications_sent) == 1
        assert notifications_sent[0]["id_usuario_destino"] == 200
        assert notifications_sent[0]["rol_destino"] == "soporte"
    finally:
        app.dependency_overrides[get_tenant_db_connection] = mock_get_tenant_db_connection
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_assign_digitalizador_success(mock_command_service, monkeypatch):
    result = MagicMock()
    result.transition.assignment.assignment_id = "123"
    result.transition.assignment.workflow_state = WorkflowState.EN_CAMPO
    result.transition.assignment.assigned_user_id = "500"
    result.transition.assignment.version = 4
    mock_command_service.execute_transition.return_value = result

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.side_effect = [
        {
            "username": "digi1",
            "first_name": "Digi",
            "last_name": "One",
            "rol": "digitalizador"
        },
        {
            "titulo": "Asignacion Test",
            "usuario_asignado": "reco1",
            "usuario_asignado_id": 200
        }
    ]

    app.dependency_overrides[get_tenant_db_connection] = lambda: mock_conn
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "100", "username": "coord1", "role_code": "coordinador"}

    notifications_sent = []
    def spy_safe_crear_notificacion(conn, tenant, id_asignacion, id_usuario_destino, id_usuario_origen, rol_origen, rol_destino, tipo, titulo, mensaje, url_destino, prioridad, metadata):
        notifications_sent.append({"id_usuario_destino": id_usuario_destino, "rol_destino": rol_destino})

    import routers.asignaciones_workflow as workflow_router
    monkeypatch.setattr(workflow_router.asignaciones_repo, "safe_crear_notificacion", spy_safe_crear_notificacion)
    monkeypatch.setattr(workflow_router.asignaciones_repo, "update_asignacion_fields", lambda *a, **k: None)

    try:
        client = TestClient(app)
        response = client.post(
            "/api/workflow/asignaciones/123/assign-digitalizador",
            json={"digitalizador_id": "500"}
        )
        assert response.status_code == 200
        assert response.json()["assigned_user_id"] == "500"
        
        # Find the update call in mock_cur.execute.call_args_list
        update_calls = [
            args for args, kwargs in mock_cur.execute.call_args_list
            if args and "UPDATE" in args[0] and "usuario_reconocedor" in args[0]
        ]
        assert len(update_calls) == 1
        assert update_calls[0][1] == ("digi1", 500, "reco1", 200, 123)
        assert len(notifications_sent) == 1
        assert notifications_sent[0]["id_usuario_destino"] == 500
        assert notifications_sent[0]["rol_destino"] == "digitalizador"
    finally:
        app.dependency_overrides[get_tenant_db_connection] = mock_get_tenant_db_connection
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_continue_with_reconocedor_success(mock_command_service, monkeypatch):
    result = MagicMock()
    result.transition.assignment.assignment_id = "123"
    result.transition.assignment.workflow_state = WorkflowState.EN_CAMPO
    result.transition.assignment.assigned_user_id = "300"
    result.transition.assignment.version = 4
    mock_command_service.execute_transition.return_value = result

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.side_effect = [
        {
            "usuario_asignado_id": 300,
            "usuario_asignado": "rec1",
            "titulo": "Asignacion Test"
        }
    ]

    app.dependency_overrides[get_tenant_db_connection] = lambda: mock_conn
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "100", "username": "coord1", "role_code": "coordinador"}

    notifications_sent = []
    def spy_safe_crear_notificacion(conn, tenant, id_asignacion, id_usuario_destino, id_usuario_origen, rol_origen, rol_destino, tipo, titulo, mensaje, url_destino, prioridad, metadata):
        notifications_sent.append({"id_usuario_destino": id_usuario_destino, "rol_destino": rol_destino})

    import routers.asignaciones_workflow as workflow_router
    monkeypatch.setattr(workflow_router.asignaciones_repo, "safe_crear_notificacion", spy_safe_crear_notificacion)
    monkeypatch.setattr(workflow_router.asignaciones_repo, "update_asignacion_fields", lambda *a, **k: None)

    try:
        client = TestClient(app)
        response = client.post("/api/workflow/asignaciones/123/continue-with-reconocedor")
        assert response.status_code == 200
        assert response.json()["assigned_user_id"] == "300"
        assert len(notifications_sent) == 1
        assert notifications_sent[0]["id_usuario_destino"] == 300
        assert notifications_sent[0]["rol_destino"] == "reconocedor"
    finally:
        app.dependency_overrides[get_tenant_db_connection] = mock_get_tenant_db_connection
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_submit_for_qa2_success(mock_command_service, monkeypatch):
    result = MagicMock()
    result.transition.assignment.assignment_id = "123"
    result.transition.assignment.workflow_state = WorkflowState.CONTROL_CALIDAD_1
    result.transition.assignment.assigned_user_id = "500"
    mock_command_service.execute_transition.return_value = result

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.side_effect = [
        {
            "usuario_asignado_id": 500,
            "coordinador_asignado_id": 100,
            "creado_por_id": 100,
            "titulo": "Asignacion Test"
        },
        {
            "rol": "coordinador"
        }
    ]

    app.dependency_overrides[get_tenant_db_connection] = lambda: mock_conn
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "500", "username": "digi1", "role_code": "digitalizador"}

    notifications_sent = []
    def spy_safe_crear_notificacion(conn, tenant, id_asignacion, id_usuario_destino, id_usuario_origen, rol_origen, rol_destino, tipo, titulo, mensaje, url_destino, prioridad, metadata):
        notifications_sent.append({"id_usuario_destino": id_usuario_destino, "rol_destino": rol_destino})

    import routers.asignaciones_workflow as workflow_router
    monkeypatch.setattr(workflow_router.asignaciones_repo, "safe_crear_notificacion", spy_safe_crear_notificacion)
    monkeypatch.setattr(workflow_router.asignaciones_repo, "update_asignacion_fields", lambda *a, **k: None)

    try:
        client = TestClient(app)
        response = client.post(
            "/api/workflow/asignaciones/123/submit-for-qa2",
            json={"enlace_digitalizacion": "https://example.com/digi-evidence"}
        )
        assert response.status_code == 200
        assert response.json()["workflow_state"] == "CONTROL_CALIDAD_2"
        assert len(notifications_sent) == 1
        assert notifications_sent[0]["id_usuario_destino"] == 100
        assert notifications_sent[0]["rol_destino"] == "coordinador"
    finally:
        app.dependency_overrides[get_tenant_db_connection] = mock_get_tenant_db_connection
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_return_to_digitalization_success(mock_command_service, monkeypatch):
    result = MagicMock()
    result.transition.assignment.assignment_id = "123"
    result.transition.assignment.workflow_state = WorkflowState.DEVUELTO
    result.transition.assignment.assigned_user_id = "500"
    mock_command_service.execute_transition.return_value = result

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.side_effect = [
        {
            "usuario_asignado_id": 500,
            "titulo": "Asignacion Test"
        },
        {
            "rol": "digitalizador"
        }
    ]

    app.dependency_overrides[get_tenant_db_connection] = lambda: mock_conn
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "100", "username": "coord1", "role_code": "coordinador"}

    notifications_sent = []
    def spy_safe_crear_notificacion(conn, tenant, id_asignacion, id_usuario_destino, id_usuario_origen, rol_origen, rol_destino, tipo, titulo, mensaje, url_destino, prioridad, metadata):
        notifications_sent.append({"id_usuario_destino": id_usuario_destino, "rol_destino": rol_destino})

    import routers.asignaciones_workflow as workflow_router
    monkeypatch.setattr(workflow_router.asignaciones_repo, "safe_crear_notificacion", spy_safe_crear_notificacion)

    try:
        client = TestClient(app)
        response = client.post("/api/workflow/asignaciones/123/return-to-digitalization")
        assert response.status_code == 200
        mock_cur.execute.assert_any_call(
            "UPDATE arbimaps_app.asignacion SET estado = 'DEVUELTO_DIGITALIZACION', enlace_digitalizacion = NULL, enlace_coordinador = NULL, enlace_devolucion = %s WHERE id = %s",
            (None, 123)
        )
        assert len(notifications_sent) == 1
        assert notifications_sent[0]["id_usuario_destino"] == 500
        assert notifications_sent[0]["rol_destino"] == "digitalizador"
    finally:
        app.dependency_overrides[get_tenant_db_connection] = mock_get_tenant_db_connection
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_approve_digitalization_success(mock_command_service, monkeypatch):
    result = MagicMock()
    result.transition.assignment.assignment_id = "123"
    result.transition.assignment.workflow_state = WorkflowState.APROBACION
    result.transition.assignment.assigned_user_id = "500"
    mock_command_service.execute_transition.return_value = result

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = {
        "enlace_digitalizacion": "https://example.com/digi-evidence",
        "creado_por_id": 200,
        "titulo": "Asignacion Test"
    }
    mock_cur.fetchall.return_value = [{"id_global": 300, "username": "lider1"}]

    app.dependency_overrides[get_tenant_db_connection] = lambda: mock_conn
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "100", "username": "coord1", "role_code": "coordinador"}

    notifications_sent = []
    def spy_safe_crear_notificacion(conn, tenant, id_asignacion, id_usuario_destino, id_usuario_origen, rol_origen, rol_destino, tipo, titulo, mensaje, url_destino, prioridad, metadata):
        notifications_sent.append({"id_usuario_destino": id_usuario_destino, "rol_destino": rol_destino})

    import routers.asignaciones_workflow as workflow_router
    monkeypatch.setattr(workflow_router.asignaciones_repo, "safe_crear_notificacion", spy_safe_crear_notificacion)
    monkeypatch.setattr(workflow_router.asignaciones_repo, "update_asignacion_fields", lambda *a, **k: None)

    try:
        client = TestClient(app)
        response = client.post("/api/workflow/asignaciones/123/approve-digitalization")
        assert response.status_code == 200
        assert len(notifications_sent) == 0
    finally:
        app.dependency_overrides[get_tenant_db_connection] = mock_get_tenant_db_connection
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_submit_to_lider_success(monkeypatch):
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = {
        "creado_por_id": 200,
        "titulo": "Asignacion Test",
        "estado": "APROBADO_DIGITALIZACION"
    }
    mock_cur.fetchall.return_value = [{"id_global": 300, "username": "lider1"}]

    app.dependency_overrides[get_tenant_db_connection] = lambda: mock_conn
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "100", "username": "coord1", "role_code": "coordinador"}

    notifications_sent = []
    def spy_safe_crear_notificacion(conn, tenant, id_asignacion, id_usuario_destino, id_usuario_origen, rol_origen, rol_destino, tipo, titulo, mensaje, url_destino, prioridad, metadata):
        notifications_sent.append({"id_usuario_destino": id_usuario_destino, "rol_destino": rol_destino})

    import routers.asignaciones_workflow as workflow_router
    monkeypatch.setattr(workflow_router.asignaciones_repo, "safe_crear_notificacion", spy_safe_crear_notificacion)
    monkeypatch.setattr(workflow_router.asignaciones_repo, "update_asignacion_fields", lambda *a, **k: None)
    monkeypatch.setattr(workflow_router.asignaciones_repo, "insert_asignacion_comentario", lambda *a, **k: None)
    monkeypatch.setattr(workflow_router.asignaciones_repo, "safe_log_event", lambda *a, **k: None)

    try:
        client = TestClient(app)
        response = client.post(
            "/api/workflow/asignaciones/123/submit-to-lider",
            json={"enlace_digitalizacion": "https://box.com/final-xtf", "comentario": "Listo para revision"}
        )
        assert response.status_code == 200
        assert len(notifications_sent) == 1
        assert notifications_sent[0]["id_usuario_destino"] == 300
        assert notifications_sent[0]["rol_destino"] == "lider_tecnico"
    finally:
        app.dependency_overrides[get_tenant_db_connection] = mock_get_tenant_db_connection
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_submit_to_lider_forbidden_for_lider():
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "300", "username": "lider1", "role_code": "lider_reconocimiento"}
    try:
        client = TestClient(app)
        response = client.post(
            "/api/workflow/asignaciones/123/submit-to-lider",
            json={"enlace_digitalizacion": "https://box.com/final-xtf"}
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Solo coordinadores o admins pueden enviar la revisión al Líder Técnico."
    finally:
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_lider_approve_success(mock_command_service, monkeypatch):
    result = MagicMock()
    result.transition.assignment.assignment_id = "123"
    result.transition.assignment.workflow_state = WorkflowState.SINCRONIZACION
    result.transition.assignment.assigned_user_id = "500"
    mock_command_service.execute_transition.return_value = result

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = {
        "enlace_digitalizacion": "https://example.com/digi-evidence",
        "creado_por_id": 200,
        "titulo": "Asignacion Test"
    }
    mock_cur.fetchall.return_value = [{"id_global": 400, "username": "support1"}]

    app.dependency_overrides[get_tenant_db_connection] = lambda: mock_conn
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "300", "username": "lider1", "role_code": "lider_reconocimiento"}

    notifications_sent = []
    def spy_safe_crear_notificacion(conn, tenant, id_asignacion, id_usuario_destino, id_usuario_origen, rol_origen, rol_destino, tipo, titulo, mensaje, url_destino, prioridad, metadata):
        notifications_sent.append({"id_usuario_destino": id_usuario_destino, "rol_destino": rol_destino})

    import routers.asignaciones_workflow as workflow_router
    monkeypatch.setattr(workflow_router.asignaciones_repo, "safe_crear_notificacion", spy_safe_crear_notificacion)
    monkeypatch.setattr(workflow_router.asignaciones_repo, "update_asignacion_fields", lambda *a, **k: None)

    try:
        client = TestClient(app)
        response = client.post("/api/workflow/asignaciones/123/lider-approve")
        assert response.status_code == 200
        assert len(notifications_sent) == 1
        assert notifications_sent[0]["id_usuario_destino"] == 400
        assert notifications_sent[0]["rol_destino"] == "admin"
    finally:
        app.dependency_overrides[get_tenant_db_connection] = mock_get_tenant_db_connection
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_lider_reject_success(mock_command_service, monkeypatch):
    result = MagicMock()
    result.transition.assignment.assignment_id = "123"
    result.transition.assignment.workflow_state = WorkflowState.DEVUELTO
    result.transition.assignment.assigned_user_id = "500"
    mock_command_service.execute_transition.return_value = result

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.side_effect = [
        {
            "usuario_asignado_id": 500,
            "coordinador_asignado_id": 600,
            "creado_por_id": 600,
            "titulo": "Asignacion Test"
        },
        {"rol": "coordinador"},
        {"rol": "digitalizador"}
    ]

    app.dependency_overrides[get_tenant_db_connection] = lambda: mock_conn
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "300", "username": "lider1", "role_code": "lider_reconocimiento"}

    notifications_sent = []
    def spy_safe_crear_notificacion(conn, tenant, id_asignacion, id_usuario_destino, id_usuario_origen, rol_origen, rol_destino, tipo, titulo, mensaje, url_destino, prioridad, metadata):
        notifications_sent.append({"id_usuario_destino": id_usuario_destino, "rol_destino": rol_destino})

    import routers.asignaciones_workflow as workflow_router
    monkeypatch.setattr(workflow_router.asignaciones_repo, "safe_crear_notificacion", spy_safe_crear_notificacion)

    try:
        client = TestClient(app)
        response = client.post("/api/workflow/asignaciones/123/lider-reject")
        assert response.status_code == 200
        assert len(notifications_sent) == 2
        assert notifications_sent[0]["id_usuario_destino"] == 600
        assert notifications_sent[0]["rol_destino"] == "coordinador"
        assert notifications_sent[1]["id_usuario_destino"] == 500
        assert notifications_sent[1]["rol_destino"] == "digitalizador"
    finally:
        app.dependency_overrides[get_tenant_db_connection] = mock_get_tenant_db_connection
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_return_to_digitalization_forbidden_for_lider():
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "300", "username": "lider1", "role_code": "lider_reconocimiento"}
    try:
        client = TestClient(app)
        response = client.post("/api/workflow/asignaciones/123/return-to-digitalization")
        assert response.status_code == 403
        assert response.json()["detail"] == "Solo coordinadores o admins pueden devolver a digitalización."
    finally:
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_approve_digitalization_forbidden_for_lider():
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "300", "username": "lider1", "role_code": "lider_reconocimiento"}
    try:
        client = TestClient(app)
        response = client.post("/api/workflow/asignaciones/123/approve-digitalization")
        assert response.status_code == 403
        assert response.json()["detail"] == "Solo coordinadores o admins pueden aprobar la digitalización."
    finally:
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user


def test_return_to_field_with_comment_success(mock_command_service, monkeypatch):
    result = MagicMock()
    result.transition.assignment.assignment_id = "1"
    result.transition.assignment.workflow_state = WorkflowState.DEVUELTO
    result.transition.assignment.assigned_user_id = "rec-01"
    result.transition.assignment.version = 3
    mock_command_service.execute_transition.return_value = result

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    
    mock_cur.fetchone.side_effect = [
        {"usuario_asignado_id": 12, "titulo": "Job", "estado": "CONTROL_CALIDAD_1"},
        {"rol": "reconocedor"}
    ]

    app.dependency_overrides[get_tenant_db_connection] = lambda: mock_conn
    app.dependency_overrides[get_current_user_from_session] = lambda: {"id_global": "123", "username": "admin1", "role_code": "administrador"}

    inserted_comments = []
    def spy_insert_comment(conn, tenant, asignacion_id, usuario_id, usuario, rol, comentario, estado_origen, estado_destino, enlace=None):
        inserted_comments.append({
            "asignacion_id": asignacion_id,
            "usuario_id": usuario_id,
            "usuario": usuario,
            "rol": rol,
            "comentario": comentario,
            "estado_origen": estado_origen,
            "estado_destino": estado_destino,
            "enlace": enlace
        })

    import routers.asignaciones_workflow as workflow_router
    monkeypatch.setattr(workflow_router.asignaciones_repo, "insert_asignacion_comentario", spy_insert_comment)
    monkeypatch.setattr(workflow_router.asignaciones_repo, "update_asignacion_fields", lambda *a, **k: None)
    monkeypatch.setattr(workflow_router.asignaciones_repo, "safe_crear_notificacion", lambda *a, **k: None)

    try:
        client = TestClient(app)
        response = client.post(
            "/api/workflow/asignaciones/1/return-to-field",
            json={"comentario": "Este es el motivo del rechazo"}
        )

        assert response.status_code == 200
        assert len(inserted_comments) == 1
        assert inserted_comments[0]["comentario"] == "Este es el motivo del rechazo"
        assert inserted_comments[0]["estado_origen"] == "CONTROL_CALIDAD_1"
        assert inserted_comments[0]["estado_destino"] == "DEVUELTO_CAMPO"
    finally:
        app.dependency_overrides[get_tenant_db_connection] = mock_get_tenant_db_connection
        app.dependency_overrides[get_current_user_from_session] = mock_get_current_user









from unittest.mock import MagicMock
import pytest

from workflow.enums import WorkflowRole, WorkflowState
from workflow.models import AssignmentSnapshot
from workflow.postgres_repositories import (
    PostgresAssignmentRepository,
    PostgresAuditRepository,
    PostgresOutboxRepository,
    PostgresTransitionRepository,
)
from workflow.postgres_uow import PostgresUnitOfWork


class MockSchemas:
    workflow = "d_workflow"
    app = "arbimaps_app"


class MockTenantContext:
    schemas = MockSchemas()


@pytest.fixture
def mock_cursor():
    return MagicMock()


@pytest.fixture
def mock_conn(mock_cursor):
    conn = MagicMock()
    conn.cursor.return_value = mock_cursor
    return conn


@pytest.fixture
def mock_connection_manager(mock_conn):
    manager = MagicMock()
    manager.get_connection.return_value = mock_conn
    return manager


@pytest.fixture
def tenant_context():
    return MockTenantContext()


def test_postgres_uow_commit_and_release(mock_connection_manager, tenant_context, mock_conn, mock_cursor):
    uow = PostgresUnitOfWork(mock_connection_manager, tenant_context)
    
    with uow:
        assert uow.conn.autocommit is False
        assert isinstance(uow.assignments, PostgresAssignmentRepository)
        assert isinstance(uow.audit, PostgresAuditRepository)
        assert isinstance(uow.outbox, PostgresOutboxRepository)
        assert isinstance(uow.transitions, PostgresTransitionRepository)

    mock_conn.commit.assert_called_once()
    mock_cursor.close.assert_called_once()
    mock_connection_manager.release_connection.assert_called_once_with(tenant_context, mock_conn)


def test_postgres_uow_rollback_on_error(mock_connection_manager, tenant_context, mock_conn, mock_cursor):
    uow = PostgresUnitOfWork(mock_connection_manager, tenant_context)
    
    with pytest.raises(ValueError):
        with uow:
            raise ValueError("Test error")

    mock_conn.rollback.assert_called_once()
    mock_conn.commit.assert_not_called()
    mock_cursor.close.assert_called_once()
    mock_connection_manager.release_connection.assert_called_once_with(tenant_context, mock_conn)


def test_postgres_assignment_repository_save(mock_cursor):
    repo = PostgresAssignmentRepository(mock_cursor, "d_workflow")
    assignment = AssignmentSnapshot(
        assignment_id="A-001", tenant_code="saravena", workflow_state=WorkflowState.SIN_ASIGNAR, version=2
    )
    mock_cursor.rowcount = 1

    repo.save(assignment)

    query = mock_cursor.execute.call_args[0][0]
    params = mock_cursor.execute.call_args[0][1]
    assert "ON CONFLICT" in query
    assert "WHERE d_workflow.assignments.version = %(expected_version)s" in query
    assert params["expected_version"] == 1


def test_postgres_assignment_repository_get_with_for_update(mock_cursor):
    repo = PostgresAssignmentRepository(mock_cursor, "d_workflow")
    mock_cursor.fetchone.return_value = (
        "A-001", "saravena", "SIN_ASIGNAR", "PENDING", "NONE", "NONE",
        None, None, False, 1, '{"key":"val"}'
    )
    
    repo.get("saravena", "A-001")
    query = mock_cursor.execute.call_args[0][0]
    assert "FOR UPDATE" in query
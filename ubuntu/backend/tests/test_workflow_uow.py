import pytest

from workflow.command_service import AssignmentCommandService
from workflow.enums import WorkflowEvent, WorkflowRole, WorkflowState
from workflow.fakes import FakeUnitOfWork
from workflow.models import ActorContext, AssignmentSnapshot
from workflow.service import AssignmentWorkflowService


@pytest.fixture
def uow():
    return FakeUnitOfWork()


@pytest.fixture
def command_service(uow):
    workflow_service = AssignmentWorkflowService()
    return AssignmentCommandService(workflow_service=workflow_service, uow_factory=lambda: uow)


@pytest.fixture
def initial_assignment(uow):
    assignment = AssignmentSnapshot(
        assignment_id="ASG-001",
        tenant_code="leiva",
        workflow_state=WorkflowState.SIN_ASIGNAR,
        version=1
    )
    uow.assignments_data[("leiva", "ASG-001")] = assignment
    return assignment


def test_successful_transition_with_commit(command_service, uow, initial_assignment):
    actor = ActorContext(tenant_code="leiva", user_id="user-123", role=WorkflowRole.ADMINISTRADOR)
    
    result = command_service.execute_transition(
        assignment_id="ASG-001",
        actor=actor,
        event=WorkflowEvent.ASSIGN,
        metadata={"target_user_id": "reconocedor-01"}
    )
    
    # Comprobamos ejecución transaccional correcta
    assert uow.committed is True
    assert uow.rolled_back is False
    
    saved_assignment = uow.assignments_data[("leiva", "ASG-001")]
    assert saved_assignment.workflow_state == WorkflowState.EN_CAMPO
    assert saved_assignment.assigned_user_id == "reconocedor-01"
    assert saved_assignment.version == 2

    assert len(uow.audit_data) > 0
    assert len(uow.outbox_data) > 0
    assert len(uow.transitions_data) == 1


def test_invalid_transition_triggers_rollback(command_service, uow, initial_assignment):
    # Fallará porque el RECONOCEDOR no puede asignar o porque el estado no lo permite
    actor = ActorContext(tenant_code="leiva", user_id="user-123", role=WorkflowRole.RECONOCEDOR)
    
    with pytest.raises(Exception):
        command_service.execute_transition(
            assignment_id="ASG-001",
            actor=actor,
            event=WorkflowEvent.SUBMIT_FOR_QA
        )
    
    # Comprobamos rollback en cadena
    assert uow.committed is False
    assert uow.rolled_back is True
    
    saved_assignment = uow.assignments_data[("leiva", "ASG-001")]
    assert saved_assignment.workflow_state == WorkflowState.SIN_ASIGNAR
    assert saved_assignment.version == 1
    
    assert len(uow.audit_data) == 0
    assert len(uow.outbox_data) == 0
    assert len(uow.transitions_data) == 0


def test_repository_error_triggers_rollback(initial_assignment):
    actor = ActorContext(tenant_code="leiva", user_id="user-123", role=WorkflowRole.ADMINISTRADOR)
    
    class BrokenFakeUnitOfWork(FakeUnitOfWork):
        def commit(self):
            raise RuntimeError("Database connection lost")
            
    broken_uow = BrokenFakeUnitOfWork()
    broken_uow.assignments_data[("leiva", "ASG-001")] = initial_assignment
    broken_service = AssignmentCommandService(AssignmentWorkflowService(), lambda: broken_uow)
    
    with pytest.raises(RuntimeError, match="Database connection lost"):
        broken_service.execute_transition("ASG-001", actor, WorkflowEvent.ASSIGN, metadata={"target_user_id": "r-01"})
    
    assert broken_uow.rolled_back is True
    assert broken_uow.assignments_data[("leiva", "ASG-001")].version == 1
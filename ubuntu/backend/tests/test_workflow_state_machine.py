import pytest

from workflow import (
    ActorContext,
    AssignmentClosedError,
    AssignmentSnapshot,
    InvalidTransitionError,
    OwnershipValidationError,
    RetornoState,
    RoleNotAllowedError,
    SyncInProgressError,
    SyncState,
    TenantMismatchError,
    WorkflowPreconditionError,
    WorkflowEvent,
    WorkflowRole,
    WorkflowState,
    WorkspaceState,
    apply_transition,
    can_transition,
    validate_transition,
)


def _assignment(**overrides):
    base = dict(
        assignment_id="asg-1",
        tenant_code="sucre",
        workflow_state=WorkflowState.SIN_ASIGNAR,
        workspace_state=WorkspaceState.PENDING,
        retorno_state=RetornoState.NONE,
        sync_state=SyncState.NONE,
        assigned_user_id=None,
        assigned_role=None,
        is_closed=False,
        version=0,
    )
    base.update(overrides)
    return AssignmentSnapshot(**base)


def _actor(
    role=WorkflowRole.COORDINADOR,
    *,
    tenant_code="sucre",
    user_id="u-1",
):
    return ActorContext(tenant_code=tenant_code, user_id=user_id, role=role)


def test_assign_transition_is_deterministic():
    assignment = _assignment()
    actor = _actor(role=WorkflowRole.ASIGNADOR)

    result = apply_transition(
        assignment,
        actor,
        WorkflowEvent.ASSIGN,
        metadata={"target_user_id": "rec-1"},
    )

    assert result.from_state == WorkflowState.SIN_ASIGNAR
    assert result.to_state == WorkflowState.EN_CAMPO
    assert result.assignment.workflow_state == WorkflowState.EN_CAMPO
    assert result.assignment.assigned_user_id == "rec-1"
    assert result.assignment.workspace_state == WorkspaceState.PENDING
    assert result.outbox_events == ("BUILD_WORKSPACE",)


def test_submit_for_qa_requires_owner_and_workspace_ready():
    assignment = _assignment(
        workflow_state=WorkflowState.EN_CAMPO,
        workspace_state=WorkspaceState.READY,
        assigned_user_id="rec-1",
        assigned_role=WorkflowRole.RECONOCEDOR,
    )
    actor = _actor(role=WorkflowRole.RECONOCEDOR, user_id="rec-1")

    result = apply_transition(assignment, actor, WorkflowEvent.SUBMIT_FOR_QA)

    assert result.assignment.workflow_state == WorkflowState.CONTROL_CALIDAD
    assert result.audit_events == ("assignment.submitted_for_qa",)


def test_invalid_role_is_rejected():
    assignment = _assignment()
    actor = _actor(role=WorkflowRole.CONSULTA)

    with pytest.raises(RoleNotAllowedError):
        validate_transition(assignment, actor, WorkflowEvent.ASSIGN, metadata={"target_user_id": "rec-1"})


def test_invalid_state_transition_is_rejected():
    assignment = _assignment(workflow_state=WorkflowState.SIN_ASIGNAR)
    actor = _actor(role=WorkflowRole.RECONOCEDOR, user_id="rec-1")

    with pytest.raises(InvalidTransitionError):
        validate_transition(assignment, actor, WorkflowEvent.SUBMIT_FOR_QA)


def test_tenant_mismatch_is_rejected():
    assignment = _assignment()
    actor = _actor(tenant_code="neiva")

    with pytest.raises(TenantMismatchError):
        validate_transition(assignment, actor, WorkflowEvent.ASSIGN, metadata={"target_user_id": "rec-1"})


def test_closed_assignment_is_blocked():
    assignment = _assignment(
        workflow_state=WorkflowState.EN_CAMPO,
        is_closed=True,
        assigned_user_id="rec-1",
    )
    actor = _actor(role=WorkflowRole.RECONOCEDOR, user_id="rec-1")

    with pytest.raises(AssignmentClosedError):
        validate_transition(assignment, actor, WorkflowEvent.SUBMIT_FOR_QA)


def test_sync_running_blocks_non_sync_completion_events():
    assignment = _assignment(
        workflow_state=WorkflowState.APROBACION,
        workspace_state=WorkspaceState.READY,
        retorno_state=RetornoState.VALIDATED,
        sync_state=SyncState.RUNNING,
    )
    actor = _actor(role=WorkflowRole.COORDINADOR)

    with pytest.raises(SyncInProgressError):
        validate_transition(assignment, actor, WorkflowEvent.START_SYNC)


def test_owner_validation_is_enforced():
    assignment = _assignment(
        workflow_state=WorkflowState.EN_CAMPO,
        workspace_state=WorkspaceState.READY,
        assigned_user_id="owner-1",
        assigned_role=WorkflowRole.RECONOCEDOR,
    )
    actor = _actor(role=WorkflowRole.RECONOCEDOR, user_id="other-user")

    with pytest.raises(OwnershipValidationError):
        validate_transition(assignment, actor, WorkflowEvent.SUBMIT_FOR_QA)


def test_start_sync_requires_validated_return():
    assignment = _assignment(
        workflow_state=WorkflowState.APROBACION,
        workspace_state=WorkspaceState.READY,
        retorno_state=RetornoState.UPLOADED,
    )
    actor = _actor(role=WorkflowRole.COORDINADOR)

    assert can_transition(assignment, actor, WorkflowEvent.START_SYNC) is False


def test_mark_synced_closes_assignment_and_archives_workspace():
    assignment = _assignment(
        workflow_state=WorkflowState.SINCRONIZACION,
        workspace_state=WorkspaceState.READY,
        retorno_state=RetornoState.VALIDATED,
        sync_state=SyncState.RUNNING,
        assigned_user_id="rec-1",
    )
    actor = _actor(role=WorkflowRole.COORDINADOR)

    result = apply_transition(assignment, actor, WorkflowEvent.MARK_SYNCED)

    assert result.assignment.workflow_state == WorkflowState.SINCRONIZADO
    assert result.assignment.sync_state == SyncState.SUCCESS
    assert result.assignment.retorno_state == RetornoState.PUBLISHED
    assert result.assignment.workspace_state == WorkspaceState.ARCHIVED
    assert result.assignment.is_closed is True


def test_reassign_keeps_workflow_state_and_resets_technical_states():
    assignment = _assignment(
        workflow_state=WorkflowState.CONTROL_CALIDAD,
        workspace_state=WorkspaceState.READY,
        retorno_state=RetornoState.VALIDATED,
        sync_state=SyncState.NONE,
        assigned_user_id="rec-1",
    )
    actor = _actor(role=WorkflowRole.COORDINADOR)

    result = apply_transition(
        assignment,
        actor,
        WorkflowEvent.REASSIGN,
        metadata={"target_user_id": "rec-2"},
    )

    assert result.assignment.workflow_state == WorkflowState.CONTROL_CALIDAD
    assert result.assignment.assigned_user_id == "rec-2"
    assert result.assignment.workspace_state == WorkspaceState.PENDING
    assert result.assignment.retorno_state == RetornoState.NONE


def test_assign_requires_target_user_id():
    assignment = _assignment()
    actor = _actor(role=WorkflowRole.COORDINADOR)

    with pytest.raises(WorkflowPreconditionError):
        validate_transition(assignment, actor, WorkflowEvent.ASSIGN)


def test_reopen_requires_reason():
    assignment = _assignment(
        workflow_state=WorkflowState.SINCRONIZADO,
        workspace_state=WorkspaceState.ARCHIVED,
        retorno_state=RetornoState.PUBLISHED,
        sync_state=SyncState.SUCCESS,
        is_closed=True,
    )
    actor = _actor(role=WorkflowRole.ADMINISTRADOR)

    with pytest.raises(WorkflowPreconditionError):
        validate_transition(assignment, actor, WorkflowEvent.REOPEN)

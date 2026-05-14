from datetime import datetime, timezone

import pytest

from workflow.audit.events import AuditEventType
from workflow.audit.models import AuditContext
from workflow.enums import RetornoState, SyncState, WorkflowEvent, WorkflowRole, WorkflowState, WorkspaceState
from workflow.exceptions import RoleNotAllowedError
from workflow.models import ActorContext, AssignmentSnapshot
from workflow.service import AssignmentWorkflowService


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


def test_service_apply_event_builds_audit_and_outbox_for_assign():
    fixed_now = datetime(2026, 5, 13, 14, 30, tzinfo=timezone.utc)
    service = AssignmentWorkflowService(
        clock=lambda: fixed_now,
        correlation_id_factory=lambda: "corr-123",
    )
    result = service.apply_event(
        _assignment(),
        _actor(role=WorkflowRole.ASIGNADOR),
        WorkflowEvent.ASSIGN,
        metadata={"target_user_id": "rec-9"},
    )

    assert result.transition.assignment.workflow_state == WorkflowState.EN_CAMPO
    assert [event.event_type for event in result.audit_events] == [
        AuditEventType.ASSIGNMENT_CREATED,
        AuditEventType.ASSIGNMENT_WORKFLOW_CHANGED,
        AuditEventType.ASSIGNMENT_WORKSPACE_BUILD_REQUESTED,
    ]
    assert result.outbox_messages[0].job_type == "BUILD_WORKSPACE"
    assert result.outbox_messages[0].idempotency_key == "sucre:asg-1:1:BUILD_WORKSPACE"
    assert result.audit_events[0].occurred_at == fixed_now
    assert result.audit_events[0].correlation_id == "corr-123"


def test_service_validate_transition_delegates_domain_errors():
    service = AssignmentWorkflowService()
    assignment = _assignment()
    actor = _actor(role=WorkflowRole.CONSULTA)

    with pytest.raises(RoleNotAllowedError):
        service.validate_transition(
            assignment,
            actor,
            WorkflowEvent.ASSIGN,
            metadata={"target_user_id": "rec-1"},
        )


def test_service_build_audit_event_uses_explicit_context():
    fixed_now = datetime(2026, 5, 13, 14, 45, tzinfo=timezone.utc)
    service = AssignmentWorkflowService(clock=lambda: fixed_now)
    assignment = _assignment(
        workflow_state=WorkflowState.SINCRONIZACION,
        workspace_state=WorkspaceState.READY,
        retorno_state=RetornoState.VALIDATED,
        sync_state=SyncState.RUNNING,
        assigned_user_id="rec-1",
    )
    transition_result = service.apply_event(
        assignment,
        _actor(role=WorkflowRole.COORDINADOR),
        WorkflowEvent.MARK_SYNCED,
        audit_context=AuditContext(
            tenant_code="sucre",
            actor_user_id="coord-1",
            actor_role=WorkflowRole.COORDINADOR,
            correlation_id="corr-explicit",
            source="tests",
            metadata={"request_id": "req-9"},
        ),
    )

    audit_event = transition_result.audit_events[0]
    assert audit_event.event_type == AuditEventType.ASSIGNMENT_SYNC_SUCCEEDED
    assert audit_event.source == "tests"
    assert audit_event.correlation_id == "corr-explicit"
    assert audit_event.metadata["audit_context_metadata"] == {"request_id": "req-9"}


def test_service_reassign_generates_reassign_and_workspace_events():
    service = AssignmentWorkflowService(correlation_id_factory=lambda: "corr-456")
    result = service.apply_event(
        _assignment(
            workflow_state=WorkflowState.CONTROL_CALIDAD,
            workspace_state=WorkspaceState.READY,
            retorno_state=RetornoState.VALIDATED,
            assigned_user_id="rec-1",
        ),
        _actor(role=WorkflowRole.COORDINADOR),
        WorkflowEvent.REASSIGN,
        metadata={"target_user_id": "rec-2"},
    )

    assert [event.event_type for event in result.audit_events] == [
        AuditEventType.ASSIGNMENT_REASSIGNED,
        AuditEventType.ASSIGNMENT_WORKFLOW_CHANGED,
        AuditEventType.ASSIGNMENT_WORKSPACE_BUILD_REQUESTED,
    ]
    assert result.transition.assignment.assigned_user_id == "rec-2"

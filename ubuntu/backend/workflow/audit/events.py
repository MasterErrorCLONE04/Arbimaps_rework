from __future__ import annotations

from enum import Enum


class AuditEventType(str, Enum):
    ASSIGNMENT_CREATED = "assignment.created"
    ASSIGNMENT_REASSIGNED = "assignment.reassigned"
    ASSIGNMENT_WORKFLOW_CHANGED = "assignment.workflow.changed"
    ASSIGNMENT_WORKSPACE_BUILD_REQUESTED = "assignment.workspace.build_requested"
    ASSIGNMENT_WORKSPACE_READY = "assignment.workspace.ready"
    ASSIGNMENT_WORKSPACE_FAILED = "assignment.workspace.failed"
    ASSIGNMENT_RETURN_UPLOADED = "assignment.return.uploaded"
    ASSIGNMENT_RETURN_VALIDATED = "assignment.return.validated"
    ASSIGNMENT_RETURN_REJECTED = "assignment.return.rejected"
    ASSIGNMENT_SYNC_STARTED = "assignment.sync.started"
    ASSIGNMENT_SYNC_SUCCEEDED = "assignment.sync.succeeded"
    ASSIGNMENT_SYNC_FAILED = "assignment.sync.failed"
    ASSIGNMENT_REOPENED = "assignment.reopened"
    ASSIGNMENT_CLOSED = "assignment.closed"


AUDIT_EVENT_ALIAS_MAP: dict[str, AuditEventType] = {
    "assignment.created": AuditEventType.ASSIGNMENT_CREATED,
    "assignment.assigned": AuditEventType.ASSIGNMENT_CREATED,
    "assignment.reassigned": AuditEventType.ASSIGNMENT_REASSIGNED,
    "assignment.workflow.changed": AuditEventType.ASSIGNMENT_WORKFLOW_CHANGED,
    "assignment.fieldwork.started": AuditEventType.ASSIGNMENT_WORKFLOW_CHANGED,
    "assignment.submitted_for_qa": AuditEventType.ASSIGNMENT_WORKFLOW_CHANGED,
    "assignment.returned_to_field": AuditEventType.ASSIGNMENT_WORKFLOW_CHANGED,
    "assignment.resubmitted_from_return": AuditEventType.ASSIGNMENT_WORKFLOW_CHANGED,
    "assignment.approved": AuditEventType.ASSIGNMENT_WORKFLOW_CHANGED,
    "assignment.sync.started": AuditEventType.ASSIGNMENT_SYNC_STARTED,
    "assignment.sync.succeeded": AuditEventType.ASSIGNMENT_SYNC_SUCCEEDED,
    "assignment.sync.failed": AuditEventType.ASSIGNMENT_SYNC_FAILED,
    "assignment.reopened": AuditEventType.ASSIGNMENT_REOPENED,
    "assignment.closed": AuditEventType.ASSIGNMENT_CLOSED,
    "assignment.cancelled": AuditEventType.ASSIGNMENT_CLOSED,
    "assignment.workspace.ready": AuditEventType.ASSIGNMENT_WORKSPACE_READY,
    "assignment.workspace.failed": AuditEventType.ASSIGNMENT_WORKSPACE_FAILED,
    "assignment.return.uploaded": AuditEventType.ASSIGNMENT_RETURN_UPLOADED,
    "assignment.return.validated": AuditEventType.ASSIGNMENT_RETURN_VALIDATED,
    "assignment.return.rejected": AuditEventType.ASSIGNMENT_RETURN_REJECTED,
}


AUDIT_OUTBOX_EVENT_MAP: dict[str, AuditEventType] = {
    "BUILD_WORKSPACE": AuditEventType.ASSIGNMENT_WORKSPACE_BUILD_REQUESTED,
}


def resolve_audit_event_types(
    raw_event_names: tuple[str, ...] | list[str],
    outbox_event_names: tuple[str, ...] | list[str] = (),
) -> tuple[AuditEventType, ...]:
    resolved: list[AuditEventType] = []
    seen: set[AuditEventType] = set()

    for name in raw_event_names:
        event_type = AUDIT_EVENT_ALIAS_MAP.get(name)
        if event_type is not None and event_type not in seen:
            resolved.append(event_type)
            seen.add(event_type)

    for name in outbox_event_names:
        event_type = AUDIT_OUTBOX_EVENT_MAP.get(name)
        if event_type is not None and event_type not in seen:
            resolved.append(event_type)
            seen.add(event_type)

    return tuple(resolved)

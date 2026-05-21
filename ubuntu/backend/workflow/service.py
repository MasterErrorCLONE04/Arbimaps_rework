from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping
from uuid import uuid4

from .audit.events import AuditEventType, resolve_audit_event_types
from .audit.models import AuditContext, AuditEvent
from .enums import WorkflowEvent
from .models import ActorContext, AssignmentSnapshot, TransitionResult
from .state_machine import apply_transition as apply_transition_core
from .state_machine import validate_transition as validate_transition_core


Clock = Callable[[], datetime]
CorrelationIdFactory = Callable[[], str]


@dataclass(frozen=True)
class PreparedOutboxMessage:
    job_type: str
    tenant_code: str
    assignment_id: str
    correlation_id: str | None
    idempotency_key: str
    payload: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowServiceResult:
    transition: TransitionResult
    audit_context: AuditContext
    audit_events: tuple[AuditEvent, ...]
    outbox_messages: tuple[PreparedOutboxMessage, ...]
    occurred_at: datetime


class AssignmentWorkflowService:
    def __init__(
        self,
        *,
        clock: Clock | None = None,
        correlation_id_factory: CorrelationIdFactory | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._correlation_id_factory = correlation_id_factory or (lambda: str(uuid4()))

    def validate_transition(
        self,
        assignment: AssignmentSnapshot,
        actor: ActorContext,
        event: WorkflowEvent,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        validate_transition_core(assignment, actor, event, metadata=dict(metadata or {}))

    def build_audit_event(
        self,
        *,
        event_type: AuditEventType,
        transition: TransitionResult,
        audit_context: AuditContext,
        occurred_at: datetime | None = None,
    ) -> AuditEvent:
        metadata = {
            "transition_metadata": dict(transition.metadata),
            "audit_context_metadata": dict(audit_context.metadata),
            "precondition_hooks": list(transition.precondition_hooks),
            "post_transition_events": list(transition.post_transition_events),
        }
        return AuditEvent(
            event_type=event_type,
            tenant_code=audit_context.tenant_code,
            assignment_id=transition.assignment.assignment_id,
            actor_user_id=audit_context.actor_user_id,
            actor_role=audit_context.actor_role,
            workflow_event=transition.event,
            from_state=transition.from_state,
            to_state=transition.to_state,
            occurred_at=occurred_at or self._clock(),
            correlation_id=audit_context.correlation_id,
            source=audit_context.source,
            metadata=metadata,
        )

    def apply_event(
        self,
        assignment: AssignmentSnapshot,
        actor: ActorContext,
        event: WorkflowEvent,
        *,
        metadata: Mapping[str, object] | None = None,
        audit_context: AuditContext | None = None,
    ) -> WorkflowServiceResult:
        occurred_at = self._clock()
        metadata_dict = dict(metadata or {})
        transition = apply_transition_core(assignment, actor, event, metadata=metadata_dict)
        effective_audit_context = audit_context or AuditContext(
            tenant_code=actor.tenant_code,
            actor_user_id=actor.user_id,
            actor_role=actor.role,
            correlation_id=self._correlation_id_factory(),
        )
        audit_events = self._build_audit_events(transition, effective_audit_context, occurred_at)
        outbox_messages = self._build_outbox_messages(transition, effective_audit_context)
        return WorkflowServiceResult(
            transition=transition,
            audit_context=effective_audit_context,
            audit_events=audit_events,
            outbox_messages=outbox_messages,
            occurred_at=occurred_at,
        )

    def _build_audit_events(
        self,
        transition: TransitionResult,
        audit_context: AuditContext,
        occurred_at: datetime,
    ) -> tuple[AuditEvent, ...]:
        raw_event_names = tuple(transition.audit_events) + tuple(transition.post_transition_events)
        event_types = resolve_audit_event_types(raw_event_names, transition.outbox_events)
        return tuple(
            self.build_audit_event(
                event_type=event_type,
                transition=transition,
                audit_context=audit_context,
                occurred_at=occurred_at,
            )
            for event_type in event_types
        )

    def _build_outbox_messages(
        self,
        transition: TransitionResult,
        audit_context: AuditContext,
    ) -> tuple[PreparedOutboxMessage, ...]:
        messages: list[PreparedOutboxMessage] = []
        for job_type in transition.outbox_events:
            payload = {
                "tenant_code": transition.assignment.tenant_code,
                "assignment_id": transition.assignment.assignment_id,
                "workflow_event": transition.event.value,
                "workflow_state": transition.assignment.workflow_state.value,
                "actor_user_id": audit_context.actor_user_id,
                "actor_role": audit_context.actor_role.value,
                "correlation_id": audit_context.correlation_id,
                "metadata": dict(transition.metadata),
            }
            idempotency_key = (
                f"{transition.assignment.tenant_code}:"
                f"{transition.assignment.assignment_id}:"
                f"{transition.assignment.version}:"
                f"{job_type}"
            )
            messages.append(
                PreparedOutboxMessage(
                    job_type=job_type,
                    tenant_code=transition.assignment.tenant_code,
                    assignment_id=transition.assignment.assignment_id,
                    correlation_id=audit_context.correlation_id,
                    idempotency_key=idempotency_key,
                    payload=payload,
                )
            )
        return tuple(messages)

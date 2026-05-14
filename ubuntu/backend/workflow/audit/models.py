from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from .events import AuditEventType
from ..enums import WorkflowEvent, WorkflowRole, WorkflowState


@dataclass(frozen=True)
class AuditContext:
    tenant_code: str
    actor_user_id: str
    actor_role: WorkflowRole
    correlation_id: str | None = None
    source: str = "workflow.service"
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditEvent:
    event_type: AuditEventType
    tenant_code: str
    assignment_id: str
    actor_user_id: str
    actor_role: WorkflowRole
    workflow_event: WorkflowEvent
    from_state: WorkflowState
    to_state: WorkflowState
    occurred_at: datetime
    correlation_id: str | None = None
    source: str = "workflow.service"
    metadata: Mapping[str, object] = field(default_factory=dict)

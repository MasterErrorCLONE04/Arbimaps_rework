from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping

from .enums import (
    RetornoState,
    SyncState,
    WorkflowEvent,
    WorkflowRole,
    WorkflowState,
    WorkspaceState,
)


@dataclass(frozen=True)
class ActorContext:
    tenant_code: str
    user_id: str
    role: WorkflowRole


@dataclass(frozen=True)
class AssignmentSnapshot:
    assignment_id: str
    tenant_code: str
    workflow_state: WorkflowState
    workspace_state: WorkspaceState = WorkspaceState.PENDING
    retorno_state: RetornoState = RetornoState.NONE
    sync_state: SyncState = SyncState.NONE
    assigned_user_id: str | None = None
    assigned_role: WorkflowRole | None = None
    is_closed: bool = False
    version: int = 0
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TransitionContext:
    assignment: AssignmentSnapshot
    actor: ActorContext
    event: WorkflowEvent
    metadata: Mapping[str, object] = field(default_factory=dict)


PreconditionHook = Callable[[TransitionContext], None]
StateResolver = Callable[[TransitionContext], WorkflowState]
AssignmentMutator = Callable[[TransitionContext, WorkflowState], AssignmentSnapshot]


@dataclass(frozen=True)
class TransitionResult:
    event: WorkflowEvent
    from_state: WorkflowState
    to_state: WorkflowState
    assignment: AssignmentSnapshot
    audit_events: tuple[str, ...] = ()
    outbox_events: tuple[str, ...] = ()
    precondition_hooks: tuple[str, ...] = ()
    post_transition_events: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TransitionSpec:
    event: WorkflowEvent
    from_states: tuple[WorkflowState, ...]
    allowed_roles: tuple[WorkflowRole, ...]
    target_state: WorkflowState | None = None
    target_state_resolver: StateResolver | None = None
    owner_required: bool = False
    allow_when_closed: bool = False
    block_when_sync_running: bool = True
    audit_events: tuple[str, ...] = ()
    outbox_events: tuple[str, ...] = ()
    precondition_hooks: tuple[str, ...] = ()
    post_transition_events: tuple[str, ...] = ()
    preconditions: tuple[PreconditionHook, ...] = ()
    assignment_mutator: AssignmentMutator | None = None

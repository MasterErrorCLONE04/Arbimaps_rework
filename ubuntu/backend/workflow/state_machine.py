from __future__ import annotations

from dataclasses import replace

from .enums import RetornoState, SyncState, WorkflowEvent, WorkflowRole, WorkflowState, WorkspaceState
from .exceptions import (
    AssignmentClosedError,
    InvalidTransitionError,
    OwnershipValidationError,
    RoleNotAllowedError,
    SyncInProgressError,
    TenantMismatchError,
    WorkflowError,
    WorkflowPreconditionError,
)
from .models import ActorContext, AssignmentSnapshot, TransitionContext, TransitionResult, TransitionSpec


def _ensure_workspace_ready(context: TransitionContext) -> None:
    if context.assignment.workspace_state != WorkspaceState.READY:
        raise WorkflowPreconditionError(
            "La asignacion requiere workspace READY para ejecutar esta transicion."
        )


def _ensure_retorno_validated(context: TransitionContext) -> None:
    if context.assignment.retorno_state != RetornoState.VALIDATED:
        raise WorkflowPreconditionError(
            "La asignacion requiere retorno VALIDATED antes de iniciar sincronizacion."
        )


def _ensure_target_user_present(context: TransitionContext) -> None:
    if not str(context.metadata.get("target_user_id") or "").strip():
        raise WorkflowPreconditionError(
            "La transicion requiere target_user_id para definir el propietario destino."
        )


def _ensure_reopen_reason_present(context: TransitionContext) -> None:
    if not str(context.metadata.get("reason") or "").strip():
        raise WorkflowPreconditionError("La reapertura requiere un motivo explicito.")


def _ensure_sync_started(context: TransitionContext) -> None:
    if context.assignment.sync_state != SyncState.RUNNING:
        raise WorkflowPreconditionError("MARK_SYNCED requiere una sincronizacion RUNNING.")


def _resolve_same_state(context: TransitionContext) -> WorkflowState:
    return context.assignment.workflow_state


def _resolve_reopen_state(context: TransitionContext) -> WorkflowState:
    if context.assignment.workflow_state == WorkflowState.DEVUELTO:
        return WorkflowState.EN_CAMPO
    return WorkflowState.EN_CAMPO


def _mutate_assign(context: TransitionContext, target_state: WorkflowState) -> AssignmentSnapshot:
    return replace(
        context.assignment,
        workflow_state=target_state,
        workspace_state=WorkspaceState.PENDING,
        retorno_state=RetornoState.NONE,
        sync_state=SyncState.NONE,
        assigned_user_id=str(context.metadata.get("target_user_id") or context.assignment.assigned_user_id or ""),
        assigned_role=WorkflowRole.RECONOCEDOR,
        is_closed=False,
        version=context.assignment.version + 1,
    )


def _mutate_start_fieldwork(context: TransitionContext, target_state: WorkflowState) -> AssignmentSnapshot:
    return replace(
        context.assignment,
        workflow_state=target_state,
        version=context.assignment.version + 1,
    )


def _mutate_submit_for_qa(context: TransitionContext, target_state: WorkflowState) -> AssignmentSnapshot:
    return replace(
        context.assignment,
        workflow_state=target_state,
        version=context.assignment.version + 1,
    )


def _mutate_return_to_field(context: TransitionContext, target_state: WorkflowState) -> AssignmentSnapshot:
    return replace(
        context.assignment,
        workflow_state=target_state,
        sync_state=SyncState.NONE,
        version=context.assignment.version + 1,
    )


def _mutate_approve(context: TransitionContext, target_state: WorkflowState) -> AssignmentSnapshot:
    return replace(
        context.assignment,
        workflow_state=target_state,
        sync_state=SyncState.PENDING,
        version=context.assignment.version + 1,
    )


def _mutate_start_sync(context: TransitionContext, target_state: WorkflowState) -> AssignmentSnapshot:
    return replace(
        context.assignment,
        workflow_state=target_state,
        sync_state=SyncState.RUNNING,
        version=context.assignment.version + 1,
    )


def _mutate_mark_synced(context: TransitionContext, target_state: WorkflowState) -> AssignmentSnapshot:
    return replace(
        context.assignment,
        workflow_state=target_state,
        retorno_state=RetornoState.PUBLISHED,
        sync_state=SyncState.SUCCESS,
        workspace_state=WorkspaceState.ARCHIVED,
        is_closed=True,
        version=context.assignment.version + 1,
    )


def _mutate_reassign(context: TransitionContext, target_state: WorkflowState) -> AssignmentSnapshot:
    return replace(
        context.assignment,
        workflow_state=target_state,
        workspace_state=WorkspaceState.PENDING,
        retorno_state=RetornoState.NONE,
        sync_state=SyncState.NONE,
        assigned_user_id=str(context.metadata.get("target_user_id") or context.assignment.assigned_user_id or ""),
        assigned_role=WorkflowRole.RECONOCEDOR,
        is_closed=False,
        version=context.assignment.version + 1,
    )


def _mutate_reopen(context: TransitionContext, target_state: WorkflowState) -> AssignmentSnapshot:
    return replace(
        context.assignment,
        workflow_state=target_state,
        workspace_state=WorkspaceState.PENDING,
        sync_state=SyncState.NONE,
        is_closed=False,
        version=context.assignment.version + 1,
    )


def _mutate_cancel(context: TransitionContext, target_state: WorkflowState) -> AssignmentSnapshot:
    return replace(
        context.assignment,
        workflow_state=target_state,
        workspace_state=WorkspaceState.ARCHIVED,
        sync_state=SyncState.NONE,
        is_closed=True,
        version=context.assignment.version + 1,
    )


transition_specs: dict[WorkflowEvent, TransitionSpec] = {
    WorkflowEvent.ASSIGN: TransitionSpec(
        event=WorkflowEvent.ASSIGN,
        from_states=(WorkflowState.SIN_ASIGNAR,),
        allowed_roles=(
            WorkflowRole.ADMINISTRADOR,
            WorkflowRole.COORDINADOR,
            WorkflowRole.ASIGNADOR,
        ),
        target_state=WorkflowState.EN_CAMPO,
        preconditions=(_ensure_target_user_present,),
        audit_events=("assignment.created", "assignment.assigned"),
        outbox_events=("BUILD_WORKSPACE",),
        precondition_hooks=("validate_target_user",),
        post_transition_events=("assignment.workflow.changed",),
        assignment_mutator=_mutate_assign,
    ),
    WorkflowEvent.START_FIELDWORK: TransitionSpec(
        event=WorkflowEvent.START_FIELDWORK,
        from_states=(WorkflowState.EN_CAMPO,),
        allowed_roles=(WorkflowRole.RECONOCEDOR,),
        target_state=WorkflowState.EN_CAMPO,
        owner_required=True,
        preconditions=(_ensure_workspace_ready,),
        audit_events=("assignment.fieldwork.started",),
        precondition_hooks=("workspace_ready", "owner_check"),
        assignment_mutator=_mutate_start_fieldwork,
    ),
    WorkflowEvent.SUBMIT_FOR_QA: TransitionSpec(
        event=WorkflowEvent.SUBMIT_FOR_QA,
        from_states=(WorkflowState.EN_CAMPO,),
        allowed_roles=(WorkflowRole.RECONOCEDOR,),
        target_state=WorkflowState.CONTROL_CALIDAD,
        owner_required=True,
        preconditions=(_ensure_workspace_ready,),
        audit_events=("assignment.submitted_for_qa",),
        precondition_hooks=("workspace_ready", "owner_check"),
        post_transition_events=("assignment.workflow.changed",),
        assignment_mutator=_mutate_submit_for_qa,
    ),
    WorkflowEvent.RETURN_TO_FIELD: TransitionSpec(
        event=WorkflowEvent.RETURN_TO_FIELD,
        from_states=(WorkflowState.CONTROL_CALIDAD,),
        allowed_roles=(
            WorkflowRole.ADMINISTRADOR,
            WorkflowRole.LIDER,
            WorkflowRole.COORDINADOR,
        ),
        target_state=WorkflowState.DEVUELTO,
        audit_events=("assignment.returned_to_field",),
        post_transition_events=("assignment.workflow.changed",),
        assignment_mutator=_mutate_return_to_field,
    ),
    WorkflowEvent.RESUBMIT_FROM_RETURN: TransitionSpec(
        event=WorkflowEvent.RESUBMIT_FROM_RETURN,
        from_states=(WorkflowState.DEVUELTO,),
        allowed_roles=(WorkflowRole.RECONOCEDOR,),
        target_state=WorkflowState.EN_CAMPO,
        owner_required=True,
        preconditions=(_ensure_workspace_ready,),
        audit_events=("assignment.resubmitted_from_return",),
        precondition_hooks=("workspace_ready", "owner_check"),
        post_transition_events=("assignment.workflow.changed",),
        assignment_mutator=_mutate_start_fieldwork,
    ),
    WorkflowEvent.APPROVE: TransitionSpec(
        event=WorkflowEvent.APPROVE,
        from_states=(WorkflowState.CONTROL_CALIDAD,),
        allowed_roles=(
            WorkflowRole.ADMINISTRADOR,
            WorkflowRole.LIDER,
            WorkflowRole.COORDINADOR,
        ),
        target_state=WorkflowState.APROBACION,
        preconditions=(_ensure_workspace_ready,),
        audit_events=("assignment.approved",),
        precondition_hooks=("workspace_ready",),
        post_transition_events=("assignment.workflow.changed",),
        assignment_mutator=_mutate_approve,
    ),
    WorkflowEvent.START_SYNC: TransitionSpec(
        event=WorkflowEvent.START_SYNC,
        from_states=(WorkflowState.APROBACION,),
        allowed_roles=(WorkflowRole.ADMINISTRADOR, WorkflowRole.COORDINADOR),
        target_state=WorkflowState.SINCRONIZACION,
        preconditions=(_ensure_workspace_ready, _ensure_retorno_validated),
        audit_events=("assignment.sync.started",),
        outbox_events=("SYNC_ASSIGNMENT",),
        precondition_hooks=("workspace_ready", "retorno_validated"),
        post_transition_events=("assignment.workflow.changed",),
        assignment_mutator=_mutate_start_sync,
    ),
    WorkflowEvent.MARK_SYNCED: TransitionSpec(
        event=WorkflowEvent.MARK_SYNCED,
        from_states=(WorkflowState.SINCRONIZACION,),
        allowed_roles=(WorkflowRole.ADMINISTRADOR, WorkflowRole.COORDINADOR),
        target_state=WorkflowState.SINCRONIZADO,
        allow_when_closed=True,
        block_when_sync_running=False,
        preconditions=(_ensure_sync_started,),
        audit_events=("assignment.sync.succeeded",),
        post_transition_events=("assignment.workflow.changed", "assignment.closed"),
        assignment_mutator=_mutate_mark_synced,
    ),
    WorkflowEvent.REOPEN: TransitionSpec(
        event=WorkflowEvent.REOPEN,
        from_states=(
            WorkflowState.SINCRONIZADO,
            WorkflowState.APROBACION,
            WorkflowState.DEVUELTO,
        ),
        allowed_roles=(
            WorkflowRole.ADMINISTRADOR,
            WorkflowRole.LIDER,
            WorkflowRole.COORDINADOR,
        ),
        target_state_resolver=_resolve_reopen_state,
        allow_when_closed=True,
        block_when_sync_running=False,
        preconditions=(_ensure_reopen_reason_present,),
        audit_events=("assignment.reopened",),
        outbox_events=("BUILD_WORKSPACE",),
        precondition_hooks=("reopen_reason_required",),
        post_transition_events=("assignment.workflow.changed",),
        assignment_mutator=_mutate_reopen,
    ),
    WorkflowEvent.REASSIGN: TransitionSpec(
        event=WorkflowEvent.REASSIGN,
        from_states=(
            WorkflowState.EN_CAMPO,
            WorkflowState.DEVUELTO,
            WorkflowState.CONTROL_CALIDAD,
            WorkflowState.APROBACION,
        ),
        allowed_roles=(
            WorkflowRole.ADMINISTRADOR,
            WorkflowRole.COORDINADOR,
            WorkflowRole.ASIGNADOR,
        ),
        target_state_resolver=_resolve_same_state,
        preconditions=(_ensure_target_user_present,),
        audit_events=("assignment.reassigned",),
        outbox_events=("BUILD_WORKSPACE",),
        precondition_hooks=("validate_target_user",),
        post_transition_events=("assignment.workflow.changed",),
        assignment_mutator=_mutate_reassign,
    ),
    WorkflowEvent.CANCEL_ASSIGNMENT: TransitionSpec(
        event=WorkflowEvent.CANCEL_ASSIGNMENT,
        from_states=(
            WorkflowState.SIN_ASIGNAR,
            WorkflowState.EN_CAMPO,
            WorkflowState.DEVUELTO,
            WorkflowState.CONTROL_CALIDAD,
            WorkflowState.APROBACION,
        ),
        allowed_roles=(WorkflowRole.ADMINISTRADOR, WorkflowRole.COORDINADOR),
        target_state_resolver=_resolve_same_state,
        block_when_sync_running=False,
        audit_events=("assignment.cancelled",),
        outbox_events=("CLEANUP_WORKSPACE",),
        post_transition_events=("assignment.closed",),
        assignment_mutator=_mutate_cancel,
    ),
}

allowed_transitions: dict[WorkflowState, dict[WorkflowEvent, WorkflowState | None]] = {}
for event, spec in transition_specs.items():
    for state in spec.from_states:
        allowed_transitions.setdefault(state, {})[event] = spec.target_state

allowed_roles: dict[WorkflowEvent, tuple[WorkflowRole, ...]] = {
    event: spec.allowed_roles for event, spec in transition_specs.items()
}


def _build_context(
    assignment: AssignmentSnapshot,
    actor: ActorContext,
    event: WorkflowEvent,
    metadata: dict[str, object] | None = None,
) -> TransitionContext:
    return TransitionContext(
        assignment=assignment,
        actor=actor,
        event=event,
        metadata=metadata or {},
    )


def _resolve_target_state(spec: TransitionSpec, context: TransitionContext) -> WorkflowState:
    if spec.target_state is not None:
        return spec.target_state
    if spec.target_state_resolver is not None:
        return spec.target_state_resolver(context)
    raise WorkflowPreconditionError(f"El evento {spec.event.value} no tiene target_state configurado.")


def validate_transition(
    assignment: AssignmentSnapshot,
    actor: ActorContext,
    event: WorkflowEvent,
    *,
    metadata: dict[str, object] | None = None,
) -> None:
    spec = transition_specs[event]
    context = _build_context(assignment, actor, event, metadata)

    if assignment.tenant_code != actor.tenant_code:
        raise TenantMismatchError("El actor no puede operar una asignacion de otro tenant.")

    if actor.role not in spec.allowed_roles:
        raise RoleNotAllowedError(
            f"El rol {actor.role.value} no puede ejecutar {event.value}."
        )

    if assignment.is_closed and not spec.allow_when_closed:
        raise AssignmentClosedError("La asignacion esta cerrada para nuevas transiciones.")

    if assignment.sync_state == SyncState.RUNNING and spec.block_when_sync_running:
        raise SyncInProgressError("La asignacion tiene una sincronizacion en ejecucion.")

    if assignment.workflow_state not in spec.from_states:
        raise InvalidTransitionError(
            f"No se puede ejecutar {event.value} desde {assignment.workflow_state.value}."
        )

    if spec.owner_required and assignment.assigned_user_id and actor.user_id != assignment.assigned_user_id:
        raise OwnershipValidationError("La operacion requiere ser el propietario de la asignacion.")

    for precondition in spec.preconditions:
        precondition(context)


def can_transition(
    assignment: AssignmentSnapshot,
    actor: ActorContext,
    event: WorkflowEvent,
    *,
    metadata: dict[str, object] | None = None,
) -> bool:
    try:
        validate_transition(assignment, actor, event, metadata=metadata)
    except WorkflowError:
        return False
    return True


def apply_transition(
    assignment: AssignmentSnapshot,
    actor: ActorContext,
    event: WorkflowEvent,
    *,
    metadata: dict[str, object] | None = None,
) -> TransitionResult:
    validate_transition(assignment, actor, event, metadata=metadata)
    spec = transition_specs[event]
    context = _build_context(assignment, actor, event, metadata)
    target_state = _resolve_target_state(spec, context)
    mutator = spec.assignment_mutator
    if mutator is None:
        raise WorkflowPreconditionError(f"El evento {event.value} no tiene mutador configurado.")

    updated_assignment = mutator(context, target_state)

    return TransitionResult(
        event=event,
        from_state=assignment.workflow_state,
        to_state=target_state,
        assignment=updated_assignment,
        audit_events=spec.audit_events,
        outbox_events=spec.outbox_events,
        precondition_hooks=spec.precondition_hooks,
        post_transition_events=spec.post_transition_events,
        metadata=metadata or {},
    )

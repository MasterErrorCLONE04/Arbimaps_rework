from typing import Callable, Mapping, Optional

from workflow.enums import WorkflowEvent
from workflow.models import ActorContext
from workflow.ports import AbstractUnitOfWork
from workflow.service import AssignmentWorkflowService, WorkflowServiceResult


class AssignmentCommandService:
    """
    Orquesta casos de uso para Assignment Workflow Service y encapsula la
    mutación, el registro de auditoría y los mensajes Outbox en una transacción.
    """

    def __init__(
        self,
        workflow_service: AssignmentWorkflowService,
        uow_factory: Callable[[], AbstractUnitOfWork],
    ):
        self.workflow_service = workflow_service
        self.uow_factory = uow_factory

    def execute_transition(
        self,
        assignment_id: str,
        actor: ActorContext,
        event: WorkflowEvent,
        *,
        metadata: Optional[Mapping[str, object]] = None,
    ) -> WorkflowServiceResult:
        with self.uow_factory() as uow:
            assignment = uow.assignments.get(actor.tenant_code, assignment_id)
            if not assignment:
                raise ValueError(f"Asignación {assignment_id} no encontrada en tenant {actor.tenant_code}.")

            result = self.workflow_service.apply_event(assignment, actor, event, metadata=metadata)
            
            uow.assignments.save(result.transition.assignment)
            uow.transitions.append(result.transition, result.audit_context, result.occurred_at)
            for audit_event in result.audit_events:
                uow.audit.append(audit_event)
            for outbox_msg in result.outbox_messages:
                uow.outbox.append(outbox_msg)
            
            return result
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from routers.auth import get_current_user_from_session
from tenants.context import TenantContext
from tenants.dependencies import get_tenant_context_from_session
from workflow.command_service import AssignmentCommandService
from workflow.enums import WorkflowEvent, WorkflowRole
from workflow.exceptions import WorkflowError
from workflow.models import ActorContext
from workflow.postgres_uow import PostgresUnitOfWork
from workflow.service import AssignmentWorkflowService

router = APIRouter(
    prefix="/api/workflow/asignaciones",
    tags=["Workflow Asignaciones"]
)


class AssignPayload(BaseModel):
    target_user_id: str


def get_command_service(
    request: Request,
    tenant: TenantContext = Depends(get_tenant_context_from_session)
) -> AssignmentCommandService:
    manager = request.app.state.tenant_connection_manager
    workflow_service = AssignmentWorkflowService()

    def uow_factory():
        return PostgresUnitOfWork(manager, tenant)

    return AssignmentCommandService(workflow_service=workflow_service, uow_factory=uow_factory)


@router.post("/{assignment_id}/assign")
def assign_assignment(
    assignment_id: str,
    payload: AssignPayload,
    tenant: TenantContext = Depends(get_tenant_context_from_session),
    user: dict = Depends(get_current_user_from_session),
    command_service: AssignmentCommandService = Depends(get_command_service)
):
    actor = ActorContext(
        tenant_code=tenant.municipality_code,
        user_id=str(user["id_global"]),
        role=WorkflowRole.parse(user["role_code"])
    )

    try:
        result = command_service.execute_transition(
            assignment_id=assignment_id,
            actor=actor,
            event=WorkflowEvent.ASSIGN,
            metadata={"target_user_id": payload.target_user_id}
        )
        return {
            "assignment_id": result.transition.assignment.assignment_id,
            "workflow_state": result.transition.assignment.workflow_state.value,
            "assigned_user_id": result.transition.assignment.assigned_user_id,
            "version": result.transition.assignment.version
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except WorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{assignment_id}/start-fieldwork")
def start_fieldwork(
    assignment_id: str,
    tenant: TenantContext = Depends(get_tenant_context_from_session),
    user: dict = Depends(get_current_user_from_session),
    command_service: AssignmentCommandService = Depends(get_command_service)
):
    actor = ActorContext(
        tenant_code=tenant.municipality_code,
        user_id=str(user["id_global"]),
        role=WorkflowRole.parse(user["role_code"])
    )

    try:
        result = command_service.execute_transition(
            assignment_id=assignment_id,
            actor=actor,
            event=WorkflowEvent.START_FIELDWORK
        )
        return {
            "assignment_id": result.transition.assignment.assignment_id,
            "workflow_state": result.transition.assignment.workflow_state.value,
            "assigned_user_id": result.transition.assignment.assigned_user_id,
            "version": result.transition.assignment.version
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except WorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
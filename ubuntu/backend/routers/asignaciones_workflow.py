from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import logging

from psycopg2.extras import RealDictCursor
from tenants import app_table, get_tenant_db_connection
from repositories import asignaciones_repo
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
logger = logging.getLogger(__name__)


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
    conn = Depends(get_tenant_db_connection),
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

        try:
            users_table = app_table(tenant, "users")
            asignacion_table = app_table(tenant, "asignacion")
            
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Fetch destination user info
                cur.execute(
                    f"SELECT id_global, username, rol FROM {users_table} WHERE id_global = %s",
                    (int(payload.target_user_id),)
                )
                target_user = cur.fetchone()
                
                # 2. Fetch the assignment title
                cur.execute(
                    f"SELECT titulo FROM {asignacion_table} WHERE id = %s",
                    (int(assignment_id),)
                )
                asig_row = cur.fetchone()
                asig_title = asig_row["titulo"] if asig_row else f"Trabajo #{assignment_id}"
            
            if target_user:
                asignaciones_repo.safe_crear_notificacion(
                    conn,
                    tenant=tenant,
                    id_asignacion=int(assignment_id),
                    id_usuario_destino=int(payload.target_user_id),
                    id_usuario_origen=int(user["id_global"]),
                    rol_origen=user.get("role_code") or user.get("role") or "coordinador",
                    rol_destino=target_user.get("rol") or "digitalizador",
                    tipo="asignacion",
                    titulo="Nueva asignación de trabajo recibida",
                    mensaje=f"Se te asignó el trabajo: {asig_title}",
                    url_destino=f"/panel/asignaciones/detalle?id={assignment_id}#asig-open",
                    prioridad="alta",
                    metadata={
                        "assignment_id": int(assignment_id),
                    }
                )
                conn.commit()
        except Exception as notif_err:
            logger.error(f"Fallo no crítico al generar notificación de workflow: {notif_err}")
            # Continuamos aunque falle la notificacion
            
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
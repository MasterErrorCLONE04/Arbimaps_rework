from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import logging

from psycopg2.extras import RealDictCursor
from tenants import app_table, get_tenant_db_connection
from repositories import asignaciones_repo
from routers.auth import get_current_user_from_session, get_user_role, normalize_role, check_admin_soporte_isolation
from tenants.context import TenantContext
from tenants.dependencies import get_tenant_context_from_session
from workflow.command_service import AssignmentCommandService
from workflow.enums import WorkflowEvent, WorkflowRole
from workflow.exceptions import WorkflowError
from workflow.models import ActorContext
from workflow.postgres_uow import PostgresUnitOfWork
from workflow.service import AssignmentWorkflowService

def verify_assignment_isolation(
    assignment_id: str,
    conn = Depends(get_tenant_db_connection),
    tenant: TenantContext = Depends(get_tenant_context_from_session),
    user: dict = Depends(get_current_user_from_session),
):
    try:
        asig_id = int(assignment_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de asignacion invalido")
    check_admin_soporte_isolation(conn, tenant, user, asig_id)

router = APIRouter(
    prefix="/api/workflow/asignaciones",
    tags=["Workflow Asignaciones"],
    dependencies=[Depends(verify_assignment_isolation)]
)
logger = logging.getLogger(__name__)


from typing import Optional

class WorkflowTransitionPayload(BaseModel):
    comentario: Optional[str] = None
    enlace: Optional[str] = None


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
                asignaciones_repo.safe_log_event(
                    conn,
                    tenant,
                    int(assignment_id),
                    "ESTADO_CAMBIADO",
                    f"Trabajo asignado al reconocedor: {target_user['username']}. Estado: {result.transition.assignment.workflow_state.value}.",
                    user.get("username")
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
            event=WorkflowEvent.START_FIELDWORK
        )
        asignaciones_repo.update_asignacion_fields(
            conn,
            tenant,
            int(assignment_id),
            estado="EN_CAMPO"
        )
        asignaciones_repo.safe_log_event(
            conn,
            tenant,
            int(assignment_id),
            "ESTADO_CAMBIADO",
            "Inicio de trabajo de campo. Estado: EN_CAMPO.",
            user.get("username")
        )
        conn.commit()
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


class SubmitQAPayload(BaseModel):
    enlace_control_calidad: str
    comentario: Optional[str] = None


@router.post("/{assignment_id}/submit-for-qa")
def submit_for_qa(
    assignment_id: str,
    payload: SubmitQAPayload,
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
            event=WorkflowEvent.SUBMIT_FOR_QA,
            metadata={"enlace_control_calidad": payload.enlace_control_calidad}
        )

        asignacion_table = app_table(tenant, "asignacion")
        users_table = app_table(tenant, "users")

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT coordinador_asignado_id, creado_por_id, creado_por, titulo, estado FROM {asignacion_table} WHERE id = %s",
                (int(assignment_id),)
            )
            asig_row = cur.fetchone()

        if asig_row:
            coordinador_id = asig_row["coordinador_asignado_id"] or asig_row["creado_por_id"]
            asig_title = asig_row["titulo"] or f"Trabajo #{assignment_id}"
            
            asignaciones_repo.update_asignacion_fields(
                conn,
                tenant,
                int(assignment_id),
                estado="CONTROL_CALIDAD_1",
                enlace_control_calidad=payload.enlace_control_calidad,
                enlace_devolucion=""
            )

            if payload.comentario:
                asignaciones_repo.insert_asignacion_comentario(
                    conn,
                    tenant,
                    asignacion_id=int(assignment_id),
                    usuario_id=int(user["id_global"]),
                    usuario=user.get("username"),
                    rol=user.get("role_code") or user.get("role") or "reconocedor",
                    comentario=payload.comentario,
                    estado_origen=asig_row["estado"],
                    estado_destino="CONTROL_CALIDAD_1"
                )

            if coordinador_id:
                try:
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute(
                            f"SELECT rol FROM {users_table} WHERE id_global = %s",
                            (int(coordinador_id),)
                        )
                        coord_user = cur.fetchone()
                    rol_dest = coord_user.get("rol") if coord_user else "coordinador"
                    
                    asignaciones_repo.safe_crear_notificacion(
                        conn,
                        tenant=tenant,
                        id_asignacion=int(assignment_id),
                        id_usuario_destino=int(coordinador_id),
                        id_usuario_origen=int(user["id_global"]),
                        rol_origen="reconocedor",
                        rol_destino=rol_dest,
                        tipo="control_calidad",
                        titulo="Trabajo enviado a control de calidad",
                        mensaje=f"El reconocedor {user.get('username')} ha enviado el trabajo '{asig_title}' para revisión. Enlace: {payload.enlace_control_calidad}",
                        url_destino=f"/panel/asignaciones/detalle?id={assignment_id}#asig-open",
                        prioridad="alta",
                        metadata={
                            "assignment_id": int(assignment_id),
                            "enlace_control_calidad": payload.enlace_control_calidad
                        }
                    )
                except Exception as notif_err:
                    logger.error(f"Fallo al generar notificacion de workflow: {notif_err}")

            asignaciones_repo.safe_log_event(
                conn,
                tenant,
                int(assignment_id),
                "ESTADO_CAMBIADO",
                f"Enviado a Control de Calidad. Estado: CONTROL_CALIDAD_1. Enlace: {payload.enlace_control_calidad}",
                user.get("username")
            )
        conn.commit()

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


@router.post("/{assignment_id}/return-to-field")
def return_to_field(
    assignment_id: str,
    payload: Optional[WorkflowTransitionPayload] = None,
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
            event=WorkflowEvent.RETURN_TO_FIELD
        )

        asignacion_table = app_table(tenant, "asignacion")
        users_table = app_table(tenant, "users")

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT usuario_asignado_id, usuario_asignado, titulo, estado FROM {asignacion_table} WHERE id = %s",
                (int(assignment_id),)
            )
            asig_row = cur.fetchone()

        if asig_row:
            reconocedor_id = asig_row["usuario_asignado_id"]
            asig_title = asig_row["titulo"] or f"Trabajo #{assignment_id}"

            # Update legacy database fields
            asignaciones_repo.update_asignacion_fields(
                conn,
                tenant,
                int(assignment_id),
                estado="DEVUELTO_CAMPO",
                enlace_control_calidad="",  # Clear evidence link so they can upload a new one
                enlace_devolucion=payload.enlace if payload else None
            )

            if payload and payload.comentario:
                asignaciones_repo.insert_asignacion_comentario(
                    conn,
                    tenant,
                    asignacion_id=int(assignment_id),
                    usuario_id=int(user["id_global"]),
                    usuario=user.get("username"),
                    rol=user.get("role_code") or user.get("role") or "coordinador",
                    comentario=payload.comentario,
                    estado_origen=asig_row["estado"],
                    estado_destino="DEVUELTO_CAMPO",
                    enlace=payload.enlace if payload else None
                )

            if reconocedor_id:
                try:
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute(
                            f"SELECT rol FROM {users_table} WHERE id_global = %s",
                            (int(reconocedor_id),)
                        )
                        rec_user = cur.fetchone()
                    rol_dest = rec_user.get("rol") if rec_user else "reconocedor"

                    asignaciones_repo.safe_crear_notificacion(
                        conn,
                        tenant=tenant,
                        id_asignacion=int(assignment_id),
                        id_usuario_destino=int(reconocedor_id),
                        id_usuario_origen=int(user["id_global"]),
                        rol_origen="coordinador",
                        rol_destino=rol_dest,
                        tipo="asignacion",
                        titulo="Asignación devuelta a campo",
                        mensaje=f"El coordinador {user.get('username')} ha devuelto el trabajo '{asig_title}' a campo para corregir.",
                        url_destino=f"/panel/asignaciones/detalle?id={assignment_id}#asig-open",
                        prioridad="alta",
                        metadata={
                            "assignment_id": int(assignment_id)
                        }
                    )
                except Exception as notif_err:
                    logger.error(f"Fallo al generar notificacion de workflow para reconocedor: {notif_err}")

            asignaciones_repo.safe_log_event(
                conn,
                tenant,
                int(assignment_id),
                "ESTADO_CAMBIADO",
                f"Trabajo devuelto a campo. Estado: DEVUELTO_CAMPO.",
                user.get("username")
            )
        conn.commit()

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


@router.post("/{assignment_id}/approve")
def approve_assignment(
    assignment_id: str,
    payload: Optional[WorkflowTransitionPayload] = None,
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
            event=WorkflowEvent.APPROVE
        )

        asignacion_table = app_table(tenant, "asignacion")
        users_table = app_table(tenant, "users")
        roles_table = app_table(tenant, "roles")
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT enlace_control_calidad, titulo, creado_por_id, estado FROM {asignacion_table} WHERE id = %s",
                (int(assignment_id),)
            )
            asig_row = cur.fetchone()

        if asig_row:
            enlace = asig_row["enlace_control_calidad"] or ""
            asig_title = asig_row["titulo"] or f"Trabajo #{assignment_id}"
            creator_id = asig_row["creado_por_id"]

            # Update legacy database fields
            asignaciones_repo.update_asignacion_fields(
                conn,
                tenant,
                int(assignment_id),
                estado="GENERACION_XTF_CAMPO"
            )

            if payload and payload.comentario:
                asignaciones_repo.insert_asignacion_comentario(
                    conn,
                    tenant,
                    asignacion_id=int(assignment_id),
                    usuario_id=int(user["id_global"]),
                    usuario=user.get("username"),
                    rol=user.get("role_code") or user.get("role") or "coordinador",
                    comentario=payload.comentario,
                    estado_origen=asig_row["estado"],
                    estado_destino="GENERACION_XTF_CAMPO"
                )

            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        f"""
                        SELECT u.id_global, u.username
                        FROM {users_table} u
                        JOIN {roles_table} r ON r.t_id = u.rol_id
                        WHERE r.itf_code = 'consolidador' AND u.activo = TRUE
                        """
                    )
                    support_users = cur.fetchall()

                notified_user_ids = {int(sup["id_global"]) for sup in support_users}

                for sup in support_users:
                    asignaciones_repo.safe_crear_notificacion(
                        conn,
                        tenant=tenant,
                        id_asignacion=int(assignment_id),
                        id_usuario_destino=int(sup["id_global"]),
                        id_usuario_origen=int(user["id_global"]),
                        rol_origen="coordinador",
                        rol_destino="consolidador",
                        tipo="soporte",
                        titulo="Asignación lista para generación XTF",
                        mensaje=f"El coordinador {user.get('username')} aprobó el trabajo '{asig_title}'. Enlace de evidencia: {enlace}",
                        url_destino=f"/panel/asignaciones/detalle?id={assignment_id}#asig-open",
                        prioridad="alta",
                        metadata={
                            "assignment_id": int(assignment_id),
                            "enlace_control_calidad": enlace
                        }
                    )

                if creator_id and int(creator_id) not in notified_user_ids:
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute(
                            f"SELECT rol FROM {users_table} WHERE id_global = %s AND activo = TRUE",
                            (int(creator_id),)
                        )
                        creator_row = cur.fetchone()
                    if creator_row and creator_row.get("rol") == "soporte":
                        asignaciones_repo.safe_crear_notificacion(
                            conn,
                            tenant=tenant,
                            id_asignacion=int(assignment_id),
                            id_usuario_destino=int(creator_id),
                            id_usuario_origen=int(user["id_global"]),
                            rol_origen="coordinador",
                            rol_destino="soporte",
                            tipo="soporte",
                            titulo="Asignación lista para generación XTF",
                            mensaje=f"El coordinador {user.get('username')} aprobó el trabajo '{asig_title}'. Enlace de evidencia: {enlace}",
                            url_destino=f"/panel/asignaciones/detalle?id={assignment_id}#asig-open",
                            prioridad="alta",
                            metadata={
                                "assignment_id": int(assignment_id),
                                "enlace_control_calidad": enlace
                            }
                        )
            except Exception as support_err:
                logger.error(f"Fallo al notificar a los consolidadores/soporte: {support_err}")

            asignaciones_repo.safe_log_event(
                conn,
                tenant,
                int(assignment_id),
                "ESTADO_CAMBIADO",
                f"Trabajo aprobado. Estado: GENERACION_XTF_CAMPO.",
                user.get("username")
            )
        conn.commit()

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


class SubmitSoporteLinkPayload(BaseModel):
    enlace_soporte: str
    comentario: Optional[str] = None


@router.post("/{assignment_id}/submit-soporte-link")
def submit_soporte_link(
    assignment_id: str,
    payload: SubmitSoporteLinkPayload,
    tenant: TenantContext = Depends(get_tenant_context_from_session),
    user: dict = Depends(get_current_user_from_session),
    conn = Depends(get_tenant_db_connection),
):
    role = normalize_role(get_user_role(user))
    if role not in {"soporte", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="Solo usuarios con rol de soporte o admin pueden enviar este enlace."
        )

    asignacion_table = app_table(tenant, "asignacion")
    users_table = app_table(tenant, "users")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT coordinador_asignado_id, creado_por_id, creado_por, estado, titulo, enlace_soporte
            FROM {asignacion_table} 
            WHERE id = %s
            """,
            (int(assignment_id),)
        )
        asig_row = cur.fetchone()

    if not asig_row:
        raise HTTPException(status_code=404, detail="Asignación no encontrada.")

    if asig_row["estado"] != "GENERACION_XTF_CAMPO":
        raise HTTPException(
            status_code=400,
            detail="La asignación debe estar en estado GENERACION_XTF_CAMPO para enviar el enlace."
        )

    if asig_row["enlace_soporte"]:
        raise HTTPException(
            status_code=400,
            detail="El enlace de soporte ya ha sido enviado para esta asignación."
        )

    asig_title = asig_row["titulo"] or f"Trabajo #{assignment_id}"
    coordinador_id = asig_row["coordinador_asignado_id"] or asig_row["creado_por_id"]

    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {asignacion_table} SET enlace_soporte = %s, enlace_devolucion = NULL WHERE id = %s",
            (payload.enlace_soporte, int(assignment_id))
        )
        if payload.comentario:
            asignaciones_repo.insert_asignacion_comentario(
                conn,
                tenant,
                asignacion_id=int(assignment_id),
                usuario_id=int(user["id_global"]),
                usuario=user.get("username"),
                rol=role,
                comentario=payload.comentario,
                estado_origen=asig_row["estado"],
                estado_destino=asig_row["estado"]
            )

    if coordinador_id:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"SELECT rol FROM {users_table} WHERE id_global = %s AND activo = TRUE",
                    (int(coordinador_id),)
                )
                coord_row = cur.fetchone()
            rol_dest = coord_row.get("rol") if coord_row else "coordinador"
            
            asignaciones_repo.safe_crear_notificacion(
                conn,
                tenant=tenant,
                id_asignacion=int(assignment_id),
                id_usuario_destino=int(coordinador_id),
                id_usuario_origen=int(user["id_global"]),
                rol_origen="soporte",
                rol_destino=rol_dest,
                tipo="asignacion",
                titulo="Enlace de soporte disponible",
                mensaje=f"El soporte {user.get('username')} ha enviado el enlace para el trabajo '{asig_title}'.",
                url_destino=f"/panel/asignaciones/detalle?id={assignment_id}#asig-open",
                prioridad="alta",
                metadata={
                    "assignment_id": int(assignment_id),
                    "enlace_soporte": payload.enlace_soporte
                }
            )
        except Exception as notif_err:
            logger.error(f"Fallo al notificar al coordinador: {notif_err}")

    asignaciones_repo.safe_log_event(
        conn,
        tenant,
        int(assignment_id),
        "ESTADO_CAMBIADO",
        f"Enlace de soporte enviado: {payload.enlace_soporte}.",
        user.get("username")
    )
    conn.commit()
    return {"status": "ok", "enlace_soporte": payload.enlace_soporte}


@router.post("/{assignment_id}/return-to-support")
def return_to_support(
    assignment_id: str,
    payload: Optional[WorkflowTransitionPayload] = None,
    tenant: TenantContext = Depends(get_tenant_context_from_session),
    user: dict = Depends(get_current_user_from_session),
    conn = Depends(get_tenant_db_connection),
):
    role = normalize_role(get_user_role(user))
    if role not in {"coordinador", "admin", "lider_reconocimiento"}:
        raise HTTPException(
            status_code=403,
            detail="Solo usuarios con rol de coordinador, lider o admin pueden devolver al soporte."
        )

    asignacion_table = app_table(tenant, "asignacion")
    users_table = app_table(tenant, "users")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"SELECT creado_por_id, creado_por, estado, titulo FROM {asignacion_table} WHERE id = %s",
            (int(assignment_id),)
        )
        asig_row = cur.fetchone()

    if not asig_row:
        raise HTTPException(status_code=404, detail="Asignación no encontrada.")

    # Reset enlace_soporte in database
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {asignacion_table} SET enlace_soporte = NULL, enlace_devolucion = %s WHERE id = %s",
            (payload.enlace if payload else None, int(assignment_id))
        )
        if payload and payload.comentario:
            asignaciones_repo.insert_asignacion_comentario(
                conn,
                tenant,
                asignacion_id=int(assignment_id),
                usuario_id=int(user["id_global"]),
                usuario=user.get("username"),
                rol=role,
                comentario=payload.comentario,
                estado_origen=asig_row["estado"],
                estado_destino=asig_row["estado"],
                enlace=payload.enlace if payload else None
            )

    # Notify creator/support user
    creator_id = asig_row["creado_por_id"]
    asig_title = asig_row["titulo"] or f"Trabajo #{assignment_id}"
    if creator_id:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"SELECT rol FROM {users_table} WHERE id_global = %s AND activo = TRUE",
                    (int(creator_id),)
                )
                creator_row = cur.fetchone()
            rol_dest = creator_row.get("rol") if creator_row else "soporte"
            
            asignaciones_repo.safe_crear_notificacion(
                conn,
                tenant=tenant,
                id_asignacion=int(assignment_id),
                id_usuario_destino=int(creator_id),
                id_usuario_origen=int(user["id_global"]),
                rol_origen="coordinador",
                rol_destino=rol_dest,
                tipo="soporte",
                titulo="Trabajo devuelto por Coordinador",
                mensaje=f"El coordinador {user.get('username')} ha devuelto el trabajo '{asig_title}' para corrección de soporte.",
                url_destino=f"/panel/asignaciones/detalle?id={assignment_id}#asig-open",
                prioridad="alta",
                metadata={"assignment_id": int(assignment_id)}
            )
        except Exception as notif_err:
            logger.error(f"Fallo al notificar al creador/soporte: {notif_err}")

    asignaciones_repo.safe_log_event(
        conn,
        tenant,
        int(assignment_id),
        "ESTADO_CAMBIADO",
        "Trabajo devuelto a soporte.",
        user.get("username")
    )
    conn.commit()
    return {"status": "ok"}


class AssignDigitalizadorPayload(BaseModel):
    digitalizador_id: str
    comentario: Optional[str] = None


@router.post("/{assignment_id}/assign-digitalizador")
def assign_digitalizador(
    assignment_id: str,
    payload: AssignDigitalizadorPayload,
    tenant: TenantContext = Depends(get_tenant_context_from_session),
    user: dict = Depends(get_current_user_from_session),
    conn = Depends(get_tenant_db_connection),
    command_service: AssignmentCommandService = Depends(get_command_service)
):
    role = normalize_role(get_user_role(user))
    if role not in {"coordinador", "admin", "lider_reconocimiento"}:
        raise HTTPException(
            status_code=403,
            detail="Solo coordinadores, lideres o admins pueden asignar un digitalizador."
        )

    asignacion_table = app_table(tenant, "asignacion")
    users_table = app_table(tenant, "users")

    # Fetch digitalizador user first
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"SELECT username, first_name, last_name, rol FROM {users_table} WHERE id_global = %s AND activo = TRUE",
            (int(payload.digitalizador_id),)
        )
        dig_user = cur.fetchone()

    if not dig_user or normalize_role(dig_user.get("rol")) != "digitalizador":
        raise HTTPException(
            status_code=400,
            detail="El usuario seleccionado no existe o no tiene el rol de digitalizador."
        )

    # 1. Run REASSIGN transition in state machine
    actor = ActorContext(
        tenant_code=tenant.municipality_code,
        user_id=str(user["id_global"]),
        role=WorkflowRole.parse(user["role_code"])
    )

    try:
        result = command_service.execute_transition(
            assignment_id=assignment_id,
            actor=actor,
            event=WorkflowEvent.REASSIGN,
            metadata={"target_user_id": payload.digitalizador_id}
        )

        # 2. Update legacy assignment fields
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT titulo, usuario_asignado, usuario_asignado_id, estado FROM {asignacion_table} WHERE id = %s",
                (int(assignment_id),)
            )
            asig_row = cur.fetchone()
        asig_title = asig_row["titulo"] if asig_row else f"Trabajo #{assignment_id}"
        prev_user = asig_row["usuario_asignado"] if asig_row else None
        prev_user_id = asig_row["usuario_asignado_id"] if asig_row else None

        asignaciones_repo.update_asignacion_fields(
            conn,
            tenant,
            int(assignment_id),
            estado="EN_DIGITALIZACION",
        )
        
        # Also update the assigned user in the legacy asignacion table and preserve the recognizer
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {asignacion_table} 
                SET usuario_asignado = %s, 
                    usuario_asignado_id = %s, 
                    usuario_reconocedor = %s, 
                    usuario_reconocedor_id = %s 
                WHERE id = %s
                """,
                (dig_user["username"], int(payload.digitalizador_id), prev_user, prev_user_id, int(assignment_id))
            )
            if payload.comentario:
                asignaciones_repo.insert_asignacion_comentario(
                    conn,
                    tenant,
                    asignacion_id=int(assignment_id),
                    usuario_id=int(user["id_global"]),
                    usuario=user.get("username"),
                    rol=role,
                    comentario=payload.comentario,
                    estado_origen=asig_row["estado"],
                    estado_destino="EN_DIGITALIZACION"
                )

        # 3. Create notification for digitalizador
        try:
            asignaciones_repo.safe_crear_notificacion(
                conn,
                tenant=tenant,
                id_asignacion=int(assignment_id),
                id_usuario_destino=int(payload.digitalizador_id),
                id_usuario_origen=int(user["id_global"]),
                rol_origen="coordinador",
                rol_destino="digitalizador",
                tipo="asignacion",
                titulo="Nueva asignación de digitalización",
                mensaje=f"Se te asignó el trabajo: {asig_title} para digitalización.",
                url_destino=f"/panel/asignaciones/detalle?id={assignment_id}#asig-open",
                prioridad="alta",
                metadata={"assignment_id": int(assignment_id)}
            )
        except Exception as notif_err:
            logger.error(f"Fallo al notificar al digitalizador: {notif_err}")

        asignaciones_repo.safe_log_event(
            conn,
            tenant,
            int(assignment_id),
            "ESTADO_CAMBIADO",
            f"Trabajo asignado al digitalizador {dig_user['username']}. Estado: EN_DIGITALIZACION.",
            user.get("username")
        )
        conn.commit()
        return {
            "assignment_id": result.transition.assignment.assignment_id,
            "workflow_state": "EN_DIGITALIZACION",
            "assigned_user_id": payload.digitalizador_id
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except WorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{assignment_id}/continue-with-reconocedor")
def continue_with_reconocedor(
    assignment_id: str,
    payload: Optional[WorkflowTransitionPayload] = None,
    tenant: TenantContext = Depends(get_tenant_context_from_session),
    user: dict = Depends(get_current_user_from_session),
    conn = Depends(get_tenant_db_connection),
    command_service: AssignmentCommandService = Depends(get_command_service)
):
    role = normalize_role(get_user_role(user))
    if role not in {"coordinador", "admin", "lider_reconocimiento"}:
        raise HTTPException(
            status_code=403,
            detail="Solo coordinadores, lideres o admins pueden continuar con el reconocedor."
        )

    asignacion_table = app_table(tenant, "asignacion")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"SELECT usuario_asignado_id, usuario_asignado, titulo, estado FROM {asignacion_table} WHERE id = %s",
            (int(assignment_id),)
        )
        asig_row = cur.fetchone()

    if not asig_row:
        raise HTTPException(status_code=404, detail="Asignación no encontrada.")

    reconocedor_id = asig_row["usuario_asignado_id"]
    if not reconocedor_id:
        raise HTTPException(
            status_code=400,
            detail="No hay un reconocedor asignado a este trabajo para continuar."
        )

    actor = ActorContext(
        tenant_code=tenant.municipality_code,
        user_id=str(user["id_global"]),
        role=WorkflowRole.parse(user["role_code"])
    )

    try:
        # 1. Run REASSIGN transition in state machine to stay in EN_CAMPO (internally mapped)
        result = command_service.execute_transition(
            assignment_id=assignment_id,
            actor=actor,
            event=WorkflowEvent.REASSIGN,
            metadata={"target_user_id": str(reconocedor_id)}
        )

        # 2. Update legacy assignment state and store recognizer
        asignaciones_repo.update_asignacion_fields(
            conn,
            tenant,
            int(assignment_id),
            estado="EN_DIGITALIZACION",
        )
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {asignacion_table} 
                SET usuario_reconocedor = %s, 
                    usuario_reconocedor_id = %s 
                WHERE id = %s
                """,
                (asig_row["usuario_asignado"], reconocedor_id, int(assignment_id))
            )
            if payload and payload.comentario:
                asignaciones_repo.insert_asignacion_comentario(
                    conn,
                    tenant,
                    asignacion_id=int(assignment_id),
                    usuario_id=int(user["id_global"]),
                    usuario=user.get("username"),
                    rol=role,
                    comentario=payload.comentario,
                    estado_origen=asig_row["estado"],
                    estado_destino="EN_DIGITALIZACION"
                )

        # 3. Create notification for reconocedor
        asig_title = asig_row["titulo"] or f"Trabajo #{assignment_id}"
        try:
            asignaciones_repo.safe_crear_notificacion(
                conn,
                tenant=tenant,
                id_asignacion=int(assignment_id),
                id_usuario_destino=int(reconocedor_id),
                id_usuario_origen=int(user["id_global"]),
                rol_origen="coordinador",
                rol_destino="reconocedor",
                tipo="asignacion",
                titulo="Continuar trabajo en digitalización",
                mensaje=f"Se te asignó continuar el trabajo: {asig_title} en digitalización.",
                url_destino=f"/panel/asignaciones/detalle?id={assignment_id}#asig-open",
                prioridad="alta",
                metadata={"assignment_id": int(assignment_id)}
            )
        except Exception as notif_err:
            logger.error(f"Fallo al notificar al reconocedor: {notif_err}")

        asignaciones_repo.safe_log_event(
            conn,
            tenant,
            int(assignment_id),
            "ESTADO_CAMBIADO",
            "Trabajo asignado para continuar con el reconocedor. Estado: EN_DIGITALIZACION.",
            user.get("username")
        )
        conn.commit()
        return {
            "assignment_id": result.transition.assignment.assignment_id,
            "workflow_state": "EN_DIGITALIZACION",
            "assigned_user_id": str(reconocedor_id)
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except WorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


class SubmitQA2Payload(BaseModel):
    enlace_digitalizacion: str
    comentario: Optional[str] = None


@router.post("/{assignment_id}/submit-for-qa2")
def submit_for_qa2(
    assignment_id: str,
    payload: SubmitQA2Payload,
    tenant: TenantContext = Depends(get_tenant_context_from_session),
    user: dict = Depends(get_current_user_from_session),
    conn = Depends(get_tenant_db_connection),
    command_service: AssignmentCommandService = Depends(get_command_service)
):
    role = normalize_role(get_user_role(user))
    if role not in {"digitalizador", "reconocedor", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="Solo el digitalizador, reconocedor asignado o admin pueden enviar a control de calidad 2."
        )

    asignacion_table = app_table(tenant, "asignacion")
    users_table = app_table(tenant, "users")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"SELECT usuario_asignado_id, coordinador_asignado_id, creado_por_id, titulo, estado FROM {asignacion_table} WHERE id = %s",
            (int(assignment_id),)
        )
        asig_row = cur.fetchone()

    if not asig_row:
        raise HTTPException(status_code=404, detail="Asignación no encontrada.")

    # Owner validation: must be the assigned user or admin
    if role != "admin" and int(asig_row["usuario_asignado_id"]) != int(user["id_global"]):
        raise HTTPException(status_code=403, detail="No eres el usuario asignado a este trabajo.")

    actor = ActorContext(
        tenant_code=tenant.municipality_code,
        user_id=str(user["id_global"]),
        role=WorkflowRole.parse(user["role_code"])
    )

    try:
        # 1. Run SUBMIT_FOR_QA transition on state machine
        result = command_service.execute_transition(
            assignment_id=assignment_id,
            actor=actor,
            event=WorkflowEvent.SUBMIT_FOR_QA,
            metadata={"enlace_control_calidad": payload.enlace_digitalizacion}
        )

        # 2. Update legacy fields
        asignaciones_repo.update_asignacion_fields(
            conn,
            tenant,
            int(assignment_id),
            estado="CONTROL_CALIDAD_2",
            enlace_digitalizacion=payload.enlace_digitalizacion,
            enlace_devolucion=""
        )

        if payload.comentario:
            asignaciones_repo.insert_asignacion_comentario(
                conn,
                tenant,
                asignacion_id=int(assignment_id),
                usuario_id=int(user["id_global"]),
                usuario=user.get("username"),
                rol=role,
                comentario=payload.comentario,
                estado_origen=asig_row["estado"],
                estado_destino="CONTROL_CALIDAD_2"
            )

        # 3. Create notification for coordinator
        coordinador_id = asig_row["coordinador_asignado_id"] or asig_row["creado_por_id"]
        asig_title = asig_row["titulo"] or f"Trabajo #{assignment_id}"
        if coordinador_id:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        f"SELECT rol FROM {users_table} WHERE id_global = %s",
                        (int(coordinador_id),)
                    )
                    coord_user = cur.fetchone()
                rol_dest = coord_user.get("rol") if coord_user else "coordinador"
                
                asignaciones_repo.safe_crear_notificacion(
                    conn,
                    tenant=tenant,
                    id_asignacion=int(assignment_id),
                    id_usuario_destino=int(coordinador_id),
                    id_usuario_origen=int(user["id_global"]),
                    rol_origen=role,
                    rol_destino=rol_dest,
                    tipo="asignacion",
                    titulo="Digitalización enviada a control de calidad 2",
                    mensaje=f"El usuario {user.get('username')} ha enviado el trabajo '{asig_title}' a control de calidad 2.",
                    url_destino=f"/panel/asignaciones/detalle?id={assignment_id}#asig-open",
                    prioridad="alta",
                    metadata={"assignment_id": int(assignment_id)}
                )
            except Exception as notif_err:
                logger.error(f"Fallo al notificar al coordinador: {notif_err}")

            asignaciones_repo.safe_log_event(
                conn,
                tenant,
                int(assignment_id),
                "ESTADO_CAMBIADO",
                f"Trabajo enviado a Control de Calidad 2. Estado: CONTROL_CALIDAD_2. Enlace: {payload.enlace_digitalizacion}",
                user.get("username")
            )
        conn.commit()
        return {
            "assignment_id": result.transition.assignment.assignment_id,
            "workflow_state": "CONTROL_CALIDAD_2",
            "assigned_user_id": result.transition.assignment.assigned_user_id
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except WorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{assignment_id}/return-to-digitalization")
def return_to_digitalization(
    assignment_id: str,
    payload: Optional[WorkflowTransitionPayload] = None,
    tenant: TenantContext = Depends(get_tenant_context_from_session),
    user: dict = Depends(get_current_user_from_session),
    conn = Depends(get_tenant_db_connection),
    command_service: AssignmentCommandService = Depends(get_command_service)
):
    role = normalize_role(get_user_role(user))
    if role not in {"coordinador", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="Solo coordinadores o admins pueden devolver a digitalización."
        )

    asignacion_table = app_table(tenant, "asignacion")
    users_table = app_table(tenant, "users")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"SELECT usuario_asignado_id, titulo, estado FROM {asignacion_table} WHERE id = %s",
            (int(assignment_id),)
        )
        asig_row = cur.fetchone()

    if not asig_row:
        raise HTTPException(status_code=404, detail="Asignación no encontrada.")

    assigned_user_id = asig_row["usuario_asignado_id"]

    actor = ActorContext(
        tenant_code=tenant.municipality_code,
        user_id=str(user["id_global"]),
        role=WorkflowRole.parse(user["role_code"])
    )

    try:
        # 1. Run RETURN_TO_FIELD transition on state machine to stay in DEVUELTO
        result = command_service.execute_transition(
            assignment_id=assignment_id,
            actor=actor,
            event=WorkflowEvent.RETURN_TO_FIELD
        )

        # 2. Update legacy fields
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE {asignacion_table} SET estado = 'DEVUELTO_DIGITALIZACION', enlace_digitalizacion = NULL, enlace_devolucion = %s WHERE id = %s",
                (payload.enlace if payload else None, int(assignment_id))
            )
            if payload and payload.comentario:
                asignaciones_repo.insert_asignacion_comentario(
                    conn,
                    tenant,
                    asignacion_id=int(assignment_id),
                    usuario_id=int(user["id_global"]),
                    usuario=user.get("username"),
                    rol=role,
                    comentario=payload.comentario,
                    estado_origen=asig_row["estado"],
                    estado_destino="DEVUELTO_DIGITALIZACION",
                    enlace=payload.enlace if payload else None
                )

        # 3. Create notification for digitalizador/reconocedor
        asig_title = asig_row["titulo"] or f"Trabajo #{assignment_id}"
        if assigned_user_id:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        f"SELECT rol FROM {users_table} WHERE id_global = %s",
                        (int(assigned_user_id),)
                    )
                    dest_user = cur.fetchone()
                rol_dest = dest_user.get("rol") if dest_user else "digitalizador"

                asignaciones_repo.safe_crear_notificacion(
                    conn,
                    tenant=tenant,
                    id_asignacion=int(assignment_id),
                    id_usuario_destino=int(assigned_user_id),
                    id_usuario_origen=int(user["id_global"]),
                    rol_origen="coordinador",
                    rol_destino=rol_dest,
                    tipo="asignacion",
                    titulo="Digitalización devuelta por Coordinador",
                    mensaje=f"El coordinador {user.get('username')} ha devuelto el trabajo '{asig_title}' para corrección de digitalización.",
                    url_destino=f"/panel/asignaciones/detalle?id={assignment_id}#asig-open",
                    prioridad="alta",
                    metadata={"assignment_id": int(assignment_id)}
                )
            except Exception as notif_err:
                logger.error(f"Fallo al notificar al usuario asignado: {notif_err}")

            asignaciones_repo.safe_log_event(
                conn,
                tenant,
                int(assignment_id),
                "ESTADO_CAMBIADO",
                "Trabajo devuelto a digitalización. Estado: DEVUELTO_DIGITALIZACION.",
                user.get("username")
            )
        conn.commit()
        return {
            "assignment_id": result.transition.assignment.assignment_id,
            "workflow_state": "DEVUELTO_DIGITALIZACION",
            "assigned_user_id": str(assigned_user_id) if assigned_user_id else None
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except WorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{assignment_id}/approve-digitalization")
def approve_digitalization(
    assignment_id: str,
    payload: Optional[WorkflowTransitionPayload] = None,
    tenant: TenantContext = Depends(get_tenant_context_from_session),
    user: dict = Depends(get_current_user_from_session),
    conn = Depends(get_tenant_db_connection),
    command_service: AssignmentCommandService = Depends(get_command_service)
):
    role = normalize_role(get_user_role(user))
    if role not in {"coordinador", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="Solo coordinadores o admins pueden aprobar la digitalización."
        )

    asignacion_table = app_table(tenant, "asignacion")
    users_table = app_table(tenant, "users")
    roles_table = app_table(tenant, "roles")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"SELECT enlace_digitalizacion, creado_por_id, titulo, estado FROM {asignacion_table} WHERE id = %s",
            (int(assignment_id),)
        )
        asig_row = cur.fetchone()

    if not asig_row:
        raise HTTPException(status_code=404, detail="Asignación no encontrada.")

    enlace = asig_row["enlace_digitalizacion"] or ""
    asig_title = asig_row["titulo"] or f"Trabajo #{assignment_id}"
    creator_id = asig_row["creado_por_id"]

    actor = ActorContext(
        tenant_code=tenant.municipality_code,
        user_id=str(user["id_global"]),
        role=WorkflowRole.parse(user["role_code"])
    )

    try:
        # 1. Run APPROVE transition on state machine
        result = command_service.execute_transition(
            assignment_id=assignment_id,
            actor=actor,
            event=WorkflowEvent.APPROVE
        )

        # 2. Update legacy fields to EN_APROBACION
        asignaciones_repo.update_asignacion_fields(
            conn,
            tenant,
            int(assignment_id),
            estado="EN_APROBACION",
        )

        if payload and payload.comentario:
            asignaciones_repo.insert_asignacion_comentario(
                conn,
                tenant,
                asignacion_id=int(assignment_id),
                usuario_id=int(user["id_global"]),
                usuario=user.get("username"),
                rol=role,
                comentario=payload.comentario,
                estado_origen=asig_row["estado"],
                estado_destino="EN_APROBACION"
            )

        # 3. Notify lideres de reconocimiento
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT u.id_global, u.username
                    FROM {users_table} u
                    JOIN {roles_table} r ON r.t_id = u.rol_id
                    WHERE r.itf_code = 'lider_reconocimiento' AND u.activo = TRUE
                    """
                )
                lider_users = cur.fetchall()

            for lid in lider_users:
                asignaciones_repo.safe_crear_notificacion(
                    conn,
                    tenant=tenant,
                    id_asignacion=int(assignment_id),
                    id_usuario_destino=int(lid["id_global"]),
                    id_usuario_origen=int(user["id_global"]),
                    rol_origen="coordinador",
                    rol_destino="lider_reconocimiento",
                    tipo="asignacion",
                    titulo="Digitalización aprobada por coordinador",
                    mensaje=f"El coordinador {user.get('username')} aprobó la digitalización de '{asig_title}' y requiere tu revisión.",
                    url_destino=f"/panel/asignaciones/detalle?id={assignment_id}#asig-open",
                    prioridad="alta",
                    metadata={"assignment_id": int(assignment_id), "enlace_digitalizacion": enlace}
                )
        except Exception as support_err:
            logger.error(f"Fallo al notificar lideres de reconocimiento para aprobación: {support_err}")

        asignaciones_repo.safe_log_event(
            conn,
            tenant,
            int(assignment_id),
            "ESTADO_CAMBIADO",
            "Digitalización aprobada por coordinador. Estado: EN_APROBACION.",
            user.get("username")
        )
        conn.commit()
        return {
            "assignment_id": result.transition.assignment.assignment_id,
            "workflow_state": "EN_APROBACION",
            "assigned_user_id": result.transition.assignment.assigned_user_id
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except WorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{assignment_id}/lider-approve")
def lider_approve_assignment(
    assignment_id: str,
    payload: Optional[WorkflowTransitionPayload] = None,
    tenant: TenantContext = Depends(get_tenant_context_from_session),
    user: dict = Depends(get_current_user_from_session),
    conn = Depends(get_tenant_db_connection),
    command_service: AssignmentCommandService = Depends(get_command_service)
):
    role = normalize_role(get_user_role(user))
    if role not in {"lider_reconocimiento", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="Solo usuarios con rol de lider de reconocimiento o admin pueden aprobar esta etapa."
        )

    asignacion_table = app_table(tenant, "asignacion")
    users_table = app_table(tenant, "users")
    roles_table = app_table(tenant, "roles")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"SELECT enlace_digitalizacion, creado_por_id, titulo, estado FROM {asignacion_table} WHERE id = %s",
            (int(assignment_id),)
        )
        asig_row = cur.fetchone()

    if not asig_row:
        raise HTTPException(status_code=404, detail="Asignación no encontrada.")

    enlace = asig_row["enlace_digitalizacion"] or ""
    asig_title = asig_row["titulo"] or f"Trabajo #{assignment_id}"
    creator_id = asig_row["creado_por_id"]

    actor = ActorContext(
        tenant_code=tenant.municipality_code,
        user_id=str(user["id_global"]),
        role=WorkflowRole.parse(user["role_code"])
    )

    try:
        # 1. Run START_SYNC transition on state machine
        result = command_service.execute_transition(
            assignment_id=assignment_id,
            actor=actor,
            event=WorkflowEvent.START_SYNC
        )

        # 2. Update legacy fields to EN_SINCRONIZACION
        asignaciones_repo.update_asignacion_fields(
            conn,
            tenant,
            int(assignment_id),
            estado="EN_SINCRONIZACION",
        )

        if payload and payload.comentario:
            asignaciones_repo.insert_asignacion_comentario(
                conn,
                tenant,
                asignacion_id=int(assignment_id),
                usuario_id=int(user["id_global"]),
                usuario=user.get("username"),
                rol=role,
                comentario=payload.comentario,
                estado_origen=asig_row["estado"],
                estado_destino="EN_SINCRONIZACION"
            )

        # 3. Notify support / consolidador
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT u.id_global, u.username
                    FROM {users_table} u
                    JOIN {roles_table} r ON r.t_id = u.rol_id
                    WHERE r.itf_code = 'consolidador' AND u.activo = TRUE
                    """
                )
                support_users = cur.fetchall()

            notified_user_ids = {int(sup["id_global"]) for sup in support_users}

            for sup in support_users:
                asignaciones_repo.safe_crear_notificacion(
                    conn,
                    tenant=tenant,
                    id_asignacion=int(assignment_id),
                    id_usuario_destino=int(sup["id_global"]),
                    id_usuario_origen=int(user["id_global"]),
                    rol_origen="lider_reconocimiento",
                    rol_destino="consolidador",
                    tipo="soporte",
                    titulo="Digitalización aprobada por Líder",
                    mensaje=f"El líder de reconocimiento {user.get('username')} aprobó la digitalización de '{asig_title}'. Enlace: {enlace}",
                    url_destino=f"/panel/asignaciones/detalle?id={assignment_id}#asig-open",
                    prioridad="alta",
                    metadata={"assignment_id": int(assignment_id), "enlace_digitalizacion": enlace}
                )

            if creator_id and int(creator_id) not in notified_user_ids:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        f"SELECT rol FROM {users_table} WHERE id_global = %s AND activo = TRUE",
                        (int(creator_id),)
                    )
                    creator_row = cur.fetchone()
                if creator_row and creator_row.get("rol") == "soporte":
                    asignaciones_repo.safe_crear_notificacion(
                        conn,
                        tenant=tenant,
                        id_asignacion=int(assignment_id),
                        id_usuario_destino=int(creator_id),
                        id_usuario_origen=int(user["id_global"]),
                        rol_origen="lider_reconocimiento",
                        rol_destino="soporte",
                        tipo="soporte",
                        titulo="Digitalización aprobada por Líder",
                        mensaje=f"El líder de reconocimiento {user.get('username')} aprobó la digitalización de '{asig_title}'. Enlace: {enlace}",
                        url_destino=f"/panel/asignaciones/detalle?id={assignment_id}#asig-open",
                        prioridad="alta",
                        metadata={"assignment_id": int(assignment_id), "enlace_digitalizacion": enlace}
                    )
        except Exception as support_err:
            logger.error(f"Fallo al notificar consolidadores/soporte para aprobacion de lider: {support_err}")

        asignaciones_repo.safe_log_event(
            conn,
            tenant,
            int(assignment_id),
            "ESTADO_CAMBIADO",
            "Trabajo aprobado por líder de reconocimiento. Estado: EN_SINCRONIZACION.",
            user.get("username")
        )
        conn.commit()
        return {
            "assignment_id": result.transition.assignment.assignment_id,
            "workflow_state": "EN_SINCRONIZACION",
            "assigned_user_id": result.transition.assignment.assigned_user_id
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except WorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{assignment_id}/lider-reject")
def lider_reject_assignment(
    assignment_id: str,
    payload: Optional[WorkflowTransitionPayload] = None,
    tenant: TenantContext = Depends(get_tenant_context_from_session),
    user: dict = Depends(get_current_user_from_session),
    conn = Depends(get_tenant_db_connection),
    command_service: AssignmentCommandService = Depends(get_command_service)
):
    role = normalize_role(get_user_role(user))
    if role not in {"lider_reconocimiento", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="Solo usuarios con rol de lider de reconocimiento o admin pueden devolver la digitalización."
        )

    asignacion_table = app_table(tenant, "asignacion")
    users_table = app_table(tenant, "users")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"SELECT usuario_asignado_id, coordinador_asignado_id, creado_por_id, titulo, estado FROM {asignacion_table} WHERE id = %s",
            (int(assignment_id),)
        )
        asig_row = cur.fetchone()

    if not asig_row:
        raise HTTPException(status_code=404, detail="Asignación no encontrada.")

    assigned_user_id = asig_row["usuario_asignado_id"]
    coordinador_id = asig_row["coordinador_asignado_id"] or asig_row["creado_por_id"]
    asig_title = asig_row["titulo"] or f"Trabajo #{assignment_id}"

    actor = ActorContext(
        tenant_code=tenant.municipality_code,
        user_id=str(user["id_global"]),
        role=WorkflowRole.parse(user["role_code"])
    )

    try:
        # 1. Run RETURN_TO_FIELD transition on state machine
        result = command_service.execute_transition(
            assignment_id=assignment_id,
            actor=actor,
            event=WorkflowEvent.RETURN_TO_FIELD
        )

        # 2. Update legacy fields: state to 'DEVUELTO_DIGITALIZACION', clear evidence link
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE {asignacion_table} SET estado = 'DEVUELTO_DIGITALIZACION', enlace_digitalizacion = NULL, enlace_devolucion = %s WHERE id = %s",
                (payload.enlace if payload else None, int(assignment_id))
            )
            if payload and payload.comentario:
                asignaciones_repo.insert_asignacion_comentario(
                    conn,
                    tenant,
                    asignacion_id=int(assignment_id),
                    usuario_id=int(user["id_global"]),
                    usuario=user.get("username"),
                    rol=role,
                    comentario=payload.comentario,
                    estado_origen=asig_row["estado"],
                    estado_destino="DEVUELTO_DIGITALIZACION",
                    enlace=payload.enlace if payload else None
                )

        # 3. Notify coordinator
        if coordinador_id:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        f"SELECT rol FROM {users_table} WHERE id_global = %s",
                        (int(coordinador_id),)
                    )
                    coord_user = cur.fetchone()
                rol_dest = coord_user.get("rol") if coord_user else "coordinador"
                
                asignaciones_repo.safe_crear_notificacion(
                    conn,
                    tenant=tenant,
                    id_asignacion=int(assignment_id),
                    id_usuario_destino=int(coordinador_id),
                    id_usuario_origen=int(user["id_global"]),
                    rol_origen="lider_reconocimiento",
                    rol_destino=rol_dest,
                    tipo="asignacion",
                    titulo="Digitalización devuelta por Líder",
                    mensaje=f"El líder de reconocimiento {user.get('username')} ha devuelto el trabajo '{asig_title}' al coordinador.",
                    url_destino=f"/panel/asignaciones/detalle?id={assignment_id}#asig-open",
                    prioridad="alta",
                    metadata={"assignment_id": int(assignment_id)}
                )
            except Exception as notif_err:
                logger.error(f"Fallo al notificar al coordinador: {notif_err}")

        # 4. Notify digitalizador/reconocedor
        if assigned_user_id:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        f"SELECT rol FROM {users_table} WHERE id_global = %s",
                        (int(assigned_user_id),)
                    )
                    dest_user = cur.fetchone()
                rol_dest = dest_user.get("rol") if dest_user else "digitalizador"

                asignaciones_repo.safe_crear_notificacion(
                    conn,
                    tenant=tenant,
                    id_asignacion=int(assignment_id),
                    id_usuario_destino=int(assigned_user_id),
                    id_usuario_origen=int(user["id_global"]),
                    rol_origen="lider_reconocimiento",
                    rol_destino=rol_dest,
                    tipo="asignacion",
                    titulo="Digitalización devuelta por Líder",
                    mensaje=f"El líder de reconocimiento {user.get('username')} ha devuelto el trabajo '{asig_title}' para corrección de digitalización.",
                    url_destino=f"/panel/asignaciones/detalle?id={assignment_id}#asig-open",
                    prioridad="alta",
                    metadata={"assignment_id": int(assignment_id)}
                )
            except Exception as notif_err:
                logger.error(f"Fallo al notificar al usuario asignado: {notif_err}")

            asignaciones_repo.safe_log_event(
                conn,
                tenant,
                int(assignment_id),
                "ESTADO_CAMBIADO",
                "Trabajo devuelto a digitalización por líder de reconocimiento. Estado: DEVUELTO_DIGITALIZACION.",
                user.get("username")
            )
        conn.commit()
        return {
            "assignment_id": result.transition.assignment.assignment_id,
            "workflow_state": "DEVUELTO_DIGITALIZACION",
            "assigned_user_id": str(assigned_user_id) if assigned_user_id else None
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except WorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
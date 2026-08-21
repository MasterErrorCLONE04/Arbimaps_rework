import json
from datetime import datetime
from typing import Optional

from workflow.audit.models import AuditContext, AuditEvent
from workflow.enums import RetornoState, SyncState, WorkflowRole, WorkflowState, WorkspaceState
from workflow.models import AssignmentSnapshot, TransitionResult
from workflow.ports import (
    AbstractAssignmentRepository,
    AbstractAuditRepository,
    AbstractOutboxRepository,
    AbstractTransitionRepository,
)
from workflow.service import PreparedOutboxMessage


class PostgresAssignmentRepository(AbstractAssignmentRepository):
    def __init__(self, cursor, schema: str, app_schema: str = "arbimaps_app"):
        self.cursor = cursor
        self.schema = schema
        self.app_schema = app_schema

    def get(self, tenant_code: str, assignment_id: str) -> Optional[AssignmentSnapshot]:
        query = f"""
            SELECT assignment_id, tenant_code, workflow_state, workspace_state, 
                   retorno_state, sync_state, assigned_user_id, assigned_role, 
                   is_closed, version, metadata
            FROM {self.schema}.assignments
            WHERE tenant_code = %s AND assignment_id = %s
            FOR UPDATE
        """
        self.cursor.execute(query, (tenant_code, assignment_id))
        row = self.cursor.fetchone()
        if not row:
            try:
                asig_id_int = int(assignment_id)
            except (ValueError, TypeError):
                return None

            self.cursor.execute(
                f"""
                SELECT estado, usuario_asignado_id 
                FROM {self.app_schema}.asignacion 
                WHERE id = %s
                """,
                (asig_id_int,)
            )
            main_row = self.cursor.fetchone()
            if not main_row:
                return None

            main_estado = main_row[0]
            assigned_user_id = str(main_row[1]) if main_row[1] is not None else None

            state_map = {
                "EN_CAMPO": "EN_CAMPO",
                "CONTROL_CALIDAD_1": "CONTROL_CALIDAD_1",
                "DEVUELTO_CAMPO": "DEVUELTO",
                "EN_APROBACION": "APROBACION",
                "GENERACION_XTF_CAMPO": "APROBACION",
                "APROBADO_DIGITALIZACION": "APROBACION",
                "EN_SINCRONIZACION": "SINCRONIZACION",
                "SINCRONIZADO": "SINCRONIZADO",
                "EN_DIGITALIZACION": "EN_CAMPO",
                "DEVUELTO_DIGITALIZACION": "DEVUELTO",
                "DEVUELTO_A_DIGITALIZACION": "DEVUELTO",
                "CONTROL_CALIDAD_2": "CONTROL_CALIDAD_1",
                    "APROBADO_SINCRONIZACION": "APROBADO_SINCRONIZACION",
                    "SINCRONIZADO_PRODUCCION": "SINCRONIZADO_PRODUCCION"
            }
            workflow_state = state_map.get(main_estado, "SIN_ASIGNAR")
            is_closed = (main_estado in ("CERRADA", "SINCRONIZADO_PRODUCCION"))

            if main_estado == "CREANDO_WORKSPACE":
                workspace_state = "BUILDING"
            elif main_estado == "ERROR_WORKSPACE":
                workspace_state = "ERROR"
            else:
                workspace_state = "READY"

            snapshot = AssignmentSnapshot(
                assignment_id=assignment_id,
                tenant_code=tenant_code,
                workflow_state=WorkflowState(workflow_state),
                workspace_state=WorkspaceState(workspace_state),
                retorno_state=RetornoState.NONE,
                sync_state=SyncState.NONE,
                assigned_user_id=assigned_user_id,
                assigned_role=WorkflowRole.RECONOCEDOR if assigned_user_id else None,
                is_closed=is_closed,
                version=1,
                metadata={}
            )

            self.save(snapshot)
            return snapshot
        
        # Self-healing alignment with legacy database
        try:
            asig_id_int = int(assignment_id)
            self.cursor.execute(
                f"SELECT estado, usuario_asignado_id FROM {self.app_schema}.asignacion WHERE id = %s",
                (asig_id_int,)
            )
            main_row = self.cursor.fetchone()
            if main_row:
                main_estado = main_row[0]
                legacy_assigned_user_id = str(main_row[1]) if main_row[1] is not None else None

                state_map = {
                    "EN_CAMPO": "EN_CAMPO",
                    "CONTROL_CALIDAD_1": "CONTROL_CALIDAD_1",
                    "DEVUELTO_CAMPO": "DEVUELTO",
                    "EN_APROBACION": "APROBACION",
                    "GENERACION_XTF_CAMPO": "APROBACION",
                    "APROBADO_DIGITALIZACION": "APROBACION",
                    "EN_SINCRONIZACION": "SINCRONIZACION",
                    "SINCRONIZADO": "SINCRONIZADO",
                    "EN_DIGITALIZACION": "EN_CAMPO",
                    "DEVUELTO_DIGITALIZACION": "DEVUELTO",
                    "DEVUELTO_A_DIGITALIZACION": "DEVUELTO",
                    "CONTROL_CALIDAD_2": "CONTROL_CALIDAD_1",
                    "APROBADO_SINCRONIZACION": "APROBADO_SINCRONIZACION",
                    "SINCRONIZADO_PRODUCCION": "SINCRONIZADO_PRODUCCION"
                }
                mapped_wf_state = state_map.get(main_estado)

                needs_update = False
                updated_wf_state = row[2]
                updated_user_id = row[6]
                updated_role = row[7]

                if mapped_wf_state and mapped_wf_state != row[2]:
                    updated_wf_state = mapped_wf_state
                    needs_update = True

                if legacy_assigned_user_id and legacy_assigned_user_id != row[6]:
                    updated_user_id = legacy_assigned_user_id
                    updated_role = "reconocedor"
                    needs_update = True

                # Align workspace state with legacy estado status
                if main_estado == "CREANDO_WORKSPACE":
                    expected_workspace_state = "BUILDING"
                elif main_estado == "ERROR_WORKSPACE":
                    expected_workspace_state = "ERROR"
                else:
                    expected_workspace_state = "READY"

                updated_ws_state = row[3]
                if expected_workspace_state != row[3]:
                    updated_ws_state = expected_workspace_state
                    needs_update = True

                if needs_update:
                    aligned_snapshot = AssignmentSnapshot(
                        assignment_id=row[0],
                        tenant_code=row[1],
                        workflow_state=WorkflowState(updated_wf_state),
                        workspace_state=WorkspaceState(updated_ws_state),
                        retorno_state=RetornoState(row[4]),
                        sync_state=SyncState(row[5]),
                        assigned_user_id=updated_user_id,
                        assigned_role=WorkflowRole(updated_role) if updated_role else None,
                        is_closed=row[8],
                        version=row[9] + 1,
                        metadata=row[10] if isinstance(row[10], dict) else (json.loads(row[10]) if row[10] else {})
                    )
                    self.save(aligned_snapshot)
                    return aligned_snapshot
        except Exception:
            pass

        return AssignmentSnapshot(
            assignment_id=row[0],
            tenant_code=row[1],
            workflow_state=WorkflowState(row[2]),
            workspace_state=WorkspaceState(row[3]),
            retorno_state=RetornoState(row[4]),
            sync_state=SyncState(row[5]),
            assigned_user_id=row[6],
            assigned_role=WorkflowRole(row[7]) if row[7] else None,
            is_closed=row[8],
            version=row[9],
            metadata=row[10] if isinstance(row[10], dict) else (json.loads(row[10]) if row[10] else {})
        )


    def save(self, assignment: AssignmentSnapshot) -> None:
        query = f"""
            INSERT INTO {self.schema}.assignments (
                assignment_id, tenant_code, workflow_state, workspace_state, 
                retorno_state, sync_state, assigned_user_id, assigned_role, 
                is_closed, version, metadata
            ) VALUES (
                %(assignment_id)s, %(tenant_code)s, %(workflow_state)s, %(workspace_state)s,
                %(retorno_state)s, %(sync_state)s, %(assigned_user_id)s, %(assigned_role)s,
                %(is_closed)s, %(version)s, %(metadata)s
            )
            ON CONFLICT (tenant_code, assignment_id) DO UPDATE SET
                workflow_state = EXCLUDED.workflow_state,
                workspace_state = EXCLUDED.workspace_state,
                retorno_state = EXCLUDED.retorno_state,
                sync_state = EXCLUDED.sync_state,
                assigned_user_id = EXCLUDED.assigned_user_id,
                assigned_role = EXCLUDED.assigned_role,
                is_closed = EXCLUDED.is_closed,
                version = EXCLUDED.version,
                metadata = EXCLUDED.metadata,
                updated_at = NOW()
            WHERE {self.schema}.assignments.version = %(expected_version)s
        """
        expected_version = assignment.version - 1 if assignment.version > 1 else 0
        self.cursor.execute(query, {
            "assignment_id": assignment.assignment_id,
            "tenant_code": assignment.tenant_code,
            "workflow_state": assignment.workflow_state.value,
            "workspace_state": assignment.workspace_state.value,
            "retorno_state": assignment.retorno_state.value,
            "sync_state": assignment.sync_state.value,
            "assigned_user_id": assignment.assigned_user_id,
            "assigned_role": assignment.assigned_role.value if assignment.assigned_role else None,
            "is_closed": assignment.is_closed,
            "version": assignment.version,
            "metadata": json.dumps(assignment.metadata),
            "expected_version": expected_version
        })
        if self.cursor.rowcount == 0:
            raise RuntimeError(f"Optimistic locking failed for assignment {assignment.assignment_id}.")


class PostgresAuditRepository(AbstractAuditRepository):
    def __init__(self, cursor, schema: str):
        self.cursor = cursor
        self.schema = schema

    def append(self, event: AuditEvent) -> None:
        query = f"""
            INSERT INTO {self.schema}.audit_events (
                event_type, tenant_code, assignment_id, actor_user_id, actor_role,
                workflow_event, from_state, to_state, occurred_at, correlation_id, source, metadata
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """
        self.cursor.execute(query, (
            str(event.event_type), event.tenant_code, event.assignment_id, event.actor_user_id,
            event.actor_role.value if event.actor_role else None,
            event.workflow_event.value if event.workflow_event else None,
            event.from_state.value if event.from_state else None,
            event.to_state.value if event.to_state else None,
            event.occurred_at, event.correlation_id, event.source,
            json.dumps(event.metadata or {})
        ))


class PostgresOutboxRepository(AbstractOutboxRepository):
    def __init__(self, cursor, schema: str):
        self.cursor = cursor
        self.schema = schema

    def append(self, message: PreparedOutboxMessage) -> None:
        query = f"""
            INSERT INTO {self.schema}.outbox_messages (
                job_type, tenant_code, assignment_id, correlation_id, idempotency_key, payload, status
            ) VALUES (
                %s, %s, %s, %s, %s, %s, 'PENDING'
            )
            ON CONFLICT (idempotency_key) DO NOTHING
        """
        self.cursor.execute(query, (
            message.job_type, message.tenant_code, message.assignment_id,
            message.correlation_id, message.idempotency_key,
            json.dumps(message.payload or {})
        ))


class PostgresTransitionRepository(AbstractTransitionRepository):
    def __init__(self, cursor, schema: str):
        self.cursor = cursor
        self.schema = schema

    def append(self, transition: TransitionResult, audit_context: AuditContext, occurred_at: datetime) -> None:
        query = f"""
            INSERT INTO {self.schema}.assignment_transitions (
                tenant_code, assignment_id, workflow_event, 
                from_state, to_state, actor_user_id, actor_role, 
                occurred_at, correlation_id, metadata
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """

        self.cursor.execute(query, (
            transition.assignment.tenant_code,
            transition.assignment.assignment_id,

            transition.event.value if transition.event else None,
            transition.from_state.value if transition.from_state else None,
            transition.to_state.value if transition.to_state else None,

            audit_context.actor_user_id,
            audit_context.actor_role.value if audit_context.actor_role else None,

            occurred_at,
            audit_context.correlation_id,

            json.dumps(transition.metadata or {})
        ))
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
    def __init__(self, cursor, schema: str):
        self.cursor = cursor
        self.schema = schema

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
            return None
        
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
            json.dumps(event.metadata) if event.metadata else None
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
            json.dumps(message.payload) if message.payload else None
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

            json.dumps(transition.metadata) if transition.metadata else None
        ))
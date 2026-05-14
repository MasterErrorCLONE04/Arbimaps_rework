from datetime import datetime
from typing import Optional

from workflow.audit.models import AuditContext, AuditEvent
from workflow.models import AssignmentSnapshot, TransitionResult
from workflow.ports import (
    AbstractAssignmentRepository,
    AbstractAuditRepository,
    AbstractOutboxRepository,
    AbstractTransitionRepository,
    AbstractUnitOfWork,
)
from workflow.service import PreparedOutboxMessage


class FakeAssignmentRepository(AbstractAssignmentRepository):
    def __init__(self, data: dict[tuple[str, str], AssignmentSnapshot]):
        self._data = data
        self._pending: dict[tuple[str, str], AssignmentSnapshot] = {}

    def get(self, tenant_code: str, assignment_id: str) -> Optional[AssignmentSnapshot]:
        key = (tenant_code, assignment_id)
        if key in self._pending:
            return self._pending[key]
        return self._data.get(key)

    def save(self, assignment: AssignmentSnapshot) -> None:
        self._pending[(assignment.tenant_code, assignment.assignment_id)] = assignment

    def commit(self) -> None:
        self._data.update(self._pending)
        self._pending.clear()

    def rollback(self) -> None:
        self._pending.clear()


class FakeAuditRepository(AbstractAuditRepository):
    def __init__(self, data: list[AuditEvent]):
        self._data = data
        self._pending: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self._pending.append(event)

    def commit(self) -> None:
        self._data.extend(self._pending)
        self._pending.clear()

    def rollback(self) -> None:
        self._pending.clear()


class FakeOutboxRepository(AbstractOutboxRepository):
    def __init__(self, data: list[PreparedOutboxMessage]):
        self._data = data
        self._pending: list[PreparedOutboxMessage] = []

    def append(self, message: PreparedOutboxMessage) -> None:
        self._pending.append(message)

    def commit(self) -> None:
        self._data.extend(self._pending)
        self._pending.clear()

    def rollback(self) -> None:
        self._pending.clear()


class FakeTransitionRepository(AbstractTransitionRepository):
    def __init__(self, data: list):
        self._data = data
        self._pending: list = []

    def append(self, transition: TransitionResult, audit_context: AuditContext, occurred_at: datetime) -> None:
        self._pending.append((transition, audit_context, occurred_at))

    def commit(self) -> None:
        self._data.extend(self._pending)
        self._pending.clear()

    def rollback(self) -> None:
        self._pending.clear()


class FakeUnitOfWork(AbstractUnitOfWork):
    def __init__(self):
        self.assignments_data: dict[tuple[str, str], AssignmentSnapshot] = {}
        self.audit_data: list[AuditEvent] = []
        self.outbox_data: list[PreparedOutboxMessage] = []
        self.transitions_data: list = []
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> "FakeUnitOfWork":
        self.assignments = FakeAssignmentRepository(self.assignments_data)
        self.audit = FakeAuditRepository(self.audit_data)
        self.outbox = FakeOutboxRepository(self.outbox_data)
        self.transitions = FakeTransitionRepository(self.transitions_data)
        self.committed = False
        self.rolled_back = False
        return super().__enter__()

    def commit(self) -> None:
        self.assignments.commit()
        self.audit.commit()
        self.outbox.commit()
        self.transitions.commit()
        self.committed = True

    def rollback(self) -> None:
        self.assignments.rollback()
        self.audit.rollback()
        self.outbox.rollback()
        self.transitions.rollback()
        self.rolled_back = True
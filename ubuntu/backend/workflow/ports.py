import abc
from datetime import datetime
from typing import Optional

from workflow.audit.models import AuditContext, AuditEvent
from workflow.models import AssignmentSnapshot, TransitionResult
from workflow.service import PreparedOutboxMessage


class AbstractAssignmentRepository(abc.ABC):
    @abc.abstractmethod
    def get(self, tenant_code: str, assignment_id: str) -> Optional[AssignmentSnapshot]:
        raise NotImplementedError

    @abc.abstractmethod
    def save(self, assignment: AssignmentSnapshot) -> None:
        raise NotImplementedError


class AbstractAuditRepository(abc.ABC):
    @abc.abstractmethod
    def append(self, event: AuditEvent) -> None:
        raise NotImplementedError


class AbstractOutboxRepository(abc.ABC):
    @abc.abstractmethod
    def append(self, message: PreparedOutboxMessage) -> None:
        raise NotImplementedError


class AbstractTransitionRepository(abc.ABC):
    @abc.abstractmethod
    def append(self, transition: TransitionResult, audit_context: AuditContext, occurred_at: datetime) -> None:
        raise NotImplementedError


class AbstractUnitOfWork(abc.ABC):
    assignments: AbstractAssignmentRepository
    audit: AbstractAuditRepository
    outbox: AbstractOutboxRepository
    transitions: AbstractTransitionRepository

    def __enter__(self) -> "AbstractUnitOfWork":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()

    @abc.abstractmethod
    def commit(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def rollback(self) -> None:
        raise NotImplementedError
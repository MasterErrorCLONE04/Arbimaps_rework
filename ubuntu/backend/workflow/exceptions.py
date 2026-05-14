class WorkflowError(Exception):
    """Base class for workflow domain errors."""


class InvalidTransitionError(WorkflowError):
    """Raised when an event is not allowed from the current workflow state."""


class RoleNotAllowedError(WorkflowError):
    """Raised when the actor role cannot execute the requested event."""


class TenantMismatchError(WorkflowError):
    """Raised when actor and assignment belong to different tenants."""


class AssignmentClosedError(WorkflowError):
    """Raised when a closed assignment receives a forbidden mutation."""


class SyncInProgressError(WorkflowError):
    """Raised when a running sync blocks the requested transition."""


class OwnershipValidationError(WorkflowError):
    """Raised when the actor must be the assignment owner but is not."""


class WorkflowPreconditionError(WorkflowError):
    """Raised when a domain precondition blocks a valid transition."""

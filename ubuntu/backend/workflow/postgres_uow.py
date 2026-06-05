import re

from workflow.ports import AbstractUnitOfWork
from workflow.postgres_repositories import (
    PostgresAssignmentRepository,
    PostgresAuditRepository,
    PostgresOutboxRepository,
    PostgresTransitionRepository,
)


class PostgresUnitOfWork(AbstractUnitOfWork):
    """
    Implementación del Unit of Work transaccional para PostgreSQL.
    Maneja la conexión del ConnectionManager y la persistencia multi-tenant
    a través del schema seguro inyectado por el TenantContext.
    """

    def __init__(self, connection_manager, tenant_context):
        self.connection_manager = connection_manager
        self.tenant_context = tenant_context
        self.conn = None
        self.cursor = None

    def __enter__(self) -> "PostgresUnitOfWork":
        self.conn = self.connection_manager.get_connection(self.tenant_context)
        self.conn.autocommit = False
        self.cursor = self.conn.cursor()

        schema = self.tenant_context.schemas.workflow
        if not schema or not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", schema):
            raise ValueError(f"Invalid schema name: {schema}")

        self.assignments = PostgresAssignmentRepository(
            self.cursor, 
            schema, 
            app_schema=self.tenant_context.schemas.app
        )

        self.audit = PostgresAuditRepository(self.cursor, schema)
        self.outbox = PostgresOutboxRepository(self.cursor, schema)
        self.transitions = PostgresTransitionRepository(self.cursor, schema)

        return super().__enter__()

    def commit(self) -> None:
        if self.conn:
            self.conn.commit()

    def rollback(self) -> None:
        if self.conn:
            self.conn.rollback()

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            if self.cursor:
                self.cursor.close()
            if self.conn and self.connection_manager:
                self.connection_manager.release_connection(self.tenant_context, self.conn)
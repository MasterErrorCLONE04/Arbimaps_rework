from dataclasses import dataclass
from typing import FrozenSet, Optional

from core.asignaciones import ASIG_MODEL_CONTEXT, AssignmentModelContext
from core.db import db_conn
from services.asignaciones_export import ExportServiceError


@dataclass(frozen=True)
class WorkspaceContext:
    model_name: str
    schema_work: str
    predio_table: str
    predio_numero_field: str
    required_tables: FrozenSet[str]
    build_strategy: str


@dataclass(frozen=True)
class WorkspaceSchemaStatus:
    context: WorkspaceContext
    exists: bool
    existing_tables: FrozenSet[str]
    missing_tables: FrozenSet[str]


def get_workspace_context(
    schema_work: Optional[str] = None,
    model_context: Optional[AssignmentModelContext] = None,
) -> WorkspaceContext:
    base = model_context or ASIG_MODEL_CONTEXT
    resolved_schema = (schema_work or base.schema_work or "").strip().strip('"')
    if not resolved_schema:
        raise ValueError("schema_work no definido para asignaciones.")

    required_tables = frozenset({"t_ili2db_dataset", "t_ili2db_basket", base.predio_table})
    return WorkspaceContext(
        model_name=base.name,
        schema_work=resolved_schema,
        predio_table=base.predio_table,
        predio_numero_field=base.predio_numero_field,
        required_tables=required_tables,
        build_strategy="ili2pg_checkout",
    )


def get_workspace_schema_status(
    schema_work: Optional[str] = None,
    model_context: Optional[AssignmentModelContext] = None,
) -> WorkspaceSchemaStatus:
    context = get_workspace_context(schema_work, model_context)

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.schemata
                    WHERE schema_name = %s
                )
                """,
                (context.schema_work,),
            )
            exists = bool((cur.fetchone() or [False])[0])

            existing_tables: FrozenSet[str] = frozenset()
            if exists:
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s
                    """,
                    (context.schema_work,),
                )
                existing_tables = frozenset(
                    str(row[0]).strip()
                    for row in (cur.fetchall() or [])
                    if row and row[0]
                )

    missing_tables = frozenset(sorted(context.required_tables - existing_tables))
    return WorkspaceSchemaStatus(
        context=context,
        exists=exists,
        existing_tables=existing_tables,
        missing_tables=missing_tables,
    )


def ensure_workspace_schema_ready(
    schema_work: Optional[str] = None,
    model_context: Optional[AssignmentModelContext] = None,
) -> WorkspaceContext:
    status = get_workspace_schema_status(schema_work, model_context)
    context = status.context
    if status.exists and not status.missing_tables:
        return context

    required_tables = ", ".join(sorted(context.required_tables))
    missing_tables = ", ".join(sorted(status.missing_tables)) or required_tables
    if not status.exists:
        raise ExportServiceError(
            status_code=500,
            detail=(
                f"El schema de workspace '{context.schema_work}' no existe. "
                f"Debe inicializarse para el modelo {context.model_name} con al menos: {required_tables}."
            ),
        )

    raise ExportServiceError(
        status_code=500,
        detail=(
            f"El schema de workspace '{context.schema_work}' no esta listo para asignaciones "
            f"del modelo {context.model_name}. Faltan tablas: {missing_tables}."
        ),
    )

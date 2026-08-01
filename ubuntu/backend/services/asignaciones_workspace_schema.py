from dataclasses import dataclass
from typing import FrozenSet, Optional

from core.asignaciones import AssignmentModelContext, get_assignment_model_context
from services.asignaciones_export import ExportServiceError
from tenants import TenantContext


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


def resolve_assignment_model_context(
    tenant: Optional[TenantContext] = None,
) -> AssignmentModelContext:
    base = get_assignment_model_context("arb")
    schema_main = (
        (tenant.schemas.main if tenant else "") or base.schema_main or ""
    ).strip().strip('"')
    schema_work = (
        (tenant.schemas.work if tenant else "") or base.schema_work or ""
    ).strip().strip('"')
    return AssignmentModelContext(
        name=base.name,
        schema_main=schema_main,
        schema_work=schema_work,
        datasetname_main_default=base.datasetname_main_default,
        required_baskets=base.required_baskets,
        predio_table=base.predio_table,
        predio_numero_field=base.predio_numero_field,
    )


def get_workspace_context(
    tenant: TenantContext | str | None,
    model_context: Optional[AssignmentModelContext] = None,
    schema_work: Optional[str] = None,
) -> WorkspaceContext:
    tenant_ctx = tenant if isinstance(tenant, TenantContext) else None
    if tenant_ctx is None and isinstance(tenant, str) and schema_work is None:
        schema_work = tenant

    base = model_context or resolve_assignment_model_context(tenant_ctx)
    resolved_schema = (
        schema_work
        or (tenant_ctx.schemas.work if tenant_ctx else "")
        or base.schema_work
        or ""
    ).strip().strip('"')
    if not resolved_schema:
        raise ValueError("schema_work no definido para asignaciones.")

    required_tables = frozenset({"t_ili2db_dataset", "t_ili2db_basket", base.predio_table})
    return WorkspaceContext(
        model_name=base.name,
        schema_work=resolved_schema,
        predio_table=base.predio_table,
        predio_numero_field=base.predio_numero_field,
        required_tables=required_tables,
        build_strategy="legacy_sql",
    )


def get_workspace_schema_status(
    conn,
    tenant: TenantContext,
    model_context: Optional[AssignmentModelContext] = None,
    schema_work: Optional[str] = None,
) -> WorkspaceSchemaStatus:
    context = get_workspace_context(tenant, model_context, schema_work)

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


def _ensure_workspace_metadata_populated(conn, schema_main: str, schema_work: str) -> None:
    with conn.cursor() as cur:
        # Check if t_ili2db_settings exists
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = 't_ili2db_settings'
            )
            """,
            (schema_work,),
        )
        if not cur.fetchone()[0]:
            return

        cur.execute(f"SELECT COUNT(*) FROM {schema_work}.t_ili2db_settings;")
        if cur.fetchone()[0] > 0:
            return

        meta_tables = [
            "t_ili2db_attrname",
            "t_ili2db_classname",
            "t_ili2db_column_prop",
            "t_ili2db_inheritance",
            "t_ili2db_meta_attrs",
            "t_ili2db_model",
            "t_ili2db_settings",
            "t_ili2db_table_prop",
            "t_ili2db_trafo",
        ]
        for table in meta_tables:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                ) AND EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                )
                """,
                (schema_main, table, schema_work, table),
            )
            if cur.fetchone()[0]:
                cur.execute(f"TRUNCATE TABLE {schema_work}.{table} CASCADE;")
                cur.execute(f"INSERT INTO {schema_work}.{table} SELECT * FROM {schema_main}.{table};")


def ensure_workspace_schema_ready(
    conn,
    tenant: TenantContext,
    model_context: Optional[AssignmentModelContext] = None,
    schema_work: Optional[str] = None,
) -> WorkspaceContext:
    status = get_workspace_schema_status(conn, tenant, model_context, schema_work)
    context = status.context
    if status.exists and not status.missing_tables:
        _ensure_workspace_metadata_populated(conn, tenant.schemas.main, context.schema_work)
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

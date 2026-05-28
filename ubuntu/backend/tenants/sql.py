import re

from .context import TenantContext


IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_identifier(value: str, *, label: str = "identifier") -> str:
    clean = (value or "").strip()
    if not IDENT_RE.match(clean):
        raise ValueError(f"{label} invalido: {value!r}")
    return clean


def tenant_schema(tenant: TenantContext, schema_name: str) -> str:
    if not hasattr(tenant.schemas, schema_name):
        raise ValueError(f"Schema tenant no soportado: {schema_name!r}")
    return validate_identifier(
        getattr(tenant.schemas, schema_name),
        label=f"tenant.schemas.{schema_name}",
    )


def tenant_table(tenant: TenantContext, table_name: str, *, schema_name: str) -> str:
    schema = tenant_schema(tenant, schema_name)
    table = validate_identifier(table_name, label="table")
    return f"{schema}.{table}"


def app_table(tenant: TenantContext, table_name: str) -> str:
    return tenant_table(tenant, table_name, schema_name="app")


def main_table(tenant: TenantContext, table_name: str) -> str:
    return tenant_table(tenant, table_name, schema_name="main")


def work_table(tenant: TenantContext, table_name: str) -> str:
    return tenant_table(tenant, table_name, schema_name="work")


def history_table(tenant: TenantContext, table_name: str) -> str:
    return tenant_table(tenant, table_name, schema_name="history")


def workflow_table(tenant: TenantContext, table_name: str) -> str:
    return tenant_table(tenant, table_name, schema_name="workflow")

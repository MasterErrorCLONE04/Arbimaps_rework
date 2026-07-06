from __future__ import annotations

from dataclasses import dataclass

import psycopg2
from psycopg2 import OperationalError
from psycopg2.extras import RealDictCursor


DEFAULT_PORT = 5432
REQUIRED_WORKSPACE_TABLES = ("t_ili2db_dataset", "t_ili2db_basket", "arb_predio")


@dataclass(frozen=True)
class LocalConnectionParams:
    host: str
    port: int
    user: str
    password: str
    database: str = "postgres"

    def as_connect_kwargs(self) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "dbname": self.database,
            "connect_timeout": 8,
            "sslmode": "prefer",
        }


class LocalPostgresConnectionService:
    def build_params(
        self,
        *,
        host: str,
        port: int | None,
        user: str,
        password: str,
        database: str | None = None,
    ) -> LocalConnectionParams:
        host_value = str(host or "").strip()
        user_value = str(user or "").strip()
        database_value = str(database or "postgres").strip() or "postgres"
        port_value = int(port or DEFAULT_PORT)

        if not host_value:
            raise ValueError("El host es obligatorio.")
        if not user_value:
            raise ValueError("El usuario es obligatorio.")
        if port_value < 1 or port_value > 65535:
            raise ValueError("El puerto debe estar entre 1 y 65535.")

        return LocalConnectionParams(
            host=host_value,
            port=port_value,
            user=user_value,
            password=str(password or ""),
            database=database_value,
        )

    def test_connection_and_list_databases(self, params: LocalConnectionParams) -> list[str]:
        query = """
            SELECT datname
            FROM pg_database
            WHERE datistemplate = FALSE
            ORDER BY CASE WHEN datname = current_database() THEN 0 ELSE 1 END, datname
        """
        with psycopg2.connect(**params.as_connect_kwargs()) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return [str(row[0]).strip() for row in (cur.fetchall() or []) if row and row[0]]

    def list_schemas(self, params: LocalConnectionParams) -> list[dict[str, object]]:
        schema_query = """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
              AND schema_name NOT LIKE 'pg_toast%'
              AND schema_name NOT LIKE 'pg_temp%'
            ORDER BY schema_name
        """
        tables_query = """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = ANY(%s)
              AND table_type = 'BASE TABLE'
        """

        with psycopg2.connect(**params.as_connect_kwargs()) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(schema_query)
                schema_names = [str(row["schema_name"]).strip() for row in (cur.fetchall() or []) if row.get("schema_name")]
                if not schema_names:
                    return []

                cur.execute(tables_query, (schema_names,))
                table_rows = cur.fetchall() or []

        tables_by_schema: dict[str, set[str]] = {schema_name: set() for schema_name in schema_names}
        for row in table_rows:
            schema_name = str(row.get("table_schema") or "").strip()
            table_name = str(row.get("table_name") or "").strip()
            if schema_name and table_name:
                tables_by_schema.setdefault(schema_name, set()).add(table_name)

        result: list[dict[str, object]] = []
        for schema_name in schema_names:
            existing_tables = tables_by_schema.get(schema_name, set())
            present = [table for table in REQUIRED_WORKSPACE_TABLES if table in existing_tables]
            missing = [table for table in REQUIRED_WORKSPACE_TABLES if table not in existing_tables]
            is_compatible = not missing
            has_partial_match = bool(present) and not is_compatible
            result.append(
                {
                    "schema": schema_name,
                    "is_compatible": is_compatible,
                    "has_partial_match": has_partial_match,
                    "required_tables_present": present,
                    "required_tables_missing": missing,
                    "table_count": len(existing_tables),
                }
            )
        return result

    @staticmethod
    def to_public_error(exc: Exception) -> str:
        if isinstance(exc, ValueError):
            return str(exc)
        if isinstance(exc, OperationalError):
            return "No fue posible conectar con PostgreSQL local usando las credenciales suministradas."
        return "Ocurrio un error al consultar PostgreSQL local."

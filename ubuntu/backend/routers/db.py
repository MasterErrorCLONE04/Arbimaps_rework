import os
import re
from contextlib import contextmanager

import psycopg2

from core.db import get_db_params
from core.env_loader import load_env_file_if_present


load_env_file_if_present()

DATA_SCHEMA = os.getenv("DATA_SCHEMA", "leiva")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _schema_name(schema: str | None = None) -> str:
    name = (schema or DATA_SCHEMA or "").strip()
    if not IDENT_RE.match(name):
        raise ValueError(f"Schema invalido: {name!r}")
    return name


def t(table: str, schema: str | None = None) -> str:
    """
    Devuelve el nombre totalmente calificado de una tabla
    en el esquema de datos configurado.
    """
    return f"{_schema_name(schema)}.{table}"


def _get_db_params() -> dict:
    """
    Lee los parámetros de conexión desde variables de entorno.

    Variables esperadas (con valores por defecto razonables para desarrollo):
    - DB_HOST (default: localhost)
    - DB_PORT (default: 5432)
    - DB_NAME (default: postgres)
    - DB_USER (default: postgres)
    - DB_PASSWORD / DB_PASS (default: "Arbitrium2026*")
    """
    return get_db_params()


@contextmanager
def db_conn():
    """
    Devuelve una conexión psycopg2 como context manager.

    Uso:
    >>> with db_conn() as conn:
    ...     with conn.cursor() as cur:
    ...         cur.execute("SELECT 1")
    """
    params = _get_db_params()
    conn = psycopg2.connect(**params)
    try:
        yield conn
    finally:
        conn.close()

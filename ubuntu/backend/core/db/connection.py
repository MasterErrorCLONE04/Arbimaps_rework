import os
from contextlib import contextmanager
from urllib.parse import unquote, urlparse

import psycopg2

from core.env_loader import load_env_file_if_present


load_env_file_if_present()

DATA_SCHEMA = os.getenv("DATA_SCHEMA", "leiva")


def t(table: str) -> str:
    """
    Devuelve el nombre totalmente calificado de una tabla
    en el esquema de datos configurado.
    """
    return f"{DATA_SCHEMA}.{table}"


def _db_params_from_database_url() -> dict:
    url = (os.getenv("DATABASE_URL", "") or "").strip()
    if not url:
        return {}
    try:
        parsed = urlparse(url)
    except Exception:
        return {}

    if parsed.scheme not in {"postgresql", "postgres"}:
        return {}

    dbname = (parsed.path or "").lstrip("/") or "postgres"
    password = unquote(parsed.password) if parsed.password else ""
    return {
        "host": parsed.hostname or "",
        "port": int(parsed.port or 5432),
        "dbname": dbname,
        "user": parsed.username or "",
        "password": password,
    }


def get_db_params() -> dict:
    """
    Lee los parametros de conexion desde variables de entorno.
    Prioriza variables DB_* y, si faltan, usa DATABASE_URL.
    """
    url_params = _db_params_from_database_url()
    return {
        "host": os.getenv("DB_HOST", url_params.get("host") or "localhost"),
        "port": int(os.getenv("DB_PORT", str(url_params.get("port") or 5432))),
        "dbname": os.getenv("DB_NAME", url_params.get("dbname") or "postgres"),
        "user": os.getenv("DB_USER", url_params.get("user") or "postgres"),
        "password": os.getenv(
            "DB_PASSWORD",
            os.getenv("DB_PASS", url_params.get("password") or "Arbitrium2026*"),
        ),
        "sslmode": os.getenv("DB_SSLMODE", "require"),
        "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "10")),
        "keepalives": int(os.getenv("DB_KEEPALIVES", "1")),
        "keepalives_idle": int(os.getenv("DB_KEEPALIVES_IDLE", "30")),
        "keepalives_interval": int(os.getenv("DB_KEEPALIVES_INTERVAL", "10")),
        "keepalives_count": int(os.getenv("DB_KEEPALIVES_COUNT", "5")),
    }


@contextmanager
def db_conn():
    """
    Devuelve una conexion psycopg2 como context manager.
    """
    params = get_db_params()
    conn = psycopg2.connect(**params)
    try:
        yield conn
    finally:
        conn.close()

from __future__ import annotations

import asyncio
import logging
import asyncpg

log = logging.getLogger(__name__)


async def test_postgresql_connection(host: str, port: int, user: str, password: str, database: str):
    """
    Prueba la conexión a una base de datos PostgreSQL específica.
    Devuelve una tupla: (is_ok, message, databases_list)
    """
    log.info(f"Intentando conectar a PostgreSQL en {host}:{port}, db: {database}, user: {user}")
    try:
        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            timeout=5,
        )
        # Opcional: listar otras bases de datos visibles si es útil.
        db_records = await conn.fetch("SELECT datname FROM pg_database WHERE datistemplate = false;")
        databases = sorted([record['datname'] for record in db_records])
        await conn.close()
        log.info(f"Conexión a {host}:{port} exitosa.")
        return True, "Conexión exitosa.", databases

    except (asyncpg.exceptions.InvalidPasswordError, asyncpg.exceptions.InvalidAuthorizationSpecificationError) as e:
        log.warning(f"Error de autenticación en {host}:{port} para usuario {user}: {e}")
        return False, "Error de autenticación: usuario o contraseña incorrectos.", []
    except asyncpg.exceptions.InvalidCatalogNameError:
        log.warning(f"La base de datos '{database}' no existe en {host}:{port}.")
        return False, f"La base de datos '{database}' no fue encontrada.", []
    except (OSError, asyncpg.exceptions.CannotConnectNowError, asyncio.TimeoutError) as e:
        log.error(f"No se pudo conectar a {host}:{port}: {e}")
        return False, f"No fue posible conectar al servidor PostgreSQL en '{host}:{port}'. Verifique el host y el puerto.", []
    except Exception as e:
        log.exception(f"Error inesperado de base de datos al conectar a {host}:{port}")
        return False, f"Error inesperado: {e}", []


async def list_schemas(host: str, port: int, user: str, password: str, database: str) -> list[dict]:
    """
    Se conecta a una base de datos específica y lista sus esquemas,
    verificando la compatibilidad con LADM-COL.
    """
    conn = await asyncpg.connect(host=host, port=port, user=user, password=password, database=database)
    try:
        schema_records = await conn.fetch(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'public')"
        )
        schemas = []
        for record in schema_records:
            schema_name = record['schema_name']
            query = """
            SELECT COUNT(*) FROM information_schema.tables 
            WHERE table_schema = $1 AND table_name IN ('t_ili2db_dataset', 't_ili2db_basket', 'arb_predio')
            """
            count = await conn.fetchval(query, schema_name)
            schemas.append({"name": schema_name, "is_ladm_col_compliant": count == 3})
        return schemas
    finally:
        await conn.close()


async def detect_open_ports(hosts: list[str], ports: list[int]) -> list[dict]:
    """Verifica la conectividad TCP a una lista de hosts y puertos."""
    results = []
    for host in hosts:
        for port in ports:
            try:
                # Intenta abrir una conexión, con un timeout corto.
                reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=1.0)
                writer.close()
                await writer.wait_closed()
                results.append({"host": host, "port": port, "status": "disponible"})
            except (OSError, asyncio.TimeoutError):
                results.append({"host": host, "port": port, "status": "no disponible"})
    return results


def to_public_error(exc: Exception) -> str:
    """
    Convierte una excepción en un mensaje de error legible para el cliente.
    """
    # Manejo específico para excepciones de asyncpg
    if isinstance(exc, asyncpg.exceptions.InvalidPasswordError):
        return "Error de autenticación: la contraseña es incorrecta."
    if isinstance(exc, asyncpg.exceptions.InvalidAuthorizationSpecificationError):
        return "Error de autenticación: el usuario no existe o la contraseña es incorrecta."
    if isinstance(exc, asyncpg.exceptions.InvalidCatalogNameError):
        return f"Error de conexión: la base de datos no fue encontrada."
    if isinstance(exc, (asyncpg.exceptions.CannotConnectNowError, ConnectionRefusedError, OSError, asyncio.TimeoutError)):
        return "Error de conexión: no se pudo establecer la conexión con el servidor PostgreSQL. Verifique el host y el puerto."
    if isinstance(exc, asyncpg.exceptions.OperationalError):
        pgerror = getattr(exc, 'pgerror', None)
        if pgerror:
            return pgerror
        if str(exc):
            return str(exc)
        return repr(exc)

    return f"Error inesperado: {str(exc)}"
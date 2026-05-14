from contextlib import contextmanager
from threading import RLock
from typing import Any

from psycopg2.pool import PoolError, ThreadedConnectionPool

from .context import TenantContext
from .exceptions import ConnectionManagerError


class ConnectionManager:
    """
    Administra pools de conexiones por municipio.

    Cada municipio obtiene su propio ThreadedConnectionPool y se identifica por
    `tenant.connection_key`, que hoy coincide con `municipality_code`.
    """

    def __init__(
        self,
        *,
        minconn: int = 1,
        maxconn: int = 5,
        pool_class=ThreadedConnectionPool,
    ) -> None:
        if int(minconn) <= 0:
            raise ConnectionManagerError("minconn debe ser mayor que cero.")
        if int(maxconn) < int(minconn):
            raise ConnectionManagerError("maxconn no puede ser menor que minconn.")
        self._minconn = int(minconn)
        self._maxconn = int(maxconn)
        self._pool_class = pool_class
        self._pools: dict[str, Any] = {}
        self._lock = RLock()
        self._closed = False

    @property
    def minconn(self) -> int:
        return self._minconn

    @property
    def maxconn(self) -> int:
        return self._maxconn

    def is_initialized_for(self, tenant: TenantContext) -> bool:
        return tenant.connection_key in self._pools

    def tenant_keys(self) -> list[str]:
        with self._lock:
            return list(self._pools.keys())

    def get_pool(self, tenant: TenantContext):
        key = tenant.connection_key
        with self._lock:
            if self._closed:
                raise ConnectionManagerError("ConnectionManager esta cerrado.")
            pool = self._pools.get(key)
            if pool is None:
                try:
                    pool = self._pool_class(
                        self._minconn,
                        self._maxconn,
                        **tenant.db_params,
                    )
                except Exception as exc:
                    raise ConnectionManagerError(
                        f"No se pudo crear pool para municipio '{tenant.municipality_code}'."
                    ) from exc
                self._pools[key] = pool
            return pool

    def get_connection(self, tenant: TenantContext):
        pool = self.get_pool(tenant)
        try:
            return pool.getconn()
        except Exception as exc:
            raise ConnectionManagerError(
                f"No se pudo obtener conexion para municipio '{tenant.municipality_code}'."
            ) from exc

    def release_connection(self, tenant: TenantContext, conn, *, close: bool = False) -> None:
        if conn is None:
            return
        key = tenant.connection_key
        with self._lock:
            pool = self._pools.get(key)
        if pool is None:
            try:
                conn.close()
            except Exception:
                pass
            return
        try:
            pool.putconn(conn, close=close)
        except Exception as exc:
            raise ConnectionManagerError(
                f"No se pudo liberar conexion para municipio '{tenant.municipality_code}'."
            ) from exc

    @contextmanager
    def connection(self, tenant: TenantContext):
        conn = self.get_connection(tenant)
        try:
            yield conn
        finally:
            self.release_connection(tenant, conn)

    def close_tenant(self, tenant_or_key: TenantContext | str) -> None:
        key = (
            tenant_or_key.connection_key
            if isinstance(tenant_or_key, TenantContext)
            else str(tenant_or_key).strip().lower()
        )
        with self._lock:
            pool = self._pools.pop(key, None)
        if pool is None:
            return
        try:
            pool.closeall()
        except Exception as exc:
            raise ConnectionManagerError(
                f"No se pudo cerrar el pool del municipio '{key}'."
            ) from exc

    def close_all(self) -> None:
        errors: list[str] = []
        with self._lock:
            pools = self._pools
            self._pools = {}
            self._closed = True
        for key, pool in pools.items():
            try:
                pool.closeall()
            except Exception:
                errors.append(key)
        if errors:
            joined = ", ".join(sorted(errors))
            raise ConnectionManagerError(
                f"No se pudieron cerrar los pools de: {joined}."
            )

    def healthcheck(self, tenant: TenantContext) -> bool:
        conn = None
        try:
            conn = self.get_connection(tenant)
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                row = cur.fetchone()
            return bool(row and row[0] == 1)
        except PoolError as exc:
            raise ConnectionManagerError(
                f"Pool no disponible para municipio '{tenant.municipality_code}'."
            ) from exc
        except Exception as exc:
            raise ConnectionManagerError(
                f"Healthcheck fallo para municipio '{tenant.municipality_code}'."
            ) from exc
        finally:
            if conn is not None:
                self.release_connection(tenant, conn)

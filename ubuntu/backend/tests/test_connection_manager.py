from tenants.connection_manager import ConnectionManager
from tenants.context import TenantContext
from tenants.models import MunicipalityDbConfig, MunicipalitySchemas


class FakeCursor:
    def execute(self, _sql):
        return None

    def fetchone(self):
        return (1,)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self):
        self.closed = False

    def cursor(self):
        return FakeCursor()

    def close(self):
        self.closed = True


class FakePool:
    def __init__(self, minconn, maxconn, **params):
        self.minconn = minconn
        self.maxconn = maxconn
        self.params = params
        self.closed = False
        self.borrowed = []
        self.released = []

    def getconn(self):
        conn = FakeConnection()
        self.borrowed.append(conn)
        return conn

    def putconn(self, conn, close=False):
        self.released.append((conn, close))
        if close:
            conn.close()

    def closeall(self):
        self.closed = True


def make_tenant(code="sucre", db_name="programacion") -> TenantContext:
    return TenantContext(
        municipality_code=code,
        municipality_name=code.title(),
        db=MunicipalityDbConfig(
            host="db.example",
            port=5432,
            db_name=db_name,
            user="postgres",
            password="secret",
        ),
        schemas=MunicipalitySchemas(),
    )


def test_connection_manager_creates_one_pool_per_tenant():
    manager = ConnectionManager(minconn=1, maxconn=3, pool_class=FakePool)
    tenant = make_tenant("sucre", "programacion")

    pool_a = manager.get_pool(tenant)
    pool_b = manager.get_pool(tenant)

    assert len(manager.tenant_keys()) == 1
    assert manager.tenant_keys()[0].startswith("sucre|")
    assert pool_a.params["dbname"] == "programacion"


def test_connection_manager_separates_pools_by_municipality():
    manager = ConnectionManager(minconn=1, maxconn=3, pool_class=FakePool)
    sucre = make_tenant("sucre", "programacion")
    neiva = make_tenant("neiva", "neiva")

    pool_sucre = manager.get_pool(sucre)
    pool_neiva = manager.get_pool(neiva)

    assert pool_sucre is not pool_neiva
    keys = sorted(manager.tenant_keys())
    assert len(keys) == 2
    assert keys[0].startswith("neiva|")
    assert keys[1].startswith("sucre|")


def test_connection_manager_releases_connection_back_to_pool():
    manager = ConnectionManager(minconn=1, maxconn=3, pool_class=FakePool)
    tenant = make_tenant()

    conn = manager.get_connection(tenant)
    manager.release_connection(tenant, conn)

    pool = manager.get_pool(tenant)
    assert len(pool.borrowed) == 1
    assert len(pool.released) == 1
    assert pool.released[0][0] is conn


def test_connection_manager_healthcheck_uses_tenant_pool():
    manager = ConnectionManager(minconn=1, maxconn=3, pool_class=FakePool)
    tenant = make_tenant()

    assert manager.healthcheck(tenant) is True


def test_connection_manager_close_all_closes_existing_pools():
    manager = ConnectionManager(minconn=1, maxconn=3, pool_class=FakePool)
    manager.get_pool(make_tenant("sucre", "programacion"))
    manager.get_pool(make_tenant("neiva", "neiva"))

    manager.close_all()

    assert manager.tenant_keys() == []

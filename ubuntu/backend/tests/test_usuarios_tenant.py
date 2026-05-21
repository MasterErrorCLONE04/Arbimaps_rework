import pytest
from fastapi import HTTPException

from routers.usuarios import (
    _app_table,
    crear_usuario,
    listar_roles,
    listar_usuarios,
)
from tenants import TenantContext
from tenants.models import MunicipalityDbConfig, MunicipalitySchemas


class FakeCursor:
    def __init__(self, plan):
        self.plan = list(plan)
        self.current = None
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if not self.plan:
            self.current = {}
            return None
        self.current = self.plan.pop(0)
        if self.current.get("raise"):
            raise self.current["raise"]
        return None

    def fetchone(self):
        return self.current.get("row")

    def fetchall(self):
        return self.current.get("rows", [])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, plan):
        self.plan = list(plan)
        self.rollback_calls = 0
        self.commit_calls = 0
        self.cursors = []

    def cursor(self, cursor_factory=None):
        cursor = FakeCursor(self.plan)
        self.cursors.append(cursor)
        return cursor

    def rollback(self):
        self.rollback_calls += 1

    def commit(self):
        self.commit_calls += 1


class UsuarioCreateStub:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def make_tenant(app_schema="arbimaps_app", municipality_code="sucre") -> TenantContext:
    return TenantContext(
        municipality_code=municipality_code,
        municipality_name=municipality_code.title(),
        db=MunicipalityDbConfig(
            host="db.example",
            port=5432,
            db_name="programacion",
            user="postgres",
            password="secret",
        ),
        schemas=MunicipalitySchemas(app=app_schema),
    )


def test_app_table_uses_tenant_app_schema():
    tenant = make_tenant(app_schema="arbimaps_neiva")

    assert _app_table(tenant, "users") == "arbimaps_neiva.users"


def test_listar_roles_uses_tenant_app_schema():
    tenant = make_tenant(app_schema="arbimaps_neiva", municipality_code="neiva")
    conn = FakeConnection([{"rows": [{"itf_code": "admin"}, {"itf_code": "otro"}]}])

    result = listar_roles({"role_code": "admin"}, tenant, conn)

    sql = conn.cursors[0].executed[0][0]
    assert result == ["admin"]
    assert "FROM arbimaps_neiva.roles" in sql


def test_listar_usuarios_rejects_non_admin():
    tenant = make_tenant()
    conn = FakeConnection([])

    with pytest.raises(HTTPException) as exc:
        listar_usuarios({"role_code": "digitalizador"}, tenant, conn)

    assert exc.value.status_code == 403


def test_crear_usuario_uses_tenant_app_schema_and_commits():
    tenant = make_tenant(app_schema="arbimaps_sucre")
    conn = FakeConnection(
        [
            {"row": {"t_id": 2}},
            {"row": None},
            {"row": {"id_global": 9, "username": "jperez", "rol": "admin", "activo": True}},
        ]
    )
    body = UsuarioCreateStub(
        username="jperez",
        first_name="Juan",
        last_name="Perez",
        rol="admin",
        email="jperez@example.com",
        activo=True,
        password="secret123",
    )

    result = crear_usuario(body, {"role_code": "admin"}, tenant, conn)

    executed = conn.cursors[0].executed
    assert result["username"] == "jperez"
    assert "FROM arbimaps_sucre.roles" in executed[0][0]
    assert "FROM arbimaps_sucre.users WHERE username = %s" in executed[1][0]
    assert "INSERT INTO arbimaps_sucre.users" in executed[2][0]
    assert conn.commit_calls == 1
    assert conn.rollback_calls == 0


def test_crear_usuario_rolls_back_on_duplicate_username():
    tenant = make_tenant(app_schema="arbimaps_sucre")
    conn = FakeConnection(
        [
            {"row": {"t_id": 2}},
            {"row": {"exists": 1}},
        ]
    )
    body = UsuarioCreateStub(
        username="jperez",
        first_name="Juan",
        last_name="Perez",
        rol="admin",
        email="jperez@example.com",
        activo=True,
        password="secret123",
    )

    with pytest.raises(HTTPException) as exc:
        crear_usuario(body, {"role_code": "admin"}, tenant, conn)

    assert exc.value.status_code == 400
    assert conn.rollback_calls == 1

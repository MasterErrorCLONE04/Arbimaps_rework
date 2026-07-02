import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routers.auth import (
    build_session_payload,
    get_current_tenant_from_session,
    get_current_user_from_session,
    signer,
)
from routers.security import hash_password
from services.session_auth import authenticate_user_for_tenant
from tenants import (
    ConnectionManager,
    MunicipalityConfig,
    MunicipalityDbConfig,
    MunicipalityRegistry,
    MunicipalitySchemas,
    TenantContext,
)
from tenants.dependencies import get_tenant_context_from_session


class FakeCursor:
    def __init__(self, row):
        self._row = row
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return None

    def fetchone(self):
        return self._row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, row):
        self._row = row
        self.last_cursor = None

    def cursor(self, cursor_factory=None):
        self.last_cursor = FakeCursor(self._row)
        return self.last_cursor

    def close(self):
        return None


class FakePool:
    def __init__(self, minconn, maxconn, **params):
        self.params = params
        self._row = None
        self.last_connection = None

    def getconn(self):
        self.last_connection = FakeConnection(self._row)
        return self.last_connection

    def putconn(self, conn, close=False):
        return None

    def closeall(self):
        return None


def make_registry() -> MunicipalityRegistry:
    return MunicipalityRegistry(
        [
            MunicipalityConfig(
                code="sucre",
                name="Sucre",
                active=True,
                db=MunicipalityDbConfig(
                    host="db.example",
                    port=5432,
                    db_name="programacion",
                    user="postgres",
                    password="secret",
                ),
                schemas=MunicipalitySchemas(),
            )
        ]
    )


def make_request(session_payload: dict | None = None, row: dict | None = None):
    registry = make_registry()
    manager = ConnectionManager(pool_class=FakePool)
    config = registry.require_active("sucre")
    tenant = TenantContext.from_config(config)
    pool = manager.get_pool(tenant)
    pool._row = row
    cookies = {}
    if session_payload is not None:
        signed = signer.sign(json.dumps(session_payload).encode("utf-8")).decode("utf-8")
        cookies["session_user"] = signed
    state = SimpleNamespace(
        municipality_registry=registry,
        tenant_connection_manager=manager,
    )
    return SimpleNamespace(
        cookies=cookies,
        app=SimpleNamespace(state=state),
        state=SimpleNamespace(),
    )


def make_session_payload() -> dict:
    return build_session_payload(
        user_id=7,
        username="jperez",
        email="jperez@example.com",
        first_name="Juan",
        last_name="Perez",
        role="admin",
        municipality_code="sucre",
        municipality_name="Sucre",
    )


def test_build_session_payload_includes_municipality():
    payload = make_session_payload()

    assert payload["user_id"] == 7
    assert payload["municipality_code"] == "sucre"
    assert payload["municipality_name"] == "Sucre"


def test_get_current_tenant_from_session_uses_cookie_municipality():
    request = make_request(
        make_session_payload(),
        {
            "id_global": 7,
            "username": "jperez",
            "email": "jperez@example.com",
            "first_name": "Juan",
            "last_name": "Perez",
            "activo": True,
            "role_code": "admin",
        },
    )

    tenant = get_current_tenant_from_session(request)

    assert tenant.municipality_code == "sucre"
    assert tenant.db.db_name == "programacion"
    assert request.state.session_tenant_code == "sucre"


def test_dependency_get_tenant_context_from_session_reuses_signed_cookie():
    request = make_request(make_session_payload())

    tenant = get_tenant_context_from_session(request, make_registry())

    assert tenant.municipality_code == "sucre"
    assert tenant.municipality_name == "Sucre"


def test_get_current_user_from_session_validates_against_same_municipality():
    request = make_request(
        make_session_payload(),
        {
            "id_global": 7,
            "username": "jperez",
            "email": "jperez@example.com",
            "first_name": "Juan",
            "last_name": "Perez",
            "activo": True,
            "role_code": "admin",
        },
    )

    user = get_current_user_from_session(request)

    assert user["username"] == "jperez"
    assert user["municipality_code"] == "sucre"
    assert user["role_code"] == "admin"


def test_get_current_user_from_session_rejects_inactive_user():
    request = make_request(
        make_session_payload(),
        {
            "id_global": 7,
            "username": "jperez",
            "email": "jperez@example.com",
            "first_name": "Juan",
            "last_name": "Perez",
            "activo": False,
            "role_code": "admin",
        },
    )

    with pytest.raises(HTTPException) as exc:
        get_current_user_from_session(request)

    assert exc.value.status_code == 401


def test_get_current_tenant_from_session_rejects_missing_municipality_code():
    request = make_request(
        {
            "user_id": 7,
            "username": "jperez",
        }
    )

    with pytest.raises(HTTPException) as exc:
        get_current_tenant_from_session(request)

    assert exc.value.status_code == 401


def test_authenticate_user_for_tenant_uses_selected_municipality_pool():
    request = make_request(
        row={
            "id_global": 7,
            "username": "jperez",
            "email": "jperez@example.com",
            "first_name": "Juan",
            "last_name": "Perez",
            "password_hash": hash_password("secret123"),
            "activo": True,
            "role_code": "admin",
        }
    )
    config = make_registry().require_active("sucre")
    tenant = TenantContext.from_config(config)

    user = authenticate_user_for_tenant(
        request,
        tenant,
        username="jperez",
        password="secret123",
    )

    pool = request.app.state.tenant_connection_manager.get_pool(tenant)
    assert user is not None
    assert pool.params["dbname"] == "programacion"
    assert pool.last_connection.last_cursor.calls[0][1] == ("jperez",)
    assert "FROM arbimaps_app.users u" in pool.last_connection.last_cursor.calls[0][0]


def test_authenticate_user_for_tenant_uses_tenant_app_schema():
    registry = MunicipalityRegistry(
        [
            MunicipalityConfig(
                code="sucre",
                name="Sucre",
                active=True,
                db=MunicipalityDbConfig(
                    host="db.example",
                    port=5432,
                    db_name="programacion",
                    user="postgres",
                    password="secret",
                ),
                schemas=MunicipalitySchemas(app="arbimaps_sucre"),
            )
        ]
    )
    manager = ConnectionManager(pool_class=FakePool)
    config = registry.require_active("sucre")
    tenant = TenantContext.from_config(config)
    pool = manager.get_pool(tenant)
    pool._row = {
        "id_global": 7,
        "username": "jperez",
        "email": "jperez@example.com",
        "first_name": "Juan",
        "last_name": "Perez",
        "password_hash": hash_password("secret123"),
        "activo": True,
        "role_code": "admin",
    }
    request = SimpleNamespace(
        cookies={},
        app=SimpleNamespace(
            state=SimpleNamespace(
                municipality_registry=registry,
                tenant_connection_manager=manager,
            )
        ),
        state=SimpleNamespace(),
    )

    user = authenticate_user_for_tenant(
        request,
        tenant,
        username="jperez",
        password="secret123",
    )

    assert user is not None
    assert "FROM arbimaps_sucre.users u" in pool.last_connection.last_cursor.calls[0][0]


def test_authenticate_user_for_tenant_rejects_wrong_password():
    request = make_request(
        row={
            "id_global": 7,
            "username": "jperez",
            "email": "jperez@example.com",
            "first_name": "Juan",
            "last_name": "Perez",
            "password_hash": hash_password("secret123"),
            "activo": True,
            "role_code": "admin",
        }
    )
    config = make_registry().require_active("sucre")
    tenant = TenantContext.from_config(config)

    user = authenticate_user_for_tenant(
        request,
        tenant,
        username="jperez",
        password="wrong-password",
    )

    assert user is None

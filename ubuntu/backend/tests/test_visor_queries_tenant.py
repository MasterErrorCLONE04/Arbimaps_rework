import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from routers.visor_queries import (
    _table_name,
    dashboard_condicion_predio,
    project_extent,
    terreno_detalle,
)
from tenants import TenantContext
from tenants.models import MunicipalityDbConfig, MunicipalitySchemas


class FakeCursor:
    def __init__(self, row=None, rows=None, fail=False):
        self.row = row
        self.rows = rows or []
        self.fail = fail
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if self.fail:
            raise RuntimeError("db failure")

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, row=None, rows=None, fail=False):
        self.row = row
        self.rows = rows or []
        self.fail = fail
        self.rollback_calls = 0
        self.cursors = []

    def cursor(self, cursor_factory=None):
        cursor = FakeCursor(row=self.row, rows=self.rows, fail=self.fail)
        self.cursors.append(cursor)
        return cursor

    def rollback(self):
        self.rollback_calls += 1


def make_tenant(schema_main="a_base_principal") -> TenantContext:
    return TenantContext(
        municipality_code="sucre",
        municipality_name="Sucre",
        db=MunicipalityDbConfig(
            host="db.example",
            port=5432,
            db_name="programacion",
            user="postgres",
            password="secret",
        ),
        schemas=MunicipalitySchemas(main=schema_main),
    )


def test_table_name_uses_tenant_main_schema():
    tenant = make_tenant("catastro_sucre")

    assert _table_name(tenant, "arb_predio") == "catastro_sucre.arb_predio"


def test_project_extent_queries_tenant_schema():
    tenant = make_tenant("catastro_sucre")
    conn = FakeConnection(
        row={"xmin": 1, "ymin": 2, "xmax": 3, "ymax": 4},
    )

    result = project_extent({"username": "jperez"}, tenant, conn)

    sql = conn.cursors[0].executed[0][0]
    assert result == {"extent": [1.0, 2.0, 3.0, 4.0]}
    assert "FROM catastro_sucre.arb_terreno" in sql


def test_terreno_detalle_uses_tenant_schema_and_returns_row():
    tenant = make_tenant("catastro_sucre")
    conn = FakeConnection(
        row={
            "terreno_id": 9,
            "predio_id": 11,
            "numero_predial_nacional": "001",
        },
    )

    result = terreno_detalle(9, {"username": "jperez"}, tenant, conn)

    sql, params = conn.cursors[0].executed[0]
    assert result["terreno_id"] == 9
    assert "FROM catastro_sucre.arb_terreno t" in sql
    assert "LEFT JOIN catastro_sucre.arb_predio p" in sql
    assert params == (9,)


def test_dashboard_condicion_predio_isolated_by_tenant():
    tenant = make_tenant("catastro_neiva")
    conn = FakeConnection(
        rows=[
            {"condicion_predio": "URBANO", "total": 10},
            {"condicion_predio": "RURAL", "total": 4},
        ],
    )

    result = dashboard_condicion_predio({"username": "jperez"}, tenant, conn)

    sql = conn.cursors[0].executed[0][0]
    assert result["items"][0]["condicion_predio"] == "URBANO"
    assert "FROM catastro_neiva.arb_predio p" in sql


def test_project_extent_rolls_back_and_raises_http_500_on_db_error():
    tenant = make_tenant("catastro_sucre")
    conn = FakeConnection(fail=True)

    with pytest.raises(HTTPException) as exc:
        project_extent({"username": "jperez"}, tenant, conn)

    assert exc.value.status_code == 500
    assert conn.rollback_calls == 1


def test_terreno_detalle_returns_404_json_when_not_found():
    tenant = make_tenant("catastro_sucre")
    conn = FakeConnection(row=None)

    result = terreno_detalle(999, {"username": "jperez"}, tenant, conn)

    assert isinstance(result, JSONResponse)
    assert result.status_code == 404

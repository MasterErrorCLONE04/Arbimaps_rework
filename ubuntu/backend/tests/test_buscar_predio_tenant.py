import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from routers.buscar_predio import (
    _qualified_table,
    predio_buscar,
    predio_detalle,
)
from tenants import TenantContext
from tenants.models import MunicipalityDbConfig, MunicipalitySchemas


class FakeCursor:
    def __init__(self, plan):
        self.plan = plan
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
        self.cursors = []

    def cursor(self, cursor_factory=None):
        cursor = FakeCursor(self.plan)
        self.cursors.append(cursor)
        return cursor

    def rollback(self):
        self.rollback_calls += 1


def make_tenant(schema_main="a_base_principal", municipality_code="sucre") -> TenantContext:
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
        schemas=MunicipalitySchemas(main=schema_main),
    )


def test_qualified_table_uses_tenant_main_schema():
    tenant = make_tenant("catastro_sucre")

    assert _qualified_table(tenant, "arb_predio") == "catastro_sucre.arb_predio"


def test_predio_buscar_requires_at_least_one_criteria():
    tenant = make_tenant("catastro_sucre")
    conn = FakeConnection([])

    result = predio_buscar(None, None, None, None, None, {"username": "jperez"}, tenant, conn)

    assert isinstance(result, JSONResponse)
    assert result.status_code == 400


def test_predio_buscar_uses_tenant_schema_and_parametrized_values():
    tenant = make_tenant("catastro_neiva", municipality_code="neiva")
    conn = FakeConnection(
        [
            {
                "rows": [
                    {
                        "t_id": 10,
                        "numero_predial_nacional": "001",
                    }
                ]
            }
        ]
    )

    result = predio_buscar("001", None, None, "CC-123", None, {"username": "jperez"}, tenant, conn)

    sql, params = conn.cursors[0].executed[0]
    assert result["features"][0]["properties"]["t_id"] == 10
    assert "FROM catastro_neiva.arb_predio p" in sql
    assert "FROM catastro_neiva.arb_derechointeresadofuente di" in sql
    assert params == ("001", "%cc123%")


def test_predio_buscar_rolls_back_and_returns_500_on_db_error():
    tenant = make_tenant("catastro_sucre")
    conn = FakeConnection([{"raise": RuntimeError("db failure")}])

    result = predio_buscar("001", None, None, None, None, {"username": "jperez"}, tenant, conn)

    assert isinstance(result, JSONResponse)
    assert result.status_code == 500
    assert conn.rollback_calls == 1


def test_predio_detalle_uses_tenant_schema_and_returns_isolated_payload():
    tenant = make_tenant("catastro_saravena", municipality_code="saravena")
    conn = FakeConnection(
        [
            {"row": {"t_id": 7, "numero_predial_nacional": "001"}},
            {"rows": [{"uc_id": 1}]},
            {"row": {"ok": False}},
            {"rows": [{"i_primer_nombre": "Juan", "i_primer_apellido": "Perez", "i_documento_identidad": "123"}]},
            {"rows": [{"direccion": "Calle 1"}]},
        ]
    )

    result = predio_detalle(7, {"username": "jperez"}, tenant, conn)

    executed = conn.cursors[0].executed
    assert result["predio"]["t_id"] == 7
    assert result["interesados"][0]["nombre_completo"] == "Juan Perez"
    assert "FROM catastro_saravena.arb_predio p" in executed[0][0]
    assert "catastro_saravena.arb_unidadconstruccion uc" in executed[1][0]


def test_predio_detalle_rolls_back_and_returns_500_on_main_query_error():
    tenant = make_tenant("catastro_sucre")
    conn = FakeConnection([{"raise": RuntimeError("db failure")}])

    result = predio_detalle(5, {"username": "jperez"}, tenant, conn)

    assert isinstance(result, JSONResponse)
    assert result.status_code == 500
    assert conn.rollback_calls == 1


def test_qualified_table_rejects_invalid_tenant_schema():
    tenant = make_tenant('bad-schema";drop')

    with pytest.raises(HTTPException) as exc:
        _qualified_table(tenant, "arb_predio")

    assert exc.value.status_code == 500

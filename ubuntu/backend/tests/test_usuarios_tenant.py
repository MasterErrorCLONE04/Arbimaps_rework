import pytest
from fastapi import HTTPException

from routers.usuarios import (
    _app_table,
    actualizar_equipo_trabajo,
    actualizar_usuario,
    crear_equipo_trabajo,
    eliminar_equipo_trabajo,
    listar_reconocedores_disponibles,
    listar_zonas_intervencion,
    crear_usuario,
    listar_equipos_trabajo,
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
        self.rowcount = 0

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if not self.plan:
            self.current = {}
            self.rowcount = 0
            return None
        self.current = self.plan.pop(0)
        if self.current.get("raise"):
            raise self.current["raise"]
        self.rowcount = self.current.get("rowcount", 0)
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


class UsuarioUpdateStub:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class EquipoTrabajoUpsertStub:
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


def test_listar_usuarios_uses_supervisor_join():
    tenant = make_tenant(app_schema="arbimaps_app", municipality_code="sucre")
    conn = FakeConnection(
        [
            {
                "rows": [
                    {
                        "id_global": 21,
                        "username": "cvallarta",
                        "email": "carlos@example.com",
                        "first_name": "Carlos",
                        "last_name": "Vallarta",
                        "rol": "reconocedor",
                        "activo": True,
                        "creado_en": "2026-05-29",
                        "supervisor_id": 7,
                        "supervisor_raw": "7",
                        "supervisor_encargado": "Juan Gonzalez",
                    }
                ]
            }
        ]
    )

    result = listar_usuarios({"role_code": "admin"}, tenant, conn)

    sql = conn.cursors[0].executed[0][0]
    assert result[0]["supervisor_encargado"] == "Juan Gonzalez"
    assert result[0]["supervisor_id"] == 7
    assert result[0]["supervisor_raw"] == "7"
    assert "LEFT JOIN arbimaps_app.users sup" in sql
    assert "sup.id_global::text = NULLIF(TRIM(u.supervisor), '')" in sql


def test_listar_equipos_trabajo_uses_tenant_app_schema():
    tenant = make_tenant(app_schema="arbimaps_app", municipality_code="sucre")
    conn = FakeConnection(
        [
            {
                "rows": [
                    {
                        "equipo_id": 11,
                        "nombre": "Equipo 1",
                        "coordinador_id": 7,
                        "coordinador_username": "coordinador1",
                        "zona_id": 3,
                        "zona_nombre": "Norte",
                        "fecha_creacion": "2026-05-29",
                        "reconocedores": [
                            {
                                "id_global": 15,
                                "username": "cvallarta",
                                "first_name": "Carlos",
                                "last_name": "Vallarta",
                            }
                        ],
                    }
                ]
            }
        ]
    )

    result = listar_equipos_trabajo({"role_code": "admin"}, tenant, conn)

    sql = conn.cursors[0].executed[0][0]
    assert result[0]["nombre"] == "Equipo 1"
    assert result[0]["equipo_id"] == 11
    assert result[0]["coordinador_username"] == "coordinador1"
    assert result[0]["zona_nombre"] == "Norte"
    assert result[0]["reconocedores"][0]["username"] == "cvallarta"
    assert "LEFT JOIN arbimaps_app.users" in sql
    assert "LEFT JOIN arbimaps_app.equipo_reconocedores" in sql
    assert "LEFT JOIN arbimaps_app.zonas_intervencion" in sql


def test_listar_zonas_intervencion_uses_tenant_app_schema():
    tenant = make_tenant(app_schema="arbimaps_app", municipality_code="sucre")
    conn = FakeConnection([{"rows": [{"t_id": 3, "nombre": "Norte"}]}])

    result = listar_zonas_intervencion({"role_code": "admin"}, tenant, conn)

    sql = conn.cursors[0].executed[0][0]
    assert result[0]["nombre"] == "Norte"
    assert "FROM arbimaps_app.zonas_intervencion" in sql


def test_listar_reconocedores_disponibles_uses_equipo_reconocedores_filter():
    tenant = make_tenant(app_schema="arbimaps_app", municipality_code="sucre")
    conn = FakeConnection([{"rows": [{"id_global": 15, "username": "cvallarta", "first_name": "Carlos", "last_name": "Vallarta"}]}])

    result = listar_reconocedores_disponibles({"role_code": "admin"}, tenant, conn, exclude_equipo_id=11)

    sql = conn.cursors[0].executed[0][0]
    assert result[0]["username"] == "cvallarta"
    assert "FROM arbimaps_app.users u" in sql
    assert "arbimaps_app.equipo_reconocedores" in sql
    assert "NOT EXISTS" in sql


def test_listar_reconocedores_disponibles_filters_by_coordinator():
    tenant = make_tenant(app_schema="arbimaps_app", municipality_code="sucre")
    conn = FakeConnection([{"rows": [{"id_global": 15, "username": "cvallarta", "first_name": "Carlos", "last_name": "Vallarta", "supervisor": "7"}]}])

    result = listar_reconocedores_disponibles({"role_code": "admin"}, tenant, conn, coordinador_id=7)

    sql = conn.cursors[0].executed[0][0]
    assert result[0]["supervisor"] == "7"
    assert "NULLIF(TRIM(u.supervisor), '') = %s::text" in sql


def test_actualizar_equipo_trabajo_uses_tenant_app_schema_and_syncs_members():
    tenant = make_tenant(app_schema="arbimaps_app", municipality_code="sucre")
    conn = FakeConnection(
        [
            {"row": {"t_id": 11, "nombre": "Equipo 1"}},
            {"row": {"id_global": 7, "username": "coord1", "first_name": "Coord", "last_name": "One", "rol": "coordinador", "activo": True}},
            {"row": {"t_id": 3, "nombre": "Norte"}},
            {"rows": [{"id_global": 15, "username": "cvallarta", "first_name": "Carlos", "last_name": "Vallarta", "rol": "reconocedor", "activo": True, "supervisor": "7"}]},
            {"rows": []},
            {"rows": []},
            {"rows": []},
            {"row": {"t_id": 11, "nombre": "Equipo actualizado", "coordinador_id": 7, "coordinador_username": "coord1", "zona_id": 3, "zona_nombre": "Norte", "fecha_creacion": "2026-05-29", "reconocedores": [{"id_global": 15, "username": "cvallarta", "first_name": "Carlos", "last_name": "Vallarta"}]}},
        ]
    )
    body = EquipoTrabajoUpsertStub(
        nombre="Equipo actualizado",
        coordinador_id=7,
        zona_id=3,
        reconocedor_ids=[15],
    )

    result = actualizar_equipo_trabajo(11, body, {"role_code": "admin"}, tenant, conn)

    sqls = [sql for cursor in conn.cursors for sql, _ in cursor.executed]
    assert result["equipo_id"] == 11
    assert any("FOR UPDATE" in sql and "FROM arbimaps_app.equipos_trabajo" in sql for sql in sqls)
    assert any("UPDATE arbimaps_app.equipos_trabajo" in sql for sql in sqls)
    assert any("DELETE FROM arbimaps_app.equipo_reconocedores" in sql for sql in sqls)
    assert any("INSERT INTO arbimaps_app.equipo_reconocedores" in sql for sql in sqls)


def test_crear_equipo_trabajo_uses_tenant_app_schema_and_syncs_members():
    tenant = make_tenant(app_schema="arbimaps_app", municipality_code="sucre")
    conn = FakeConnection(
        [
            {"row": {"id_global": 7, "username": "coord1", "first_name": "Coord", "last_name": "One", "rol": "coordinador", "activo": True}},
            {"row": {"t_id": 3, "nombre": "Norte"}},
            {"rows": [{"id_global": 15, "username": "cvallarta", "first_name": "Carlos", "last_name": "Vallarta", "rol": "reconocedor", "activo": True, "supervisor": "7"}]},
            {"rows": []},
            {"row": {"t_id": 12}},
            {"rows": []},
            {"rows": []},
            {"row": {"equipo_id": 12, "nombre": "Equipo nuevo", "coordinador_id": 7, "coordinador_username": "coord1", "zona_id": 3, "zona_nombre": "Norte", "fecha_creacion": "2026-05-29", "reconocedores": [{"id_global": 15, "username": "cvallarta", "first_name": "Carlos", "last_name": "Vallarta"}]}},
        ]
    )
    body = EquipoTrabajoUpsertStub(
        nombre="Equipo nuevo",
        coordinador_id=7,
        zona_id=3,
        reconocedor_ids=[15],
    )

    result = crear_equipo_trabajo(body, {"role_code": "admin"}, tenant, conn)

    sqls = [sql for cursor in conn.cursors for sql, _ in cursor.executed]
    assert result["equipo_id"] == 12
    assert any("INSERT INTO arbimaps_app.equipos_trabajo" in sql for sql in sqls)
    assert any("DELETE FROM arbimaps_app.equipo_reconocedores" in sql for sql in sqls)
    assert any("INSERT INTO arbimaps_app.equipo_reconocedores" in sql for sql in sqls)


def test_eliminar_equipo_trabajo_uses_backup_table_and_removes_relations():
    tenant = make_tenant(app_schema="arbimaps_app", municipality_code="sucre")
    conn = FakeConnection(
        [
            {
                "row": {
                    "t_id": 11,
                    "nombre": "Equipo 1",
                    "coordinador_id": 7,
                    "coordinador_username": "coordinador1",
                    "zona_id": 3,
                    "zona_nombre": "Norte",
                    "fecha_creacion": "2026-05-29",
                }
            },
            {
                "row": {
                    "t_id": 11,
                    "nombre": "Equipo 1",
                    "coordinador_id": 7,
                    "coordinador_username": "coordinador1",
                    "zona_id": 3,
                    "zona_nombre": "Norte",
                    "fecha_creacion": "2026-05-29",
                }
            },
            {"rows": [{"equipo_id": 11, "reconocedor_id": 15, "id_global": 15, "username": "cvallarta", "first_name": "Carlos", "last_name": "Vallarta", "email": "c@example.com", "rol": "reconocedor"}]},
        ]
    )

    result = eliminar_equipo_trabajo(11, {"role_code": "admin", "username": "admin1"}, tenant, conn)

    sqls = [sql for cursor in conn.cursors for sql, _ in cursor.executed]
    assert result["status"] == "ok"
    assert any("SELECT *" in sql and "FROM arbimaps_app.equipos_trabajo" in sql and "FOR UPDATE" in sql for sql in sqls)
    assert any("LEFT JOIN arbimaps_app.users" in sql for sql in sqls)
    assert any("INSERT INTO arbimaps_app.equipos_trabajo_backup" in sql for sql in sqls)
    assert any("DELETE FROM arbimaps_app.equipo_reconocedores" in sql for sql in sqls)
    assert any("DELETE FROM arbimaps_app.equipos_trabajo" in sql for sql in sqls)


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


def test_crear_reconocedor_uses_supervisor_id():
    tenant = make_tenant(app_schema="arbimaps_sucre")
    conn = FakeConnection(
        [
            {"row": {"t_id": 4}},
            {"row": {"id_global": 7, "rol": "coordinador", "activo": True}},
            {"row": None},
            {"row": {"id_global": 9, "username": "cvallarta", "rol": "reconocedor", "activo": True}},
        ]
    )
    body = UsuarioCreateStub(
        username="cvallarta",
        first_name="Carlos",
        last_name="Vallarta",
        rol="reconocedor",
        email="cvallarta@example.com",
        supervisor_id=7,
        activo=True,
        password="secret123",
    )

    result = crear_usuario(body, {"role_code": "admin"}, tenant, conn)

    executed = conn.cursors[0].executed
    assert result["username"] == "cvallarta"
    assert "supervisor" in executed[3][0]
    assert executed[3][1][6] == 7


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


def test_actualizar_usuario_libera_reconocedores_al_demover_coordinador():
    tenant = make_tenant(app_schema="arbimaps_app")
    conn = FakeConnection(
        [
            {"row": {"rol": "coordinador"}},
            {"row": {"t_id": 2}},
            {"row": {"id_global": 7, "username": "coord1", "email": "coord1@example.com", "first_name": "Coord", "last_name": "Uno", "rol": "consulta", "activo": True, "creado_en": "2026-05-29", "supervisor": None}},
            {"rowcount": 2},
        ]
    )
    body = UsuarioUpdateStub(
        first_name="Coord",
        last_name="Uno",
        rol="consulta",
        email="coord1@example.com",
        activo=True,
        password=None,
        supervisor_id=None,
    )

    result = actualizar_usuario(7, body, {"role_code": "admin"}, tenant, conn)

    sqls = [sql for cursor in conn.cursors for sql, _ in cursor.executed]
    assert result["id_global"] == 7
    assert any("SELECT rol" in sql and "FROM arbimaps_app.users" in sql for sql in sqls)
    assert any("UPDATE arbimaps_app.users" in sql and "SET supervisor = NULL" in sql for sql in sqls)
    assert any("WHERE NULLIF(TRIM(supervisor), '') = %s::text" in sql for sql in sqls)
    assert conn.commit_calls == 1
    assert conn.rollback_calls == 0

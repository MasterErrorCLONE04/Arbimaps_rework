from contextlib import contextmanager
from io import BytesIO

from fastapi import UploadFile

from routers import asignaciones_detalle
from tenants import TenantContext
from tenants.models import MunicipalityDbConfig, MunicipalitySchemas


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._fetchone = [None]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self._conn.executed_sql.append(str(sql))
        if "to_regclass('pg_temp._arb_sync_predio_map')" in sql:
            self._fetchone = [None]
        elif "to_regclass('pg_temp._arb_sync_selected_predio')" in sql:
            self._fetchone = [1] if self._conn.has_sync_scope else [None]
        else:
            self._fetchone = [0]

    def fetchone(self):
        return self._fetchone

    def fetchall(self):
        return []


class _FakeConn:
    def __init__(self, *, has_sync_scope=False):
        self.autocommit = True
        self.has_sync_scope = has_sync_scope
        self.executed_sql = []

    def cursor(self, *args, **kwargs):
        return _FakeCursor(self)

    def commit(self):
        return None

    def rollback(self):
        return None


class _FakeConnectionManager:
    def __init__(self, *, has_sync_scope=False):
        self.has_sync_scope = has_sync_scope
        self.connections = []

    @contextmanager
    def connection(self, tenant):
        conn = _FakeConn(has_sync_scope=self.has_sync_scope)
        self.connections.append(conn)
        yield conn


def _tenant() -> TenantContext:
    return TenantContext(
        municipality_code="sucre",
        municipality_name="Sucre",
        db=MunicipalityDbConfig(
            host="db.example",
            port=5432,
            db_name="sucre",
            user="user",
            password="pass",
        ),
        schemas=MunicipalitySchemas(
            app="arbimaps_app",
            main="a_base_principal",
            work="b_asignaciones_arb",
            history="c_base_historico",
            workflow="d_workflow",
        ),
    )


def _patch_common(monkeypatch):
    monkeypatch.setattr(
        asignaciones_detalle,
        "_copy_upload_and_sha256",
        lambda archivo, tmp_path: "sha256-test",
    )
    monkeypatch.setattr(
        asignaciones_detalle,
        "_validate_retorno_xtf_rules",
        lambda tmp_path: {"status": "ok"},
    )
    monkeypatch.setattr(
        asignaciones_detalle,
        "_ensure_workspace_ready_for_export",
        lambda tenant, manager, asignacion_id, usuario_log: "ws_asg_1",
    )
    monkeypatch.setattr(
        asignaciones_detalle,
        "_build_retorno_datasetname",
        lambda dataset, version: f"{dataset}_ret_{version}",
    )
    monkeypatch.setattr(
        asignaciones_detalle,
        "_allow_retorno_sync_with_missing_predios",
        lambda: False,
    )
    monkeypatch.setattr(asignaciones_detalle, "_log_sync_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(asignaciones_detalle, "_xtf_validation_note", lambda result: "ok")
    monkeypatch.setattr(asignaciones_detalle, "_validation_history_message", lambda result: "ok")
    monkeypatch.setattr(asignaciones_detalle, "_validator_pipeline_labels", lambda: ["rules"])
    monkeypatch.setattr(asignaciones_detalle, "_extract_rule_ids_from_validation", lambda result: [])
    monkeypatch.setattr(asignaciones_detalle, "_retorno_correlation_id", lambda asignacion_id: "corr-test")
    monkeypatch.setattr(
        asignaciones_detalle,
        "_ili2pg_import",
        lambda conn, tenant, schema, datasetname, xtf_path: None,
    )

    monkeypatch.setattr(
        asignaciones_detalle.asignaciones_repo,
        "get_asignacion_work_dataset",
        lambda conn, tenant, asignacion_id: {
            "id": asignacion_id,
            "work_datasetname": "ws_asg_1",
            "usuario_asignado": "coord1",
        },
    )
    monkeypatch.setattr(asignaciones_detalle.asignaciones_repo, "ensure_asignacion_tables", lambda conn, tenant: None)
    monkeypatch.setattr(
        asignaciones_detalle.asignaciones_repo,
        "get_recent_retorno_by_sha256",
        lambda conn, tenant, asignacion_id, sha256: None,
    )
    monkeypatch.setattr(
        asignaciones_detalle.asignaciones_repo,
        "allocate_asignacion_retorno_version",
        lambda conn, tenant, asignacion_id: 2,
    )
    monkeypatch.setattr(
        asignaciones_detalle.asignaciones_repo,
        "create_asignacion_retorno",
        lambda conn, tenant, asignacion_id, version, dataset, **kwargs: {"id": 55},
    )
    monkeypatch.setattr(asignaciones_detalle.asignaciones_repo, "update_asignacion_retorno", lambda *args, **kwargs: None)
    monkeypatch.setattr(asignaciones_detalle.asignaciones_repo, "insert_asignacion_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(asignaciones_detalle.asignaciones_repo, "safe_log_event", lambda *args, **kwargs: None)

    monkeypatch.setattr(
        asignaciones_detalle.workspace_service,
        "cleanup_orphan_workspace_datasets",
        lambda conn, tenant, schema_work, limit=25: {},
    )
    monkeypatch.setattr(
        asignaciones_detalle.workspace_service,
        "remove_workspace_dataset",
        lambda conn, datasetname, schema_work: {},
    )
    monkeypatch.setattr(
        asignaciones_detalle.workspace_service,
        "validate_workspace_dataset_health",
        lambda schema_work, datasetname, conn=None, tenant=None: None,
    )
    monkeypatch.setattr(
        asignaciones_detalle.workspace_service,
        "validate_workspace_assignment_coverage",
        lambda asignacion_id, schema_work, datasetname, conn=None, tenant=None, allow_missing_predios=False: {
            "expected_predios": 1,
            "covered_predios": 1,
            "missing_predios": 0,
            "missing_predios_preview": [],
        },
    )


def test_procesar_retorno_xtf_passes_tenant_to_prune_workspace_predios(monkeypatch):
    _patch_common(monkeypatch)
    captured = {}

    def _prune(conn, tenant, asignacion_id, datasetname, schema_work, **kwargs):
        captured["tenant"] = tenant
        captured["asignacion_id"] = asignacion_id
        captured["datasetname"] = datasetname
        captured["schema_work"] = schema_work
        return 0

    monkeypatch.setattr(asignaciones_detalle.workspace_service, "prune_workspace_predios", _prune)
    monkeypatch.setattr(
        asignaciones_detalle.workspace_service,
        "sync_workspace_predios_to_main",
        lambda conn, tenant, asignacion_id, datasetname, schema_main, schema_work: 1,
    )

    tenant = _tenant()
    archivo = UploadFile(filename="retorno.xtf", file=BytesIO(b"<xtf/>"))

    result = asignaciones_detalle._procesar_retorno_xtf(
        tenant,
        _FakeConnectionManager(),
        136,
        archivo,
        {"username": "coord1", "role": "coordinador"},
        publish_to_main=True,
    )

    assert result["asignacion_id"] == 136
    assert captured == {
        "tenant": tenant,
        "asignacion_id": 136,
        "datasetname": "ws_asg_1_ret_2",
        "schema_work": "b_asignaciones_arb",
    }


def test_procesar_retorno_xtf_workspace_refreshes_predio_ids_with_conn_and_tenant(monkeypatch):
    _patch_common(monkeypatch)
    captured = {}

    monkeypatch.setattr(
        asignaciones_detalle.workspace_service,
        "prune_workspace_predios",
        lambda conn, tenant, asignacion_id, datasetname, schema_work, **kwargs: 0,
    )

    def _actualizar(conn, tenant, asignacion_id, *, strict=False):
        captured["conn_type"] = type(conn).__name__
        captured["tenant"] = tenant
        captured["asignacion_id"] = asignacion_id
        captured["strict"] = strict

    monkeypatch.setattr(
        asignaciones_detalle.workspace_service,
        "actualizar_predio_ids_desde_workspace",
        _actualizar,
    )

    tenant = _tenant()
    archivo = UploadFile(filename="retorno.xtf", file=BytesIO(b"<xtf/>"))

    result = asignaciones_detalle._procesar_retorno_xtf(
        tenant,
        _FakeConnectionManager(),
        136,
        archivo,
        {"username": "digit1", "role": "digitalizador"},
        publish_to_main=False,
    )

    assert result["asignacion_id"] == 136
    assert captured == {
        "conn_type": "_FakeConn",
        "tenant": tenant,
        "asignacion_id": 136,
        "strict": False,
    }


def test_procesar_retorno_xtf_publish_main_interpolates_assignment_table_sql(monkeypatch):
    _patch_common(monkeypatch)
    logged_events = []
    monkeypatch.setattr(
        asignaciones_detalle.workspace_service,
        "prune_workspace_predios",
        lambda conn, tenant, asignacion_id, datasetname, schema_work, **kwargs: 0,
    )
    monkeypatch.setattr(
        asignaciones_detalle.workspace_service,
        "sync_workspace_predios_to_main",
        lambda conn, tenant, asignacion_id, datasetname, schema_main, schema_work: 1,
    )
    monkeypatch.setattr(
        asignaciones_detalle.asignaciones_repo,
        "safe_log_event",
        lambda conn, tenant, asignacion_id, evento, mensaje, usuario=None: logged_events.append(evento),
    )
    monkeypatch.setattr(
        asignaciones_detalle.asignaciones_repo,
        "insert_asignacion_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("insert_asignacion_event should not be called")),
    )

    tenant = _tenant()
    manager = _FakeConnectionManager(has_sync_scope=True)
    archivo = UploadFile(filename="retorno.xtf", file=BytesIO(b"<xtf/>"))

    result = asignaciones_detalle._procesar_retorno_xtf(
        tenant,
        manager,
        136,
        archivo,
        {"username": "coord1", "role": "coordinador"},
        publish_to_main=True,
    )

    assert result["asignacion_id"] == 136
    assert "PUBLICACION_MAIN" in logged_events
    sync_sql = "\n".join(
        sql
        for conn in manager.connections
        for sql in conn.executed_sql
        if "_arb_sync_selected_predio sp" in sql
    )
    assert "FROM {" not in sync_sql
    assert "arbimaps_app.asignacion_predio" in sync_sql

import json

import pytest

from tenants import (
    MunicipalityConfigError,
    MunicipalityInactiveError,
    MunicipalityNotFoundError,
    MunicipalityRegistry,
    TenantContext,
)
from tenants.loader import load_municipality_configs


@pytest.fixture
def clean_municipality_env(monkeypatch):
    keys = [
        "MUNICIPALITIES",
        "MUNICIPALITY_CONFIG_FILE",
        "MUNICIPALITY_SUCRE_NAME",
        "MUNICIPALITY_SUCRE_ACTIVE",
        "MUNICIPALITY_SUCRE_DB_HOST",
        "MUNICIPALITY_SUCRE_DB_PORT",
        "MUNICIPALITY_SUCRE_DB_NAME",
        "MUNICIPALITY_SUCRE_DB_USER",
        "MUNICIPALITY_SUCRE_DB_PASSWORD",
        "MUNICIPALITY_SUCRE_SCHEMA_APP",
        "MUNICIPALITY_SUCRE_SCHEMA_MAIN",
        "MUNICIPALITY_SUCRE_SCHEMA_WORK",
        "MUNICIPALITY_SUCRE_SCHEMA_HISTORY",
        "MUNICIPALITY_SUCRE_SCHEMA_WORKFLOW",
        "MUNICIPALITY_NEIVA_NAME",
        "MUNICIPALITY_NEIVA_DB_HOST",
        "MUNICIPALITY_NEIVA_DB_NAME",
        "MUNICIPALITY_NEIVA_DB_USER",
        "MUNICIPALITY_NEIVA_DB_PASSWORD",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)


def test_registry_loads_from_env(clean_municipality_env, monkeypatch):
    monkeypatch.setenv("MUNICIPALITIES", "sucre,neiva")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_NAME", "Sucre")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_DB_HOST", "db.example")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_DB_NAME", "programacion")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_DB_USER", "postgres")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_DB_PASSWORD", "secret")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_SCHEMA_WORKFLOW", "custom_workflow")
    monkeypatch.setenv("MUNICIPALITY_NEIVA_NAME", "Neiva")
    monkeypatch.setenv("MUNICIPALITY_NEIVA_DB_HOST", "db2.example")
    monkeypatch.setenv("MUNICIPALITY_NEIVA_DB_NAME", "neiva")
    monkeypatch.setenv("MUNICIPALITY_NEIVA_DB_USER", "postgres")
    monkeypatch.setenv("MUNICIPALITY_NEIVA_DB_PASSWORD", "secret2")

    registry = MunicipalityRegistry(load_municipality_configs())

    assert registry.codes() == ["sucre", "neiva"]
    assert registry.get("sucre").db.db_name == "programacion"
    assert registry.get("sucre").schemas.workflow == "custom_workflow"
    assert registry.require_active("neiva").schemas.work == "b_asignaciones_arb"
    assert registry.require_active("neiva").schemas.workflow == "d_workflow"


def test_registry_rejects_unknown_code(clean_municipality_env, monkeypatch):
    monkeypatch.setenv("MUNICIPALITIES", "sucre")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_NAME", "Sucre")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_DB_HOST", "db.example")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_DB_NAME", "programacion")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_DB_USER", "postgres")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_DB_PASSWORD", "secret")

    registry = MunicipalityRegistry(load_municipality_configs())

    with pytest.raises(MunicipalityNotFoundError):
        registry.get("bogota")


def test_registry_rejects_inactive_code(clean_municipality_env, monkeypatch):
    monkeypatch.setenv("MUNICIPALITIES", "sucre")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_NAME", "Sucre")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_ACTIVE", "false")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_DB_HOST", "db.example")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_DB_NAME", "programacion")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_DB_USER", "postgres")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_DB_PASSWORD", "secret")

    registry = MunicipalityRegistry(load_municipality_configs())

    with pytest.raises(MunicipalityInactiveError):
        registry.require_active("sucre")


def test_registry_loads_from_json_file(clean_municipality_env, monkeypatch, tmp_path):
    config_path = tmp_path / "municipalities.json"
    config_path.write_text(
        json.dumps(
            {
                "municipalities": [
                    {
                        "code": "saravena",
                        "name": "Saravena",
                        "active": True,
                        "db": {
                            "host": "db.example",
                            "port": 5432,
                            "db_name": "saravena",
                            "user": "postgres",
                            "password": "secret",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MUNICIPALITY_CONFIG_FILE", str(config_path))

    registry = MunicipalityRegistry.from_sources()

    assert registry.codes(active_only=True) == ["saravena"]
    assert registry.get("saravena").db.db_name == "saravena"


def test_tenant_context_derives_from_config(clean_municipality_env, monkeypatch):
    monkeypatch.setenv("MUNICIPALITIES", "sucre")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_NAME", "Sucre")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_DB_HOST", "db.example")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_DB_NAME", "programacion")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_DB_USER", "postgres")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_DB_PASSWORD", "secret")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_WMS_BASE_URL", "https://maps.example/wms")
    monkeypatch.setenv("MUNICIPALITY_SUCRE_GEOSERVER_LAYERS", "A_Base_Principal:Base_Principal")

    registry = MunicipalityRegistry(load_municipality_configs())
    tenant = TenantContext.from_config(registry.require_active("sucre"))

    assert tenant.municipality_code == "sucre"
    assert tenant.municipality_name == "Sucre"
    assert tenant.connection_key == "sucre"
    assert tenant.db_params["dbname"] == "programacion"
    assert tenant.schemas.work == "b_asignaciones_arb"

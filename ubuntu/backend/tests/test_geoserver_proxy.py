import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

from routers.pages import _default_visor_geoserver_layers
from routers.proxy import _resolve_geoserver_root, _resolve_wms_base_url
from tenants.context import TenantContext
from tenants.models import MunicipalityDbConfig, MunicipalitySchemas


def _tenant(
    *,
    geoserver_base_url: str = "",
    geoserver_workspace: str = "",
    wms_base_url: str = "",
    geoserver_layers: str = "",
) -> TenantContext:
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
        schemas=MunicipalitySchemas(),
        geoserver_base_url=geoserver_base_url,
        geoserver_workspace=geoserver_workspace,
        wms_base_url=wms_base_url,
        geoserver_layers=geoserver_layers,
    )


def test_default_visor_geoserver_layers_uses_workspace_when_layers_missing():
    tenant = _tenant(geoserver_workspace="SUCRE")

    assert _default_visor_geoserver_layers(tenant) == "SUCRE:Base_Principal"


def test_default_visor_geoserver_layers_prefers_configured_layers():
    tenant = _tenant(geoserver_layers="SARAVENA:SARAVENA")

    assert _default_visor_geoserver_layers(tenant) == "SARAVENA:SARAVENA"


def test_resolve_wms_base_url_prefers_tenant_wms_url(monkeypatch):
    tenant = _tenant(wms_base_url="https://desarrollo.arbimaps.com/geoserver/SUCRE/wms")
    monkeypatch.setattr("routers.proxy.get_current_tenant_from_session", lambda request: tenant)

    assert (
        _resolve_wms_base_url(object())
        == "https://desarrollo.arbimaps.com/geoserver/SUCRE/wms"
    )


def test_resolve_wms_base_url_builds_from_workspace_when_needed(monkeypatch):
    tenant = _tenant(
        geoserver_base_url="https://desarrollo.arbimaps.com/geoserver",
        geoserver_workspace="ALMAGUER",
    )
    monkeypatch.setattr("routers.proxy.get_current_tenant_from_session", lambda request: tenant)

    assert (
        _resolve_wms_base_url(object())
        == "https://desarrollo.arbimaps.com/geoserver/ALMAGUER/wms"
    )


def test_resolve_geoserver_root_uses_tenant_base_url(monkeypatch):
    tenant = _tenant(geoserver_base_url="https://desarrollo.arbimaps.com/geoserver")
    monkeypatch.setattr("routers.proxy.get_current_tenant_from_session", lambda request: tenant)

    assert _resolve_geoserver_root(object()) == "https://desarrollo.arbimaps.com/geoserver"


def test_resolve_geoserver_root_falls_back_to_wms_url(monkeypatch):
    tenant = _tenant(wms_base_url="https://desarrollo.arbimaps.com/geoserver/SUCRE/wms")
    monkeypatch.setattr("routers.proxy.get_current_tenant_from_session", lambda request: tenant)

    assert _resolve_geoserver_root(object()) == "https://desarrollo.arbimaps.com/geoserver"


def test_resolve_wms_base_url_falls_back_without_session(monkeypatch):
    monkeypatch.setattr(
        "routers.proxy.get_current_tenant_from_session",
        lambda request: (_ for _ in ()).throw(HTTPException(status_code=401)),
    )

    assert _resolve_wms_base_url(object()).startswith("http")


@pytest.mark.anyio
async def test_proxy_geoserver_rejects_path_traversal():
    request = MagicMock()
    request.body = AsyncMock(return_value=b"")
    request.query_params = {}
    request.method = "GET"

    from routers.proxy import proxy_geoserver

    with pytest.raises(HTTPException) as exc:
        await proxy_geoserver("dir/../../admin", request)
    assert exc.value.status_code == 400
    assert exc.value.detail == "Path no permitido"

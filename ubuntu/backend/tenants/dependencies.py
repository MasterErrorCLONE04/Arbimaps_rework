from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, status

from .bootstrap import APP_STATE_KEY, CONNECTION_MANAGER_STATE_KEY
from .connection_manager import ConnectionManager
from .context import TenantContext
from .exceptions import ConnectionManagerError
from .exceptions import (
    MunicipalityConfigError,
    MunicipalityInactiveError,
    MunicipalityNotFoundError,
)
from .models import MunicipalityConfig
from .registry import MunicipalityRegistry


MUNICIPALITY_CODE_QUERY = Query(
    ...,
    alias="municipality_code",
    min_length=1,
    description="Codigo del municipio objetivo.",
)


def get_municipality_registry(request: Request) -> MunicipalityRegistry:
    registry = getattr(request.app.state, APP_STATE_KEY, None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Municipality registry no inicializado en app.state.",
        )
    if not isinstance(registry, MunicipalityRegistry):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Municipality registry invalido en app.state.",
        )
    return registry


def get_municipality_code(
    municipality_code: Annotated[str, MUNICIPALITY_CODE_QUERY],
) -> str:
    code = (municipality_code or "").strip().lower()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="municipality_code es obligatorio.",
        )
    return code


def resolve_active_municipality_config(
    municipality_code: Annotated[str, Depends(get_municipality_code)],
    registry: Annotated[MunicipalityRegistry, Depends(get_municipality_registry)],
) -> MunicipalityConfig:
    try:
        return registry.require_active(municipality_code)
    except MunicipalityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Municipio no registrado.",
        ) from exc
    except MunicipalityInactiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Municipio inactivo.",
        ) from exc
    except MunicipalityConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


def resolve_municipality_config(
    municipality_code: Annotated[str, Depends(get_municipality_code)],
    registry: Annotated[MunicipalityRegistry, Depends(get_municipality_registry)],
) -> MunicipalityConfig:
    try:
        return registry.get(municipality_code)
    except MunicipalityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Municipio no registrado.",
        ) from exc
    except MunicipalityConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


def get_tenant_context(
    config: Annotated[MunicipalityConfig, Depends(resolve_active_municipality_config)],
) -> TenantContext:
    return TenantContext.from_config(config)


def get_optional_tenant_context_from_state(request: Request) -> TenantContext | None:
    tenant = getattr(request.state, "tenant_context", None)
    return tenant if isinstance(tenant, TenantContext) else None


def get_tenant_context_from_session(
    request: Request,
    registry: Annotated[MunicipalityRegistry, Depends(get_municipality_registry)],
) -> TenantContext:
    del registry
    from services.session_auth import get_current_tenant_from_session

    return get_current_tenant_from_session(request)


def get_connection_manager(request: Request) -> ConnectionManager:
    manager = getattr(request.app.state, CONNECTION_MANAGER_STATE_KEY, None)
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ConnectionManager no inicializado en app.state.",
        )
    if not isinstance(manager, ConnectionManager):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ConnectionManager invalido en app.state.",
        )
    return manager


def get_tenant_db_connection(
    tenant: Annotated[TenantContext, Depends(get_tenant_context_from_session)],
    manager: Annotated[ConnectionManager, Depends(get_connection_manager)],
):
    conn = None
    try:
        conn = manager.get_connection(tenant)
    except ConnectionManagerError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    try:
        yield conn
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if conn is not None:
            try:
                manager.release_connection(tenant, conn)
            except ConnectionManagerError:
                try:
                    conn.close()
                except Exception:
                    pass

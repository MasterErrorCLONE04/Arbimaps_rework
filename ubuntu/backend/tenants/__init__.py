from .bootstrap import (
    get_connection_manager,
    get_registry,
    init_connection_manager,
    init_municipality_registry,
)
from .connection_manager import ConnectionManager
from .context import TenantContext
from .exceptions import (
    ConnectionManagerError,
    ConnectionManagerNotInitializedError,
    MunicipalityConfigError,
    MunicipalityInactiveError,
    MunicipalityNotFoundError,
)
from .models import MunicipalityConfig, MunicipalityDbConfig, MunicipalitySchemas
from .registry import MunicipalityRegistry

_dependency_exports = []
try:
    from .dependencies import (
        get_municipality_code,
        get_municipality_registry,
        get_optional_tenant_context_from_state,
        get_connection_manager as get_connection_manager_dependency,
        get_tenant_context,
        get_tenant_db_connection,
        get_tenant_context_from_session,
        resolve_active_municipality_config,
        resolve_municipality_config,
    )

    _dependency_exports = [
        "get_municipality_code",
        "get_municipality_registry",
        "get_optional_tenant_context_from_state",
        "get_connection_manager_dependency",
        "get_tenant_context",
        "get_tenant_db_connection",
        "get_tenant_context_from_session",
        "resolve_active_municipality_config",
        "resolve_municipality_config",
    ]
except ModuleNotFoundError:
    # Permite reutilizar el nucleo de tenancy aunque FastAPI no este cargado
    # en el entorno actual de pruebas o scripting.
    pass

__all__ = [
    "ConnectionManager",
    "ConnectionManagerError",
    "ConnectionManagerNotInitializedError",
    "MunicipalityConfig",
    "MunicipalityConfigError",
    "MunicipalityInactiveError",
    "MunicipalityDbConfig",
    "MunicipalityNotFoundError",
    "MunicipalityRegistry",
    "MunicipalitySchemas",
    "TenantContext",
    "get_connection_manager",
    "get_registry",
    "init_connection_manager",
    "init_municipality_registry",
]
__all__.extend(_dependency_exports)

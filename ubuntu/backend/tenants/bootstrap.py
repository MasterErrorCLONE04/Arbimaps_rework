from .registry import MunicipalityRegistry


APP_STATE_KEY = "municipality_registry"
CONNECTION_MANAGER_STATE_KEY = "tenant_connection_manager"


def init_municipality_registry(app) -> MunicipalityRegistry:
    registry = MunicipalityRegistry.from_sources()
    setattr(app.state, APP_STATE_KEY, registry)
    return registry


def get_registry(app) -> MunicipalityRegistry:
    registry = getattr(app.state, APP_STATE_KEY, None)
    if registry is None:
        registry = init_municipality_registry(app)
    return registry


def init_connection_manager(app, connection_manager) -> None:
    setattr(app.state, CONNECTION_MANAGER_STATE_KEY, connection_manager)


def get_connection_manager(app):
    return getattr(app.state, CONNECTION_MANAGER_STATE_KEY, None)

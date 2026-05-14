class MunicipalityConfigError(RuntimeError):
    """Configuracion invalida del registro de municipios."""


class MunicipalityNotFoundError(KeyError):
    """Municipio no registrado o no disponible."""


class MunicipalityInactiveError(MunicipalityConfigError):
    """Municipio registrado pero inactivo."""


class ConnectionManagerError(RuntimeError):
    """Fallo general del pool o ciclo de vida de conexiones por tenant."""


class ConnectionManagerNotInitializedError(ConnectionManagerError):
    """ConnectionManager no disponible en app.state."""

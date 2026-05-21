from dataclasses import dataclass, field

from .exceptions import MunicipalityConfigError


def _clean_code(value: str) -> str:
    return (value or "").strip().lower()


def _clean_name(value: str) -> str:
    return (value or "").strip()


@dataclass(frozen=True)
class MunicipalityDbConfig:
    host: str
    port: int
    db_name: str
    user: str
    password: str
    sslmode: str = "require"
    connect_timeout: int = 10
    keepalives: int = 1
    keepalives_idle: int = 30
    keepalives_interval: int = 10
    keepalives_count: int = 5

    def __post_init__(self) -> None:
        if not _clean_name(self.host):
            raise MunicipalityConfigError("DB host es obligatorio.")
        if not _clean_name(self.db_name):
            raise MunicipalityConfigError("DB name es obligatorio.")
        if not _clean_name(self.user):
            raise MunicipalityConfigError("DB user es obligatorio.")
        if not _clean_name(self.password):
            raise MunicipalityConfigError("DB password es obligatorio.")
        if int(self.port) <= 0:
            raise MunicipalityConfigError("DB port debe ser mayor que cero.")


@dataclass(frozen=True)
class MunicipalitySchemas:
    app: str = "arbimaps_app"
    main: str = "a_base_principal"
    work: str = "b_asignaciones_arb"
    history: str = "c_base_historico"
    workflow: str = "d_workflow"

    def __post_init__(self) -> None:
        for field_name in ("app", "main", "work", "history", "workflow"):
            if not _clean_name(getattr(self, field_name)):
                raise MunicipalityConfigError(
                    f"Schema '{field_name}' es obligatorio para el municipio."
                )


@dataclass(frozen=True)
class MunicipalityConfig:
    code: str
    name: str
    active: bool
    db: MunicipalityDbConfig
    schemas: MunicipalitySchemas = field(default_factory=MunicipalitySchemas)
    wms_base_url: str = ""
    geoserver_layers: str = ""

    def __post_init__(self) -> None:
        code = _clean_code(self.code)
        name = _clean_name(self.name)
        if not code:
            raise MunicipalityConfigError("Municipality code es obligatorio.")
        if not name:
            raise MunicipalityConfigError(
                f"Municipality name es obligatorio para '{self.code}'."
            )
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "wms_base_url", _clean_name(self.wms_base_url))
        object.__setattr__(self, "geoserver_layers", _clean_name(self.geoserver_layers))

    @property
    def db_params(self) -> dict:
        return {
            "host": self.db.host,
            "port": self.db.port,
            "dbname": self.db.db_name,
            "user": self.db.user,
            "password": self.db.password,
            "sslmode": self.db.sslmode,
            "connect_timeout": self.db.connect_timeout,
            "keepalives": self.db.keepalives,
            "keepalives_idle": self.db.keepalives_idle,
            "keepalives_interval": self.db.keepalives_interval,
            "keepalives_count": self.db.keepalives_count,
        }

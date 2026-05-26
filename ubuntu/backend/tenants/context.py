from dataclasses import dataclass

from .models import MunicipalityConfig, MunicipalityDbConfig, MunicipalitySchemas


@dataclass(frozen=True)
class TenantContext:
    municipality_code: str
    municipality_name: str
    db: MunicipalityDbConfig
    schemas: MunicipalitySchemas
    geoserver_base_url: str = ""
    geoserver_workspace: str = ""
    wms_base_url: str = ""
    geoserver_layers: str = ""

    @classmethod
    def from_config(cls, config: MunicipalityConfig) -> "TenantContext":
        if config.db is None:
            raise ValueError(
                f"Municipio '{config.code}' no tiene configuracion DB utilizable."
            )
        if config.schemas is None:
            raise ValueError(
                f"Municipio '{config.code}' no tiene schemas configurados."
            )
        return cls(
            municipality_code=config.code,
            municipality_name=config.name,
            db=config.db,
            schemas=config.schemas,
            geoserver_base_url=config.geoserver_base_url,
            geoserver_workspace=config.geoserver_workspace,
            wms_base_url=config.wms_base_url,
            geoserver_layers=config.geoserver_layers,
        )

    @property
    def connection_key(self) -> str:
        """
        Clave estable para pools por tenant y origen fisico de base.
        """
        host = (self.db.host or "").strip().lower()
        db_name = (self.db.db_name or "").strip().lower()
        return f"{self.municipality_code}|{host}|{self.db.port}|{db_name}"

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
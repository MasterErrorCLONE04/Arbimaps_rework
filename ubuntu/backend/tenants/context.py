from dataclasses import dataclass

from .models import MunicipalityConfig, MunicipalityDbConfig, MunicipalitySchemas


@dataclass(frozen=True)
class TenantContext:
    municipality_code: str
    municipality_name: str
    db: MunicipalityDbConfig
    schemas: MunicipalitySchemas
    wms_base_url: str = ""
    geoserver_layers: str = ""

    @classmethod
    def from_config(cls, config: MunicipalityConfig) -> "TenantContext":
        return cls(
            municipality_code=config.code,
            municipality_name=config.name,
            db=config.db,
            schemas=config.schemas,
            wms_base_url=config.wms_base_url,
            geoserver_layers=config.geoserver_layers,
        )

    @property
    def connection_key(self) -> str:
        """
        Clave estable prevista para futuros pools en ConnectionManager.
        """
        return self.municipality_code

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

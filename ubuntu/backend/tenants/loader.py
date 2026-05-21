import json
import os
from pathlib import Path

from core.env_loader import load_env_file_if_present

from .exceptions import MunicipalityConfigError
from .models import MunicipalityConfig, MunicipalityDbConfig, MunicipalitySchemas


load_env_file_if_present()

DEFAULT_CODES = ("sucre", "saravena", "almaguer", "neiva")
DEFAULT_NAMES = {
    "sucre": "Sucre",
    "saravena": "Saravena",
    "almaguer": "Almaguer",
    "neiva": "Neiva",
}
DEFAULT_DB_NAMES = {
    "sucre": "programacion",
    "saravena": "saravena",
    "almaguer": "almaguer",
    "neiva": "neiva",
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on", "si"}


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise MunicipalityConfigError(
            f"Variable '{name}' debe ser numerica. Valor actual: {raw!r}"
        ) from exc


def _env_str(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()


def _codes_from_env() -> list[str]:
    raw = _env_str("MUNICIPALITIES")
    if not raw:
        return list(DEFAULT_CODES)
    codes = []
    seen = set()
    for token in raw.split(","):
        code = token.strip().lower()
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes


def _municipality_prefix(code: str) -> str:
    return f"MUNICIPALITY_{code.strip().upper()}"


def _load_from_env(code: str) -> MunicipalityConfig:
    prefix = _municipality_prefix(code)
    db = MunicipalityDbConfig(
        host=_env_str(f"{prefix}_DB_HOST", _env_str("DB_HOST", "localhost")),
        port=_env_int(f"{prefix}_DB_PORT", _env_int("DB_PORT", 5432)),
        db_name=_env_str(f"{prefix}_DB_NAME", DEFAULT_DB_NAMES.get(code, "")),
        user=_env_str(f"{prefix}_DB_USER", _env_str("DB_USER", "postgres")),
        password=_env_str(f"{prefix}_DB_PASSWORD", _env_str("DB_PASSWORD", _env_str("DB_PASS"))),
        sslmode=_env_str(f"{prefix}_DB_SSLMODE", _env_str("DB_SSLMODE", "require")),
        connect_timeout=_env_int(
            f"{prefix}_DB_CONNECT_TIMEOUT",
            _env_int("DB_CONNECT_TIMEOUT", 10),
        ),
        keepalives=_env_int(f"{prefix}_DB_KEEPALIVES", _env_int("DB_KEEPALIVES", 1)),
        keepalives_idle=_env_int(
            f"{prefix}_DB_KEEPALIVES_IDLE",
            _env_int("DB_KEEPALIVES_IDLE", 30),
        ),
        keepalives_interval=_env_int(
            f"{prefix}_DB_KEEPALIVES_INTERVAL",
            _env_int("DB_KEEPALIVES_INTERVAL", 10),
        ),
        keepalives_count=_env_int(
            f"{prefix}_DB_KEEPALIVES_COUNT",
            _env_int("DB_KEEPALIVES_COUNT", 5),
        ),
    )
    schemas = MunicipalitySchemas(
        app=_env_str(f"{prefix}_SCHEMA_APP", "arbimaps_app"),
        main=_env_str(f"{prefix}_SCHEMA_MAIN", "a_base_principal"),
        work=_env_str(f"{prefix}_SCHEMA_WORK", "b_asignaciones_arb"),
        history=_env_str(f"{prefix}_SCHEMA_HISTORY", "c_base_historico"),
        workflow=_env_str(f"{prefix}_SCHEMA_WORKFLOW", "d_workflow"),
    )
    return MunicipalityConfig(
        code=code,
        name=_env_str(f"{prefix}_NAME", DEFAULT_NAMES.get(code, code.title())),
        active=_env_bool(f"{prefix}_ACTIVE", True),
        db=db,
        schemas=schemas,
        wms_base_url=_env_str(f"{prefix}_WMS_BASE_URL"),
        geoserver_layers=_env_str(f"{prefix}_GEOSERVER_LAYERS"),
    )


def _config_file_path() -> Path | None:
    raw = _env_str("MUNICIPALITY_CONFIG_FILE")
    if not raw:
        return None
    return Path(raw)


def _load_from_file(path: Path) -> list[MunicipalityConfig]:
    if not path.exists() or not path.is_file():
        raise MunicipalityConfigError(
            f"No existe MUNICIPALITY_CONFIG_FILE: {str(path)!r}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MunicipalityConfigError(
            f"No se pudo leer el archivo de municipios: {str(path)!r}"
        ) from exc

    items = payload.get("municipalities") if isinstance(payload, dict) else payload
    if not isinstance(items, list) or not items:
        raise MunicipalityConfigError(
            "El archivo de municipios debe contener una lista no vacia."
        )

    configs: list[MunicipalityConfig] = []
    for item in items:
        if not isinstance(item, dict):
            raise MunicipalityConfigError("Cada municipio del archivo debe ser un objeto.")
        db_data = item.get("db") or {}
        schemas_data = item.get("schemas") or {}
        configs.append(
            MunicipalityConfig(
                code=str(item.get("code", "")),
                name=str(item.get("name", "")),
                active=bool(item.get("active", True)),
                db=MunicipalityDbConfig(
                    host=str(db_data.get("host", "")),
                    port=int(db_data.get("port", 5432)),
                    db_name=str(db_data.get("db_name", "")),
                    user=str(db_data.get("user", "")),
                    password=str(db_data.get("password", "")),
                    sslmode=str(db_data.get("sslmode", "require")),
                    connect_timeout=int(db_data.get("connect_timeout", 10)),
                    keepalives=int(db_data.get("keepalives", 1)),
                    keepalives_idle=int(db_data.get("keepalives_idle", 30)),
                    keepalives_interval=int(db_data.get("keepalives_interval", 10)),
                    keepalives_count=int(db_data.get("keepalives_count", 5)),
                ),
                schemas=MunicipalitySchemas(
                    app=str(schemas_data.get("app", "arbimaps_app")),
                    main=str(schemas_data.get("main", "a_base_principal")),
                    work=str(schemas_data.get("work", "b_asignaciones_arb")),
                    history=str(schemas_data.get("history", "c_base_historico")),
                    workflow=str(schemas_data.get("workflow", "d_workflow")),
                ),
                wms_base_url=str(item.get("wms_base_url", "")),
                geoserver_layers=str(item.get("geoserver_layers", "")),
            )
        )
    return configs


def load_municipality_configs() -> list[MunicipalityConfig]:
    config_file = _config_file_path()
    if config_file is not None:
        return _load_from_file(config_file)
    return [_load_from_env(code) for code in _codes_from_env()]

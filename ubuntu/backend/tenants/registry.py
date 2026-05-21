from collections.abc import Iterable

from .exceptions import (
    MunicipalityConfigError,
    MunicipalityInactiveError,
    MunicipalityNotFoundError,
)
from .loader import load_municipality_configs
from .models import MunicipalityConfig


class MunicipalityRegistry:
    def __init__(self, configs: Iterable[MunicipalityConfig]):
        items = list(configs)
        if not items:
            raise MunicipalityConfigError("No hay municipios configurados.")

        self._by_code: dict[str, MunicipalityConfig] = {}
        for config in items:
            code = config.code
            if code in self._by_code:
                raise MunicipalityConfigError(
                    f"Municipality code duplicado en registry: {code!r}"
                )
            self._by_code[code] = config

    @classmethod
    def from_sources(cls) -> "MunicipalityRegistry":
        return cls(load_municipality_configs())

    def all(self) -> list[MunicipalityConfig]:
        return list(self._by_code.values())

    def active(self) -> list[MunicipalityConfig]:
        return [config for config in self._by_code.values() if config.active]

    def codes(self, *, active_only: bool = False) -> list[str]:
        source = self.active() if active_only else self.all()
        return [config.code for config in source]

    def has(self, municipality_code: str) -> bool:
        code = (municipality_code or "").strip().lower()
        return code in self._by_code

    def is_active(self, municipality_code: str) -> bool:
        code = self._normalize_code(municipality_code)
        config = self._by_code.get(code)
        return bool(config and config.active)

    def get(self, municipality_code: str) -> MunicipalityConfig:
        code = self._normalize_code(municipality_code)
        try:
            return self._by_code[code]
        except KeyError as exc:
            raise MunicipalityNotFoundError(
                f"Municipio no registrado: {municipality_code!r}"
            ) from exc

    def require_active(self, municipality_code: str) -> MunicipalityConfig:
        config = self.get(municipality_code)
        if not config.active:
            raise MunicipalityInactiveError(
                f"Municipio inactivo: {config.code!r}"
            )
        return config

    def validate_code(self, municipality_code: str, *, active_only: bool = True) -> str:
        config = self.require_active(municipality_code) if active_only else self.get(municipality_code)
        return config.code

    @staticmethod
    def _normalize_code(municipality_code: str) -> str:
        code = (municipality_code or "").strip().lower()
        if not code:
            raise MunicipalityConfigError("municipality_code es obligatorio.")
        return code

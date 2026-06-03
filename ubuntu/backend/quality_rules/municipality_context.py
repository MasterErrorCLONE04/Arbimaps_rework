from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MunicipalityValidationContext:
    tenant_code: str
    municipality_name: str
    department_code: str
    department_name: str
    municipality_code: str
    orip_code: str | None = None


DEFAULT_MUNICIPALITY_CODE = "neiva"

MUNICIPALITY_VALIDATION_CONTEXTS: dict[str, MunicipalityValidationContext] = {
    "sucre": MunicipalityValidationContext(
        tenant_code="sucre",
        municipality_name="SUCRE",
        department_code="19",
        department_name="CAUCA",
        municipality_code="785",
        orip_code="122",
    ),
    "saravena": MunicipalityValidationContext(
        tenant_code="saravena",
        municipality_name="SARAVENA",
        department_code="81",
        department_name="ARAUCA",
        municipality_code="736",
        orip_code="410",
    ),
    "almaguer": MunicipalityValidationContext(
        tenant_code="almaguer",
        municipality_name="ALMAGUER",
        department_code="19",
        department_name="CAUCA",
        municipality_code="022",
        orip_code="122",
    ),
    "neiva": MunicipalityValidationContext(
        tenant_code="neiva",
        municipality_name="NEIVA",
        department_code="41",
        department_name="HUILA",
        municipality_code="001",
        orip_code="200",
    ),
}


def _normalize_municipality_code(value: object) -> str:
    return str(value or "").strip().lower()


def get_municipality_validation_context(
    municipality_code: object,
) -> MunicipalityValidationContext:
    normalized = _normalize_municipality_code(municipality_code)
    if normalized in MUNICIPALITY_VALIDATION_CONTEXTS:
        return MUNICIPALITY_VALIDATION_CONTEXTS[normalized]
    return MUNICIPALITY_VALIDATION_CONTEXTS[DEFAULT_MUNICIPALITY_CODE]


def get_dataset_municipality_context(dataset: object) -> MunicipalityValidationContext:
    metadata = getattr(dataset, "metadata", None)
    municipality_code: Any = None
    if isinstance(metadata, dict):
        municipality_code = metadata.get("municipality_code")
    if not municipality_code:
        municipality_code = getattr(dataset, "municipality_code", "")
    return get_municipality_validation_context(municipality_code)

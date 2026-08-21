from __future__ import annotations

from collections import Counter
import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class MunicipalityValidationContext:
    tenant_code: str
    municipality_name: str
    department_code: str
    department_name: str
    municipality_code: str
    orip_code: str | None = None


# Contextos conocidos. Son atajos, no un limite de municipios soportados.
MUNICIPALITY_VALIDATION_CONTEXTS: dict[str, MunicipalityValidationContext] = {
    "sucre": MunicipalityValidationContext("sucre", "SUCRE", "19", "CAUCA", "785", "122"),
    "saravena": MunicipalityValidationContext("saravena", "SARAVENA", "81", "ARAUCA", "736", "410"),
    "almaguer": MunicipalityValidationContext("almaguer", "ALMAGUER", "19", "CAUCA", "022", "122"),
    "neiva": MunicipalityValidationContext("neiva", "NEIVA", "41", "HUILA", "001", "200"),
}

_MUNICIPALITY_BY_DANE = {
    (ctx.department_code, ctx.municipality_code): ctx
    for ctx in MUNICIPALITY_VALIDATION_CONTEXTS.values()
}


def _normalize_municipality_code(value: object) -> str:
    return str(value or "").strip().lower()


def _normalize_key(value: object) -> str:
    text = str(value or "").strip().lower()
    return "".join(ch for ch in text if ch.isalnum())


def _row_value(row: dict[str, Any], *names: str) -> Any:
    wanted = {_normalize_key(name) for name in names}
    for key, value in row.items():
        if _normalize_key(key) in wanted and value not in (None, ""):
            return value
    return None


def _iter_predios(dataset: object) -> Iterable[dict[str, Any]]:
    seen: set[int] = set()
    for table in ("ARB_Predio", "arb_predio", "A_Predio", "a_predio"):
        try:
            rows = dataset.get_records(table)
        except Exception:
            continue
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            marker = id(row)
            if marker in seen:
                continue
            seen.add(marker)
            yield row


def _infer_dane_from_dataset(dataset: object) -> tuple[str, str] | None:
    counts: Counter[tuple[str, str]] = Counter()
    for row in _iter_predios(dataset):
        npn = _row_value(row, "numero_predial", "Numero_Predial", "numero_predial_nacional")
        if npn is None:
            continue
        digits = str(npn).strip()
        if len(digits) >= 5 and digits[:5].isdigit():
            counts[(digits[:2], digits[2:5])] += 1
    return counts.most_common(1)[0][0] if counts else None


def _infer_orip_from_dataset(dataset: object) -> str | None:
    # Para municipios no registrados, la matricula inmobiliaria aporta un respaldo
    # independiente de Codigo_orip. Se usa solamente el prefijo registral predominante.
    counts: Counter[str] = Counter()
    for row in _iter_predios(dataset):
        value = _row_value(row, "matricula_inmobiliaria", "Matricula_Inmobiliaria", "matricula")
        if value is None:
            continue
        text = str(value).strip()
        match = re.match(r"^(\d{3})\s*[-–]", text)
        if match:
            counts[match.group(1)] += 1
    return counts.most_common(1)[0][0] if counts else None


def get_municipality_validation_context(
    municipality_code: object,
) -> MunicipalityValidationContext | None:
    """Resuelve un contexto conocido sin aplicar un municipio por defecto."""
    normalized = _normalize_municipality_code(municipality_code)
    if normalized in MUNICIPALITY_VALIDATION_CONTEXTS:
        return MUNICIPALITY_VALIDATION_CONTEXTS[normalized]

    # Permite que el llamador envie DANE 5 digitos: 41001, 19785, etc.
    digits = "".join(ch for ch in normalized if ch.isdigit())
    if len(digits) == 5:
        known = _MUNICIPALITY_BY_DANE.get((digits[:2], digits[2:5]))
        if known is not None:
            return known
        return MunicipalityValidationContext(
            tenant_code=f"dane_{digits}",
            municipality_name=digits[2:5],
            department_code=digits[:2],
            department_name=digits[:2],
            municipality_code=digits[2:5],
            orip_code=None,
        )

    return None


def get_dataset_municipality_context(dataset: object) -> MunicipalityValidationContext:
    """Obtiene contexto municipal portable.

    Prioridad:
    1. Metadatos explicitos del dataset (tenant/DANE/ORIP).
    2. Contextos conocidos.
    3. DANE predominante inferido de los NPN del propio archivo.
    4. ORIP explicito; si no existe, prefijo registral predominante de matricula.

    Nunca cae silenciosamente en Neiva para un municipio desconocido.
    """
    metadata = getattr(dataset, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}

    tenant_raw = metadata.get("municipality_code") or metadata.get("tenant_code") or getattr(dataset, "municipality_code", "")
    known = get_municipality_validation_context(tenant_raw)

    department = str(metadata.get("department_code") or metadata.get("codigo_departamento") or "").strip()
    municipality = str(metadata.get("dane_municipality_code") or metadata.get("codigo_municipio") or "").strip()
    orip = str(metadata.get("orip_code") or metadata.get("codigo_orip") or "").strip() or None
    tenant = _normalize_municipality_code(tenant_raw)
    department_name = str(metadata.get("department_name") or "").strip()
    municipality_name = str(metadata.get("municipality_name") or "").strip()

    if known is not None:
        department = department or known.department_code
        municipality = municipality or known.municipality_code
        orip = orip or known.orip_code
        tenant = tenant or known.tenant_code
        department_name = department_name or known.department_name
        municipality_name = municipality_name or known.municipality_name

    if not department or not municipality:
        inferred = _infer_dane_from_dataset(dataset)
        if inferred is not None:
            dep_inf, mun_inf = inferred
            department = department or dep_inf
            municipality = municipality or mun_inf

    known_dane = _MUNICIPALITY_BY_DANE.get((department, municipality))
    if known_dane is not None:
        orip = orip or known_dane.orip_code
        tenant = tenant or known_dane.tenant_code
        department_name = department_name or known_dane.department_name
        municipality_name = municipality_name or known_dane.municipality_name

    if not orip:
        orip = _infer_orip_from_dataset(dataset)

    dane = f"{department}{municipality}" if department and municipality else ""
    return MunicipalityValidationContext(
        tenant_code=tenant or (f"dane_{dane}" if dane else "desconocido"),
        municipality_name=municipality_name or municipality,
        department_code=department,
        department_name=department_name or department,
        municipality_code=municipality,
        orip_code=orip,
    )

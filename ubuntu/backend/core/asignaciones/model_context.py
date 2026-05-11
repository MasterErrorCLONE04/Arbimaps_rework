from dataclasses import dataclass
from typing import FrozenSet, Optional

from .config import (
    ASIG_MODEL,
    DATASETNAME_MAIN_DEFAULT_ARB,
    REQUIRED_BASKETS_ARB,
    SCHEMA_MAIN_ARB,
    SCHEMA_WORK_ARB,
)


@dataclass(frozen=True)
class AssignmentModelContext:
    name: str
    schema_main: str
    schema_work: str
    datasetname_main_default: str
    required_baskets: FrozenSet[str]
    predio_table: str
    predio_numero_field: str


def get_assignment_model_context(model: Optional[str] = None) -> AssignmentModelContext:
    target = (model or ASIG_MODEL).strip().lower()
    if target != "arb":
        raise ValueError(f"Modelo de asignaciones no soportado: {target!r}")
    return AssignmentModelContext(
        name="arb",
        schema_main=SCHEMA_MAIN_ARB,
        schema_work=SCHEMA_WORK_ARB,
        datasetname_main_default=DATASETNAME_MAIN_DEFAULT_ARB,
        required_baskets=REQUIRED_BASKETS_ARB,
        predio_table="arb_predio",
        predio_numero_field="numero_predial",
    )


ASIG_MODEL_CONTEXT = get_assignment_model_context()

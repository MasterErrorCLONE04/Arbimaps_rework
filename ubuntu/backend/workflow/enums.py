from __future__ import annotations

from enum import Enum
import unicodedata


class _StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


def normalize_token(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = text.encode("ascii", "ignore").decode("ascii")
    return ascii_text.strip().lower()


class WorkflowState(_StrEnum):
    SIN_ASIGNAR = "SIN_ASIGNAR"
    EN_CAMPO = "EN_CAMPO"
    CONTROL_CALIDAD_1 = "CONTROL_CALIDAD_1"
    DEVUELTO = "DEVUELTO"
    APROBACION = "APROBACION"
    SINCRONIZACION = "SINCRONIZACION"
    SINCRONIZADO = "SINCRONIZADO"


class WorkspaceState(_StrEnum):
    PENDING = "PENDING"
    BUILDING = "BUILDING"
    READY = "READY"
    ERROR = "ERROR"
    ARCHIVED = "ARCHIVED"


class RetornoState(_StrEnum):
    NONE = "NONE"
    UPLOADED = "UPLOADED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"
    ERROR = "ERROR"


class SyncState(_StrEnum):
    NONE = "NONE"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class WorkflowEvent(_StrEnum):
    ASSIGN = "ASSIGN"
    START_FIELDWORK = "START_FIELDWORK"
    SUBMIT_FOR_QA = "SUBMIT_FOR_QA"
    RETURN_TO_FIELD = "RETURN_TO_FIELD"
    RESUBMIT_FROM_RETURN = "RESUBMIT_FROM_RETURN"
    APPROVE = "APPROVE"
    START_SYNC = "START_SYNC"
    MARK_SYNCED = "MARK_SYNCED"
    REOPEN = "REOPEN"
    REASSIGN = "REASSIGN"
    CANCEL_ASSIGNMENT = "CANCEL_ASSIGNMENT"


class WorkflowRole(_StrEnum):
    ADMINISTRADOR = "administrador"
    LIDER = "lider"
    COORDINADOR = "coordinador"
    ASIGNADOR = "asignador"
    RECONOCEDOR = "reconocedor"
    CONSULTA = "consulta"
    SOPORTE = "soporte"

    @classmethod
    def parse(cls, value: str | WorkflowRole) -> "WorkflowRole":
        if isinstance(value, cls):
            return value

        normalized = normalize_token(value)
        alias_map = {
            "admin": cls.ADMINISTRADOR,
            "administrador": cls.ADMINISTRADOR,
            "lider": cls.LIDER,
            "lider_reconocimiento": cls.LIDER,
            "lider_tecnico": cls.LIDER,
            "coordinador": cls.COORDINADOR,
            "asignador": cls.ASIGNADOR,
            "reconocedor": cls.RECONOCEDOR,
            "digitalizador": cls.RECONOCEDOR,
            "consulta": cls.CONSULTA,
            "soporte": cls.SOPORTE,
        }
        role = alias_map.get(normalized)
        if role is None:
            raise ValueError(f"Rol no soportado: {value!r}")
        return role

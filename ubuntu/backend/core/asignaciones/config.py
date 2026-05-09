import os
import tempfile


def env_true(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "si"}


def env_csv(name: str, default: str = "") -> frozenset[str]:
    raw = os.getenv(name, default) or ""
    return frozenset(
        token.strip().lower()
        for token in raw.split(",")
        if token and token.strip()
    )


SUPPORTED_MODELS = frozenset({"arb"})
ASIG_MODEL = os.getenv("ASIG_MODEL", "arb").strip().lower()
if ASIG_MODEL not in SUPPORTED_MODELS:
    allowed = ", ".join(sorted(SUPPORTED_MODELS))
    raise RuntimeError(f"ASIG_MODEL invalido: {ASIG_MODEL!r}. Valores permitidos: {allowed}")

SCHEMA_MAIN_ARB = os.getenv("ASIG_SCHEMA_MAIN_ARB", "a_base_principal")
SCHEMA_WORK_ARB = os.getenv("ASIG_SCHEMA_WORK_ARB", "b_asignaciones_arb")
DATASETNAME_MAIN_DEFAULT_ARB = os.getenv("ASIG_DATASETNAME_MAIN_DEFAULT_ARB", "")

# Compatibilidad: mantener aliases planos para el flujo activo arb-only.
SCHEMA_MAIN = os.getenv("ASIG_SCHEMA_MAIN", SCHEMA_MAIN_ARB)
SCHEMA_WORK = os.getenv("ASIG_SCHEMA_WORK", SCHEMA_WORK_ARB)
DATASETNAME_MAIN_DEFAULT = os.getenv("ASIG_DATASETNAME_MAIN_DEFAULT", DATASETNAME_MAIN_DEFAULT_ARB)
ILI2PG_CMD = os.getenv("ILI2PG_CMD", "").strip()
ILI2PG_TIMEOUT_SEC = int(os.getenv("ILI2PG_TIMEOUT_SEC", "600"))
ASIG_SKIP_WORKSPACE = env_true("ASIG_SKIP_WORKSPACE", False)

REQUIRED_BASKETS_ARB = frozenset()
REQUIRED_BASKETS = REQUIRED_BASKETS_ARB

ASIG_EXPORT_JOB_DIR = os.getenv(
    "ASIG_EXPORT_JOB_DIR",
    os.path.join(tempfile.gettempdir(), "asignacion_exports"),
)
ASIG_EXPORT_JOB_TTL_HOURS = int(os.getenv("ASIG_EXPORT_JOB_TTL_HOURS", "24"))

ASIG_ARB_INTERNAL_ONLY = env_true("ASIG_ARB_INTERNAL_ONLY", False)
ASIG_ARB_INTERNAL_USERS = env_csv("ASIG_ARB_INTERNAL_USERS")
ASIG_ARB_INTERNAL_EMAILS = env_csv("ASIG_ARB_INTERNAL_EMAILS")
ASIG_ARB_INTERNAL_IDS = env_csv("ASIG_ARB_INTERNAL_IDS")
ASIG_ARB_INTERNAL_ROLES = env_csv("ASIG_ARB_INTERNAL_ROLES", "admin")

import os
from pathlib import Path


_ENV_LOADED = False


def _candidate_env_paths() -> list[Path]:
    explicit = os.getenv("APP_ENV_FILE", "").strip()
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit))

    project_root = Path(__file__).resolve().parents[1]
    paths.append(project_root / ".env")
    paths.append(Path.cwd() / ".env")

    unique: list[Path] = []
    seen = set()
    for p in paths:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def load_env_file_if_present() -> None:
    """
    Carga variables desde .env si existen y no están ya definidas en el entorno.
    Esto evita depender exclusivamente de EnvironmentFile en systemd.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    for path in _candidate_env_paths():
        if not path.exists() or not path.is_file():
            continue
        try:
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.lower().startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key:
                    continue
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                os.environ.setdefault(key, value)
            _ENV_LOADED = True
            return
        except Exception:
            # Si falla parseando un .env, intentamos con el siguiente candidato.
            continue

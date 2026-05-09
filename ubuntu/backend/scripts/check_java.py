from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.xtf_validation_service import XTFValidationService


def main() -> None:
    service = XTFValidationService()
    java_bin = service._resolve_java_bin()

    if java_bin:
        print(f"Java detectado en: {java_bin}")
    else:
        print("Java no encontrado. Instala Java 11+ o configura JAVA_BIN/JAVA_HOME.")


if __name__ == "__main__":
    main()

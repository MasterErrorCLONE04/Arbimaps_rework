from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .base import RuleDefinition


def _normalize_list(value: str | None) -> list[str]:
    if not value:
        return []
    parts = [chunk.strip() for chunk in str(value).replace("\r", "").split("\n")]
    return [chunk for chunk in parts if chunk]


def load_rule_group(slug: str, base_dir: Path | None = None) -> list[RuleDefinition]:
    base = base_dir or Path("resource/quality_rules")
    path = base / f"{slug}.json"
    if not path.exists():
        raise FileNotFoundError(f"No se encontr? el archivo de reglas: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    definitions: list[RuleDefinition] = []
    for entry in payload.get("rules", []):
        definition = RuleDefinition(
            rule_id=str(entry.get("id")),
            description=str(entry.get("description") or ""),
            classes=_normalize_list(entry.get("classes")),
            variables=_normalize_list(entry.get("variables")),
            technical_rule=entry.get("technical_rule"),
            component=entry.get("component"),
            sheet_slug=entry.get("sheet_slug"),
        )
        definitions.append(definition)
    return definitions

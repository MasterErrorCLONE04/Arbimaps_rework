from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .base import DatasetReader


class InMemoryDataset(DatasetReader):
    def __init__(
        self,
        tables: dict[str, Iterable[dict[str, Any]]],
        metadata: dict[str, Any] | None = None,
    ):
        self._tables = {name.lower(): list(rows) for name, rows in tables.items()}
        self.metadata = metadata or {}

    def get_records(self, table: str) -> Iterable[dict[str, Any]]:
        return list(self._tables.get(table.lower(), []))

    def has_table(self, table: str) -> bool:
        return table.lower() in self._tables


class EmptyDataset(DatasetReader):
    def get_records(self, table: str) -> Iterable[dict[str, Any]]:  # pragma: no cover - trivial
        return []

    def has_table(self, table: str) -> bool:
        return False


from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol


@dataclass(slots=True)
class RuleDefinition:
    rule_id: str
    description: str
    classes: list[str]
    variables: list[str]
    technical_rule: str | None = None
    component: str | None = None
    sheet_slug: str | None = None


@dataclass(slots=True)
class RuleIssue:
    rule_id: str
    object_ref: str | None
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RuleResult:
    rule_id: str
    issues: list[RuleIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.issues


class DatasetReader(Protocol):
    def get_records(self, table: str) -> Iterable[dict[str, Any]]: ...

    def has_table(self, table: str) -> bool: ...


RuleCallable = Callable[[DatasetReader], list[RuleIssue]]


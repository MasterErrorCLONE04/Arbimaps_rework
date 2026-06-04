from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .base import DatasetReader, RuleCallable, RuleResult
from . import administrativo
from . import juridico
from . import fisico
from . import economico
from . import topologico
from . import novedades
from . import estructura
from . import complementarias
from . import obligatorias

@dataclass(slots=True)
class Component:
    slug: str
    default_rule_ids: frozenset[str]
    rule_functions: Mapping[str, RuleCallable]

    def run(
        self,
        dataset: DatasetReader,
        rule_ids: Iterable[str] | None = None,
        excluded_rule_ids: Iterable[str] | None = None,
    ) -> list[RuleResult]:
        selected = list(rule_ids) if rule_ids else list(self.default_rule_ids)
        excluded = {str(rule_id).strip() for rule_id in (excluded_rule_ids or [])}
        results: list[RuleResult] = []
        for rule_id in selected:
            if rule_id in excluded:
                continue
            func = self.rule_functions.get(rule_id)
            if not func:
                continue
            issues = func(dataset)
            results.append(RuleResult(rule_id=rule_id, issues=issues))
        return results


@dataclass(slots=True)
class ComponentResult:
    component: str
    result: RuleResult


COMPONENTS: dict[str, Component] = {
    administrativo.COMPONENT_SLUG: Component(
        slug=administrativo.COMPONENT_SLUG,
        default_rule_ids=administrativo.DEFAULT_RULE_IDS,
        rule_functions=administrativo.RULE_FUNCTIONS,
    ),

    juridico.COMPONENT_SLUG: Component(
        slug=juridico.COMPONENT_SLUG,
        default_rule_ids=juridico.DEFAULT_RULE_IDS,
        rule_functions=juridico.RULE_FUNCTIONS,
    ),

    fisico.COMPONENT_SLUG: Component(
        slug=fisico.COMPONENT_SLUG,
        default_rule_ids=fisico.DEFAULT_RULE_IDS,
        rule_functions=fisico.RULE_FUNCTIONS,
    ),

    economico.COMPONENT_SLUG: Component(
        slug=economico.COMPONENT_SLUG,
        default_rule_ids=economico.DEFAULT_RULE_IDS,
        rule_functions=economico.RULE_FUNCTIONS,
    ),

    topologico.COMPONENT_SLUG: Component(
        slug=topologico.COMPONENT_SLUG,
        default_rule_ids=topologico.DEFAULT_RULE_IDS,
        rule_functions=topologico.RULE_FUNCTIONS,
    ),

    novedades.COMPONENT_SLUG: Component(
        slug=novedades.COMPONENT_SLUG,
        default_rule_ids=novedades.DEFAULT_RULE_IDS,
        rule_functions=novedades.RULE_FUNCTIONS,
    ),

    estructura.COMPONENT_SLUG: Component(
        slug=estructura.COMPONENT_SLUG,
        default_rule_ids=estructura.DEFAULT_RULE_IDS,
        rule_functions=estructura.RULE_FUNCTIONS,
    ),

    complementarias.COMPONENT_SLUG: Component(
        slug=complementarias.COMPONENT_SLUG,
        default_rule_ids=complementarias.DEFAULT_RULE_IDS,
        rule_functions=complementarias.RULE_FUNCTIONS,
    ),

    obligatorias.COMPONENT_SLUG: Component(
        slug=obligatorias.COMPONENT_SLUG,
        default_rule_ids=obligatorias.DEFAULT_RULE_IDS,
        rule_functions=obligatorias.RULE_FUNCTIONS,
    ),
}

def run_all_components(
    dataset: DatasetReader,
    *,
    excluded_rule_ids: Iterable[str] | None = None,
) -> list[ComponentResult]:
    results: list[ComponentResult] = []
    for component in COMPONENTS.values():
        rule_results = component.run(dataset, excluded_rule_ids=excluded_rule_ids)
        for rule_result in rule_results:
            results.append(ComponentResult(component=component.slug, result=rule_result))
    return results


__all__ = [
    "Component",
    "ComponentResult",
    "COMPONENTS",
    "run_all_components",
]

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

from .dataset import InMemoryDataset
from .components import COMPONENTS, run_all_components
from .loader import load_rule_group
from .xtf_reader import parse_xtf_tables, TARGET_CLASSES


def _load_available_rule_ids() -> list[str]:
    available_rule_ids: list[str] = []
    for component in COMPONENTS.values():
        try:
            definitions = load_rule_group(component.slug)
        except FileNotFoundError:
            continue

        for definition in definitions:
            if definition.rule_id not in available_rule_ids:
                available_rule_ids.append(definition.rule_id)

    return available_rule_ids


def _debug_tables(tables: dict[str, list[dict[str, Any]]]) -> None:
    print("========== TABLAS DETECTADAS EN XTF ==========")
    if not tables:
        print("No se detectaron tablas.")
        print("=============================================")
        return

    for table_name, rows in sorted(tables.items()):
        print(f"TABLA: {table_name}")
        print(f"CANTIDAD: {len(rows)}")
        if rows:
            first_row = rows[0]
            print(f"CAMPOS: {list(first_row.keys())}")
            print(f"MUESTRA: {first_row}")
        print("---------------------------------------------")

    print("=============================================")


def _total_predios(tables: dict[str, list[dict[str, Any]]]) -> int:
    for table_name in ("ARB_Predio", "arb_predio", "ILC_Predio", "ilc_predio"):
        rows = tables.get(table_name)
        if rows:
            return len(rows)
    return 0


PREDIO_TABLES = ("ARB_Predio", "arb_predio", "ILC_Predio", "ilc_predio")
PREDIO_IDENTIFIER_FIELDS = (
    "id_operacion",
    "Id_Operacion",
    "ID_OPERACION",
    "id_predio",
    "ID_PREDIO",
    "predio_id",
    "Predio_ID",
    "t_id",
    "T_ID",
    "tid",
    "TID",
    "Numero_Predial_Nacional",
    "numero_predial_nacional",
    "Numero_Predial",
    "numero_predial",
)


def _normalize_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch for ch in text if ch.isalnum())


def _clean_identifier(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text if text and text.lower() not in {"null", "none", "nan", "n/a", "na"} else ""


def _predio_identifier_lookup(tables: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    field_targets = {_normalize_key(field) for field in PREDIO_IDENTIFIER_FIELDS}
    lookup: dict[str, str] = {}

    for table_name in PREDIO_TABLES:
        for row in tables.get(table_name, []):
            identifiers: list[str] = []

            for key, value in row.items():
                if _normalize_key(key) not in field_targets:
                    continue
                identifier = _clean_identifier(value)
                if identifier and identifier not in identifiers:
                    identifiers.append(identifier)

            if not identifiers:
                continue

            display_id = identifiers[0]
            for identifier in identifiers:
                lookup[identifier] = display_id

    return lookup


def _issue_predio_id(issue: dict[str, Any], predio_lookup: dict[str, str]) -> str | None:
    details = issue.get("details")
    if not isinstance(details, dict):
        details = {}

    candidates: list[object] = []
    candidate_fields = (
        "predio_id",
        "id_predio",
        "id_operacion",
        "Id_Operacion",
        "ID_OPERACION",
        "arb_predio",
        "ilc_predio",
        "predio",
        "display_id",
        "object_id",
        "tid",
        "t_id",
        "T_ID",
        "Numero_Predial_Nacional",
        "numero_predial_nacional",
        "Numero_Predial",
        "numero_predial",
    )

    for field in candidate_fields:
        candidates.append(details.get(field))
        candidates.append(issue.get(field))

    for source in (details, issue):
        for key, value in source.items():
            normalized_key = _normalize_key(key)
            if "predio" in normalized_key or normalized_key in {"tid", "idoperacion"}:
                candidates.append(value)

    object_class = _normalize_key(issue.get("object_class") or details.get("class") or details.get("tabla"))
    is_predio_object = object_class in {"arbpredio", "ilcpredio"}

    for candidate in candidates:
        identifier = _clean_identifier(candidate)
        if not identifier:
            continue
        if identifier in predio_lookup:
            return predio_lookup[identifier]
        if is_predio_object:
            return identifier

    return None


def _build_predio_summary(
    issues: list[dict[str, Any]],
    tables: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    predio_lookup = _predio_identifier_lookup(tables)
    predio_display_ids = set(predio_lookup.values())
    single_predio_id = next(iter(predio_display_ids)) if len(predio_display_ids) == 1 else None
    issue_counts_by_predio: dict[str, int] = {}

    for issue in issues:
        predio_id = _issue_predio_id(issue, predio_lookup)
        if not predio_id:
            predio_id = single_predio_id or "Sin identificar"
        issue_counts_by_predio[predio_id] = issue_counts_by_predio.get(predio_id, 0) + 1

    return [
        {"object_id": object_id, "issue_count": count}
        for object_id, count in sorted(
            issue_counts_by_predio.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]


def run_quality_checks(xtf_path: Path) -> dict[str, Any]:
    try:
        tables = parse_xtf_tables(xtf_path, TARGET_CLASSES)
        _debug_tables(tables)
    except Exception as exc:
        return {
            "status": "error",
            "issues": [],
            "message": f"No se pudieron leer las tablas del XTF: {exc}",
            "quality": {
                "summary": {
                    "total_rules": 0,
                    "available_rules": 0,
                    "implemented_rules": 0,
                    "unimplemented_rules": 0,
                    "passed_rules": 0,
                    "failed_rules": 0,
                    "total_issues": 0,
                    "predios_con_errores": 0,
                },
                "rules": [],
                "rule_catalog": {},
                "predio_summary": [],
                "unimplemented_rule_ids": [],
            },
        }

    dataset = InMemoryDataset(tables)
    component_results = run_all_components(dataset)
    available_rule_ids = _load_available_rule_ids()
    total_predios = _total_predios(tables)

    issues: list[dict[str, Any]] = []
    for component_result in component_results:
        result = component_result.result
        for issue in result.issues:
            display_id = (
                issue.details.get("id_operacion")
                or issue.details.get("Id_Operacion")
                or issue.details.get("id_predio")
                or issue.details.get("predio_id")
                or issue.object_ref
            )

            issues.append(
                {
                    "rule": issue.rule_id,
                    "display_id": display_id,
                    "object_id": display_id,
                    "tid": issue.object_ref,
                    "object_class": issue.details.get("class"),
                    "message": issue.message,
                    "details": issue.details,
                    "component": component_result.component,
                }
            )

    rule_definitions_by_component: dict[str, dict[str, dict[str, str]]] = {}

    for component in COMPONENTS.values():
        try:
            definitions = load_rule_group(component.slug)
        except FileNotFoundError:
            definitions = []

        rule_definitions_by_component[component.slug] = {
            definition.rule_id: {
                "description": definition.description or "",
                "component_label": definition.component or component.slug.title(),
            }
            for definition in definitions
        }

    rule_catalog: dict[str, dict[str, str]] = {}
    for component_slug, rules_map in rule_definitions_by_component.items():
        for rule_id, metadata in rules_map.items():
            rule_catalog[rule_id] = {
                "component_label": metadata.get("component_label", ""),
                "description": metadata.get("description", ""),
                "component_slug": component_slug,
            }

    rule_status: list[dict[str, Any]] = []
    for component_result in component_results:
        rule_id = component_result.result.rule_id
        catalog_item = rule_catalog.get(rule_id, {})

        rule_status.append(
            {
                "rule": rule_id,
                "component": component_result.component,
                "component_label": catalog_item.get("component_label", ""),
                "description": catalog_item.get("description", ""),
                "passed": component_result.result.passed,
                "issue_count": len(component_result.result.issues),
            }
        )

    passed_rules = [item for item in rule_status if item["passed"]]
    failed_rules = [item for item in rule_status if not item["passed"]]

    implemented_rule_ids = [item["rule"] for item in rule_status]
    unimplemented_rule_ids = [
        rule_id for rule_id in available_rule_ids
        if rule_id not in implemented_rule_ids
    ]

    predio_summary = _build_predio_summary(issues, tables)
    predios_con_errores = min(len(predio_summary), total_predios) if total_predios else len(predio_summary)
    predios_sin_errores = max(total_predios - predios_con_errores, 0)

    status = "passed" if not issues else "failed"

    return {
        "status": status,
        "issues": issues,
        "message": None,
        "quality": {
            "summary": {
                "total_rules": len(rule_status),
                "available_rules": len(available_rule_ids),
                "implemented_rules": len(rule_status),
                "unimplemented_rules": len(unimplemented_rule_ids),
                "passed_rules": len(passed_rules),
                "failed_rules": len(failed_rules),
                "total_issues": len(issues),
                "total_predios": total_predios,
                "predios_con_errores": predios_con_errores,
                "predios_sin_errores": predios_sin_errores,
            },
            "rules": rule_status,
            "rule_catalog": rule_catalog,
            "predio_summary": predio_summary,
            "unimplemented_rule_ids": unimplemented_rule_ids,
        },
    }

from __future__ import annotations

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

    issue_counts_by_object: dict[str, int] = {}
    for issue in issues:
        object_id = (
            issue.get("display_id")
            or issue.get("object_id")
            or issue.get("tid")
            or "Sin identificar"
        )
        issue_counts_by_object[object_id] = issue_counts_by_object.get(object_id, 0) + 1

    predio_summary = [
        {"object_id": object_id, "issue_count": count}
        for object_id, count in sorted(
            issue_counts_by_object.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    predios_con_errores = len(predio_summary)
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

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.asignaciones.model_context import get_assignment_model_context


def _build_parser() -> argparse.ArgumentParser:
    ctx = get_assignment_model_context("arb")
    parser = argparse.ArgumentParser(
        description="Smoke test de solo lectura para una asignacion Arbimaps."
    )
    parser.add_argument("asignacion_id", type=int, help="ID de la asignacion a validar.")
    parser.add_argument(
        "--schema-main",
        default=ctx.schema_main,
        help=f"Schema principal Arbimaps. Default: {ctx.schema_main}",
    )
    parser.add_argument(
        "--schema-work",
        default=ctx.schema_work,
        help=f"Schema workspace Arbimaps. Default: {ctx.schema_work}",
    )
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Formato de salida.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Devuelve codigo 2 si el resultado es warning.",
    )
    return parser


def _fmt(value) -> str:
    if value is None:
        return "-"
    return str(value)


def _print_text(report: dict) -> None:
    assignment = report.get("assignment") or {}
    context = report.get("context") or {}
    counts = report.get("counts") or {}
    checks = report.get("checks") or []
    warnings = report.get("warnings") or []
    table_counts = report.get("table_counts") or []

    print(f"Estado general: {report.get('status', 'unknown').upper()}")
    print(
        f"Asignacion: #{_fmt(assignment.get('id'))} | estado={_fmt(assignment.get('estado'))} | "
        f"titulo={_fmt(assignment.get('titulo'))}"
    )
    print(
        f"Usuario asignado: {_fmt(assignment.get('usuario_asignado'))} | "
        f"creado por={_fmt(assignment.get('creado_por'))}"
    )
    print(
        f"Schemas: main={_fmt(context.get('schema_main'))} | "
        f"work={_fmt(context.get('schema_work'))}"
    )
    print(
        f"Datasets: main={_fmt(assignment.get('datasetname_main'))} | "
        f"work={_fmt(assignment.get('work_datasetname'))}"
    )

    print("\nConteos")
    ordered_keys = (
        "expected_predios",
        "main_assigned_predios",
        "main_dataset_baskets",
        "main_dataset_predios",
        "workspace_dataset_baskets",
        "mapped_baskets",
        "workspace_dataset_predios",
        "workspace_assignment_predios",
        "workspace_support_predios",
        "selected_predios_scope",
        "mapped_predios_scope",
    )
    for key in ordered_keys:
        if key in counts:
            print(f"- {key}: {_fmt(counts.get(key))}")

    print("\nChecks")
    for check in checks:
        status = "OK" if check.get("ok") else "FAIL"
        print(f"- {status} {check.get('name')}: {_fmt(check.get('detail'))}")

    if warnings:
        print("\nWarnings")
        for warning in warnings:
            print(f"- {warning}")

    if table_counts:
        print("\nParidad por tabla")
        for row in table_counts:
            print(
                f"- {row.get('table')}: workspace={_fmt(row.get('workspace'))} | "
                f"main={_fmt(row.get('main'))} | status={_fmt(row.get('status'))}"
            )


def main() -> int:
    args = _build_parser().parse_args()
    try:
        from services.asignaciones_export import ExportServiceError
        from services.asignaciones_workspace import run_arb_workspace_smoke_test
    except ModuleNotFoundError as exc:
        print(f"Estado general: ERROR")
        print(
            "Detalle: faltan dependencias de ejecucion para el smoke test. "
            f"Import error: {exc}"
        )
        return 1

    try:
        report = run_arb_workspace_smoke_test(
            args.asignacion_id,
            schema_main=args.schema_main,
            schema_work=args.schema_work,
        )
    except ExportServiceError as exc:
        error_payload = {
            "status": "error",
            "status_code": exc.status_code,
            "detail": exc.detail,
        }
        if args.output == "json":
            print(json.dumps(error_payload, indent=2, ensure_ascii=False))
        else:
            print(f"Estado general: ERROR")
            print(f"Detalle: {exc.detail}")
        return 1

    if args.output == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_text(report)

    if report.get("status") == "error":
        return 1
    if args.strict and report.get("status") == "warning":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

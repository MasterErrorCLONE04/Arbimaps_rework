from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.asignaciones.model_context import get_assignment_model_context


def _build_parser() -> argparse.ArgumentParser:
    ctx = get_assignment_model_context("arb")
    parser = argparse.ArgumentParser(
        description="Ejecuta una bateria de smoke tests Arbimaps a partir de un archivo de casos."
    )
    parser.add_argument(
        "--cases-file",
        default=str(REPO_ROOT / "resource" / "asignaciones_arb_casos_patron.template.json"),
        help="Ruta al JSON con los casos patron.",
    )
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
        help="Devuelve codigo 2 si hay warnings y codigo 1 si hay fallos.",
    )
    return parser


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)


def _load_cases(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        cases = payload.get("cases") or []
    elif isinstance(payload, list):
        cases = payload
    else:
        cases = []
    return [case for case in cases if isinstance(case, dict)]


def _normalize_expected_status(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value.strip().lower()} if value.strip() else {"ok"}
    if isinstance(value, list):
        return {
            str(item).strip().lower()
            for item in value
            if item is not None and str(item).strip()
        } or {"ok"}
    return {"ok"}


def _evaluate_case(case: dict, report: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    expected_status = _normalize_expected_status(case.get("expected_status"))
    actual_status = str(report.get("status") or "").strip().lower()
    if actual_status not in expected_status:
        reasons.append(f"status={actual_status} fuera de {sorted(expected_status)}")

    checks_map = {
        str(item.get("name") or "").strip(): bool(item.get("ok"))
        for item in (report.get("checks") or [])
        if item.get("name")
    }
    for check_name in case.get("required_checks") or []:
        key = str(check_name or "").strip()
        if key and not checks_map.get(key, False):
            reasons.append(f"check={key} fallido")

    return (not reasons, reasons)


def _print_text(summary: dict) -> None:
    print(f"Estado general: {summary.get('status', 'unknown').upper()}")
    print(
        f"Schemas: main={_fmt(summary.get('schema_main'))} | "
        f"work={_fmt(summary.get('schema_work'))}"
    )
    print(
        f"Resumen: total={_fmt(summary.get('total_cases'))} | "
        f"ejecutados={_fmt(summary.get('executed_cases'))} | "
        f"ok={_fmt(summary.get('passed_cases'))} | "
        f"warning={_fmt(summary.get('warning_cases'))} | "
        f"fail={_fmt(summary.get('failed_cases'))} | "
        f"skip={_fmt(summary.get('skipped_cases'))}"
    )

    print("\nCasos")
    for item in summary.get("cases") or []:
        line = (
            f"- {item.get('code')}: result={item.get('result')} | "
            f"asignacion_id={_fmt(item.get('asignacion_id'))} | "
            f"detalle={_fmt(item.get('detail'))}"
        )
        print(line)


def main() -> int:
    args = _build_parser().parse_args()
    cases_path = Path(args.cases_file).resolve()
    if not cases_path.exists():
        print("Estado general: ERROR")
        print(f"Detalle: no existe el archivo de casos {cases_path}")
        return 1

    try:
        from services.asignaciones_export import ExportServiceError
        from services.asignaciones_workspace import run_arb_workspace_smoke_test
    except ModuleNotFoundError as exc:
        print("Estado general: ERROR")
        print(f"Detalle: faltan dependencias para ejecutar la suite. Import error: {exc}")
        return 1

    cases = _load_cases(cases_path)
    summary = {
        "status": "ok",
        "schema_main": args.schema_main,
        "schema_work": args.schema_work,
        "total_cases": len(cases),
        "executed_cases": 0,
        "passed_cases": 0,
        "warning_cases": 0,
        "failed_cases": 0,
        "skipped_cases": 0,
        "cases": [],
    }

    for case in cases:
        code = str(case.get("code") or "SIN_CODIGO").strip()
        asignacion_id = case.get("asignacion_id")
        enabled = bool(case.get("enabled", True))
        if not enabled or asignacion_id in (None, ""):
            summary["skipped_cases"] += 1
            summary["cases"].append(
                {
                    "code": code,
                    "asignacion_id": asignacion_id,
                    "result": "skip",
                    "detail": "Caso deshabilitado o sin asignacion_id.",
                }
            )
            continue

        summary["executed_cases"] += 1
        try:
            report = run_arb_workspace_smoke_test(
                int(asignacion_id),
                schema_main=args.schema_main,
                schema_work=args.schema_work,
            )
            passed, reasons = _evaluate_case(case, report)
            if passed:
                case_status = str(report.get("status") or "").strip().lower()
                if case_status == "warning":
                    summary["warning_cases"] += 1
                else:
                    summary["passed_cases"] += 1
                summary["cases"].append(
                    {
                        "code": code,
                        "asignacion_id": int(asignacion_id),
                        "result": case_status or "ok",
                        "detail": "Caso validado.",
                        "report_status": case_status,
                    }
                )
            else:
                summary["failed_cases"] += 1
                summary["cases"].append(
                    {
                        "code": code,
                        "asignacion_id": int(asignacion_id),
                        "result": "fail",
                        "detail": "; ".join(reasons),
                        "report_status": report.get("status"),
                    }
                )
        except ExportServiceError as exc:
            summary["failed_cases"] += 1
            summary["cases"].append(
                {
                    "code": code,
                    "asignacion_id": int(asignacion_id),
                    "result": "fail",
                    "detail": exc.detail,
                    "status_code": exc.status_code,
                }
            )

    if summary["failed_cases"] > 0:
        summary["status"] = "error"
    elif summary["warning_cases"] > 0:
        summary["status"] = "warning"

    if args.output == "json":
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        _print_text(summary)

    if summary["failed_cases"] > 0:
        return 1
    if args.strict and summary["warning_cases"] > 0:
        return 2
    if summary["executed_cases"] <= 0:
        return 2 if args.strict else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

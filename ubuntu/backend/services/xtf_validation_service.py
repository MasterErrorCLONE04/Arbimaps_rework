from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import shlex
import shutil
import subprocess
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from quality_rules.runner import run_quality_checks
from services.validation_excel_report import build_validation_errors_excel, validation_excel_filename
from services.validation_pdf_report import build_validation_pdf, validation_pdf_filename


COMPONENT_LABELS = {
    "administrativo": "Administrativo",
    "juridico": "Juridico",
    "fisico": "Fisico",
    "economico": "Económico",
    "topologico": "Topológico",
    "novedades": "Novedades",
    "estructura": "Estructura",
    "complementarias": "Complementarias",
    "obligatorias": "Obligatorias",
}


class XTFValidationService:
    def __init__(self):
        self.project_root = Path(__file__).resolve().parent.parent
        self.base_dir = self._abs_path("resource", "xtf_validation")
        self.upload_dir = self.base_dir / "uploads"
        self.log_dir = self.base_dir / "logs"
        self.report_dir = self.base_dir / "reports"

        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)

        self.java_bin = self._resolve_java_bin()
        self.default_validator_path = self._abs_path("resource", "ilivalidator", "ilivalidator.jar")
        self.validator_lib_dir = Path(
            os.getenv("ILIVALIDATOR_LIB_DIR", str(self._abs_path("resource", "ilivalidator", "lib")))
        )
        self.validator_jar = self._resolve_validator_jar()
        self.model_dir = Path(os.getenv("ILIVALIDATOR_MODEL_DIR", str(self._abs_path("resource", "model"))))
        self.models = os.getenv("ILIVALIDATOR_MODELS")
        extra_args = os.getenv("ILIVALIDATOR_EXTRA_ARGS", "")
        self.extra_args = shlex.split(extra_args) if extra_args else []

    async def save_xtf(
        self,
        uploaded_file,
        *,
        municipality_code: str | None = None,
    ):
        job_id = str(uuid4())
        safe_name = uploaded_file.filename.replace(" ", "_")
        file_path = self.upload_dir / f"{job_id}_{safe_name}"

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(uploaded_file.file, buffer)

        validation = await asyncio.to_thread(
            self._validate_xtf,
            job_id,
            file_path,
            municipality_code,
        )

        result = {
            "job_id": job_id,
            "original_filename": uploaded_file.filename,
            "stored_path": str(file_path),
            "stored_name": file_path.name,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "municipality_code": municipality_code,
            "validation": validation,
        }
        self._write_job_result(job_id, result)
        return result

    def build_pdf_report(self, job_id: str, *, component: str | None = None) -> tuple[bytes, str]:
        result = self.load_job_result(job_id)
        result = self._filter_report_by_component(result, component)
        watermark_path = self._abs_path("static", "img", "marca_de_agua.png")
        pdf_bytes = build_validation_pdf(result, watermark_path)
        return pdf_bytes, validation_pdf_filename(result)

    def build_excel_report(self, job_id: str, *, component: str | None = None) -> tuple[bytes, str]:
        result = self.load_job_result(job_id)
        result = self._filter_report_by_component(result, component)
        excel_bytes = build_validation_errors_excel(result)
        return excel_bytes, validation_excel_filename(result)

    def load_job_result(self, job_id: str) -> dict[str, Any]:
        result_path = self._job_result_path(job_id)
        if not result_path.is_file():
            raise FileNotFoundError(f"No se encontro el resultado de validacion {job_id}.")
        try:
            return json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"El resultado de validacion {job_id} no es un JSON valido.") from exc

    def _write_job_result(self, job_id: str, result: dict[str, Any]) -> None:
        result_path = self._job_result_path(job_id)
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _filter_report_by_component(
        self,
        report: dict[str, Any],
        component: str | None,
    ) -> dict[str, Any]:
        component_slug = self._normalize_component_slug(component)
        if not component_slug:
            return report

        filtered = copy.deepcopy(report)
        validation = filtered.get("validation")
        if not isinstance(validation, dict):
            validation = {}
            filtered["validation"] = validation

        quality = validation.get("quality")
        if not isinstance(quality, dict):
            quality = {}
            validation["quality"] = quality

        catalog = quality.get("rule_catalog") if isinstance(quality.get("rule_catalog"), dict) else {}
        all_rules = [item for item in self._as_list(quality.get("rules")) if isinstance(item, dict)]
        rule_meta_by_id = {
            str(item.get("rule") or item.get("rule_id") or "").strip(): item
            for item in all_rules
            if str(item.get("rule") or item.get("rule_id") or "").strip()
        }

        selected_rules = [
            item
            for item in all_rules
            if self._component_slug_from_item(item, catalog, rule_meta_by_id) == component_slug
        ]
        selected_rule_ids = {
            str(item.get("rule") or item.get("rule_id") or "").strip()
            for item in selected_rules
            if str(item.get("rule") or item.get("rule_id") or "").strip()
        }

        selected_rule_errors = []
        for item in self._as_list(validation.get("rule_errors")):
            if not isinstance(item, dict):
                continue
            rule_id = str(item.get("rule") or item.get("rule_id") or "").strip()
            item_slug = self._component_slug_from_item(item, catalog, rule_meta_by_id)
            if item_slug == component_slug or rule_id in selected_rule_ids:
                selected_rule_errors.append(item)

        selected_schema_errors = (
            [item for item in self._as_list(validation.get("schema_errors")) if isinstance(item, dict)]
            if component_slug == "estructura"
            else []
        )

        selected_quality_issues = []
        for item in self._as_list(quality.get("issues")):
            if not isinstance(item, dict):
                continue
            rule_id = str(item.get("rule") or item.get("rule_id") or "").strip()
            item_slug = self._component_slug_from_item(item, catalog, rule_meta_by_id)
            if item_slug == component_slug or rule_id in selected_rule_ids:
                selected_quality_issues.append(item)

        label = COMPONENT_LABELS.get(component_slug) or component_slug.replace("_", " ").title()
        validation["rule_errors"] = selected_rule_errors
        validation["schema_errors"] = selected_schema_errors
        quality["rules"] = selected_rules
        quality["issues"] = selected_quality_issues
        quality["predio_summary"] = self._predio_summary_for_errors(
            [*selected_rule_errors, *selected_schema_errors]
        )

        previous_summary = quality.get("summary") if isinstance(quality.get("summary"), dict) else {}
        total_predios = self._coerce_int(previous_summary.get("total_predios"), default=0)
        predios_con_errores = len(quality["predio_summary"])
        passed_rules = sum(1 for item in selected_rules if bool(item.get("passed")))
        failed_rules = max(len(selected_rules) - passed_rules, 0)
        quality["summary"] = {
            **previous_summary,
            "total_rules": len(selected_rules),
            "implemented_rules": len(selected_rules),
            "passed_rules": passed_rules,
            "failed_rules": failed_rules,
            "total_issues": len(selected_rule_errors) + len(selected_schema_errors),
            "predios_con_errores": predios_con_errores,
            "predios_sin_errores": max(total_predios - predios_con_errores, 0),
        }

        filtered["selected_component"] = component_slug
        filtered["selected_component_label"] = label
        return filtered

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    @staticmethod
    def _normalize_component_slug(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = unicodedata.normalize("NFKD", text.lower())
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
        aliases = {
            "juridico": "juridico",
            "juridica": "juridico",
            "fisico": "fisico",
            "fisica": "fisico",
            "economico": "economico",
            "economica": "economico",
            "topologico": "topologico",
            "topologica": "topologico",
            "estructural": "estructura",
            "estructural_xtf": "estructura",
        }
        return aliases.get(text, text)

    def _component_slug_from_item(
        self,
        item: dict[str, Any],
        catalog: dict[str, Any],
        rule_meta_by_id: dict[str, dict[str, Any]],
    ) -> str:
        rule_id = str(item.get("rule") or item.get("rule_id") or "").strip()
        rule_meta = rule_meta_by_id.get(rule_id, {})
        catalog_item = catalog.get(rule_id) if isinstance(catalog, dict) else {}
        if not isinstance(catalog_item, dict):
            catalog_item = {}

        raw_component = (
            item.get("component")
            or item.get("component_slug")
            or rule_meta.get("component")
            or rule_meta.get("component_slug")
            or catalog_item.get("component_slug")
            or catalog_item.get("sheet_slug")
            or item.get("component_label")
            or rule_meta.get("component_label")
            or catalog_item.get("component_label")
            or catalog_item.get("component")
        )
        return self._normalize_component_slug(raw_component)

    @staticmethod
    def _predio_summary_for_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
        issue_counts_by_object: dict[str, int] = {}
        for item in errors:
            object_id = (
                item.get("display_id")
                or item.get("object_id")
                or item.get("tid")
                or "Sin identificar"
            )
            object_id = str(object_id).strip() if object_id else "Sin identificar"
            issue_counts_by_object[object_id] = issue_counts_by_object.get(object_id, 0) + 1

        return [
            {"object_id": object_id, "issue_count": count}
            for object_id, count in sorted(
                issue_counts_by_object.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]

    def _job_result_path(self, job_id: str) -> Path:
        safe_job_id = str(job_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", safe_job_id):
            raise FileNotFoundError("Identificador de validacion no valido.")
        return (self.report_dir / f"{safe_job_id}.json").resolve()

    def _validate_xtf(
        self,
        job_id: str,
        file_path: Path,
        municipality_code: str | None = None,
    ) -> dict[str, Any]:
        log_path = (self.log_dir / f"{job_id}.log").resolve()
        report_path = (self.report_dir / f"{job_id}.xml").resolve()
        model_names = self._extract_xtf_model_names(file_path)
        quality_result = self._run_internal_quality(
            file_path,
            municipality_code=municipality_code,
        )
        quality, rule_errors = self._quality_and_rule_errors(quality_result)

        validator_path = self.validator_jar
        if not validator_path or not validator_path.exists():
            validator_path = self._resolve_validator_jar()
            self.validator_jar = validator_path

        if not validator_path or not validator_path.exists():
            location_hint = (validator_path or self.default_validator_path).parent
            return self._build_validation_result(
                status="skipped",
                message=(
                    "No se encontro ilivalidator.jar. "
                    f"Configura ILIVALIDATOR_JAR o coloca el archivo en {location_hint}."
                ),
                schema_errors=[],
                rule_errors=rule_errors,
                quality=quality,
                model_names=model_names,
            )

        java_bin = self.java_bin
        if not java_bin:
            java_bin = self._resolve_java_bin()
            self.java_bin = java_bin

        if not java_bin:
            return self._build_validation_result(
                status="skipped",
                message=(
                    "No se encontro el ejecutable de Java. "
                    "Instala Java 11+ o configura JAVA_BIN/JAVA_HOME en el entorno."
                ),
                schema_errors=[],
                rule_errors=rule_errors,
                quality=quality,
                model_names=model_names,
            )

        if not self.model_dir.exists():
            return self._build_validation_result(
                status="error",
                message=f"No se encontro la carpeta de modelos {self.model_dir}",
                schema_errors=[],
                rule_errors=rule_errors,
                quality=quality,
                model_names=model_names,
            )

        libs = self._gather_validator_libs(validator_path)
        if not libs:
            return self._build_validation_result(
                status="error",
                message=f"No se encontraron librerías del validador en {self.validator_lib_dir}",
                schema_errors=[],
                rule_errors=rule_errors,
                quality=quality,
                model_names=model_names,
            )

        base_cmd = self._build_validator_base_cmd(java_bin, validator_path, libs)
        cmd: list[str] = [
            *base_cmd,
            "--log",
            str(log_path),
            "--xtflog",
            str(report_path),
            "--modeldir",
            str(self.model_dir),
        ]

        if self.models:
            cmd.extend(["--models", self.models])

        cmd.extend(self.extra_args)
        cmd.append(str(file_path))

        print("=== ENTRANDO A _validate_xtf ===")
        print("JOB ID:", job_id)
        print("FILE PATH:", file_path)
        print("JAVA_BIN:", java_bin)
        print("VALIDATOR_JAR:", validator_path)
        print("VALIDATOR_LIB_DIR:", self.validator_lib_dir)
        print("MODEL_DIR:", self.model_dir)
        print("LIBS:", [str(x) for x in libs])
        print("CMD:", cmd)

        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        print("RETURNCODE:", process.returncode)
        print("STDOUT:", process.stdout)
        print("STDERR:", process.stderr)

        status = self._status_from_return_code(process.returncode)
        message = self._message_from_status(status)

        schema_errors = self._collect_validation_errors(
            report_path, log_path, process.stdout, process.stderr
        )

        return self._build_validation_result(
            status=status,
            message=message,
            log_path=str(log_path) if log_path.exists() else None,
            report_path=str(report_path) if report_path.exists() else None,
            command=" ".join(shlex.quote(part) for part in cmd),
            stdout_tail=self._tail_text(process.stdout),
            stderr_tail=self._tail_text(process.stderr),
            schema_errors=schema_errors,
            rule_errors=rule_errors,
            quality=quality,
            model_names=model_names,
        )

    def _empty_quality_result(self) -> dict[str, Any]:
        return {
            "issues": [],
            "rules": [],
            "predio_summary": [],
            "summary": {
                "available_rules": 0,
                "total_rules": 0,
                "implemented_rules": 0,
                "passed_rules": 0,
                "failed_rules": 0,
                "unimplemented_rules": 0,
                "total_issues": 0,
                "total_predios": 0,
                "predios_con_errores": 0,
                "predios_sin_errores": 0,
            },
        }

    def _normalize_quality_result(
        self,
        quality: dict[str, Any] | None,
        *,
        issues_override: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:

        if not isinstance(quality, dict):
            quality = {}

        summary = quality.get("summary")
        if not isinstance(summary, dict):
            summary = {}

        issues = issues_override if issues_override is not None else quality.get("issues")
        if not isinstance(issues, list):
            issues = []

        rules = quality.get("rules")
        if not isinstance(rules, list):
            rules = []


        # Traer catálogo. Si el motor no lo entrega, cargarlo desde resource/quality_rules/*.json.
        rule_catalog = quality.get("rule_catalog")
        if not isinstance(rule_catalog, dict) or not rule_catalog:
            rule_catalog = self._load_rule_catalog_fallback()
        else:
            normalized_catalog: dict[str, dict[str, Any]] = {}
            for rule_id, metadata in rule_catalog.items():
                normalized_rule_id = str(rule_id or "").strip()
                if not normalized_rule_id or not isinstance(metadata, dict):
                    continue
                normalized_catalog[normalized_rule_id] = metadata
            rule_catalog = normalized_catalog

        issues_by_rule: dict[str, int] = {}
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            rule_id = str(
                issue.get("rule")
                or issue.get("rule_id")
                or issue.get("codigo")
                or ""
            ).strip()
            if not rule_id or rule_id == "No disponible":
                continue
            issues_by_rule[rule_id] = issues_by_rule.get(rule_id, 0) + 1

        implemented_rule_ids = self._implemented_rule_ids_from_components()
        catalog_rule_ids = implemented_rule_ids or sorted(rule_catalog.keys(), key=self._rule_sort_key)

        rules_by_id: dict[str, dict[str, Any]] = {}
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rule_id = str(rule.get("rule") or rule.get("rule_id") or "").strip()
            if not rule_id:
                continue
            rules_by_id[rule_id] = rule

        # Si llegan reglas parciales (por ejemplo solo las incumplidas), se completa
        # la lista con el catálogo implementado para conservar agrupación y descripciones.
        rules_have_metadata = any(
            isinstance(rule, dict) and (
                rule.get("component")
                or rule.get("component_slug")
                or rule.get("component_label")
                or rule.get("description")
            )
            for rule in rules
        )
        missing_catalog_rules = bool(catalog_rule_ids) and any(
            rule_id not in rules_by_id for rule_id in catalog_rule_ids
        )

        if rule_catalog and catalog_rule_ids and (not rules_by_id or missing_catalog_rules or not rules_have_metadata):
            merged_rules: list[dict[str, Any]] = []

            for rule_id in catalog_rule_ids:
                catalog_item = rule_catalog.get(rule_id, {})
                item = rules_by_id.pop(rule_id, {})
                issue_count = self._coerce_int(
                    item.get("issue_count"),
                    default=issues_by_rule.get(rule_id, 0),
                )
                passed = (
                    self._coerce_bool(item.get("passed"), default=issue_count == 0)
                    if "passed" in item
                    else issue_count == 0
                )
                merged_rules.append(
                    {
                        "rule": rule_id,
                        "issue_count": issue_count,
                        "passed": passed,
                        "component": (
                            item.get("component")
                            or item.get("component_slug")
                            or catalog_item.get("component_slug")
                            or catalog_item.get("component")
                        ),
                        "component_label": (
                            item.get("component_label")
                            or catalog_item.get("component_label")
                            or catalog_item.get("component")
                        ),
                        "description": item.get("description") or catalog_item.get("description"),
                    }
                )

            for rule_id in sorted(rules_by_id.keys(), key=self._rule_sort_key):
                item = rules_by_id[rule_id]
                catalog_item = rule_catalog.get(rule_id, {})
                issue_count = self._coerce_int(
                    item.get("issue_count"),
                    default=issues_by_rule.get(rule_id, 0),
                )
                passed = (
                    self._coerce_bool(item.get("passed"), default=issue_count == 0)
                    if "passed" in item
                    else issue_count == 0
                )
                merged_rules.append(
                    {
                        "rule": rule_id,
                        "issue_count": issue_count,
                        "passed": passed,
                        "component": (
                            item.get("component")
                            or item.get("component_slug")
                            or catalog_item.get("component_slug")
                            or catalog_item.get("component")
                        ),
                        "component_label": (
                            item.get("component_label")
                            or catalog_item.get("component_label")
                            or catalog_item.get("component")
                        ),
                        "description": item.get("description") or catalog_item.get("description"),
                    }
                )

            rules = merged_rules

        # fallback final: reconstruir reglas desde issues si no hay catálogo
        if not rules and issues:
            rules = [
                {
                    "rule": rule_id,
                    "issue_count": issue_count,
                    "passed": issue_count == 0,
                }
                for rule_id, issue_count in sorted(issues_by_rule.items())
            ]

        implemented_rule_ids: list[str] = []
        normalized_rules: list[dict[str, Any]] = []

        for item in rules:
            if not isinstance(item, dict):
                continue

            rule_id = str(item.get("rule") or item.get("rule_id") or "").strip()
            if not rule_id:
                continue

            issue_count = self._coerce_int(
                item.get("issue_count"),
                default=issues_by_rule.get(rule_id, 0),
            )
            passed = (
                self._coerce_bool(item.get("passed"), default=issue_count == 0)
                if "passed" in item
                else issue_count == 0
            )

            # No perder metadata aunque la regla venga solo desde un issue.
            catalog_item = rule_catalog.get(rule_id, {})

            normalized_rules.append({
                "rule": rule_id,
                "issue_count": issue_count,
                "passed": passed,
                "component": (
                    item.get("component")
                    or item.get("component_slug")
                    or catalog_item.get("component_slug")
                    or catalog_item.get("component")
                ),
                "component_label": (
                    item.get("component_label")
                    or catalog_item.get("component_label")
                    or catalog_item.get("component")
                ),
                "description": item.get("description") or catalog_item.get("description"),
            })

            if rule_id not in implemented_rule_ids:
                implemented_rule_ids.append(rule_id)

        unimplemented_rule_ids = quality.get("unimplemented_rule_ids") or []
        if not isinstance(unimplemented_rule_ids, list):
            unimplemented_rule_ids = []

        predio_summary = quality.get("predio_summary") or []
        if not isinstance(predio_summary, list):
            predio_summary = []

        # fallback: reconstruir resumen por predio
        if not predio_summary and issues:
            issue_counts_by_object: dict[str, int] = {}

            for issue in issues:
                if not isinstance(issue, dict):
                    continue

                object_id = (
                    issue.get("display_id")
                    or issue.get("object_id")
                    or issue.get("tid")
                    or "Sin identificar"
                )

                object_id = str(object_id).strip() if object_id else "Sin identificar"

                issue_counts_by_object[object_id] = issue_counts_by_object.get(object_id, 0) + 1

            predio_summary = [
                {"object_id": object_id, "issue_count": count}
                for object_id, count in sorted(
                    issue_counts_by_object.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ]

        normalized_rules.sort(key=lambda rule: self._rule_sort_key(str(rule.get("rule") or "")))

        # Conservar catálogo para que el template tenga un fallback de metadata.
        quality["rule_catalog"] = rule_catalog

        quality["issues"] = issues
        quality["rules"] = normalized_rules
        quality["predio_summary"] = predio_summary
        computed_total_rules = len(normalized_rules)
        computed_passed_rules = sum(1 for rule in normalized_rules if rule["passed"])
        computed_failed_rules = computed_total_rules - computed_passed_rules
        available_default = len(rule_catalog) if rule_catalog else len(set(implemented_rule_ids) | set(unimplemented_rule_ids))
        available_rules = self._coerce_int(summary.get("available_rules"), default=available_default)
        if available_rules < computed_total_rules:
            available_rules = max(computed_total_rules, available_default)

        unimplemented_default = max(available_rules - computed_total_rules, 0)
        unimplemented_rules = self._coerce_int(
            summary.get("unimplemented_rules"),
            default=unimplemented_default,
        )
        if (
            unimplemented_rules == 0
            and available_rules > computed_total_rules
            and self._coerce_int(summary.get("total_rules"), default=-1) != computed_total_rules
        ):
            unimplemented_rules = unimplemented_default

        total_predios_value = self._coerce_int(summary.get("total_predios"), default=0)
        total_issues_value = self._coerce_int(
            summary.get("total_issues"),
            default=len(issues),
        )
        raw_predios_con_errores = self._coerce_int(
            summary.get("predios_con_errores"),
            default=len(predio_summary),
        )
        if predio_summary:
            raw_predios_con_errores = max(raw_predios_con_errores, len(predio_summary))
        if total_predios_value == 1 and total_issues_value > 0:
            raw_predios_con_errores = 1

        if total_predios_value:
            predios_con_errores_value = min(raw_predios_con_errores, total_predios_value)
        else:
            predios_con_errores_value = raw_predios_con_errores

        quality["summary"] = {
            "available_rules": available_rules,
            "total_rules": computed_total_rules,
            "implemented_rules": computed_total_rules,
            "passed_rules": computed_passed_rules,
            "failed_rules": computed_failed_rules,
            "unimplemented_rules": unimplemented_rules,
            "total_issues": total_issues_value,
            "total_predios": total_predios_value,
            "predios_con_errores": predios_con_errores_value,
            "predios_sin_errores": max(total_predios_value - predios_con_errores_value, 0),
        }

        return quality

    def _resolve_validator_jar(self) -> Path | None:
        env_path = os.getenv("ILIVALIDATOR_JAR")
        if env_path:
            candidate = Path(env_path)
            if candidate.is_file():
                return candidate

        if self.default_validator_path.is_file():
            return self.default_validator_path

        resource_dir = self._abs_path("resource")
        if not resource_dir.exists():
            return None

        jar_candidates: list[Path] = []
        for pattern in ("ilivalidator*/ilivalidator*.jar", "ilivalidator*/**/ilivalidator*.jar"):
            for path in resource_dir.glob(pattern):
                if path.is_file():
                    jar_candidates.append(path)

        if not jar_candidates:
            return None

        try:
            jar_candidates.sort(
                key=lambda p: p.stat().st_mtime if p.exists() else 0,
                reverse=True,
            )
        except OSError:
            jar_candidates.sort(reverse=True)
        return jar_candidates[0]

    def _validator_lib_dirs(self, validator_path: Path | None = None) -> list[Path]:
        candidates: list[Path] = []
        seen: set[str] = set()

        for candidate in (
            self.validator_lib_dir,
            validator_path.parent / "lib" if validator_path else None,
            validator_path.parent / "libs" if validator_path else None,
        ):
            if not candidate:
                continue
            candidate_str = str(candidate)
            if candidate_str in seen:
                continue
            seen.add(candidate_str)
            candidates.append(candidate)

        return candidates

    def _gather_validator_libs(self, validator_path: Path | None = None) -> list[Path]:
        libs: list[Path] = []
        seen: set[str] = set()

        for lib_dir in self._validator_lib_dirs(validator_path):
            if not lib_dir.exists():
                continue
            for jar in sorted(lib_dir.glob("*.jar")):
                if not jar.is_file():
                    continue
                jar_str = str(jar)
                if jar_str in seen:
                    continue
                seen.add(jar_str)
                libs.append(jar)

        extra_classpath = os.getenv("ILIVALIDATOR_CLASSPATH")
        if extra_classpath:
            for chunk in extra_classpath.split(os.pathsep):
                chunk = chunk.strip()
                if not chunk:
                    continue

                chunk_path = Path(chunk)
                if chunk_path.is_dir():
                    for jar in sorted(chunk_path.glob("*.jar")):
                        if not jar.is_file():
                            continue
                        jar_str = str(jar)
                        if jar_str in seen:
                            continue
                        seen.add(jar_str)
                        libs.append(jar)
                    continue

                jar_str = str(chunk_path)
                if jar_str in seen:
                    continue
                seen.add(jar_str)
                libs.append(chunk_path)

        return libs

    def _build_validator_base_cmd(self, java_bin: str, validator_path: Path, libs: list[Path]) -> list[str]:
        main_class = (
            os.getenv("ILIVALIDATOR_MAIN_CLASS", "org.interlis2.validator.Main").strip()
            or "org.interlis2.validator.Main"
        )

        classpath_entries = [str(validator_path)] + [str(path) for path in libs]
        classpath = os.pathsep.join(classpath_entries)

        return [java_bin, "-cp", classpath, main_class]

    @staticmethod
    def _coerce_int(value: Any, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_bool(value: Any, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "t", "yes", "y", "si", "sí"}:
                return True
            if normalized in {"0", "false", "f", "no", "n"}:
                return False
        return default

    @staticmethod
    def _rule_sort_key(rule_id: str) -> tuple[int, ...]:
        parts: list[int] = []
        for chunk in str(rule_id).split("."):
            try:
                parts.append(int(chunk))
            except ValueError:
                parts.append(999999)
        return tuple(parts)

    def _implemented_rule_ids_from_components(self) -> list[str]:
        try:
            from quality_rules.components import COMPONENTS
        except Exception:
            return []

        rule_ids: list[str] = []
        for component in COMPONENTS.values():
            for rule_id in sorted(component.default_rule_ids, key=self._rule_sort_key):
                if rule_id not in component.rule_functions:
                    continue
                if rule_id not in rule_ids:
                    rule_ids.append(rule_id)
        return rule_ids

    def _load_rule_catalog_fallback(self) -> dict[str, dict[str, str]]:
        base_dir = self._abs_path("resource", "quality_rules")
        if not base_dir.exists():
            return {}

        try:
            from quality_rules.components import COMPONENTS
            component_slugs = list(COMPONENTS.keys())
        except Exception:
            component_slugs = [
                path.stem
                for path in sorted(base_dir.glob("*.json"))
                if path.stem != "all_rules"
            ]

        catalog: dict[str, dict[str, str]] = {}
        for slug in component_slugs:
            path = base_dir / f"{slug}.json"
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            for entry in payload.get("rules", []):
                if not isinstance(entry, dict):
                    continue
                rule_id = str(entry.get("id") or "").strip()
                if not rule_id:
                    continue

                component_label = str(entry.get("component") or "").strip()
                component_slug = str(entry.get("sheet_slug") or slug).strip()
                catalog[rule_id] = {
                    "description": str(entry.get("description") or ""),
                    "component_label": component_label or component_slug.replace("_", " ").title(),
                    "component_slug": component_slug,
                }

        return catalog

    def _abs_path(self, *parts: str) -> Path:
        return self.project_root.joinpath(*parts)

    def _resolve_java_bin(self) -> str | None:
        exe_name = "java.exe" if os.name == "nt" else "java"
        candidates: list[str] = []

        def register_hint(hint: str | Path | None) -> None:
            if not hint:
                return
            hint_str = str(hint).strip().strip("'\"")
            if not hint_str:
                return
            candidates.append(hint_str)
            hint_path = Path(hint_str)
            try:
                if hint_path.exists() and hint_path.is_dir():
                    candidates.append(str(hint_path / exe_name))
            except OSError:
                pass

        env_java_bin = os.getenv("JAVA_BIN")
        if env_java_bin:
            register_hint(env_java_bin)

        java_home = os.getenv("JAVA_HOME")
        if java_home:
            register_hint(Path(java_home) / "bin" / exe_name)
            register_hint(Path(java_home) / "bin")

        register_hint(exe_name)

        for fallback_dir in self._default_java_dirs():
            register_hint(fallback_dir)

        seen: set[str] = set()
        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            path_candidate = Path(candidate)
            try:
                if path_candidate.is_file():
                    return str(path_candidate)
            except OSError:
                pass
            resolved = shutil.which(candidate)
            if resolved:
                return resolved

        return None

    def _default_java_dirs(self) -> list[Path]:
        dirs: list[Path] = []

        resource_candidates = [
            self._abs_path("resource", "java"),
            self._abs_path("resource", "ilivalidator", "java"),
        ]
        for candidate in resource_candidates:
            if candidate.exists():
                dirs.append(candidate)

        if os.name == "nt":
            for env_name in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
                base = os.getenv(env_name)
                if not base:
                    continue
                base_path = Path(base)
                oracle_path = base_path / "Common Files" / "Oracle" / "Java" / "javapath"
                if oracle_path.exists():
                    dirs.append(oracle_path)

                java_root = base_path / "Java"
                if java_root.exists():
                    try:
                        for child in java_root.iterdir():
                            bin_dir = child / "bin"
                            if bin_dir.exists():
                                dirs.append(bin_dir)
                    except OSError:
                        continue
        else:
            unix_roots = [
                Path("/usr/lib/jvm"),
                Path("/usr/lib64/jvm"),
                Path("/usr/java"),
                Path("/usr/local/java"),
                Path("/usr/local/lib/jvm"),
                Path("/opt"),
                Path("/opt/java"),
                Path("/opt/jdk"),
            ]
            for root in unix_roots:
                if not root.exists():
                    continue
                try:
                    for child in root.iterdir():
                        bin_dir = child / "bin"
                        if bin_dir.exists():
                            dirs.append(bin_dir)
                except OSError:
                    continue

            for fixed in (Path("/usr/bin"), Path("/usr/local/bin")):
                if fixed.exists():
                    dirs.append(fixed)

        return dirs

    def _extract_xtf_model_names(self, file_path: Path) -> list[str]:
        if not file_path or not file_path.exists():
            return []

        try:
            tree = ET.parse(file_path)
        except (ET.ParseError, OSError):
            return []

        names: list[str] = []
        for element in tree.getroot().iter():
            tag_name = element.tag.split("}")[-1].lower()
            if tag_name != "model":
                continue
            name = str(element.get("NAME") or element.get("name") or "").strip()
            if name and name not in names:
                names.append(name)

        return names

    def _collect_validation_errors(
        self,
        report_path: Path,
        log_path: Path,
        stdout: str,
        stderr: str,
        max_items: int = 200,
    ) -> list[dict[str, str | None]]:
        errors = self._parse_report_errors(report_path)
        if not errors:
            errors = self._parse_log_errors(log_path)
        if not errors and stdout:
            errors = self._parse_text_errors(stdout.splitlines())
        if not errors and stderr:
            errors = self._parse_text_errors(stderr.splitlines())
        return errors[:max_items]

    def _parse_report_errors(self, report_path: Path) -> list[dict[str, str | None]]:
        if not report_path or not report_path.exists():
            return []
        try:
            tree = ET.parse(report_path)
        except (ET.ParseError, OSError):
            return []

        root = tree.getroot()
        entries: list[dict[str, str | None]] = []
        for element in root.findall(".//{*}log"):
            severity = (element.get("severity") or element.get("severityCode") or "").upper()
            if severity not in {"ERROR", "E"}:
                continue

            entry = {
                "severity": "ERROR",
                "object_id": self._first_value(
                    element, ["tid", "objectid", "oid", "ref"], attr_fallback=True
                ),
                "object_class": self._first_value(
                    element,
                    ["objtag", "tag", "class", "topic", "objectclass"],
                    attr_fallback=True,
                ),
                "rule": self._first_value(element, ["rule", "check"], attr_fallback=True),
                "message": self._first_value(element, ["msg", "message"], text_fallback=True)
                or (element.text or "").strip(),
            }
            entries.append(entry)

        return entries

    def _parse_log_errors(self, log_path: Path) -> list[dict[str, str | None]]:
        if not log_path or not log_path.exists():
            return []
        try:
            content = log_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = log_path.read_text(encoding="latin-1", errors="ignore")
        return self._parse_text_errors(content.splitlines())

    def _parse_text_errors(self, lines: list[str]) -> list[dict[str, str | None]]:
        if not lines:
            return []

        entries: list[dict[str, str | None]] = []
        error_pattern = re.compile(r"\b(?:error|err)\b[:\-]?\s*(.*)", re.IGNORECASE)
        class_pattern = re.compile(r"class\s+([A-Za-z0-9_.]+)", re.IGNORECASE)
        tid_pattern = re.compile(
            r"\b(?:tid|oid|objectid)\s*(?:[:=]|is)?\s*([A-Za-z0-9_.\-]+)",
            re.IGNORECASE,
        )
        rule_pattern = re.compile(
            r"\b(?:regla|rule|constraint)\s*(?:[:=]|is)?\s*([A-Za-z0-9_.\-]+)",
            re.IGNORECASE,
        )

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            match = error_pattern.search(line)
            if not match:
                continue

            message = match.group(1).strip() or line
            entry = {
                "severity": "ERROR",
                "object_id": None,
                "object_class": None,
                "rule": None,
                "message": message,
            }

            tid_match = tid_pattern.search(line)
            if tid_match:
                entry["object_id"] = tid_match.group(1)

            class_match = class_pattern.search(line)
            if class_match:
                entry["object_class"] = class_match.group(1)

            rule_match = rule_pattern.search(line)
            if rule_match:
                entry["rule"] = rule_match.group(1)

            entries.append(entry)

        return entries

    @staticmethod
    def _first_value(
        element: ET.Element,
        names: list[str],
        *,
        attr_fallback: bool = False,
        text_fallback: bool = False,
    ) -> str | None:
        for name in names:
            if attr_fallback and (value := element.get(name)):
                return value
            for child in element:
                child_name = child.tag.split("}")[-1]
                if child_name.lower() == name.lower() and (child.text or "").strip():
                    return child.text.strip()
        if text_fallback:
            combined = " ".join(
                (child.text or "").strip()
                for child in element
                if child.text and child.text.strip()
            )
            return combined or None
        return None

    @staticmethod
    def _tail_text(text: str, lines: int = 15) -> str:
        if not text:
            return ""
        chunks = text.strip().splitlines()
        tail = chunks[-lines:]
        return "\n".join(tail)

    @staticmethod
    def _status_from_return_code(return_code: int) -> str:
        if return_code == 0:
            return "success"
        if return_code == 1:
            return "invalid"
        return "error"

    @staticmethod
    def _message_from_status(status: str) -> str:
        if status == "success":
            return "Validación completada sin errores."
        if status == "invalid":
            return "El validador encontró errores en el XTF."
        return "No se pudo ejecutar el validador. Revisa los registros."

    def _rule_error_sort_key(self, error: dict[str, Any]) -> tuple[tuple[int, ...], str, str, str]:
        rule_id = str(error.get("rule") or error.get("rule_id") or "").strip()
        object_id = str(
            error.get("display_id")
            or error.get("object_id")
            or error.get("tid")
            or ""
        ).strip()
        object_class = str(error.get("object_class") or error.get("class") or "").strip()
        message = str(error.get("message") or "").strip()
        return (self._rule_sort_key(rule_id), object_id, object_class, message)

    def _run_internal_quality(
        self,
        file_path: Path,
        *,
        municipality_code: str | None = None,
    ) -> dict[str, Any]:
        """Ejecuta las reglas internas de calidad y siempre devuelve una estructura válida."""
        try:
            result = run_quality_checks(
                file_path,
                municipality_code=municipality_code,
            )
        except Exception as exc:
            empty = self._empty_quality_result()
            empty["issues"] = [
                {
                    "rule": "internal_quality",
                    "object_id": None,
                    "display_id": "Validador interno",
                    "message": f"No se pudieron ejecutar las reglas internas: {exc}",
                    "component": "internal",
                    "component_label": "Reglas internas",
                }
            ]
            empty["summary"]["total_issues"] = 1
            empty["summary"]["failed_rules"] = 1
            return empty

        if isinstance(result, dict) and isinstance(result.get("quality"), dict):
            quality = result["quality"]

            if "issues" not in quality:
                quality["issues"] = result.get("issues", [])

            return self._normalize_quality_result(quality)

        return self._normalize_quality_result(result)

    def _quality_and_rule_errors(self, quality_result: dict[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Normaliza quality y copia los issues internos a rule_errors para que el frontend los muestre."""
        quality = self._normalize_quality_result(quality_result)
        rule_errors: list[dict[str, Any]] = []

        catalog = quality.get("rule_catalog") or self._load_rule_catalog_fallback()
        rule_meta_by_id = {
            str(rule.get("rule")).strip(): rule
            for rule in quality.get("rules", [])
            if isinstance(rule, dict) and rule.get("rule")
        }

        for issue in quality.get("issues", []):
            if not isinstance(issue, dict):
                continue

            rule_id = str(
                issue.get("rule")
                or issue.get("rule_id")
                or issue.get("codigo")
                or "No disponible"
            ).strip()

            object_id = (
                issue.get("display_id")
                or issue.get("object_id")
                or issue.get("object_ref")
                or issue.get("tid")
            )

            rule_meta = rule_meta_by_id.get(rule_id) or {}
            catalog_item = catalog.get(rule_id) or {}

            component = (
                issue.get("component")
                or issue.get("component_slug")
                or rule_meta.get("component")
                or catalog_item.get("component_slug")
            )
            component_label = (
                issue.get("component_label")
                or rule_meta.get("component_label")
                or catalog_item.get("component_label")
            )
            description = (
                issue.get("description")
                or issue.get("descripcion")
                or rule_meta.get("description")
                or catalog_item.get("description")
            )

            rule_errors.append(
                {
                    "severity": issue.get("severity") or "ERROR",
                    "object_id": str(object_id).strip() if object_id else None,
                    "object_class": issue.get("object_class") or issue.get("class") or issue.get("tabla"),
                    "rule": rule_id,
                    "message": issue.get("message") or description or "Error de regla interna.",
                    "description": description,
                    "details": issue.get("details") or {},
                    "component": component,
                    "component_label": component_label,
                }
            )

        rule_errors.sort(key=self._rule_error_sort_key)

        return quality, rule_errors

    def _build_validation_result(
        self,
        *,
        status: str,
        message: str,
        schema_errors: list[dict[str, Any]] | None = None,
        rule_errors: list[dict[str, Any]] | None = None,
        quality: dict[str, Any] | None = None,
        log_path: str | None = None,
        report_path: str | None = None,
        command: str | None = None,
        stdout_tail: str = "",
        stderr_tail: str = "",
        model_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Construye la respuesta final conservando schema_errors y errores topológicos/calidad."""
        normalized_quality = self._normalize_quality_result(quality)

        schema_errors = schema_errors or []
        rule_errors = sorted(rule_errors or [], key=self._rule_error_sort_key)

        summary = normalized_quality.get("summary") or {}
        total_issues = self._coerce_int(summary.get("total_issues"), default=0)
        failed_rules = self._coerce_int(summary.get("failed_rules"), default=0)

        if status == "success" and (schema_errors or rule_errors or total_issues > 0 or failed_rules > 0):
            status = "invalid"
            message = (
                "Se detectaron errores durante la validación. "
                "Revisa el detalle por regla y por predio en las secciones inferiores."
            )

        return {
            "status": status,
            "message": message,
            "schema_errors": schema_errors,
            "rule_errors": rule_errors,
            "quality": normalized_quality,
            "model_names": model_names or [],
            "model_name": ", ".join(model_names or []),
            "log_path": log_path,
            "report_path": report_path,
            "command": command,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
        }

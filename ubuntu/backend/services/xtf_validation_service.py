from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from uuid import uuid4

from quality_rules.runner import run_quality_checks


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

    async def save_xtf(self, uploaded_file):
        job_id = str(uuid4())
        safe_name = uploaded_file.filename.replace(" ", "_")
        file_path = self.upload_dir / f"{job_id}_{safe_name}"

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(uploaded_file.file, buffer)

        validation = await asyncio.to_thread(self._validate_xtf, job_id, file_path)

        return {
            "job_id": job_id,
            "original_filename": uploaded_file.filename,
            "stored_path": str(file_path),
            "stored_name": file_path.name,
            "validation": validation,
        }

    def _validate_xtf(self, job_id: str, file_path: Path) -> dict[str, Any]:
        log_path = (self.log_dir / f"{job_id}.log").resolve()
        report_path = (self.report_dir / f"{job_id}.xml").resolve()

        validator_path = self.validator_jar
        if not validator_path or not validator_path.exists():
            validator_path = self._resolve_validator_jar()
            self.validator_jar = validator_path

        if not validator_path or not validator_path.exists():
            location_hint = (validator_path or self.default_validator_path).parent
            return {
                "status": "skipped",
                "message": (
                    "No se encontro ilivalidator.jar. "
                    f"Configura ILIVALIDATOR_JAR o coloca el archivo en {location_hint}."
                ),
                "log_path": None,
                "report_path": None,
                "command": None,
                "stdout_tail": "",
                "stderr_tail": "",
                "errors": [],
                "quality": self._empty_quality_result(),
            }

        java_bin = self.java_bin
        if not java_bin:
            java_bin = self._resolve_java_bin()
            self.java_bin = java_bin

        if not java_bin:
            return {
                "status": "skipped",
                "message": (
                    "No se encontro el ejecutable de Java. "
                    "Instala Java 11+ o configura JAVA_BIN/JAVA_HOME en el entorno."
                ),
                "log_path": None,
                "report_path": None,
                "command": None,
                "stdout_tail": "",
                "stderr_tail": "",
                "errors": [],
                "quality": self._empty_quality_result(),
            }

        if not self.model_dir.exists():
            return {
                "status": "error",
                "message": f"No se encontro la carpeta de modelos {self.model_dir}",
                "log_path": None,
                "report_path": None,
                "command": None,
                "stdout_tail": "",
                "stderr_tail": "",
                "errors": [],
                "quality": self._empty_quality_result(),
            }

        libs = self._gather_validator_libs(validator_path)
        if not libs:
            return {
                "status": "error",
                "message": f"No se encontraron librerías del validador en {self.validator_lib_dir}",
                "log_path": None,
                "report_path": None,
                "command": None,
                "stdout_tail": "",
                "stderr_tail": "",
                "errors": [],
                "quality": self._empty_quality_result(),
            }

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

        quality_result = run_quality_checks(file_path)

        raw_quality = quality_result.get("quality")
        raw_issues = quality_result.get("issues", [])

        if not isinstance(raw_quality, dict):
            raw_quality = {}

        if not isinstance(raw_issues, list):
            raw_issues = []

        if "issues" not in raw_quality or not isinstance(raw_quality.get("issues"), list):
            raw_quality["issues"] = raw_issues

        quality = self._normalize_quality_result(
            raw_quality,
            issues_override=raw_issues,
        )

        rule_errors = quality_result.get("issues", []) if isinstance(quality_result.get("issues"), list) else []
        errors = [*schema_errors, *rule_errors]

        if rule_errors and status == "success":
            status = "invalid"
            message = "El validador encontró errores en las reglas internas."

        return {
            "status": status,
            "message": message,
            "log_path": str(log_path) if log_path.exists() else None,
            "report_path": str(report_path) if report_path.exists() else None,
            "command": " ".join(shlex.quote(part) for part in cmd),
            "stdout_tail": self._tail_text(process.stdout),
            "stderr_tail": self._tail_text(process.stderr),
            "errors": errors,
            "schema_errors": schema_errors,
            "rule_errors": rule_errors,
            "quality": quality,
        }

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
                "predios_con_errores": 0,
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

        # 🔴 IMPORTANTE: traer catálogo
        rule_catalog = quality.get("rule_catalog")
        if not isinstance(rule_catalog, dict):
            rule_catalog = {}

        # fallback: reconstruir reglas desde issues si rules viene vacío
        if not rules and issues:
            grouped_rules: dict[str, int] = {}

            for issue in issues:
                if not isinstance(issue, dict):
                    continue

                rule_id = str(issue.get("rule") or "").strip()
                if not rule_id or rule_id == "No disponible":
                    continue

                grouped_rules[rule_id] = grouped_rules.get(rule_id, 0) + 1

            rules = [
                {
                    "rule": rule_id,
                    "issue_count": issue_count,
                    "passed": issue_count == 0,
                }
                for rule_id, issue_count in sorted(grouped_rules.items())
            ]

        implemented_rule_ids: list[str] = []
        normalized_rules: list[dict[str, Any]] = []

        for item in rules:
            if not isinstance(item, dict):
                continue

            rule_id = str(item.get("rule") or item.get("rule_id") or "").strip()
            if not rule_id:
                continue

            issue_count = self._coerce_int(item.get("issue_count", 0), default=0)
            passed = bool(item.get("passed")) if "passed" in item else issue_count == 0

            # 🔴 AQUÍ ESTÁ LA CLAVE (no perder metadata)
            catalog_item = rule_catalog.get(rule_id, {})

            normalized_rules.append({
                "rule": rule_id,
                "issue_count": issue_count,
                "passed": passed,
                "component": item.get("component") or catalog_item.get("component_slug"),
                "component_label": item.get("component_label") or catalog_item.get("component_label"),
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

        # 🔴 MUY IMPORTANTE: conservar catálogo
        quality["rule_catalog"] = rule_catalog

        quality["issues"] = issues
        quality["rules"] = normalized_rules
        quality["predio_summary"] = predio_summary
        quality["summary"] = {
            "available_rules": self._coerce_int(
                summary.get("available_rules"),
                default=len(set(implemented_rule_ids) | set(unimplemented_rule_ids)),
            ),
            "total_rules": self._coerce_int(
                summary.get("total_rules"),
                default=len(normalized_rules),
            ),
            "implemented_rules": self._coerce_int(
                summary.get("implemented_rules"),
                default=len(normalized_rules),
            ),
            "passed_rules": self._coerce_int(
                summary.get("passed_rules"),
                default=sum(1 for rule in normalized_rules if rule["passed"]),
            ),
            "failed_rules": self._coerce_int(
                summary.get("failed_rules"),
                default=sum(1 for rule in normalized_rules if not rule["passed"]),
            ),
            "unimplemented_rules": self._coerce_int(
                summary.get("unimplemented_rules"),
                default=len(unimplemented_rule_ids),
            ),
            "total_issues": self._coerce_int(
                summary.get("total_issues"),
                default=len(issues),
            ),
            "predios_con_errores": self._coerce_int(
                summary.get("predios_con_errores"),
                default=len(predio_summary),
            ),
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

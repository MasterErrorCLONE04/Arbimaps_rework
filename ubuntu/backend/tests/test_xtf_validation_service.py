from io import BytesIO
from zipfile import ZipFile

from services.validation_excel_report import build_validation_errors_excel, validation_excel_filename
from services.xtf_validation_service import XTFValidationService
from quality_rules.runner import _build_predio_summary
from quality_rules.npn_resolver import (
    annotate_ids_with_npns,
    build_npn_lookup,
    build_tid_lookup,
    resolve_display_tid,
    resolve_issue_npn,
)


def test_validate_xtf_stops_when_declared_model_does_not_match(tmp_path):
    xtf_path = tmp_path / "modelo_incorrecto.xtf"
    xtf_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<TRANSFER xmlns="http://www.interlis.ch/INTERLIS2.3">
  <HEADERSECTION VERSION="2.3" SENDER="test">
    <MODELS>
      <MODEL NAME="Otro_Modelo_V1" VERSION="1.0" URI="https://example.test" />
    </MODELS>
  </HEADERSECTION>
  <DATASECTION />
</TRANSFER>
""",
        encoding="utf-8",
    )

    service = XTFValidationService()
    quality_was_run = False

    def fail_if_quality_runs(*args, **kwargs):
        nonlocal quality_was_run
        quality_was_run = True
        raise AssertionError("No deben ejecutarse reglas para un modelo incorrecto")

    service._run_internal_quality = fail_if_quality_runs

    result = service._validate_xtf("modelo-incorrecto", xtf_path)

    assert result["status"] == "error"
    assert result["model_names"] == ["Otro_Modelo_V1"]
    assert "no corresponde al modelo esperado 'Captura_ArbiMaps_V1_0'" in result["message"]
    assert "Modelo encontrado: Otro_Modelo_V1" in result["message"]
    assert quality_was_run is False


def test_model_check_accepts_expected_model_among_declared_models():
    service = XTFValidationService()

    message = service._model_mismatch_message(
        ["LADM_COL_V3_1", "Captura_ArbiMaps_V1_0"]
    )

    assert message is None


def test_model_check_rejects_xtf_without_declared_model():
    service = XTFValidationService()

    message = service._model_mismatch_message([])

    assert "Modelo encontrado: no identificado" in message


def test_normalize_quality_expands_partial_rules_with_catalog_metadata():
    service = XTFValidationService()

    quality = {
        "issues": [
            {
                "rule": "2.18",
                "display_id": "PREDIO-1",
                "message": "Error de prueba",
            }
        ],
        "rules": [
            {
                "rule": "2.18",
                "issue_count": 1,
                "passed": False,
            }
        ],
        "summary": {
            "available_rules": 1,
            "total_rules": 1,
            "implemented_rules": 1,
            "passed_rules": 0,
            "failed_rules": 1,
            "unimplemented_rules": 0,
            "total_issues": 1,
            "predios_con_errores": 1,
        },
    }

    normalized = service._normalize_quality_result(quality)
    rules = normalized["rules"]
    rule_218 = next(rule for rule in rules if rule["rule"] == "2.18")

    assert len(rules) > 1
    assert normalized["summary"]["total_rules"] == len(rules)
    assert normalized["summary"]["passed_rules"] > 0
    assert normalized["summary"]["failed_rules"] == 1
    assert rule_218["component"] == "juridico"
    assert rule_218["component_label"] == "Juridico"
    assert rule_218["description"]
    assert "Administrativo" in {rule["component_label"] for rule in rules}


def test_normalize_quality_marks_single_predio_with_unidentified_errors():
    service = XTFValidationService()
    service._implemented_rule_ids_from_components = lambda: []

    quality = {
        "issues": [
            {
                "rule": "3.20",
                "message": "Error en area construida",
                "details": {"tabla": "ARB_CaracteristicasUnidadConstruccion"},
            }
        ],
        "rules": [
            {
                "rule": "3.20",
                "issue_count": 1,
                "passed": False,
            }
        ],
        "rule_catalog": {
            "3.20": {"description": "Regla fisica", "component_label": "Fisico"},
        },
        "summary": {
            "total_predios": 1,
            "predios_con_errores": 0,
            "predios_sin_errores": 1,
            "total_issues": 1,
        },
    }

    normalized = service._normalize_quality_result(quality)

    assert normalized["summary"]["predios_con_errores"] == 1
    assert normalized["summary"]["predios_sin_errores"] == 0


def test_normalize_quality_keeps_uncatalogued_issue_as_failed_rule():
    service = XTFValidationService()
    service._implemented_rule_ids_from_components = lambda: ["1.1"]

    quality = {
        "issues": [
            {
                "rule": "internal_quality",
                "display_id": "Validador interno",
                "message": "No se pudo ejecutar una regla interna",
                "component": "administrativo",
                "component_label": "Administrativo",
            }
        ],
        "rules": [
            {
                "rule": "1.1",
                "issue_count": 0,
                "passed": True,
                "component": "administrativo",
            }
        ],
        "rule_catalog": {
            "1.1": {
                "description": "Regla administrativa",
                "component_label": "Administrativo",
                "component_slug": "administrativo",
            },
        },
        "summary": {
            "total_issues": 1,
        },
    }

    normalized = service._normalize_quality_result(quality)
    synthetic_rule = next(rule for rule in normalized["rules"] if rule["rule"] == "internal_quality")

    assert synthetic_rule["issue_count"] == 1
    assert synthetic_rule["passed"] is False
    assert synthetic_rule["component"] == "administrativo"
    assert normalized["summary"]["failed_rules"] == 1


def test_npn_lookup_resolves_unit_characteristics_and_related_layers():
    npn = "415510101000003890019000000000"
    tables = {
        "ARB_Predio": [{"TID": "predio-1", "Numero_Predial": npn}],
        "ARB_Terreno": [{"TID": "terreno-1", "predio": "predio-1"}],
        "ARB_Construccion": [{"TID": "construccion-1", "predio": "predio-1"}],
        "ARB_UnidadConstruccion": [
            {
                "TID": "unidad-1",
                "construccion": "construccion-1",
                "caracteristicasunidadconstruccion": "caracteristica-1",
            }
        ],
        "ARB_CaracteristicasUnidadConstruccion": [{"TID": "caracteristica-1"}],
    }

    lookup = build_npn_lookup(tables)

    assert lookup["predio-1"] == npn
    assert lookup["terreno-1"] == npn
    assert lookup["construccion-1"] == npn
    assert lookup["unidad-1"] == npn
    assert lookup["caracteristica-1"] == npn

    tid_lookup = build_tid_lookup(tables)
    assert tid_lookup[npn] == "predio-1"
    assert resolve_display_tid(npn, tid_lookup) == "predio-1"
    assert resolve_display_tid("unidad-1", tid_lookup) == "unidad-1"
    assert resolve_issue_npn(
        {
            "object_id": "unidad-1 <-> terreno-1",
            "details": {
                "id_uconstruccion": "unidad-1",
                "id_terreno": "terreno-1",
            },
        },
        lookup,
    ) == npn


def test_error_description_keeps_tid_and_adds_npn():
    tid = "d8d9aaf7-bcc1-4465-aae9-86d258556eb1"
    npn = "415510101000006350010901010002"

    message = annotate_ids_with_npns(
        f"La unidad con ID {tid} presenta un error.",
        {tid: npn},
    )

    assert message == (
        f"La unidad con ID {tid} (NPN: {npn}) presenta un error."
    )


def test_predio_summary_assigns_unidentified_issue_to_single_predio():
    predio_summary = _build_predio_summary(
        [
            {
                "rule": "3.20",
                "object_id": "caracteristica-1",
                "details": {"tabla": "ARB_CaracteristicasUnidadConstruccion"},
            }
        ],
        {"ARB_Predio": [{"id_operacion": "PREDIO-1", "TID": "p1"}]},
    )

    assert predio_summary == [{"object_id": "PREDIO-1", "issue_count": 1}]


def test_normalize_quality_orders_rules_numerically():
    service = XTFValidationService()
    service._implemented_rule_ids_from_components = lambda: []

    quality = {
        "issues": [],
        "rules": [
            {"rule": "1.10", "issue_count": 0, "passed": True},
            {"rule": "1.2", "issue_count": 0, "passed": True},
            {"rule": "2", "issue_count": 0, "passed": True},
            {"rule": "1.1", "issue_count": 0, "passed": True},
        ],
        "rule_catalog": {
            "1.1": {"description": "Regla 1.1", "component_label": "Prueba"},
            "1.2": {"description": "Regla 1.2", "component_label": "Prueba"},
            "1.10": {"description": "Regla 1.10", "component_label": "Prueba"},
            "2": {"description": "Regla 2", "component_label": "Prueba"},
        },
    }

    normalized = service._normalize_quality_result(quality)

    assert [rule["rule"] for rule in normalized["rules"][:4]] == ["1.1", "1.2", "1.10", "2"]


def test_rule_errors_are_ordered_by_rule_number():
    service = XTFValidationService()
    service._implemented_rule_ids_from_components = lambda: []

    quality = {
        "issues": [
            {"rule": "1.10", "display_id": "PREDIO-3", "message": "Error 1.10"},
            {"rule": "1.2", "display_id": "PREDIO-2", "message": "Error 1.2"},
            {"rule": "1.1", "display_id": "PREDIO-1", "message": "Error 1.1"},
        ],
        "rules": [
            {"rule": "1.10", "issue_count": 1, "passed": False},
            {"rule": "1.2", "issue_count": 1, "passed": False},
            {"rule": "1.1", "issue_count": 1, "passed": False},
        ],
        "rule_catalog": {
            "1.1": {"description": "Regla 1.1", "component_label": "Prueba"},
            "1.2": {"description": "Regla 1.2", "component_label": "Prueba"},
            "1.10": {"description": "Regla 1.10", "component_label": "Prueba"},
        },
    }

    _, rule_errors = service._quality_and_rule_errors(quality)

    assert [error["rule"] for error in rule_errors] == ["1.1", "1.2", "1.10"]


def test_validation_excel_has_consolidated_and_component_sheets():
    report = {
        "generated_at": "2026-05-28T10:30:00",
        "original_filename": "retorno.xtf",
        "validation": {
            "rule_errors": [
                {
                    "display_id": "PREDIO-1",
                    "npn": "415510101000003890019000000000",
                    "object_class": "Administrativo.Predio",
                    "rule": "1.1",
                    "message": "Falta direccion",
                    "component_label": "Administrativo",
                },
                {
                    "display_id": "PREDIO-2",
                    "object_class": "Juridico.Derecho",
                    "rule": "2.1",
                    "message": "Falta interesado",
                    "component_label": "Juridico",
                },
            ],
            "schema_errors": [
                {
                    "object_id": "TID-1",
                    "object_class": "Modelo.Clase",
                    "message": "Error estructural",
                }
            ],
            "quality": {
                "rules": [],
                "rule_catalog": {},
            },
        },
    }

    xlsx = build_validation_errors_excel(report)

    with ZipFile(BytesIO(xlsx)) as workbook:
        workbook_xml = workbook.read("xl/workbook.xml").decode("utf-8")
        consolidated_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")

    assert 'name="Consolidado"' in workbook_xml
    assert 'name="Administrativo"' in workbook_xml
    assert 'name="Juridico"' in workbook_xml
    assert 'name="Estructural XTF"' in workbook_xml
    assert "Componente" in consolidated_xml
    assert "NPN" in consolidated_xml
    assert "415510101000003890019000000000" in consolidated_xml
    assert "PREDIO-1" in consolidated_xml
    assert "Administrativo.Predio" in consolidated_xml
    assert "Falta direccion" in consolidated_xml


def test_validation_excel_filename_uses_generation_date():
    filename = validation_excel_filename({"generated_at": "2026-05-28T10:30:00"})

    assert filename == "Usuario_errores_validacion_20260528_1030.xlsx"

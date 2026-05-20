from services.xtf_validation_service import XTFValidationService


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

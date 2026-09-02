import unittest
from unittest.mock import MagicMock
from routers.asignaciones_detalle import _filter_validation_result_for_exempt_npns


class TestPredioRolesAndCancellation(unittest.TestCase):

    def test_filter_validation_result_for_exempt_npns_omits_colindante_alphanumeric_issues(self):
        result = {
            "status": "failed",
            "message": "Validacion XTF fallida.",
            "validation": {
                "status": "failed",
                "message": "Validacion XTF fallida.",
                "rule_errors": [
                    {
                        "npn": "41001000100010001000",
                        "component": "juridico",
                        "rule": "RULE_01",
                        "message": "Falta interesado activo en predio principal",
                    },
                    {
                        "npn": "41001000100010002000",  # Colindante
                        "component": "juridico",
                        "rule": "RULE_02",
                        "message": "Falta interesado activo en colindante",
                    },
                    {
                        "npn": "41001000100010002000",  # Colindante
                        "component": "topologico",
                        "rule": "TOP_01",
                        "message": "Overlap topologico de linderos",
                    },
                ],
                "quality": {
                    "issues": [
                        {
                            "npn": "41001000100010001000",
                            "component": "juridico",
                            "rule": "RULE_01",
                        },
                        {
                            "npn": "41001000100010002000",
                            "component": "juridico",
                            "rule": "RULE_02",
                        },
                        {
                            "npn": "41001000100010002000",
                            "component": "topologico",
                            "rule": "TOP_01",
                        },
                    ],
                    "summary": {"total_issues": 3, "failed_rules": 3},
                },
            },
        }

        exempt_npns = {"41001000100010002000"}
        filtered = _filter_validation_result_for_exempt_npns(result, exempt_npns)

        val = filtered.get("validation") or filtered
        rule_errors = val.get("rule_errors") or []

        # 1. Alphanumeric issue for 41001000100010002000 should be removed
        # 2. Topological issue for 41001000100010002000 MUST remain
        # 3. Alphanumeric issue for main parcel 41001000100010001000 MUST remain
        self.assertEqual(len(rule_errors), 2)
        npns_remaining = [e.get("npn") for e in rule_errors]
        self.assertIn("41001000100010001000", npns_remaining)
        self.assertIn("41001000100010002000", npns_remaining)

        components_remaining = [e.get("component") for e in rule_errors if e.get("npn") == "41001000100010002000"]
        self.assertEqual(components_remaining, ["topologico"])

    def test_filter_validation_result_approves_when_only_exempt_issues_exist(self):
        result = {
            "status": "failed",
            "message": "Validacion XTF fallida.",
            "validation": {
                "status": "failed",
                "message": "Validacion XTF fallida.",
                "rule_errors": [
                    {
                        "npn": "41001000100010002000",
                        "component": "economico",
                        "rule": "ECO_01",
                        "message": "Avaluo faltante en colindante",
                    }
                ],
                "quality": {
                    "issues": [
                        {
                            "npn": "41001000100010002000",
                            "component": "economico",
                            "rule": "ECO_01",
                        }
                    ],
                    "summary": {"total_issues": 1, "failed_rules": 1},
                },
            },
        }

        exempt_npns = {"41001000100010002000"}
        filtered = _filter_validation_result_for_exempt_npns(result, exempt_npns)

        self.assertEqual(filtered.get("status"), "success")


if __name__ == "__main__":
    unittest.main()

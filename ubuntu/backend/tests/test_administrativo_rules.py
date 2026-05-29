from quality_rules.administrativo import (
    _rule_1_15,
    _rule_1_16,
    _rule_1_17,
    _rule_1_21,
    _rule_1_22,
    _rule_1_24,
)
from quality_rules.dataset import InMemoryDataset


def test_empty_destinacion_errors_are_not_duplicated_by_table_aliases():
    dataset = InMemoryDataset(
        {
            "ARB_Predio": [
                {"t_id": "predio-1", "Destinacion_Economica": ""},
                {"t_id": "predio-2", "Destinacion_Economica": "NULL"},
            ],
        }
    )

    for rule in (_rule_1_15, _rule_1_16, _rule_1_17):
        issues = rule(dataset)

        assert len(issues) == 2
        assert {issue.object_ref for issue in issues} == {"predio-1", "predio-2"}


def test_empty_condicion_errors_are_not_duplicated_by_table_aliases():
    dataset = InMemoryDataset(
        {
            "ARB_Predio": [
                {"t_id": "predio-1", "Condicion_Predio": ""},
                {"t_id": "predio-2", "Condicion_Predio": "nan"},
            ],
        }
    )

    for rule in (_rule_1_21, _rule_1_22, _rule_1_24):
        issues = rule(dataset)

        assert len(issues) == 2
        assert {issue.object_ref for issue in issues} == {"predio-1", "predio-2"}


def test_empty_required_fields_are_reported_before_missing_t_id():
    predio_sin_t_id = InMemoryDataset(
        {"ARB_Predio": [{"Id_Operacion": "predio-1", "Destinacion_Economica": ""}]}
    )
    condicion_sin_t_id = InMemoryDataset(
        {"ARB_Predio": [{"Id_Operacion": "predio-2", "Condicion_Predio": ""}]}
    )

    assert len(_rule_1_15(predio_sin_t_id)) == 1
    assert len(_rule_1_21(condicion_sin_t_id)) == 1

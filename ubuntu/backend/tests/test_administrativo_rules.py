from quality_rules.administrativo import (
    _rule_1_2,
    _rule_1_9,
    _rule_1_10,
    _rule_1_14,
    _rule_1_15,
    _rule_1_16,
    _rule_1_17,
    _rule_1_21,
    _rule_1_22,
    _rule_1_24,
)
from quality_rules.dataset import InMemoryDataset
from quality_rules.obligatorias import rule_11_1


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


def test_divipola_rules_use_selected_municipality_context():
    dataset = InMemoryDataset(
        {
            "ARB_Predio": [
                {
                    "t_id": "predio-almaguer",
                    "Numero_Predial_Nacional": "19022" + "0" * 25,
                    "Codigo_ORIP": "122",
                }
            ],
        },
        metadata={"municipality_code": "almaguer"},
    )

    assert _rule_1_9(dataset) == []
    assert _rule_1_10(dataset) == []
    assert _rule_1_14(dataset) == []


def test_divipola_rule_11_1_uses_selected_municipality_context():
    dataset = InMemoryDataset(
        {
            "ARB_Predio": [
                {
                    "t_id": "predio-saravena",
                    "numero_predial": "81736" + "0" * 25,
                }
            ],
        },
        metadata={"municipality_code": "saravena"},
    )

    assert rule_11_1(dataset) == []


def test_orip_rule_uses_selected_municipality_context():
    dataset = InMemoryDataset(
        {
            "ARB_Predio": [
                {
                    "t_id": "predio-sucre",
                    "Numero_Predial_Nacional": "19785" + "0" * 25,
                    "Codigo_ORIP": "122",
                }
            ],
        },
        metadata={"municipality_code": "sucre"},
    )

    assert _rule_1_14(dataset) == []


def test_orip_rule_uses_saravena_orip_context():
    dataset = InMemoryDataset(
        {
            "ARB_Predio": [
                {
                    "t_id": "predio-saravena",
                    "Numero_Predial_Nacional": "81736" + "0" * 25,
                    "Codigo_ORIP": "410",
                }
            ],
        },
        metadata={"municipality_code": "saravena"},
    )

    assert _rule_1_14(dataset) == []

def test_rule_1_2_allows_predio_nuevo_with_provisional_letter_at_position_18():
    numero = "41001010900000702A900000000000"
    dataset = InMemoryDataset(
        {
            "ARB_Predio": [
                {
                    "t_id": "predio-nuevo-1",
                    "Numero_Predial_Nacional": numero,
                }
            ],
            "ARB_NovedadNumeroPredialValor": [
                {
                    "t_id": "novedad-1",
                    "tipo_novedad": "Predio_Nuevo",
                    "numero_predial": numero,
                    "arb_predio_novedad_numero_predial": "predio-nuevo-1",
                }
            ],
        }
    )

    assert _rule_1_2(dataset) == []


def test_rule_1_2_allows_predio_nuevo_with_provisional_letter_at_position_14():
    numero = "4100101090000A7020900000000000"
    dataset = InMemoryDataset(
        {
            "ARB_Predio": [
                {
                    "t_id": "predio-nuevo-2",
                    "Numero_Predial_Nacional": numero,
                }
            ],
            "ARB_NovedadNumeroPredialValor": [
                {
                    "t_id": "novedad-2",
                    "tipo_novedad": "Predio nuevo",
                    "numero_predial": numero,
                    "arb_predio_novedad_numero_predial": "predio-nuevo-2",
                }
            ],
        }
    )

    assert _rule_1_2(dataset) == []


def test_rule_1_2_rejects_provisional_number_without_predio_nuevo_novedad():
    dataset = InMemoryDataset(
        {
            "ARB_Predio": [
                {
                    "t_id": "predio-sin-novedad",
                    "Numero_Predial_Nacional": "41001010900000702A900000000000",
                }
            ]
        }
    )

    issues = _rule_1_2(dataset)

    assert len(issues) == 1
    assert issues[0].rule_id == "1.2"


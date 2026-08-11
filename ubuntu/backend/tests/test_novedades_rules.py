from quality_rules.dataset import InMemoryDataset
from quality_rules.novedades import _rule_8_11


def _dataset_cancelacion(numero_predial: str) -> InMemoryDataset:
    return InMemoryDataset(
        {
            "ARB_Predio": [
                {
                    "TID": "predio-cancelado",
                    "Numero_Predial": numero_predial,
                }
            ],
            "ARB_NovedadNumeroPredialValor": [
                {
                    "Tipo_Novedad": "Cancelacion_por_Desenglobe",
                    "Numero_Predial": numero_predial,
                    "arb_predio_novedad_numero_predial": "predio-cancelado",
                }
            ],
        }
    )


def test_rule_8_11_does_not_treat_digit_9_at_position_18_as_provisional_new_predio():
    dataset = _dataset_cancelacion("410010109000002719990000000000")

    assert _rule_8_11(dataset) == []


def test_rule_8_11_rejects_cancelacion_with_letter_at_position_18():
    dataset = _dataset_cancelacion("41001010900000271A990000000000")

    issues = _rule_8_11(dataset)

    assert len(issues) == 1
    assert issues[0].rule_id == "8.11"


def test_rule_8_11_rejects_cancelacion_with_letter_at_position_14():
    dataset = _dataset_cancelacion("4100101090000A2719990000000000")

    issues = _rule_8_11(dataset)

    assert len(issues) == 1
    assert issues[0].rule_id == "8.11"

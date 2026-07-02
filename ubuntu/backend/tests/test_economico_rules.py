from quality_rules.dataset import InMemoryDataset
from quality_rules.economico import (
    _rule_4_1,
    _rule_4_2,
    _rule_4_3,
    _rule_4_4,
    _rule_4_10,
    _rule_4_14,
    _rule_4_15,
)
from quality_rules.xtf_reader import TARGET_CLASSES, parse_xtf_tables


def test_tipologia_rules_detect_direct_arb_mismatches():
    dataset = InMemoryDataset(
        {
            "ARB_CaracteristicasUnidadConstruccion": [
                {
                    "TID": "uc-res",
                    "Tipo_Unidad_Construccion": "Residencial",
                    "CT_Tipo_Tipologia": "Comercial.Basico_2_2014111",
                },
                {
                    "TID": "uc-com",
                    "Tipo_Unidad_Construccion": "Comercial",
                    "CT_Tipo_Tipologia": "Industrial.Tipo_1_3011111",
                },
                {
                    "TID": "uc-ind",
                    "Tipo_Unidad_Construccion": "Industrial",
                    "CT_Tipo_Tipologia": "Residencial.Tipo_1_1014011",
                },
                {
                    "TID": "uc-inst",
                    "Tipo_Unidad_Construccion": "Institucional",
                    "CT_Tipo_Tipologia": "Comercial.Basico_2_2014111",
                },
            ]
        }
    )

    assert {issue.object_ref for issue in _rule_4_1(dataset)} == {"uc-res"}
    assert {issue.object_ref for issue in _rule_4_2(dataset)} == {"uc-com"}
    assert {issue.object_ref for issue in _rule_4_3(dataset)} == {"uc-ind"}
    assert {issue.object_ref for issue in _rule_4_4(dataset)} == {"uc-inst"}


def test_qgis_relation_tids_detect_industrial_with_commercial_tipologia():
    dataset = InMemoryDataset(
        {
            "ARB_CaracteristicasUnidadConstruccion": [
                {
                    "t_id": "1561",
                    "tipo_unidad_construccion": "159",
                    "ct_tipo_tipologia": "1512",
                }
            ]
        }
    )

    issues = _rule_4_3(dataset)

    assert len(issues) == 1
    assert issues[0].object_ref == "1561"
    assert issues[0].details["tipo_unidad_construccion"] == "Industrial"
    assert issues[0].details["tipo_unidad_construccion_original"] == "159"
    assert issues[0].details["tipo_tipologia"] == "Comercial.Especializado_2_2036543"
    assert issues[0].details["tipo_tipologia_original"] == "1512"


def test_qgis_domain_tables_resolve_relation_ids():
    dataset = InMemoryDataset(
        {
            "ARB_UnidadConstruccionTipo": [
                {"t_id": "159", "itfcode": "3", "ilicode": "Industrial", "dispname": "Industrial"},
            ],
            "ARB_TipologiaTipo": [
                {
                    "t_id": "1512",
                    "itfcode": "30",
                    "ilicode": "Comercial.Especializado_2_2036543",
                    "dispname": "(Comercial) Especializado 2",
                },
            ],
            "ARB_CaracteristicasUnidadConstruccion": [
                {"t_id": "1561", "tipo_unidad_construccion": "159", "ct_tipo_tipologia": "1512"},
            ],
        }
    )

    issues = _rule_4_3(dataset)

    assert len(issues) == 1
    assert issues[0].details["tipo_unidad_construccion_ilicode"] == "Industrial"
    assert issues[0].details["tipo_tipologia_ilicode"] == "Comercial.Especializado_2_2036543"


def test_tipologia_rules_use_cuc_association_for_ilc_rows():
    dataset = InMemoryDataset(
        {
            "ILC_CaracteristicasUnidadConstruccion": [
                {"TID": "uc1", "Tipo_Unidad_Construccion": "Residencial"},
            ],
            "CUC_TipologiaConstruccion": [
                {"TID": "tip1", "Tipo_Tipologia": "Comercial.Basico_2_2014111"},
            ],
            "cuc_calificacion_unidadconstruccion": [
                {
                    "ilc_caracteristicasunidadconstruccion": "uc1",
                    "cuc_calificacionunidadconstruccion": "tip1",
                }
            ],
        }
    )

    issues = _rule_4_1(dataset)

    assert len(issues) == 1
    assert issues[0].object_ref == "uc1"
    assert issues[0].details["tipologia_ref"] == "tip1"


def test_ilc_numeric_unit_domain_is_resolved_before_tipologia_validation():
    dataset = InMemoryDataset(
        {
            "ILC_CaracteristicasUnidadConstruccion": [
                {"TID": "uc-industrial", "Tipo_Unidad_Construccion": "2"},
            ],
            "CUC_TipologiaConstruccion": [
                {"TID": "tip-res", "Tipo_Tipologia": "Residencial.Tipo_1_1014011"},
            ],
            "cuc_calificacion_unidadconstruccion": [
                {
                    "ilc_caracteristicasunidadconstruccion": "uc-industrial",
                    "cuc_calificacionunidadconstruccion": "tip-res",
                }
            ],
        }
    )

    issues = _rule_4_3(dataset)

    assert len(issues) == 1
    assert issues[0].object_ref == "uc-industrial"
    assert issues[0].details["tipo_unidad_construccion_ilicode"] == "Industrial"


def test_rule_4_10_detects_conservation_unit_with_non_conservation_tipologia():
    dataset = InMemoryDataset(
        {
            "ARB_CaracteristicasUnidadConstruccion": [
                {
                    "t_id": "uc-conservacion",
                    "tipo_unidad_construccion": "158",
                    "ct_tipo_tipologia": "1512",
                }
            ]
        }
    )

    issues = _rule_4_10(dataset)

    assert len(issues) == 1
    assert issues[0].object_ref == "uc-conservacion"
    assert issues[0].details["tipo_unidad_construccion_ilicode"] == "Conservacion_Proteccion_Ambiental"
    assert issues[0].details["tipo_tipologia_ilicode"] == "Comercial.Especializado_2_2036543"


def test_rules_4_14_and_4_15_detect_missing_anexo_fields_for_no_convencional():
    dataset = InMemoryDataset(
        {
            "ARB_CaracteristicasUnidadConstruccion": [
                {
                    "TID": "uc-no-convencional",
                    "Tipo_Unidad_Construccion": "Anexo",
                    "Tipo_Calificacion": "No_Convencional",
                },
                {
                    "TID": "uc-convencional",
                    "Tipo_Unidad_Construccion": "Residencial",
                    "Tipo_Calificacion": "Convencional",
                },
            ]
        }
    )

    issues_4_14 = _rule_4_14(dataset)
    issues_4_15 = _rule_4_15(dataset)

    assert len(issues_4_14) == 1
    assert issues_4_14[0].object_ref == "uc-no-convencional"
    assert issues_4_14[0].details["tipo_calificacion_ilicode"] == "No_Convencional"

    assert len(issues_4_15) == 1
    assert issues_4_15[0].object_ref == "uc-no-convencional"
    assert issues_4_15[0].details["tipo_calificacion_ilicode"] == "No_Convencional"


def test_xtf_reader_loads_domain_tables_and_detects_relation_error(tmp_path):
    xtf_path = tmp_path / "economico.xtf"
    xtf_path.write_text(
        """
        <XTF>
          <DATASECTION>
            <Modelo.ARB_UnidadConstruccionTipo TID="159">
              <itfcode>3</itfcode>
              <ilicode>Industrial</ilicode>
              <dispname>Industrial</dispname>
            </Modelo.ARB_UnidadConstruccionTipo>
            <Modelo.ARB_TipologiaTipo TID="1512">
              <itfcode>30</itfcode>
              <ilicode>Comercial.Especializado_2_2036543</ilicode>
              <dispname>(Comercial) Especializado 2</dispname>
            </Modelo.ARB_TipologiaTipo>
            <Modelo.ARB_CaracteristicasUnidadConstruccion TID="1561">
              <Tipo_Unidad_Construccion REF="159" />
              <CT_Tipo_Tipologia REF="1512" />
            </Modelo.ARB_CaracteristicasUnidadConstruccion>
          </DATASECTION>
        </XTF>
        """,
        encoding="utf-8",
    )

    tables = parse_xtf_tables(xtf_path, TARGET_CLASSES)
    dataset = InMemoryDataset(tables)

    assert "ARB_UnidadConstruccionTipo" in tables
    assert "ARB_TipologiaTipo" in tables
    assert "ARB_CaracteristicasUnidadConstruccion" in tables
    assert len(_rule_4_3(dataset)) == 1
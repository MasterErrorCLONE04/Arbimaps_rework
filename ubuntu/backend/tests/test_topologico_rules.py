from quality_rules.dataset import InMemoryDataset
from quality_rules.topologico import RULE_FUNCTIONS
from quality_rules.xtf_reader import TARGET_CLASSES, parse_xtf_tables


def _xtf_polygon(xmin: int, ymin: int, xmax: int, ymax: int) -> str:
    coords = (
        (xmin, ymin),
        (xmax, ymin),
        (xmax, ymax),
        (xmin, ymax),
    )
    coord_xml = "".join(
        f"<coord><c1>{x}</c1><c2>{y}</c2></coord>"
        for x, y in coords
    )
    return f"<Geometria><surface><boundary>{coord_xml}</boundary></surface></Geometria>"


def test_rule_5_1_uses_predio_derecho_and_predio_terreno_associations():
    dataset = InMemoryDataset(
        {
            "ARB_DerechoInteresadoFuente": [
                {"TID": "d1", "D_Tipo": "Dominio"},
                {"TID": "d2", "D_Tipo": "Dominio"},
            ],
            "arb_predio_derecho": [
                {"predio": "p1", "derecho": "d1"},
                {"predio": "p2", "derecho": "d2"},
            ],
            "ARB_Terreno": [
                {"TID": "t1", "Geometria": _xtf_polygon(0, 0, 2, 2)},
                {"TID": "t2", "Geometria": _xtf_polygon(1, 1, 3, 3)},
            ],
            "arb_predio_terreno": [
                {"predio": "p1", "terreno": "t1"},
                {"predio": "p2", "terreno": "t2"},
            ],
        }
    )

    issues = RULE_FUNCTIONS["5.1"](dataset)

    assert len(issues) == 1
    assert issues[0].rule_id == "5.1"
    assert issues[0].details["identificador_terreno_1"] == "t1"
    assert issues[0].details["identificador_terreno_2"] == "t2"


def test_rule_5_1_canonicalizes_predio_aliases_between_derecho_and_terreno():
    dataset = InMemoryDataset(
        {
            "ARB_Predio": [
                {"TID": "p1", "Id_Operacion": "op1", "Numero_Predial": "NP1"},
                {"TID": "p2", "Id_Operacion": "op2", "Numero_Predial": "NP2"},
            ],
            "ARB_DerechoInteresadoFuente": [
                {"TID": "d1", "D_Tipo": "Dominio", "predio": "op1"},
                {"TID": "d2", "D_Tipo": "Dominio", "predio": "op2"},
            ],
            "ARB_Terreno": [
                {"TID": "t1", "Numero_Predial": "NP1", "Geometria": _xtf_polygon(0, 0, 2, 2)},
                {"TID": "t2", "Numero_Predial": "NP2", "Geometria": _xtf_polygon(1, 1, 3, 3)},
            ],
        }
    )

    issues = RULE_FUNCTIONS["5.1"](dataset)

    assert len(issues) == 1
    assert issues[0].rule_id == "5.1"


def test_rule_5_1_falls_back_to_all_terrenos_when_predio_refs_are_missing():
    dataset = InMemoryDataset(
        {
            "ARB_DerechoInteresadoFuente": [
                {"TID": "d1", "D_Tipo": "Dominio"},
            ],
            "ARB_Terreno": [
                {"TID": "t1", "Geometria": _xtf_polygon(0, 0, 2, 2)},
                {"TID": "t2", "Geometria": _xtf_polygon(1, 1, 3, 3)},
            ],
        }
    )

    issues = RULE_FUNCTIONS["5.1"](dataset)

    assert len(issues) == 1
    assert issues[0].rule_id == "5.1"


def test_rule_5_2_uses_parent_refs_for_nested_xtf_predio_children(tmp_path):
    xtf_path = tmp_path / "topologico_nested.xtf"
    xtf_path.write_text(
        f"""
        <XTF>
          <DATASECTION>
            <Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_Predio TID="p1">
              <Id_Operacion>op1</Id_Operacion>
              <Derecho>
                <Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_DerechoInteresadoFuente TID="d1">
                  <D_Tipo>Posesion</D_Tipo>
                </Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_DerechoInteresadoFuente>
              </Derecho>
              <Terreno>
                <Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_Terreno TID="t1">
                  {_xtf_polygon(0, 0, 2, 2)}
                </Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_Terreno>
              </Terreno>
            </Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_Predio>
            <Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_Predio TID="p2">
              <Id_Operacion>op2</Id_Operacion>
              <Derecho>
                <Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_DerechoInteresadoFuente TID="d2">
                  <D_Tipo>Ocupacion</D_Tipo>
                </Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_DerechoInteresadoFuente>
              </Derecho>
              <Terreno>
                <Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_Terreno TID="t2">
                  {_xtf_polygon(1, 1, 3, 3)}
                </Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_Terreno>
              </Terreno>
            </Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_Predio>
          </DATASECTION>
        </XTF>
        """,
        encoding="utf-8",
    )

    tables = parse_xtf_tables(xtf_path, TARGET_CLASSES)
    issues = RULE_FUNCTIONS["5.2"](InMemoryDataset(tables))

    assert tables["ARB_DerechoInteresadoFuente"][0]["arb_predio_derecho"] == "p1"
    assert any(
        row.get("TID") == "t1" and row.get("arb_predio_terreno") == "p1"
        for row in tables["ARB_Terreno"]
    )
    assert len(issues) == 1
    assert issues[0].rule_id == "5.2"


def test_xtf_reader_adds_predio_ref_to_nested_unidad_construccion(tmp_path):
    xtf_path = tmp_path / "unidad_nested.xtf"
    xtf_path.write_text(
        """
        <XTF>
          <DATASECTION>
            <Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_Predio TID="p1">
              <Construccion>
                <Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_Construccion TID="c1">
                  <UnidadConstruccion>
                    <Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_UnidadConstruccion TID="u1" />
                  </UnidadConstruccion>
                </Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_Construccion>
              </Construccion>
            </Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_Predio>
          </DATASECTION>
        </XTF>
        """,
        encoding="utf-8",
    )

    tables = parse_xtf_tables(xtf_path, TARGET_CLASSES)
    unidad = tables["ARB_UnidadConstruccion"][0]

    assert unidad["construccion"] == "c1"
    assert unidad["predio"] == "p1"
    assert unidad["arb_predio_unidadconstruccion"] == "p1"

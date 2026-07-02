from quality_rules.complementarias import rule_10_1, rule_10_2, rule_10_3, rule_10_4
from quality_rules.dataset import InMemoryDataset
from quality_rules.xtf_reader import TARGET_CLASSES, parse_xtf_tables


def _numero_predial(*, pos18: str = "1", pos22: str = "1") -> str:
    chars = list("1" * 30)
    chars[17] = pos18
    chars[21] = pos22
    return "".join(chars)


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


def test_rule_10_1_detects_xtf_arb_marca_alias(tmp_path):
    xtf_path = tmp_path / "marca.xtf"
    xtf_path.write_text(
        """
        <XTF>
          <DATASECTION>
            <Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_Marca TID="m1">
              <Resuelta>false</Resuelta>
            </Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_Marca>
          </DATASECTION>
        </XTF>
        """,
        encoding="utf-8",
    )

    tables = parse_xtf_tables(xtf_path, TARGET_CLASSES)
    issues = rule_10_1(InMemoryDataset(tables))

    assert "ARB_MarcaPredial" in tables
    assert len(issues) == 1
    assert issues[0].rule_id == "10.1"


def test_rule_10_2_matches_direct_predio_nuevo_domain():
    dataset = InMemoryDataset(
        {
            "ARB_NovedadNumeroPredialValor": [
                {
                    "TID": "n1",
                    "Tipo_Novedad": "Predio_Nuevo",
                    "Numero_Predial": _numero_predial(pos18="0", pos22="2"),
                }
            ]
        }
    )

    issues = rule_10_2(dataset)

    assert len(issues) == 1
    assert issues[0].details["pos_18"] == "0"
    assert issues[0].details["pos_22"] == "2"


def test_rule_10_3_reads_xtf_geometry_xml():
    dataset = InMemoryDataset(
        {
            "ARB_UnidadConstruccion": [
                {
                    "TID": "u1",
                    "Tipo_Planta": "Piso",
                    "Planta_Ubicacion": "1",
                    "construccion": "c1",
                    "Geometria": _xtf_polygon(0, 0, 1, 1),
                },
                {
                    "TID": "u2",
                    "Tipo_Planta": "Piso",
                    "Planta_Ubicacion": "2",
                    "construccion": "c1",
                    "Geometria": _xtf_polygon(2, 2, 3, 3),
                },
            ]
        }
    )

    issues = rule_10_3(dataset)

    assert len(issues) == 1
    assert issues[0].rule_id == "10.3"
    assert issues[0].details["planta_superior"] == 2


def test_rule_10_3_passes_when_upper_floor_has_area_overlap():
    dataset = InMemoryDataset(
        {
            "ARB_UnidadConstruccion": [
                {
                    "TID": "u1",
                    "Tipo_Planta": "Piso",
                    "Planta_Ubicacion": "1",
                    "construccion": "c1",
                    "Geometria": _xtf_polygon(0, 0, 2, 2),
                },
                {
                    "TID": "u2",
                    "Tipo_Planta": "Piso",
                    "Planta_Ubicacion": "2",
                    "construccion": "c1",
                    "Geometria": _xtf_polygon(1, 1, 3, 3),
                },
            ]
        }
    )

    assert rule_10_3(dataset) == []


def test_rule_10_3_flags_touching_edges_without_area_overlap():
    dataset = InMemoryDataset(
        {
            "ARB_UnidadConstruccion": [
                {
                    "TID": "u1",
                    "Tipo_Planta": "Piso",
                    "Planta_Ubicacion": "1",
                    "construccion": "c1",
                    "Geometria": _xtf_polygon(0, 0, 1, 1),
                },
                {
                    "TID": "u2",
                    "Tipo_Planta": "Piso",
                    "Planta_Ubicacion": "2",
                    "construccion": "c1",
                    "Geometria": _xtf_polygon(1, 0, 2, 1),
                },
            ]
        }
    )

    issues = rule_10_3(dataset)

    assert len(issues) == 1
    assert issues[0].details["motivo"] == "Existe planta inferior, pero no hay superposición espacial con área mayor a cero."


def test_rule_10_3_flags_unknown_construction_for_upper_floor():
    dataset = InMemoryDataset(
        {
            "ARB_UnidadConstruccion": [
                {
                    "TID": "u1",
                    "Tipo_Planta": "Piso",
                    "Planta_Ubicacion": "1",
                    "Geometria": _xtf_polygon(0, 0, 1, 1),
                },
                {
                    "TID": "u2",
                    "Tipo_Planta": "Piso",
                    "Planta_Ubicacion": "2",
                    "Geometria": _xtf_polygon(0, 0, 1, 1),
                },
            ]
        }
    )

    issues = rule_10_3(dataset)

    assert len(issues) == 1
    assert issues[0].details["unidad_superior"] == "u2"
    assert issues[0].details["motivo"] == "Construcción no resuelta."


def test_rule_10_3_uses_construction_unit_association():
    dataset = InMemoryDataset(
        {
            "ARB_UnidadConstruccion": [
                {
                    "TID": "u1",
                    "Tipo_Planta": "Piso",
                    "Planta_Ubicacion": "1",
                    "Geometria": _xtf_polygon(0, 0, 1, 1),
                },
                {
                    "TID": "u2",
                    "Tipo_Planta": "Piso",
                    "Planta_Ubicacion": "2",
                    "Geometria": _xtf_polygon(10, 10, 11, 11),
                },
                {
                    "TID": "u3",
                    "Tipo_Planta": "Piso",
                    "Planta_Ubicacion": "1",
                    "Geometria": _xtf_polygon(10, 10, 11, 11),
                },
            ],
            "arb_construccion_unidadconstruccion": [
                {"construccion": "c1", "unidad_construccion": "u1"},
                {"construccion": "c1", "unidad_construccion": "u2"},
                {"construccion": "c2", "unidad_construccion": "u3"},
            ],
        }
    )

    issues = rule_10_3(dataset)

    assert len(issues) == 1
    assert issues[0].details["unidad_superior"] == "u2"
    assert issues[0].details["construccion"] == "c1"


def test_rule_10_3_deduplicates_same_upper_floor_error():
    duplicated_upper = {
        "TID": "u2",
        "Tipo_Planta": "Piso",
        "Planta_Ubicacion": "2",
        "construccion": "c1",
        "Geometria": _xtf_polygon(2, 2, 3, 3),
    }
    dataset = InMemoryDataset(
        {
            "ARB_UnidadConstruccion": [
                {
                    "TID": "u1",
                    "Tipo_Planta": "Piso",
                    "Planta_Ubicacion": "1",
                    "construccion": "c1",
                    "Geometria": _xtf_polygon(0, 0, 1, 1),
                },
                duplicated_upper,
                dict(duplicated_upper),
            ]
        }
    )

    issues = rule_10_3(dataset)

    assert len(issues) == 1
    assert issues[0].details["unidad_superior"] == "u2"


def test_rule_10_4_uses_parent_ref_for_nested_novedad(tmp_path):
    xtf_path = tmp_path / "novedad.xtf"
    numero_predial = _numero_predial(pos18="A", pos22="1")
    xtf_path.write_text(
        f"""
        <XTF>
          <DATASECTION>
            <Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_Predio TID="p1">
              <Id_Operacion>op1</Id_Operacion>
              <Numero_Predial>{numero_predial}</Numero_Predial>
              <Novedad_Numero_Predial>
                <Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_NovedadNumeroPredialValor>
                  <Numero_Predial>{numero_predial}</Numero_Predial>
                  <Tipo_Novedad>Predio_Nuevo</Tipo_Novedad>
                </Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_NovedadNumeroPredialValor>
              </Novedad_Numero_Predial>
            </Captura_ArbiMaps_V1_0.Captura_ArbiMaps.ARB_Predio>
          </DATASECTION>
        </XTF>
        """,
        encoding="utf-8",
    )

    tables = parse_xtf_tables(xtf_path, TARGET_CLASSES)
    issues = rule_10_4(InMemoryDataset(tables))

    assert tables["ARB_NovedadNumeroPredialValor"][0]["arb_predio_novedad_numero_predial"] == "p1"
    assert issues == []

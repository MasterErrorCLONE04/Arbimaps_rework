import pytest
from unittest.mock import MagicMock
from services.asignaciones_workspace_f_r1_r2_reverse import (
    sincronizar_predios_a_f_r1_r2,
    _get_r1_doc_type,
    _normalize_str,
)
from tenants import TenantContext
from tenants.models import MunicipalityDbConfig, MunicipalitySchemas


def make_tenant() -> TenantContext:
    return TenantContext(
        municipality_code="neiva",
        municipality_name="Neiva",
        db=MunicipalityDbConfig("localhost", 5432, "neiva", "postgres", "admin", sslmode="prefer"),
        schemas=MunicipalitySchemas(main="a_base_principal", work="b_asignaciones_arb"),
    )


def test_get_r1_doc_type():
    assert _get_r1_doc_type("Cedula_Ciudadania") == "C"
    assert _get_r1_doc_type("NIT") == "N"
    assert _get_r1_doc_type("Cedula_Extranjeria") == "E"
    assert _get_r1_doc_type("Pasaporte") == "P"
    assert _get_r1_doc_type("Registro_Civil") == "R"
    assert _get_r1_doc_type("Tarjeta_Identidad") == "T"
    assert _get_r1_doc_type(None) == "C"
    assert _get_r1_doc_type("Desconocido") == "C"


def test_normalize_str():
    assert _normalize_str(None) is None
    assert _normalize_str("") is None
    assert _normalize_str("   ") is None
    assert _normalize_str("  Calle 10  ") == "Calle 10"


def test_sincronizar_predios_a_f_r1_r2_empty_list():
    tenant = make_tenant()
    mock_conn = MagicMock()
    res = sincronizar_predios_a_f_r1_r2(mock_conn, tenant, [], "a_base_principal")
    assert res == 0


def test_sincronizar_predios_a_f_r1_r2_missing_schema():
    tenant = make_tenant()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None  # f_r1_r2 schema does not exist
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    res = sincronizar_predios_a_f_r1_r2(mock_conn, tenant, ["410010001000000010017000000000"], "a_base_principal")
    assert res == 0


def test_sincronizar_predios_a_f_r1_r2_success():
    tenant = make_tenant()
    npn = "410010001000000010017000000000"

    mock_cursor = MagicMock()

    # Sequence of fetch responses for cursor:
    # 1. Check schema f_r1_r2 exists -> True
    # 2. Check tables exist -> [{'table_name': 'r1_predio_propietario'}, {'table_name': 'r2_construccion_zona'}]
    # 3. Fetch arb_predio -> row with t_id=100
    # 4. Fetch arb_terreno -> row with area_terreno=150.50
    # 5. Fetch arb_direccion -> row with nombre_predio="CL 5 # 10-20"
    # 6. Fetch arb_avaluovalor -> row with avaluo_catastral=50000000.00
    # 7. Fetch arb_derechointeresadofuente -> list with 1 owner
    # 8. Fetch arb_novedadfmivalor -> row with numero_fmi="200-12345"
    # 9. Fetch arb_construccion + arb_unidadconstruccion -> list of ucons

    mock_cursor.fetchone.side_effect = [
        {"schema_name": "f_r1_r2"},  # 1. schema check
        {"t_id": 100, "numero_predial": npn, "numero_predial_anterior": "4100100000000", "area_catastral_terreno": 150.50, "observaciones": "Test"},  # 3. predio
        {"area_terreno": 150.50},  # 4. terreno
        {"nombre_predio": "CL 5 # 10-20"},  # 5. direccion
        {"avaluo_catastral": 50000000.00, "fecha_avaluo_catastral": "2026-01-01"},  # 6. avaluo
        {"numero_fmi": "200-12345"},  # 8. fmi
    ]

    mock_cursor.fetchall.side_effect = [
        [{"table_name": "r1_predio_propietario"}, {"table_name": "r2_construccion_zona"}],  # 2. tables check
        [  # 7. propietarios
            {
                "i_primer_nombre": "JUAN",
                "i_segundo_nombre": "CARLOS",
                "i_primer_apellido": "PEREZ",
                "i_segundo_apellido": "GOMEZ",
                "i_razon_social": None,
                "i_documento_identidad": "12345678",
                "d_cuota_participacion": 100.00,
                "ic_direccion_residencia": "CL 5 # 10-20",
                "tipo_doc_ilicode": "Cedula_Ciudadania",
            }
        ],
        [  # 9. ucons
            {
                "area_unidad_construccion": 80.00,
                "total_habitaciones": 3,
                "total_banios": 2,
                "total_locales": 0,
                "total_plantas": 1,
                "cc_total_calificacion": 65,
                "tipo_calificacion": 1447,
                "u_obs": "Bloque 1",
            }
        ],
    ]

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    res = sincronizar_predios_a_f_r1_r2(mock_conn, tenant, [npn], "a_base_principal")
    assert res == 1
    assert mock_cursor.execute.call_count > 5

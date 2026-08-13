import logging
import re
from typing import List, Optional
from psycopg2.extras import RealDictCursor
from tenants import TenantContext

logger = logging.getLogger(__name__)

_ILI_CODE_TO_R1_DOCUMENT_TYPE = {
    "Cedula_Ciudadania": "C",
    "Cedula_Extranjeria": "E",
    "NIT": "N",
    "Pasaporte": "P",
    "Registro_Civil": "R",
    "Tarjeta_Identidad": "T",
}


def _normalize_str(val: Optional[object]) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _get_r1_doc_type(ilicode: Optional[str]) -> str:
    if not ilicode:
        return "C"
    norm = str(ilicode).strip()
    return _ILI_CODE_TO_R1_DOCUMENT_TYPE.get(norm, "C")


def sincronizar_predios_a_f_r1_r2(
    conn,
    tenant: TenantContext,
    npn_list: List[str],
    schema_source: str,
) -> int:
    """
    Reverse ETL: Sincroniza una lista de NPNs desde el esquema origen (e.g. a_base_principal o schema_work)
    hacia el esquema f_r1_r2 (tablas f_r1_r2.r1_predio_propietario y f_r1_r2.r2_construccion_zona).

    Retorna el número de predios procesados exitosamente.
    """
    if not npn_list or not schema_source:
        return 0

    # Limpiar lista de NPNs
    clean_npns = list(dict.fromkeys(filter(None, [str(n).strip() for n in npn_list])))
    if not clean_npns:
        return 0

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 1. Verificar si existe el esquema f_r1_r2
        cur.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'f_r1_r2' LIMIT 1;"
        )
        if not cur.fetchone():
            logger.warning("El esquema 'f_r1_r2' no existe en la base de datos. Se omite el Reverse ETL.")
            return 0

        # Verificar si existen las tablas r1_predio_propietario y r2_construccion_zona
        cur.execute(
            """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'f_r1_r2' 
              AND table_name IN ('r1_predio_propietario', 'r2_construccion_zona');
            """
        )
        tables = {row["table_name"] for row in (cur.fetchall() or [])}
        if "r1_predio_propietario" not in tables or "r2_construccion_zona" not in tables:
            logger.warning("Tablas r1_predio_propietario o r2_construccion_zona no encontradas en f_r1_r2.")
            return 0

        synced_count = 0

        for npn in clean_npns:
            try:
                # 2. Consultar predio principal en schema_source
                cur.execute(
                    f"""
                    SELECT t_id, numero_predial, numero_predial_anterior, area_catastral_terreno, observaciones
                    FROM {schema_source}.arb_predio
                    WHERE BTRIM(numero_predial::text) = %s
                    LIMIT 1;
                    """,
                    (npn,),
                )
                predio_row = cur.fetchone()
                if not predio_row:
                    logger.debug("Predio %s no encontrado en %s para Reverse ETL.", npn, schema_source)
                    continue

                id_predio = predio_row["t_id"]
                npn_val = str(predio_row["numero_predial"]).strip()
                npn_anterior = _normalize_str(predio_row.get("numero_predial_anterior"))
                observaciones = _normalize_str(predio_row.get("observaciones"))

                # Extraer dpto y mpio del NPN (Dpto 2 pos, Mpio 3 pos)
                dpto = npn_val[:2] if len(npn_val) >= 2 else "41"
                mpio = npn_val[2:5] if len(npn_val) >= 5 else "001"

                # 3. Consultar Área de Terreno
                area_terreno = predio_row.get("area_catastral_terreno") or 0.00
                cur.execute(
                    f"""
                    SELECT area_terreno
                    FROM {schema_source}.arb_terreno
                    WHERE predio = %s
                    LIMIT 1;
                    """,
                    (id_predio,),
                )
                terreno_row = cur.fetchone()
                if terreno_row and terreno_row.get("area_terreno") is not None:
                    area_terreno = terreno_row["area_terreno"]

                # 4. Consultar Dirección
                direccion = None
                cur.execute(
                    f"""
                    SELECT nombre_predio
                    FROM {schema_source}.arb_direccion
                    WHERE arb_predio_direccion = %s
                    ORDER BY t_id ASC
                    LIMIT 1;
                    """,
                    (id_predio,),
                )
                dir_row = cur.fetchone()
                if dir_row and dir_row.get("nombre_predio"):
                    direccion = _normalize_str(dir_row["nombre_predio"])

                # 5. Consultar Avalúo y Vigencia
                avaluo = 0.00
                vigencia = None
                cur.execute(
                    f"""
                    SELECT avaluo_catastral, fecha_avaluo_catastral
                    FROM {schema_source}.arb_avaluovalor
                    WHERE arb_predio_avaluo = %s
                    ORDER BY t_id DESC
                    LIMIT 1;
                    """,
                    (id_predio,),
                )
                av_row = cur.fetchone()
                if av_row:
                    if av_row.get("avaluo_catastral") is not None:
                        avaluo = av_row["avaluo_catastral"]
                    if av_row.get("fecha_avaluo_catastral"):
                        vigencia = av_row["fecha_avaluo_catastral"]

                # 6. Consultar Propietarios (arb_derechointeresadofuente)
                cur.execute(
                    f"""
                    SELECT d.i_primer_nombre, d.i_segundo_nombre, d.i_primer_apellido, d.i_segundo_apellido,
                           d.i_razon_social, d.i_documento_identidad, d.d_cuota_participacion, d.ic_direccion_residencia,
                           t.ilicode AS tipo_doc_ilicode
                    FROM {schema_source}.arb_derechointeresadofuente d
                    LEFT JOIN {schema_source}.arb_interesadodocumentotipo t ON t.t_id = d.i_tipo_documento
                    WHERE d.predio = %s
                    ORDER BY d.t_id ASC;
                    """,
                    (id_predio,),
                )
                propietarios = cur.fetchall() or []

                # 7. Consultar Matrícula Inmobiliaria (novedad FMI o observaciones)
                matricula = None
                try:
                    cur.execute(
                        f"""
                        SELECT numero_fmi
                        FROM {schema_source}.arb_novedadfmivalor
                        WHERE arb_predio_novedad_fmi = %s
                        ORDER BY t_id DESC
                        LIMIT 1;
                        """,
                        (id_predio,),
                    )
                    fmi_row = cur.fetchone()
                    if fmi_row and fmi_row.get("numero_fmi"):
                        matricula = _normalize_str(fmi_row["numero_fmi"])
                except Exception:
                    pass

                if not matricula and observaciones:
                    # Intentar extraer Matrícula desde observaciones si fue importado con 'Matrícula: XYZ'
                    mat_match = re.search(r"Matrícula:\s*([^\s|]+)", observaciones)
                    if mat_match:
                        matricula = mat_match.group(1).strip()

                # 8. Consultar Construcciones y Unidades de Construcción
                area_construida_total = 0.00
                bloques_ucons = []

                cur.execute(
                    f"""
                    SELECT u.area_unidad_construccion,
                           c.total_habitaciones, c.total_banios, c.total_locales, c.total_plantas,
                           c.cc_total_calificacion, c.tipo_calificacion, c.observaciones AS u_obs
                    FROM {schema_source}.arb_construccion cons
                    JOIN {schema_source}.arb_unidadconstruccion u ON u.construccion = cons.t_id
                    LEFT JOIN {schema_source}.arb_caracteristicasunidadconstruccion c ON c.t_id = u.caracteristicasunidadconstruccion
                    WHERE cons.predio = %s
                    ORDER BY u.t_id ASC;
                    """,
                    (id_predio,),
                )
                ucons_rows = cur.fetchall() or []

                for u_row in ucons_rows:
                    u_area = float(u_row.get("area_unidad_construccion") or 0.00)
                    area_construida_total += u_area
                    bloques_ucons.append({
                        "habitaciones": int(u_row.get("total_habitaciones") or 0),
                        "banos": int(u_row.get("total_banios") or 0),
                        "locales": int(u_row.get("total_locales") or 0),
                        "pisos": int(u_row.get("total_plantas") or 0),
                        "puntaje": int(u_row.get("cc_total_calificacion") or 0),
                        "area_construida": u_area,
                    })

                # --- APLICAR REVERSE ETL A f_r1_r2.r1_predio_propietario ---
                # Eliminar registros anteriores del predio en r1_predio_propietario
                cur.execute(
                    "DELETE FROM f_r1_r2.r1_predio_propietario WHERE BTRIM(numero_predial::text) = %s;",
                    (npn_val,),
                )

                if propietarios:
                    total_regs = len(propietarios)
                    for idx, prop in enumerate(propietarios, start=1):
                        ilicode = prop.get("tipo_doc_ilicode")
                        tipo_doc = _get_r1_doc_type(ilicode)
                        doc_id = _normalize_str(prop.get("i_documento_identidad"))

                        if ilicode == "NIT" or prop.get("i_razon_social"):
                            nombre = _normalize_str(prop.get("i_razon_social"))
                        else:
                            nombre_parts = filter(None, [
                                _normalize_str(prop.get("i_primer_nombre")),
                                _normalize_str(prop.get("i_segundo_nombre")),
                                _normalize_str(prop.get("i_primer_apellido")),
                                _normalize_str(prop.get("i_segundo_apellido")),
                            ])
                            nombre = " ".join(nombre_parts) or None

                        participacion = float(prop.get("d_cuota_participacion") or 100.00)
                        prop_dir = _normalize_str(prop.get("ic_direccion_residencia")) or direccion

                        cur.execute(
                            """
                            INSERT INTO f_r1_r2.r1_predio_propietario (
                                departamento, municipio, numero_predial, tipo_registro,
                                numero_de_orden, total_registros, nombre, participacion,
                                tipo_documento, documento_identidad, direccion,
                                area_terreno, area_construida, avaluo, vigencia, numero_predial_anterior
                            )
                            VALUES (
                                %s, %s, %s, 1,
                                %s, %s, %s, %s,
                                %s, %s, %s,
                                %s, %s, %s, %s, %s
                            );
                            """,
                            (
                                dpto, mpio, npn_val,
                                idx, total_regs, nombre, participacion,
                                tipo_doc, doc_id, prop_dir,
                                area_terreno, area_construida_total, avaluo, vigencia, npn_anterior,
                            ),
                        )
                else:
                    # Sin propietarios registrados, crear 1 entrada general
                    cur.execute(
                        """
                        INSERT INTO f_r1_r2.r1_predio_propietario (
                            departamento, municipio, numero_predial, tipo_registro,
                            numero_de_orden, total_registros, nombre, participacion,
                            tipo_documento, documento_identidad, direccion,
                            area_terreno, area_construida, avaluo, vigencia, numero_predial_anterior
                        )
                        VALUES (
                            %s, %s, %s, 1,
                            1, 1, NULL, 100.00,
                            'C', NULL, %s,
                            %s, %s, %s, %s, %s
                        );
                        """,
                        (
                            dpto, mpio, npn_val,
                            direccion,
                            area_terreno, area_construida_total, avaluo, vigencia, npn_anterior,
                        ),
                    )

                # --- APLICAR REVERSE ETL A f_r1_r2.r2_construccion_zona ---
                # Eliminar registros anteriores del predio en r2_construccion_zona
                cur.execute(
                    "DELETE FROM f_r1_r2.r2_construccion_zona WHERE BTRIM(numero_predial::text) = %s;",
                    (npn_val,),
                )

                b1 = bloques_ucons[0] if len(bloques_ucons) > 0 else {}
                b2 = bloques_ucons[1] if len(bloques_ucons) > 1 else {}
                b3 = bloques_ucons[2] if len(bloques_ucons) > 2 else {}

                cur.execute(
                    """
                    INSERT INTO f_r1_r2.r2_construccion_zona (
                        departamento, municipio, numero_predial, tipo_registro,
                        numero_de_orden, total_registros, matricula,
                        habitaciones_1, banos_1, locales_1, pisos_1, puntaje_1, area_construida_1,
                        habitaciones_2, banos_2, locales_2, pisos_2, puntaje_2, area_construida_2,
                        habitaciones_3, banos_3, locales_3, pisos_3, puntaje_3, area_construida_3,
                        vigencia, numero_predial_anterior
                    )
                    VALUES (
                        %s, %s, %s, 2,
                        1, 1, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s
                    );
                    """,
                    (
                        dpto, mpio, npn_val,
                        matricula,
                        b1.get("habitaciones", 0), b1.get("banos", 0), b1.get("locales", 0), b1.get("pisos", 0), b1.get("puntaje", 0), b1.get("area_construida", 0.00),
                        b2.get("habitaciones", 0), b2.get("banos", 0), b2.get("locales", 0), b2.get("pisos", 0), b2.get("puntaje", 0), b2.get("area_construida", 0.00),
                        b3.get("habitaciones", 0), b3.get("banos", 0), b3.get("locales", 0), b3.get("pisos", 0), b3.get("puntaje", 0), b3.get("area_construida", 0.00),
                        vigencia, npn_anterior,
                    ),
                )

                synced_count += 1
                logger.info("Reverse ETL a f_r1_r2 completado para el predio %s.", npn_val)

            except Exception as e:
                logger.error("Error durante Reverse ETL a f_r1_r2 para predio %s: %s", npn, e, exc_info=True)

        return synced_count

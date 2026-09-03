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


def _get_table_columns(cur, schema: str, table_name: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s;
        """,
        (schema, table_name),
    )
    rows = cur.fetchall() or []
    cols = set()
    for r in rows:
        if isinstance(r, dict):
            c = r.get("column_name")
        else:
            c = r[0] if r else None
        if c:
            cols.add(str(c))
    return cols


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


_DESTINO_ILICODE_TO_R2_CODE = {
    "HABITACIONAL": "A",
    "INDUSTRIAL": "B",
    "COMERCIAL": "C",
    "AGROPECUARIO": "D",
    "CULTURAL": "F",
    "RECREACIONAL": "G",
    "SALUBRIDAD": "H",
    "INSTITUCIONAL": "I",
    "EDUCATIVO": "J",
    "RELIGIOSO": "K",
    "AGRICOLA": "L",
    "PECUARIO": "M",
    "AGROINDUSTRIAL": "N",
    "FORESTAL_PRODUCTOR": "O",
    "USO_PUBLICO": "P",
    "INFRAESTRUCTURA_ASOCIADA_PRODUCCION_AGROPECUARIA": "Q",
    "LOTE_URBANIZABLE_NO_URBANIZADO": "R",
    "LOTE_URBANIZADO_NO_CONSTRUIDO": "S",
    "LOTE_NO_URBANIZABLE": "T",
    "ACUICOLA": "U",
    "INFRAESTRUCTURA_HIDRAULICA": "V",
    "MINERIA_HIDROCARBUROS": "W",
    "INFRAESTRUCTURA_TRANSPORTE": "X",
    "SERVICIOS_FUNERARIOS": "Y",
    "AGROFORESTAL": "Z",
    "INFRAESTRUCTURA_SANEAMIENTO_BASICO": "1",
    "INFRAESTRUCTURA_SEGURIDAD": "2",
    "INFRAESTRUCTURA_ENERVABLE_ELECTRICA": "3",
    "INFRAESTRUCTURA_ENERGIA_RENOVABLE_ELECTRICA": "3",
    "LOTE_RURAL": "4",
}


def _resolve_destino_economico_r1(cur, raw_val, schema_source: str) -> str:
    if not raw_val:
        return "A"

    val_str = str(raw_val).strip()

    # Si ya es una clave valida de f_r1_r2.destino_economico
    try:
        cur.execute(
            "SELECT codigo FROM f_r1_r2.destino_economico WHERE BTRIM(codigo::text) = %s LIMIT 1;",
            (val_str,),
        )
        r = cur.fetchone()
        if r and r.get("codigo"):
            return str(r["codigo"]).strip()
    except Exception:
        pass

    # Si es un t_id numerico de arb_destinacioneconomicatipo
    if val_str.isdigit():
        try:
            cur.execute(
                f"SELECT ilicode FROM {schema_source}.arb_destinacioneconomicatipo WHERE t_id = %s LIMIT 1;",
                (int(val_str),),
            )
            type_row = cur.fetchone()
            if type_row and type_row.get("ilicode"):
                ilicode = str(type_row["ilicode"]).strip().upper()
                code_mapped = _DESTINO_ILICODE_TO_R2_CODE.get(ilicode)
                if code_mapped:
                    return code_mapped
        except Exception:
            pass

    return "A"


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

        # Verificar columnas de arb_predio en Python antes de construir el query
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = 'arb_predio';",
            (schema_source,)
        )
        predio_cols = set()
        for row in (cur.fetchall() or []):
            if isinstance(row, dict):
                val = row.get("column_name") or row.get("COLUMN_NAME") or (list(row.values())[0] if row else None)
            elif isinstance(row, (list, tuple)):
                val = row[0]
            else:
                val = getattr(row, "column_name", str(row))
            if val:
                predio_cols.add(str(val))
        if "destino_economico" in predio_cols:
            dest_col_expr = "destino_economico::text"
        elif "destinacion_economica" in predio_cols:
            dest_col_expr = "destinacion_economica::text"
        else:
            dest_col_expr = "'01'"

        if "estado" in predio_cols:
            estado_col_expr = "estado::text"
        else:
            estado_col_expr = "NULL::text"

        if "codigo_orip" in predio_cols:
            orip_col_expr = "codigo_orip::text"
        else:
            orip_col_expr = "NULL::text"

        if "matricula_inmobiliaria" in predio_cols:
            mat_col_expr = "matricula_inmobiliaria::text"
        else:
            mat_col_expr = "NULL::text"

        synced_count = 0

        for npn in clean_npns:
            sp_name = f"sp_retl_{abs(hash(npn)) % 10000000}"
            try:
                cur.execute(f"SAVEPOINT {sp_name};")
                # 2. Consultar predio principal en schema_source
                cur.execute(
                    f"""
                    SELECT t_id, numero_predial, numero_predial_anterior, area_catastral_terreno, observaciones,
                           COALESCE({dest_col_expr}, '01') AS destino_economico,
                           {orip_col_expr} AS codigo_orip,
                           {mat_col_expr} AS matricula_inmobiliaria,
                           {estado_col_expr} AS predio_estado
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
                codigo_orip = _normalize_str(predio_row.get("codigo_orip"))
                matricula = _normalize_str(predio_row.get("matricula_inmobiliaria"))

                # Detección del Estado de Cancelación
                is_cancelled = False
                predio_estado_raw = predio_row.get("predio_estado")
                if predio_estado_raw:
                    raw_str = str(predio_estado_raw).strip().lower()
                    if raw_str in ("cancelado", "cancelacion"):
                        is_cancelled = True
                    elif raw_str.isdigit():
                        try:
                            cur.execute(
                                f"SELECT ilicode, dispname FROM {schema_source}.arb_estadotipo WHERE t_id = %s LIMIT 1;",
                                (int(raw_str),)
                            )
                            et_row = cur.fetchone()
                            if et_row:
                                ili = str(et_row.get("ilicode") or "").strip().lower()
                                disp = str(et_row.get("dispname") or "").strip().lower()
                                if "cancelado" in ili or "cancelado" in disp or "cancelacion" in ili or "cancelacion" in disp:
                                    is_cancelled = True
                        except Exception as e:
                            pass

                if not is_cancelled:
                    try:
                        cur.execute(
                            f"""
                            SELECT 1
                            FROM {schema_source}.arb_novedadnumeropredialvalor nnp
                            LEFT JOIN {schema_source}.arb_novedadnumeropredialtipo nt ON nt.t_id = nnp.tipo_novedad
                            WHERE nnp.arb_predio_novedad_numero_predial = %s
                              AND (
                                LOWER(BTRIM(nt.ilicode::text)) IN ('cancelacion', 'cancelacion_por_desenglobe', 'cancelacion_por_englobe')
                                OR LOWER(BTRIM(nnp.tipo_novedad::text)) LIKE 'cancelacion%'
                              )
                            LIMIT 1;
                            """,
                            (id_predio,),
                        )
                        if cur.fetchone():
                            is_cancelled = True
                    except Exception:
                        pass

                estado_r1_val = "CANCELADO" if is_cancelled else "ACTIVO"

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
                           d.d_tipo, d.d_fecha_inicio_tenencia, d.fa_tipo, d.fa_numero_fuente, d.fa_fecha_documento_fuente, d.fa_ente_emisor,
                           t.ilicode AS tipo_doc_ilicode
                    FROM {schema_source}.arb_derechointeresadofuente d
                    LEFT JOIN {schema_source}.arb_interesadodocumentotipo t ON t.t_id = d.i_tipo_documento
                    WHERE d.predio = %s
                    ORDER BY d.t_id ASC;
                    """,
                    (id_predio,),
                )
                propietarios = cur.fetchall() or []

                # 7. Consultar Matrícula Inmobiliaria (predio, novedad FMI u observaciones)
                if not matricula:
                    try:
                        cur.execute(
                            f"""
                            SELECT *
                            FROM {schema_source}.arb_novedadfmivalor
                            WHERE arb_predio_novedad_fmi = %s
                            ORDER BY t_id DESC
                            LIMIT 1;
                            """,
                            (id_predio,),
                        )
                        fmi_row = cur.fetchone()
                        if fmi_row:
                            if fmi_row.get("numero_fmi"):
                                matricula = _normalize_str(fmi_row["numero_fmi"])
                            if not codigo_orip:
                                fmi_orip = fmi_row.get("codigo_orip") or fmi_row.get("codio_orip")
                                if fmi_orip:
                                    codigo_orip = _normalize_str(fmi_orip)
                    except Exception:
                        pass

                if not matricula and observaciones:
                    # Intentar extraer Matrícula desde observaciones si fue importado con 'Matrícula: XYZ'
                    mat_match = re.search(r"Matrícula:\s*([^\s|]+)", observaciones)
                    if mat_match:
                        matricula = mat_match.group(1).strip()

                if not codigo_orip and observaciones:
                    orip_match = re.search(r"ORIP:\s*([^\s|]+)", observaciones)
                    if orip_match and orip_match.group(1):
                        codigo_orip = orip_match.group(1).strip()

                # Formatear la matrícula del R2 uniendo codigo_orip + matricula (ej: 200-4895)
                if codigo_orip and matricula:
                    if not matricula.startswith(f"{codigo_orip}-"):
                        matricula = f"{codigo_orip}-{matricula}"

                # 8. Consultar Construcciones y Unidades de Construcción
                area_construida_total = 0.00
                bloques_ucons = []

                cur.execute(
                    f"""
                    SELECT u.area_unidad_construccion,
                           c.total_habitaciones, c.total_banios, c.total_locales, c.total_plantas,
                           c.cc_total_calificacion, c.tipo_calificacion, c.tipo_unidad_construccion, c.observaciones AS u_obs
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
                    tipif_val = u_row.get("tipo_calificacion")
                    uso_val = u_row.get("tipo_unidad_construccion")
                    bloques_ucons.append({
                        "habitaciones": int(u_row.get("total_habitaciones") or 0),
                        "banos": int(u_row.get("total_banios") or 0),
                        "locales": int(u_row.get("total_locales") or 0),
                        "pisos": int(u_row.get("total_plantas") or 0),
                        "puntaje": int(u_row.get("cc_total_calificacion") or 0),
                        "tipificacion": int(tipif_val) if tipif_val and str(tipif_val).isdigit() else 0,
                        "uso": int(uso_val) if uso_val and str(uso_val).isdigit() else 0,
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

                        comuna_val = npn_val[9:11] if len(npn_val) >= 11 else None
                        dest_econ = _resolve_destino_economico_r1(cur, predio_row.get("destino_economico"), schema_source)
                        d_tipo_val = prop.get("d_tipo")
                        d_fecha_val = prop.get("d_fecha_inicio_tenencia")
                        fa_tipo_val = prop.get("fa_tipo")
                        fa_num_val = _normalize_str(prop.get("fa_numero_fuente"))
                        fa_fecha_val = prop.get("fa_fecha_documento_fuente")
                        fa_ente_val = _normalize_str(prop.get("fa_ente_emisor"))

                        r1_cols = set(_get_table_columns(cur, "f_r1_r2", "r1_predio_propietario"))
                        r1_data = {
                            "departamento": dpto,
                            "municipio": mpio,
                            "numero_predial": npn_val,
                            "tipo_registro": 1,
                            "numero_de_orden": idx,
                            "total_registros": total_regs,
                            "nombre": nombre,
                            "participacion": participacion,
                            "tipo_documento": tipo_doc,
                            "documento_identidad": doc_id,
                            "direccion": prop_dir,
                            "comuna": comuna_val,
                            "destino_economico": dest_econ,
                            "area_terreno": area_terreno,
                            "area_construida": area_construida_total,
                            "avaluo": avaluo,
                            "vigencia": vigencia,
                            "numero_predial_anterior": npn_anterior,
                            "d_tipo": d_tipo_val,
                            "d_fecha_inicio_tenencia": d_fecha_val,
                            "fa_tipo": fa_tipo_val,
                            "fa_numero_fuente": fa_num_val,
                            "fa_fecha_documento_fuente": fa_fecha_val,
                            "fa_ente_emisor": fa_ente_val,
                            "estado": estado_r1_val,
                        }
                        valid_r1_data = {k: v for k, v in r1_data.items() if k in r1_cols}
                        cols_str = ", ".join(valid_r1_data.keys())
                        placeholders = ", ".join(["%s"] * len(valid_r1_data))
                        cur.execute(
                            f"INSERT INTO f_r1_r2.r1_predio_propietario ({cols_str}) VALUES ({placeholders});",
                            tuple(valid_r1_data.values()),
                        )
                else:
                    # Sin propietarios registrados, crear 1 entrada general
                    comuna_val = npn_val[9:11] if len(npn_val) >= 11 else None
                    dest_econ = _resolve_destino_economico_r1(cur, predio_row.get("destino_economico"), schema_source)
                    r1_cols = set(_get_table_columns(cur, "f_r1_r2", "r1_predio_propietario"))
                    r1_gen_data = {
                        "departamento": dpto,
                        "municipio": mpio,
                        "numero_predial": npn_val,
                        "tipo_registro": 1,
                        "numero_de_orden": 1,
                        "total_registros": 1,
                        "nombre": None,
                        "participacion": 100.00,
                        "tipo_documento": "C",
                        "documento_identidad": None,
                        "direccion": direccion,
                        "comuna": comuna_val,
                        "destino_economico": dest_econ,
                        "area_terreno": area_terreno,
                        "area_construida": area_construida_total,
                        "avaluo": avaluo,
                        "vigencia": vigencia,
                        "numero_predial_anterior": npn_anterior,
                        "estado": estado_r1_val,
                    }
                    valid_gen_data = {k: v for k, v in r1_gen_data.items() if k in r1_cols}
                    cols_str = ", ".join(valid_gen_data.keys())
                    placeholders = ", ".join(["%s"] * len(valid_gen_data))
                    cur.execute(
                        f"INSERT INTO f_r1_r2.r1_predio_propietario ({cols_str}) VALUES ({placeholders});",
                        tuple(valid_gen_data.values()),
                    )

                # --- APLICAR REVERSE ETL A f_r1_r2.r2_construccion_zona ---
                # Eliminar registros anteriores del predio en r2_construccion_zona
                cur.execute(
                    "DELETE FROM f_r1_r2.r2_construccion_zona WHERE BTRIM(numero_predial::text) = %s;",
                    (npn_val,),
                )

                import math
                if bloques_ucons:
                    total_r2_regs = math.ceil(len(bloques_ucons) / 3.0)
                    for r2_idx in range(total_r2_regs):
                        order_num = r2_idx + 1
                        chunk = bloques_ucons[r2_idx * 3 : (r2_idx + 1) * 3]
                        b1 = chunk[0] if len(chunk) > 0 else {}
                        b2 = chunk[1] if len(chunk) > 1 else {}
                        b3 = chunk[2] if len(chunk) > 2 else {}

                        cur.execute(
                            """
                            INSERT INTO f_r1_r2.r2_construccion_zona (
                                departamento, municipio, numero_predial, tipo_registro,
                                numero_de_orden, total_registros, matricula,
                                habitaciones_1, banos_1, locales_1, pisos_1, tipificacion_1, uso_1, puntaje_1, area_construida_1,
                                habitaciones_2, banos_2, locales_2, pisos_2, tipificacion_2, uso_2, puntaje_2, area_construida_2,
                                habitaciones_3, banos_3, locales_3, pisos_3, tipificacion_3, uso_3, puntaje_3, area_construida_3,
                                vigencia, numero_predial_anterior
                            )
                            VALUES (
                                %s, %s, %s, 2,
                                %s, %s, %s,
                                %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s
                            );
                            """,
                            (
                                dpto, mpio, npn_val,
                                order_num, total_r2_regs, matricula,
                                b1.get("habitaciones", 0), b1.get("banos", 0), b1.get("locales", 0), b1.get("pisos", 0), b1.get("tipificacion", 0), b1.get("uso", 0), b1.get("puntaje", 0), b1.get("area_construida", 0.00),
                                b2.get("habitaciones", 0), b2.get("banos", 0), b2.get("locales", 0), b2.get("pisos", 0), b2.get("tipificacion", 0), b2.get("uso", 0), b2.get("puntaje", 0), b2.get("area_construida", 0.00),
                                b3.get("habitaciones", 0), b3.get("banos", 0), b3.get("locales", 0), b3.get("pisos", 0), b3.get("tipificacion", 0), b3.get("uso", 0), b3.get("puntaje", 0), b3.get("area_construida", 0.00),
                                vigencia, npn_anterior,
                            ),
                        )
                else:
                    # Sin unidades de construcción registradas, crear 1 entrada general de ceros
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
                            0, 0, 0, 0, 0, 0.00,
                            0, 0, 0, 0, 0, 0.00,
                            0, 0, 0, 0, 0, 0.00,
                            %s, %s
                        );
                        """,
                        (
                            dpto, mpio, npn_val,
                            matricula,
                            vigencia, npn_anterior,
                        ),
                    )

                synced_count += 1
                logger.info("Reverse ETL a f_r1_r2 completado para el predio %s.", npn_val)

            except Exception as e:
                try:
                    cur.execute(f"ROLLBACK TO SAVEPOINT {sp_name};")
                except Exception:
                    pass
                logger.error("Error durante Reverse ETL a f_r1_r2 para predio %s: %s", npn, e, exc_info=True)

        return synced_count

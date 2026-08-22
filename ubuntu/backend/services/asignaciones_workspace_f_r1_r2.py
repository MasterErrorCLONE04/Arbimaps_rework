import logging
import re
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

def _normalize_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


_R1_DOCUMENT_TYPE_TO_ILI_CODE = {
    "C": "Cedula_Ciudadania",
    "E": "Cedula_Extranjeria",
    "N": "NIT",
    "P": "Pasaporte",
    "R": "Registro_Civil",
    "T": "Tarjeta_Identidad",
    "X": None,
}


def _document_type_ilicode(value) -> str | None:
    normalized = _normalize_text(value).upper()
    compact = re.sub(r"[^A-Z0-9]+", "", normalized)
    if compact in _R1_DOCUMENT_TYPE_TO_ILI_CODE:
        return _R1_DOCUMENT_TYPE_TO_ILI_CODE[compact]

    aliases = {
        "CEDULA": "Cedula_Ciudadania",
        "CEDULADECIUDADANIA": "Cedula_Ciudadania",
        "CC": "Cedula_Ciudadania",
        "CEDULAEXTRANJERIA": "Cedula_Extranjeria",
        "CE": "Cedula_Extranjeria",
        "NIT": "NIT",
        "NI": "NIT",
        "31": "NIT",
        "PASAPORTE": "Pasaporte",
        "PA": "Pasaporte",
        "REGISTROCIVIL": "Registro_Civil",
        "RC": "Registro_Civil",
        "TARJETAIDENTIDAD": "Tarjeta_Identidad",
        "TI": "Tarjeta_Identidad",
        "1": "Pasaporte",
        "2": "Tarjeta_Identidad",
        "3": "Cedula_Extranjeria",
        "4": "Cedula_Ciudadania",
        "5": "NIT",
        "6": "Registro_Civil",
    }
    return aliases.get(compact)


def _is_nit_document_type(value) -> bool:
    return _document_type_ilicode(value) == "NIT"


def _split_natural_person_name(value) -> dict[str, str | None]:
    """
    Best-effort split for R1 names. R1 stores a single display name, while
    Arbimaps expects natural persons split into first/second name and surnames.
    """
    name = _normalize_text(value)
    if not name:
        return {
            "primer_nombre": None,
            "segundo_nombre": None,
            "primer_apellido": None,
            "segundo_apellido": None,
        }

    tokens = name.split(" ")
    if len(tokens) == 1:
        return {
            "primer_nombre": tokens[0],
            "segundo_nombre": None,
            "primer_apellido": None,
            "segundo_apellido": None,
        }
    if len(tokens) == 2:
        return {
            "primer_nombre": tokens[0],
            "segundo_nombre": None,
            "primer_apellido": tokens[1],
            "segundo_apellido": None,
        }
    if len(tokens) == 3:
        return {
            "primer_nombre": tokens[0],
            "segundo_nombre": tokens[1],
            "primer_apellido": tokens[2],
            "segundo_apellido": None,
        }

    return {
        "primer_nombre": tokens[0],
        "segundo_nombre": " ".join(tokens[1:-2]) or None,
        "primer_apellido": tokens[-2],
        "segundo_apellido": tokens[-1],
    }

def importar_predio_f_r1_r2_a_workspace(conn, tenant, npn: str, schema_work: str, t_basket_id: int) -> bool:
    """
    Importa un predio desde f_r1_r2 hacia el schema de trabajo (schema_work),
    asociándolo al basket_id correspondiente al dataset del reconocedor.
    """
    logger.info("Iniciando importación alfanumérica de predio %s al workspace %s...", npn, schema_work)
    
    # Geometrías Dummy estandarizadas de respaldo (EPSG:9377)
    dummy_terreno_sql = """
        ST_GeomFromText('MULTIPOLYGON(((4742898.743 1879567.779, 4742799.502 1879542.969, 4742781.108 1879623.603, 4742870.831 1879652.798, 4742898.743 1879567.779)))', 9377)
    """
    dummy_construccion_sql = """
        ST_GeomFromText('MULTIPOLYGON(((4742790.937 1879618.418, 4742806.122 1879550.404, 4742847.402 1879560.670, 4742829.222 1879629.326, 4742790.937 1879618.418)))', 9377)
    """
    dummy_direccion_sql = """
        ST_GeomFromText('POINT(4742854.116 1879599.176)', 9377)
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 1. Asegurar longitud de columnas identificadoras y quitar NOT NULL
        for tbl in ['arb_unidadconstruccion', 'arb_caracteristicasunidadconstruccion']:
            sp_name = f"sp_alter_{tbl}"
            try:
                cur.execute(f"SAVEPOINT {sp_name};")
                cur.execute(f'ALTER TABLE {schema_work}.{tbl} ALTER COLUMN identificador TYPE varchar(60);')
                cur.execute(f"RELEASE SAVEPOINT {sp_name};")
            except Exception as e:
                try:
                    cur.execute(f"ROLLBACK TO SAVEPOINT {sp_name};")
                except Exception:
                    pass
                logger.debug("Bypass ALTER COLUMN en %s: %s", tbl, e)

        # Quitar restricciones NOT NULL en campos opcionales del LADM
        for table_name in ['arb_derechointeresadofuente', 'arb_caracteristicasunidadconstruccion']:
            try:
                cur.execute(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_schema = '{schema_work}' AND table_name = '{table_name}' AND is_nullable = 'NO';
                """)
                columns = cur.fetchall()
                for col in columns:
                    col_name = col['column_name']
                    if col_name not in ('t_id', 't_basket'):
                        try:
                            cur.execute(f'ALTER TABLE {schema_work}.{table_name} ALTER COLUMN "{col_name}" DROP NOT NULL;')
                        except Exception:
                            pass
            except Exception as e:
                logger.debug("Error al remover NOT NULL en %s: %s", table_name, e)

        # 2. Consultar si tiene geometrías espaciales reales en a_base_principal
        geom_terreno = dummy_terreno_sql
        geom_construccion = dummy_construccion_sql
        
        has_geo_base = False
        try:
            cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'a_base_principal';")
            has_geo_base = bool(cur.fetchone())
        except Exception:
            pass

        if has_geo_base:
            # Obtener geometría de terreno
            try:
                cur.execute("SAVEPOINT trace_geom_terreno;")
                cur.execute(
                    """
                    SELECT t.geometria 
                    FROM a_base_principal.arb_terreno t
                    JOIN a_base_principal.arb_predio p ON p.t_id = t.predio
                    WHERE p.numero_predial = %s 
                    LIMIT 1;
                    """,
                    (npn,),
                )
                res = cur.fetchone()
                if res and res.get('geometria'):
                    geom_terreno = "%s"
                    geom_terreno_val = res['geometria']
                else:
                    geom_terreno_val = None
                cur.execute("RELEASE SAVEPOINT trace_geom_terreno;")
            except Exception as e:
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT trace_geom_terreno;")
                except Exception:
                    pass
                logger.warning("Error al obtener geometría de terreno: %s", e)
                geom_terreno_val = None

            # Obtener geometría de construcción
            try:
                cur.execute("SAVEPOINT trace_geom_construccion;")
                cur.execute(
                    """
                    SELECT c.geometria 
                    FROM a_base_principal.arb_construccion c
                    JOIN a_base_principal.arb_predio p ON p.t_id = c.predio
                    WHERE p.numero_predial = %s 
                    LIMIT 1;
                    """,
                    (npn,),
                )
                res_c = cur.fetchone()
                if res_c and res_c.get('geometria'):
                    geom_construccion = "%s"
                    geom_cons_val = res_c['geometria']
                else:
                    geom_cons_val = None
                cur.execute("RELEASE SAVEPOINT trace_geom_construccion;")
            except Exception as e:
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT trace_geom_construccion;")
                except Exception:
                    pass
                logger.warning("Error al obtener geometría de construcción: %s", e)
                geom_cons_val = None
        else:
            geom_terreno_val = None
            geom_cons_val = None

        # 3. Insertar arb_predio
        # Verificar si arb_predio tiene la columna destino_economico
        has_dest_col = False
        with conn.cursor() as check_cur:
            check_cur.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_schema = %s AND table_name = 'arb_predio' AND column_name = 'destino_economico' LIMIT 1;",
                (schema_work,)
            )
            has_dest_col = bool(check_cur.fetchone())

        dest_col_sql = ", destino_economico" if has_dest_col else ""
        dest_val_sql = ", COALESCE(r1.destino_economico, '01')" if has_dest_col else ""

        sql_predio = f"""
            INSERT INTO {schema_work}.arb_predio (
                t_id, t_basket, id_operacion, numero_predial, numero_predial_anterior,
                area_catastral_terreno, observaciones{dest_col_sql}
            )
            SELECT DISTINCT ON (r1.numero_predial)
                nextval('{schema_work}.t_ili2db_seq'),
                %s,
                r1.numero_predial,
                r1.numero_predial,
                r1.numero_predial_anterior,
                r1.area_terreno,
                CONCAT('Asignación Backend (f_r1_r2) - Dirección: ', r1.direccion, ' | Matrícula: ', COALESCE(r2.matricula, ''), ' | Destino: ', COALESCE(r1.destino_economico, ''))
                {dest_val_sql}
            FROM f_r1_r2.r1_predio_propietario r1
            LEFT JOIN f_r1_r2.r2_construccion_zona r2 ON r1.numero_predial = r2.numero_predial
            WHERE r1.numero_predial = %s
            ON CONFLICT DO NOTHING;
        """
        sp_pred = f"sp_pred_{abs(hash(npn)) % 10000000}"
        try:
            cur.execute(f"SAVEPOINT {sp_pred};")
            cur.execute(sql_predio, (t_basket_id, npn))
            cur.execute(f"RELEASE SAVEPOINT {sp_pred};")
        except Exception as pred_err:
            try:
                cur.execute(f"ROLLBACK TO SAVEPOINT {sp_pred};")
            except Exception:
                pass
            logger.info("El predio %s ya existia o tuvo conflicto al insertar en arb_predio: %s", npn, pred_err)

        # Obtener t_id de predio
        cur.execute(f"SELECT t_id, area_catastral_terreno FROM {schema_work}.arb_predio WHERE numero_predial = %s ORDER BY t_id DESC LIMIT 1;", (npn,))
        pred_row = cur.fetchone()
        if not pred_row:
            logger.warning("Predio %s no encontrado en f_r1_r2 para importar.", npn)
            return False

        id_predio = pred_row['t_id']
        area_terreno = pred_row['area_catastral_terreno']

        # 4. Insertar arb_terreno
        sql_terreno = f"""
            INSERT INTO {schema_work}.arb_terreno (
                t_id, t_basket, predio, area_terreno, etiqueta, geometria
            )
            VALUES (
                nextval('{schema_work}.t_ili2db_seq'),
                %s, %s, %s, %s, {geom_terreno}
            )
            ON CONFLICT DO NOTHING;
        """
        if geom_terreno == "%s":
            cur.execute(sql_terreno, (t_basket_id, id_predio, area_terreno, f"Terreno Predio {npn}", geom_terreno_val))
        else:
            cur.execute(sql_terreno, (t_basket_id, id_predio, area_terreno, f"Terreno Predio {npn}"))

        # 5. Insertar arb_direccion
        sql_dir = f"""
            INSERT INTO {schema_work}.arb_direccion (
                t_id, t_basket, tipo_direccion, arb_predio_direccion, nombre_predio, localizacion
            )
            SELECT DISTINCT ON (r1.numero_predial)
                nextval('{schema_work}.t_ili2db_seq'),
                %s, 1544, %s, r1.direccion, {dummy_direccion_sql}
            FROM f_r1_r2.r1_predio_propietario r1
            WHERE r1.numero_predial = %s
            ON CONFLICT DO NOTHING;
        """
        cur.execute(sql_dir, (t_basket_id, id_predio, npn))

        # 6. Insertar arb_avaluovalor
        sql_av = f"""
            INSERT INTO {schema_work}.arb_avaluovalor (
                t_id, t_basket, arb_predio_avaluo, avaluo_catastral, fecha_avaluo_catastral, autoestimacion
            )
            SELECT DISTINCT ON (r1.numero_predial)
                nextval('{schema_work}.t_ili2db_seq'),
                %s, %s, r1.avaluo, COALESCE(r1.vigencia, CURRENT_DATE), false
            FROM f_r1_r2.r1_predio_propietario r1
            WHERE r1.numero_predial = %s
            ON CONFLICT DO NOTHING;
        """
        cur.execute(sql_av, (t_basket_id, id_predio, npn))

        # 7. Insertar arb_construccion
        sql_cons = f"""
            INSERT INTO {schema_work}.arb_construccion (
                t_id, t_basket, identificador, predio, area_total_construccion, geometria
            )
            SELECT DISTINCT ON (r2.numero_predial)
                nextval('{schema_work}.t_ili2db_seq'),
                %s, CONCAT('CONS_', r2.numero_predial), %s,
                (COALESCE(r2.area_construida_1, 0) + COALESCE(r2.area_construida_2, 0) + COALESCE(r2.area_construida_3, 0)),
                {geom_construccion}
            FROM f_r1_r2.r2_construccion_zona r2
            WHERE r2.numero_predial = %s
              AND (COALESCE(r2.area_construida_1, 0) + COALESCE(r2.area_construida_2, 0) + COALESCE(r2.area_construida_3, 0)) > 0
            ON CONFLICT DO NOTHING;
        """
        sp_cons = f"sp_cons_{abs(hash(npn)) % 10000000}"
        try:
            cur.execute(f"SAVEPOINT {sp_cons};")
            if geom_construccion == "%s":
                cur.execute(sql_cons, (t_basket_id, id_predio, npn, geom_cons_val))
            else:
                cur.execute(sql_cons, (t_basket_id, id_predio, npn))
            cur.execute(f"RELEASE SAVEPOINT {sp_cons};")
        except Exception as cons_err:
            try:
                cur.execute(f"ROLLBACK TO SAVEPOINT {sp_cons};")
            except Exception:
                pass
            logger.warning("Geometria invalida para %s: %s. Reintentando con dummy_construccion_sql.", npn, cons_err)
            try:
                sp_dummy = f"sp_cons_dummy_{abs(hash(npn)) % 10000000}"
                cur.execute(f"SAVEPOINT {sp_dummy};")
                cur.execute(sql_cons.replace(geom_construccion, dummy_construccion_sql), (t_basket_id, id_predio, npn))
                cur.execute(f"RELEASE SAVEPOINT {sp_dummy};")
            except Exception as dummy_err:
                try:
                    cur.execute(f"ROLLBACK TO SAVEPOINT {sp_dummy};")
                except Exception:
                    pass
                logger.error("Error al insertar arb_construccion para predio %s: %s", npn, dummy_err)

        # 8. Insertar propietarios (arb_derechointeresadofuente)
        cur.execute(
            """
            SELECT nombre, tipo_documento, documento_identidad, participacion, direccion,
                   d_tipo, d_fecha_inicio_tenencia, fa_tipo, fa_numero_fuente, fa_fecha_documento_fuente, fa_ente_emisor
            FROM f_r1_r2.r1_predio_propietario
            WHERE numero_predial = %s
              AND NULLIF(BTRIM(nombre::text), '') IS NOT NULL
            """,
            (npn,),
        )
        propietarios = cur.fetchall() or []
        sql_prop = f"""
            INSERT INTO {schema_work}.arb_derechointeresadofuente (
                t_id, t_basket, predio, i_tipo_documento,
                i_primer_nombre, i_segundo_nombre,
                i_primer_apellido, i_segundo_apellido, i_razon_social,
                i_documento_identidad, d_cuota_participacion,
                ic_direccion_residencia, fa_tipo, d_tipo, d_fecha_inicio_tenencia,
                fa_numero_fuente, fa_fecha_documento_fuente, fa_ente_emisor
            )
            VALUES (
                nextval('{schema_work}.t_ili2db_seq'),
                %s, %s,
                (SELECT t_id FROM {schema_work}.arb_interesadodocumentotipo WHERE ilicode = %s LIMIT 1),
                %s, %s, %s, %s, %s, %s, %s, %s,
                COALESCE(%s, 686), COALESCE(%s, 1481), %s, %s, %s, %s
            )
            ON CONFLICT DO NOTHING;
        """
        for propietario in propietarios:
            nombre_r1 = propietario.get("nombre")
            tipo_documento_ilicode = _document_type_ilicode(propietario.get("tipo_documento"))
            es_nit = tipo_documento_ilicode == "NIT"
            nombre_partes = _split_natural_person_name(nombre_r1)
            participacion = propietario.get("participacion")
            if participacion is None or str(participacion) == "NaN":
                participacion = 0.0

            cur.execute(
                sql_prop,
                (
                    t_basket_id,
                    id_predio,
                    tipo_documento_ilicode,
                    None if es_nit else nombre_partes["primer_nombre"],
                    None if es_nit else nombre_partes["segundo_nombre"],
                    None if es_nit else nombre_partes["primer_apellido"],
                    None if es_nit else nombre_partes["segundo_apellido"],
                    _normalize_text(nombre_r1) if es_nit else None,
                    propietario.get("documento_identidad"),
                    participacion,
                    propietario.get("direccion"),
                    propietario.get("fa_tipo"),
                    propietario.get("d_tipo"),
                    propietario.get("d_fecha_inicio_tenencia"),
                    propietario.get("fa_numero_fuente"),
                    propietario.get("fa_fecha_documento_fuente"),
                    propietario.get("fa_ente_emisor"),
                ),
            )
        # 9. Insertar unidades de construcción y sus características
        cur.execute(f"SELECT t_id FROM {schema_work}.arb_construccion WHERE predio = %s ORDER BY t_id DESC LIMIT 1;", (id_predio,))
        cons_row = cur.fetchone()
        if cons_row:
            id_cons = cons_row['t_id']
            # Consultar todas las filas R2 pertenecientes a este predio (ordenadas por numero_de_orden)
            cur.execute(
                """
                SELECT id, numero_de_orden,
                       habitaciones_1, banos_1, locales_1, pisos_1, puntaje_1, area_construida_1, tipificacion_1, uso_1,
                       habitaciones_2, banos_2, locales_2, pisos_2, puntaje_2, area_construida_2, tipificacion_2, uso_2,
                       habitaciones_3, banos_3, locales_3, pisos_3, puntaje_3, area_construida_3, tipificacion_3, uso_3
                FROM f_r1_r2.r2_construccion_zona
                WHERE numero_predial = %s
                ORDER BY numero_de_orden ASC;
                """,
                (npn,),
            )
            r2_rows = cur.fetchall() or []
            u_global_idx = 0
            for r2_row in r2_rows:
                r2_id = r2_row['id']
                r2_order = r2_row['numero_de_orden']
                for b_idx in [1, 2, 3]:
                    area_val = float(r2_row.get(f'area_construida_{b_idx}') or 0.0)
                    if area_val <= 0:
                        continue
                    u_global_idx += 1
                    u_identificador = f"U_{npn[-10:]}_R{r2_order}_B{b_idx}_{u_global_idx}"
                    tipif_val = r2_row.get(f'tipificacion_{b_idx}')
                    tipo_calif = int(tipif_val) if tipif_val and int(tipif_val) > 0 else 1447
                    uso_val = r2_row.get(f'uso_{b_idx}')
                    tipo_ucons = int(uso_val) if uso_val and int(uso_val) > 0 else 1526
                    hab = int(r2_row.get(f'habitaciones_{b_idx}') or 0)
                    ban = int(r2_row.get(f'banos_{b_idx}') or 0)
                    loc = int(r2_row.get(f'locales_{b_idx}') or 0)
                    pis = int(r2_row.get(f'pisos_{b_idx}') or 0)
                    pun = int(r2_row.get(f'puntaje_{b_idx}') or 0)

                    sql_ucons = f"""
                        WITH caracteristicas_ins AS (
                            INSERT INTO {schema_work}.arb_caracteristicasunidadconstruccion (
                                t_id, t_basket, identificador, tipo_unidad_construccion, total_habitaciones, total_banios,
                                total_locales, total_plantas, cc_total_calificacion, area_construida, observaciones,
                                tipo_calificacion, id_grupo
                            )
                            VALUES (
                                nextval('{schema_work}.t_ili2db_seq'), %s,
                                %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s
                            )
                            ON CONFLICT DO NOTHING
                            RETURNING t_id, identificador
                        )
                        INSERT INTO {schema_work}.arb_unidadconstruccion (
                            t_id, t_basket, identificador, area_unidad_construccion, construccion, caracteristicasunidadconstruccion,
                            tipo_planta, planta_ubicacion, geometria
                        )
                        SELECT 
                            nextval('{schema_work}.t_ili2db_seq'), %s,
                            ci.identificador, %s, %s, ci.t_id,
                            1532, 1, {geom_construccion}
                        FROM caracteristicas_ins ci
                        ON CONFLICT DO NOTHING;
                    """
                    obs_text = f"Reg {r2_order} Bloque {b_idx} R2 - Tipificación: {tipif_val or 'S/D'}"
                    if geom_construccion == "%s":
                        cur.execute(
                            sql_ucons,
                            (
                                t_basket_id, u_identificador, tipo_ucons, hab, ban, loc, pis, pun, area_val,
                                obs_text, tipo_calif, npn,
                                t_basket_id, area_val, id_cons, geom_cons_val
                            ),
                        )
                    else:
                        cur.execute(
                            sql_ucons,
                            (
                                t_basket_id, u_identificador, tipo_ucons, hab, ban, loc, pis, pun, area_val,
                                obs_text, tipo_calif, npn,
                                t_basket_id, area_val, id_cons
                            ),
                        )

    logger.info("Importación de predio %s completada con éxito en el workspace.", npn)
    return True


def importar_predios_f_r1_r2_a_workspace(conn, tenant_id: str, npns: list[str], schema_work: str, t_basket_id: int) -> int:
    """
    Importa de forma masiva (bulk/set-based) la información de una lista de predios 
    desde las tablas del tenant (formato_f, formato_r1, formato_r2) hacia las tablas 
    del workspace (formato_f, formato_r1, formato_r2).
    """
    if not npns:
        return 0

    with conn.cursor() as cur:
        # 1. Copiar formato_f
        sql_predio = f"""
            INSERT INTO {schema_work}.formato_f (
                t_basket_id, npn, codigo_orip, matricula_inmobiliaria, numero_predial_anterior,
                tipo_predio, tipo_documento, numero_documento, primer_nombre, segundo_nombre,
                primer_apellido, segundo_apellido, razon_social, porcentaje_derecho,
                departamento, municipio, direccion, condicion_predio, area_terreno, area_construida
            )
            SELECT 
                %s, npn, codigo_orip, matricula_inmobiliaria, numero_predial_anterior,
                tipo_predio, tipo_documento, numero_documento, primer_nombre, segundo_nombre,
                primer_apellido, segundo_apellido, razon_social, porcentaje_derecho,
                departamento, municipio, direccion, condicion_predio, area_terreno, area_construida
            FROM public.formato_f
            WHERE tenant_id = %s AND npn = ANY(%s)
            ON CONFLICT (t_basket_id, npn) DO NOTHING;
        """
        cur.execute(sql_predio, (t_basket_id, tenant_id, list(npns)))
        inserted_count = cur.rowcount if cur.rowcount >= 0 else len(npns)

        # 2. Copiar formato_r1
        sql_r1 = f"""
            INSERT INTO {schema_work}.formato_r1 (
                t_basket_id, npn, numero_anotacion, fecha_anotacion, codigo_especificacion,
                especificacion, cuen, tipo_documento_publico, numero_documento_publico,
                fecha_documento_publico, oficina_origen, ciudad_oficina_origen
            )
            SELECT 
                %s, npn, numero_anotacion, fecha_anotacion, codigo_especificacion,
                especificacion, cuen, tipo_documento_publico, numero_documento_publico,
                fecha_documento_publico, oficina_origen, ciudad_oficina_origen
            FROM public.formato_r1
            WHERE tenant_id = %s AND npn = ANY(%s)
            ON CONFLICT DO NOTHING;
        """
        cur.execute(sql_r1, (t_basket_id, tenant_id, list(npns)))

        # 3. Copiar formato_r2
        sql_r2 = f"""
            INSERT INTO {schema_work}.formato_r2 (
                t_basket_id, npn, numero_anotacion, primer_nombre, segundo_nombre,
                primer_apellido, segundo_apellido, razon_social, tipo_documento,
                numero_documento, porcentaje_derecho, rol_persona
            )
            SELECT 
                %s, npn, numero_anotacion, primer_nombre, segundo_nombre,
                primer_apellido, segundo_apellido, razon_social, tipo_documento,
                numero_documento, porcentaje_derecho, rol_persona
            FROM public.formato_r2
            WHERE tenant_id = %s AND npn = ANY(%s)
            ON CONFLICT DO NOTHING;
        """
        cur.execute(sql_r2, (t_basket_id, tenant_id, list(npns)))

    return inserted_count

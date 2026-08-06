import logging
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

def importar_predio_f_r1_r2_a_workspace(conn, tenant, npn: str, schema_work: str, t_basket_id: int) -> bool:
    """
    Importa un predio desde f_r1_r2 hacia el schema de trabajo (schema_work),
    asociándolo al basket_id correspondiente al dataset del reconocedor.
    """
    logger.info("Iniciando importación alfanumérica de predio %s al workspace %s...", npn, schema_work)
    
    # Geometrías Dummy estandarizadas de respaldo (EPSG:9377)
    dummy_terreno_sql = """
        ST_GeomFromText('MULTIPOLYGON(((4746637.942 1881706.252, 4746538.701 1881681.442, 4746520.307 1881762.076, 4746610.030 1881791.271, 4746637.942 1881706.252)))', 9377)
    """
    dummy_construccion_sql = """
        ST_GeomFromText('MULTIPOLYGON(((4746533.461 1881758.974, 4746548.646 1881690.960, 4746589.926 1881701.226, 4746571.746 1881769.882, 4746533.461 1881758.974)))', 9377)
    """
    dummy_direccion_sql = """
        ST_GeomFromText('POINT(4746577.212 1881766.456)', 9377)
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 1. Asegurar longitud de columnas identificadoras y quitar NOT NULL
        for tbl in ['arb_unidadconstruccion', 'arb_caracteristicasunidadconstruccion']:
            try:
                cur.execute(f'ALTER TABLE {schema_work}.{tbl} ALTER COLUMN identificador TYPE varchar(60);')
            except Exception as e:
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
        sql_predio = f"""
            INSERT INTO {schema_work}.arb_predio (
                t_id, t_basket, id_operacion, numero_predial, numero_predial_anterior,
                area_catastral_terreno, observaciones
            )
            SELECT DISTINCT ON (r1.numero_predial)
                nextval('{schema_work}.t_ili2db_seq'),
                %s,
                r1.numero_predial,
                r1.numero_predial,
                r1.numero_predial_anterior,
                r1.area_terreno,
                CONCAT('Asignación Backend (f_r1_r2) - Dirección: ', r1.direccion, ' | Matrícula: ', COALESCE(r2.matricula, ''))
            FROM f_r1_r2.r1_predio_propietario r1
            LEFT JOIN f_r1_r2.r2_construccion_zona r2 ON r1.numero_predial = r2.numero_predial
            WHERE r1.numero_predial = %s
            ON CONFLICT DO NOTHING;
        """
        cur.execute(sql_predio, (t_basket_id, npn))

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
        if geom_construccion == "%s":
            cur.execute(sql_cons, (t_basket_id, id_predio, npn, geom_cons_val))
        else:
            cur.execute(sql_cons, (t_basket_id, id_predio, npn))

        # 8. Insertar propietarios (arb_derechointeresadofuente)
        sql_prop = f"""
            INSERT INTO {schema_work}.arb_derechointeresadofuente (
                t_id, t_basket, predio, nombre, i_documento_identidad, d_cuota_participacion, ic_direccion_residencia,
                fa_tipo
            )
            SELECT 
                nextval('{schema_work}.t_ili2db_seq'),
                %s, %s, r1.nombre, r1.documento_identidad,
                CASE WHEN r1.participacion IS NULL OR r1.participacion = 'NaN'::numeric THEN 0.0 ELSE r1.participacion END,
                r1.direccion,
                686
            FROM f_r1_r2.r1_predio_propietario r1
            WHERE r1.numero_predial = %s AND r1.nombre IS NOT NULL
            ON CONFLICT DO NOTHING;
        """
        cur.execute(sql_prop, (t_basket_id, id_predio, npn))

        # 9. Insertar unidades de construcción y sus características
        cur.execute(f"SELECT t_id FROM {schema_work}.arb_construccion WHERE predio = %s ORDER BY t_id DESC LIMIT 1;", (id_predio,))
        cons_row = cur.fetchone()
        if cons_row:
            id_cons = cons_row['t_id']
            for b_idx in [1, 2, 3]:
                sql_ucons = f"""
                    WITH caracteristicas_ins AS (
                        INSERT INTO {schema_work}.arb_caracteristicasunidadconstruccion (
                            t_id, t_basket, identificador, tipo_unidad_construccion, total_habitaciones, total_banios,
                            total_locales, total_plantas, cc_total_calificacion, area_construida, observaciones,
                            tipo_calificacion, id_grupo
                        )
                        SELECT 
                            nextval('{schema_work}.t_ili2db_seq'), %s,
                            CONCAT('U_', RIGHT(r2.numero_predial, 10), '_B{b_idx}'), 1526,
                            r2.habitaciones_{b_idx}, r2.banos_{b_idx}, r2.locales_{b_idx},
                            r2.pisos_{b_idx}, r2.puntaje_{b_idx}, r2.area_construida_{b_idx},
                            CONCAT('Bloque {b_idx} R2 - Tipificación: ', COALESCE(r2.tipificacion_{b_idx}::text, 'S/D')),
                            1447, r2.numero_predial
                        FROM f_r1_r2.r2_construccion_zona r2
                        WHERE r2.numero_predial = %s AND r2.area_construida_{b_idx} > 0
                        ON CONFLICT DO NOTHING
                        RETURNING t_id, identificador
                    )
                    INSERT INTO {schema_work}.arb_unidadconstruccion (
                        t_id, t_basket, identificador, area_unidad_construccion, construccion, caracteristicasunidadconstruccion,
                        tipo_planta, planta_ubicacion, geometria
                    )
                    SELECT 
                        nextval('{schema_work}.t_ili2db_seq'), %s,
                        ci.identificador, r2.area_construida_{b_idx}, %s, ci.t_id,
                        1532, 1, {geom_construccion}
                    FROM f_r1_r2.r2_construccion_zona r2
                    JOIN caracteristicas_ins ci ON ci.identificador = CONCAT('U_', RIGHT(r2.numero_predial, 10), '_B{b_idx}')
                    WHERE r2.numero_predial = %s AND r2.area_construida_{b_idx} > 0
                    ON CONFLICT DO NOTHING;
                """
                if geom_construccion == "%s":
                    cur.execute(sql_ucons, (t_basket_id, npn, t_basket_id, id_cons, geom_cons_val, npn))
                else:
                    cur.execute(sql_ucons, (t_basket_id, npn, t_basket_id, id_cons, npn))

    logger.info("Importación de predio %s completada con éxito en el workspace.", npn)
    return True

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
SERVICIO BACKEND DE ASIGNACIÓN PREDIAL LADM-COL
=============================================================================
Módulo principal para integrar con el Panel de Asignación del Backend.

FLUJO DE TRABAJO DE ASIGNACIÓN:
1. Entrada: Lista de Número Predial Nacional (NPN).
2. Rastreo Geo (Paso 1): Consulta el esquema 'a_base_principal' buscando 
   la geometría del terreno y construcción.
3. Rastreo Alfa (Paso 2): Si no existe en 'a_base_principal', rastrea y extrae 
   toda la información alfanumérica desde 'f_r1_r2' (R1 y R2).
4. Transferencia (Paso 3): Pobla las tablas LADM-COL en el esquema 'b_asignaciones_arb'
   (arb_predio, arb_terreno, arb_direccion, arb_avaluovalor, arb_construccion,
    arb_derechointeresadofuente, arb_unidadconstruccion, arb_caracteristicasunidadconstruccion).
5. Exportación XTF (Paso 4): Genera el archivo INTERLIS (.xtf).
=============================================================================
"""

import os
import sys
import time
import subprocess
import psycopg2

def load_config():
    env_vars = {}
    if os.path.exists('config.env'):
        with open('config.env', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env_vars[k.strip()] = v.strip()
    return env_vars

class AsignadorPredialBackend:
    def __init__(self):
        config = load_config()
        self.host = config.get('DB_HOST', 'localhost')
        self.port = config.get('DB_PORT', '5433')
        self.dbname = config.get('DB_NAME', 'neiva_catastro_registro')
        self.user = config.get('DB_USER', 'postgres')
        self.password = config.get('DB_PASSWORD', 'admin')

    def _get_connection(self):
        return psycopg2.connect(
            host=self.host, port=self.port, dbname=self.dbname, 
            user=self.user, password=self.password
        )

    def ejecutar_asignacion(self, lista_npn, exportar_xtf=False, ruta_xtf="asignacion_predial.xtf"):
        """
        Ejecuta la asignación de predios desde a_base_principal / f_r1_r2 hacia b_asignaciones_arb.
        """
        if isinstance(lista_npn, str):
            lista_npn = [lista_npn.strip()]
        
        print(f"[*] Iniciando Asignación de {len(lista_npn):,} predios para Backend...")
        conn = self._get_connection()
        conn.autocommit = False
        cur = conn.cursor()

        # Geometría Dummy EPSG:9377 de respaldo
        dummy_geom = """
            ST_Multi(ST_SetSRID(ST_MakePolygon(ST_MakeLine(ARRAY[
                ST_MakePoint(4850000, 2050000),
                ST_MakePoint(4850001, 2050000),
                ST_MakePoint(4850001, 2050001),
                ST_MakePoint(4850000, 2050001),
                ST_MakePoint(4850000, 2050000)
            ])), 9377))
        """

        # Verificar si esquema a_base_principal existe
        cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'a_base_principal';")
        has_geo_base = bool(cur.fetchone())

        for npn in lista_npn:
            # -----------------------------------------------------------------
            # 1. RASTREO GEO (a_base_principal)
            # -----------------------------------------------------------------
            geom_terreno_sql = dummy_geom
            geom_cons_sql = dummy_geom

            if has_geo_base:
                try:
                    cur.execute("SELECT t.geometria FROM a_base_principal.terreno t WHERE t.numero_predial = %s LIMIT 1;", (npn,))
                    res_g = cur.fetchone()
                    if res_g and res_g[0]:
                        geom_terreno_sql = "%s"  # Se usará la geometría real encontrada

                    cur.execute("SELECT c.geometria FROM a_base_principal.construccion c WHERE c.numero_predial = %s LIMIT 1;", (npn,))
                    res_c = cur.fetchone()
                    if res_c and res_c[0]:
                        geom_cons_sql = "%s"
                except Exception:
                    conn.rollback()

            # -----------------------------------------------------------------
            # 2. RASTREO ALFA (f_r1_r2) & TRANSFERENCIA (b_asignaciones_arb)
            # -----------------------------------------------------------------
            # A. arb_predio
            sql_predio = """
                INSERT INTO b_asignaciones_arb.arb_predio (
                    t_id, t_basket, id_operacion, numero_predial, numero_predial_anterior,
                    area_catastral_terreno, observaciones
                )
                SELECT DISTINCT ON (r1.numero_predial)
                    nextval('b_asignaciones_arb.t_ili2db_seq'),
                    1,
                    r1.numero_predial,
                    r1.numero_predial,
                    r1.numero_predial_anterior,
                    r1.area_terreno,
                    CONCAT('Asignación Backend - Dirección: ', r1.direccion, ' | Matrícula: ', COALESCE(r2.matricula, ''))
                FROM f_r1_r2.r1_predio_propietario r1
                LEFT JOIN f_r1_r2.r2_construccion_zona r2 ON r1.numero_predial = r2.numero_predial
                WHERE r1.numero_predial = %s
                ON CONFLICT (t_id) DO NOTHING;
            """
            cur.execute(sql_predio, (npn,))

            # Obtener t_id de predio
            cur.execute("SELECT t_id, area_catastral_terreno FROM b_asignaciones_arb.arb_predio WHERE numero_predial = %s ORDER BY t_id DESC LIMIT 1;", (npn,))
            pred_row = cur.fetchone()
            if not pred_row:
                print(f"  [WARN] Predio {npn} no encontrado en f_r1_r2.")
                continue

            id_predio, area_terreno = pred_row

            # B. arb_terreno
            sql_terreno = f"""
                INSERT INTO b_asignaciones_arb.arb_terreno (
                    t_id, t_basket, predio, area_terreno, etiqueta, geometria
                )
                VALUES (
                    nextval('b_asignaciones_arb.t_ili2db_seq'),
                    1, %s, %s, %s, {geom_terreno_sql}
                )
                ON CONFLICT DO NOTHING;
            """
            cur.execute(sql_terreno, (id_predio, area_terreno, f"Terreno Predio {npn}"))

            # C. arb_direccion
            sql_dir = """
                INSERT INTO b_asignaciones_arb.arb_direccion (
                    t_id, t_basket, tipo_direccion, arb_predio_direccion, nombre_predio
                )
                SELECT DISTINCT ON (r1.numero_predial)
                    nextval('b_asignaciones_arb.t_ili2db_seq'),
                    1, 1544, %s, r1.direccion
                FROM f_r1_r2.r1_predio_propietario r1
                WHERE r1.numero_predial = %s
                ON CONFLICT DO NOTHING;
            """
            cur.execute(sql_dir, (id_predio, npn))

            # D. arb_avaluovalor
            sql_av = """
                INSERT INTO b_asignaciones_arb.arb_avaluovalor (
                    t_id, t_basket, arb_predio_avaluo, avaluo_catastral, fecha_avaluo_catastral, autoestimacion
                )
                SELECT DISTINCT ON (r1.numero_predial)
                    nextval('b_asignaciones_arb.t_ili2db_seq'),
                    1, %s, r1.avaluo, COALESCE(r1.vigencia, CURRENT_DATE), false
                FROM f_r1_r2.r1_predio_propietario r1
                WHERE r1.numero_predial = %s
                ON CONFLICT DO NOTHING;
            """
            cur.execute(sql_av, (id_predio, npn))

            # E. arb_construccion
            sql_cons = f"""
                INSERT INTO b_asignaciones_arb.arb_construccion (
                    t_id, t_basket, identificador, predio, area_total_construccion, geometria
                )
                SELECT DISTINCT ON (r2.numero_predial)
                    nextval('b_asignaciones_arb.t_ili2db_seq'),
                    1, CONCAT('CONS_', r2.numero_predial), %s,
                    (COALESCE(r2.area_construida_1, 0) + COALESCE(r2.area_construida_2, 0) + COALESCE(r2.area_construida_3, 0)),
                    {geom_cons_sql}
                FROM f_r1_r2.r2_construccion_zona r2
                WHERE r2.numero_predial = %s
                  AND (COALESCE(r2.area_construida_1, 0) + COALESCE(r2.area_construida_2, 0) + COALESCE(r2.area_construida_3, 0)) > 0
                ON CONFLICT DO NOTHING;
            """
            cur.execute(sql_cons, (id_predio, npn))

            # F. Propietarios (arb_derechointeresadofuente)
            sql_prop = """
                INSERT INTO b_asignaciones_arb.arb_derechointeresadofuente (
                    t_id, t_basket, predio, nombre, i_documento_identidad, d_cuota_participacion, ic_direccion_residencia
                )
                SELECT 
                    nextval('b_asignaciones_arb.t_ili2db_seq'),
                    1, %s, r1.nombre, r1.documento_identidad,
                    CASE WHEN r1.participacion IS NULL OR r1.participacion = 'NaN'::numeric THEN 0.0 ELSE r1.participacion END,
                    r1.direccion
                FROM f_r1_r2.r1_predio_propietario r1
                WHERE r1.numero_predial = %s AND r1.nombre IS NOT NULL
                ON CONFLICT DO NOTHING;
            """
            cur.execute(sql_prop, (id_predio, npn))

            # G. Unidades de Construcción y Características (Bloques 1, 2, 3)
            cur.execute("SELECT t_id FROM b_asignaciones_arb.arb_construccion WHERE predio = %s ORDER BY t_id DESC LIMIT 1;", (id_predio,))
            cons_row = cur.fetchone()
            if cons_row:
                id_cons = cons_row[0]
                for b_idx in [1, 2, 3]:
                    sql_ucons = f"""
                        WITH caracteristicas_ins AS (
                            INSERT INTO b_asignaciones_arb.arb_caracteristicasunidadconstruccion (
                                t_id, t_basket, identificador, tipo_unidad_construccion, total_habitaciones, total_banios,
                                total_locales, total_plantas, cc_total_calificacion, area_construida, observaciones
                            )
                            SELECT 
                                nextval('b_asignaciones_arb.t_ili2db_seq'), 1,
                                CONCAT('UCONS_', r2.numero_predial, '_B{b_idx}'), 1526,
                                r2.habitaciones_{b_idx}, r2.banos_{b_idx}, r2.locales_{b_idx},
                                r2.pisos_{b_idx}, r2.puntaje_{b_idx}, r2.area_construida_{b_idx},
                                CONCAT('Bloque {b_idx} R2 - Tipificación: ', COALESCE(r2.tipificacion_{b_idx}::text, 'S/D'))
                            FROM f_r1_r2.r2_construccion_zona r2
                            WHERE r2.numero_predial = %s AND r2.area_construida_{b_idx} > 0
                            ON CONFLICT DO NOTHING
                            RETURNING t_id, identificador
                        )
                        INSERT INTO b_asignaciones_arb.arb_unidadconstruccion (
                            t_id, t_basket, identificador, area_unidad_construccion, construccion, caracteristicasunidadconstruccion
                        )
                        SELECT 
                            nextval('b_asignaciones_arb.t_ili2db_seq'), 1,
                            ci.identificador, r2.area_construida_{b_idx}, %s, ci.t_id
                        FROM f_r1_r2.r2_construccion_zona r2
                        JOIN caracteristicas_ins ci ON ci.identificador = CONCAT('UCONS_', r2.numero_predial, '_B{b_idx}')
                        WHERE r2.numero_predial = %s AND r2.area_construida_{b_idx} > 0
                        ON CONFLICT DO NOTHING;
                    """
                    cur.execute(sql_ucons, (npn, id_cons, npn))

        conn.commit()
        conn.close()
        print(f"[SUCCESS] Asignación completada exitosamente en b_asignaciones_arb.")

        # Exportación a XTF si se solicita
        if exportar_xtf:
            self.exportar_xtf(ruta_salida=ruta_xtf)

    def exportar_xtf(self, ruta_salida="asignacion_predial.xtf"):
        """
        Exporta el esquema b_asignaciones_arb al formato INTERLIS (.xtf).
        """
        print(f"[*] Generando exportación INTERLIS XTF en: {ruta_salida}...")
        cmd = [
            "java", "-jar", "ili2pg.jar",
            "--export",
            "--dbhost", self.host,
            "--dbport", self.port,
            "--dbname", self.dbname,
            "--dbusr", self.user,
            "--dbpwd", self.password,
            "--schema", "b_asignaciones_arb",
            "--models", "LADM_COL_V3_1",
            "--xtf", ruta_salida
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                print(f"[SUCCESS] Archivo XTF exportado correctamente: {ruta_salida}")
            else:
                print(f"[WARN] ili2pg export info: {res.stderr or res.stdout}")
        except Exception as e:
            print(f"[INFO] Comando ili2pg preparado. Asegúrate de tener ili2pg.jar en PATH para la exportación XTF: {e}")

if __name__ == '__main__':
    asignador = AsignadorPredialBackend()
    # Prueba con 1 predio
    asignador.ejecutar_asignacion(lista_npn=["410010001000000010017000000000"], exportar_xtf=False)

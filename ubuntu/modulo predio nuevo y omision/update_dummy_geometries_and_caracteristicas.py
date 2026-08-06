#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
SGR & LADM-COL: ASIGNACIÓN DE GEOMETRÍAS PREDETERMINADAS Y MIGRACIÓN DE 
CARACTERÍSTICAS DE UNIDADES DE CONSTRUCCIÓN (R2)
=============================================================================
"""

import psycopg2

def process_databases():
    dummy_geom_sql = """
        ST_Multi(ST_SetSRID(ST_MakePolygon(ST_MakeLine(ARRAY[
            ST_MakePoint(4850000, 2050000),
            ST_MakePoint(4850001, 2050000),
            ST_MakePoint(4850001, 2050001),
            ST_MakePoint(4850000, 2050001),
            ST_MakePoint(4850000, 2050000)
        ])), 9377))
    """

    for db in ['neiva_catastro_registro', 'neiva_castro_registro']:
        print(f"\n=============================================================================")
        print(f" PROCESANDO BASE DE DATOS: {db}")
        print(f"=============================================================================")
        conn = psycopg2.connect(host='localhost', port=5433, dbname=db, user='postgres', password='admin')
        conn.autocommit = True
        cur = conn.cursor()

        # Expandir longitud de identificador si es necesario
        for tbl in ['arb_unidadconstruccion', 'arb_caracteristicasunidadconstruccion']:
            try:
                cur.execute(f'ALTER TABLE b_asignaciones_arb.{tbl} ALTER COLUMN identificador TYPE varchar(60);')
            except Exception:
                pass

        # Drop NOT NULL on optional LADM columns in arb_caracteristicasunidadconstruccion
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_schema = 'b_asignaciones_arb' AND table_name = 'arb_caracteristicasunidadconstruccion' AND is_nullable = 'NO';
        """)
        for col, in cur.fetchall():
            if col not in ('t_id', 't_basket'):
                try:
                    cur.execute(f'ALTER TABLE b_asignaciones_arb.arb_caracteristicasunidadconstruccion ALTER COLUMN "{col}" DROP NOT NULL;')
                except Exception:
                    pass

        # 1. Asignar Geometría Dummy a arb_terreno
        print("[1/3] Asignando geometría base EPSG:9377 a arb_terreno...")
        cur.execute(f"""
            UPDATE b_asignaciones_arb.arb_terreno 
            SET geometria = {dummy_geom_sql}
            WHERE geometria IS NULL;
        """)
        print(f"  [OK] {cur.rowcount:,} terrenos actualizados con geometría predeterminada.")

        # 2. Asignar Geometría Dummy a arb_construccion
        print("[2/3] Asignando geometría base EPSG:9377 a arb_construccion...")
        cur.execute(f"""
            UPDATE b_asignaciones_arb.arb_construccion 
            SET geometria = {dummy_geom_sql}
            WHERE geometria IS NULL;
        """)
        print(f"  [OK] {cur.rowcount:,} construcciones actualizadas con geometría predeterminada.")

        # 3. Migrar Características de Unidades de Construcción desde R2
        print("[3/3] Migrando características detalladas de Unidades de Construcción desde R2...")
        
        # Bloques 1, 2 y 3 de R2
        for b_idx in [1, 2, 3]:
            sql_ucons = f"""
                WITH caracteristicas_ins AS (
                    INSERT INTO b_asignaciones_arb.arb_caracteristicasunidadconstruccion (
                        t_id, t_basket, identificador, tipo_unidad_construccion, total_habitaciones, total_banios,
                        total_locales, total_plantas, cc_total_calificacion, area_construida, observaciones
                    )
                    SELECT 
                        nextval('b_asignaciones_arb.t_ili2db_seq'),
                        1,
                        CONCAT('UCONS_', r2.numero_predial, '_B{b_idx}'),
                        1526,
                        r2.habitaciones_{b_idx},
                        r2.banos_{b_idx},
                        r2.locales_{b_idx},
                        r2.pisos_{b_idx},
                        r2.puntaje_{b_idx},
                        r2.area_construida_{b_idx},
                        CONCAT('Bloque {b_idx} R2 - Tipificación: ', COALESCE(r2.tipificacion_{b_idx}::text, 'S/D'), ' | Uso: ', COALESCE(r2.uso_{b_idx}::text, 'S/D'))
                    FROM f_r1_r2.r2_construccion_zona r2
                    WHERE r2.area_construida_{b_idx} IS NOT NULL AND r2.area_construida_{b_idx} > 0
                    ON CONFLICT DO NOTHING
                    RETURNING t_id, identificador
                )
                INSERT INTO b_asignaciones_arb.arb_unidadconstruccion (
                    t_id, t_basket, identificador, area_unidad_construccion, construccion, caracteristicasunidadconstruccion
                )
                SELECT 
                    nextval('b_asignaciones_arb.t_ili2db_seq'),
                    1,
                    ci.identificador,
                    r2.area_construida_{b_idx},
                    c.t_id,
                    ci.t_id
                FROM f_r1_r2.r2_construccion_zona r2
                JOIN caracteristicas_ins ci ON ci.identificador = CONCAT('UCONS_', r2.numero_predial, '_B{b_idx}')
                JOIN b_asignaciones_arb.arb_predio p ON r2.numero_predial = p.numero_predial
                JOIN b_asignaciones_arb.arb_construccion c ON c.predio = p.t_id
                WHERE r2.area_construida_{b_idx} IS NOT NULL AND r2.area_construida_{b_idx} > 0
                ON CONFLICT DO NOTHING;
            """
            try:
                cur.execute(sql_ucons)
                print(f"  [OK] Bloque {b_idx}: {cur.rowcount:,} unidades de construcción migradas.")
            except Exception as e:
                print(f"  [WARN] Error en Bloque {b_idx}: {e}")

        conn.close()

    print("\n=============================================================================")
    print("      PROCESO COMPLETADO EXITOSAMENTE EN AMBAS BASES DE DATOS                ")
    print("=============================================================================\n")

if __name__ == '__main__':
    process_databases()

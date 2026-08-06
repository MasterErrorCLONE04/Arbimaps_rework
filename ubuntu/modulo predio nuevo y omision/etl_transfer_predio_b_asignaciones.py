#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ETL DE TRANSFERENCIA SELECTIVA DE PREDIOS: f_r1_r2 -> b_asignaciones_arb
Base de Datos: neiva_catastro_registro
Permite migrar 1 predio (NPN), una lista de predios o todos los predios 
desde el esquema origen f_r1_r2 hacia las tablas LADM-COL en b_asignaciones_arb.
=============================================================================
"""

import sys
import os
import time
import argparse
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

def transferir_predios(predios_list=None, transfer_all=False):
    config = load_config()
    host = config.get('DB_HOST', 'localhost')
    port = config.get('DB_PORT', '5433')
    dbname = config.get('DB_NAME', 'neiva_catastro_registro')
    user = config.get('DB_USER', 'postgres')
    password = config.get('DB_PASSWORD', 'admin')

    print("=============================================================================")
    print(" ETL DE MIGRACION PREDIO A PREDIO: f_r1_r2 -> b_asignaciones_arb             ")
    print("=============================================================================")
    print(f"  Base de Datos: {dbname}")
    print(f"  Origen:        f_r1_r2")
    print(f"  Destino:       b_asignaciones_arb")

    conn = psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password)
    conn.autocommit = False
    cur = conn.cursor()

    # 1. Asegurar secuencia y basket predeterminado
    cur.execute("CREATE SEQUENCE IF NOT EXISTS b_asignaciones_arb.t_ili2db_seq START WITH 1;")
    cur.execute("INSERT INTO b_asignaciones_arb.t_ili2db_dataset (t_id, datasetname) VALUES (1, 'dataset_neiva') ON CONFLICT DO NOTHING;")
    cur.execute("INSERT INTO b_asignaciones_arb.t_ili2db_basket (t_id, dataset, topic, attachmentkey) VALUES (1, 1, 'b_asignaciones_arb', 'b_asignaciones') ON CONFLICT DO NOTHING;")
    conn.commit()

    # Si se solicitó transferir todos
    if transfer_all or not predios_list:
        cur.execute("SELECT DISTINCT numero_predial FROM f_r1_r2.r1_predio_propietario;")
        predios_list = [r[0] for r in cur.fetchall()]
        print(f"[*] Modo Carga Global: Se procesarán los {len(predios_list):,} predios de f_r1_r2.")
    else:
        print(f"[*] Modo Selección: Se procesarán {len(predios_list):,} predios especificados.")

    start_time = time.time()

    total_predios_migrados = 0
    total_terrenos = 0
    total_direcciones = 0
    total_avaluos = 0
    total_construcciones = 0

    batch_size = 5000
    for i in range(0, len(predios_list), batch_size):
        chunk_npns = predios_list[i:i+batch_size]

        # 1. Insertar arb_predio
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
                CONCAT('Migrado desde f_r1_r2 Neiva - Dirección: ', r1.direccion, ' | Matrícula: ', COALESCE(r2.matricula, ''))
            FROM f_r1_r2.r1_predio_propietario r1
            LEFT JOIN f_r1_r2.r2_construccion_zona r2 ON r1.numero_predial = r2.numero_predial
            WHERE r1.numero_predial IN %s
              AND r1.numero_predial NOT IN (SELECT numero_predial FROM b_asignaciones_arb.arb_predio WHERE numero_predial IS NOT NULL);
        """
        cur.execute(sql_predio, (tuple(chunk_npns),))
        total_predios_migrados += cur.rowcount

        # 2. Insertar arb_terreno
        sql_terreno = """
            INSERT INTO b_asignaciones_arb.arb_terreno (
                t_id, t_basket, predio, area_terreno, etiqueta
            )
            SELECT 
                nextval('b_asignaciones_arb.t_ili2db_seq'),
                1,
                p.t_id,
                p.area_catastral_terreno,
                CONCAT('Terreno Predio ', p.numero_predial)
            FROM b_asignaciones_arb.arb_predio p
            WHERE p.numero_predial IN %s
              AND p.t_id NOT IN (SELECT predio FROM b_asignaciones_arb.arb_terreno WHERE predio IS NOT NULL);
        """
        cur.execute(sql_terreno, (tuple(chunk_npns),))
        total_terrenos += cur.rowcount

        # 3. Insertar arb_direccion
        sql_direccion = """
            INSERT INTO b_asignaciones_arb.arb_direccion (
                t_id, t_basket, tipo_direccion, arb_predio_direccion, nombre_predio
            )
            SELECT DISTINCT ON (r1.numero_predial)
                nextval('b_asignaciones_arb.t_ili2db_seq'),
                1,
                1544,
                p.t_id,
                r1.direccion
            FROM f_r1_r2.r1_predio_propietario r1
            JOIN b_asignaciones_arb.arb_predio p ON r1.numero_predial = p.numero_predial
            WHERE r1.numero_predial IN %s
              AND p.t_id NOT IN (SELECT arb_predio_direccion FROM b_asignaciones_arb.arb_direccion WHERE arb_predio_direccion IS NOT NULL);
        """
        cur.execute(sql_direccion, (tuple(chunk_npns),))
        total_direcciones += cur.rowcount

        # 4. Insertar arb_avaluovalor
        sql_avaluo = """
            INSERT INTO b_asignaciones_arb.arb_avaluovalor (
                t_id, t_basket, arb_predio_avaluo, avaluo_catastral, fecha_avaluo_catastral, autoestimacion
            )
            SELECT DISTINCT ON (r1.numero_predial)
                nextval('b_asignaciones_arb.t_ili2db_seq'),
                1,
                p.t_id,
                r1.avaluo,
                COALESCE(r1.vigencia, CURRENT_DATE),
                false
            FROM f_r1_r2.r1_predio_propietario r1
            JOIN b_asignaciones_arb.arb_predio p ON r1.numero_predial = p.numero_predial
            WHERE r1.numero_predial IN %s
              AND p.t_id NOT IN (SELECT arb_predio_avaluo FROM b_asignaciones_arb.arb_avaluovalor WHERE arb_predio_avaluo IS NOT NULL);
        """
        cur.execute(sql_avaluo, (tuple(chunk_npns),))
        total_avaluos += cur.rowcount

        # 5. Insertar arb_construccion
        sql_construccion = """
            INSERT INTO b_asignaciones_arb.arb_construccion (
                t_id, t_basket, identificador, predio, area_total_construccion
            )
            SELECT DISTINCT ON (r2.numero_predial)
                nextval('b_asignaciones_arb.t_ili2db_seq'),
                1,
                CONCAT('CONS_', r2.numero_predial),
                p.t_id,
                (COALESCE(r2.area_construida_1, 0) + COALESCE(r2.area_construida_2, 0) + COALESCE(r2.area_construida_3, 0))
            FROM f_r1_r2.r2_construccion_zona r2
            JOIN b_asignaciones_arb.arb_predio p ON r2.numero_predial = p.numero_predial
            WHERE r2.numero_predial IN %s
              AND (COALESCE(r2.area_construida_1, 0) + COALESCE(r2.area_construida_2, 0) + COALESCE(r2.area_construida_3, 0)) > 0
              AND p.t_id NOT IN (SELECT predio FROM b_asignaciones_arb.arb_construccion WHERE predio IS NOT NULL);
        """
        cur.execute(sql_construccion, (tuple(chunk_npns),))
        total_construcciones += cur.rowcount

        conn.commit()
        print(f"  - Avance: {min(i+batch_size, len(predios_list)):,}/{len(predios_list):,} predios procesados...")

    elapsed = time.time() - start_time
    print(f"\n=============================================================================")
    print(f"       TRANSFERENCIA SELECTIVA COMPLETADA A b_asignaciones_arb               ")
    print(f"=============================================================================")
    print(f"  - Total Predios Migrados (arb_predio):        {total_predios_migrados:,}")
    print(f"  - Terrenos Generados (arb_terreno):           {total_terrenos:,}")
    print(f"  - Direcciones Generadas (arb_direccion):       {total_direcciones:,}")
    print(f"  - Avalúos Registrados (arb_avaluovalor):       {total_avaluos:,}")
    print(f"  - Construcciones Generadas (arb_construccion): {total_construcciones:,}")
    print(f"  - Tiempo Transcurrido:                        {elapsed:.2f} segundos")
    print(f"=============================================================================\n")

    conn.close()

def main():
    parser = argparse.ArgumentParser(description="ETL de Transferencia de Predios desde f_r1_r2 hacia b_asignaciones_arb")
    parser.add_argument('--npn', '--numero-predial', help="Número Predial Nacional (NPN) individual a transferir")
    parser.add_argument('--file', help="Archivo de texto con lista de NPNs a transferir")
    parser.add_argument('--all', action='store_true', help="Transferir TODOS los predios de f_r1_r2")

    args = parser.parse_args()

    npn_target = getattr(args, 'npn', None) or getattr(args, 'numero_predial', None)

    if npn_target:
        transferir_predios(predios_list=[npn_target.strip()])
    elif args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            npns = [line.strip() for line in f if line.strip()]
        transferir_predios(predios_list=npns)
    else:
        transferir_predios(transfer_all=args.all)

if __name__ == '__main__':
    main()

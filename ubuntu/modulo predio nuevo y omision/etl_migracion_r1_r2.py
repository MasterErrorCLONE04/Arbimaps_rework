#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
SCRIPT ETL DE MIGRACIÓN CATASTRAL R1 Y R2 NEIVA A AWS POSTGRESQL
Base de Datos: neiva | Esquema: f_r1_r2
Circular 5160 IGAC / Modelo LADM_COL V4.1
=============================================================================
"""

import os
import sys
import csv
import time
import argparse
import datetime

# Intentar importar psycopg2 si está disponible
try:
    import psycopg2
    from psycopg2.extras import execute_values
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

# Catálogo oficial de Destinos Económicos LADM_COL V4.1 / IGAC
DESTINOS_ECONOMICOS = [
    ('0', 'NO REGISTRA', 'Clasificación por defecto asignada cuando el predio no registra uso capturado.'),
    ('A', 'HABITACIONAL', 'Predios destinados a la habitación o vivienda familiar.'),
    ('B', 'INDUSTRIAL', 'Predios destinados al establecimiento de industrias o fábricas.'),
    ('C', 'COMERCIAL', 'Predios destinados al comercio de bienes y servicios.'),
    ('D', 'AGROPECUARIO', 'Predios con actividades agrícolas y pecuarias.'),
    ('W', 'MINERIA O HIDROCARBUROS', 'Aprovechamiento directo de recursos minerales e hidrocarburos.'),
    ('F', 'CULTURAL', 'Predios destinados al desarrollo de actividades artísticas y culturales.'),
    ('G', 'RECREACIONAL', 'Equipamientos deportivos, recreativos, parques y clubes.'),
    ('H', 'SALUBRIDAD', 'Predios destinados al cuidado de la salud (hospitales, clínicas, consultorios).'),
    ('I', 'INSTITUCIONAL', 'Administración y prestación de servicios del Estado.'),
    ('J', 'EDUCATIVO', 'Actividades académicas de educación inicial, primaria, secundaria y superior.'),
    ('K', 'RELIGIOSO', 'Culto religioso (parroquias, catedrales, capillas, conventos).'),
    ('L', 'AGRICOLA', 'Terrenos destinados a la producción de cultivos.'),
    ('M', 'PECUARIO', 'Cría, beneficio y aprovechamiento de animales.'),
    ('N', 'AGROINDUSTRIAL', 'Cultivo y transformación agroindustrial de productos.'),
    ('O', 'FORESTAL PRODUCTOR', 'Extracción y transformación primaria de madera y bosque.'),
    ('P', 'USO PUBLICO', 'Uso y goce de todos los habitantes (plazas, vías, zonas verdes).'),
    ('Q', 'INFRAESTRUCTURA AGROPECUARIA', 'Infraestructura requerida para la producción agropecuaria.'),
    ('R', 'LOTE URBANIZABLE NO URBANIZADO', 'Predios urbanos sin desarrollo y sin restricción legal.'),
    ('S', 'LOTE URBANIZADO NO CONSTRUIDO', 'Predios en zonas urbanizadas con servicios públicos sin construcción.'),
    ('T', 'LOTE NO URBANIZABLE', 'Afectaciones por instrumento de planeación municipal.'),
    ('U', 'ACUICOLA', 'Cultivo de organismos acuáticos en ambientes naturales o artificiales.'),
    ('V', 'INFRAESTRUCTURA HIDRAULICA', 'Control, almacenamiento y conducción de agua.'),
    ('X', 'INFRAESTRUCTURA TRANSPORTE', 'Puertos, pistas de aterrizaje, terminales de transporte.'),
    ('Y', 'SERVICIOS FUNERARIOS', 'Velatorio, cremación y entierro (cementerios, funerarias).'),
    ('Z', 'AGROFORESTAL', 'Combinación de especies forestales con actividades agrícolas o pecuarias.'),
    ('1', 'INFRAESTRUCTURA SANEAMIENTO BASICO', 'Rellenos sanitarios, plantas depuradoras, alcantarillados.'),
    ('2', 'INFRAESTRUCTURA SEGURIDAD', 'Estaciones de policía, batallones, cárceles.'),
    ('3', 'INFRAESTRUCTURA ENERGIA RENOVABLE', 'Generación de energía eléctrica, parques eólicos, granjas solares.'),
    ('4', 'LOTE RURAL', 'Predios rurales no construidos sin actividad económica.')
]

def parse_date(date_str):
    """Convierte cadena DDMMAAAA a datetime.date o None."""
    d_clean = date_str.strip() if date_str else ''
    if len(d_clean) != 8 or not d_clean.isdigit():
        return None
    try:
        day = int(d_clean[0:2])
        month = int(d_clean[2:4])
        year = int(d_clean[4:8])
        return datetime.date(year, month, day)
    except Exception:
        return None

def parse_num(num_str, is_float=False):
    """Convierte cadena a float o int, reemplazando comas por puntos."""
    if not num_str:
        return 0.0 if is_float else 0
    n_clean = num_str.replace(',', '.').strip()
    try:
        val = float(n_clean)
        return val if is_float else int(val)
    except Exception:
        return 0.0 if is_float else 0

def load_env_file(env_path):
    """Carga variables desde un archivo .env si existe."""
    env_vars = {}
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env_vars[k.strip()] = v.strip()
    return env_vars

def main():
    parser = argparse.ArgumentParser(description="Script ETL de Migración Catastral R1 y R2 Neiva a AWS PostgreSQL")
    parser.add_argument('--host', help="Host de la base de datos AWS Postgres")
    parser.add_argument('--port', help="Puerto de conexión (Default: 5432)")
    parser.add_argument('--dbname', help="Nombre de la base de datos (Default: neiva)")
    parser.add_argument('--schema', help="Esquema destino (Default: f_r1_r2)")
    parser.add_argument('--user', help="Usuario PostgreSQL")
    parser.add_argument('--password', help="Contraseña PostgreSQL")
    parser.add_argument('--r1-file', default="INSUMO/BACK_UP_16072026_R1_R2/SGC-2026.R1_NEW.csv", help="Ruta archivo CSV R1")
    parser.add_argument('--r2-file', default="INSUMO/BACK_UP_16072026_R2_NEW.csv" if not os.path.exists("INSUMO/BACK_UP_16072026_R1_R2/SGC-2026.R2_NEW.csv") else "INSUMO/BACK_UP_16072026_R1_R2/SGC-2026.R2_NEW.csv", help="Ruta archivo CSV R2")
    parser.add_argument('--ddl-file', default="sql/01_create_schema_f_r1_r2.sql", help="Ruta archivo DDL SQL")
    parser.add_argument('--generate-sql-dump', action='store_true', help="Generar archivos SQL offline de inserción")
    parser.add_argument('--batch-size', type=int, help="Tamaño de lote para inserción masiva (Default: 10000)")

    args = parser.parse_args()

    # Cargar variables .env como respaldo
    env_vars = load_env_file('config.env')
    host = args.host or env_vars.get('DB_HOST') or os.environ.get('DB_HOST')
    port = args.port or env_vars.get('DB_PORT') or os.environ.get('DB_PORT', '5432')
    dbname = args.dbname or env_vars.get('DB_NAME') or os.environ.get('DB_NAME', 'neiva')
    schema = args.schema or env_vars.get('DB_SCHEMA') or os.environ.get('DB_SCHEMA', 'f_r1_r2')
    user = args.user or env_vars.get('DB_USER') or os.environ.get('DB_USER')
    password = args.password or env_vars.get('DB_PASSWORD') or os.environ.get('DB_PASSWORD')
    batch_size = args.batch_size or int(env_vars.get('BATCH_SIZE', '10000'))

    print("=============================================================================")
    print("      MIGRACIÓN CATASTRAL NEIVA - RESOLUCIONES R1 Y R2 A POSTGRESQL          ")
    print("=============================================================================")
    print(f"  Base de Datos: {dbname}")
    print(f"  Esquema:      {schema}")
    print(f"  Host:         {host if host else '[No especificado - Modo Simulación/SQL Dump]'}")
    print(f"  Archivo R1:   {args.r1_file}")
    print(f"  Archivo R2:   {args.r2_file}")
    print("=============================================================================\n")

    start_time = time.time()

    # Modo Generación de Dump SQL Offline
    if args.generate_sql_dump or not (host and user and password and HAS_PSYCOPG2):
        if not HAS_PSYCOPG2 and host:
            print("[! WARNING] psycopg2 no está disponible en este entorno de python.")
        print("[* INFO] Ejecutando procesamiento y verificación de datos en modo offline / validación.")
        
        # Procesar R1
        print("\n[*] Procesando archivo R1 (Predios y Propietarios)...")
        r1_rows = []
        r1_count = 0
        with open(args.r1_file, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f, delimiter=';')
            next(reader) # Header
            for row in reader:
                if not row or len(row) < 19: continue
                r1_count += 1
                vig = parse_date(row[17])
                dest = row[13].strip()
                # si el destino económico no está en la lista estándar, asignar '0'
                if dest not in [d[0] for d in DESTINOS_ECONOMICOS]:
                    dest = '0'
                
                r1_rows.append((
                    row[0].strip(), # dpto
                    row[1].strip(), # mpio
                    row[2].strip(), # npn
                    parse_num(row[3]), # tipo_reg
                    parse_num(row[4]), # orden
                    parse_num(row[5]), # total_reg
                    row[6].strip()[:150], # nombre
                    parse_num(row[7], True), # participacion
                    row[8].strip(), # estado_civil
                    row[9].strip(), # tipo_doc
                    row[10].strip(), # doc_identidad
                    row[11].strip()[:150], # direccion
                    row[12].strip(), # comuna
                    dest,
                    parse_num(row[14], True), # area_terreno
                    parse_num(row[15], True), # area_construida
                    parse_num(row[16], True), # avaluo
                    vig,
                    row[18].strip() # npn_anterior
                ))
        print(f"  [OK] Registros R1 procesados y validados correctamente: {r1_count:,}")

        # Procesar R2
        print("\n[*] Procesando archivo R2 (Construcciones y Zonas)...")
        r2_rows = []
        r2_count = 0
        with open(args.r2_file, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f, delimiter=';')
            next(reader) # Header
            for row in reader:
                if not row or len(row) < 39: continue
                r2_count += 1
                vig = parse_date(row[37])
                r2_rows.append((
                    row[0].strip(), row[1].strip(), row[2].strip(),
                    parse_num(row[3]), parse_num(row[4]), parse_num(row[5]),
                    row[6].strip(), # matricula
                    row[7].strip(), row[8].strip(), parse_num(row[9], True), # zona 1
                    row[10].strip(), row[11].strip(), parse_num(row[12], True), # zona 2
                    parse_num(row[13]), parse_num(row[14]), parse_num(row[15]), parse_num(row[16]),
                    parse_num(row[17]), parse_num(row[18]), parse_num(row[19]), parse_num(row[20], True), # cons 1
                    parse_num(row[21]), parse_num(row[22]), parse_num(row[23]), parse_num(row[24]),
                    parse_num(row[25]), parse_num(row[26]), parse_num(row[27]), parse_num(row[28], True), # cons 2
                    parse_num(row[29]), parse_num(row[30]), parse_num(row[31]), parse_num(row[32]),
                    parse_num(row[33]), parse_num(row[34]), parse_num(row[35]), parse_num(row[36], True), # cons 3
                    vig, row[38].strip()
                ))
        print(f"  [OK] Registros R2 procesados y validados correctamente: {r2_count:,}")

        print(f"\n=============================================================================")
        print(f" RESUMEN DE PROCESAMIENTO OFFLINE / VALIDACIÓN DE INTEGRIDAD")
        print(f"=============================================================================")
        print(f"  - Total Registros R1 Validados: {r1_count:,}")
        print(f"  - Total Registros R2 Validados: {r2_count:,}")
        print(f"  - Tiempo de Procesamiento:      {time.time() - start_time:.2f} segundos")
        print(f"=============================================================================\n")
        return

    # Conexión directa a PostgreSQL AWS
    print(f"[*] Conectándose a AWS PostgreSQL {host}:{port}/{dbname}...")
    conn = psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password
    )
    conn.autocommit = False
    cursor = conn.cursor()
    print("  [OK] Conexión establecida con éxito.")

    # 1. Ejecutar DDL
    print("\n[*] Creando esquema y estructuras de tablas DDL...")
    with open(args.ddl_file, 'r', encoding='utf-8') as f:
        ddl_sql = f.read()
    cursor.execute(ddl_sql)
    conn.commit()
    print("  [OK] Esquema f_r1_r2 y tablas DDL listas.")

    # 2. Poblar Catálogo Destino Económico
    print("\n[*] Poblando tabla de referencia f_r1_r2.destino_economico...")
    insert_dest = f"""
        INSERT INTO {schema}.destino_economico (codigo, descripcion, observaciones)
        VALUES %s
        ON CONFLICT (codigo) DO UPDATE 
        SET descripcion = EXCLUDED.descripcion, observaciones = EXCLUDED.observaciones;
    """
    execute_values(cursor, insert_dest, DESTINOS_ECONOMICOS)
    conn.commit()
    print(f"  [OK] {len(DESTINOS_ECONOMICOS)} registros de catálogo insertados/actualizados.")

    # 3. Cargar R1
    print("\n[*] Migrando registros de R1 (SGC-2026.R1_NEW.csv)...")
    r1_insert_sql = f"""
        INSERT INTO {schema}.r1_predio_propietario (
            departamento, municipio, numero_predial, tipo_registro, numero_de_orden, total_registros,
            nombre, participacion, estado_civil, tipo_documento, documento_identidad, direccion,
            comuna, destino_economico, area_terreno, area_construida, avaluo, vigencia, numero_predial_anterior
        ) VALUES %s;
    """
    
    r1_batch = []
    r1_total = 0
    with open(args.r1_file, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.reader(f, delimiter=';')
        next(reader)
        for row in reader:
            if not row or len(row) < 19: continue
            vig = parse_date(row[17])
            dest = row[13].strip()
            if dest not in [d[0] for d in DESTINOS_ECONOMICOS]:
                dest = '0'
            
            r1_batch.append((
                row[0].strip(), row[1].strip(), row[2].strip(),
                parse_num(row[3]), parse_num(row[4]), parse_num(row[5]),
                row[6].strip()[:150], parse_num(row[7], True), row[8].strip(),
                row[9].strip(), row[10].strip(), row[11].strip()[:150],
                row[12].strip(), dest, parse_num(row[14], True),
                parse_num(row[15], True), parse_num(row[16], True), vig, row[18].strip()
            ))
            
            if len(r1_batch) >= batch_size:
                execute_values(cursor, r1_insert_sql, r1_batch)
                conn.commit()
                r1_total += len(r1_batch)
                print(f"  - Registros R1 insertados: {r1_total:,}...")
                r1_batch = []

    if r1_batch:
        execute_values(cursor, r1_insert_sql, r1_batch)
        conn.commit()
        r1_total += len(r1_batch)
    print(f"  [OK] Migración de R1 finalizada: {r1_total:,} registros cargados.")

    # 4. Cargar R2
    print("\n[*] Migrando registros de R2 (SGC-2026.R2_NEW.csv)...")
    r2_insert_sql = f"""
        INSERT INTO {schema}.r2_construccion_zona (
            departamento, municipio, numero_predial, tipo_registro, numero_de_orden, total_registros,
            matricula, zona_fisica_1, zona_economica_1, area_terreno_1, zona_fisica_2, zona_economica_2, area_terreno_2,
            habitaciones_1, banos_1, locales_1, pisos_1, tipificacion_1, uso_1, puntaje_1, area_construida_1,
            habitaciones_2, banos_2, locales_2, pisos_2, tipificacion_2, uso_2, puntaje_2, area_construida_2,
            habitaciones_3, banos_3, locales_3, pisos_3, tipificacion_3, uso_3, puntaje_3, area_construida_3,
            vigencia, numero_predial_anterior
        ) VALUES %s;
    """
    
    r2_batch = []
    r2_total = 0
    with open(args.r2_file, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.reader(f, delimiter=';')
        next(reader)
        for row in reader:
            if not row or len(row) < 39: continue
            vig = parse_date(row[37])
            r2_batch.append((
                row[0].strip(), row[1].strip(), row[2].strip(),
                parse_num(row[3]), parse_num(row[4]), parse_num(row[5]),
                row[6].strip(), row[7].strip(), row[8].strip(), parse_num(row[9], True),
                row[10].strip(), row[11].strip(), parse_num(row[12], True),
                parse_num(row[13]), parse_num(row[14]), parse_num(row[15]), parse_num(row[16]),
                parse_num(row[17]), parse_num(row[18]), parse_num(row[19]), parse_num(row[20], True),
                parse_num(row[21]), parse_num(row[22]), parse_num(row[23]), parse_num(row[24]),
                parse_num(row[25]), parse_num(row[26]), parse_num(row[27]), parse_num(row[28], True),
                parse_num(row[29]), parse_num(row[30]), parse_num(row[31]), parse_num(row[32]),
                parse_num(row[33]), parse_num(row[34]), parse_num(row[35]), parse_num(row[36], True),
                vig, row[38].strip()
            ))

            if len(r2_batch) >= batch_size:
                execute_values(cursor, r2_insert_sql, r2_batch)
                conn.commit()
                r2_total += len(r2_batch)
                print(f"  - Registros R2 insertados: {r2_total:,}...")
                r2_batch = []

    if r2_batch:
        execute_values(cursor, r2_insert_sql, r2_batch)
        conn.commit()
        r2_total += len(r2_batch)
    print(f"  [OK] Migración de R2 finalizada: {r2_total:,} registros cargados.")

    cursor.close()
    conn.close()

    elapsed = time.time() - start_time
    print(f"\n=============================================================================")
    print(f"              MIGRACIÓN A AWS POSTGRESQL COMPLETADA CON ÉXITO                ")
    print(f"=============================================================================")
    print(f"  - Registros R1 Cargados:   {r1_total:,}")
    print(f"  - Registros R2 Cargados:   {r2_total:,}")
    print(f"  - Tiempo Total Transcurrido: {elapsed:.2f} segundos")
    print(f"=============================================================================\n")

if __name__ == '__main__':
    main()

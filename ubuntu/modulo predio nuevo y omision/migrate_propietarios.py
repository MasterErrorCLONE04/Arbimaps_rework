import psycopg2

def migrate_propietarios():
    for db in ['neiva_catastro_registro', 'neiva_castro_registro']:
        conn = psycopg2.connect(host='localhost', port=5433, dbname=db, user='postgres', password='admin')
        conn.autocommit = True
        cur = conn.cursor()

        # Drop NOT NULL on optional LADM columns in arb_derechointeresadofuente
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_schema = 'b_asignaciones_arb' AND table_name = 'arb_derechointeresadofuente' AND is_nullable = 'NO';
        """)
        for col, in cur.fetchall():
            if col not in ('t_id', 't_basket'):
                try:
                    cur.execute(f'ALTER TABLE b_asignaciones_arb.arb_derechointeresadofuente ALTER COLUMN "{col}" DROP NOT NULL;')
                except Exception:
                    pass

        # Drop check constraints on d_cuota_participacion if any
        try:
            cur.execute('ALTER TABLE b_asignaciones_arb.arb_derechointeresadofuente DROP CONSTRAINT IF EXISTS arb_derechointeresadofnte_d_cuota_participacion_check;')
        except Exception:
            pass

        # Insert Propietarios handling NaN/NULL in participacion
        sql_prop = """
            INSERT INTO b_asignaciones_arb.arb_derechointeresadofuente (
                t_id, t_basket, predio, nombre, i_documento_identidad, d_cuota_participacion, ic_direccion_residencia
            )
            SELECT 
                nextval('b_asignaciones_arb.t_ili2db_seq'),
                1,
                p.t_id,
                r1.nombre,
                r1.documento_identidad,
                CASE WHEN r1.participacion IS NULL OR r1.participacion = 'NaN'::numeric THEN 0.0 ELSE r1.participacion END,
                r1.direccion
            FROM f_r1_r2.r1_predio_propietario r1
            JOIN b_asignaciones_arb.arb_predio p ON r1.numero_predial = p.numero_predial
            WHERE r1.nombre IS NOT NULL
            ON CONFLICT DO NOTHING;
        """
        cur.execute(sql_prop)
        cnt = cur.rowcount
        print(f"[{db}] Total Propietarios migrados a arb_derechointeresadofuente: {cnt:,}")

        conn.close()

if __name__ == '__main__':
    migrate_propietarios()

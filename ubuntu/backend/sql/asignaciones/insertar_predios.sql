-- Runtime contract:
-- _cfg must already exist before this body runs, with:
--   dataset_name text
--   npn_list     text[]


-- 1) Semilla predios origen
DROP TABLE IF EXISTS _seed_predios;
CREATE TEMP TABLE _seed_predios AS
SELECT p.t_id, p.numero_predial_nacional, p.t_basket
FROM leiva.ilc_predio p
JOIN unnest((SELECT npn_list FROM _cfg)) AS x(npn)
  ON x.npn = p.numero_predial_nacional;
-- validar semilla
SELECT count(*) AS seed_predios FROM _seed_predios;

-- 2) Dataset destino (crear/limpiar)
DROP TABLE IF EXISTS _ds;
CREATE TEMP TABLE _ds(dataset_id bigint);

WITH ex AS (
  SELECT t_id AS dataset_id
  FROM b_asignaciones.t_ili2db_dataset
  WHERE datasetname=(SELECT dataset_name FROM _cfg)
  LIMIT 1
),
ins AS (
  INSERT INTO b_asignaciones.t_ili2db_dataset(t_id,datasetname)
  SELECT COALESCE((SELECT max(t_id) FROM b_asignaciones.t_ili2db_dataset),0)+1,
         (SELECT dataset_name FROM _cfg)
  WHERE NOT EXISTS (SELECT 1 FROM ex)
  RETURNING t_id AS dataset_id
)
INSERT INTO _ds(dataset_id)
SELECT dataset_id FROM ex
UNION ALL
SELECT dataset_id FROM ins;

-- limpiar dataset destino existente
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT table_name
    FROM information_schema.columns
    WHERE table_schema='b_asignaciones'
      AND column_name='t_basket'
    GROUP BY table_name
  LOOP
    EXECUTE format(
      'DELETE FROM b_asignaciones.%I
       WHERE t_basket IN (
         SELECT t_id FROM b_asignaciones.t_ili2db_basket
         WHERE dataset = %s
       )',
      r.table_name, (SELECT dataset_id FROM _ds)
    );
  END LOOP;

  DELETE FROM b_asignaciones.t_ili2db_basket
  WHERE dataset = (SELECT dataset_id FROM _ds);
END $$;

-- 3) Grafo relacionado (controlado)
DROP TABLE IF EXISTS _fk;
DROP TABLE IF EXISTS _sel;
DROP TABLE IF EXISTS _frontier;
DROP TABLE IF EXISTS _next;
DROP TABLE IF EXISTS _new;

CREATE TEMP TABLE _fk AS
SELECT
  tc.table_name   AS child_table,
  kcu.column_name AS child_fk_col,
  ccu.table_name  AS parent_table
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
 AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu
  ON ccu.constraint_name = tc.constraint_name
 AND ccu.table_schema = tc.table_schema
WHERE tc.constraint_type='FOREIGN KEY'
  AND tc.table_schema='leiva'
  AND ccu.table_schema='leiva'
  AND ccu.column_name='t_id'
  AND tc.table_name NOT LIKE 't_ili2db_%'
  AND ccu.table_name NOT LIKE 't_ili2db_%'
  AND EXISTS (
    SELECT 1 FROM information_schema.columns c
    WHERE c.table_schema='leiva' AND c.table_name=tc.table_name AND c.column_name='t_id'
  )
  AND EXISTS (
    SELECT 1 FROM information_schema.columns c
    WHERE c.table_schema='leiva' AND c.table_name=ccu.table_name AND c.column_name='t_id'
  );

CREATE TEMP TABLE _sel(
  table_name text,
  id bigint,
  PRIMARY KEY(table_name,id)
);

CREATE TEMP TABLE _frontier(
  table_name text,
  id bigint,
  PRIMARY KEY(table_name,id)
);

CREATE TEMP TABLE _next(
  table_name text,
  id bigint,
  PRIMARY KEY(table_name,id)
);

CREATE TEMP TABLE _new(
  table_name text,
  id bigint,
  PRIMARY KEY(table_name,id)
);

INSERT INTO _sel(table_name,id)
SELECT 'ilc_predio', t_id
FROM _seed_predios
ON CONFLICT DO NOTHING;

INSERT INTO _frontier(table_name,id)
SELECT 'ilc_predio', t_id
FROM _seed_predios
ON CONFLICT DO NOTHING;

DO $$
DECLARE
  r record;
  v_added int;
  v_iter int := 0;
BEGIN
  LOOP
    v_iter := v_iter + 1;
    TRUNCATE TABLE _next;

    FOR r IN SELECT * FROM _fk LOOP
      -- Downward completo: incluir todas las tablas hijas relacionadas
      -- con los objetos del frontier. Se mantiene la exclusión de ilc_predio
      -- para no incorporar predios fuera de la semilla solicitada.
      IF r.child_table <> 'ilc_predio' THEN
        EXECUTE format(
          'INSERT INTO _next(table_name,id)
           SELECT %L, c.t_id
           FROM leiva.%I c
           JOIN _frontier f
             ON f.table_name=%L
            AND c.%I=f.id
           ON CONFLICT DO NOTHING',
          r.child_table, r.child_table, r.parent_table, r.child_fk_col
        );
      END IF;

      -- Upward: traer padres, excepto ilc_predio para no sumar predios fuera de semilla.
      IF r.parent_table <> 'ilc_predio' THEN
        EXECUTE format(
          'INSERT INTO _next(table_name,id)
           SELECT %L, p.t_id
           FROM leiva.%I c
           JOIN _frontier f
             ON f.table_name=%L
            AND c.t_id=f.id
           JOIN leiva.%I p
             ON p.t_id=c.%I
           WHERE c.%I IS NOT NULL
           ON CONFLICT DO NOTHING',
          r.parent_table, r.child_table, r.child_table, r.parent_table, r.child_fk_col, r.child_fk_col
        );
      END IF;
    END LOOP;

    TRUNCATE TABLE _new;
    INSERT INTO _new(table_name,id)
    SELECT n.table_name, n.id
    FROM _next n
    LEFT JOIN _sel s
      ON s.table_name=n.table_name AND s.id=n.id
    WHERE s.id IS NULL
    ON CONFLICT DO NOTHING;

    GET DIAGNOSTICS v_added = ROW_COUNT;

    INSERT INTO _sel(table_name,id)
    SELECT table_name,id FROM _new
    ON CONFLICT DO NOTHING;

    TRUNCATE TABLE _frontier;
    INSERT INTO _frontier(table_name,id)
    SELECT table_name,id FROM _new
    ON CONFLICT DO NOTHING;

    EXIT WHEN v_added = 0 OR v_iter >= 25;
  END LOOP;
END $$;

-- Excluir ILC informalidad del workspace de asignaciones:
-- evita arrastrar predios no asignados por relaciones formal/informal.
DELETE FROM _sel
WHERE table_name='ilc_predio_informalidad';

-- Mantener solo predios sembrados en la asignacion.
DELETE FROM _sel
WHERE table_name='ilc_predio'
  AND id NOT IN (SELECT t_id FROM _seed_predios);

-- Refuerzo BAUnit-RRR: garantizar derechos de los predios semilla.
INSERT INTO _sel(table_name,id)
SELECT 'ilc_derecho', d.t_id
FROM leiva.ilc_derecho d
JOIN _seed_predios sp ON sp.t_id = d.unidad
ON CONFLICT DO NOTHING;

-- Si el esquema tiene tabla física para col_baunitRrr, incluirla también.
DO $$
DECLARE
  v_tbl text;
BEGIN
  SELECT t.table_name
  INTO v_tbl
  FROM information_schema.tables t
  WHERE t.table_schema='leiva'
    AND lower(t.table_name) LIKE 'col_baunit%rrr%'
    AND EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema='leiva' AND c.table_name=t.table_name AND c.column_name='t_id'
    )
    AND EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema='leiva' AND c.table_name=t.table_name AND c.column_name='unidad'
    )
    AND EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema='leiva' AND c.table_name=t.table_name AND c.column_name='rrr'
    )
  ORDER BY t.table_name
  LIMIT 1;

  IF v_tbl IS NOT NULL THEN
    EXECUTE format(
      'INSERT INTO _sel(table_name,id)
       SELECT %L, b.t_id
       FROM leiva.%I b
       JOIN _seed_predios sp ON sp.t_id=b.unidad
       ON CONFLICT DO NOTHING',
      v_tbl, v_tbl
    );

    EXECUTE format(
      'INSERT INTO _sel(table_name,id)
       SELECT ''ilc_derecho'', d.t_id
       FROM leiva.ilc_derecho d
       JOIN leiva.%I b ON b.rrr=d.t_id
       JOIN _seed_predios sp ON sp.t_id=b.unidad
       ON CONFLICT DO NOTHING',
      v_tbl
    );
  END IF;
END $$;

-- Cierre ascendente de FKs para nodos agregados fuera del grafo inicial
-- (p.ej. ilc_derecho sembrado por BAUnit-RRR).
DO $$
DECLARE
  r record;
  v_added int := 1;
  v_step int := 0;
BEGIN
  WHILE v_added > 0 LOOP
    v_added := 0;
    FOR r IN SELECT child_table, child_fk_col, parent_table FROM _fk LOOP
      EXECUTE format(
        'INSERT INTO _sel(table_name,id)
         SELECT %L, c.%I
         FROM leiva.%I c
         JOIN _sel s ON s.table_name=%L AND s.id=c.t_id
         WHERE c.%I IS NOT NULL
         ON CONFLICT DO NOTHING',
        r.parent_table, r.child_fk_col, r.child_table, r.child_table, r.child_fk_col
      );
      GET DIAGNOSTICS v_step = ROW_COUNT;
      v_added := v_added + COALESCE(v_step,0);
    END LOOP;
  END LOOP;
END $$;

-- Refuerzo cadena de construccion/CUC desde predios seleccionados:
-- ilc_predio -> col_uebaunit -> cr_unidadconstruccion
-- -> ilc_caracteristicasunidadconstruccion -> cuc_calificacion_unidadconstruccion
DO $$
DECLARE
  v_fk_predio text;
  v_fk_uc text;
BEGIN
  SELECT
    MAX(CASE WHEN parent_table='ilc_predio' THEN child_fk_col END),
    MAX(CASE WHEN parent_table='cr_unidadconstruccion' THEN child_fk_col END)
  INTO v_fk_predio, v_fk_uc
  FROM _fk
  WHERE child_table='col_uebaunit';

  IF v_fk_predio IS NOT NULL THEN
    EXECUTE format(
      'INSERT INTO _sel(table_name,id)
       SELECT ''col_uebaunit'', u.t_id
       FROM leiva.col_uebaunit u
       JOIN _sel p ON p.table_name=''ilc_predio'' AND p.id=u.%1$I
       ON CONFLICT DO NOTHING',
      v_fk_predio
    );
  END IF;

  IF v_fk_uc IS NOT NULL THEN
    EXECUTE format(
      'INSERT INTO _sel(table_name,id)
       SELECT ''cr_unidadconstruccion'', u.%1$I
       FROM leiva.col_uebaunit u
       JOIN _sel su ON su.table_name=''col_uebaunit'' AND su.id=u.t_id
       WHERE u.%1$I IS NOT NULL
       ON CONFLICT DO NOTHING',
      v_fk_uc
    );
  END IF;
END $$;

DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT child_fk_col
    FROM _fk
    WHERE child_table='ilc_caracteristicasunidadconstruccion'
      AND parent_table='cr_unidadconstruccion'
  LOOP
    EXECUTE format(
      'INSERT INTO _sel(table_name,id)
       SELECT ''ilc_caracteristicasunidadconstruccion'', c.t_id
       FROM leiva.ilc_caracteristicasunidadconstruccion c
       JOIN _sel u ON u.table_name=''cr_unidadconstruccion'' AND u.id=c.%1$I
       ON CONFLICT DO NOTHING',
      r.child_fk_col
    );
  END LOOP;
END $$;

DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT child_fk_col
    FROM _fk
    WHERE child_table='cuc_calificacion_unidadconstruccion'
      AND parent_table='ilc_caracteristicasunidadconstruccion'
  LOOP
    EXECUTE format(
      'INSERT INTO _sel(table_name,id)
       SELECT ''cuc_calificacion_unidadconstruccion'', c.t_id
       FROM leiva.cuc_calificacion_unidadconstruccion c
       JOIN _sel ch ON ch.table_name=''ilc_caracteristicasunidadconstruccion'' AND ch.id=c.%1$I
       ON CONFLICT DO NOTHING',
      r.child_fk_col
    );
  END LOOP;
END $$;

-- Fallback por nombres convencionales de columnas cuando faltan FKs en metadata.
DO $$
DECLARE
  v_has_baunit boolean;
  v_has_uc boolean;
  v_fk_uc_char text;
  v_fk_char_cuc text;
BEGIN
  SELECT EXISTS (
           SELECT 1
           FROM information_schema.columns
           WHERE table_schema='leiva'
             AND table_name='col_uebaunit'
             AND column_name='baunit'
         ),
         EXISTS (
           SELECT 1
           FROM information_schema.columns
           WHERE table_schema='leiva'
             AND table_name='col_uebaunit'
             AND column_name='ue_cr_unidadconstruccion'
         )
  INTO v_has_baunit, v_has_uc;

  IF v_has_baunit THEN
    INSERT INTO _sel(table_name,id)
    SELECT 'col_uebaunit', u.t_id
    FROM leiva.col_uebaunit u
    JOIN _seed_predios sp ON sp.t_id = u.baunit
    ON CONFLICT DO NOTHING;
  END IF;

  IF v_has_uc THEN
    INSERT INTO _sel(table_name,id)
    SELECT 'cr_unidadconstruccion', u.ue_cr_unidadconstruccion
    FROM leiva.col_uebaunit u
    JOIN _sel su ON su.table_name='col_uebaunit' AND su.id=u.t_id
    WHERE u.ue_cr_unidadconstruccion IS NOT NULL
    ON CONFLICT DO NOTHING;
  END IF;

  SELECT c.column_name
  INTO v_fk_uc_char
  FROM information_schema.columns c
  WHERE c.table_schema='leiva'
    AND c.table_name='cr_unidadconstruccion'
    AND c.column_name ILIKE '%caracteristicasunidadconstruccion%'
    AND c.column_name NOT IN ('t_id','t_basket','t_ili_tid')
  ORDER BY
    CASE WHEN c.column_name='cr_caracteristicasunidadconstruccion' THEN 0 ELSE 1 END,
    c.ordinal_position
  LIMIT 1;

  IF v_fk_uc_char IS NOT NULL THEN
    EXECUTE format(
      'INSERT INTO _sel(table_name,id)
       SELECT ''ilc_caracteristicasunidadconstruccion'', u.%1$I
       FROM leiva.cr_unidadconstruccion u
       JOIN _sel su ON su.table_name=''cr_unidadconstruccion'' AND su.id=u.t_id
       WHERE u.%1$I IS NOT NULL
       ON CONFLICT DO NOTHING',
      v_fk_uc_char
    );
  END IF;

  SELECT c.column_name
  INTO v_fk_char_cuc
  FROM information_schema.columns c
  WHERE c.table_schema='leiva'
    AND c.table_name='cuc_calificacion_unidadconstruccion'
    AND c.column_name ILIKE '%caracteristicasunidadconstruccion%'
    AND c.column_name NOT IN ('t_id','t_basket','t_ili_tid')
  ORDER BY c.ordinal_position
  LIMIT 1;

  IF v_fk_char_cuc IS NOT NULL THEN
    EXECUTE format(
      'INSERT INTO _sel(table_name,id)
       SELECT ''cuc_calificacion_unidadconstruccion'', c.t_id
       FROM leiva.cuc_calificacion_unidadconstruccion c
       JOIN _sel ch ON ch.table_name=''ilc_caracteristicasunidadconstruccion'' AND ch.id=c.%1$I
       ON CONFLICT DO NOTHING',
      v_fk_char_cuc
    );
  END IF;
END $$;

-- Refuerzo CUC: incluir referencias requeridas por las calificaciones seleccionadas.
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT child_fk_col, parent_table
    FROM _fk
    WHERE child_table='cuc_calificacion_unidadconstruccion'
      AND (
        child_fk_col LIKE '%tipologia%'
        OR child_fk_col LIKE '%calificacionconvencional%'
        OR child_fk_col LIKE '%caracteristicasunidadconstruccion%'
      )
  LOOP
    EXECUTE format(
      'INSERT INTO _sel(table_name,id)
       SELECT %L, c.%I
       FROM leiva.cuc_calificacion_unidadconstruccion c
       JOIN _sel s ON s.table_name=''cuc_calificacion_unidadconstruccion'' AND s.id=c.t_id
       WHERE c.%I IS NOT NULL
       ON CONFLICT DO NOTHING',
      r.parent_table, r.child_fk_col, r.child_fk_col
    );
  END LOOP;
END $$;

-- Refuerzo CUC: incluir catálogos/tipos requeridos por esas tipologias.
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT child_table, child_fk_col, parent_table
    FROM _fk
    WHERE child_table IN ('cuc_tipologiaconstruccion','cuc_tipologianoconvencional')
  LOOP
    EXECUTE format(
      'INSERT INTO _sel(table_name,id)
       SELECT %L, c.%I
       FROM leiva.%I c
       JOIN _sel s ON s.table_name=%L AND s.id=c.t_id
       WHERE c.%I IS NOT NULL
       ON CONFLICT DO NOTHING',
      r.parent_table, r.child_fk_col, r.child_table, r.child_table, r.child_fk_col
    );
  END LOOP;
END $$;

-- Refuerzo CUC/UC por nombres de columna (independiente de metadata FK).
DO $$
DECLARE
  v_fk_uc_char text;
  v_fk_char_cuc text;
  v_fk_cal text;
  v_fk_tipc text;
  v_fk_tipn text;
BEGIN
  SELECT c.column_name
  INTO v_fk_uc_char
  FROM information_schema.columns c
  WHERE c.table_schema='leiva'
    AND c.table_name='cr_unidadconstruccion'
    AND c.column_name ILIKE '%caracteristicasunidadconstruccion%'
    AND c.column_name NOT IN ('t_id','t_basket','t_ili_tid')
  ORDER BY
    CASE WHEN c.column_name='cr_caracteristicasunidadconstruccion' THEN 0 ELSE 1 END,
    c.ordinal_position
  LIMIT 1;

  IF v_fk_uc_char IS NOT NULL THEN
    EXECUTE format(
      'INSERT INTO _sel(table_name,id)
       SELECT ''ilc_caracteristicasunidadconstruccion'', u.%1$I
       FROM leiva.cr_unidadconstruccion u
       JOIN _sel su ON su.table_name=''cr_unidadconstruccion'' AND su.id=u.t_id
       WHERE u.%1$I IS NOT NULL
       ON CONFLICT DO NOTHING',
      v_fk_uc_char
    );

    EXECUTE format(
      'INSERT INTO _sel(table_name,id)
       SELECT ''cr_unidadconstruccion'', u.t_id
       FROM leiva.cr_unidadconstruccion u
       JOIN _sel sch ON sch.table_name=''ilc_caracteristicasunidadconstruccion'' AND sch.id=u.%1$I
       ON CONFLICT DO NOTHING',
      v_fk_uc_char
    );
  END IF;

  SELECT c.column_name
  INTO v_fk_char_cuc
  FROM information_schema.columns c
  WHERE c.table_schema='leiva'
    AND c.table_name='cuc_calificacion_unidadconstruccion'
    AND c.column_name ILIKE '%caracteristicasunidadconstruccion%'
    AND c.column_name NOT IN ('t_id','t_basket','t_ili_tid')
  ORDER BY c.ordinal_position
  LIMIT 1;

  IF v_fk_char_cuc IS NOT NULL THEN
    EXECUTE format(
      'INSERT INTO _sel(table_name,id)
       SELECT ''ilc_caracteristicasunidadconstruccion'', c.%1$I
       FROM leiva.cuc_calificacion_unidadconstruccion c
       JOIN _sel sc ON sc.table_name=''cuc_calificacion_unidadconstruccion'' AND sc.id=c.t_id
       WHERE c.%1$I IS NOT NULL
       ON CONFLICT DO NOTHING',
      v_fk_char_cuc
    );
  END IF;

  SELECT c.column_name
  INTO v_fk_cal
  FROM information_schema.columns c
  WHERE c.table_schema='leiva'
    AND c.table_name='cuc_calificacion_unidadconstruccion'
    AND c.column_name ILIKE '%calificacionconvencional%'
    AND c.column_name NOT IN ('t_id','t_basket','t_ili_tid')
  ORDER BY c.ordinal_position
  LIMIT 1;

  IF v_fk_cal IS NOT NULL THEN
    EXECUTE format(
      'INSERT INTO _sel(table_name,id)
       SELECT ''cuc_calificacionconvencional'', c.%1$I
       FROM leiva.cuc_calificacion_unidadconstruccion c
       JOIN _sel sc ON sc.table_name=''cuc_calificacion_unidadconstruccion'' AND sc.id=c.t_id
       WHERE c.%1$I IS NOT NULL
       ON CONFLICT DO NOTHING',
      v_fk_cal
    );
  END IF;

  SELECT c.column_name
  INTO v_fk_tipc
  FROM information_schema.columns c
  WHERE c.table_schema='leiva'
    AND c.table_name='cuc_calificacion_unidadconstruccion'
    AND c.column_name ILIKE '%tipologiaconstruccion%'
    AND c.column_name NOT ILIKE '%noconvencional%'
    AND c.column_name NOT IN ('t_id','t_basket','t_ili_tid')
  ORDER BY c.ordinal_position
  LIMIT 1;

  IF v_fk_tipc IS NOT NULL THEN
    EXECUTE format(
      'INSERT INTO _sel(table_name,id)
       SELECT ''cuc_tipologiaconstruccion'', c.%1$I
       FROM leiva.cuc_calificacion_unidadconstruccion c
       JOIN _sel sc ON sc.table_name=''cuc_calificacion_unidadconstruccion'' AND sc.id=c.t_id
       WHERE c.%1$I IS NOT NULL
       ON CONFLICT DO NOTHING',
      v_fk_tipc
    );
  END IF;

  SELECT c.column_name
  INTO v_fk_tipn
  FROM information_schema.columns c
  WHERE c.table_schema='leiva'
    AND c.table_name='cuc_calificacion_unidadconstruccion'
    AND c.column_name ILIKE '%tipologianoconvencional%'
    AND c.column_name NOT IN ('t_id','t_basket','t_ili_tid')
  ORDER BY c.ordinal_position
  LIMIT 1;

  IF v_fk_tipn IS NOT NULL THEN
    EXECUTE format(
      'INSERT INTO _sel(table_name,id)
       SELECT ''cuc_tipologianoconvencional'', c.%1$I
       FROM leiva.cuc_calificacion_unidadconstruccion c
       JOIN _sel sc ON sc.table_name=''cuc_calificacion_unidadconstruccion'' AND sc.id=c.t_id
       WHERE c.%1$I IS NOT NULL
       ON CONFLICT DO NOTHING',
      v_fk_tipn
    );
  END IF;
END $$;

-- Refuerzo RRR/agrupaciones: asegurar que los derechos seleccionados conserven
-- sus interesados/fuentes y soporte de agrupaciones anidadas.
INSERT INTO _sel(table_name,id)
SELECT 'col_rrrinteresado', ri.t_id
FROM leiva.col_rrrinteresado ri
JOIN _sel d ON d.table_name='ilc_derecho' AND d.id=ri.rrr
ON CONFLICT DO NOTHING;

INSERT INTO _sel(table_name,id)
SELECT 'col_rrrfuente', rf.t_id
FROM leiva.col_rrrfuente rf
JOIN _sel d ON d.table_name='ilc_derecho' AND d.id=rf.rrr
ON CONFLICT DO NOTHING;

INSERT INTO _sel(table_name,id)
SELECT 'cr_agrupacioninteresados', ri.interesado_cr_agrupacioninteresados
FROM leiva.col_rrrinteresado ri
JOIN _sel s ON s.table_name='col_rrrinteresado' AND s.id=ri.t_id
WHERE ri.interesado_cr_agrupacioninteresados IS NOT NULL
ON CONFLICT DO NOTHING;

INSERT INTO _sel(table_name,id)
SELECT 'ilc_interesado', ri.interesado_ilc_interesado
FROM leiva.col_rrrinteresado ri
JOIN _sel s ON s.table_name='col_rrrinteresado' AND s.id=ri.t_id
WHERE ri.interesado_ilc_interesado IS NOT NULL
ON CONFLICT DO NOTHING;

INSERT INTO _sel(table_name,id)
SELECT 'ilc_fuenteadministrativa', rf.fuente_administrativa
FROM leiva.col_rrrfuente rf
JOIN _sel s ON s.table_name='col_rrrfuente' AND s.id=rf.t_id
WHERE rf.fuente_administrativa IS NOT NULL
ON CONFLICT DO NOTHING;

DO $$
DECLARE
  v_added int := 1;
  v_step int := 0;
BEGIN
  WHILE v_added > 0 LOOP
    v_added := 0;

    INSERT INTO _sel(table_name,id)
    SELECT 'col_miembros', m.t_id
    FROM leiva.col_miembros m
    JOIN _sel g ON g.table_name='cr_agrupacioninteresados' AND g.id=m.agrupacion
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS v_step = ROW_COUNT;
    v_added := v_added + COALESCE(v_step,0);

    INSERT INTO _sel(table_name,id)
    SELECT 'ilc_interesado', m.interesado_ilc_interesado
    FROM leiva.col_miembros m
    JOIN _sel sm ON sm.table_name='col_miembros' AND sm.id=m.t_id
    WHERE m.interesado_ilc_interesado IS NOT NULL
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS v_step = ROW_COUNT;
    v_added := v_added + COALESCE(v_step,0);

    INSERT INTO _sel(table_name,id)
    SELECT 'cr_agrupacioninteresados', m.interesado_cr_agrupacioninteresados
    FROM leiva.col_miembros m
    JOIN _sel sm ON sm.table_name='col_miembros' AND sm.id=m.t_id
    WHERE m.interesado_cr_agrupacioninteresados IS NOT NULL
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS v_step = ROW_COUNT;
    v_added := v_added + COALESCE(v_step,0);
  END LOOP;
END $$;

-- Guard FK: miembros válidos con interesado individual O agrupación.
DELETE FROM _sel s
WHERE s.table_name='col_miembros'
  AND NOT EXISTS (
    SELECT 1
    FROM leiva.col_miembros m
    JOIN _sel g ON g.table_name='cr_agrupacioninteresados' AND g.id=m.agrupacion
    WHERE m.t_id=s.id
      AND (
        (
          m.interesado_ilc_interesado IS NOT NULL
          AND EXISTS (
            SELECT 1
            FROM _sel i
            WHERE i.table_name='ilc_interesado'
              AND i.id=m.interesado_ilc_interesado
          )
        )
        OR (
          m.interesado_cr_agrupacioninteresados IS NOT NULL
          AND EXISTS (
            SELECT 1
            FROM _sel ga
            WHERE ga.table_name='cr_agrupacioninteresados'
              AND ga.id=m.interesado_cr_agrupacioninteresados
          )
        )
      )
  );

-- Segunda pasada de cierre ascendente FK tras expandir RRR/agrupaciones.
DO $$
DECLARE
  r record;
  v_added int := 1;
  v_step int := 0;
BEGIN
  WHILE v_added > 0 LOOP
    v_added := 0;
    FOR r IN SELECT child_table, child_fk_col, parent_table FROM _fk LOOP
      EXECUTE format(
        'INSERT INTO _sel(table_name,id)
         SELECT %L, c.%I
         FROM leiva.%I c
         JOIN _sel s ON s.table_name=%L AND s.id=c.t_id
         WHERE c.%I IS NOT NULL
         ON CONFLICT DO NOTHING',
        r.parent_table, r.child_fk_col, r.child_table, r.child_table, r.child_fk_col
      );
      GET DIAGNOSTICS v_step = ROW_COUNT;
      v_added := v_added + COALESCE(v_step,0);
    END LOOP;
  END LOOP;
END $$;

-- Guard FK: conservar solo derechos cuyo predio (unidad) está seleccionado.
DELETE FROM _sel s
WHERE s.table_name='ilc_derecho'
  AND NOT EXISTS (
    SELECT 1
    FROM leiva.ilc_derecho d
    JOIN _sel p ON p.table_name='ilc_predio' AND p.id=d.unidad
    WHERE d.t_id=s.id
  );

-- Guard FK: relaciones RRR solo si ilc_derecho existe en _sel.
DELETE FROM _sel s
WHERE s.table_name='col_rrrfuente'
  AND NOT EXISTS (
    SELECT 1
    FROM leiva.col_rrrfuente r
    JOIN _sel d ON d.table_name='ilc_derecho' AND d.id=r.rrr
    WHERE r.t_id=s.id
  );

DELETE FROM _sel s
WHERE s.table_name='col_rrrinteresado'
  AND NOT EXISTS (
    SELECT 1
    FROM leiva.col_rrrinteresado r
    JOIN _sel d ON d.table_name='ilc_derecho' AND d.id=r.rrr
    WHERE r.t_id=s.id
  );

-- Guard multiplicidad: ILC_Derecho requiere al menos 1 interesado y 1 fuente.
DELETE FROM _sel s
WHERE s.table_name='ilc_derecho'
  AND EXISTS (
    SELECT 1
    FROM leiva.ilc_derecho d
    WHERE d.t_id=s.id
      AND (
        NOT EXISTS (
          SELECT 1
          FROM leiva.col_rrrinteresado ri
          JOIN _sel sri ON sri.table_name='col_rrrinteresado' AND sri.id=ri.t_id
          WHERE ri.rrr=d.t_id
        )
        OR NOT EXISTS (
          SELECT 1
          FROM leiva.col_rrrfuente rf
          JOIN _sel srf ON srf.table_name='col_rrrfuente' AND srf.id=rf.t_id
          WHERE rf.rrr=d.t_id
        )
      )
  );

-- Segunda pasada: remover relaciones RRR que quedaron sin derecho.
DELETE FROM _sel s
WHERE s.table_name='col_rrrfuente'
  AND NOT EXISTS (
    SELECT 1
    FROM leiva.col_rrrfuente r
    JOIN _sel d ON d.table_name='ilc_derecho' AND d.id=r.rrr
    WHERE r.t_id=s.id
  );

DELETE FROM _sel s
WHERE s.table_name='col_rrrinteresado'
  AND NOT EXISTS (
    SELECT 1
    FROM leiva.col_rrrinteresado r
    JOIN _sel d ON d.table_name='ilc_derecho' AND d.id=r.rrr
    WHERE r.t_id=s.id
  );

-- Guard CUC: mantener solo filas válidas según FKs obligatorias y tipología alterna.
DO $$
DECLARE
  v_fk_cal text;
  v_fk_car text;
  v_fk_tipc text;
  v_fk_tipn text;
  v_tipc_expr text;
  v_tipn_expr text;
  v_sql text;
BEGIN
  SELECT
    MAX(CASE WHEN parent_table='cuc_calificacionconvencional' THEN child_fk_col END),
    MAX(CASE WHEN parent_table='ilc_caracteristicasunidadconstruccion' THEN child_fk_col END),
    MAX(CASE WHEN parent_table='cuc_tipologiaconstruccion' THEN child_fk_col END),
    MAX(CASE WHEN parent_table='cuc_tipologianoconvencional' THEN child_fk_col END)
  INTO v_fk_cal, v_fk_car, v_fk_tipc, v_fk_tipn
  FROM _fk
  WHERE child_table='cuc_calificacion_unidadconstruccion';

  IF v_fk_cal IS NULL THEN
    SELECT c.column_name
    INTO v_fk_cal
    FROM information_schema.columns c
    WHERE c.table_schema='leiva'
      AND c.table_name='cuc_calificacion_unidadconstruccion'
      AND c.column_name ILIKE '%calificacionconvencional%'
      AND c.column_name NOT IN ('t_id','t_basket','t_ili_tid')
    ORDER BY c.ordinal_position
    LIMIT 1;
  END IF;

  IF v_fk_car IS NULL THEN
    SELECT c.column_name
    INTO v_fk_car
    FROM information_schema.columns c
    WHERE c.table_schema='leiva'
      AND c.table_name='cuc_calificacion_unidadconstruccion'
      AND c.column_name ILIKE '%caracteristicasunidadconstruccion%'
      AND c.column_name NOT IN ('t_id','t_basket','t_ili_tid')
    ORDER BY c.ordinal_position
    LIMIT 1;
  END IF;

  IF v_fk_tipc IS NULL THEN
    SELECT c.column_name
    INTO v_fk_tipc
    FROM information_schema.columns c
    WHERE c.table_schema='leiva'
      AND c.table_name='cuc_calificacion_unidadconstruccion'
      AND c.column_name ILIKE '%tipologiaconstruccion%'
      AND c.column_name NOT ILIKE '%noconvencional%'
      AND c.column_name NOT IN ('t_id','t_basket','t_ili_tid')
    ORDER BY c.ordinal_position
    LIMIT 1;
  END IF;

  IF v_fk_tipn IS NULL THEN
    SELECT c.column_name
    INTO v_fk_tipn
    FROM information_schema.columns c
    WHERE c.table_schema='leiva'
      AND c.table_name='cuc_calificacion_unidadconstruccion'
      AND c.column_name ILIKE '%tipologianoconvencional%'
      AND c.column_name NOT IN ('t_id','t_basket','t_ili_tid')
    ORDER BY c.ordinal_position
    LIMIT 1;
  END IF;

  IF v_fk_cal IS NULL OR v_fk_car IS NULL THEN
    RAISE EXCEPTION 'No se encontraron columnas CUC obligatorias (calificacionconvencional/caracteristicasunidadconstruccion) ni por FK ni por nombre.';
  END IF;

  v_tipc_expr := CASE WHEN v_fk_tipc IS NULL THEN 'NULL' ELSE format('c.%I', v_fk_tipc) END;
  v_tipn_expr := CASE WHEN v_fk_tipn IS NULL THEN 'NULL' ELSE format('c.%I', v_fk_tipn) END;

  v_sql := format(
    'DELETE FROM _sel s
     WHERE s.table_name=''cuc_calificacion_unidadconstruccion''
       AND EXISTS (
         SELECT 1
         FROM leiva.cuc_calificacion_unidadconstruccion c
         WHERE c.t_id=s.id
           AND (
             c.%1$I IS NULL
             OR NOT EXISTS (
               SELECT 1 FROM _sel p
               WHERE p.table_name=''cuc_calificacionconvencional'' AND p.id=c.%1$I
             )
             OR c.%2$I IS NULL
             OR NOT EXISTS (
               SELECT 1 FROM _sel p
               WHERE p.table_name=''ilc_caracteristicasunidadconstruccion'' AND p.id=c.%2$I
             )
             OR COALESCE(%3$s, %4$s) IS NULL
             OR (%3$s IS NOT NULL AND NOT EXISTS (
               SELECT 1 FROM _sel p
               WHERE p.table_name=''cuc_tipologiaconstruccion'' AND p.id=%3$s
             ))
             OR (%4$s IS NOT NULL AND NOT EXISTS (
               SELECT 1 FROM _sel p
               WHERE p.table_name=''cuc_tipologianoconvencional'' AND p.id=%4$s
             ))
           )
       )',
    v_fk_cal, v_fk_car, v_tipc_expr, v_tipn_expr
  );
  EXECUTE v_sql;
END $$;

-- Guard CUC multiplicidad: podar padres sin vínculo en cuc_calificacion_unidadconstruccion.
DO $$
DECLARE
  v_fk_cal text;
  v_fk_car text;
  v_fk_tipc text;
  v_fk_tipn text;
BEGIN
  SELECT
    MAX(CASE WHEN parent_table='cuc_calificacionconvencional' THEN child_fk_col END),
    MAX(CASE WHEN parent_table='ilc_caracteristicasunidadconstruccion' THEN child_fk_col END),
    MAX(CASE WHEN parent_table='cuc_tipologiaconstruccion' THEN child_fk_col END),
    MAX(CASE WHEN parent_table='cuc_tipologianoconvencional' THEN child_fk_col END)
  INTO v_fk_cal, v_fk_car, v_fk_tipc, v_fk_tipn
  FROM _fk
  WHERE child_table='cuc_calificacion_unidadconstruccion';

  IF v_fk_cal IS NULL THEN
    SELECT c.column_name
    INTO v_fk_cal
    FROM information_schema.columns c
    WHERE c.table_schema='leiva'
      AND c.table_name='cuc_calificacion_unidadconstruccion'
      AND c.column_name ILIKE '%calificacionconvencional%'
      AND c.column_name NOT IN ('t_id','t_basket','t_ili_tid')
    ORDER BY c.ordinal_position
    LIMIT 1;
  END IF;

  IF v_fk_car IS NULL THEN
    SELECT c.column_name
    INTO v_fk_car
    FROM information_schema.columns c
    WHERE c.table_schema='leiva'
      AND c.table_name='cuc_calificacion_unidadconstruccion'
      AND c.column_name ILIKE '%caracteristicasunidadconstruccion%'
      AND c.column_name NOT IN ('t_id','t_basket','t_ili_tid')
    ORDER BY c.ordinal_position
    LIMIT 1;
  END IF;

  IF v_fk_tipc IS NULL THEN
    SELECT c.column_name
    INTO v_fk_tipc
    FROM information_schema.columns c
    WHERE c.table_schema='leiva'
      AND c.table_name='cuc_calificacion_unidadconstruccion'
      AND c.column_name ILIKE '%tipologiaconstruccion%'
      AND c.column_name NOT ILIKE '%noconvencional%'
      AND c.column_name NOT IN ('t_id','t_basket','t_ili_tid')
    ORDER BY c.ordinal_position
    LIMIT 1;
  END IF;

  IF v_fk_tipn IS NULL THEN
    SELECT c.column_name
    INTO v_fk_tipn
    FROM information_schema.columns c
    WHERE c.table_schema='leiva'
      AND c.table_name='cuc_calificacion_unidadconstruccion'
      AND c.column_name ILIKE '%tipologianoconvencional%'
      AND c.column_name NOT IN ('t_id','t_basket','t_ili_tid')
    ORDER BY c.ordinal_position
    LIMIT 1;
  END IF;

  IF v_fk_cal IS NOT NULL THEN
    EXECUTE format(
      'DELETE FROM _sel s
       WHERE s.table_name=''cuc_calificacionconvencional''
         AND NOT EXISTS (
           SELECT 1
           FROM leiva.cuc_calificacion_unidadconstruccion c
           JOIN _sel cc ON cc.table_name=''cuc_calificacion_unidadconstruccion'' AND cc.id=c.t_id
           WHERE c.%1$I=s.id
         )',
      v_fk_cal
    );
  END IF;

  IF v_fk_car IS NOT NULL THEN
    EXECUTE format(
      'DELETE FROM _sel s
       WHERE s.table_name=''ilc_caracteristicasunidadconstruccion''
         AND NOT EXISTS (
           SELECT 1
           FROM leiva.cuc_calificacion_unidadconstruccion c
           JOIN _sel cc ON cc.table_name=''cuc_calificacion_unidadconstruccion'' AND cc.id=c.t_id
           WHERE c.%1$I=s.id
         )',
      v_fk_car
    );
  END IF;

  IF v_fk_tipc IS NOT NULL THEN
    EXECUTE format(
      'DELETE FROM _sel s
       WHERE s.table_name=''cuc_tipologiaconstruccion''
         AND NOT EXISTS (
           SELECT 1
           FROM leiva.cuc_calificacion_unidadconstruccion c
           JOIN _sel cc ON cc.table_name=''cuc_calificacion_unidadconstruccion'' AND cc.id=c.t_id
           WHERE c.%1$I=s.id
         )',
      v_fk_tipc
    );
  END IF;

  IF v_fk_tipn IS NOT NULL THEN
    EXECUTE format(
      'DELETE FROM _sel s
       WHERE s.table_name=''cuc_tipologianoconvencional''
         AND NOT EXISTS (
           SELECT 1
           FROM leiva.cuc_calificacion_unidadconstruccion c
           JOIN _sel cc ON cc.table_name=''cuc_calificacion_unidadconstruccion'' AND cc.id=c.t_id
           WHERE c.%1$I=s.id
         )',
      v_fk_tipn
    );
  END IF;
END $$;

-- Cierre FK global iterativo: no dejar hijos con referencia a padres fuera de _sel.
DO $$
DECLARE
  r record;
  v_pass int := 0;
  v_deleted int := 0;
  v_step_deleted int := 0;
BEGIN
  LOOP
    v_pass := v_pass + 1;
    v_deleted := 0;

    FOR r IN SELECT child_table, child_fk_col, parent_table FROM _fk LOOP
      EXECUTE format(
        'DELETE FROM _sel s
         WHERE s.table_name=%1$L
           AND EXISTS (
             SELECT 1
             FROM leiva.%2$I c
             WHERE c.t_id=s.id
               AND c.%3$I IS NOT NULL
               AND NOT EXISTS (
                 SELECT 1
                 FROM _sel p
                 WHERE p.table_name=%4$L
                   AND p.id=c.%3$I
               )
           )',
        r.child_table, r.child_table, r.child_fk_col, r.parent_table
      );
      GET DIAGNOSTICS v_step_deleted = ROW_COUNT;
      v_deleted := v_deleted + COALESCE(v_step_deleted,0);
    END LOOP;

    EXIT WHEN v_deleted = 0 OR v_pass >= 12;
  END LOOP;
END $$;

-- Poda final CUC inversa: características sin fila en cuc_calificacion_unidadconstruccion.
DO $$
DECLARE
  v_fk_car text;
BEGIN
  SELECT MAX(CASE WHEN parent_table='ilc_caracteristicasunidadconstruccion' THEN child_fk_col END)
  INTO v_fk_car
  FROM _fk
  WHERE child_table='cuc_calificacion_unidadconstruccion';

  IF v_fk_car IS NULL THEN
    SELECT c.column_name
    INTO v_fk_car
    FROM information_schema.columns c
    WHERE c.table_schema='leiva'
      AND c.table_name='cuc_calificacion_unidadconstruccion'
      AND c.column_name ILIKE '%caracteristicasunidadconstruccion%'
      AND c.column_name NOT IN ('t_id','t_basket','t_ili_tid')
    ORDER BY c.ordinal_position
    LIMIT 1;
  END IF;

  IF v_fk_car IS NOT NULL THEN
    EXECUTE format(
      'DELETE FROM _sel s
       WHERE s.table_name=''ilc_caracteristicasunidadconstruccion''
         AND NOT EXISTS (
           SELECT 1
           FROM leiva.cuc_calificacion_unidadconstruccion c
           JOIN _sel cc ON cc.table_name=''cuc_calificacion_unidadconstruccion'' AND cc.id=c.t_id
           WHERE c.%1$I=s.id
         )',
      v_fk_car
    );
  END IF;
END $$;

-- 4) Tablas destino + bandera t_basket
DROP TABLE IF EXISTS _table_flags;
CREATE TEMP TABLE _table_flags AS
SELECT
  s.table_name,
  EXISTS (
    SELECT 1 FROM information_schema.columns c
    WHERE c.table_schema='leiva'
      AND c.table_name=s.table_name
      AND c.column_name='t_basket'
  ) AS has_t_basket
FROM (SELECT DISTINCT table_name FROM _sel) s
JOIN information_schema.tables t
  ON t.table_schema='b_asignaciones'
 AND t.table_name=s.table_name;

-- 5) Baskets requeridos por topics
DROP TABLE IF EXISTS _src_baskets;
CREATE TEMP TABLE _src_baskets(source_basket bigint PRIMARY KEY);

DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT table_name FROM _table_flags WHERE has_t_basket LOOP
    EXECUTE format(
      'INSERT INTO _src_baskets(source_basket)
       SELECT DISTINCT x.t_basket
       FROM leiva.%I x
       JOIN _sel s ON s.table_name=%L AND s.id=x.t_id
       WHERE x.t_basket IS NOT NULL
       ON CONFLICT DO NOTHING',
      r.table_name, r.table_name
    );
  END LOOP;
END $$;

WITH topic_meta AS (
  SELECT
    sb.topic,
    MIN(sb.attachmentkey) AS attachmentkey,
    MIN(sb.domains) AS domains
  FROM _src_baskets x
  JOIN leiva.t_ili2db_basket sb ON sb.t_id=x.source_basket
  GROUP BY sb.topic
),
base AS (
  SELECT COALESCE(MAX(t_id),0) AS mx
  FROM b_asignaciones.t_ili2db_basket
),
num AS (
  SELECT tm.*, row_number() OVER (ORDER BY tm.topic) rn
  FROM topic_meta tm
)
INSERT INTO b_asignaciones.t_ili2db_basket
  (t_id,dataset,topic,t_ili_tid,attachmentkey,domains)
SELECT
  base.mx + num.rn,
  (SELECT dataset_id FROM _ds),
  num.topic,
  md5(CONCAT((SELECT dataset_name FROM _cfg), '_', num.topic, '_', (base.mx + num.rn)::text))::uuid,
  COALESCE(num.attachmentkey, CONCAT((SELECT dataset_name FROM _cfg), '_attach_', base.mx + num.rn)),
  COALESCE(num.domains, '')
FROM num, base;

DROP TABLE IF EXISTS _basket_map;
CREATE TEMP TABLE _basket_map AS
SELECT
  sb.t_id AS source_basket,
  tb.t_id AS target_basket
FROM _src_baskets x
JOIN leiva.t_ili2db_basket sb ON sb.t_id=x.source_basket
JOIN b_asignaciones.t_ili2db_basket tb
  ON tb.dataset=(SELECT dataset_id FROM _ds)
 AND tb.topic=sb.topic;

-- 6) Mapeo de IDs + copia iterativa (reintenta por FK)
-- Evita pérdidas por colisión global de t_id entre datasets.
DROP TABLE IF EXISTS _id_map;
CREATE TEMP TABLE _id_map(
  table_name text NOT NULL,
  source_id bigint NOT NULL,
  target_id bigint NOT NULL,
  PRIMARY KEY(table_name, source_id)
);

DO $$
DECLARE
  r record;
  v_base bigint;
BEGIN
  FOR r IN SELECT table_name, has_t_basket FROM _table_flags ORDER BY table_name LOOP
    EXECUTE format(
      'SELECT GREATEST(
         COALESCE((SELECT MAX(t.t_id) FROM b_asignaciones.%1$I t), 0),
         COALESCE((SELECT MAX(s.id) FROM _sel s WHERE s.table_name=%2$L), 0)
       )',
      r.table_name,
      r.table_name
    )
    INTO v_base;

    IF r.has_t_basket THEN
      IF r.table_name = 'ilc_predio' THEN
        EXECUTE format(
          'WITH src AS (
             SELECT
               s.id AS source_id,
               UPPER(NULLIF(BTRIM(p.numero_predial_nacional::text), '''')) AS npn_key
             FROM _sel s
             JOIN leiva.%1$I p
               ON p.t_id=s.id
             WHERE s.table_name=%2$L
           ),
           existing_id AS (
             SELECT
               src.source_id,
               t.t_id AS existing_id,
               CASE
                 WHEN tb.dataset=(SELECT dataset_id FROM _ds) THEN TRUE
                 ELSE FALSE
               END AS in_dataset
             FROM src
             LEFT JOIN b_asignaciones.%1$I t
               ON t.t_id=src.source_id
             LEFT JOIN b_asignaciones.t_ili2db_basket tb
               ON tb.t_id=t.t_basket
           ),
           existing_npn AS (
             SELECT
               src.source_id,
               MIN(t.t_id) AS npn_id
             FROM src
             LEFT JOIN b_asignaciones.%1$I t
               ON src.npn_key IS NOT NULL
              AND UPPER(NULLIF(BTRIM(t.numero_predial_nacional::text), '''')) = src.npn_key
             GROUP BY src.source_id
           ),
           merged AS (
             SELECT
               e.source_id,
               e.existing_id,
               e.in_dataset,
               n.npn_id
             FROM existing_id e
             LEFT JOIN existing_npn n
               ON n.source_id=e.source_id
           ),
           direct AS (
             SELECT
               m.source_id,
               CASE
                 WHEN m.in_dataset IS TRUE THEN m.existing_id
                 WHEN m.npn_id IS NOT NULL THEN m.npn_id
                 WHEN m.existing_id IS NULL THEN m.source_id
                 ELSE NULL
               END AS target_id
             FROM merged m
           ),
           need_clone AS (
             SELECT m.source_id
             FROM merged m
             WHERE m.existing_id IS NOT NULL
               AND m.in_dataset IS DISTINCT FROM TRUE
               AND m.npn_id IS NULL
           ),
           clone_ids AS (
             SELECT
               n.source_id,
               %3$s + ROW_NUMBER() OVER (ORDER BY n.source_id) AS target_id
             FROM need_clone n
           ),
           final_map AS (
             SELECT d.source_id, d.target_id
             FROM direct d
             WHERE d.target_id IS NOT NULL
             UNION ALL
             SELECT c.source_id, c.target_id
             FROM clone_ids c
           )
           INSERT INTO _id_map(table_name, source_id, target_id)
           SELECT %2$L, f.source_id, f.target_id
           FROM final_map f
           ON CONFLICT(table_name, source_id)
           DO UPDATE SET target_id=EXCLUDED.target_id',
          r.table_name,
          r.table_name,
          v_base
        );
      ELSIF r.table_name = 'ilc_interesado' THEN
        EXECUTE format(
           'WITH src AS (
             SELECT
               s.id AS source_id,
               NULLIF(
                 UPPER(REGEXP_REPLACE(BTRIM(i.documento_identidad::text), ''[^0-9A-Z]+'', '''', ''g'')),
                 ''''
               ) AS doc_key
             FROM _sel s
             JOIN leiva.%1$I i
               ON i.t_id=s.id
             WHERE s.table_name=%2$L
           ),
           existing_id AS (
             SELECT
                src.source_id,
                t.t_id AS existing_id,
                CASE
                  WHEN tb.dataset=(SELECT dataset_id FROM _ds) THEN TRUE
                  ELSE FALSE
                END AS in_dataset
             FROM src
             LEFT JOIN b_asignaciones.%1$I t
               ON t.t_id=src.source_id
             LEFT JOIN b_asignaciones.t_ili2db_basket tb
               ON tb.t_id=t.t_basket
           ),
           existing_doc AS (
             SELECT
                src.source_id,
                MIN(t.t_id) AS doc_id
             FROM src
             LEFT JOIN b_asignaciones.%1$I t
                ON src.doc_key IS NOT NULL
               AND NULLIF(
                     UPPER(REGEXP_REPLACE(BTRIM(t.documento_identidad::text), ''[^0-9A-Z]+'', '''', ''g'')),
                     ''''
                   ) = src.doc_key
             LEFT JOIN b_asignaciones.t_ili2db_basket tb_doc
               ON tb_doc.t_id=t.t_basket
             LEFT JOIN b_asignaciones.t_ili2db_dataset td_doc
               ON td_doc.t_id=tb_doc.dataset
              AND td_doc.datasetname=(SELECT dataset_name FROM _cfg)
             WHERE t.t_id IS NULL OR td_doc.t_id IS NOT NULL
             GROUP BY src.source_id
           ),
           merged AS (
              SELECT
                e.source_id,
                e.existing_id,
                e.in_dataset,
                d.doc_id,
                s.doc_key
              FROM existing_id e
              LEFT JOIN existing_doc d
                ON d.source_id=e.source_id
              JOIN src s
                ON s.source_id=e.source_id
            ),
            direct_keep AS (
              SELECT
                source_id,
                existing_id AS target_id
              FROM merged
              WHERE in_dataset IS TRUE
            ),
            direct_doc AS (
              SELECT
                source_id,
                doc_id AS target_id
              FROM merged
              WHERE in_dataset IS DISTINCT FROM TRUE
                AND doc_id IS NOT NULL
            ),
            pending AS (
              SELECT source_id
                   , existing_id
                   , doc_key
              FROM merged
              WHERE in_dataset IS DISTINCT FROM TRUE
                AND doc_id IS NULL
            ),
            pending_doc_group AS (
              SELECT
                g.doc_key,
                %3$s + ROW_NUMBER() OVER (ORDER BY g.doc_key) AS target_id
              FROM (
                SELECT DISTINCT p.doc_key
                FROM pending p
                WHERE p.doc_key IS NOT NULL
              ) g
            ),
            pending_doc AS (
              SELECT
                p.source_id,
                g.target_id
              FROM pending p
              JOIN pending_doc_group g
                ON g.doc_key=p.doc_key
            ),
            pending_nodoc_direct AS (
              SELECT
                p.source_id,
                p.source_id AS target_id
              FROM pending p
              WHERE p.doc_key IS NULL
                AND p.existing_id IS NULL
            ),
            pending_nodoc_clone AS (
              SELECT
                p.source_id,
                %3$s
                + COALESCE((SELECT COUNT(*) FROM pending_doc_group), 0)
                + ROW_NUMBER() OVER (ORDER BY p.source_id) AS target_id
              FROM pending p
              WHERE p.doc_key IS NULL
                AND p.existing_id IS NOT NULL
            ),
            direct AS (
              SELECT source_id, target_id FROM direct_keep
              UNION ALL
              SELECT source_id, target_id FROM direct_doc
              UNION ALL
              SELECT source_id, target_id FROM pending_doc
              UNION ALL
              SELECT source_id, target_id FROM pending_nodoc_direct
              UNION ALL
              SELECT source_id, target_id FROM pending_nodoc_clone
            )
            INSERT INTO _id_map(table_name, source_id, target_id)
            SELECT %2$L, d.source_id, d.target_id
            FROM direct d
            ON CONFLICT(table_name, source_id)
            DO UPDATE SET target_id=EXCLUDED.target_id',
          r.table_name,
          r.table_name,
          v_base
        );
      ELSE
        EXECUTE format(
          'WITH src AS (
             SELECT s.id AS source_id
             FROM _sel s
             WHERE s.table_name=%1$L
           ),
           existing AS (
             SELECT
               src.source_id,
               t.t_id AS existing_id,
               CASE
                 WHEN tb.dataset=(SELECT dataset_id FROM _ds) THEN TRUE
                 ELSE FALSE
               END AS in_dataset
             FROM src
             LEFT JOIN b_asignaciones.%2$I t
               ON t.t_id=src.source_id
             LEFT JOIN b_asignaciones.t_ili2db_basket tb
               ON tb.t_id=t.t_basket
           ),
           direct AS (
             SELECT source_id, source_id AS target_id
             FROM existing
             WHERE existing_id IS NULL
                OR in_dataset IS TRUE
           ),
           need_clone AS (
             SELECT source_id
             FROM existing
             WHERE existing_id IS NOT NULL
               AND in_dataset IS DISTINCT FROM TRUE
           ),
           clone_ids AS (
             SELECT
               n.source_id,
               %3$s + ROW_NUMBER() OVER (ORDER BY n.source_id) AS target_id
             FROM need_clone n
           )
           INSERT INTO _id_map(table_name, source_id, target_id)
           SELECT %1$L, d.source_id, d.target_id
           FROM direct d
           UNION ALL
           SELECT %1$L, c.source_id, c.target_id
           FROM clone_ids c
           ON CONFLICT(table_name, source_id)
           DO UPDATE SET target_id=EXCLUDED.target_id',
          r.table_name,
          r.table_name,
          v_base
        );
      END IF;
    ELSE
      EXECUTE format(
        'WITH src AS (
           SELECT s.id AS source_id
           FROM _sel s
           WHERE s.table_name=%1$L
         ),
         existing AS (
           SELECT src.source_id, t.t_id AS existing_id
           FROM src
           LEFT JOIN b_asignaciones.%2$I t
             ON t.t_id=src.source_id
         ),
         direct AS (
           SELECT source_id, source_id AS target_id
           FROM existing
           WHERE existing_id IS NULL
         ),
         need_clone AS (
           SELECT source_id
           FROM existing
           WHERE existing_id IS NOT NULL
         ),
         clone_ids AS (
           SELECT
             n.source_id,
             %3$s + ROW_NUMBER() OVER (ORDER BY n.source_id) AS target_id
           FROM need_clone n
         )
         INSERT INTO _id_map(table_name, source_id, target_id)
         SELECT %1$L, d.source_id, d.target_id
         FROM direct d
         UNION ALL
         SELECT %1$L, c.source_id, c.target_id
         FROM clone_ids c
         ON CONFLICT(table_name, source_id)
         DO UPDATE SET target_id=EXCLUDED.target_id',
        r.table_name,
        r.table_name,
        v_base
      );
    END IF;
  END LOOP;
END $$;

-- Si ilc_predio se mapeo contra filas existentes por NPN, moverlas al basket destino
-- del dataset actual para evitar que queden referenciadas en otro dataset.
UPDATE b_asignaciones.ilc_predio p
SET t_basket = bm.target_basket
FROM leiva.ilc_predio s
JOIN _id_map mi
  ON mi.table_name='ilc_predio'
 AND mi.source_id=s.t_id
JOIN _basket_map bm
  ON bm.source_basket=s.t_basket
WHERE p.t_id=mi.target_id
  AND p.t_basket IS DISTINCT FROM bm.target_basket;

DO $$
DECLARE
  r record;
  fk_row record;
  pass_i int := 0;
  v_rows int;
  v_inserted int;
  v_idx int;
  v_alias text;
  v_fk_join_sql text;
  v_fk_json_pairs text;
  v_conflict_sql text;
  v_sql text;
BEGIN
  LOOP
    pass_i := pass_i + 1;
    v_inserted := 0;

    FOR r IN SELECT table_name, has_t_basket FROM _table_flags ORDER BY table_name LOOP
      BEGIN
        v_idx := 0;
        v_fk_join_sql := '';
        v_fk_json_pairs := '';

        FOR fk_row IN
          SELECT f.child_fk_col, f.parent_table
          FROM _fk f
          WHERE f.child_table = r.table_name
            AND EXISTS (
              SELECT 1
              FROM information_schema.columns c
              WHERE c.table_schema='b_asignaciones'
                AND c.table_name=r.table_name
                AND c.column_name=f.child_fk_col
            )
        LOOP
          v_idx := v_idx + 1;
          v_alias := format('mp%s', v_idx);
          v_fk_join_sql := v_fk_join_sql || format(
            ' LEFT JOIN _id_map %1$I
                ON %1$I.table_name=%2$L
               AND %1$I.source_id=s.%3$I',
            v_alias,
            fk_row.parent_table,
            fk_row.child_fk_col
          );
          v_fk_json_pairs := v_fk_json_pairs || format(
            ', %1$L, COALESCE(%2$I.target_id, s.%1$I)',
            fk_row.child_fk_col,
            v_alias
          );
        END LOOP;

        IF r.table_name = 'ilc_interesado' THEN
          -- Mantener ilc_interesado dentro del dataset actual cuando hay
          -- conflicto por documento_identidad con filas de otros datasets.
          v_conflict_sql := 'ON CONFLICT (documento_identidad) DO UPDATE
                             SET t_basket = EXCLUDED.t_basket';
        ELSE
          v_conflict_sql := 'ON CONFLICT (t_id) DO NOTHING';
        END IF;

        IF r.has_t_basket THEN
          v_sql := format(
            'INSERT INTO b_asignaciones.%1$I
             SELECT (jsonb_populate_record(
                       NULL::b_asignaciones.%1$I,
                       to_jsonb(s) || jsonb_build_object(
                         ''t_id'', mi.target_id,
                         ''t_basket'', bm.target_basket%2$s
                       )
                     )).*
             FROM leiva.%1$I s
             JOIN _sel x
               ON x.table_name=%3$L
              AND x.id=s.t_id
             JOIN _id_map mi
               ON mi.table_name=%3$L
              AND mi.source_id=s.t_id
             JOIN _basket_map bm
               ON bm.source_basket=s.t_basket
             LEFT JOIN b_asignaciones.%1$I t
               ON t.t_id=mi.target_id
             %4$s
             WHERE t.t_id IS NULL
             %5$s',
            r.table_name,
            v_fk_json_pairs,
            r.table_name,
            v_fk_join_sql,
            v_conflict_sql
          );
        ELSE
          v_sql := format(
            'INSERT INTO b_asignaciones.%1$I
             SELECT (jsonb_populate_record(
                       NULL::b_asignaciones.%1$I,
                       to_jsonb(s) || jsonb_build_object(
                         ''t_id'', mi.target_id%2$s
                       )
                     )).*
             FROM leiva.%1$I s
             JOIN _sel x
               ON x.table_name=%3$L
              AND x.id=s.t_id
             JOIN _id_map mi
               ON mi.table_name=%3$L
              AND mi.source_id=s.t_id
             LEFT JOIN b_asignaciones.%1$I t
               ON t.t_id=mi.target_id
             %4$s
             WHERE t.t_id IS NULL
             %5$s',
            r.table_name,
            v_fk_json_pairs,
            r.table_name,
            v_fk_join_sql,
            v_conflict_sql
          );
        END IF;

        EXECUTE v_sql;
        GET DIAGNOSTICS v_rows = ROW_COUNT;
        v_inserted := v_inserted + COALESCE(v_rows,0);

        IF r.table_name = 'ilc_interesado' THEN
          EXECUTE '
            WITH src AS (
              SELECT
                s.t_id AS source_id,
                NULLIF(
                  UPPER(REGEXP_REPLACE(BTRIM(s.documento_identidad::text), ''[^0-9A-Z]+'', '''', ''g'')),
                  ''''
                ) AS doc_key
              FROM leiva.ilc_interesado s
              JOIN _sel x
                ON x.table_name=''ilc_interesado''
               AND x.id=s.t_id
            ),
            matched AS (
              SELECT
                src.source_id,
                MIN(t.t_id) AS target_id
              FROM src
              JOIN b_asignaciones.ilc_interesado t
                ON src.doc_key IS NOT NULL
               AND NULLIF(
                     UPPER(REGEXP_REPLACE(BTRIM(t.documento_identidad::text), ''[^0-9A-Z]+'', '''', ''g'')),
                     ''''
                   ) = src.doc_key
              JOIN b_asignaciones.t_ili2db_basket tb
                ON tb.t_id=t.t_basket
              JOIN b_asignaciones.t_ili2db_dataset td
                ON td.t_id=tb.dataset
               AND td.datasetname=(SELECT dataset_name FROM _cfg)
              GROUP BY src.source_id
            )
            UPDATE _id_map mi
            SET target_id=m.target_id
            FROM matched m
            WHERE mi.table_name=''ilc_interesado''
              AND mi.source_id=m.source_id
              AND mi.target_id IS DISTINCT FROM m.target_id';
        END IF;

      EXCEPTION WHEN foreign_key_violation THEN
        NULL;
      END;
    END LOOP;

    EXIT WHEN v_inserted=0 OR pass_i>=30;
  END LOOP;
END $$;

-- 6.1) Cierre FK en destino (dataset): remover hijos que apunten a padres no copiados.
DO $$
DECLARE
  r record;
  v_pass int := 0;
  v_deleted int := 0;
  v_step_deleted int := 0;
BEGIN
  LOOP
    v_pass := v_pass + 1;
    v_deleted := 0;

    FOR r IN
      SELECT
        fk.child_table,
        fk.child_fk_col,
        fk.parent_table,
        EXISTS (
          SELECT 1
          FROM information_schema.columns c
          WHERE c.table_schema='b_asignaciones'
            AND c.table_name=fk.child_table
            AND c.column_name='t_basket'
        ) AS child_has_basket,
        EXISTS (
          SELECT 1
          FROM information_schema.columns c
          WHERE c.table_schema='b_asignaciones'
            AND c.table_name=fk.parent_table
            AND c.column_name='t_basket'
        ) AS parent_has_basket
      FROM _fk fk
      WHERE EXISTS (
        SELECT 1
        FROM information_schema.tables t
        WHERE t.table_schema='b_asignaciones'
          AND t.table_name=fk.child_table
      )
      AND EXISTS (
        SELECT 1
        FROM information_schema.tables t
        WHERE t.table_schema='b_asignaciones'
          AND t.table_name=fk.parent_table
      )
    LOOP
      IF NOT r.child_has_basket THEN
        CONTINUE;
      END IF;

      IF r.parent_has_basket THEN
        EXECUTE format(
          'DELETE FROM b_asignaciones.%1$I c
           USING b_asignaciones.t_ili2db_basket cb, b_asignaciones.t_ili2db_dataset cd
           WHERE c.t_basket=cb.t_id
             AND cb.dataset=cd.t_id
             AND cd.datasetname=(SELECT dataset_name FROM _cfg)
             AND c.%2$I IS NOT NULL
             AND NOT EXISTS (
               SELECT 1
               FROM b_asignaciones.%3$I p
               JOIN b_asignaciones.t_ili2db_basket pb ON pb.t_id=p.t_basket
               JOIN b_asignaciones.t_ili2db_dataset pd ON pd.t_id=pb.dataset
               WHERE p.t_id=c.%2$I
                 AND pd.datasetname=(SELECT dataset_name FROM _cfg)
             )',
          r.child_table, r.child_fk_col, r.parent_table
        );
      ELSE
        EXECUTE format(
          'DELETE FROM b_asignaciones.%1$I c
           USING b_asignaciones.t_ili2db_basket cb, b_asignaciones.t_ili2db_dataset cd
           WHERE c.t_basket=cb.t_id
             AND cb.dataset=cd.t_id
             AND cd.datasetname=(SELECT dataset_name FROM _cfg)
             AND c.%2$I IS NOT NULL
             AND NOT EXISTS (
               SELECT 1
               FROM b_asignaciones.%3$I p
               WHERE p.t_id=c.%2$I
             )',
          r.child_table, r.child_fk_col, r.parent_table
        );
      END IF;

      GET DIAGNOSTICS v_step_deleted = ROW_COUNT;
      v_deleted := v_deleted + COALESCE(v_step_deleted,0);
    END LOOP;

    EXIT WHEN v_deleted = 0 OR v_pass >= 12;
  END LOOP;
END $$;

-- 6.2) CUC inversa en destino: quitar padres CUC sin vínculo real en la tabla puente.
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT fk.child_fk_col, fk.parent_table
    FROM _fk fk
    WHERE fk.child_table='cuc_calificacion_unidadconstruccion'
      AND fk.parent_table IN (
        'cuc_calificacionconvencional',
        'ilc_caracteristicasunidadconstruccion',
        'cuc_tipologiaconstruccion',
        'cuc_tipologianoconvencional'
      )
      AND EXISTS (
        SELECT 1
        FROM information_schema.columns cp
        WHERE cp.table_schema='b_asignaciones'
          AND cp.table_name=fk.parent_table
          AND cp.column_name='t_basket'
      )
  LOOP
    EXECUTE format(
      'DELETE FROM b_asignaciones.%1$I p
       USING b_asignaciones.t_ili2db_basket pb, b_asignaciones.t_ili2db_dataset pd
       WHERE p.t_basket=pb.t_id
         AND pb.dataset=pd.t_id
         AND pd.datasetname=(SELECT dataset_name FROM _cfg)
         AND NOT EXISTS (
           SELECT 1
           FROM b_asignaciones.cuc_calificacion_unidadconstruccion c
           JOIN b_asignaciones.t_ili2db_basket cb ON cb.t_id=c.t_basket
           JOIN b_asignaciones.t_ili2db_dataset cd ON cd.t_id=cb.dataset
           WHERE cd.datasetname=(SELECT dataset_name FROM _cfg)
             AND c.%2$I=p.t_id
         )',
      r.parent_table, r.child_fk_col
    );
  END LOOP;
END $$;

-- 7) Saneamiento OID/FK CUC desde origen para evitar XTF inválido.
DO $$
DECLARE
  r record;
  v_expr text;
BEGIN
  -- Reparar t_ili_tid vacío en tablas copiadas (acotado al dataset destino).
  FOR r IN
    SELECT tf.table_name, c.data_type
    FROM _table_flags tf
    JOIN information_schema.columns c
      ON c.table_schema='b_asignaciones'
     AND c.table_name=tf.table_name
     AND c.column_name='t_ili_tid'
    WHERE EXISTS (
        SELECT 1
        FROM information_schema.columns cb
        WHERE cb.table_schema='b_asignaciones'
          AND cb.table_name=tf.table_name
          AND cb.column_name='t_basket'
      )
  LOOP
    IF r.data_type='uuid' THEN
      v_expr := format(
        'COALESCE(
           CASE
              WHEN NULLIF(BTRIM(l.t_ili_tid::text), '''') ~* ''^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$''
              THEN NULLIF(BTRIM(l.t_ili_tid::text), '''')::uuid
            END,
           (md5(CONCAT(
              random()::text,
              clock_timestamp()::text,
              ''_%1$s_'',
              b.t_id::text
            )))::uuid
          )',
        r.table_name
      );
    ELSE
      v_expr := format(
        'COALESCE(
           NULLIF(BTRIM(l.t_ili_tid::text), ''''),
           ((md5(CONCAT(
              random()::text,
              clock_timestamp()::text,
              ''_%1$s_'',
              b.t_id::text
            )))::uuid)::text
         )',
        r.table_name
      );
    END IF;

    EXECUTE format(
      'UPDATE b_asignaciones.%1$I b
       SET t_ili_tid = %2$s
       FROM leiva.%1$I l
       JOIN b_asignaciones.t_ili2db_basket bb ON TRUE
       JOIN b_asignaciones.t_ili2db_dataset dd ON dd.t_id=bb.dataset
       WHERE l.t_id=b.t_id
         AND bb.t_id=b.t_basket
         AND dd.datasetname=(SELECT dataset_name FROM _cfg)
         AND NULLIF(BTRIM(b.t_ili_tid::text), '''') IS NULL',
      r.table_name,
      v_expr
    );
  END LOOP;
END $$;

DO $$
DECLARE
  v_set text;
BEGIN
  -- Rehidratar referencias CUC desde leiva para evitar REF vacíos.
  SELECT string_agg(format('%1$I = l.%1$I', c.column_name), ', ')
  INTO v_set
  FROM information_schema.columns c
  WHERE c.table_schema='b_asignaciones'
    AND c.table_name='cuc_calificacion_unidadconstruccion'
    AND (
      c.column_name LIKE '%tipologia%'
      OR c.column_name LIKE '%calificacionconvencional%'
      OR c.column_name LIKE '%caracteristicasunidadconstruccion%'
    );

  IF v_set IS NOT NULL THEN
    EXECUTE format(
      'UPDATE b_asignaciones.cuc_calificacion_unidadconstruccion b
       SET %s
       FROM leiva.cuc_calificacion_unidadconstruccion l
       JOIN b_asignaciones.t_ili2db_basket bb ON TRUE
       JOIN b_asignaciones.t_ili2db_dataset dd ON dd.t_id=bb.dataset
       WHERE dd.datasetname=(SELECT dataset_name FROM _cfg)
         AND bb.t_id=b.t_basket
         AND l.t_id=b.t_id',
      v_set
    );
  END IF;
END $$;

DO $$
DECLARE
  v_tbl text;
  v_total bigint;
  v_oid_vacio bigint;
  v_has_tid boolean;
  r record;
  v_ref_faltante bigint;
BEGIN
  -- Validar OID/TID en tablas CUC que SI tienen t_ili_tid.
  -- Nota: cuc_calificacion_unidadconstruccion no tiene t_ili_tid en el modelo.
  FOREACH v_tbl IN ARRAY ARRAY[
    'cuc_calificacionconvencional',
    'cuc_tipologiaconstruccion',
    'cuc_tipologianoconvencional'
  ]
  LOOP
    SELECT EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema='b_asignaciones'
        AND table_name=v_tbl
        AND column_name='t_ili_tid'
    )
    INTO v_has_tid;

    IF NOT v_has_tid THEN
      CONTINUE;
    END IF;

    EXECUTE format(
      'SELECT COUNT(*),
              COUNT(*) FILTER (WHERE NULLIF(BTRIM(c.t_ili_tid::text), '''') IS NULL)
       FROM b_asignaciones.%I c
       JOIN b_asignaciones.t_ili2db_basket b ON b.t_id=c.t_basket
       JOIN b_asignaciones.t_ili2db_dataset d ON d.t_id=b.dataset
       WHERE d.datasetname=(SELECT dataset_name FROM _cfg)',
      v_tbl
    )
    INTO v_total, v_oid_vacio;

    IF v_total > 0 AND v_oid_vacio > 0 THEN
      RAISE EXCEPTION
        'Workspace invalido: %.t_ili_tid vacio en % de % filas (dataset=%).',
        v_tbl, v_oid_vacio, v_total, (SELECT dataset_name FROM _cfg);
    END IF;
  END LOOP;

  -- Validar referencias CUC dentro del mismo dataset.
  FOR r IN
    SELECT fk.child_fk_col, fk.parent_table
    FROM _fk fk
    WHERE fk.child_table='cuc_calificacion_unidadconstruccion'
      AND (
        fk.child_fk_col LIKE '%tipologia%'
        OR fk.child_fk_col LIKE '%calificacionconvencional%'
        OR fk.child_fk_col LIKE '%caracteristicasunidadconstruccion%'
      )
      AND EXISTS (
        SELECT 1
        FROM information_schema.columns cp
        WHERE cp.table_schema='b_asignaciones'
          AND cp.table_name=fk.parent_table
          AND cp.column_name='t_basket'
      )
  LOOP
    EXECUTE format(
      'SELECT COUNT(*)
       FROM b_asignaciones.cuc_calificacion_unidadconstruccion c
       JOIN b_asignaciones.t_ili2db_basket cb ON cb.t_id=c.t_basket
       JOIN b_asignaciones.t_ili2db_dataset cd ON cd.t_id=cb.dataset
       LEFT JOIN (
         SELECT p.t_id
         FROM b_asignaciones.%1$I p
         JOIN b_asignaciones.t_ili2db_basket pb ON pb.t_id=p.t_basket
         JOIN b_asignaciones.t_ili2db_dataset pd ON pd.t_id=pb.dataset
         WHERE pd.datasetname=(SELECT dataset_name FROM _cfg)
       ) p ON p.t_id=c.%2$I
       WHERE cd.datasetname=(SELECT dataset_name FROM _cfg)
         AND c.%2$I IS NOT NULL
         AND p.t_id IS NULL',
      r.parent_table, r.child_fk_col
    )
    INTO v_ref_faltante;

    IF v_ref_faltante > 0 THEN
      RAISE EXCEPTION
        'Workspace invalido: % fila(s) de cuc_calificacion_unidadconstruccion sin referencia valida en % (columna %, dataset=%).',
        v_ref_faltante, r.parent_table, r.child_fk_col, (SELECT dataset_name FROM _cfg);
    END IF;
  END LOOP;
END $$;


-- 8) Verificación final
SELECT p.t_id, p.numero_predial_nacional
FROM b_asignaciones.ilc_predio p
JOIN b_asignaciones.t_ili2db_basket b ON b.t_id=p.t_basket
JOIN b_asignaciones.t_ili2db_dataset d ON d.t_id=b.dataset
WHERE d.datasetname=(SELECT dataset_name FROM _cfg)
ORDER BY p.numero_predial_nacional;

SELECT 'cuc_calificacion_unidadconstruccion' AS tabla, count(*) AS filas
FROM b_asignaciones.cuc_calificacion_unidadconstruccion c
JOIN b_asignaciones.t_ili2db_basket b ON b.t_id=c.t_basket
JOIN b_asignaciones.t_ili2db_dataset d ON d.t_id=b.dataset
WHERE d.datasetname=(SELECT dataset_name FROM _cfg)
UNION ALL
SELECT 'cr_unidadconstruccion', count(*)
FROM b_asignaciones.cr_unidadconstruccion c
JOIN b_asignaciones.t_ili2db_basket b ON b.t_id=c.t_basket
JOIN b_asignaciones.t_ili2db_dataset d ON d.t_id=b.dataset
WHERE d.datasetname=(SELECT dataset_name FROM _cfg)
UNION ALL
SELECT 'ilc_caracteristicasunidadconstruccion', count(*)
FROM b_asignaciones.ilc_caracteristicasunidadconstruccion c
JOIN b_asignaciones.t_ili2db_basket b ON b.t_id=c.t_basket
JOIN b_asignaciones.t_ili2db_dataset d ON d.t_id=b.dataset
WHERE d.datasetname=(SELECT dataset_name FROM _cfg)
UNION ALL
SELECT 'cuc_calificacionconvencional', count(*)
FROM b_asignaciones.cuc_calificacionconvencional c
JOIN b_asignaciones.t_ili2db_basket b ON b.t_id=c.t_basket
JOIN b_asignaciones.t_ili2db_dataset d ON d.t_id=b.dataset
WHERE d.datasetname=(SELECT dataset_name FROM _cfg)
UNION ALL
SELECT 'cuc_tipologiaconstruccion', count(*)
FROM b_asignaciones.cuc_tipologiaconstruccion c
JOIN b_asignaciones.t_ili2db_basket b ON b.t_id=c.t_basket
JOIN b_asignaciones.t_ili2db_dataset d ON d.t_id=b.dataset
WHERE d.datasetname=(SELECT dataset_name FROM _cfg)
UNION ALL
SELECT 'cuc_tipologianoconvencional', count(*)
FROM b_asignaciones.cuc_tipologianoconvencional c
JOIN b_asignaciones.t_ili2db_basket b ON b.t_id=c.t_basket
JOIN b_asignaciones.t_ili2db_dataset d ON d.t_id=b.dataset
WHERE d.datasetname=(SELECT dataset_name FROM _cfg)
ORDER BY 1;

-- Hardening operativo para sincronizacion Arbimaps.
-- Ejecutar por bloques segun necesidad operativa.

-- 1) Datasets workspace huerfanos (sin asignacion activa).
SELECT d.t_id, d.datasetname
FROM b_asignaciones_arb.t_ili2db_dataset d
LEFT JOIN arbimaps_app.asignacion a
  ON BTRIM(a.work_datasetname::text) = BTRIM(d.datasetname::text)
 AND a.estado IS DISTINCT FROM 'CERRADA'
WHERE a.id IS NULL
ORDER BY d.datasetname;

-- 2) Baskets huerfanos (sin dataset).
SELECT b.t_id AS basket_id, b.dataset, b.t_ili_tid, b.topic
FROM b_asignaciones_arb.t_ili2db_basket b
LEFT JOIN b_asignaciones_arb.t_ili2db_dataset d ON d.t_id = b.dataset
WHERE d.t_id IS NULL
ORDER BY b.t_id;

-- 3) Cobertura por asignacion activa (desfase esperado vs workspace).
WITH activos AS (
  SELECT a.id AS asignacion_id,
         BTRIM(a.work_datasetname::text) AS work_datasetname,
         COUNT(*) FILTER (WHERE ap.activo IS DISTINCT FROM FALSE) AS expected_predios
  FROM arbimaps_app.asignacion a
  LEFT JOIN arbimaps_app.asignacion_predio ap ON ap.asignacion_id = a.id
  WHERE a.estado IS DISTINCT FROM 'CERRADA'
  GROUP BY a.id, BTRIM(a.work_datasetname::text)
),
coverage AS (
  SELECT a.asignacion_id,
         COUNT(DISTINCT BTRIM(p.numero_predial::text)) AS covered_predios
  FROM activos a
  LEFT JOIN b_asignaciones_arb.t_ili2db_dataset d ON BTRIM(d.datasetname::text) = a.work_datasetname
  LEFT JOIN b_asignaciones_arb.t_ili2db_basket b ON b.dataset = d.t_id
  LEFT JOIN b_asignaciones_arb.arb_predio p ON p.t_basket = b.t_id
  LEFT JOIN arbimaps_app.asignacion_predio ap
    ON ap.asignacion_id = a.asignacion_id
   AND ap.activo IS DISTINCT FROM FALSE
   AND BTRIM(ap.numero_predial_nacional::text) = BTRIM(p.numero_predial::text)
  WHERE ap.id IS NOT NULL
  GROUP BY a.asignacion_id
)
SELECT a.asignacion_id,
       a.work_datasetname,
       a.expected_predios,
       COALESCE(c.covered_predios, 0) AS covered_predios,
       a.expected_predios - COALESCE(c.covered_predios, 0) AS missing_predios
FROM activos a
LEFT JOIN coverage c ON c.asignacion_id = a.asignacion_id
WHERE a.expected_predios <> COALESCE(c.covered_predios, 0)
ORDER BY missing_predios DESC, a.asignacion_id DESC;

-- 4) Retornos con error para seguimiento.
SELECT id, asignacion_id, version, datasetname_retorno, estado, error_msg, creado_en
FROM arbimaps_app.asignacion_retorno
WHERE estado = 'ERROR'
ORDER BY id DESC;

-- 5) Deteccion de duplicidad por hash en retornos (si columna existe).
SELECT asignacion_id, archivo_sha256, COUNT(*) AS total
FROM arbimaps_app.asignacion_retorno
WHERE COALESCE(NULLIF(BTRIM(archivo_sha256), ''), '') <> ''
GROUP BY asignacion_id, archivo_sha256
HAVING COUNT(*) > 1
ORDER BY total DESC, asignacion_id;

-- 6) Limpieza controlada de dataset huerfano (descomentar y ajustar nombre).
-- SELECT * FROM b_asignaciones_arb.t_ili2db_dataset WHERE datasetname = '<dataset_huerfano>';
-- DELETE FROM b_asignaciones_arb.t_ili2db_basket
-- WHERE dataset IN (SELECT t_id FROM b_asignaciones_arb.t_ili2db_dataset WHERE datasetname = '<dataset_huerfano>');
-- DELETE FROM b_asignaciones_arb.t_ili2db_dataset WHERE datasetname = '<dataset_huerfano>';

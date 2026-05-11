-- Migracion minima para idempotencia y correlacion de retornos XTF.

ALTER TABLE IF EXISTS arbimaps_app.asignacion_retorno
ADD COLUMN IF NOT EXISTS archivo_sha256 TEXT;

ALTER TABLE IF EXISTS arbimaps_app.asignacion_retorno
ADD COLUMN IF NOT EXISTS correlation_id TEXT;

CREATE INDEX IF NOT EXISTS idx_asig_retorno_sha_asig
ON arbimaps_app.asignacion_retorno (asignacion_id, archivo_sha256);

CREATE INDEX IF NOT EXISTS idx_asig_retorno_correlation
ON arbimaps_app.asignacion_retorno (correlation_id);

-- fonbet_live_migration.sql
-- Adds minimal columns/indexes to support live mode without breaking existing prematch logic.
-- Safe to run multiple times (uses information_schema checks).

SET @db := DATABASE();

-- ===== fonbet_odds_history: add phase =====
SET @c := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema=@db AND table_name='fonbet_odds_history' AND column_name='phase'
);

SET @sql := IF(@c=0,
  'ALTER TABLE fonbet_odds_history ADD COLUMN phase VARCHAR(8) NULL',
  'SELECT "fonbet_odds_history.phase already exists"'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Backfill: treat NULL as prematch
UPDATE fonbet_odds_history SET phase='prematch' WHERE phase IS NULL;

-- Index for faster /tables
SET @i := (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=@db AND table_name='fonbet_odds_history' AND index_name='idx_fonbet_oh_event_phase_ts'
);
SET @sql := IF(@i=0,
  'CREATE INDEX idx_fonbet_oh_event_phase_ts ON fonbet_odds_history(event_id, phase, ts)',
  'SELECT "idx_fonbet_oh_event_phase_ts already exists"'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ===== fonbet_events: add is_live + last_seen_ts =====
SET @c1 := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema=@db AND table_name='fonbet_events' AND column_name='is_live'
);
SET @sql := IF(@c1=0,
  'ALTER TABLE fonbet_events ADD COLUMN is_live TINYINT(1) NOT NULL DEFAULT 0',
  'SELECT "fonbet_events.is_live already exists"'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c2 := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema=@db AND table_name='fonbet_events' AND column_name='last_seen_ts'
);
SET @sql := IF(@c2=0,
  'ALTER TABLE fonbet_events ADD COLUMN last_seen_ts BIGINT NULL',
  'SELECT "fonbet_events.last_seen_ts already exists"'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @i := (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=@db AND table_name='fonbet_events' AND index_name='idx_fonbet_events_live'
);
SET @sql := IF(@i=0,
  'CREATE INDEX idx_fonbet_events_live ON fonbet_events(is_live, last_seen_ts)',
  'SELECT "idx_fonbet_events_live already exists"'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SELECT "OK: live schema ready" AS status;

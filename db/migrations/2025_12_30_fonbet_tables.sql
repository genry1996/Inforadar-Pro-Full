-- Fonbet (separate tables)
CREATE TABLE IF NOT EXISTS fonbet_events (
  event_id      BIGINT PRIMARY KEY,
  sport_id      INT NULL,
  league_id     BIGINT NULL,
  league_name   VARCHAR(255) NULL,
  team1         VARCHAR(255) NULL,
  team2         VARCHAR(255) NULL,
  start_ts      INT NULL,
  state         VARCHAR(32) NULL,
  updated_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_fonbet_start_ts (start_ts),
  KEY idx_fonbet_league (league_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS fonbet_odds (
  event_id   BIGINT NOT NULL,
  factor_id  INT NOT NULL,
  odd        DECIMAL(10,3) NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (event_id, factor_id),
  KEY idx_fonbet_factor (factor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS fonbet_odds_history (
  id        BIGINT AUTO_INCREMENT PRIMARY KEY,
  event_id  BIGINT NOT NULL,
  factor_id INT NOT NULL,
  odd       DECIMAL(10,3) NULL,
  ts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_fonbet_hist_event_factor_ts (event_id, factor_id, ts),
  KEY idx_fonbet_hist_ts (ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS fonbet_factor_catalog (
  factor_id INT PRIMARY KEY,
  name      VARCHAR(255) NULL,
  raw_json  JSON NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

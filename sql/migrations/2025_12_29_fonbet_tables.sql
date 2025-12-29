CREATE TABLE IF NOT EXISTS fonbet_matches (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  event_id VARCHAR(64) NOT NULL,
  sport VARCHAR(32) NOT NULL,
  league VARCHAR(255),
  team1 VARCHAR(255),
  team2 VARCHAR(255),
  start_time DATETIME NULL,
  is_live TINYINT(1) NOT NULL DEFAULT 0,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_fonbet_event (event_id),
  KEY idx_fonbet_sport_live (sport, is_live),
  KEY idx_fonbet_start (start_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS fonbet_odds (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  event_id VARCHAR(64) NOT NULL,
  market_key VARCHAR(128) NOT NULL,
  outcome_key VARCHAR(128) NOT NULL,
  odd DECIMAL(10,4) NOT NULL,
  limit_value DECIMAL(18,4) NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_fonbet_odds (event_id, market_key, outcome_key),
  KEY idx_fonbet_odds_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS fonbet_odds_history (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  event_id VARCHAR(64) NOT NULL,
  market_key VARCHAR(128) NOT NULL,
  outcome_key VARCHAR(128) NOT NULL,
  odd DECIMAL(10,4) NOT NULL,
  limit_value DECIMAL(18,4) NULL,
  ts DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_fonbet_hist (event_id, market_key, outcome_key, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

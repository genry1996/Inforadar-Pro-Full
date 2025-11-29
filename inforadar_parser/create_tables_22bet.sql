-- SQL script to create necessary tables for the 22BET parser and anomaly detector
-- This script creates the markets, odds_history and anomalies tables. Adjust
-- table names or column types if your environment differs.

-- 1. Table: markets
--    Stores market configuration for each match. A unique index on
--    (match_id, market_type, market_param) ensures there is only one
--    record per market type per match.
CREATE TABLE IF NOT EXISTS markets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    match_id INT NOT NULL,
    market_type VARCHAR(50) NOT NULL,
    market_param VARCHAR(50) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_match_market (match_id, market_type, market_param),
    INDEX idx_market_match (match_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Table: odds_history
--    Stores snapshots of odds and limit values over time for each outcome
--    of a market. The collected_at timestamp defaults to the current time.
CREATE TABLE IF NOT EXISTS odds_history (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    match_id INT NOT NULL,
    market_id INT NOT NULL,
    bookmaker_id INT NOT NULL,
    market_type VARCHAR(50) NOT NULL,
    market_param VARCHAR(50) NOT NULL,
    outcome_code VARCHAR(50) NOT NULL,
    odds DECIMAL(10,3) NOT NULL,
    limit_value DECIMAL(12,2) DEFAULT NULL,
    is_live TINYINT(1) NOT NULL DEFAULT 0,
    collected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_oh_match_time (match_id, market_type, collected_at),
    INDEX idx_oh_market (market_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Table: anomalies
--    Records detected anomalies in odds or limits over a sliding window.
CREATE TABLE IF NOT EXISTS anomalies (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    match_id INT NOT NULL,
    bookmaker_id INT DEFAULT NULL,
    anomaly_type VARCHAR(100) NOT NULL,
    before_odd DECIMAL(10,3) DEFAULT NULL,
    after_odd DECIMAL(10,3) DEFAULT NULL,
    before_limit DECIMAL(12,2) DEFAULT NULL,
    after_limit DECIMAL(12,2) DEFAULT NULL,
    diff_pct DECIMAL(10,2) DEFAULT NULL,
    window_seconds INT DEFAULT NULL,
    comment VARCHAR(255) DEFAULT NULL,
    occurred_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_anom_match (match_id),
    INDEX idx_anom_type (anomaly_type, occurred_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- End of script

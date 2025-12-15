-- ═══════════════════════════════════════════════════════════════
-- 22BET ANOMALY PARSER - Database Schema
-- ═══════════════════════════════════════════════════════════════
-- MySQL 5.7+ compatible
-- Last updated: 2025-12-15

-- Create database if not exists
CREATE DATABASE IF NOT EXISTS inforadar;
USE inforadar;

-- ───────────────────────────────────────────────────────────────
-- TABLE: odds_22bet
-- Stores current and historical betting odds
-- ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS odds_22bet (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Unique identifier',
  event_name VARCHAR(255) NOT NULL COMMENT 'Match/Event name (e.g., Team A vs Team B)',
  sport VARCHAR(100) COMMENT 'Sport type (football, tennis, basketball, etc.)',
  league VARCHAR(100) COMMENT 'League/Tournament name',
  market_type VARCHAR(50) DEFAULT '1X2' COMMENT 'Market type (1X2, Total, Handicap, etc.)',
  odd_1 DECIMAL(6,3) COMMENT 'Odds for outcome 1 (Home team win or similar)',
  odd_x DECIMAL(6,3) COMMENT 'Odds for draw',
  odd_2 DECIMAL(6,3) COMMENT 'Odds for outcome 2 (Away team win or similar)',
  status VARCHAR(50) DEFAULT 'active' COMMENT 'Event status (active, frozen, removed)',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation time',
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update time',
  
  -- Indexes for better query performance
  UNIQUE KEY unique_event (event_name, market_type) COMMENT 'Prevent duplicates for same event+market',
  INDEX idx_sport (sport) COMMENT 'Speed up queries by sport',
  INDEX idx_league (league) COMMENT 'Speed up queries by league',
  INDEX idx_updated (updated_at) COMMENT 'Speed up time-range queries',
  INDEX idx_status (status) COMMENT 'Speed up queries by status',
  
  CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
) COMMENT='Current and historical betting odds from 22BET';

-- ───────────────────────────────────────────────────────────────
-- TABLE: anomalies_22bet
-- Stores detected betting anomalies
-- ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS anomalies_22bet (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Unique anomaly identifier',
  event_name VARCHAR(255) NOT NULL COMMENT 'Match/Event name where anomaly occurred',
  sport VARCHAR(100) COMMENT 'Sport type',
  league VARCHAR(100) COMMENT 'League name',
  anomaly_type VARCHAR(50) NOT NULL COMMENT 'Type of anomaly (ODDS_DROP, ODDS_SPIKE, LIMIT_CUT, etc.)',
  market_type VARCHAR(50) DEFAULT '1X2' COMMENT 'Market type affected',
  before_value DECIMAL(8,3) COMMENT 'Value before anomaly (e.g., old odds)',
  after_value DECIMAL(8,3) COMMENT 'Value after anomaly (e.g., new odds)',
  diff_pct DECIMAL(8,2) COMMENT 'Percentage change (negative for drops, positive for rises)',
  severity VARCHAR(50) DEFAULT 'medium' COMMENT 'Severity level (low, medium, high, critical)',
  status VARCHAR(50) DEFAULT 'new' COMMENT 'Status (new, confirmed, resolved, ignored)',
  comment TEXT COMMENT 'Additional details about the anomaly',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'When anomaly was detected',
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update time',
  
  -- Indexes for better query performance
  INDEX idx_type (anomaly_type) COMMENT 'Speed up queries by anomaly type',
  INDEX idx_sport (sport) COMMENT 'Speed up queries by sport',
  INDEX idx_league (league) COMMENT 'Speed up queries by league',
  INDEX idx_severity (severity) COMMENT 'Speed up queries by severity',
  INDEX idx_status (status) COMMENT 'Speed up queries by status',
  INDEX idx_created (created_at) COMMENT 'Speed up time-range queries',
  
  CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
) COMMENT='Detected betting anomalies (odds drops, limit cuts, etc.)';

-- ───────────────────────────────────────────────────────────────
-- TABLE: daily_stats
-- Stores daily statistics for reporting
-- ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS daily_stats (
  id INT AUTO_INCREMENT PRIMARY KEY,
  date_recorded DATE NOT NULL UNIQUE,
  total_events INT DEFAULT 0 COMMENT 'Total events processed',
  total_updates INT DEFAULT 0 COMMENT 'Total odds updates',
  anomalies_count INT DEFAULT 0 COMMENT 'Total anomalies detected',
  sports_covered INT DEFAULT 0 COMMENT 'Number of sports tracked',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  
  INDEX idx_date (date_recorded),
  CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
) COMMENT='Daily statistics for reporting and analytics';

-- ───────────────────────────────────────────────────────────────
-- VIEW: recent_anomalies
-- Quick access to recent anomalies (last 24 hours)
-- ───────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW recent_anomalies AS
SELECT 
  id,
  event_name,
  sport,
  league,
  anomaly_type,
  market_type,
  before_value,
  after_value,
  diff_pct,
  severity,
  status,
  created_at
FROM anomalies_22bet
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
ORDER BY created_at DESC;

-- ───────────────────────────────────────────────────────────────
-- VIEW: anomaly_summary
-- Summary statistics by anomaly type
-- ───────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW anomaly_summary AS
SELECT 
  anomaly_type,
  COUNT(*) as count,
  MIN(diff_pct) as min_change,
  MAX(diff_pct) as max_change,
  AVG(diff_pct) as avg_change,
  DATE(created_at) as date_recorded
FROM anomalies_22bet
GROUP BY anomaly_type, DATE(created_at)
ORDER BY date_recorded DESC, count DESC;

-- ───────────────────────────────────────────────────────────────
-- PROCEDURE: cleanup_old_data
-- Remove data older than specified days (default: 90 days)
-- Usage: CALL cleanup_old_data(90);
-- ───────────────────────────────────────────────────────────────

DELIMITER $$

CREATE PROCEDURE IF NOT EXISTS cleanup_old_data(IN days_to_keep INT)
BEGIN
  DECLARE affected_odds INT;
  DECLARE affected_anomalies INT;
  
  DELETE FROM odds_22bet 
  WHERE updated_at < DATE_SUB(NOW(), INTERVAL days_to_keep DAY);
  SET affected_odds = ROW_COUNT();
  
  DELETE FROM anomalies_22bet 
  WHERE created_at < DATE_SUB(NOW(), INTERVAL days_to_keep DAY);
  SET affected_anomalies = ROW_COUNT();
  
  SELECT CONCAT('Deleted ', affected_odds, ' odds records and ', affected_anomalies, ' anomaly records') as cleanup_result;
END$$

DELIMITER ;

-- ───────────────────────────────────────────────────────────────
-- Initial Data & Constraints
-- ───────────────────────────────────────────────────────────────

-- Set stricter SQL mode
SET SQL_MODE='STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO';

-- Add CHECK constraints for data validation
ALTER TABLE odds_22bet 
  ADD CONSTRAINT check_odds_positive CHECK (odd_1 > 0 AND odd_x > 0 AND odd_2 > 0);

ALTER TABLE anomalies_22bet 
  ADD CONSTRAINT check_values_positive CHECK (before_value > 0 AND after_value > 0),
  ADD CONSTRAINT check_valid_type CHECK (anomaly_type IN ('ODDS_DROP', 'ODDS_SPIKE', 'LIMIT_CUT', 'MARKET_REMOVED', 'MARKET_FROZEN'));

-- ═══════════════════════════════════════════════════════════════
-- Database Setup Complete
-- ═══════════════════════════════════════════════════════════════
-- 
-- Tables created:
--   1. odds_22bet        - Current/historical odds
--   2. anomalies_22bet   - Detected anomalies
--   3. daily_stats       - Daily statistics
--
-- Views created:
--   1. recent_anomalies  - Anomalies from last 24 hours
--   2. anomaly_summary   - Summary statistics by type
--
-- Procedures created:
--   1. cleanup_old_data() - Remove old records
--
-- Indexes created for optimal performance
-- Character set: UTF-8 (utf8mb4) for full Unicode support
--
-- To initialize parser with this schema:
-- mysql -u root -p inforadar < database/schema.sql
--
-- ═══════════════════════════════════════════════════════════════

-- История коэффициентов (тайм-серия)
CREATE TABLE IF NOT EXISTS odds_22bet_ticks (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  event_name VARCHAR(255) NOT NULL,
  sport VARCHAR(100),
  league VARCHAR(100),
  market_type VARCHAR(50) DEFAULT '1X2',
  odd_1 DECIMAL(6,3),
  odd_x DECIMAL(6,3),
  odd_2 DECIMAL(6,3),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_event_market_time (event_name, market_type, created_at),
  INDEX idx_created (created_at),
  INDEX idx_sport_league (sport, league)
);

-- Сердцебиение парсера
CREATE TABLE IF NOT EXISTS parser_heartbeat (
  id INT AUTO_INCREMENT PRIMARY KEY,
  parser_name VARCHAR(100) NOT NULL UNIQUE,
  last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Ускоряем дедуп аномалий
ALTER TABLE anomalies_22bet
  ADD INDEX idx_event_market_type_time (event_name, market_type, anomaly_type, created_at);

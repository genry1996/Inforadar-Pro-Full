ALTER TABLE odds_22bet_ticks
  ADD COLUMN market_key VARCHAR(100) NULL AFTER market_type;

CREATE INDEX idx_ticks_mkey_time
ON odds_22bet_ticks (market_key, created_at);

ALTER TABLE anomalies_22bet
  ADD COLUMN market_key VARCHAR(100) NULL AFTER market_type;

CREATE INDEX idx_anom_mkey_type_time
ON anomalies_22bet (market_key, anomaly_type, detected_at);

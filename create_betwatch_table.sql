-- Создание таблицы betwatch_signals для хранения сигналов
CREATE TABLE IF NOT EXISTS betwatch_signals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    signal_type VARCHAR(50) NOT NULL COMMENT 'Тип сигнала: sharp_drop, value_bet, unbalanced_flow, total_over_spike, late_game_spike',
    event_id VARCHAR(255) DEFAULT NULL COMMENT 'ID события из Betfair',
    event_name VARCHAR(255) NOT NULL COMMENT 'Название матча (Home - Away)',
    league VARCHAR(255) DEFAULT NULL COMMENT 'Название лиги',
    sport VARCHAR(50) DEFAULT 'football' COMMENT 'Вид спорта',
    
    -- Статус матча
    is_live TINYINT(1) DEFAULT 0 COMMENT '0 = prematch, 1 = live',
    match_time INT DEFAULT NULL COMMENT 'Минута матча (только для live)',
    
    -- Рынок и коэффициенты
    market_type VARCHAR(100) DEFAULT NULL COMMENT 'Тип рынка: 1, X, 2, Over, Under и т.д.',
    betfair_odd DECIMAL(10, 2) DEFAULT NULL COMMENT 'Коэффициент на Betfair',
    bookmaker_odd DECIMAL(10, 2) DEFAULT NULL COMMENT 'Коэффициент у букмекера',
    bookmaker_name VARCHAR(100) DEFAULT NULL COMMENT 'Название букмекера',
    
    -- Изменения коэффициентов
    old_odd DECIMAL(10, 2) DEFAULT NULL COMMENT 'Старый коэффициент',
    new_odd DECIMAL(10, 2) DEFAULT NULL COMMENT 'Новый коэффициент',
    odd_drop_percent DECIMAL(10, 2) DEFAULT NULL COMMENT 'Процент падения кэфа',
    
    -- Денежные потоки
    money_volume DECIMAL(15, 2) DEFAULT NULL COMMENT 'Объем денег (EUR)',
    total_market_volume DECIMAL(15, 2) DEFAULT NULL COMMENT 'Общий объем рынка',
    flow_percent DECIMAL(5, 2) DEFAULT NULL COMMENT 'Процент перекоса денежного потока',
    
    -- Метаданные
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Время обнаружения сигнала',
    comment TEXT DEFAULT NULL COMMENT 'Дополнительная информация',
    
    -- Индексы для быстрого поиска
    INDEX idx_signal_type (signal_type),
    INDEX idx_event_name (event_name),
    INDEX idx_league (league),
    INDEX idx_is_live (is_live),
    INDEX idx_detected_at (detected_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Таблица сигналов Betwatch Advanced Detector';

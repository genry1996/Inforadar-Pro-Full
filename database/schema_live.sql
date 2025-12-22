-- Таблица живых матчей
CREATE TABLE IF NOT EXISTS live_matches (
    id INT PRIMARY KEY AUTO_INCREMENT,
    event_id VARCHAR(100) UNIQUE,
    event_name VARCHAR(255),
    home_team VARCHAR(255),
    away_team VARCHAR(255),
    score VARCHAR(20),
    minute INT,
    status ENUM('prematch', 'live', 'halftime', 'finished') DEFAULT 'prematch',
    sport VARCHAR(100) DEFAULT 'Football',
    league VARCHAR(255),
    bookmaker VARCHAR(50) DEFAULT '22bet',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_event_id (event_id),
    INDEX idx_status (status),
    INDEX idx_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица событий матчей (голы, карточки)
CREATE TABLE IF NOT EXISTS match_events (
    id INT PRIMARY KEY AUTO_INCREMENT,
    event_id VARCHAR(100),
    event_type ENUM('goal', 'yellow', 'red', 'substitution', 'penalty'),
    minute INT,
    team ENUM('home', 'away'),
    player VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_event_id (event_id),
    INDEX idx_type (event_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Расширяем существующую таблицу odds_full_history
ALTER TABLE odds_full_history 
ADD COLUMN minute INT DEFAULT NULL,
ADD COLUMN score VARCHAR(20) DEFAULT NULL,
ADD COLUMN status VARCHAR(20) DEFAULT 'live',
ADD COLUMN handicap DECIMAL(4,2) DEFAULT NULL,
ADD COLUMN handicap_home DECIMAL(10,2) DEFAULT NULL,
ADD COLUMN handicap_away DECIMAL(10,2) DEFAULT NULL,
ADD COLUMN total DECIMAL(4,2) DEFAULT NULL,
ADD COLUMN `over` DECIMAL(10,2) DEFAULT NULL,
ADD COLUMN `under` DECIMAL(10,2) DEFAULT NULL;

-- Добавляем индексы
ALTER TABLE odds_full_history
ADD INDEX idx_minute (minute),
ADD INDEX idx_status (status);

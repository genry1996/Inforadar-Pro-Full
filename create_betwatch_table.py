#!/usr/bin/env python3
"""
Скрипт для создания таблицы betwatch_signals в MySQL
"""

import pymysql

DB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': 'ryban8991!',
    'database': 'inforadar',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
    'autocommit': True
}

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS betwatch_signals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    signal_type VARCHAR(50) NOT NULL COMMENT 'Тип сигнала: sharp_drop, value_bet, unbalanced_flow, total_over_spike, late_game_spike',
    event_id VARCHAR(255) DEFAULT NULL COMMENT 'ID события из Betfair',
    event_name VARCHAR(255) NOT NULL COMMENT 'Название матча (Home - Away)',
    league VARCHAR(255) DEFAULT NULL COMMENT 'Название лиги',
    sport VARCHAR(50) DEFAULT 'football' COMMENT 'Вид спорта',
    
    is_live TINYINT(1) DEFAULT 0 COMMENT '0 = prematch, 1 = live',
    match_time INT DEFAULT NULL COMMENT 'Минута матча (только для live)',
    
    market_type VARCHAR(100) DEFAULT NULL COMMENT 'Тип рынка: 1, X, 2, Over, Under и т.д.',
    betfair_odd DECIMAL(10, 2) DEFAULT NULL COMMENT 'Коэффициент на Betfair',
    bookmaker_odd DECIMAL(10, 2) DEFAULT NULL COMMENT 'Коэффициент у букмекера',
    bookmaker_name VARCHAR(100) DEFAULT NULL COMMENT 'Название букмекера',
    
    old_odd DECIMAL(10, 2) DEFAULT NULL COMMENT 'Старый коэффициент',
    new_odd DECIMAL(10, 2) DEFAULT NULL COMMENT 'Новый коэффициент',
    odd_drop_percent DECIMAL(10, 2) DEFAULT NULL COMMENT 'Процент падения кэфа',
    
    money_volume DECIMAL(15, 2) DEFAULT NULL COMMENT 'Объем денег (EUR)',
    total_market_volume DECIMAL(15, 2) DEFAULT NULL COMMENT 'Общий объем рынка',
    flow_percent DECIMAL(5, 2) DEFAULT NULL COMMENT 'Процент перекоса денежного потока',
    
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Время обнаружения сигнала',
    comment TEXT DEFAULT NULL COMMENT 'Дополнительная информация',
    
    INDEX idx_signal_type (signal_type),
    INDEX idx_event_name (event_name),
    INDEX idx_league (league),
    INDEX idx_is_live (is_live),
    INDEX idx_detected_at (detected_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Таблица сигналов Betwatch Advanced Detector'
"""

def create_betwatch_table():
    """Создает таблицу betwatch_signals"""
    
    try:
        print("=" * 70)
        print("🗄️  СОЗДАНИЕ ТАБЛИЦЫ BETWATCH_SIGNALS")
        print("=" * 70)
        print("\n🔌 Подключаюсь к MySQL...")
        
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("✅ Подключение успешно!")
        print("\n📋 Создаю таблицу betwatch_signals...")
        
        cursor.execute(CREATE_TABLE_SQL)
        
        print("✅ Таблица успешно создана!")
        
        # Проверяем структуру таблицы
        cursor.execute("DESCRIBE betwatch_signals")
        columns = cursor.fetchall()
        
        print(f"\n📊 Структура таблицы (всего {len(columns)} колонок):")
        print("-" * 70)
        for col in columns:
            print(f"  • {col['Field']:<25} {col['Type']:<20} {col['Null']}")
        print("-" * 70)
        
        cursor.close()
        conn.close()
        
        print("\n🎉 ВСЕ ГОТОВО!")
        print("📌 Теперь можно запускать:")
        print("   python insert_test_prematch.py")
        print("   python betwatch_advanced.py")
        
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    create_betwatch_table()

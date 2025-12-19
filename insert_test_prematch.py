#!/usr/bin/env python3
"""
Скрипт для добавления тестовых PREMATCH сигналов в БД
"""

import pymysql
from datetime import datetime

# Настройки для Docker MySQL
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

def insert_test_prematch_signals():
    """Добавляет тестовые Prematch сигналы"""
    
    try:
        print("🔌 Подключаюсь к MySQL...")
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        print("✅ Подключение успешно!")
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        print("\n💡 Попробуй установить cryptography:")
        print("   pip install cryptography")
        return
    
    test_signals = [
        {
            'signal_type': 'value_bet',
            'event_name': 'Arsenal - Chelsea',
            'league': 'Premier League',
            'sport': 'football',
            'is_live': 0,
            'market_type': '1',
            'betfair_odd': 2.45,
            'bookmaker_odd': 2.75,
            'bookmaker_name': '22bet',
            'money_volume': 15000,
            'flow_percent': 75.5,
            'detected_at': datetime.now()
        },
        {
            'signal_type': 'sharp_drop',
            'event_name': 'Real Madrid - Barcelona',
            'league': 'La Liga',
            'sport': 'football',
            'is_live': 0,
            'market_type': 'X',
            'betfair_odd': 3.50,
            'old_odd': 4.20,
            'new_odd': 3.50,
            'odd_drop_percent': -16.67,
            'money_volume': 12000,
            'flow_percent': 82.3,
            'detected_at': datetime.now()
        },
        {
            'signal_type': 'unbalanced_flow',
            'event_name': 'Bayern Munich - Borussia Dortmund',
            'league': 'Bundesliga',
            'sport': 'football',
            'is_live': 0,
            'market_type': '2',
            'betfair_odd': 2.80,
            'money_volume': 18000,
            'flow_percent': 88.1,
            'detected_at': datetime.now()
        },
        {
            'signal_type': 'value_bet',
            'event_name': 'PSG - Marseille',
            'league': 'Ligue 1',
            'sport': 'football',
            'is_live': 0,
            'market_type': '1',
            'betfair_odd': 1.95,
            'bookmaker_odd': 2.25,
            'bookmaker_name': 'Pinnacle',
            'money_volume': 22000,
            'flow_percent': 79.4,
            'detected_at': datetime.now()
        },
        {
            'signal_type': 'unbalanced_flow',
            'event_name': 'Manchester United - Liverpool',
            'league': 'Premier League',
            'sport': 'football',
            'is_live': 0,
            'market_type': 'Over 2.5',
            'betfair_odd': 1.85,
            'money_volume': 25000,
            'flow_percent': 91.2,
            'detected_at': datetime.now()
        },
        {
            'signal_type': 'sharp_drop',
            'event_name': 'Juventus - Inter',
            'league': 'Serie A',
            'sport': 'football',
            'is_live': 0,
            'market_type': '2',
            'betfair_odd': 2.90,
            'old_odd': 3.60,
            'new_odd': 2.90,
            'odd_drop_percent': -19.44,
            'money_volume': 16500,
            'flow_percent': 84.7,
            'detected_at': datetime.now()
        }
    ]
    
    sql = """
        INSERT INTO betwatch_signals (
            signal_type, event_name, league, sport, is_live, 
            market_type, betfair_odd, bookmaker_odd, bookmaker_name,
            old_odd, new_odd, odd_drop_percent,
            money_volume, flow_percent, detected_at
        ) VALUES (
            %(signal_type)s, %(event_name)s, %(league)s, %(sport)s, %(is_live)s,
            %(market_type)s, %(betfair_odd)s, %(bookmaker_odd)s, %(bookmaker_name)s,
            %(old_odd)s, %(new_odd)s, %(odd_drop_percent)s,
            %(money_volume)s, %(flow_percent)s, %(detected_at)s
        )
    """
    
    inserted = 0
    for signal in test_signals:
        # Заполняем пропущенные поля
        signal.setdefault('bookmaker_odd', None)
        signal.setdefault('bookmaker_name', None)
        signal.setdefault('old_odd', None)
        signal.setdefault('new_odd', None)
        signal.setdefault('odd_drop_percent', None)
        
        try:
            cursor.execute(sql, signal)
            inserted += 1
            print(f"✅ Добавлен: {signal['event_name']} ({signal['signal_type']})")
        except Exception as e:
            print(f"❌ Ошибка добавления: {e}")
    
    cursor.close()
    conn.close()
    
    print(f"\n🎉 Успешно добавлено {inserted} Prematch сигналов!")
    print(f"🌐 Обнови страницу: http://localhost:5000/betwatch")
    print(f"📅 Кликни на кнопку 'Прематч' чтобы увидеть их!")

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 Добавление тестовых Prematch сигналов в Betwatch")
    print("=" * 60)
    insert_test_prematch_signals()

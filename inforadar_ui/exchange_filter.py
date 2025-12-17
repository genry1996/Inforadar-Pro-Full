# ===============================================
# 🏀 BETFAIR EXCHANGE FILTER WITH ANOMALY DETECTION
# Залив денег (spike volume) + падение коэфф
# ===============================================

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('exchange_filter.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ✅ ВСЕ СПОРТЫ
SPORTS = [
    {"name": "Football", "slug": "football", "id": "1"},
    {"name": "Basketball", "slug": "basketball", "id": "3"},
    {"name": "Tennis", "slug": "tennis", "id": "2"},
    {"name": "Esports", "slug": "esports", "id": "27454292"},
    {"name": "Futsal", "slug": "futsal", "id": "20716736"},
    {"name": "Volleyball", "slug": "volleyball", "id": "26420519"},
]

# ✅ ФИЛЬТРЫ С КОРИДОРАМИ
FILTER_CONFIG = {
    # Коридор для коэффициентов
    "coefficient_range": {
        "min": 1.01,
        "max": 50.0,
        "description": "Диапазон коэффициентов"
    },
    
    # Коридор для минимума объема ставок до аномалии
    "min_base_volume": {
        "min": 100,  # €
        "max": 100000,
        "description": "Базовый объем до аномалии"
    },
    
    # ⚠️ КРИТИЧЕСКОЕ: Коридор для скачка объема (залив денег)
    "volume_spike_percent": {
        "min": 50,  # Минимум 50% увеличение
        "max": 1000,  # Максимум 1000% (10x)
        "description": "Процент увеличения объема = АНОМАЛИЯ ЗАЛИВА"
    },
    
    # ⚠️ КРИТИЧЕСКОЕ: Падение коэффициента (одновременно со сливом)
    "coefficient_drop_percent": {
        "min": 2.0,  # Минимум 2% падение
        "max": 100.0,  # Максимум 100% падение
        "description": "Процент падения коэффициента"
    },
    
    # Временное окно для обнаружения аномалии
    "time_window_seconds": {
        "value": 60,  # Проверяем события за последние 60 сек
        "description": "Окно времени для обнаружения spike + drop"
    },
    
    # Минимальная ликвидность для срабатывания
    "min_liquidity": {
        "min": 50,  # €
        "max": 1000000,
        "description": "Минимальная ликвидность для детекции"
    },
    
    # Минимальный матч-объем (реальные деньги)
    "min_matched_amount": {
        "value": 10,  # € - минимум 10€ чтобы считать значимым
        "description": "Минимум реально ставленных денег"
    }
}

# ✅ ТИПЫ АНОМАЛИЙ ДЛЯ БИРЖИ
ANOMALY_TYPES_EXCHANGE = {
    "VOLUME_SPIKE": {
        "name": "Залив денег (Volume Spike)",
        "description": "Резкий скачок объема ставок +50-1000%",
        "severity": "HIGH"
    },
    "ODDS_DROP_WITH_SPIKE": {
        "name": "Падение коэфф со сливом (Odds Drop + Volume)",
        "description": "Падение коэффициента + одновременный залив денег",
        "severity": "CRITICAL"
    },
    "SUSPICIOUS_ARBITRAGE": {
        "name": "Подозрительный арбитраж",
        "description": "Резкое расхождение коэффициентов между букмекерами",
        "severity": "HIGH"
    },
    "MARKET_SUSPENSION": {
        "name": "Приостановка рынка",
        "description": "Рынок временно перестал принимать ставки",
        "severity": "MEDIUM"
    },
    "ODDS_FLASH": {
        "name": "Flash коэффициент",
        "description": "Очень короткий аномальный коэффициент (< 5 сек)",
        "severity": "MEDIUM"
    }
}

class ExchangeAnomalyDetector:
    """Детектор аномалий на бирже Betfair"""
    
    def __init__(self):
        self.db_connection = self.get_db_connection()
        self.previous_state = {}  # Хранит предыдущие значения
        self.logger = logger
        
    def get_db_connection(self):
        """Подключение к БД"""
        return mysql.connector.connect(
            host=os.getenv("MYSQL_HOST", "localhost"),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=os.getenv("MYSQL_DB", "inforadar"),
            autocommit=True
        )
    
    def detect_volume_spike(self, market_data: Dict) -> Optional[Dict]:
        """
        🚨 Детектируем скачок объема (залив денег)
        
        Args:
            market_data: {
                'market_id': str,
                'selection_id': int,
                'matched_volume': float,  # Текущий объем
                'available_volume': float,  # Доступный объем
                'back_price': float,
                'lay_price': float,
                'timestamp': datetime
            }
        
        Returns:
            Аномалия если найдена, иначе None
        """
        
        key = f"{market_data['market_id']}_{market_data['selection_id']}"
        current_matched = market_data.get('matched_volume', 0)
        
        # Если это первое наблюдение
        if key not in self.previous_state:
            self.previous_state[key] = {
                'matched_volume': current_matched,
                'timestamp': market_data['timestamp'],
                'back_price': market_data.get('back_price', 0),
                'observations': 1
            }
            return None
        
        prev_state = self.previous_state[key]
        prev_matched = prev_state['matched_volume']
        prev_price = prev_state['back_price']
        
        # Пропускаем если объем 0
        if prev_matched <= 0 or current_matched <= 0:
            self.previous_state[key] = {
                'matched_volume': current_matched,
                'timestamp': market_data['timestamp'],
                'back_price': market_data.get('back_price', 0),
                'observations': prev_state.get('observations', 1) + 1
            }
            return None
        
        # Считаем процент увеличения объема
        volume_change_pct = ((current_matched - prev_matched) / prev_matched) * 100
        
        # Считаем процент падения коэффициента
        current_price = market_data.get('back_price', 0)
        if prev_price > 0 and current_price > 0:
            price_change_pct = ((prev_price - current_price) / prev_price) * 100
        else:
            price_change_pct = 0
        
        # Проверяем критерии аномалии
        cfg = FILTER_CONFIG
        
        is_volume_spike = (
            volume_change_pct >= cfg['volume_spike_percent']['min'] and
            volume_change_pct <= cfg['volume_spike_percent']['max']
        )
        
        is_odds_drop = (
            price_change_pct >= cfg['coefficient_drop_percent']['min'] and
            price_change_pct <= cfg['coefficient_drop_percent']['max']
        )
        
        # ⚠️ КРИТИЧЕСКАЯ АНОМАЛИЯ: Залив денег + падение коэфф одновременно
        if is_volume_spike and is_odds_drop:
            anomaly = {
                'market_id': market_data['market_id'],
                'selection_id': market_data['selection_id'],
                'anomaly_type': 'ODDS_DROP_WITH_SPIKE',
                'severity': 'CRITICAL',
                'volume_before': prev_matched,
                'volume_current': current_matched,
                'volume_change_pct': round(volume_change_pct, 2),
                'price_before': round(prev_price, 3),
                'price_current': round(current_price, 3),
                'price_change_pct': round(price_change_pct, 2),
                'timestamp': market_data['timestamp'],
                'details': f"Залив {volume_change_pct:.1f}% + падение коэфф {price_change_pct:.1f}%"
            }
            
            self.logger.warning(
                f"🚨 АНОМАЛИЯ! {anomaly['anomaly_type']}: "
                f"Объем {volume_change_pct:.1f}%, Коэфф падал на {price_change_pct:.1f}%"
            )
            return anomaly
        
        # Просто залив денег (без падения коэфф)
        elif is_volume_spike:
            anomaly = {
                'market_id': market_data['market_id'],
                'selection_id': market_data['selection_id'],
                'anomaly_type': 'VOLUME_SPIKE',
                'severity': 'HIGH',
                'volume_before': prev_matched,
                'volume_current': current_matched,
                'volume_change_pct': round(volume_change_pct, 2),
                'timestamp': market_data['timestamp'],
                'details': f"Залив денег {volume_change_pct:.1f}%"
            }
            
            self.logger.info(
                f"📊 SPIKE: Объем скакнул на {volume_change_pct:.1f}%"
            )
            return anomaly
        
        # Просто падение коэффициента
        elif is_odds_drop:
            anomaly = {
                'market_id': market_data['market_id'],
                'selection_id': market_data['selection_id'],
                'anomaly_type': 'ODDS_DROP_WITH_SPIKE',  # Все равно критичное
                'severity': 'MEDIUM',
                'price_before': round(prev_price, 3),
                'price_current': round(current_price, 3),
                'price_change_pct': round(price_change_pct, 2),
                'timestamp': market_data['timestamp'],
                'details': f"Падение коэфф {price_change_pct:.1f}%"
            }
            return anomaly
        
        # Обновляем состояние
        self.previous_state[key] = {
            'matched_volume': current_matched,
            'timestamp': market_data['timestamp'],
            'back_price': current_price,
            'observations': prev_state.get('observations', 1) + 1
        }
        
        return None
    
    def save_anomaly_to_db(self, anomaly: Dict, sport: str) -> bool:
        """Сохраняем аномалию в БД"""
        try:
            cursor = self.db_connection.cursor()
            
            sql = """
            INSERT INTO exchange_anomalies 
            (market_id, selection_id, sport, anomaly_type, severity, 
             volume_before, volume_current, volume_change_pct,
             price_before, price_current, price_change_pct,
             details, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            cursor.execute(sql, (
                anomaly['market_id'],
                anomaly['selection_id'],
                sport,
                anomaly['anomaly_type'],
                anomaly['severity'],
                anomaly.get('volume_before', 0),
                anomaly.get('volume_current', 0),
                anomaly.get('volume_change_pct', 0),
                anomaly.get('price_before', 0),
                anomaly.get('price_current', 0),
                anomaly.get('price_change_pct', 0),
                anomaly['details'],
                anomaly['timestamp']
            ))
            
            cursor.close()
            self.logger.info(f"✅ Аномалия сохранена в БД: {anomaly['anomaly_type']}")
            return True
        
        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения аномалии: {e}")
            return False

# ✅ Пример использования фильтра
if __name__ == "__main__":
    detector = ExchangeAnomalyDetector()
    
    # Симуляция данных с биржи
    test_market = {
        'market_id': 'MARKET_123456',
        'selection_id': 789,
        'matched_volume': 5000,  # €
        'available_volume': 10000,
        'back_price': 2.50,
        'lay_price': 2.54,
        'timestamp': datetime.now()
    }
    
    # Первое наблюдение (просто сохраняем базовое состояние)
    print("📊 Первое наблюдение (базовое состояние)...")
    result = detector.detect_volume_spike(test_market)
    print(f"Результат: {result}\n")
    
    # Второе наблюдение - залив денег + падение коэфф
    import time
    time.sleep(1)
    
    test_market['matched_volume'] = 12000  # +140% от 5000
    test_market['back_price'] = 2.15  # Падение с 2.50 на 2.15 = 14% падение
    test_market['timestamp'] = datetime.now()
    
    print("🚨 Второе наблюдение (залив денег + падение коэфф)...")
    result = detector.detect_volume_spike(test_market)
    if result:
        print(f"✅ ОБНАРУЖЕНА АНОМАЛИЯ!")
        print(f"  Тип: {result['anomaly_type']}")
        print(f"  Серьезность: {result['severity']}")
        print(f"  Залив: {result['volume_change_pct']}%")
        print(f"  Падение коэфф: {result['price_change_pct']}%")
        print(f"  Детали: {result['details']}")

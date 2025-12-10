# =====================================================
# PINNACLE PARSER - Самый простой для начала
# =====================================================
# API документация: https://www.pinnacle.com/en/api/sports/
# Не нужна регистрация, не нужны ключи, просто работает!

import asyncio
import aiohttp
import json
from datetime import datetime
from typing import List, Dict, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PinnacleParser:
    """
    Парсер для Pinnacle Sports API
    """
    BASE_URL = "https://api.pinnacle.com/v3"
    
    # ID спортов
    SPORTS = {
        'SOCCER': 1,
        'BASKETBALL': 12,
        'TENNIS': 33,
        'HOCKEY': 4,
        'BASEBALL': 16,
        'AMERICAN_FOOTBALL': 15,
        'CRICKET': 13,
    }
    
    def __init__(self):
        self.bookmaker_id = 'pinnacle'
        self.bookmaker_name = 'Pinnacle'
    
    async def get_sports(self) -> List[Dict]:
        """Получить список доступных спортов"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.BASE_URL}/sports") as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.error(f"Failed to fetch sports: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"Error getting sports: {e}")
            return []
    
    async def get_odds(self, sport_id: int = 1) -> Dict[str, Any]:
        """
        Получить коэффициенты по спорту
        
        Args:
            sport_id: ID спорта (1=football, 12=basketball и т.д.)
        
        Returns:
            Словарь с событиями и коэффициентами
        """
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    'sportId': sport_id,
                    'oddsFormat': 'decimal',  # Decimal формат (европейский)
                    'since': 0  # или timestamp последнего запроса для инкрементального обновления
                }
                
                async with session.get(
                    f"{self.BASE_URL}/odds",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.error(f"Failed to fetch odds: {resp.status}")
                        return {}
        except Exception as e:
            logger.error(f"Error getting odds: {e}")
            return {}
    
    async def parse_event(self, event: Dict) -> Dict:
        """
        Парсить одно событие
        
        Возвращает структурированные данные
        """
        try:
            event_data = {
                'external_id': str(event.get('id')),
                'bookmaker_id': self.bookmaker_id,
                'bookmaker_name': self.bookmaker_name,
                'home_team': event.get('homeTeam', 'N/A'),
                'away_team': event.get('awayTeam', 'N/A'),
                'league': event.get('league', 'N/A'),
                'sport_id': event.get('sport_id', 'unknown'),
                'start_time': event.get('starts', 'N/A'),
                'status': 'prematch',  # Pinnacle в основном дает прематч
                'odds': {},
                'timestamp': datetime.utcnow().isoformat(),
            }
            
            # Парсим коэффициенты
            prices = event.get('prices', [])
            if prices:
                for price in prices:
                    # Основной рынок (1X2)
                    if '1H' in price or 'X' in price or '2H' in price:
                        event_data['odds']['1x2'] = {
                            'home': price.get('1H'),
                            'draw': price.get('X'),
                            'away': price.get('2H'),
                        }
                    
                    # Тотал голов
                    if 'OU' in price:
                        event_data['odds']['totals'] = {
                            'over': price.get('OU', {}).get('Over'),
                            'under': price.get('OU', {}).get('Under'),
                        }
                    
                    # Фора
                    if 'Spread' in price:
                        event_data['odds']['spreads'] = {
                            'home': price.get('Spread', {}).get('Home'),
                            'away': price.get('Spread', {}).get('Away'),
                        }
            
            return event_data
        except Exception as e:
            logger.error(f"Error parsing event: {e}")
            return None
    
    async def parse_all_events(self, sport_id: int = 1) -> List[Dict]:
        """
        Получить и распарсить все события для спорта
        """
        logger.info(f"Fetching Pinnacle odds for sport_id={sport_id}")
        odds_data = await self.get_odds(sport_id)
        
        if not odds_data or 'events' not in odds_data:
            logger.warning("No events found")
            return []
        
        events = odds_data.get('events', [])
        parsed_events = []
        
        for event in events:
            parsed = await self.parse_event(event)
            if parsed:
                parsed_events.append(parsed)
        
        logger.info(f"Parsed {len(parsed_events)} events from Pinnacle")
        return parsed_events
    
    async def detect_anomalies(self, current_odds: Dict, previous_odds: Dict = None) -> List[Dict]:
        """
        Обнаружить аномалии в коэффициентах
        """
        anomalies = []
        
        if not previous_odds:
            return anomalies  # Нет чем сравнивать
        
        # Проверка резкого падения коэффициентов
        try:
            current_1x2 = current_odds.get('odds', {}).get('1x2', {})
            prev_1x2 = previous_odds.get('odds', {}).get('1x2', {})
            
            for key in ['home', 'draw', 'away']:
                current_odd = current_1x2.get(key)
                prev_odd = prev_1x2.get(key)
                
                if current_odd and prev_odd:
                    change_percent = ((current_odd - prev_odd) / prev_odd) * 100
                    
                    # Аномалия: падение больше чем на 5%
                    if change_percent < -5:
                        anomalies.append({
                            'type': 'sharp_drop',
                            'event_id': current_odds['external_id'],
                            'market': 'home' if key == 'home' else ('draw' if key == 'draw' else 'away'),
                            'old_value': prev_odd,
                            'new_value': current_odd,
                            'change_percent': change_percent,
                            'timestamp': datetime.utcnow().isoformat(),
                        })
                    
                    # Аномалия: рост больше чем на 5%
                    elif change_percent > 5:
                        anomalies.append({
                            'type': 'sharp_rise',
                            'event_id': current_odds['external_id'],
                            'market': key,
                            'old_value': prev_odd,
                            'new_value': current_odd,
                            'change_percent': change_percent,
                            'timestamp': datetime.utcnow().isoformat(),
                        })
        
        except Exception as e:
            logger.error(f"Error detecting anomalies: {e}")
        
        return anomalies


# =====================================================
# ПРИМЕР ИСПОЛЬЗОВАНИЯ
# =====================================================

async def main():
    parser = PinnacleParser()
    
    # 1. Получить все спорты
    print("\n" + "="*60)
    print("1️⃣ ПОЛУЧЕНИЕ СПОРТОВ")
    print("="*60)
    sports = await parser.get_sports()
    print(f"✅ Получено {len(sports)} спортов")
    for sport in sports[:3]:
        print(f"   {sport.get('id'):2d}: {sport.get('name')}")
    
    # 2. Получить события футбола
    print("\n" + "="*60)
    print("2️⃣ ПОЛУЧЕНИЕ СОБЫТИЙ (ФУТБОЛ)")
    print("="*60)
    events = await parser.parse_all_events(sport_id=1)
    print(f"✅ Получено {len(events)} событий")
    
    if events:
        event = events[0]
        print(f"\n   Матч: {event['home_team']} vs {event['away_team']}")
        print(f"   Лига: {event['league']}")
        print(f"   Коэффициенты: {event['odds']}")
    
    # 3. Получить события баскетбола
    print("\n" + "="*60)
    print("3️⃣ ПОЛУЧЕНИЕ СОБЫТИЙ (БАСКЕТБОЛ)")
    print("="*60)
    events_nba = await parser.parse_all_events(sport_id=12)
    print(f"✅ Получено {len(events_nba)} событий")


if __name__ == "__main__":
    # Для запуска: python pinnacle_parser.py
    asyncio.run(main())

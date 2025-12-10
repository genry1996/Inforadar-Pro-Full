import asyncio
import logging
import json
from datetime import datetime
from playwright.async_api import async_playwright
from typing import List, Dict, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')

class BetWatchParser:
    """
    Production-ready Betwatch.fr parser using API endpoints
    Парсит матчи с коэффициентами и объёмом ставок
    """
    
    BASE_URL = "https://betwatch.fr"
    
    def __init__(self):
        self.page = None
        self.browser = None
        self.logger = logging.getLogger(__name__)
    
    async def init(self):
        """Инициализация браузера"""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page()
        self.page.set_default_timeout(60000)
    
    async def fetch_football_matches(self, date: str = None, live_only: bool = False) -> List[Dict]:
        """
        Получает футбольные матчи с коэффициентами
        
        Args:
            date: дата в формате YYYY-MM-DD (default: сегодня)
            live_only: только LIVE матчи
        
        Returns:
            List матчей с данными
        """
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        
        url = f"{self.BASE_URL}/football/getMoney"
        params = {
            'live_only': 'true' if live_only else 'false',
            'prematch_only': 'false',
            'finished_only': 'false',
            'favorite_only': 'false',
            'utc': '0',
            'step': '1',
            'date': date,
            'order_by_time': 'false',
            'not_countries': '',
            'not_leagues': ''
        }
        
        full_url = url + '?' + '&'.join(f"{k}={v}" for k, v in params.items())
        
        try:
            self.logger.info(f"📡 Fetching matches from {date}...")
            response = await self.page.goto(full_url)
            
            if response and response.status == 200:
                data = await self.page.json()
                matches = self._parse_matches(data.get('data', []))
                self.logger.info(f"✅ Found {len(matches)} matches")
                return matches
            else:
                self.logger.error(f"❌ Failed to fetch: {response.status if response else 'No response'}")
                return []
        
        except Exception as e:
            self.logger.error(f"❌ Error: {str(e)}")
            return []
    
    async def fetch_leagues(self) -> Dict[str, Dict]:
        """Получает все доступные лиги"""
        try:
            url = f"{self.BASE_URL}/football/leagues"
            response = await self.page.goto(url)
            
            if response and response.status == 200:
                leagues = await self.page.json()
                self.logger.info(f"✅ Found {len(leagues)} countries with leagues")
                return leagues
            return {}
        except Exception as e:
            self.logger.error(f"❌ Error fetching leagues: {str(e)}")
            return {}
    
    def _parse_matches(self, data: List) -> List[Dict]:
        """
        Парсит raw API данные в удобный формат
        
        Data structure:
        {
            "m": "Team1 - Team2",           # матч
            "c": "Country",                  # страна
            "cn": "Country",                 # страна (англ)
            "ce": "2025-12-10T17:45:00Z",   # время начала
            "li": 228,                       # league ID
            "ln": "League Name",             # название лиги
            "l": 1,                          # тип (1=Match Odds)
            "h": 0,                          # home team ID
            "n": "Match Odds",               # название события
            "e": 35004051,                   # event ID
            "iid": 251082599,                # some ID
            "v": 2880175.93,                 # объём ставок
            "vm": 2133333,                   # something
            "i": [                           # odds [id, amount, odds1, odds2]
                ["1", 2461576, 1.4, 2.48],   # [win/home, volume, coefficient, ...]
                ["X", 104066, 4.5, 4.4],     # [draw]
                ["2", 314532, 16.0, 3.45]    # [away/2]
            ],
            "ht": 10583858,                  # home team total
            "at": 52494689,                  # away team total
            "htn": "Team1",                  # home team name
            "atn": "Team2"                   # away team name
        }
        """
        matches = []
        
        for item in data:
            try:
                # Парсим коэффициенты
                odds = {}
                for odd in item.get('i', []):
                    if len(odd) >= 4:
                        key = odd[0]  # "1", "X", "2"
                        odds[key] = {
                            'volume': odd[1],
                            'coefficient': odd[2],
                            'value': odd[3] if len(odd) > 3 else None
                        }
                
                match = {
                    'name': item.get('m', ''),
                    'teams': {
                        'home': item.get('htn', ''),
                        'away': item.get('atn', '')
                    },
                    'league': item.get('ln', ''),
                    'country': item.get('c', ''),
                    'start_time': item.get('ce', ''),
                    'event_id': item.get('e', ''),
                    'league_id': item.get('li', ''),
                    'odds': odds,
                    'total_volume': item.get('v', 0),
                    'home_total_volume': item.get('ht', 0),
                    'away_total_volume': item.get('at', 0),
                }
                
                matches.append(match)
            
            except Exception as e:
                self.logger.warning(f"⚠️ Error parsing match: {str(e)}")
                continue
        
        return matches
    
    async def detect_anomalies(self, matches: List[Dict]) -> List[Dict]:
        """
        Детектирует аномалии в коэффициентах
        
        Аномалия = резкое движение коэффициента/объёма
        """
        anomalies = []
        
        for match in matches:
            odds = match['odds']
            
            # Проверяем дисбаланс ставок
            home_vol = match['home_total_volume']
            away_vol = match['away_total_volume']
            
            if home_vol > 0 and away_vol > 0:
                ratio = max(home_vol, away_vol) / min(home_vol, away_vol)
                
                # Если дисбаланс > 3:1, это аномалия
                if ratio > 3:
                    anomalies.append({
                        'match': match['name'],
                        'type': 'volume_imbalance',
                        'ratio': round(ratio, 2),
                        'data': match
                    })
            
            # Проверяем коэффициенты (low odds = high probability)
            if '1' in odds and odds['1']['coefficient'] < 1.2:
                anomalies.append({
                    'match': match['name'],
                    'type': 'very_low_odds',
                    'odds': odds['1']['coefficient'],
                    'data': match
                })
        
        return anomalies
    
    async def close(self):
        """Закрывает браузер"""
        if self.browser:
            await self.browser.close()


async def main():
    """Пример использования"""
    parser = BetWatchParser()
    await parser.init()
    
    try:
        # Получаем матчи
        matches = await parser.fetch_football_matches(live_only=False)
        
        # Выводим результаты
        logging.info("\n" + "="*80)
        logging.info("📊 MATCHES FOUND:")
        logging.info("="*80)
        
        for match in matches[:5]:  # Первые 5
            logging.info(f"\n⚽ {match['name']}")
            logging.info(f"   League: {match['league']}")
            logging.info(f"   Time: {match['start_time']}")
            logging.info(f"   Odds: {match['odds']}")
            logging.info(f"   Total Volume: {match['total_volume']}")
        
        # Детектим аномалии
        anomalies = await parser.detect_anomalies(matches)
        
        if anomalies:
            logging.info("\n" + "="*80)
            logging.info("⚠️ ANOMALIES DETECTED:")
            logging.info("="*80)
            
            for anomaly in anomalies:
                logging.info(f"\n{anomaly['type'].upper()}: {anomaly['match']}")
                logging.info(f"   Details: {anomaly}")
    
    finally:
        await parser.close()


if __name__ == "__main__":
    asyncio.run(main())

# -*- coding: utf-8 -*-
"""
22bet PREMATCH Parser - API Direct Approach
D:\Inforadar_Pro\parsers\playwright_22bet\prematch_parser.py

Используем API 22bet напрямую вместо HTML парсинга
Интервал: 60 сек
"""
import asyncio
import os
import hashlib
import aiohttp
import json
from datetime import datetime, timedelta
import pymysql
import time

# ===== КОНФИГУРАЦИЯ =====
DB_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'localhost'),
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', 'ryban8991!'),
    'database': os.getenv('MYSQL_DB', 'inforadar'),
    'cursorclass': pymysql.cursors.DictCursor
}

# 22bet API endpoints
API_BASE = 'https://22bet.com/api/line/list'
API_PARAMS = {
    'lang': 'en',
    'sport_id': 1,  # Football
    'count': 500
}

PROXY_URL = 'http://14ab48c9d85c1:5d234f6517@213.137.91.35:12323'

UPDATE_INTERVAL = 60  # 60 сек
BOOKMAKER = '22bet'
HOURS_AHEAD = 12  # 🔥 12 часов вперёд!


class PrematchParser:
    def __init__(self):
        self.conn = None
        self.last_saved = {}
        self.session = None

    def connect_db(self):
        try:
            self.conn = pymysql.connect(**DB_CONFIG)
            print(f"✅ Connected to MySQL: {DB_CONFIG['host']}")
            return True
        except Exception as e:
            print(f"❌ DB Connection Error: {e}")
            return False

    def generate_unique_key(self, home_team, away_team):
        key_str = f"{home_team}#{away_team}".lower()
        return hashlib.md5(key_str.encode()).hexdigest()[:12]

    async def fetch_prematch_via_api(self):
        """
        🚀 Получаем prematch матчи напрямую через API
        """
        try:
            connector = aiohttp.TCPConnector(ssl=False)
            timeout = aiohttp.ClientTimeout(total=30)

            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'application/json',
                    'Referer': 'https://22bet.com/'
                }

                async with session.get(
                    API_BASE,
                    params=API_PARAMS,
                    headers=headers,
                    proxy=PROXY_URL
                ) as response:
                    if response.status != 200:
                        print(f"❌ API returned status {response.status}")
                        return []

                    data = await response.json()
                    return self.parse_api_response(data)

        except Exception as e:
            print(f"❌ API Error: {e}")
            return []

    def parse_api_response(self, data):
        """
        Парсим ответ API
        """
        try:
            if not data or 'results' not in data:
                print("⚠️ No results in API response")
                return []

            matches_data = []
            now = datetime.now()
            cutoff_time = now + timedelta(hours=HOURS_AHEAD)

            for item in data['results']:
                try:
                    # Пропускаем live матчи
                    if item.get('is_live', False):
                        continue

                    # Команды
                    home_team = item.get('home_team', {}).get('name', '').strip()
                    away_team = item.get('away_team', {}).get('name', '').strip()

                    if not home_team or not away_team:
                        continue

                    # Время матча
                    start_time = item.get('start_time')
                    if not start_time:
                        continue

                    try:
                        match_time = datetime.fromtimestamp(start_time)
                        if match_time > cutoff_time or match_time < now:
                            continue
                    except:
                        continue

                    # Коэффициенты 1X2
                    markets = item.get('markets', {})
                    main_market = markets.get('1X2', {})

                    home_odd = main_market.get('1')
                    draw_odd = main_market.get('X')
                    away_odd = main_market.get('2')

                    # Лига
                    league = item.get('tournament', {}).get('name', 'Unknown')

                    event_name = f"{home_team} vs {away_team}"
                    unique_key = self.generate_unique_key(home_team, away_team)

                    # Проверяем дубликаты
                    if unique_key in self.last_saved:
                        if (self.last_saved[unique_key].get('home_odd') == home_odd and
                            self.last_saved[unique_key].get('draw_odd') == draw_odd and
                            self.last_saved[unique_key].get('away_odd') == away_odd):
                            continue

                    self.last_saved[unique_key] = {
                        'home_odd': home_odd,
                        'draw_odd': draw_odd,
                        'away_odd': away_odd
                    }

                    time_str = match_time.strftime('%H:%M')

                    matches_data.append({
                        'match_id': unique_key,
                        'event_name': event_name,
                        'home_team': home_team,
                        'away_team': away_team,
                        'status': 'prematch',
                        'match_time': time_str,
                        'home_odd': home_odd,
                        'draw_odd': draw_odd,
                        'away_odd': away_odd,
                        'sport': 'Football',
                        'league': league,
                        'match_datetime': match_time.isoformat()
                    })

                except Exception as e:
                    continue

            print(f"✅ Parsed {len(matches_data)} PREMATCH matches (next {HOURS_AHEAD} hours)")
            return matches_data

        except Exception as e:
            print(f"❌ Error parsing API response: {e}")
            return []

    def save_to_database(self, matches_data):
        if not matches_data or not self.conn:
            return

        try:
            cursor = self.conn.cursor()
            for match in matches_data:
                try:
                    cursor.execute("""
                        INSERT INTO odds_22bet
                        (event_name, home_team, away_team, sport, league, status,
                         odd_1, odd_x, odd_2, match_time, bookmaker, market_type,
                         updated_at, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                        ON DUPLICATE KEY UPDATE
                            odd_1 = VALUES(odd_1),
                            odd_x = VALUES(odd_x),
                            odd_2 = VALUES(odd_2),
                            match_time = VALUES(match_time),
                            status = VALUES(status),
                            updated_at = NOW()
                    """, (
                        match['event_name'],
                        match['home_team'],
                        match['away_team'],
                        match['sport'],
                        match['league'],
                        match['status'],
                        match['home_odd'],
                        match['draw_odd'],
                        match['away_odd'],
                        match['match_time'],
                        BOOKMAKER,
                        '1X2'
                    ))

                except pymysql.IntegrityError:
                    pass
                except Exception as e:
                    continue

            self.conn.commit()
            print(f"✅ Saved {len(matches_data)} PREMATCH matches to DB")

        except Exception as e:
            print(f"❌ Error saving to DB: {e}")

    async def run(self):
        print(f"\n🚀 Starting 22bet PREMATCH Parser (API Direct)")
        print(f"🌐 Proxy: {PROXY_URL}")
        print(f"⏰ Update interval: {UPDATE_INTERVAL} seconds")
        print(f"📅 Time window: NEXT {HOURS_AHEAD} hours")
        print(f"📊 Using API: {API_BASE}\n")

        if not self.connect_db():
            return

        consecutive_errors = 0
        max_errors = 5

        try:
            while True:
                try:
                    matches_data = await self.fetch_prematch_via_api()

                    if matches_data:
                        self.save_to_database(matches_data)
                        consecutive_errors = 0
                    else:
                        consecutive_errors += 1
                        if consecutive_errors >= max_errors:
                            print(f"❌ Too many consecutive errors, sleeping 5 min...")
                            await asyncio.sleep(300)
                            consecutive_errors = 0
                            continue

                    # Очистка кэша
                    if len(self.last_saved) > 10000:
                        self.last_saved = {}

                    print(f"⏳ Waiting {UPDATE_INTERVAL} seconds...\n")
                    await asyncio.sleep(UPDATE_INTERVAL)

                except Exception as e:
                    print(f"❌ Error in loop: {e}")
                    consecutive_errors += 1
                    await asyncio.sleep(10)

        except KeyboardInterrupt:
            print("\n⏹️ Stopped by user")
        except Exception as e:
            print(f"❌ Fatal error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.conn:
                self.conn.close()
                print("🔐 Database closed")


if __name__ == '__main__':
    parser = PrematchParser()
    asyncio.run(parser.run())

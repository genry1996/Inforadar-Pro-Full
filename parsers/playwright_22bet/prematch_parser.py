# -*- coding: utf-8 -*-
"""
22bet PREMATCH Parser - Live Page with Prematch Filter
D:\Inforadar_Pro\parsers\playwright_22bet\prematch_parser.py

Парсим с Live страницы, но фильтруем только prematch матчи
(по наличию времени старта вместо счёта)
Интервал: 60 сек
"""
import asyncio
import os
import hashlib
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
import pymysql
import re

# ===== КОНФИГУРАЦИЯ =====
DB_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'localhost'),
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', 'ryban8991!'),
    'database': os.getenv('MYSQL_DB', 'inforadar'),
    'cursorclass': pymysql.cursors.DictCursor
}

PROXY_CONFIG = {
    'server': 'http://213.137.91.35:12323',
    'username': '14ab48c9d85c1',
    'password': '5d234f6517'
}

UPDATE_INTERVAL = 60
BOOKMAKER = '22bet'
HOURS_AHEAD = 12  # 12 часов вперёд


class PrematchParser:
    def __init__(self):
        self.conn = None
        self.last_saved = {}

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

    def parse_time_string(self, time_str):
        """
        Парсим время:
        - "14:30" -> prematch (время начала)
        - "45'" -> live (минуты игры)
        - "HT" -> перерыв
        """
        time_str = time_str.strip()
        
        # Live матч - есть минуты
        if "'" in time_str or 'HT' in time_str.upper():
            return None, 'live'
        
        # Prematch - время в формате HH:MM
        time_match = re.search(r'(\d{1,2}):(\d{2})', time_str)
        if time_match:
            try:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2))
                now = datetime.now()
                match_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                # Если время уже прошло - это завтра
                if match_time < now:
                    match_time = match_time + timedelta(days=1)
                
                return match_time, 'prematch'
            except:
                return None, 'unknown'
        
        return None, 'unknown'

    async def parse_prematch_matches(self, page):
        """
        Парсим Live страницу, но фильтруем prematch
        """
        try:
            if len(self.last_saved) > 10000:
                self.last_saved = {}

            # Ждём загрузки
            await page.wait_for_selector('.c-events__item', timeout=15000)
            await asyncio.sleep(2)  # Доп. время на JS
            
            matches = await page.query_selector_all('.c-events__item')
            
            if not matches:
                print(f"⚠️ No matches found")
                return []

            print(f"📊 Found {len(matches)} total items on page")

            matches_data = []
            now = datetime.now()
            cutoff_time = now + timedelta(hours=HOURS_AHEAD)

            for idx, match in enumerate(matches, 1):
                try:
                    # Команды
                    teams = await match.query_selector('.c-events__teams')
                    teams_text = await teams.text_content() if teams else ""
                    teams_text = ' '.join(teams_text.split())
                    
                    if ' - ' in teams_text:
                        teams_split = teams_text.split(' - ')
                    elif ' vs ' in teams_text:
                        teams_split = teams_text.split(' vs ')
                    else:
                        continue
                    
                    home_team = teams_split[0].strip() if len(teams_split) > 0 else None
                    away_team = teams_split[1].strip() if len(teams_split) > 1 else None

                    if not home_team or not away_team:
                        continue

                    # ВРЕМЯ - ключевой момент!
                    time_elem = await match.query_selector('.c-events__time')
                    time_str = await time_elem.text_content() if time_elem else ""
                    time_str = time_str.strip()

                    match_time, status = self.parse_time_string(time_str)

                    # 🔥 ФИЛЬТР: только prematch!
                    if status != 'prematch' or not match_time:
                        continue

                    # Фильтр по временному окну
                    if match_time > cutoff_time:
                        continue
                    if match_time < now - timedelta(minutes=5):
                        continue

                    # Лига
                    league_elem = await match.query_selector('.c-events__league')
                    league = await league_elem.text_content() if league_elem else "Unknown"
                    league = league.strip()

                    # Коэффициенты
                    odds_elements = await match.query_selector_all('.c-bets__bet')
                    home_odd = draw_odd = away_odd = None

                    if len(odds_elements) >= 3:
                        try:
                            home_text = await odds_elements[0].text_content()
                            home_odd = float(home_text.strip()) if home_text.strip() else None
                        except:
                            pass

                        try:
                            draw_text = await odds_elements[1].text_content()
                            draw_text = draw_text.strip()
                            if draw_text.upper() not in ['X', '']:
                                draw_odd = float(draw_text)
                        except:
                            pass

                        try:
                            away_text = await odds_elements[2].text_content()
                            away_odd = float(away_text.strip()) if away_text.strip() else None
                        except:
                            pass

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

            print(f"✅ Filtered to {len(matches_data)} PREMATCH matches (next {HOURS_AHEAD} hours)")
            return matches_data

        except Exception as e:
            print(f"❌ Error in parse_prematch_matches: {e}")
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
        print(f"\n🚀 Starting 22bet PREMATCH Parser")
        print(f"🌐 Proxy: {PROXY_CONFIG['server']}")
        print(f"⏰ Update interval: {UPDATE_INTERVAL} seconds")
        print(f"📅 Time window: NEXT {HOURS_AHEAD} hours")
        print(f"📊 Parsing from: https://22bet.com/live/football")
        print(f"🔍 Filter: Only matches with start time (HH:MM format)\n")

        if not self.connect_db():
            return

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                proxy=PROXY_CONFIG,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                ]
            )

            print(f"✅ Browser launched\n")

            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='en-US'
            )

            page = await context.new_page()

            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)

            try:
                print(f"🔄 Loading https://22bet.com/live/football...")
                await page.goto('https://22bet.com/live/football', timeout=30000, wait_until='domcontentloaded')
                await asyncio.sleep(3)
                
                print("✅ Page loaded\n")

                consecutive_errors = 0
                max_errors = 5

                while True:
                    try:
                        matches_data = await self.parse_prematch_matches(page)

                        if matches_data:
                            self.save_to_database(matches_data)
                            consecutive_errors = 0
                        else:
                            consecutive_errors += 1
                            if consecutive_errors >= max_errors:
                                print(f"❌ Too many errors, reloading...")
                                await page.reload(wait_until='domcontentloaded')
                                await asyncio.sleep(3)
                                consecutive_errors = 0
                                continue

                        print(f"⏳ Waiting {UPDATE_INTERVAL} seconds...\n")
                        await asyncio.sleep(UPDATE_INTERVAL)
                        
                        await page.reload(wait_until='domcontentloaded')
                        await asyncio.sleep(2)

                    except Exception as e:
                        print(f"❌ Error in loop: {e}")
                        consecutive_errors += 1
                        await asyncio.sleep(10)

            except KeyboardInterrupt:
                print("\n⏹️ Stopped by user")
            except Exception as e:
                print(f"❌ Fatal error: {e}")
            finally:
                await context.close()
                await browser.close()
                if self.conn:
                    self.conn.close()
                    print("🔐 Database closed")


if __name__ == '__main__':
    parser = PrematchParser()
    asyncio.run(parser.run())

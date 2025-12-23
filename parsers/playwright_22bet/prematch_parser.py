# -*- coding: utf-8 -*-
"""
22bet PREMATCH Parser - Calendar & Upcoming Matches
D:\Inforadar_Pro\parsers\playwright_22bet\prematch_parser.py

Парсит предстоящие матчи из календаря 22bet
Время: 1 час ПЕРЕД матчем (test), потом переключим на 12 часов
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

UPDATE_INTERVAL = 60  # 🔥 60 сек
BOOKMAKER = '22bet'
HOURS_AHEAD = 1  # ТЕСТОВАЯ СТОИМОСТЬ: 1 час, потом переключим на 12


class PrematchParser:
    def __init__(self):
        self.conn = None
        self.last_saved = {}  # Кэш для избежания дубликатов

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

    async def parse_prematch_matches(self, page):
        """
        Парсим матчи из календаря на главной странице
        Берём матчи которые начнутся в течение HOURS_AHEAD
        """
        try:
            if len(self.last_saved) > 10000:
                self.last_saved = {}

            # Ищем элементы с временем матча
            matches = await page.query_selector_all('[data-tournament-id]')

            if not matches:
                print(f"⚠️ No matches found with [data-tournament-id]")
                # Попробуем другой селектор
                matches = await page.query_selector_all('.c-events__item')
                if not matches:
                    print(f"⚠️ Also no matches with .c-events__item")
                    return []

            print(f"📊 Found {len(matches)} total matches")

            matches_data = []
            now = datetime.now()
            cutoff_time = now + timedelta(hours=HOURS_AHEAD)

            for idx, match in enumerate(matches, 1):
                try:
                    # Парсим команды
                    teams = await match.query_selector('.c-events__teams')
                    teams_text = await teams.text_content() if teams else "Unknown vs Unknown"
                    teams_text = ' '.join(teams_text.split())

                    if ' - ' in teams_text:
                        teams_split = teams_text.split(' - ')
                    elif ' vs ' in teams_text:
                        teams_split = teams_text.split(' vs ')
                    else:
                        continue

                    home_team = teams_split[0].strip() if len(teams_split) > 0 else None
                    away_team = teams_split[1].strip() if len(teams_split) > 1 else None

                    if not home_team or not away_team or home_team == "Unknown" or away_team == "Unknown":
                        continue

                    # ключевой момент: парсим время матча
                    time_elem = await match.query_selector('.c-events__time')
                    time_str = await time_elem.text_content() if time_elem else None

                    if not time_str:
                        continue

                    time_str = time_str.strip()

                    # Парсим время в формате "HH:MM" или "14:30"
                    time_match = re.search(r'(\d{1,2}):(\d{2})', time_str)
                    if not time_match:
                        continue

                    try:
                        match_hour = int(time_match.group(1))
                        match_min = int(time_match.group(2))
                        # Предполагаем сегодняшний день или завтра
                        match_time = now.replace(hour=match_hour, minute=match_min, second=0, microsecond=0)

                        # Если время прошло, считаем что это завтра
                        if match_time < now:
                            match_time = match_time + timedelta(days=1)

                        # 🔥 ФИЛЬТР: матч должен быть в течение HOURS_AHEAD
                        if match_time > cutoff_time:
                            continue  # Матч слишком далеко в будущем
                        if match_time < now - timedelta(minutes=5):
                            continue  # Матч уже прошел

                    except:
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
                            home_odd = None

                        try:
                            draw_text = await odds_elements[1].text_content()
                            draw_text = draw_text.strip()
                            if draw_text.upper() == 'X' or not draw_text:
                                draw_odd = None
                            else:
                                draw_odd = float(draw_text)
                        except:
                            draw_odd = None

                        try:
                            away_text = await odds_elements[2].text_content()
                            away_odd = float(away_text.strip()) if away_text.strip() else None
                        except:
                            away_odd = None

                    # Уникальный ключ
                    unique_key = self.generate_unique_key(home_team, away_team)

                    # Проверяем дубликаты
                    if unique_key in self.last_saved:
                        if (self.last_saved[unique_key]['home_odd'] == home_odd and
                            self.last_saved[unique_key]['draw_odd'] == draw_odd and
                            self.last_saved[unique_key]['away_odd'] == away_odd):
                            continue

                    self.last_saved[unique_key] = {
                        'home_odd': home_odd,
                        'draw_odd': draw_odd,
                        'away_odd': away_odd
                    }

                    event_name = f"{home_team} vs {away_team}"

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

            print(f"✅ Filtered to {len(matches_data)} PREMATCH matches (next {HOURS_AHEAD} hour)")
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

                    cursor.execute("""
                        INSERT INTO odds_full_history
                        (bookmaker, match_id, home_team, away_team, sport, league,
                         home_odd, draw_odd, away_odd, minute, score, status,
                         is_live, timestamp, notes)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                    """, (
                        BOOKMAKER,
                        match['match_id'],
                        match['home_team'],
                        match['away_team'],
                        match['sport'],
                        match['league'],
                        match['home_odd'],
                        match['draw_odd'],
                        match['away_odd'],
                        0,
                        "0:0",
                        'prematch',
                        False,
                        f"Prematch - {match['match_time']}"
                    ))

                except pymysql.IntegrityError:
                    # Дубликат - пропускаем
                    pass
                except Exception as e:
                    print(f"⚠️ Error inserting match: {e}")
                    continue

            self.conn.commit()
            print(f"✅ Saved {len(matches_data)} PREMATCH matches to DB")

        except Exception as e:
            print(f"❌ Error saving to DB: {e}")

    async def run(self):
        print(f"\n🚀 Starting 22bet PREMATCH Parser (Calendar)")
        print(f"🌐 Proxy: {PROXY_CONFIG['server']}")
        print(f"⏰ Update interval: {UPDATE_INTERVAL} seconds")
        print(f"📅 Time window: NEXT {HOURS_AHEAD} hour from now")
        print(f"📊 Parsing from: https://22bet.com/football\n")

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
                    '--disable-setuid-sandbox',
                ]
            )

            print(f"✅ Browser launched\n")

            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='ru-RU',
                timezone_id='Europe/Moscow'
            )

            page = await context.new_page()

            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
            """)

            try:
                print(f"🔄 Loading https://22bet.com/football...")
                await page.goto('https://22bet.com/football', timeout=30000, wait_until='domcontentloaded')
                await asyncio.sleep(3)  # Даём время на загрузку JS

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
                                print(f"❌ Too many consecutive errors, reloading page...")
                                await page.reload(wait_until='domcontentloaded')
                                await asyncio.sleep(3)
                                consecutive_errors = 0
                                continue

                        print(f"⏳ Waiting {UPDATE_INTERVAL} seconds...\n")
                        await asyncio.sleep(UPDATE_INTERVAL)

                        # Периодически перезагружаем
                        if consecutive_errors == 0:
                            await page.reload(wait_until='domcontentloaded')
                            await asyncio.sleep(2)

                    except Exception as e:
                        print(f"❌ Error in loop: {e}")
                        consecutive_errors += 1
                        await asyncio.sleep(10)

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

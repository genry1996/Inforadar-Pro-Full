# -*- coding: utf-8 -*-
"""
22bet Prematch Parser - Upcoming Matches
D:\Inforadar_Pro\parsers\playwright_22bet\prematch_parser.py

Парсит матчи от 1 часа до 7 дней в будущем
"""
import asyncio
import os
import hashlib
from datetime import datetime
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

# ===== ПРОКСИ НАСТРОЙКИ =====
PROXY_CONFIG = {
    'server': 'http://213.137.91.35:12323',
    'username': '14ab48c9d85c1',
    'password': '5d234f6517'
}

UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', 5))
BOOKMAKER = '22bet'


class PrematchParser:
    def __init__(self):
        self.conn = None

    def connect_db(self):
        try:
            self.conn = pymysql.connect(**DB_CONFIG)
            print(f"✅ Connected to MySQL: {DB_CONFIG['host']}")
            return True
        except Exception as e:
            print(f"❌ DB Connection Error: {e}")
            return False

    async def parse_prematch_matches(self, page):
        """
        Парсинг prematch матчей
        Ищет в секциях: Today, Tomorrow, Next 7 Days
        """
        try:
            # Ждём загрузки элементов
            await page.wait_for_selector('.c-events__item', timeout=10000)
            matches = await page.query_selector_all('.c-events__item')

            if not matches:
                print(f"⚠️ No prematch matches found")
                return []

            print(f"📊 Found {len(matches)} prematch matches")

            matches_data = []
            for idx, match in enumerate(matches, 1):
                try:
                    # Парсинг match_id
                    match_id = await match.get_attribute('data-event-id')
                    if not match_id:
                        match_id = await match.get_attribute('id')
                    if not match_id:
                        match_id = await match.get_attribute('data-id')

                    # Парсинг команд
                    teams = await match.query_selector('.c-events__teams')
                    teams_text = await teams.text_content() if teams else "Unknown vs Unknown"
                    teams_text = ' '.join(teams_text.split())
                    teams_split = teams_text.split(' - ') if ' - ' in teams_text else teams_text.split(' vs ')

                    home_team = teams_split[0].strip() if len(teams_split) > 0 else "Unknown"
                    away_team = teams_split[1].strip() if len(teams_split) > 1 else "Unknown"

                    # Генерируем ID если нужно
                    if not match_id:
                        team_hash = hashlib.md5(f"{home_team}{away_team}".encode()).hexdigest()[:8]
                        match_id = f"22bet_{team_hash}"
                        print(f"⚠️ Generated fallback match_id: {match_id}")

                    event_name = f"{home_team} vs {away_team}"

                    # Время матча (может быть в разных форматах)
                    time_elem = await match.query_selector('.c-events__time')
                    match_time = await time_elem.text_content() if time_elem else "N/A"
                    match_time = match_time.strip()

                    # Парсинг коэффициентов 1X2
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

                    # Лига (парсим из контекста)
                    league_elem = await match.query_selector('.c-events__league')
                    league = await league_elem.text_content() if league_elem else "Unknown League"
                    league = league.strip()

                    matches_data.append({
                        'match_id': match_id,
                        'event_name': event_name,
                        'home_team': home_team,
                        'away_team': away_team,
                        'status': 'prematch',
                        'match_time': match_time,
                        'home_odd': home_odd,
                        'draw_odd': draw_odd,
                        'away_odd': away_odd,
                        'sport': 'Football',
                        'league': league,
                        'minute': 0,
                        'score': "0:0"
                    })

                except Exception as e:
                    print(f"⚠️ Error parsing match #{idx}: {e}")
                    continue

            print(f"✅ Successfully parsed {len(matches_data)}/{len(matches)} prematch matches")
            return matches_data

        except Exception as e:
            print(f"❌ Error in parse_prematch_matches: {e}")
            return []

    def save_to_database(self, matches_data):
        """Сохранение prematch матчей в БД"""
        if not matches_data or not self.conn:
            return

        try:
            cursor = self.conn.cursor()
            for match in matches_data:
                try:
                    # Сохраняем в odds_22bet (для prematch)
                    cursor.execute("""
                        INSERT INTO odds_22bet
                        (event_name, home_team, away_team, sport, league, status,
                         odd_1, odd_x, odd_2, match_time, bookmaker)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        BOOKMAKER
                    ))

                    # Также сохраняем в odds_full_history для истории
                    cursor.execute("""
                        INSERT INTO odds_full_history
                        (bookmaker, match_id, home_team, away_team, sport, league,
                         home_odd, draw_odd, away_odd, minute, score, status,
                         is_live, timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
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
                        match['status'],
                        False
                    ))

                except Exception as e:
                    print(f"⚠️ Error inserting match {match.get('event_name')}: {e}")
                    continue

            self.conn.commit()
            print(f"✅ Saved {len(matches_data)} prematch matches to DB")

        except Exception as e:
            print(f"❌ Error saving to DB: {e}")

    async def run(self):
        """Главный цикл парсера"""
        print(f"🚀 Starting 22bet PREMATCH parser")
        print(f"🌐 Proxy: {PROXY_CONFIG['server']} (Sweden)")
        print(f"🔄 Update interval: {UPDATE_INTERVAL} seconds")
        print(f"📅 Parsing upcoming matches (1 hour - 7 days ahead)")

        if not self.connect_db():
            print("❌ Cannot start without DB connection")
            return

        async with async_playwright() as p:
            # Запуск браузера с прокси
            browser = await p.chromium.launch(
                headless=True,
                proxy=PROXY_CONFIG,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-web-security',
                ]
            )

            print(f"✅ Browser launched with proxy: {PROXY_CONFIG['server']}")

            # Контекст
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='ru-RU',
                timezone_id='Europe/Moscow'
            )

            page = await context.new_page()

            # Скрываем webdriver
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru', 'en-US', 'en']});
            """)

            try:
                print(f"🔄 Loading https://22bet.com/football (prematch) via proxy...")
                # Грузим главную страницу футбола (где видны предстоящие матчи)
                await page.goto('https://22bet.com/football', timeout=30000, wait_until='domcontentloaded')
                print("✅ Loaded 22bet football page")

                consecutive_errors = 0
                max_consecutive_errors = 5

                while True:
                    try:
                        matches_data = await self.parse_prematch_matches(page)

                        if matches_data:
                            self.save_to_database(matches_data)
                            consecutive_errors = 0
                        else:
                            print("⚠️ No matches parsed")
                            consecutive_errors += 1

                        print(f"⏳ Waiting {UPDATE_INTERVAL} seconds...")
                        await asyncio.sleep(UPDATE_INTERVAL)
                        await page.reload(wait_until='domcontentloaded')

                    except Exception as e:
                        print(f"❌ Error in main loop: {e}")
                        consecutive_errors += 1

                        if consecutive_errors >= max_consecutive_errors:
                            print(f"❌ Too many consecutive errors, restarting...")
                            break

                        await asyncio.sleep(10)

            except Exception as e:
                print(f"❌ Fatal error: {e}")
            finally:
                await context.close()
                await browser.close()

                if self.conn:
                    self.conn.close()
                    print("🔌 Database connection closed")


if __name__ == '__main__':
    parser = PrematchParser()
    asyncio.run(parser.run())

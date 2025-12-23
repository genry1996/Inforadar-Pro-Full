# -*- coding: utf-8 -*-
"""
22bet PREMATCH Parser - AUTO SELECTOR DETECTION
D:\Inforadar_Pro\parsers\playwright_22bet\prematch_parser.py

Автоматический поиск селекторов на главной странице 22bet
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

UPDATE_INTERVAL = 60  # 60 сек
BOOKMAKER = '22bet'
HOURS_AHEAD = 1  # Тестовая стоимость: 1 час


class PrematchParser:
    def __init__(self):
        self.conn = None
        self.last_saved = {}
        self.detected_selectors = {}  # Кэш найденных селекторов

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

    async def detect_selectors(self, page):
        """
        🔍 Автоматический поиск селекторов для матчей
        Пробует разные CSS селекторы и возвращает рабочие
        """
        selectors_to_try = [
            # Основные варианты
            '.c-events__item',
            '[class*="event"]',
            '[class*="match"]',
            '.match',
            '.event',
            '[data-event]',
            '[data-match]',
            '[data-tournament]',
            # Более специфичные
            'div[class*="event-row"]',
            'div[class*="match-row"]',
            'tr[data-event-id]',
            'tr[class*="event"]',
            # Общие контейнеры
            'li[class*="event"]',
            'div[role="button"][class*="event"]',
        ]

        found_selectors = {}

        for selector in selectors_to_try:
            try:
                elements = await page.query_selector_all(selector)
                count = len(elements)
                if count > 0:
                    found_selectors[selector] = count
                    print(f"  ✅ Found {count} elements with: {selector}")
            except:
                pass

        return found_selectors

    async def extract_match_info_from_element(self, match_elem):
        """
        Пытается извлечь информацию из элемента матча
        Пробует разные способы
        """
        try:
            # Способ 1: Получи весь текст элемента
            full_text = await match_elem.text_content()
            if not full_text:
                return None

            full_text = ' '.join(full_text.split())

            # Попробуй найти команды (Team1 vs Team2 или Team1 - Team2)
            teams_match = re.search(r'(.+?)\s+(?:vs|-|—)\s+(.+?)\s+(\d{1,2}:\d{2})', full_text)
            if not teams_match:
                return None

            home_team = teams_match.group(1).strip()
            away_team = teams_match.group(2).strip()
            time_str = teams_match.group(3).strip()

            # Фильтр неправильных команд
            if len(home_team) < 2 or len(away_team) < 2:
                return None
            if 'unknown' in home_team.lower() or 'unknown' in away_team.lower():
                return None

            return {
                'home_team': home_team,
                'away_team': away_team,
                'time_str': time_str,
                'full_text': full_text
            }

        except Exception as e:
            return None

    async def parse_prematch_matches(self, page):
        """
        Парсим матчи с автоматическим поиском селекторов
        """
        try:
            if len(self.last_saved) > 10000:
                self.last_saved = {}

            print("\n🔍 Detecting selectors...")
            found_selectors = await self.detect_selectors(page)

            if not found_selectors:
                print("⚠️ No match selectors found!")
                # Попробуем просто получить страницу HTML
                print("📄 Dumping page structure...")
                html = await page.content()
                # Ищем в HTML text с похожестью на название команды
                if 'vs' in html.lower() or '—' in html or '-' in html:
                    print(f"   ℹ️ Page contains team indicators")
                return []

            # Используем первый найденный селектор (с наибольшим количеством элементов)
            best_selector = max(found_selectors.items(), key=lambda x: x[1])[0]
            print(f"\n🎯 Using selector: {best_selector} ({found_selectors[best_selector]} elements)")

            matches = await page.query_selector_all(best_selector)
            print(f"📊 Found {len(matches)} total elements")

            matches_data = []
            now = datetime.now()
            cutoff_time = now + timedelta(hours=HOURS_AHEAD)

            for idx, match in enumerate(matches[:100], 1):  # Макс 100 проверяем
                try:
                    match_info = await self.extract_match_info_from_element(match)
                    if not match_info:
                        continue

                    home_team = match_info['home_team']
                    away_team = match_info['away_team']
                    time_str = match_info['time_str']

                    # Парсим время
                    time_match = re.search(r'(\d{1,2}):(\d{2})', time_str)
                    if not time_match:
                        continue

                    try:
                        match_hour = int(time_match.group(1))
                        match_min = int(time_match.group(2))
                        match_time = now.replace(hour=match_hour, minute=match_min, second=0, microsecond=0)

                        if match_time < now:
                            match_time = match_time + timedelta(days=1)

                        if match_time > cutoff_time or match_time < now - timedelta(minutes=5):
                            continue

                    except:
                        continue

                    # Пробуем получить коэффициенты из элемента
                    odd_texts = await match.query_selector_all('text')
                    home_odd = draw_odd = away_odd = None

                    # Ищем селекторы для коэффициентов
                    odds_container = await match.query_selector_all('[class*="odd"], [class*="coefficient"], .c-bets__bet')
                    if len(odds_container) >= 3:
                        try:
                            home_odd = float(await odds_container[0].text_content())
                        except:
                            home_odd = None
                        try:
                            draw_text = await odds_container[1].text_content()
                            if draw_text.strip().upper() != 'X':
                                draw_odd = float(draw_text)
                        except:
                            draw_odd = None
                        try:
                            away_odd = float(await odds_container[2].text_content())
                        except:
                            away_odd = None

                    # Лига - попробуем найти
                    league = "Unknown"
                    league_elem = await match.query_selector('[class*="league"], [class*="tournament"]')
                    if league_elem:
                        league = await league_elem.text_content()
                        league = league.strip() if league else "Unknown"

                    unique_key = self.generate_unique_key(home_team, away_team)

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

            print(f"✅ Parsed {len(matches_data)} PREMATCH matches")
            return matches_data

        except Exception as e:
            print(f"❌ Error in parse_prematch_matches: {e}")
            import traceback
            traceback.print_exc()
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

                except pymysql.IntegrityError:
                    pass
                except Exception as e:
                    continue

            self.conn.commit()
            print(f"✅ Saved {len(matches_data)} PREMATCH matches to DB")

        except Exception as e:
            print(f"❌ Error saving to DB: {e}")

    async def run(self):
        print(f"\n🚀 Starting 22bet PREMATCH Parser (AUTO DETECT)")
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
                await asyncio.sleep(3)

                print("✅ Page loaded")

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
                                print(f"❌ Too many errors, reloading page...")
                                await page.reload(wait_until='domcontentloaded')
                                await asyncio.sleep(3)
                                consecutive_errors = 0
                                continue

                        print(f"⏳ Waiting {UPDATE_INTERVAL} seconds...\n")
                        await asyncio.sleep(UPDATE_INTERVAL)

                        if consecutive_errors == 0:
                            await page.reload(wait_until='domcontentloaded')
                            await asyncio.sleep(2)

                    except Exception as e:
                        print(f"❌ Error in loop: {e}")
                        consecutive_errors += 1
                        await asyncio.sleep(10)

            except Exception as e:
                print(f"❌ Fatal error: {e}")
                import traceback
                traceback.print_exc()
            finally:
                await context.close()
                await browser.close()
                if self.conn:
                    self.conn.close()
                    print("🔐 Database closed")


if __name__ == '__main__':
    parser = PrematchParser()
    asyncio.run(parser.run())

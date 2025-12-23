# -*- coding: utf-8 -*-
"""
22bet Live Parser with Anti-Detection + Proxy
D:\Inforadar_Pro\parsers\playwright_22bet\live_parser.py

БЕЗ ДУБЛИКАТОВ - парсим только реальные матчи
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

UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', 3))
BOOKMAKER = '22bet'


class LiveMatchParser:
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

    def generate_unique_key(self, home_team, away_team, minute, score):
        """Генерируем уникальный ключ из реальных данных матча"""
        key_str = f"{home_team}#{away_team}#{minute}#{score}".lower()
        return hashlib.md5(key_str.encode()).hexdigest()[:12]

    async def parse_match_status(self, match):
        """Парсинг минуты, счета и статуса"""
        try:
            # Минута матча
            minute_elem = await match.query_selector('.c-events__time')
            minute_text = await minute_elem.text_content() if minute_elem else "0'"
            minute = int(re.search(r'\d+', minute_text).group()) if re.search(r'\d+', minute_text) else 0

            # Счет
            score_elem = await match.query_selector('.c-events__score')
            if score_elem:
                score_text = await score_elem.text_content()
                score = score_text.strip()
                
                # Проверяем формат счёта (должен быть X:Y)
                if ':' not in score or len(score) > 10:
                    score = "0:0"
            else:
                score = "0:0"

            # Статус
            if minute == 0:
                status = 'prematch'
            elif 1 <= minute <= 45:
                status = 'live'
            elif minute == 45:
                status = 'halftime'
            elif minute > 45:
                status = 'live'
            else:
                status = 'finished'

            return minute, score, status
        except Exception as e:
            print(f"⚠️ Error parsing status: {e}")
            return 0, "0:0", "prematch"

    async def parse_events(self, match):
        """Парсинг событий матча (голы, карточки)"""
        events = []
        try:
            # Ищем иконки событий
            event_icons = await match.query_selector_all('.c-events__icon')
            for icon in event_icons:
                icon_class = await icon.get_attribute('class')

                # Определяем тип события
                event_type = None
                if 'goal' in icon_class.lower():
                    event_type = 'goal'
                elif 'yellow' in icon_class.lower():
                    event_type = 'yellow'
                elif 'red' in icon_class.lower():
                    event_type = 'red'

                if event_type:
                    # Минута события
                    minute_elem = await icon.query_selector('..//span[@class="minute"]')
                    minute = int(await minute_elem.text_content()) if minute_elem else 0

                    # Команда (home/away)
                    team_elem = await icon.query_selector('..//span[@class="team"]')
                    team = await team_elem.text_content() if team_elem else 'home'
                    team = 'home' if team.lower() in ['home', '1'] else 'away'

                    events.append({
                        'type': event_type,
                        'minute': minute,
                        'team': team,
                        'player': 'Unknown'
                    })
        except Exception as e:
            print(f"⚠️ Error parsing events: {e}")

        return events

    async def parse_live_matches(self, page):
        """Полный парсинг live-матчей БЕЗ ДУБЛИКАТОВ"""
        try:
            await page.wait_for_selector('.c-events__item', timeout=10000)
            matches = await page.query_selector_all('.c-events__item')

            if not matches:
                print(f"⚠️ No matches found")
                return []

            print(f"📊 Found {len(matches)} matches (parsing...)")

            matches_data = []
            for idx, match in enumerate(matches, 1):
                try:
                    # Парсинг команд
                    teams = await match.query_selector('.c-events__teams')
                    teams_text = await teams.text_content() if teams else "Unknown vs Unknown"
                    
                    # Убираем лишние пробелы и разбиваем
                    teams_text = ' '.join(teams_text.split())
                    
                    if ' - ' in teams_text:
                        teams_split = teams_text.split(' - ')
                    elif ' vs ' in teams_text:
                        teams_split = teams_text.split(' vs ')
                    else:
                        teams_split = teams_text.split()
                    
                    home_team = teams_split[0].strip() if len(teams_split) > 0 else "Unknown"
                    away_team = teams_split[1].strip() if len(teams_split) > 1 else "Unknown"
                    
                    # 🔥 ФИЛЬТР: пропускаем матчи с "Unknown" командами
                    if home_team == "Unknown" or away_team == "Unknown":
                        continue

                    event_name = f"{home_team} vs {away_team}"

                    # Статус матча
                    minute, score, status = await self.parse_match_status(match)

                    # 🔥 Генерируем уникальный ключ БЕЗ session_id
                    unique_key = self.generate_unique_key(home_team, away_team, minute, score)

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

                    # События
                    events = await self.parse_events(match)

                    # 🔥 ДОПОЛНИТЕЛЬНЫЙ ФИЛЬТР: если у нас уже есть этот матч с теми же кэффициентами - пропускаем
                    if unique_key in self.last_saved:
                        cached = self.last_saved[unique_key]
                        if (cached['home_odd'] == home_odd and 
                            cached['draw_odd'] == draw_odd and 
                            cached['away_odd'] == away_odd):
                            # Точный дубликат - не добавляем
                            continue

                    # Кэшируем для следующей итерации
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
                        'minute': minute,
                        'score': score,
                        'status': status,
                        'home_odd': home_odd,
                        'draw_odd': draw_odd,
                        'away_odd': away_odd,
                        'events': events,
                        'sport': 'Football',
                        'league': 'Unknown'
                    })

                except Exception as e:
                    print(f"⚠️ Error parsing match #{idx}: {e}")
                    continue

            print(f"✅ Successfully parsed {len(matches_data)} unique live matches")
            return matches_data

        except Exception as e:
            print(f"❌ Error in parse_live_matches: {e}")
            return []

    def save_to_database(self, matches_data):
        """Сохранение в БД"""
        if not matches_data or not self.conn:
            return

        try:
            cursor = self.conn.cursor()
            for match in matches_data:
                try:
                    # Сохраняем/обновляем в odds_22bet
                    cursor.execute("""
                        INSERT INTO odds_22bet
                        (event_name, home_team, away_team, sport, league, status,
                         odd_1, odd_x, odd_2, minute, score, bookmaker, match_time)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON DUPLICATE KEY UPDATE
                            odd_1 = VALUES(odd_1),
                            odd_x = VALUES(odd_x),
                            odd_2 = VALUES(odd_2),
                            minute = VALUES(minute),
                            score = VALUES(score),
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
                        match['minute'],
                        match['score'],
                        BOOKMAKER
                    ))

                    # Сохраняем в odds_full_history (история)
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
                        match['minute'],
                        match['score'],
                        match['status'],
                        True
                    ))

                except Exception as e:
                    print(f"⚠️ Error inserting match {match.get('event_name')}: {e}")
                    continue

            self.conn.commit()
            print(f"✅ Saved {len(matches_data)} matches to DB")

        except Exception as e:
            print(f"❌ Error saving to DB: {e}")

    async def run(self):
        """Главный цикл парсера"""
        print(f"🚀 Starting 22bet LIVE parser (CLEAN - NO DUPLICATES)")
        print(f"🌐 Proxy: {PROXY_CONFIG['server']} (Sweden)")
        print(f"🔄 Update interval: {UPDATE_INTERVAL} seconds")

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
                print(f"🔄 Loading https://22bet.com/live/football via proxy...")
                await page.goto('https://22bet.com/live/football', timeout=30000, wait_until='domcontentloaded')
                await asyncio.sleep(2)
                print("✅ Loaded 22bet live page")

                consecutive_errors = 0
                max_consecutive_errors = 5

                while True:
                    try:
                        matches_data = await self.parse_live_matches(page)

                        if matches_data:
                            self.save_to_database(matches_data)
                            consecutive_errors = 0
                        else:
                            print("⚠️ No matches parsed")
                            consecutive_errors += 1

                        print(f"⏳ Waiting {UPDATE_INTERVAL} seconds...")
                        await asyncio.sleep(UPDATE_INTERVAL)
                        await page.reload(wait_until='domcontentloaded')
                        await asyncio.sleep(1)

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
    parser = LiveMatchParser()
    asyncio.run(parser.run())

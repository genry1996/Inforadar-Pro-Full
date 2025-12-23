# -*- coding: utf-8 -*-
"""
22bet Live Parser with Anti-Detection + Proxy
D:\Inforadar_Pro\parsers\playwright_22bet\live_parser.py
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

    def connect_db(self):
        try:
            self.conn = pymysql.connect(**DB_CONFIG)
            print(f"✅ Connected to MySQL: {DB_CONFIG['host']}")
            return True
        except Exception as e:
            print(f"❌ DB Connection Error: {e}")
            return False

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

    async def parse_handicap(self, match):
        """Парсинг фор (handicap)"""
        try:
            handicap_section = await match.query_selector('[data-market-type="handicap"]')
            if not handicap_section:
                return None

            line_elem = await handicap_section.query_selector('.handicap-line')
            line = float(await line_elem.text_content()) if line_elem else 0.0

            home_odd_elem = await handicap_section.query_selector('.handicap-home')
            home_odd = float(await home_odd_elem.text_content()) if home_odd_elem else None

            away_odd_elem = await handicap_section.query_selector('.handicap-away')
            away_odd = float(await away_odd_elem.text_content()) if away_odd_elem else None

            return {
                'line': line,
                'home': home_odd,
                'away': away_odd
            }
        except:
            return None

    async def parse_totals(self, match):
        """Парсинг тоталов (over/under)"""
        try:
            total_section = await match.query_selector('[data-market-type="total"]')
            if not total_section:
                return None

            line_elem = await total_section.query_selector('.total-line')
            line = float(await line_elem.text_content()) if line_elem else 2.5

            over_elem = await total_section.query_selector('.total-over')
            over_odd = float(await over_elem.text_content()) if over_elem else None

            under_elem = await total_section.query_selector('.total-under')
            under_odd = float(await under_elem.text_content()) if under_elem else None

            return {
                'line': line,
                'over': over_odd,
                'under': under_odd
            }
        except:
            return None

    async def parse_live_matches(self, page):
        """Полный парсинг live-матчей"""
        try:
            await page.wait_for_selector('.c-events__item', timeout=10000)
            matches = await page.query_selector_all('.c-events__item')

            if not matches:
                print(f"⚠️ No matches found")
                return []

            print(f"📊 Found {len(matches)} live matches")

            matches_data = []
            # 🔥 ИСПРАВЛЕНО: убрал [:10], теперь парсим ВСЕ матчи
            for idx, match in enumerate(matches, 1):
                try:
                    # Парсинг match_id с fallback
                    match_id = await match.get_attribute('data-event-id')
                    
                    # Если нет data-event-id, пробуем другие атрибуты
                    if not match_id:
                        match_id = await match.get_attribute('id')
                    
                    if not match_id:
                        match_id = await match.get_attribute('data-id')
                    
                    # Парсинг команд
                    teams = await match.query_selector('.c-events__teams')
                    teams_text = await teams.text_content() if teams else "Unknown vs Unknown"
                    
                    # Убираем лишние пробелы и разбиваем
                    teams_text = ' '.join(teams_text.split())
                    teams_split = teams_text.split(' - ')
                    
                    if len(teams_split) != 2:
                        teams_split = teams_text.split(' vs ')
                    
                    home_team = teams_split[0].strip() if len(teams_split) > 0 else "Unknown"
                    away_team = teams_split[1].strip() if len(teams_split) > 1 else "Unknown"
                    
                    # Если всё равно None - генерируем ID из команд
                    if not match_id:
                        team_hash = hashlib.md5(f"{home_team}{away_team}".encode()).hexdigest()[:8]
                        match_id = f"22bet_{team_hash}"
                        print(f"⚠️ Generated fallback match_id: {match_id}")
                    
                    event_name = f"{home_team} vs {away_team}"

                    # Статус матча
                    minute, score, status = await self.parse_match_status(match)

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

                    # Форы
                    handicap = await self.parse_handicap(match)

                    # Тоталы
                    totals = await self.parse_totals(match)

                    matches_data.append({
                        'match_id': match_id,
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
                        'handicap': handicap,
                        'totals': totals,
                        'sport': 'Football',
                        'league': 'Unknown'
                    })

                except Exception as e:
                    print(f"⚠️ Error parsing match #{idx}: {e}")
                    continue

            print(f"✅ Successfully parsed {len(matches_data)}/{len(matches)} matches")
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
                    # 1. Сохраняем/обновляем live_matches
                    cursor.execute("""
                        INSERT INTO live_matches
                        (event_id, event_name, home_team, away_team, score, minute, status, sport, league, bookmaker)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            score = VALUES(score),
                            minute = VALUES(minute),
                            status = VALUES(status),
                            updated_at = NOW()
                    """, (
                        match['match_id'],
                        match['event_name'],
                        match['home_team'],
                        match['away_team'],
                        match['score'],
                        match['minute'],
                        match['status'],
                        match['sport'],
                        match['league'],
                        BOOKMAKER
                    ))

                    # 2. Сохраняем события
                    for event in match['events']:
                        cursor.execute("""
                            INSERT INTO match_events
                            (event_id, event_type, minute, team, player)
                            VALUES (%s, %s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE minute = VALUES(minute)
                        """, (
                            match['match_id'],
                            event['type'],
                            event['minute'],
                            event['team'],
                            event['player']
                        ))

                    # 3. Сохраняем коэффициенты (расширенные)
                    cursor.execute("""
                        INSERT INTO odds_full_history
                        (bookmaker, match_id, home_team, away_team, sport, league,
                         home_odd, draw_odd, away_odd, minute, score, status,
                         handicap, handicap_home, handicap_away,
                         total, `over`, `under`, is_live, timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
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
                        match['handicap']['line'] if match['handicap'] else None,
                        match['handicap']['home'] if match['handicap'] else None,
                        match['handicap']['away'] if match['handicap'] else None,
                        match['totals']['line'] if match['totals'] else None,
                        match['totals']['over'] if match['totals'] else None,
                        match['totals']['under'] if match['totals'] else None,
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
        print(f"🚀 Starting 22bet LIVE parser (FULL + ANTI-DETECT + PROXY)")
        print(f"🌐 Proxy: {PROXY_CONFIG['server']} (Sweden)")
        print(f"🔄 Update interval: {UPDATE_INTERVAL} seconds")

        if not self.connect_db():
            print("❌ Cannot start without DB connection")
            return

        async with async_playwright() as p:
            # Запуск браузера с прокси
            browser = await p.chromium.launch(
                headless=False,
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

            # Контекст без прокси
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
    parser = LiveMatchParser()
    asyncio.run(parser.run())

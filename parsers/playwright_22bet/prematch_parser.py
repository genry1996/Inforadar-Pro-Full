# -*- coding: utf-8 -*-
"""
22bet Prematch Parser - Upcoming Matches
D:\Inforadar_Pro\parsers\playwright_22bet\prematch_parser.py

Парсит предстоящие матчи с 22bet
Интервал: 60 сек
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

UPDATE_INTERVAL = 60  # 60 сек
BOOKMAKER = '22bet'


class PrematchParser:
    def __init__(self):
        self.conn = None
        self.last_saved = {}  # Кэш для избежания дубликатов

    def connect_db(self):
        """Подключение к MySQL"""
        try:
            self.conn = pymysql.connect(**DB_CONFIG)
            print(f"✅ Connected to MySQL: {DB_CONFIG['host']}")
            return True
        except Exception as e:
            print(f"❌ DB Connection Error: {e}")
            return False

    def generate_unique_key(self, home_team, away_team, match_time):
        """Генерируем уникальный ключ"""
        key_str = f"{home_team}#{away_team}#{match_time}".lower()
        return hashlib.md5(key_str.encode()).hexdigest()[:12]

    async def wait_for_dynamic_content(self, page):
        """Дождёмся динамического лоада содержимого"""
        try:
            # Одна из этих страниц должна работать
            selectors_to_try = [
                '.c-events__item',
                '[class*="event"]',
                '.match',
                '[data-event-id]',
                '.row',
            ]

            for selector in selectors_to_try:
                try:
                    await page.wait_for_selector(selector, timeout=5000)
                    matches = await page.query_selector_all(selector)
                    if matches and len(matches) > 0:
                        print(f"✅ Found selector: {selector}")
                        return selector, matches
                except:
                    continue

            # Если обычные селекторы не работают, попытаямся альтернативы
            print("⚠️ Standard selectors not found, trying JavaScript approach...")
            
            # Пытаемся понять структуру страницы
            content = await page.content()
            
            if 'event' in content.lower() or 'match' in content.lower():
                # Есть содержимое
                print("✅ Page has content")
                return None, None
            else:
                print("⚠️ Page might be empty or requires more loading")
                return None, None

        except Exception as e:
            print(f"⚠️ Error waiting for content: {e}")
            return None, None

    async def parse_prematch_matches(self, page):
        """
        Парсинг prematch матчей
        """
        try:
            # Очистим кэш с каждым запросом
            if len(self.last_saved) > 10000:
                self.last_saved = {}  # От переполнения

            # Дождёмся динамического лоада
            selector, matches = await self.wait_for_dynamic_content(page)

            if not selector or not matches:
                # Пытаемся вытянуть данные через evaluate
                print("⚠️ Trying JavaScript extraction...")
                matches_data = await page.evaluate("""
                    () => {
                        const results = [];
                        
                        // Пытаемся найти любые элементы с текстом "вс"
                        const allElements = document.querySelectorAll('*');
                        
                        for (let elem of allElements) {
                            const text = elem.textContent;
                            if (text && text.includes(' vs ') && text.length < 100) {
                                // это вероятно матч
                                results.push(text);
                            }
                        }
                        
                        return results.slice(0, 100);  // Первые 100
                    }
                """)

                if matches_data and len(matches_data) > 0:
                    print(f"📅 Found {len(matches_data)} potential matches via JS")
                    # Парсим пары команд
                    parsed = []
                    for match_text in matches_data:
                        try:
                            if ' vs ' in match_text:
                                teams = match_text.split(' vs ')
                                if len(teams) == 2:
                                    home = teams[0].strip()
                                    away = teams[1].strip()
                                    
                                    if home and away and home != 'Unknown' and away != 'Unknown':
                                        parsed.append({
                                            'event_name': f"{home} vs {away}",
                                            'home_team': home,
                                            'away_team': away
                                        })
                        except:
                            continue
                    
                    print(f"✅ Parsed {len(parsed)} matches from JS extraction")
                    return parsed
                else:
                    print("⚠️ No matches found via JS")
                    return []
            else:
                # Обычный парсинг
                print(f"📅 Found {len(matches)} matches (selector: {selector})")

                matches_data = []
                for idx, match in enumerate(matches, 1):
                    try:
                        # Парсинг команд
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

                        event_name = f"{home_team} vs {away_team}"

                        # Парсинг времени
                        time_elem = await match.query_selector('.c-events__time')
                        match_time = await time_elem.text_content() if time_elem else "N/A"
                        match_time = match_time.strip()

                        # Парсинг коэффициентов
                        odds_elements = await match.query_selector_all('.c-bets__bet')
                        home_odd = draw_odd = away_odd = None

                        if len(odds_elements) >= 3:
                            try:
                                home_odd = float(await odds_elements[0].text_content())
                            except:
                                home_odd = None
                            try:
                                draw_odd = float(await odds_elements[1].text_content())
                            except:
                                draw_odd = None
                            try:
                                away_odd = float(await odds_elements[2].text_content())
                            except:
                                away_odd = None

                        # Лига
                        league_elem = await match.query_selector('.c-events__league')
                        league = await league_elem.text_content() if league_elem else "Unknown"
                        league = league.strip()

                        # Уникальный ключ
                        unique_key = self.generate_unique_key(home_team, away_team, match_time)

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

                        matches_data.append({
                            'match_id': unique_key,
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
                        continue

                print(f"✅ Successfully parsed {len(matches_data)} unique prematch matches")
                return matches_data

        except Exception as e:
            print(f"❌ Error in parse_prematch_matches: {e}")
            return []

    def save_to_database(self, matches_data):
        """Сохранение в БД"""
        if not matches_data or not self.conn:
            return

        try:
            cursor = self.conn.cursor()
            for match in matches_data:
                try:
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
                    continue

            self.conn.commit()
            print(f"✅ Saved {len(matches_data)} prematch matches to DB")

        except Exception as e:
            print(f"❌ Error saving to DB: {e}")

    async def run(self):
        """Главный цикл"""
        print(f"🚀 Starting 22bet PREMATCH parser")
        print(f"🌐 Proxy: {PROXY_CONFIG['server']}")
        print(f"⏰ Update interval: {UPDATE_INTERVAL} seconds")

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

            print(f"✅ Browser launched")

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
                await page.goto('https://22bet.com/football', timeout=30000, wait_until='networkidle')
                await asyncio.sleep(5)  # Очень долгая пауза для динамического контента
                
                print("✅ Page loaded")

                while True:
                    try:
                        matches_data = await self.parse_prematch_matches(page)

                        if matches_data:
                            self.save_to_database(matches_data)

                        print(f"⏳ Waiting {UPDATE_INTERVAL} seconds...")
                        await asyncio.sleep(UPDATE_INTERVAL)
                        await page.reload(wait_until='networkidle')
                        await asyncio.sleep(3)

                    except Exception as e:
                        print(f"❌ Error in loop: {e}")
                        await asyncio.sleep(10)

            except Exception as e:
                print(f"❌ Fatal error: {e}")
            finally:
                await context.close()
                await browser.close()
                if self.conn:
                    self.conn.close()


if __name__ == '__main__':
    parser = PrematchParser()
    asyncio.run(parser.run())

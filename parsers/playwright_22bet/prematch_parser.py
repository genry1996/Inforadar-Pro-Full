# -*- coding: utf-8 -*-
"""
22bet PREMATCH Parser - Line/Football Section
D:\Inforadar_Pro\parsers\playwright_22bet\prematch_parser.py

Парсим из секции LINE (prematch), а не LIVE!
URL: https://22bet.com/line/football
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
HOURS_AHEAD = 12
DEBUG_MODE = True


class PrematchParser:
    def __init__(self):
        self.conn = None
        self.last_saved = {}
        self.debug_samples = 0

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
        try:
            if len(self.last_saved) > 10000:
                self.last_saved = {}

            # Ждём загрузки - на LINE странице могут быть другие селекторы
            await asyncio.sleep(5)  # Даём время JS полностью загрузиться
            
            # Пробуем разные селекторы
            selectors_to_try = [
                '.c-events__item',
                '.c-events-scoreboard__item',
                '[class*="event"]',
                '.event-item',
                'div[data-event-id]'
            ]
            
            matches = None
            for selector in selectors_to_try:
                try:
                    test = await page.query_selector_all(selector)
                    if test and len(test) > 0:
                        matches = test
                        print(f"✅ Using selector: {selector} ({len(test)} items)")
                        break
                except:
                    continue
            
            if not matches:
                print(f"⚠️ No matches found with any selector")
                # Сохраняем HTML для анализа
                html = await page.content()
                with open('D:\\Inforadar_Pro\\debug_line_page.html', 'w', encoding='utf-8') as f:
                    f.write(html)
                print("📄 Saved page HTML to debug_line_page.html")
                return []

            print(f"📊 Found {len(matches)} total items on page")

            matches_data = []
            now = datetime.now()
            cutoff_time = now + timedelta(hours=HOURS_AHEAD)

            # 🔍 ДЕБАГ
            if DEBUG_MODE and self.debug_samples < 3:
                print("\n🔍 DEBUG: Showing first 10 matches...")
                for idx in range(min(10, len(matches))):
                    match = matches[idx]
                    try:
                        # Получаем весь текст
                        full_text = await match.text_content()
                        full_text = ' '.join(full_text.split())[:80]
                        print(f"  [{idx+1}] {full_text}")
                    except:
                        print(f"  [{idx+1}] Error getting text")
                print()
                self.debug_samples += 1

            for idx, match in enumerate(matches, 1):
                try:
                    # Получаем весь текст элемента
                    full_text = await match.text_content()
                    if not full_text:
                        continue
                    
                    full_text = ' '.join(full_text.split())
                    
                    # Пытаемся найти команды и время
                    # Формат: "Team1 - Team2 14:30" или "Team1 vs Team2 21:00"
                    pattern = r'(.+?)\s*(?:-|vs)\s*(.+?)\s+(\d{1,2}:\d{2})'
                    match_data = re.search(pattern, full_text, re.IGNORECASE)
                    
                    if not match_data:
                        continue
                    
                    home_team = match_data.group(1).strip()
                    away_team = match_data.group(2).strip()
                    time_str = match_data.group(3).strip()
                    
                    # Фильтр некорректных названий
                    if len(home_team) < 3 or len(away_team) < 3:
                        continue
                    if any(char.isdigit() for char in home_team[:5]):
                        continue
                    
                    # Парсим время
                    try:
                        time_match = re.search(r'(\d{1,2}):(\d{2})', time_str)
                        if not time_match:
                            continue
                        
                        hour = int(time_match.group(1))
                        minute = int(time_match.group(2))
                        match_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                        
                        if match_time < now:
                            match_time = match_time + timedelta(days=1)
                        
                        # Фильтр по времени
                        if match_time > cutoff_time:
                            continue
                        if match_time < now - timedelta(minutes=5):
                            continue
                    except:
                        continue
                    
                    # Пытаемся найти лигу и коэффы
                    league = "Unknown"
                    home_odd = draw_odd = away_odd = None
                    
                    # Коэффы - ищем числа в диапазоне 1.01-100
                    odds_pattern = r'\b(\d{1,2}\.\d{2})\b'
                    odds_found = re.findall(odds_pattern, full_text)
                    
                    if len(odds_found) >= 3:
                        try:
                            home_odd = float(odds_found[0])
                            draw_odd = float(odds_found[1])
                            away_odd = float(odds_found[2])
                        except:
                            pass
                    
                    event_name = f"{home_team} vs {away_team}"
                    unique_key = self.generate_unique_key(home_team, away_team)
                    
                    # Проверка дубликатов
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
                        'status': 'active',
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
        print(f"📊 Parsing from: https://22bet.com/line/football\n")

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
                print(f"🔄 Loading https://22bet.com/line/football...")
                await page.goto('https://22bet.com/line/football', timeout=30000, wait_until='domcontentloaded')
                await asyncio.sleep(5)
                
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
                                await asyncio.sleep(5)
                                consecutive_errors = 0
                                continue

                        print(f"⏳ Waiting {UPDATE_INTERVAL} seconds...\n")
                        await asyncio.sleep(UPDATE_INTERVAL)
                        
                        await page.reload(wait_until='domcontentloaded')
                        await asyncio.sleep(3)

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
                await context.close()
                await browser.close()
                if self.conn:
                    self.conn.close()
                    print("🔐 Database closed")


if __name__ == '__main__':
    parser = PrematchParser()
    asyncio.run(parser.run())

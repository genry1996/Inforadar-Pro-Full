import asyncio
import os
from datetime import datetime
from playwright.async_api import async_playwright
import pymysql
import time

# Настройки БД
DB_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'mysql_inforadar'),
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', 'ryban8991!'),
    'database': os.getenv('MYSQL_DB', 'inforadar'),
    'cursorclass': pymysql.cursors.DictCursor
}

UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', 3))
BOOKMAKER = os.getenv('BOOKMAKER', '22bet')

class LiveOddsParser:
    def __init__(self):
        self.conn = None
        
    def connect_db(self):
        """Подключение к MySQL"""
        try:
            self.conn = pymysql.connect(**DB_CONFIG)
            print(f"✅ Connected to MySQL: {DB_CONFIG['host']}")
            return True
        except Exception as e:
            print(f"❌ DB Connection Error: {e}")
            return False
    
    async def parse_live_matches(self, page):
        """Парсит все live матчи"""
        try:
            # Ждем загрузки live матчей
            await page.wait_for_selector('.c-events__item', timeout=10000)
            
            matches = await page.query_selector_all('.c-events__item')
            print(f"📊 Found {len(matches)} live matches")
            
            odds_data = []
            for match in matches[:10]:  # Берем первые 10 матчей
                try:
                    # Извлекаем данные матча
                    match_id = await match.get_attribute('data-event-id')
                    
                    teams = await match.query_selector('.c-events__teams')
                    teams_text = await teams.text_content() if teams else "Unknown vs Unknown"
                    
                    # Разделяем команды
                    teams_split = teams_text.split(' - ')
                    home_team = teams_split[0].strip() if len(teams_split) > 0 else "Unknown"
                    away_team = teams_split[1].strip() if len(teams_split) > 1 else "Unknown"
                    
                    # Получаем коэффициенты 1X2
                    odds_elements = await match.query_selector_all('.c-bets__bet')
                    
                    home_odd = None
                    draw_odd = None
                    away_odd = None
                    
                    if len(odds_elements) >= 3:
                        home_odd = await odds_elements[0].text_content()
                        draw_odd = await odds_elements[1].text_content()
                        away_odd = await odds_elements[2].text_content()
                    
                    odds_data.append({
                        'match_id': match_id,
                        'home_team': home_team,
                        'away_team': away_team,
                        'home_odd': float(home_odd) if home_odd else None,
                        'draw_odd': float(draw_odd) if draw_odd else None,
                        'away_odd': float(away_odd) if away_odd else None,
                        'sport': 'Football',  # TODO: определять автоматически
                        'league': 'Unknown',
                        'is_live': True
                    })
                    
                except Exception as e:
                    print(f"⚠️ Error parsing match: {e}")
                    continue
            
            return odds_data
            
        except Exception as e:
            print(f"❌ Error in parse_live_matches: {e}")
            return []
    
    def save_to_database(self, odds_data):
        """Сохраняет данные в БД"""
        if not odds_data:
            return
        
        try:
            cursor = self.conn.cursor()
            
            for odds in odds_data:
                cursor.execute("""
                    INSERT INTO odds_full_history 
                    (bookmaker, match_id, home_team, away_team, sport, league,
                     home_odd, draw_odd, away_odd, is_live, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    BOOKMAKER,
                    odds['match_id'],
                    odds['home_team'],
                    odds['away_team'],
                    odds['sport'],
                    odds['league'],
                    odds['home_odd'],
                    odds['draw_odd'],
                    odds['away_odd'],
                    odds['is_live'],
                    datetime.now()
                ))
            
            self.conn.commit()
            print(f"✅ Saved {len(odds_data)} odds records")
            
        except Exception as e:
            print(f"❌ Error saving to DB: {e}")
    
    async def run(self):
        """Главный цикл парсинга"""
        print(f"🚀 Starting 22bet LIVE parser")
        print(f"🔄 Update interval: {UPDATE_INTERVAL} seconds")
        
        if not self.connect_db():
            print("❌ Cannot start without DB connection")
            return
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                await page.goto('https://22bet.com/live/football', timeout=30000)
                print("✅ Loaded 22bet live page")
                
                while True:
                    try:
                        odds_data = await self.parse_live_matches(page)
                        self.save_to_database(odds_data)
                        
                        print(f"⏳ Waiting {UPDATE_INTERVAL} seconds...")
                        await asyncio.sleep(UPDATE_INTERVAL)
                        
                        # Обновляем страницу
                        await page.reload()
                        
                    except Exception as e:
                        print(f"❌ Error in main loop: {e}")
                        await asyncio.sleep(10)
                        
            except Exception as e:
                print(f"❌ Fatal error: {e}")
            finally:
                await browser.close()
                if self.conn:
                    self.conn.close()

if __name__ == '__main__':
    parser = LiveOddsParser()
    asyncio.run(parser.run())

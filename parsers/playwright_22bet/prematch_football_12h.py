# -*- coding: utf-8 -*-
"""
22bet PREMATCH Parser - КАК В ПРИЛОЖЕНИИ 22BET
Убраны: MLS+, Специальные ставки, Команда vs Игрок
"""
import asyncio, os, hashlib, pymysql, re
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "ryban8991!",
    "database": "inforadar",
    "charset": "utf8mb4"
}

PROXY_CONFIG = {"server": "http://213.137.91.35:12323", "username": "14ab48c9d85c1", "password": "5d234f6517"}
UPDATE_INTERVAL = 60
HOURS_AHEAD = 18

print(f"\n🚀 22bet PREMATCH Parser\n⏰ Interval: {UPDATE_INTERVAL}s | Window: {HOURS_AHEAD}h\n")

class PrematchParser:
    def __init__(self):
        self.conn, self.cursor, self.processed_keys = None, None, set()
    
    def connect_db(self):
        self.conn = pymysql.connect(**DB_CONFIG)
        self.cursor = self.conn.cursor()
        print("✅ MySQL connected\n")
    
    def parse_match_time(self, time_str):
        try:
            day, month = time_str.split()[0].split('/')
            hour, minute = time_str.split()[1].split(':')
            
            now = datetime.now()
            year = now.year
            match_dt = datetime(year, int(month), int(day), int(hour), int(minute))
            
            if match_dt < now:
                match_dt = datetime(year + 1, int(month), int(day), int(hour), int(minute))
            
            return match_dt
        except:
            return None
    
    def is_special_bet(self, full_text, team1, team2):
        """Определяет является ли это спецставкой"""
        combined = f"{team1} {team2} {full_text}".lower()
        
        # Список фраз которые указывают на спецставки
        special_patterns = [
            "специальные ставки",
            "special bet",
            "команда vs игрок",
            "mls+",
            "точный счет",
            "exact score",
            "anytime",
            "first goal",
            "last goal"
        ]
        
        for pattern in special_patterns:
            if pattern in combined:
                return True
        
        return False
    
    def is_valid_match(self, team1, team2):
        """Проверка валидности матча"""
        team1_lower = team1.lower()
        team2_lower = team2.lower()
        
        # Минимальная длина
        if len(team1) < 3 or len(team2) < 3:
            return False
        
        # Не одинаковые
        if team1_lower == team2_lower:
            return False
        
        # Не начинается с цифр
        if team1[0].isdigit() or team2[0].isdigit():
            return False
        
        # Не содержит +
        if "+" in team1 or "+" in team2:
            return False
        
        # Базовые запрещенные слова в названиях команд
        forbidden = ["home", "away", "total", "handicap", "corners", "cards"]
        for word in forbidden:
            if word in team1_lower or word in team2_lower:
                return False
        
        return True
    
    def clear_all_prematch(self):
        try:
            self.cursor.execute("""
                DELETE FROM odds_22bet 
                WHERE status = 'active' 
                AND sport = 'Football'
                AND bookmaker = '22bet'
            """)
            self.conn.commit()
        except:
            pass
    
    async def parse_prematch(self, page):
        await page.goto("https://22bet.com/line/football", wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(3000)
        print("✅ Page loaded")
        
        print("🔄 Auto-scrolling...")
        prev_count = 0
        for i in range(10):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            
            current_count = await page.evaluate("document.querySelectorAll('.c-events__item').length")
            
            if current_count == prev_count:
                print(f" ✅ Loaded {current_count} items\n")
                break
            prev_count = current_count
        
        events = await page.query_selector_all(".c-events__item")
        
        now = datetime.now()
        cutoff_time = now + timedelta(hours=HOURS_AHEAD)
        
        count = 0
        skipped = 0
        filtered_specials = 0
        time_pattern = r'\d{2}/\d{2}\s+\d{2}:\d{2}'
        
        for idx, event in enumerate(events, 1):
            try:
                full_text = await event.inner_text()
                lines = full_text.strip().split('\n')
                
                if len(lines) < 5:
                    continue
                
                time_match = None
                match_time_str = None
                team1_idx = None
                team2_idx = None
                
                for i in range(min(3, len(lines))):
                    if re.match(time_pattern, lines[i]):
                        match_time_str = lines[i]
                        time_match = self.parse_match_time(match_time_str)
                        if i + 2 < len(lines):
                            team1_idx = i + 1
                            team2_idx = i + 2
                        break
                
                if not time_match or team1_idx is None:
                    continue
                
                if time_match > cutoff_time:
                    skipped += 1
                    continue
                
                team1 = lines[team1_idx].strip()
                team2 = lines[team2_idx].strip()
                
                if not team1 or not team2:
                    continue
                
                # ПРОВЕРКА НА СПЕЦСТАВКИ (по полному тексту)
                if self.is_special_bet(full_text, team1, team2):
                    filtered_specials += 1
                    continue
                
                # ПРОВЕРКА ВАЛИДНОСТИ МАТЧА
                if not self.is_valid_match(team1, team2):
                    filtered_specials += 1
                    continue
                
                odds = re.findall(r'\b(\d+\.\d+)\b', full_text)
                if len(odds) < 3:
                    continue
                
                try:
                    odd_1 = float(odds[0])
                    odd_x = float(odds[1])
                    odd_2 = float(odds[2])
                except:
                    continue
                
                event_name = f"{team1} vs {team2}"
                unique_key = hashlib.md5(event_name.lower().encode()).hexdigest()
                
                if unique_key in self.processed_keys:
                    continue
                
                self.processed_keys.add(unique_key)
                
                self.cursor.execute("""
                    INSERT INTO odds_22bet (event_name, sport, league, odd_1, odd_x, odd_2, 
                                          status, bookmaker, updated_at, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                """, (event_name, "Football", "Unknown", 
                      round(odd_1, 2), round(odd_x, 2), round(odd_2, 2),
                      "active", "22bet"))
                
                count += 1
                
            except Exception as e:
                pass
        
        self.conn.commit()
        print(f"✅ Saved {count} real matches | 🚫 Filtered {filtered_specials} specials | ⏭️ Skipped {skipped}\n")
        return count
    
    async def run(self):
        self.connect_db()
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, proxy=PROXY_CONFIG)
            page = await browser.new_page()
            
            try:
                while True:
                    try:
                        self.clear_all_prematch()
                        self.processed_keys.clear()
                        await self.parse_prematch(page)
                        
                        print(f"⏳ Waiting {UPDATE_INTERVAL}s...\n" + "="*60)
                        await asyncio.sleep(UPDATE_INTERVAL)
                        
                    except Exception as e:
                        print(f"❌ Error: {e}")
                        await asyncio.sleep(10)
            except KeyboardInterrupt:
                print("\n⏹️ Stopped")
                await browser.close()
                if self.conn:
                    self.conn.close()

if __name__ == "__main__":
    parser = PrematchParser()
    asyncio.run(parser.run())

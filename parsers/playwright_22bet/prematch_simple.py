# -*- coding: utf-8 -*-
"""
22bet PREMATCH Parser - ИСПРАВЛЕННЫЙ SQL
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

print(f"\n🚀 22bet PREMATCH Parser (FINAL)\n🌐 Proxy: {PROXY_CONFIG['server']}\n⏰ Interval: {UPDATE_INTERVAL}s\n")

class PrematchParser:
    def __init__(self):
        self.conn, self.cursor, self.processed_keys = None, None, set()
    
    def connect_db(self):
        self.conn = pymysql.connect(**DB_CONFIG)
        self.cursor = self.conn.cursor()
        print("✅ MySQL connected")
    
    async def parse_prematch(self, page):
        await page.goto("https://22bet.com/line/football", wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(5000)
        print("✅ Page loaded")
        
        events = await page.query_selector_all(".c-events__item")
        print(f"📊 Found {len(events)} items\n")
        
        count = 0
        time_pattern = r'\d{2}/\d{2}\s+\d{2}:\d{2}'
        
        for idx, event in enumerate(events, 1):
            try:
                full_text = await event.inner_text()
                lines = full_text.strip().split('\n')
                
                # Пропускаем заголовки турниров
                if len(lines) < 5:
                    continue
                
                # Проверяем наличие времени в первых 3 строках
                time_match = None
                team1_idx = None
                team2_idx = None
                
                for i in range(min(3, len(lines))):
                    if re.match(time_pattern, lines[i]):
                        time_match = lines[i]
                        if i + 2 < len(lines):
                            team1_idx = i + 1
                            team2_idx = i + 2
                        break
                
                if not time_match or team1_idx is None:
                    continue
                
                team1 = lines[team1_idx].strip()
                team2 = lines[team2_idx].strip()
                
                # Пропускаем невалидные команды
                if not team1 or not team2 or "Unknown" in team1 or "Unknown" in team2:
                    continue
                
                # Извлекаем коэффициенты
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
                
                # ИСПРАВЛЕННЫЙ SQL БЕЗ event_id
                sql = """
                INSERT INTO odds_22bet (event_name, sport, league, odd_1, odd_x, odd_2, 
                                        status, bookmaker, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    odd_1=%s, odd_x=%s, odd_2=%s, updated_at=NOW()
                """
                self.cursor.execute(sql, (
                    event_name, "Football", "Unknown", 
                    round(odd_1, 2), round(odd_x, 2), round(odd_2, 2),
                    "prematch", "22bet",
                    round(odd_1, 2), round(odd_x, 2), round(odd_2, 2)
                ))
                count += 1
                print(f"  ✅ [{count}] {event_name} | {odd_1:.2f} / {odd_x:.2f} / {odd_2:.2f}")
                
            except Exception as e:
                pass
        
        self.conn.commit()
        print(f"\n✅ Saved {count} prematch matches\n")
        return count
    
    async def run(self):
        self.connect_db()
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, proxy=PROXY_CONFIG)
            page = await browser.new_page()
            
            while True:
                try:
                    await self.parse_prematch(page)
                    print(f"⏳ Waiting {UPDATE_INTERVAL}s...\n")
                    await asyncio.sleep(UPDATE_INTERVAL)
                except Exception as e:
                    print(f"❌ Error: {e}")
                    await asyncio.sleep(10)

if __name__ == "__main__":
    parser = PrematchParser()
    asyncio.run(parser.run())

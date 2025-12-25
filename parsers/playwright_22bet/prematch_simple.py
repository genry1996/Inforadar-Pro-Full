# -*- coding: utf-8 -*-

"""
22bet PREMATCH Parser v29 (New IPRoyal proxy)
"""

import asyncio
import pymysql
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "ryban8991!",
    "database": "inforadar",
    "charset": "utf8mb4"
}

PROXY_CONFIG = {
    "server": "http://46.182.207.241:12323",
    "username": "14ab0fcf235c2",
    "password": "380da05609"
}

UPDATE_INTERVAL = 60
HOURS_AHEAD = 12

HIGH_LIQ_LEAGUES = {
    "England. Premier League",
    "Spain. La Liga",
    "Germany. Bundesliga",
    "Italy. Serie A",
    "France. Ligue 1",
}

LOW_LIQ_WHITELIST = {
    "India. Santosh Trophy",
    "Vietnam Championship U19",
    "Honduras. Liga Nacional. Reserve League",
    "ЧЕМПИОНАТ ГОНДУРАСА",
}

EXCLUDE_KEYWORDS = [
    "ХОККЕЙ", "HOCKEY", "КХЛ", "KHL", "VHL", "ВХЛ",
    "БАСКЕТБОЛ", "BASKETBALL", "NBA", "НБА",
    "ТЕННИС", "TENNIS", "ВОЛЕЙБОЛ", "VOLLEYBALL",
    "MLS", "ВТБ", "ЛИГА ВТБ", "МХЛ"
]

print("\n⚽ 22bet PREMATCH - v29 (New proxy)")
print(f"⏰ Update: {UPDATE_INTERVAL}s | Window: {HOURS_AHEAD}h")
print(f"🌍 Proxy: {PROXY_CONFIG['server']}\n")


def classify_league(league_name: str):
    if league_name in HIGH_LIQ_LEAGUES:
        return "high", 0
    if league_name in LOW_LIQ_WHITELIST:
        return "low", 0
    return "low", 1


class PrematchParser:
    def __init__(self):
        self.conn, self.cursor = None, None
        self.seen_keys = set()

    def connect_db(self):
        self.conn = pymysql.connect(**DB_CONFIG)
        self.cursor = self.conn.cursor()
        print("✅ MySQL OK")

    def clear_old(self):
        now = datetime.now()
        cutoff = now + timedelta(hours=HOURS_AHEAD)
        stale_time = now - timedelta(minutes=5)
        
        self.cursor.execute(
            "DELETE FROM odds_22bet WHERE bookmaker='22bet' AND match_time IS NOT NULL AND match_time <= %s",
            (now,)
        )
        deleted_started = self.cursor.rowcount
        
        self.cursor.execute(
            "DELETE FROM odds_22bet WHERE bookmaker='22bet' AND match_time IS NOT NULL AND match_time > %s",
            (cutoff,)
        )
        deleted_outside = self.cursor.rowcount
        
        self.cursor.execute(
            "DELETE FROM odds_22bet WHERE bookmaker='22bet' AND updated_at < %s",
            (stale_time,)
        )
        deleted_stale = self.cursor.rowcount
        
        self.conn.commit()
        print(f"🧹 Deleted: {deleted_started} started | {deleted_outside} outside | {deleted_stale} stale")

    def parse_time(self, time_str: str):
        try:
            parts = time_str.strip().split()
            if len(parts) < 2:
                return None
            date_part, time_part = parts[0], parts[1]
            if "." in date_part:
                day, month = date_part.split(".")
            else:
                day, month = date_part.split("/")
            hour, minute = time_part.split(":")

            now = datetime.now()
            year = now.year
            dt = datetime(year, int(month), int(day), int(hour), int(minute))
            if dt < now:
                dt = datetime(year + 1, int(month), int(day), int(hour), int(minute))
            return dt
        except Exception:
            return None

    async def parse_prematch(self, page):
        try:
            print("📡 Loading football page...")
            await page.goto("https://22betluck.com/ru/line/football", timeout=90000)
            await page.wait_for_timeout(8000)
            
            current_url = page.url
            print(f"🌐 Current URL: {current_url}")
            
            if "football" not in current_url.lower():
                print(f"❌ WRONG PAGE! Expected football, got: {current_url}")
                return 0
                
        except Exception as e:
            print(f"❌ Page load error: {e}")
            return 0

        # Скролл до конца
        print("📜 Scrolling to bottom...")
        previous_height = 0
        scroll_iterations = 0
        max_iterations = 200
        
        while scroll_iterations < max_iterations:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(500)
            
            current_height = await page.evaluate("document.body.scrollHeight")
            if current_height == previous_height:
                print(f"✅ Reached bottom after {scroll_iterations} scrolls")
                break
            previous_height = current_height
            scroll_iterations += 1
            
            if scroll_iterations % 20 == 0:
                print(f"  ... прокручено {scroll_iterations} раз")

        # Раскрываем свернутые блоки
        print("🔽 Expanding collapsed league blocks...")
        for attempt in range(5):
            try:
                league_info = await page.evaluate("""
                    async () => {
                        let totalExpanded = 0;
                        const leagueBlocks = document.querySelectorAll('.c-events');
                        
                        for (const block of leagueBlocks) {
                            const header = block.querySelector('.c-events__item_head');
                            if (!header) continue;
                            
                            const visibleMatches = block.querySelectorAll('.c-events__item_col .c-events__item');
                            
                            if (visibleMatches.length < 100) {
                                const leagueName = header.querySelector('.c-events__name');
                                if (leagueName) {
                                    leagueName.click();
                                    totalExpanded++;
                                    await new Promise(r => setTimeout(r, 500));
                                }
                            }
                        }
                        
                        return totalExpanded;
                    }
                """)
                print(f"  Попытка {attempt + 1}: Раскрыто {league_info} блоков")
                if league_info == 0:
                    break
                await page.wait_for_timeout(3000)
            except Exception as e:
                print(f"  ⚠️ Expand error: {e}")

        league_blocks = await page.query_selector_all(".c-events")
        print(f"📊 Found {len(league_blocks)} league blocks")

        now = datetime.now()
        cutoff = now + timedelta(hours=HOURS_AHEAD)

        saved = 0
        skipped = 0
        self.seen_keys.clear()

        for idx, league_block in enumerate(league_blocks):
            try:
                league_name = "Unknown"
                head_liga = await league_block.query_selector(
                    ".c-events__item_head .c-events__name .c-events__liga"
                )
                if head_liga:
                    league_name = (await head_liga.inner_text()).strip()

                if any(keyword in league_name.upper() for keyword in EXCLUDE_KEYWORDS):
                    continue

                match_rows = await league_block.query_selector_all(
                    ".c-events__item_col .c-events__item"
                )

                for row in match_rows:
                    try:
                        time_el = await row.query_selector(".c-events__time.min span")
                        if not time_el:
                            skipped += 1
                            continue
                            
                        time_str = (await time_el.inner_text()).strip()
                        match_time = self.parse_time(time_str)
                        
                        if not match_time:
                            skipped += 1
                            continue
                            
                        if match_time > cutoff:
                            skipped += 1
                            continue

                        team_nodes = await row.query_selector_all(
                            ".c-events__name .c-events__teams .c-events__team"
                        )
                        if len(team_nodes) < 2:
                            skipped += 1
                            continue
                            
                        team1 = (await team_nodes[0].inner_text()).strip()
                        team2 = (await team_nodes[1].inner_text()).strip()

                        if (team1 == "Home" or team2 == "Away" or team1 == team2 or 
                            "Хозяева" in team1 or "Гости" in team2 or
                            team1 == "Хозяева" or team2 == "Гости"):
                            skipped += 1
                            continue

                        key = (league_name, team1, team2, match_time)
                        if key in self.seen_keys:
                            continue
                        self.seen_keys.add(key)

                        odds_nodes = await row.query_selector_all(
                            ".c-bets .c-bets__bet.c-bets__bet_sm"
                        )
                        if len(odds_nodes) < 3:
                            skipped += 1
                            continue

                        try:
                            odd_1 = float((await odds_nodes[0].inner_text()).strip())
                            odd_x = float((await odds_nodes[1].inner_text()).strip())
                            odd_2 = float((await odds_nodes[2].inner_text()).strip())
                        except Exception:
                            skipped += 1
                            continue

                        event_name = f"{team1} vs {team2}"
                        liquidity_level, is_suspicious = classify_league(league_name)

                        sql = """
                        INSERT INTO odds_22bet (
                            event_name, sport, league,
                            odd_1, odd_x, odd_2,
                            status, bookmaker,
                            match_time, liquidity_level, is_suspicious,
                            updated_at
                        )
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                        ON DUPLICATE KEY UPDATE
                            odd_1=%s, odd_x=%s, odd_2=%s,
                            match_time=%s,
                            league=%s,
                            liquidity_level=%s,
                            is_suspicious=%s,
                            status='active',
                            updated_at=NOW()
                        """

                        params = (
                            event_name, "Football", league_name,
                            round(odd_1, 2), round(odd_x, 2), round(odd_2, 2),
                            "active", "22bet", match_time, liquidity_level, is_suspicious,
                            round(odd_1, 2), round(odd_x, 2), round(odd_2, 2),
                            match_time, league_name, liquidity_level, is_suspicious,
                        )

                        try:
                            self.cursor.execute(sql, params)
                        except Exception as e:
                            print(f"❌ DB error for {event_name}: {e}")
                            self.conn.rollback()
                            skipped += 1
                            continue

                        saved += 1
                        time_left = (match_time - now).total_seconds() / 3600
                        
                        if "ЕГИПЕТ" in league_name.upper() or "ГОНДУРАС" in league_name.upper():
                            print(f"🎯 [{saved}] {event_name} | {league_name[:40]} | 💰 {odd_1:.2f}/{odd_x:.2f}/{odd_2:.2f} | ⏰ {time_left:.1f}h")
                        else:
                            print(f"✅ [{saved}] {event_name} | {league_name[:40]} | 💰 {odd_1:.2f}/{odd_x:.2f}/{odd_2:.2f} | ⏰ {time_left:.1f}h")

                    except Exception:
                        skipped += 1

            except Exception:
                skipped += 1

        self.conn.commit()
        print(f"\n✅ SAVED: {saved} | SKIPPED: {skipped}\n")
        return saved

    async def run(self):
        self.connect_db()
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                proxy=PROXY_CONFIG
            )
            page = await browser.new_page()
            
            while True:
                try:
                    self.clear_old()
                    await self.parse_prematch(page)
                    print(f"⏳ Next in {UPDATE_INTERVAL}s...\n")
                    await asyncio.sleep(UPDATE_INTERVAL)
                except Exception as e:
                    print(f"❌ Error: {e}")
                    await asyncio.sleep(15)


if __name__ == "__main__":
    parser = PrematchParser()
    asyncio.run(parser.run())

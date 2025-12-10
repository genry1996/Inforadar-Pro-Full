import asyncio
import logging
from playwright.async_api import async_playwright
import mysql.connector
import os
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "ryban8991!"),
        database=os.getenv("MYSQL_DB", "inforadar")
    )

try:
    conn = get_db_connection()
    conn.close()
    logger.info("✅ Успешное подключение к MySQL")
except Exception as e:
    logger.error(f"❌ Ошибка подключения к MySQL: {e}")
    exit(1)

PROXY_CONFIG = {
    "server": "http://213.137.91.35:12323",
    "username": "14ab48c9d85c1",
    "password": "5d234f6517"
}

MIRRORS = ["https://22betluck.com", "https://22bet.com"]
SPORTS = [
    {"name": "Football", "slug": "football"},
    {"name": "Basketball", "slug": "basketball"}
]

async def parse_22bet():
    async with async_playwright() as p:
        logger.info(f"Используем прокси: {PROXY_CONFIG['server']}")
        browser = await p.chromium.launch(
            headless=True,
            proxy=PROXY_CONFIG,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        page = await context.new_page()
        
        working_mirror = None
        for mirror in MIRRORS:
            try:
                logger.info(f"Пробуем: {mirror}")
                response = await page.goto(mirror, wait_until="domcontentloaded", timeout=15000)
                if response.status < 400:
                    logger.info(f"✅ Работает: {mirror}")
                    working_mirror = mirror
                    break
            except Exception as e:
                logger.warning(f"Недоступно {mirror}: {e}")
        
        if not working_mirror:
            logger.error("❌ Все зеркала недоступны")
            await browser.close()
            return
        
        for sport in SPORTS:
            sport_url = f"{working_mirror}/line/{sport['slug']}/"
            logger.info(f"Открываем: {sport_url}")
            
            try:
                await page.goto(sport_url, wait_until="networkidle", timeout=60000)
                
                selectors = [".c-events__item_col", ".c-events__liga"]
                for selector in selectors:
                    try:
                        await page.wait_for_selector(selector, timeout=10000)
                        logger.info(f"✅ Контент: {selector}")
                        break
                    except:
                        continue
                
                html = await page.content()
                debug_file = f"/app/debug_22bet_{sport['slug']}.html"
                with open(debug_file, "w", encoding="utf-8") as f:
                    f.write(html)
                logger.info(f"📄 HTML: {debug_file}")
                
                all_events = await page.query_selector_all(".c-events__item.c-events__item_col")
                logger.info(f"📊 Найдено событий: {len(all_events)}")
                
                conn = get_db_connection()
                cursor = conn.cursor()
                
                matches_count = 0
                
                for idx, event in enumerate(all_events[:50]):  # Парсим ВСЕ события
                    try:
                        logger.info(f"\n===== СОБЫТИЕ {idx+1} =====")
                        
                        # ===== ЛОГИРОВАНИЕ HTML СОБЫТИЯ =====
                        event_html = await event.inner_html()
                        logger.info(f"EVENT HTML:\n{event_html[:600]}\n")
                        
                        # Команды
                        teams = await event.query_selector_all(".c-events__team")
                        logger.info(f"DEBUG: Найдено команд: {len(teams)}")
                        
                        if len(teams) >= 2:
                            home_team = (await teams[0].inner_text()).strip()
                            away_team = (await teams[1].inner_text()).strip()
                            logger.info(f"DEBUG: ✓ Команды: {home_team} vs {away_team}")
                        else:
                            logger.info(f"DEBUG: ✗ Команд < 2, пропускаю")
                            continue
                        
                        # Коэффициенты
                        odds_elems = await event.query_selector_all(".c-bets__inner")
                        logger.info(f"DEBUG: Найдено коэффициентов: {len(odds_elems)}")
                        
                        odds_list = []
                        for odd_elem in odds_elems[:5]:
                            try:
                                odd_val = float(await odd_elem.inner_text())
                                odds_list.append(odd_val)
                            except Exception as e:
                                logger.debug(f"Ошибка парсинга коэффициента: {e}")
                        
                        logger.info(f"DEBUG: Распарсено коэффициентов: {len(odds_list)}")
                        
                        if len(odds_list) < 3:
                            logger.info(f"DEBUG: ✗ Коэффициентов < 3, пропускаю")
                            continue
                        
                        odd_1 = odds_list[0]
                        odd_x = odds_list[1]
                        odd_2 = odds_list[2]
                        
                        logger.info(f"DEBUG: ✓ Коэффициенты: {odd_1}, {odd_x}, {odd_2}")
                        
                        # ===== ВСТАВЛЯЕМ В ТАБЛИЦУ events =====
                        cursor.execute("""
                            INSERT INTO events (sport, league, home_team, away_team, match_time, status)
                            VALUES (%s, %s, %s, %s, %s, 'scheduled')
                            ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)
                        """, (sport['name'], "Mixed", home_team, away_team, None))
                        
                        event_id = cursor.lastrowid
                        
                        # ===== ВСТАВЛЯЕМ В ТАБЛИЦУ odds =====
                        cursor.execute("""
                            INSERT INTO odds (event_id, bookmaker, market_type, odd_1, odd_x, odd_2)
                            VALUES (%s, %s, '1x2', %s, %s, %s)
                        """, (event_id, "22bet", odd_1, odd_x, odd_2))
                        
                        matches_count += 1
                        logger.info(f"✓ УСПЕШНО: {home_team} vs {away_team} | {odd_1:.2f}, {odd_x:.2f}, {odd_2:.2f}\n")
                        
                    except Exception as e:
                        logger.error(f"❌ Ошибка события: {e}\n")
                
                conn.commit()
                cursor.close()
                conn.close()
                logger.info(f"🎉 [{sport['name']}] Вставлено: {matches_count}")
                
            except Exception as e:
                logger.error(f"❌ Ошибка {sport['name']}: {e}")
        
        await browser.close()

async def main():
    logger.info("=== Старт парсера 22BET ===")
    while True:
        try:
            await parse_22bet()
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
        logger.info("💤 Спим 60 сек...")
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())

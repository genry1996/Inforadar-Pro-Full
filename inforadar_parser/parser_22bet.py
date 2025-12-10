import asyncio
import logging
from playwright.async_api import async_playwright
import mysql.connector
import os
from datetime import datetime

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

# MySQL подключение
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "ryban8991!"),
        database=os.getenv("MYSQL_DB", "inforadar")
    )

# Проверка подключения
try:
    conn = get_db_connection()
    conn.close()
    logger.info("✅ Успешное подключение к MySQL")
except Exception as e:
    logger.error(f"❌ Ошибка подключения к MySQL: {e}")
    exit(1)

# Прокси
PROXY_CONFIG = {
    "server": "http://213.137.91.35:12323",
    "username": "7kn8p6sBjU",
    "password": "wifi;ru;;;",
}

# Зеркала 22bet
MIRRORS = [
    "https://22betluck.com",
    "https://22bet.com",
]

# Спорты для парсинга
SPORTS = [
    {"name": "Football", "slug": "football"},
    {"name": "Basketball", "slug": "basketball"},
]

async def parse_22bet():
    async with async_playwright() as p:
        logger.info(f"Используем Playwright прокси: {PROXY_CONFIG['server']}")
        
        browser = await p.chromium.launch(
            headless=True,
            proxy=PROXY_CONFIG,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ]
        )
        
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # Убираем webdriver флаги
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)
        
        page = await context.new_page()
        
        # Пробуем зеркала
        working_mirror = None
        for mirror in MIRRORS:
            try:
                logger.info(f"Пробуем зеркало: {mirror}")
                response = await page.goto(mirror, wait_until="domcontentloaded", timeout=15000)
                
                if response.status < 400:
                    logger.info(f"✅ Зеркало работает: {mirror}")
                    working_mirror = mirror
                    break
            except Exception as e:
                logger.warning(f"Зеркало {mirror} недоступно: {e}")
        
        if not working_mirror:
            logger.error("❌ Все зеркала недоступны")
            await browser.close()
            return
        
        # Парсим каждый спорт
        for sport in SPORTS:
            sport_url = f"{working_mirror}/line/{sport['slug']}/"
            logger.info(f"Открываем: {sport_url}")
            
            try:
                await page.goto(sport_url, wait_until="networkidle", timeout=60000)
                
                # Ждём появления контента (несколько вариантов селекторов)
                selectors = [
                    ".c-events__league",
                    ".c-events__liga",
                    "[class*='event']",
                ]
                
                content_loaded = False
                for selector in selectors:
                    try:
                        await page.wait_for_selector(selector, timeout=10000)
                        logger.info(f"✅ Контент найден по селектору: {selector}")
                        content_loaded = True
                        break
                    except:
                        continue
                
                if not content_loaded:
                    logger.warning(f"⚠️ Контент не загрузился за 30 сек для {sport['name']}")
                
                # Сохраняем HTML для отладки
                html = await page.content()
                debug_file = f"/app/debug_22bet_{sport['slug']}.html"
                with open(debug_file, "w", encoding="utf-8") as f:
                    f.write(html)
                logger.info(f"📄 HTML сохранён: {debug_file}")
                
                # Ищем блоки матчей
                leagues = await page.query_selector_all(".c-events__league, .c-events__liga")
                
                if not leagues:
                    logger.warning(f"Блоки лиг не найдены для {sport['name']}")
                    # Пробуем альтернативный селектор
                    leagues = await page.query_selector_all("[class*='league']")
                
                logger.info(f"Найдено блоков лиг: {len(leagues)}")
                
                matches_count = 0
                conn = get_db_connection()
                cursor = conn.cursor()
                
                for league in leagues[:5]:  # Ограничим первыми 5 лигами для теста
                    try:
                        league_name = await league.inner_text()
                        logger.info(f"  Лига: {league_name[:50]}...")
                        
                        # Ищем матчи внутри лиги
                        events = await league.query_selector_all(".c-events-scoreboard, [class*='event-item']")
                        
                        for event in events[:3]:  # Первые 3 матча из лиги
                            try:
                                event_text = await event.inner_text()
                                
                                # Простая вставка для теста (потом доработаешь структуру)
                                cursor.execute("""
                                    INSERT INTO odds_raw (bookmaker, sport, league, event_data, parsed_at)
                                    VALUES (%s, %s, %s, %s, %s)
                                    ON DUPLICATE KEY UPDATE parsed_at = VALUES(parsed_at)
                                """, ("22bet", sport['name'], league_name[:100], event_text[:500], datetime.now()))
                                
                                matches_count += 1
                            except Exception as e:
                                logger.error(f"Ошибка парсинга события: {e}")
                    
                    except Exception as e:
                        logger.error(f"Ошибка парсинга лиги: {e}")
                
                conn.commit()
                cursor.close()
                conn.close()
                
                logger.info(f"✅ [{sport['name']}] Вставлено матчей: {matches_count}")
                
            except Exception as e:
                logger.error(f"Ошибка парсинга {sport['name']}: {e}")
        
        await browser.close()

# Основной цикл
async def main():
    logger.info("=== Старт Playwright-парсера 22BET ===")
    
    while True:
        try:
            await parse_22bet()
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
        
        logger.info("Спим 60 сек...")
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())

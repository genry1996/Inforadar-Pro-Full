import asyncio
import logging
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')

async def debug_betwatch():
    async with async_playwright() as p:
        logging.info("🚀 Launching browser for DEBUG...")
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        logging.info("📄 Going to betwatch.fr/money...")
        await page.goto('https://betwatch.fr/money', wait_until='domcontentloaded', timeout=60000)
        
        logging.info("🔴 Clicking LIVE...")
        try:
            await page.click('a:has-text("LIVE")', timeout=10000)
            await page.wait_for_timeout(5000) # Ждем подгрузку
        except:
            logging.info("⚠️ Could not click LIVE (maybe already active or not found)")

        logging.info("🕵️ LOOKING FOR ANY ROWS...")
        
        # 1. Пробуем найти хоть какие-то таблицы
        tables = await page.query_selector_all('table')
        logging.info(f"📊 Found {len(tables)} tables")
        
        # 2. Пробуем найти строки в первой таблице
        if tables:
            rows = await tables[0].query_selector_all('tr')
            logging.info(f"📝 Found {len(rows)} rows in first table")
            
            # Печатаем HTML первой строки (не хедера)
            if len(rows) > 1:
                html = await rows[1].inner_html()
                logging.info(f"\n🔍 ROW HTML SNIPPET:\n{html[:1000]}...\n")
                
                # Ищем атрибуты самого TR
                outer = await rows[1].evaluate("el => el.outerHTML")
                logging.info(f"\n🔍 ROW OUTER HTML:\n{outer[:500]}...\n")
        
        # 3. Если таблиц нет, ищем DIV-ы, похожие на матчи
        else:
            logging.info("⚠️ No tables found! Checking DIVs...")
            content = await page.content()
            logging.info(f"📄 Page content length: {len(content)}")
            logging.info(f"📄 Page snippet: {content[:1000]}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_betwatch())

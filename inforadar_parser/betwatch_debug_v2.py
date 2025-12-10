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
        except:
            logging.info("⚠️ Could not click LIVE")

        logging.info("⏳ Waiting for content to render (5 seconds)...")
        await page.wait_for_timeout(5000)

        logging.info("🕵️ SEARCHING FOR MATCH ROWS...")
        
        # Попробуем разные селекторы
        selectors_to_try = [
            'div[data-event-id]',
            'div.row',
            'div.match',
            'div[class*="event"]',
            'div[class*="match"]',
            'tr',
            'tbody tr',
            'div.sc-',  # styled-components
        ]
        
        for selector in selectors_to_try:
            try:
                elements = await page.query_selector_all(selector)
                if len(elements) > 0:
                    logging.info(f"✅ FOUND {len(elements)} elements with selector: '{selector}'")
                    
                    # Выводим HTML первого найденного элемента
                    if len(elements) > 0:
                        html = await elements[0].inner_html()
                        logging.info(f"\n📌 FIRST ELEMENT HTML:\n{html[:800]}...\n")
                        
                        outer = await elements[0].evaluate("el => el.outerHTML")
                        logging.info(f"\n📌 OUTER HTML:\n{outer[:800]}...\n")
                    break
            except Exception as e:
                logging.info(f"⚠️ Selector '{selector}' failed: {str(e)[:50]}")
        
        # Если ничего не нашли, посмотрим на весь контент
        logging.info("\n🔍 LOOKING FOR ANY DIVs WITH 'data-' ATTRIBUTES...")
        content = await page.content()
        
        # Ищем все уникальные data-* атрибуты
        import re
        data_attrs = set(re.findall(r'data-(\w+)="[^"]*"', content))
        logging.info(f"📊 Found data-* attributes: {data_attrs}")
        
        # Ищем классы, которые выглядят как идентификаторы
        logging.info("\n🔍 SEARCHING FOR ELEMENTS WITH CLASS NAMES...")
        class_matches = set(re.findall(r'class="([^"]*(?:event|match|row|live)[^"]*)"', content, re.IGNORECASE))
        logging.info(f"📊 Found class names with 'event/match/row/live': {list(class_matches)[:10]}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_betwatch())

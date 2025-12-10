import asyncio
import logging
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')

async def debug_betwatch():
    async with async_playwright() as p:
        logging.info("🚀 Launching browser...")
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        logging.info("📄 Going to betwatch.fr/money...")
        await page.goto('https://betwatch.fr/money', wait_until='domcontentloaded', timeout=60000)
        
        logging.info("⏳ Initial wait for page to fully load...")
        await page.wait_for_timeout(3000)
        
        # Проверяем, есть ли LIVE кнопка и активна ли она
        logging.info("🔍 Searching for LIVE button...")
        live_buttons = await page.query_selector_all('a, button')
        for i, btn in enumerate(live_buttons[:20]):
            text = await btn.inner_text()
            if 'LIVE' in text.upper() or 'FOOTBALL' in text.upper():
                logging.info(f"  #{i}: {text[:50]}")
        
        # Пробуем разные способы нажать на LIVE
        logging.info("🔴 Attempting to activate LIVE tab...")
        
        # Способ 1: по текст-селектору
        try:
            live_btn = await page.query_selector('a:has-text("LIVE")')
            if live_btn:
                logging.info("✅ Found LIVE button with 'a:has-text(LIVE)'")
                await live_btn.click()
                await page.wait_for_timeout(2000)
            else:
                logging.info("⚠️ No LIVE button found with 'a:has-text(LIVE)'")
        except Exception as e:
            logging.info(f"⚠️ Click failed: {str(e)[:100]}")
        
        # Способ 2: поищем футбол селектор
        try:
            football_btn = await page.query_selector('[href*="football"]')
            if football_btn:
                logging.info("✅ Found football button")
                await football_btn.click()
                await page.wait_for_timeout(2000)
        except:
            pass
        
        logging.info("⏳ Waiting 5 seconds for content to render...")
        await page.wait_for_timeout(5000)
        
        # Теперь ищем матчи
        logging.info("🕵️ SEARCHING FOR MATCH ROWS WITH MULTIPLE STRATEGIES...")
        
        # Стратегия 1: поищем по классам tailwind
        selectors_to_try = [
            'div[data-test*="match"]',
            'div[data-test*="event"]',
            'div[role="row"]',
            '.match-row',
            '.event-row',
            '[data-qa*="match"]',
            '[data-qa*="event"]',
            'article',
            'section',
            'li[data-',
            'div.relative',  # Generic container
            'button:has(span)',  # Button with span children
        ]
        
        found_something = False
        for selector in selectors_to_try:
            try:
                elements = await page.query_selector_all(selector)
                if len(elements) > 5:  # Ищем много элементов, чтобы исключить навигацию
                    logging.info(f"✅ FOUND {len(elements)} elements with selector: '{selector}'")
                    
                    # Показываем первые 3
                    for idx, elem in enumerate(elements[:3]):
                        text = await elem.inner_text()
                        html = await elem.inner_html()
                        logging.info(f"\n  Element #{idx}:")
                        logging.info(f"    TEXT: {text[:150]}")
                        logging.info(f"    HTML: {html[:200]}")
                    
                    found_something = True
                    break
            except Exception as e:
                pass
        
        if not found_something:
            logging.info("❌ Could not find any match rows!")
            logging.info("\n🔍 FULL PAGE ANALYSIS:")
            
            # Выведем структуру главного контента
            main = await page.query_selector('main')
            if main:
                logging.info("✅ Found <main> element")
                html = await main.inner_html()
                logging.info(f"MAIN HTML (first 1500 chars):\n{html[:1500]}")
            else:
                logging.info("❌ No <main> element found")
                
                # Ищем body
                body = await page.query_selector('body')
                if body:
                    html = await body.inner_html()
                    logging.info(f"BODY HTML (first 1500 chars):\n{html[:1500]}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_betwatch())

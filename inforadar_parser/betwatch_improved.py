import asyncio
import logging
import json
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')

async def debug_betwatch_improved():
    """
    Улучшенный мониторинг Betwatch API с поддержкой Cloudflare
    """
    async with async_playwright() as p:
        logging.info("🚀 Launching browser...")
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Увеличиваем timeout для Cloudflare
        page.set_default_timeout(120000)
        page.set_default_navigation_timeout(120000)
        
        api_responses = []
        
        async def handle_response(response):
            try:
                # Ищем реальные API запросы (исключаем Cloudflare)
                url = response.url
                if any(x in url for x in ['api', 'graphql', 'odds', 'event', 'match', 'football']) and \
                   'cloudflare' not in url and 'analytics' not in url:
                    logging.info(f"📡 API: {url[:80]}")
                    
                    try:
                        if response.status == 200:
                            data = await response.json()
                            logging.info(f"✅ JSON: {str(data)[:200]}")
                            api_responses.append({'url': url, 'data': data})
                    except:
                        logging.info(f"   Status: {response.status}")
            except:
                pass
        
        page.on("response", handle_response)
        
        try:
            logging.info("📄 Going to betwatch.fr/money...")
            # Ждём load event вместо networkidle (быстрее)
            await page.goto('https://betwatch.fr/money', wait_until='load', timeout=90000)
            
            logging.info("⏳ Page loaded, waiting for JS to render...")
            await page.wait_for_timeout(5000)
            
            # Пробуем кликнуть на футбол
            logging.info("🔴 Looking for football button...")
            try:
                btn = await page.query_selector('a[href*="football"]')
                if btn:
                    logging.info("✅ Found, clicking...")
                    await btn.click()
                    await page.wait_for_timeout(3000)
            except:
                logging.info("⚠️ No button found, skipping")
            
            await page.wait_for_timeout(3000)
            
            # Выводим результаты
            logging.info("\n" + "="*80)
            logging.info("📊 CAPTURED API RESPONSES:")
            logging.info("="*80)
            
            if api_responses:
                for i, resp in enumerate(api_responses, 1):
                    logging.info(f"\n#{i} URL: {resp['url']}")
                    logging.info(f"Data: {json.dumps(resp['data'], indent=2)[:800]}")
            else:
                logging.info("❌ No API data captured")
            
            # Проверяем localStorage
            local_data = await page.evaluate("() => JSON.stringify(localStorage)")
            if local_data != "{}":
                logging.info(f"\n📦 LocalStorage: {local_data[:300]}")
            
            # Получаем текстовый контент
            text = await page.inner_text('body')
            matches_count = text.count('vs') + text.count('VS')
            logging.info(f"\n📄 Page text contains ~{matches_count} potential matches")
            
        except Exception as e:
            logging.error(f"❌ Error: {str(e)[:200]}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_betwatch_improved())

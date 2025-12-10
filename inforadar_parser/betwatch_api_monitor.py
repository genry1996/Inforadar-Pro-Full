import asyncio
import logging
import json
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')

async def debug_betwatch_api():
    """
    Перехватываем API запросы вместо парсинга DOM
    Betwatch использует API для загрузки матчей
    """
    async with async_playwright() as p:
        logging.info("🚀 Launching browser for API monitoring...")
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Переменная для сохранения API ответов
        api_responses = []
        
        # Перехватываем все API запросы
        async def handle_response(response):
            try:
                # Ищем API запросы с матчами
                if 'api' in response.url or 'graphql' in response.url or '/odds' in response.url:
                    logging.info(f"📡 API Response: {response.url[:100]}")
                    
                    # Пробуем прочитать JSON
                    try:
                        data = await response.json()
                        logging.info(f"✅ Got JSON data: {str(data)[:300]}")
                        api_responses.append({
                            'url': response.url,
                            'status': response.status,
                            'data': data
                        })
                    except:
                        # Если не JSON, просто логируем
                        logging.info(f"⚠️ Response not JSON, status: {response.status}")
            except Exception as e:
                pass
        
        # Подписываемся на все ответы
        page.on("response", handle_response)
        
        logging.info("📄 Going to betwatch.fr/money...")
        await page.goto('https://betwatch.fr/money', wait_until='networkidle', timeout=60000)
        
        logging.info("⏳ Waiting for API requests to complete (3 seconds)...")
        await page.wait_for_timeout(3000)
        
        # Ищем футбол
        logging.info("🔴 Clicking football/LIVE button...")
        try:
            football_btn = await page.query_selector('[href*="football"]')
            if football_btn:
                logging.info("✅ Found football button")
                await football_btn.click()
                await page.wait_for_timeout(3000)
        except:
            logging.info("⚠️ Could not click football button")
        
        logging.info("⏳ Waiting for more API requests (5 seconds)...")
        await page.wait_for_timeout(5000)
        
        # Выводим все перехваченные API запросы
        logging.info("\n" + "="*80)
        logging.info("📊 CAPTURED API REQUESTS:")
        logging.info("="*80)
        
        if api_responses:
            for i, resp in enumerate(api_responses):
                logging.info(f"\n#{i+1} URL: {resp['url']}")
                logging.info(f"   Status: {resp['status']}")
                logging.info(f"   Data: {json.dumps(resp['data'], indent=2)[:500]}")
        else:
            logging.info("❌ No API responses captured!")
            logging.info("\n🔍 TRYING ALTERNATIVE: Looking for fetch/XMLHttpRequest calls...")
        
        # Пробуем получить всё, что загружалось
        logging.info("\n" + "="*80)
        logging.info("🔍 ANALYZING PAGE CONTENT:")
        logging.info("="*80)
        
        # Ищем скрипты с данными
        scripts = await page.query_selector_all('script')
        logging.info(f"Found {len(scripts)} script tags")
        
        # Ищем window переменные с данными
        data_vars = await page.evaluate("""
            () => {
                const keys = Object.keys(window);
                const dataKeys = keys.filter(k => 
                    k.includes('data') || 
                    k.includes('odds') || 
                    k.includes('match') ||
                    k.includes('event')
                ).slice(0, 20);
                return dataKeys;
            }
        """)
        
        logging.info(f"Found window variables with data: {data_vars}")
        
        # Пробуем получить локальное хранилище
        local_storage = await page.evaluate("() => JSON.stringify(localStorage)")
        if local_storage != "{}":
            logging.info(f"\n📦 LocalStorage content:\n{local_storage[:500]}")
        
        # Пробуем sessionStorage
        session_storage = await page.evaluate("() => JSON.stringify(sessionStorage)")
        if session_storage != "{}":
            logging.info(f"\n📦 SessionStorage content:\n{session_storage[:500]}")
        
        # Смотрим HTML основной контент
        main = await page.query_selector('main')
        if main:
            text_content = await main.inner_text()
            logging.info(f"\n📄 Main content (first 500 chars):\n{text_content[:500]}")
        
        await browser.close()
        
        logging.info("\n✅ Debug completed!")

if __name__ == "__main__":
    asyncio.run(debug_betwatch_api())

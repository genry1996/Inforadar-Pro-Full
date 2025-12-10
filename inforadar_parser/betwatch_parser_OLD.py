import asyncio
import logging
import os
import requests
from datetime import datetime
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

CONFIG = {
    "pause_sec": 5,
    "timeOddMin": 3,
    "koefPercentMin": 10,
    "koefPercentMax": 30,
    "koef_min": 1.4,
    "koef_max": 10,
    "money_min": 5000,
    "browserHeadless": True,
}

async def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        params = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        requests.get(url, params=params, timeout=5)
        logger.info("📱 Telegram отправлен!")
    except Exception as e:
        logger.error(f"❌ Telegram ошибка: {e}")

async def parse_betwatch():
    async with async_playwright() as p:
        logger.info("🚀 Запускаем браузер Betwatch парсера...")
        browser = await p.chromium.launch(
            headless=CONFIG["browserHeadless"],
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        page = await browser.new_page()
        
        try:
            logger.info("📄 Переходим на betwatch.fr/money...")
            await page.goto("https://www.betwatch.fr/money", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)
            
            logger.info("🔴 Выбираем LIVE матчи...")
            try:
                await page.evaluate("""
                    const el = document.evaluate(
                        '/html/body/div[3]/div[2]/div/div[2]/div/div/label',
                        document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                    ).singleNodeValue;
                    if (el) el.click();
                """)
            except:
                pass
            
            await asyncio.sleep(2)
            
            # Переменные отслеживания
            event_tracking = {}
            event_reported = set()
            
            logger.info("✅ Парсер запущен! Мониторим события...")
            
            cycle = 0
            while True:
                try:
                    cycle += 1
                    
                    # ПАРСИМ moneywayDetails
                    events_data = await page.evaluate("""
                        () => {
                            try {
                                if (typeof Alpine !== 'undefined' && Alpine.store) {
                                    const store = Alpine.store('data');
                                    const details = store.moneywayDetails || [];
                                    
                                    // Фильтруем только LIVE события (l === 1)
                                    return details.filter(m => m.l === 1).slice(0, 30);
                                }
                                return [];
                            } catch(e) {
                                console.error('Error:', e);
                                return [];
                            }
                        }
                    """)
                    
                    if len(events_data) > 0:
                        logger.info(f"📊 Найдено LIVE событий: {len(events_data)}")
                        
                        for event in events_data:
                            event_id = event.get('e')
                            event_name = event.get('m', 'Unknown')
                            league = event.get('ln', 'Unknown')
                            issues = event.get('i', [])
                            
                            if not event_id or not issues:
                                continue
                            
                            for idx, issue in enumerate(issues):
                                if len(issue) < 3:
                                    continue
                                
                                bet_type = issue[0]
                                money = issue[1]
                                odd = issue[2]
                                prev_odd = issue[3] if len(issue) > 3 else odd
                                
                                key = f"{event_id}_{idx}"
                                
                                # Фильтры
                                if money < CONFIG["money_min"]:
                                    continue
                                if not (CONFIG["koef_min"] <= odd <= CONFIG["koef_max"]):
                                    continue
                                
                                # Первое появление
                                if key not in event_tracking:
                                    event_tracking[key] = {
                                        "time": datetime.now(),
                                        "odd": odd,
                                        "name": event_name,
                                        "league": league,
                                        "bet_type": bet_type,
                                        "money": money,
                                    }
                                    logger.info(f"✓ {event_name} [{league}] | {bet_type}: €{money:,.0f} @ {odd}")
                                else:
                                    # Проверяем падение
                                    tracked = event_tracking[key]
                                    time_diff = (datetime.now() - tracked["time"]).total_seconds()
                                    
                                    if odd < tracked["odd"] and time_diff <= CONFIG["timeOddMin"] * 60:
                                        percent_drop = ((tracked["odd"] - odd) * 100 / tracked["odd"])
                                        
                                        if CONFIG["koefPercentMin"] <= percent_drop <= CONFIG["koefPercentMax"]:
                                            if key not in event_reported:
                                                msg = (
                                                    f"🚨 <b>SHARP MOVE</b>\n"
                                                    f"⚽ {event_name}\n"
                                                    f"🏆 {league}\n"
                                                    f"💰 {bet_type}: €{money:,.0f}\n"
                                                    f"📉 {tracked['odd']:.2f} → {odd:.2f} ({percent_drop:.1f}%)\n"
                                                    f"⏱ {int(time_diff)}s"
                                                )
                                                logger.info(f"📢 ALERT: {event_name} | {bet_type} | -{percent_drop:.1f}%")
                                                await send_telegram(msg)
                                                event_reported.add(key)
                                    
                                    # Обновляем
                                    event_tracking[key]["odd"] = odd
                                    event_tracking[key]["time"] = datetime.now()
                    else:
                        logger.info(f"🔍 Цикл #{cycle}: LIVE событий не найдено")
                    
                    await asyncio.sleep(CONFIG["pause_sec"])
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле: {e}")
                    await asyncio.sleep(5)
        
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}")
        finally:
            await browser.close()

async def main():
    logger.info("=== Старт парсера BETWATCH ===")
    while True:
        try:
            await parse_betwatch()
        except Exception as e:
            logger.error(f"❌ Критическая ошибка main: {e}")
        logger.info("💤 Рестартуем через 30 сек...")
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())

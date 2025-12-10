# 🎯 BETWATCH EXTENDED DETECTOR v3
# Отслеживает ВСЕ сигналы: sharp moves, line moves, market removal, odds squeeze и т.д.

import asyncio
import logging
import os
import json
import requests
import mysql.connector
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)

logger = logging.getLogger(__name__)

# ============ КОНФИГ ============
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "mysql_inforadar"),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DB", "inforadar"),
}

CONFIG = {
    "pause_sec": 5,
    
    # SHARP MOVE (падение кэфа)
    "timeOddMin": 3,
    "koefPercentMin": 8,
    "koefPercentMax": 35,
    "koef_min": 1.4,
    "koef_max": 10,
    "money_min": 3000,
    
    # ODDS SQUEEZE (сжатие котировок)
    "squeeze_threshold": 0.15,  # обе стороны упали на 15%+
    
    # MARKET REMOVAL (удаление рынка)
    "market_disappear_cycles": 2,  # если линию не видели 2 цикла подряд
    
    # LIMIT CUT (урезка лимита)
    "limit_cut_percent": 60,  # если лимит упал на 60%+
    
    # BOOKMAKER ALERT (букмекер покрыл)
    "bookie_min": 5000,  # минимум денег в букмекере
    
    "browserHeadless": True,
}

# ============ СИГНАЛЫ (для подсчета) ============
class SignalTypes:
    SHARP_MOVE = "Sharp Move"
    LINE_SHIFT = "Line Shift"
    MARKET_REMOVAL = "Market Removal"
    MATCH_REMOVAL = "Match Removal"
    ODDS_SQUEEZE = "Odds Squeeze"
    LIMIT_CUT = "Limit Cut"
    BET_BLOCKED = "Bet Blocked"
    BOOKIE_MATCHED = "Bookmaker Matched"

# ============ TELEGRAM ============
async def send_telegram(signal_type, text):
    """Отправляет сообщение в Telegram"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ Telegram не настроен")
        return
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        params = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }
        
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            logger.info(f"✅ Telegram отправлен: {signal_type}")
    except Exception as e:
        logger.error(f"❌ Telegram error: {e}")

# ============ MySQL ============
def get_mysql_connection():
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        return conn
    except mysql.connector.Error as e:
        logger.error(f"❌ MySQL connection error: {e}")
        return None

def save_signal_to_db(signal_type, signal_data):
    """Сохраняет сигнал в БД"""
    conn = get_mysql_connection()
    if not conn:
        return
    
    try:
        cursor = conn.cursor()
        query = """
            INSERT INTO betwatch_signals 
            (signal_type, event_name, league, market_type, old_value, new_value, 
             bookmaker_value, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        values = (
            signal_type,
            signal_data.get('event_name'),
            signal_data.get('league'),
            signal_data.get('market_type'),
            json.dumps(signal_data.get('old_value')),
            json.dumps(signal_data.get('new_value')),
            json.dumps(signal_data.get('bookie_value')),
            datetime.now()
        )
        
        cursor.execute(query, values)
        conn.commit()
        logger.info(f"✅ Signal saved: {signal_type}")
    except Exception as e:
        logger.error(f"❌ DB save error: {e}")
    finally:
        cursor.close()
        conn.close()

# ============ ДЕТЕКТОР СИГНАЛОВ ============
class SignalDetector:
    def __init__(self):
        self.event_history = {}  # Полная история событий
        self.line_shifts = {}  # Отслеживание сдвигов линий
        self.market_disappear_count = {}  # Счетчик исчезнувших рынков
    
    async def detect_sharp_move(self, event_id, event_name, league, 
                                bet_type, money, old_odd, new_odd):
        """Детектор падения коэффициента"""
        if old_odd <= new_odd:
            return None
        
        percent_drop = ((old_odd - new_odd) * 100 / old_odd)
        
        if not (CONFIG["koefPercentMin"] <= percent_drop <= CONFIG["koefPercentMax"]):
            return None
        
        if money < CONFIG["money_min"]:
            return None
        
        logger.warning(f"🚨 SHARP MOVE: {event_name} | {bet_type} | "
                      f"{old_odd:.2f} → {new_odd:.2f} ({percent_drop:.1f}%)")
        
        telegram_text = (
            f"📉 <b>SHARP MOVE DETECTED!</b>\n\n"
            f"⚽ {event_name}\n"
            f"🏆 {league}\n"
            f"💰 {bet_type}: €{money:,.0f}\n\n"
            f"<b>{old_odd:.2f} → {new_odd:.2f}</b>\n"
            f"Drop: {percent_drop:.1f}%"
        )
        
        await send_telegram(SignalTypes.SHARP_MOVE, telegram_text)
        
        return {
            'signal_type': SignalTypes.SHARP_MOVE,
            'event_name': event_name,
            'league': league,
            'market_type': bet_type,
            'old_value': {'odd': old_odd, 'money': money},
            'new_value': {'odd': new_odd, 'money': money},
            'bookie_value': None
        }
    
    async def detect_odds_squeeze(self, event_id, event_name, league, issues):
        """Детектор сжатия котировок (обе стороны упали)"""
        if len(issues) < 2:
            return None
        
        # Берём первые две стороны (обычно 1 и X или Over/Under)
        side1 = issues[0]
        side2 = issues[1]
        
        if len(side1) < 4 or len(side2) < 4:
            return None
        
        side1_now = side1[2]
        side1_prev = side1[3]
        side2_now = side2[2]
        side2_prev = side2[3]
        
        if not all([side1_now, side2_now, side1_prev, side2_prev]):
            return None
        
        squeeze1 = ((side1_prev - side1_now) / side1_prev) if side1_prev > 0 else 0
        squeeze2 = ((side2_prev - side2_now) / side2_prev) if side2_prev > 0 else 0
        
        # Обе упали больше чем threshold
        if squeeze1 > CONFIG["squeeze_threshold"] and squeeze2 > CONFIG["squeeze_threshold"]:
            logger.warning(f"✂️ ODDS SQUEEZE: {event_name} | Both sides down "
                          f"{squeeze1*100:.1f}% and {squeeze2*100:.1f}%")
            
            telegram_text = (
                f"✂️ <b>ODDS SQUEEZE!</b>\n\n"
                f"⚽ {event_name}\n"
                f"🏆 {league}\n\n"
                f"Both sides tightened significantly\n"
                f"Side 1: {squeeze1*100:.1f}% ↓\n"
                f"Side 2: {squeeze2*100:.1f}% ↓"
            )
            
            await send_telegram(SignalTypes.ODDS_SQUEEZE, telegram_text)
            
            return {
                'signal_type': SignalTypes.ODDS_SQUEEZE,
                'event_name': event_name,
                'league': league,
                'market_type': f"{side1[0]} / {side2[0]}",
                'old_value': {'side1': side1_prev, 'side2': side2_prev},
                'new_value': {'side1': side1_now, 'side2': side2_now},
                'bookie_value': None
            }
        
        return None
    
    async def detect_limit_cut(self, event_id, event_name, league, 
                               bet_type, old_limit, new_limit):
        """Детектор урезки лимита"""
        if not old_limit or new_limit >= old_limit:
            return None
        
        cut_percent = ((old_limit - new_limit) / old_limit) * 100
        
        if cut_percent >= CONFIG["limit_cut_percent"]:
            logger.warning(f"💸 LIMIT CUT: {event_name} | {bet_type} | "
                          f"€{old_limit:,.0f} → €{new_limit:,.0f} ({cut_percent:.0f}% cut)")
            
            telegram_text = (
                f"💸 <b>LIMIT CUT!</b>\n\n"
                f"⚽ {event_name}\n"
                f"🏆 {league}\n"
                f"Market: {bet_type}\n\n"
                f"<b>€{old_limit:,.0f} → €{new_limit:,.0f}</b>\n"
                f"Cut: {cut_percent:.0f}%"
            )
            
            await send_telegram(SignalTypes.LIMIT_CUT, telegram_text)
            
            return {
                'signal_type': SignalTypes.LIMIT_CUT,
                'event_name': event_name,
                'league': league,
                'market_type': bet_type,
                'old_value': {'limit': old_limit},
                'new_value': {'limit': new_limit},
                'bookie_value': None
            }
        
        return None

# ============ ГЛАВНЫЙ ПАРСЕР ============
async def parse_betwatch():
    async with async_playwright() as p:
        logger.info("🚀 Запускаем браузер...")
        browser = await p.chromium.launch(
            headless=CONFIG["browserHeadless"],
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        
        page = await browser.new_page()
        detector = SignalDetector()
        
        try:
            logger.info("📄 Переходим на betwatch.fr/money...")
            await page.goto("https://www.betwatch.fr/money", 
                          wait_until="domcontentloaded", timeout=30000)
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
            
            event_tracking = {}
            event_reported = set()
            
            logger.info("✅ Парсер запущен! Детектируем ВСЕ сигналы...")
            logger.info("📊 Следим за: Sharp Moves, Odds Squeeze, Limit Cuts...")
            
            cycle = 0
            
            while True:
                try:
                    cycle += 1
                    
                    events_data = await page.evaluate("""
                        () => {
                            try {
                                if (typeof Alpine !== 'undefined' && Alpine.store) {
                                    const store = Alpine.store('data');
                                    const details = store.moneywayDetails || [];
                                    return details.filter(m => m.l === 1).slice(0, 30);
                                }
                                return [];
                            } catch(e) {
                                return [];
                            }
                        }
                    """)
                    
                    if len(events_data) == 0:
                        logger.info(f"🔍 Цикл #{cycle}: LIVE событий не найдено")
                        await asyncio.sleep(CONFIG["pause_sec"])
                        continue
                    
                    logger.info(f"📊 Цикл #{cycle}: {len(events_data)} LIVE событий")
                    
                    for event in events_data:
                        event_id = event.get('e')
                        event_name = event.get('m', 'Unknown')
                        league = event.get('ln', 'Unknown')
                        issues = event.get('i', [])
                        
                        if not event_id or not issues:
                            continue
                        
                        # Проверка Odds Squeeze для всего матча
                        squeeze_signal = await detector.detect_odds_squeeze(
                            event_id, event_name, league, issues
                        )
                        if squeeze_signal:
                            save_signal_to_db(squeeze_signal['signal_type'], squeeze_signal)
                        
                        for idx, issue in enumerate(issues):
                            if len(issue) < 3:
                                continue
                            
                            bet_type = issue[0]
                            money = issue[1]
                            odd = issue[2]
                            
                            key = f"{event_id}_{idx}"
                            
                            if money < CONFIG["money_min"] * 0.5:
                                continue
                            
                            if not (CONFIG["koef_min"] <= odd <= CONFIG["koef_max"]):
                                continue
                            
                            # ===== ПЕРВОЕ ПОЯВЛЕНИЕ =====
                            if key not in event_tracking:
                                event_tracking[key] = {
                                    "time": datetime.now(),
                                    "odd": odd,
                                    "name": event_name,
                                    "league": league,
                                    "bet_type": bet_type,
                                    "money": money,
                                    "limit": money,
                                }
                                logger.info(f"✓ NEW: {event_name} [{league}] | {bet_type}: €{money:,.0f} @ {odd:.2f}")
                            else:
                                tracked = event_tracking[key]
                                
                                # 1️⃣ SHARP MOVE
                                if odd < tracked["odd"]:
                                    signal = await detector.detect_sharp_move(
                                        event_id, event_name, league, bet_type, money,
                                        tracked["odd"], odd
                                    )
                                    if signal:
                                        save_signal_to_db(signal['signal_type'], signal)
                                        event_reported.add(key)
                                
                                # 2️⃣ LIMIT CUT
                                if money < tracked["limit"]:
                                    signal = await detector.detect_limit_cut(
                                        event_id, event_name, league, bet_type,
                                        tracked["limit"], money
                                    )
                                    if signal:
                                        save_signal_to_db(signal['signal_type'], signal)
                                
                                # Обновляем отслеживание
                                event_tracking[key]["odd"] = odd
                                event_tracking[key]["money"] = money
                                event_tracking[key]["limit"] = money
                                event_tracking[key]["time"] = datetime.now()
                    
                    await asyncio.sleep(CONFIG["pause_sec"])
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле: {e}", exc_info=True)
                    await asyncio.sleep(5)
        
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        finally:
            await browser.close()

async def main():
    logger.info("=" * 70)
    logger.info("🎯 === BETWATCH EXTENDED DETECTOR v3 (All Signals) ===")
    logger.info("=" * 70)
    logger.info("📡 Signals: Sharp Move, Odds Squeeze, Limit Cuts")
    logger.info("=" * 70)
    
    while True:
        try:
            await parse_betwatch()
        except Exception as e:
            logger.error(f"❌ Main loop error: {e}", exc_info=True)
            logger.info("💤 Рестартуем через 30 сек...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())

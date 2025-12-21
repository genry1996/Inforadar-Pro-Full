# 🎯 BETWATCH PRODUCTION v3.0 - Финальные критерии для прода

import asyncio
import logging
import os
import requests
import mysql.connector
import json
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

logging.basicConfig(
    level=logging.DEBUG,  # DEBUG для отладки
    format='%(asctime)s | %(levelname)s | %(message)s'
)

logger = logging.getLogger(__name__)

# ============ КОНФИГ ============
TELEGRAM_TOKEN = "8432470497:AAE35c89FTPLOtmMgUPpCaaD8htYd1gO9uI"
TELEGRAM_CHAT_ID = "5377484616"

MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "ryban8991!"),
    "database": os.getenv("MYSQL_DB", "inforadar"),
}

# ============ ПРОДАКШН КРИТЕРИИ ============
PRODUCTION_CONFIG = {
    "pause_sec": 5,
    "signal_cooldown_minutes": 15,
    "browser_headless": True,
    
    # Sharp Drop критерии (единые на весь матч)
    "odds_drops": [
        {"name": "10→5", "from_min": 10.0, "to_max": 5.0, "drop_percent_min": 30},
        {"name": "5→2.0", "from_min": 5.0, "to_max": 2.0, "drop_percent_min": 20},
        {"name": "2.0→1.3", "from_min": 2.0, "to_max": 1.3, "drop_percent_min": 15},
    ],
    
    # Превышение средней суммы
    "money_multiplier": 1.5,  # В 1.5 раза выше средней
    "min_money_absolute": 1000,  # Минимум 1000€
    
    # Метка позднего времени (только визуал)
    "late_game_minute": 75,
    
    # Диапазон коэффициентов
    "odd_min": 1.3,
    "odd_max": 15.0,
}

# ============ ФЛАГИ СТРАН ============
def get_country_flag(league_name: str) -> str:
    """Получить флаг страны по названию лиги"""
    flags = {
        "Premier League": "🏴", "Championship": "🏴",
        "La Liga": "🇪🇸", "Serie A": "🇮🇹",
        "Bundesliga": "🇩🇪", "Ligue 1": "🇫🇷",
        "Eredivisie": "🇳🇱", "Primeira Liga": "🇵🇹",
        "Champions League": "🇪🇺", "Europa League": "🇪🇺",
        "World Cup": "🌍", "Euro": "🇪🇺",
        "NBA": "🇺🇸", "Euroleague": "🇪🇺",
    }
    for key, flag in flags.items():
        if key.lower() in league_name.lower():
            return flag
    return "🌐"

def format_time_elapsed(seconds: float) -> str:
    """Форматировать время падения"""
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = seconds // 60
    secs = seconds % 60
    return f"{int(minutes)}m {int(secs)}s"

# ============ TELEGRAM УВЕДОМЛЕНИЯ ============
def send_telegram_sharp_drop(
    event_name, league, bet_type, old_odd, new_odd,
    drop_percent, money, money_multiplier, match_time=None,
    time_elapsed=None, is_late_game=False
):
    """📉 SHARP DROP"""
    flag = get_country_flag(league)
    late_marker = "⏱️ 75+" if is_late_game else ""
    
    text = f"🔻 SHARP DROP {late_marker}\n\n"
    text += f"✅ LIVE\n"
    text += f"⚽ {event_name}\n"
    text += f"{flag} League: {league}\n"
    
    if match_time:
        text += f"⏱️ Time: {match_time}'\n"
    
    text += f"\n📊 Market: {bet_type}\n"
    text += f"📉 Drop: {old_odd:.2f} → {new_odd:.2f} (-{drop_percent:.1f}%)\n"
    text += f"💰 Money: €{money:,.0f} ({money_multiplier:.1f}x avg)\n"
    
    if time_elapsed:
        text += f"⏳ Drop in: {format_time_elapsed(time_elapsed)}\n"
    
    text += "\n🔗 https://www.betwatch.fr/money"
    
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            params = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
            requests.get(url, params=params, timeout=5)
            logger.info("✅ Telegram sent (Sharp Drop)")
        except Exception as e:
            logger.error(f"❌ Telegram error: {e}")

# ============ MySQL ============
def get_db_connection():
    try:
        return mysql.connector.connect(**MYSQL_CONFIG)
    except Exception as e:
        logger.error(f"❌ DB error: {e}")
        return None

def save_signal(
    signal_type, event_id, event_name, league, is_live, match_time,
    market_type, betfair_odd, money_volume, old_odd, new_odd,
    odd_drop_percent, total_volume=None
):
    conn = get_db_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        query = """
        INSERT INTO betwatchsignals
        (signaltype, eventid, eventname, league, islive, matchtime,
         markettype, betfairodd, moneyvolume, totalmarketvolume,
         oldodd, newodd, odddroppercent, detectedat)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        values = (
            signal_type, event_id, event_name, league, int(is_live), match_time,
            market_type, betfair_odd, money_volume, total_volume,
            old_odd, new_odd, odd_drop_percent,
            datetime.now()
        )
        cursor.execute(query, values)
        conn.commit()
        logger.info(f"💾 Signal saved: {signal_type} | {event_name}")
    except Exception as e:
        logger.error(f"❌ DB save error: {e}")
    finally:
        cursor.close()
        conn.close()

# ============ ПРОДАКШН ДЕТЕКТ ============
def calculate_average_money(event_id: str, bettype: str, event_tracking: dict) -> float:
    """
    Вычисляет среднюю сумму (упрощённая версия)
    TODO: В будущем можно хранить историю в БД
    """
    key = f"{event_id}_{bettype}"
    if key in event_tracking:
        old_money = event_tracking[key].get("money", 0)
        # Предполагаем что средняя = 70% от старой
        return old_money * 0.7
    return PRODUCTION_CONFIG["min_money_absolute"]

def check_odds_drop(odds_before: float, odds_now: float) -> dict:
    """Проверка падения коэффициента"""
    if odds_before <= odds_now:
        return None
    
    drop_percent = ((odds_before - odds_now) / odds_before) * 100
    
    for rule in PRODUCTION_CONFIG["odds_drops"]:
        if odds_before >= rule["from_min"] and odds_now <= rule["to_max"]:
            if drop_percent >= rule["drop_percent_min"]:
                return {
                    "type": rule["name"],
                    "drop_percent": round(drop_percent, 1),
                    "odds_from": odds_before,
                    "odds_to": odds_now
                }
    
    return None

def check_money_spike(current_money: float, avg_money: float) -> bool:
    """Проверка превышения средней суммы"""
    if current_money < PRODUCTION_CONFIG["min_money_absolute"]:
        return False
    
    if avg_money == 0:
        return current_money >= PRODUCTION_CONFIG["min_money_absolute"]
    
    return current_money >= (avg_money * PRODUCTION_CONFIG["money_multiplier"])

def detect_production_signal(
    odds_before: float, odds_now: float,
    current_money: float, avg_money: float,
    minute: int
) -> dict:
    """
    Главная функция детекта для продакшна
    Возвращает словарь с данными сигнала или None
    """
    # 1. Проверка падения коэффициента
    drop_info = check_odds_drop(odds_before, odds_now)
    if not drop_info:
        return None
    
    # 2. Проверка превышения денег
    if not check_money_spike(current_money, avg_money):
        return None
    
    # 3. Метка времени (если >= 75 минуты) - только визуал
    late_game = minute >= PRODUCTION_CONFIG["late_game_minute"] if minute else False
    
    return {
        "signal_type": f"sharpdrop_{drop_info['type'].replace('→', '-')}",
        "drop_range": drop_info["type"],
        "odds_from": drop_info["odds_from"],
        "odds_to": drop_info["odds_to"],
        "drop_percent": drop_info["drop_percent"],
        "money": current_money,
        "money_multiplier": round(current_money / avg_money, 1) if avg_money > 0 else 0,
        "minute": minute if minute else 0,
        "late_game": late_game
    }

# ============ ВСПОМОГАТЕЛЬНЫЕ ============
def extract_match_time(event_data):
    time_str = event_data.get("t", "")
    if not time_str:
        return None
    import re
    match = re.search(r"(\d+)", time_str)
    if match:
        return int(match.group(1))
    return None

def should_send_signal(signal_key: str, reported_signals: dict) -> bool:
    """Проверяет, нужно ли отправлять сигнал (дедупликация)"""
    now = datetime.now()
    cooldown = timedelta(minutes=PRODUCTION_CONFIG["signal_cooldown_minutes"])
    if signal_key in reported_signals:
        last_sent = reported_signals[signal_key]
        if now - last_sent < cooldown:
            return False
    reported_signals[signal_key] = now
    return True

# ============ ОСНОВНОЙ ПАРСИНГ ============
async def parse_betwatch():
    async with async_playwright() as p:
        logger.info("🚀 Launching browser...")
        browser = await p.chromium.launch(
            headless=PRODUCTION_CONFIG["browser_headless"],
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = await browser.new_page()
        try:
            logger.info("📄 Going to betwatch.fr/money...")
            await page.goto(
                "https://www.betwatch.fr/money",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await asyncio.sleep(5)
            
            logger.info("🔴 Selecting LIVE...")
            try:
                await page.evaluate(
                    """
                    const el = document.evaluate(
                        '/html/body/div[3]/div[2]/div/div[2]/div/div/label',
                        document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                    ).singleNodeValue;
                    if (el) el.click();
                    """
                )
            except Exception:
                pass
            await asyncio.sleep(2)
            
            event_tracking = {}
            reported_signals = {}
            
            logger.info("=" * 80)
            logger.info("✅ PRODUCTION DETECTOR STARTED")
            logger.info("📉 Sharp Drop: 10→5 (30%), 5→2.0 (20%), 2.0→1.3 (15%)")
            logger.info(f"💰 Money multiplier: {PRODUCTION_CONFIG['money_multiplier']}x")
            logger.info(f"⏱️ Late game marker: {PRODUCTION_CONFIG['late_game_minute']}+ min")
            logger.info("🚫 Excluded: UNDER markets")
            logger.info("=" * 80)
            
            cycle = 0
            
            while True:
                try:
                    cycle += 1
                    events_data = await page.evaluate(
                        """
                        () => {
                            try {
                                if (typeof Alpine !== 'undefined' && Alpine.store) {
                                    const store = Alpine.store('data');
                                    const details = store.moneywayDetails || [];
                                    return details.filter(m => m.l === 1).slice(0, 50);
                                }
                                return [];
                            } catch(e) {
                                return [];
                            }
                        }
                        """
                    )
                    
                    if len(events_data) == 0:
                        logger.info(f"🔍 Cycle #{cycle}: No LIVE events")
                        await asyncio.sleep(PRODUCTION_CONFIG["pause_sec"])
                        continue
                    
                    logger.info(f"📊 Cycle #{cycle}: {len(events_data)} LIVE events")
                    
                    for event in events_data:
                        event_id = str(event.get("e", ""))
                        event_name = event.get("m", "Unknown")
                        league = event.get("ln", "Unknown")
                        issues = event.get("i", [])
                        
                        if not event_id or not issues:
                            continue
                        
                        match_time = extract_match_time(event)
                        
                        total_money = sum(iss[1] for iss in issues if len(iss) > 1)
                        
                        for issue in issues:
                            if len(issue) < 3:
                                continue
                            
                            bet_type = issue[0]
                            money = issue[1]
                            odd = issue[2]
                            key = f"{event_id}_{bet_type}"
                            
                            # ========== ФИЛЬТР: ИСКЛЮЧАЕМ UNDER ==========
                            bet_type_lower = bet_type.lower()
                            if 'under' in bet_type_lower:
                                continue
                            
                            # Фильтры
                            if money < PRODUCTION_CONFIG["min_money_absolute"] * 0.5:
                                continue
                            
                            if not (PRODUCTION_CONFIG["odd_min"] <= odd <= PRODUCTION_CONFIG["odd_max"]):
                                continue
                            
                            # Первое обнаружение
                            if key not in event_tracking:
                                event_tracking[key] = {
                                    "time": datetime.now(),
                                    "odd": odd,
                                    "money": money,
                                    "name": event_name,
                                    "league": league,
                                    "bet_type": bet_type,
                                }
                                continue
                            
                            tracked = event_tracking[key]
                            old_odd = tracked["odd"]
                            time_elapsed = (datetime.now() - tracked["time"]).total_seconds()
                            
                            # ========== DEBUG: Показываем проверку ==========
                            if old_odd > odd and money >= 500:
                                drop_percent = ((old_odd - odd) / old_odd) * 100
                                avg_money = calculate_average_money(event_id, bet_type, event_tracking)
                                money_mult = round(money / avg_money, 1) if avg_money > 0 else 0
                                
                                logger.debug(
                                    f"🔍 CHECK: {event_name[:35]} | {bet_type[:20]} | "
                                    f"{old_odd:.2f}→{odd:.2f} (-{drop_percent:.1f}%) | "
                                    f"€{money:,.0f} ({money_mult}x avg €{avg_money:,.0f}) | {match_time}'"
                                )
                            
                            # ========== ПРОДАКШН ДЕТЕКТ ==========
                            avg_money = calculate_average_money(event_id, bet_type, event_tracking)
                            
                            signal = detect_production_signal(
                                odds_before=old_odd,
                                odds_now=odd,
                                current_money=money,
                                avg_money=avg_money,
                                minute=match_time
                            )
                            
                            if signal:
                                signal_key = f"sharp|{event_id}|{bet_type}"
                                
                                if should_send_signal(signal_key, reported_signals):
                                    late_marker = "⏱️ 75+" if signal["late_game"] else ""
                                    
                                    logger.warning(
                                        f"🔻 SHARP DROP {late_marker} | {event_name} | "
                                        f"{bet_type} | {signal['drop_range']} | "
                                        f"{signal['odds_from']:.2f}→{signal['odds_to']:.2f} "
                                        f"({signal['drop_percent']:.1f}%) | "
                                        f"€{signal['money']:,.0f} ({signal['money_multiplier']}x avg)"
                                    )
                                    
                                    # Telegram
                                    send_telegram_sharp_drop(
                                        event_name=event_name,
                                        league=league,
                                        bet_type=bet_type,
                                        old_odd=signal["odds_from"],
                                        new_odd=signal["odds_to"],
                                        drop_percent=signal["drop_percent"],
                                        money=signal["money"],
                                        money_multiplier=signal["money_multiplier"],
                                        match_time=match_time,
                                        time_elapsed=time_elapsed,
                                        is_late_game=signal["late_game"]
                                    )
                                    
                                    # Сохранение в БД
                                    save_signal(
                                        signal["signal_type"],
                                        event_id,
                                        event_name,
                                        league,
                                        True,  # is_live
                                        match_time,
                                        bet_type,
                                        odd,
                                        signal["money"],
                                        signal["odds_from"],
                                        signal["odds_to"],
                                        signal["drop_percent"],
                                        total_money
                                    )
                            
                            # Обновление трекинга
                            event_tracking[key]["odd"] = odd
                            event_tracking[key]["money"] = money
                    
                    await asyncio.sleep(PRODUCTION_CONFIG["pause_sec"])
                    
                except Exception as e:
                    logger.error(f"❌ Cycle error: {e}", exc_info=True)
                    await asyncio.sleep(5)
                    
        except Exception as e:
            logger.error(f"❌ Critical: {e}", exc_info=True)
        finally:
            await browser.close()

async def main():
    logger.info("=" * 80)
    logger.info("🎯 BETWATCH PRODUCTION v3.0")
    logger.info("=" * 80)
    
    while True:
        try:
            await parse_betwatch()
        except Exception as e:
            logger.error(f"❌ Main error: {e}", exc_info=True)
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())

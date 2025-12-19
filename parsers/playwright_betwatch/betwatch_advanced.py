# 🎯 BETWATCH ADVANCED DETECTOR v2.0
# Динамические пороги падения + защита от послегольных ложняков

import asyncio
import logging
import os
import requests
import mysql.connector
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

# ============ КОНФИГ ============
TELEGRAM_TOKEN = "8432470497:AAE35c89FTPLOtmMgUPpCaaD8htYd1gO9uI"
TELEGRAM_CHAT_ID = "5377484616"

MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "mysql_inforadar"),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "ryban8991!"),
    "database": os.getenv("MYSQL_DB", "inforadar"),
}

CONFIG = {
    "pause_sec": 5,
    
    # 💰 МИНИМАЛЬНАЯ СУММА ЗАЛИВА
    "money_min": 3000,  # €3000
    
    # 📉 SHARP DROP - ДИНАМИЧЕСКИЕ ПОРОГИ
    "sharp_drop_high_odds_min": 3.0,    # Граница "высоких" кэфов
    "sharp_drop_mid_odds_min": 2.0,     # Граница "средних" кэфов
    
    # Пороги падения по диапазонам:
    "sharp_drop_ranges": {
        "high": {"min": 25, "max": 50},     # 10.0-3.0 → 25%
        "mid": {"min": 15, "max": 40},      # 3.0-2.0 → 15%
        "low": {"min": 14, "max": 35}       # <2.0 → 14%
    },
    
    "odd_min": 1.4,
    "odd_max": 10.0,
    
    # 💎 VALUE BET (разница Betfair vs 22bet)
    "value_bet_threshold": 0.13,            # 13% минимум
    "value_confirmation_delay": 7,          # Ждём 7 секунд!
    "value_recheck_cycles": 2,              # Проверяем 2 раза
    
    # 🎯 ТОП ЛИГИ
    "top_leagues": [
        "Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1",
        "Champions League", "Europa League", "World Cup", "Euro",
        "NBA", "Euroleague", "Super League"
    ],
    
    # ⚖️ UNBALANCED FLOW
    "unbalanced_flow": 70,
    "unbalanced_odd_min": 1.7,
    
    # 📈 TOTAL OVER
    "total_over_keywords": ["Over", "Total Over", "ТБ", "Goals Over"],
    
    # ⏰ LATE GAME
    "late_game_minute": 80,
    
    # 🔐 ДЕДУПЛИКАЦИЯ
    "signal_cooldown_minutes": 15,
    
    "browserHeadless": True,
}

TOP_LEAGUES = CONFIG["top_leagues"]

# ============ TELEGRAM ============
def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        params = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        requests.get(url, params=params, timeout=5)
        logger.info(f"✅ Telegram sent")
    except Exception as e:
        logger.error(f"❌ Telegram error: {e}")

# ============ MySQL ============
def get_db_connection():
    try:
        return mysql.connector.connect(**MYSQL_CONFIG)
    except Exception as e:
        logger.error(f"❌ DB error: {e}")
        return None

def save_signal(signal_type, event_id, event_name, league, is_live, match_time,
                market_type, betfair_odd, money_volume, old_odd, new_odd, 
                odd_drop_percent, flow_percent=None, total_volume=None,
                bookmaker_odd=None, bookmaker_name=None):
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cursor = conn.cursor()
        query = """
            INSERT INTO betwatch_signals 
            (signal_type, event_id, event_name, league, is_live, match_time, 
             market_type, betfair_odd, bookmaker_odd, bookmaker_name,
             money_volume, total_market_volume, flow_percent,
             old_odd, new_odd, odd_drop_percent)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        values = (
            signal_type, event_id, event_name, league, is_live, match_time,
            market_type, betfair_odd, bookmaker_odd, bookmaker_name,
            money_volume, total_volume, flow_percent,
            old_odd, new_odd, odd_drop_percent
        )
        cursor.execute(query, values)
        conn.commit()
        logger.info(f"💾 Signal saved: {signal_type} | {event_name}")
    except Exception as e:
        logger.error(f"❌ DB save error: {e}")
    finally:
        cursor.close()
        conn.close()

def get_22bet_odds(home_team, away_team, sport="Football"):
    conn = get_db_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT o.odd_1, o.odd_x, o.odd_2
            FROM events e
            JOIN odds o ON e.id = o.event_id
            WHERE e.home_team LIKE %s 
              AND e.away_team LIKE %s
              AND e.sport = %s
              AND o.bookmaker = '22bet'
            ORDER BY o.created_at DESC
            LIMIT 1
        """
        cursor.execute(query, (f"%{home_team}%", f"%{away_team}%", sport))
        result = cursor.fetchone()
        return result
    except Exception as e:
        return None
    finally:
        cursor.close()
        conn.close()

# ============ ДЕТЕКТОРЫ ============
def is_minor_league(league_name):
    for top in TOP_LEAGUES:
        if top.lower() in league_name.lower():
            return False
    return True

def extract_match_time(event_data):
    time_str = event_data.get('t', '')
    if not time_str:
        return None
    
    import re
    match = re.search(r'(\d+)', time_str)
    if match:
        return int(match.group(1))
    return None

def should_send_signal(signal_key, reported_signals):
    """Проверяет, нужно ли отправлять сигнал (дедупликация)"""
    now = datetime.now()
    cooldown = timedelta(minutes=CONFIG["signal_cooldown_minutes"])
    
    if signal_key in reported_signals:
        last_sent = reported_signals[signal_key]
        if now - last_sent < cooldown:
            return False
    
    reported_signals[signal_key] = now
    return True

def detect_sharp_drop(old_odd, new_odd, money):
    """
    Проверяет падение кэфа с учётом динамических порогов
    
    Диапазоны:
    - 10.0-3.0: минимум 25% падение
    - 3.0-2.0:  минимум 15% падение
    - <2.0:     минимум 14% падение
    """
    
    if old_odd <= new_odd:
        return None  # Кэф не упал
    
    if money < CONFIG["money_min"]:
        return None  # Мало денег
    
    drop_percent = ((old_odd - new_odd) / old_odd) * 100
    
    # Определяем диапазон
    if old_odd >= CONFIG["sharp_drop_high_odds_min"]:
        range_name = "high"
        range_desc = f"{old_odd:.2f} (high odds)"
    elif old_odd >= CONFIG["sharp_drop_mid_odds_min"]:
        range_name = "mid"
        range_desc = f"{old_odd:.2f} (mid odds)"
    else:
        range_name = "low"
        range_desc = f"{old_odd:.2f} (low odds)"
    
    thresholds = CONFIG["sharp_drop_ranges"][range_name]
    
    # Проверка порогов
    if thresholds["min"] <= drop_percent <= thresholds["max"]:
        return {
            "is_valid": True,
            "drop_percent": drop_percent,
            "range": range_name,
            "range_desc": range_desc,
            "min_threshold": thresholds["min"],
            "old_odd": old_odd,
            "new_odd": new_odd,
            "money": money
        }
    
    return None

async def parse_betwatch():
    async with async_playwright() as p:
        logger.info("🚀 Launching browser...")
        browser = await p.chromium.launch(
            headless=CONFIG["browserHeadless"],
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        
        page = await browser.new_page()
        
        try:
            logger.info("📄 Going to betwatch.fr/money...")
            await page.goto("https://www.betwatch.fr/money",
                          wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)
            
            logger.info("🔴 Selecting LIVE...")
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
            reported_signals = {}
            pending_value_bets = {}  # Для VALUE BET с задержкой
            
            logger.info("✅ Detector started! Dynamic thresholds + 7s VALUE delay...")
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
                                    return details.filter(m => m.l === 1).slice(0, 50);
                                }
                                return [];
                            } catch(e) {
                                return [];
                            }
                        }
                    """)
                    
                    if len(events_data) == 0:
                        logger.info(f"🔍 Cycle #{cycle}: No LIVE events")
                        await asyncio.sleep(CONFIG["pause_sec"])
                        continue
                    
                    logger.info(f"📊 Cycle #{cycle}: {len(events_data)} LIVE events")
                    
                    for event in events_data:
                        event_id = str(event.get('e', ''))
                        event_name = event.get('m', 'Unknown')
                        league = event.get('ln', 'Unknown')
                        issues = event.get('i', [])
                        
                        if not event_id or not issues:
                            continue
                        
                        match_time = extract_match_time(event)
                        is_late_game = match_time and match_time >= CONFIG["late_game_minute"]
                        is_minor = is_minor_league(league)
                        
                        teams = event_name.split(' - ') if ' - ' in event_name else event_name.split(' vs ')
                        home_team = teams[0].strip() if len(teams) > 0 else ""
                        away_team = teams[1].strip() if len(teams) > 1 else ""
                        
                        bk_odds = get_22bet_odds(home_team, away_team)
                        total_money = sum([iss[1] for iss in issues if len(iss) > 1])
                        
                        for idx, issue in enumerate(issues):
                            if len(issue) < 3:
                                continue
                            
                            bet_type = issue[0]
                            money = issue[1]
                            odd = issue[2]
                            key = f"{event_id}_{bet_type}"
                            
                            if money < CONFIG["money_min"] * 0.5:
                                continue
                            
                            if not (CONFIG["odd_min"] <= odd <= CONFIG["odd_max"]):
                                continue
                            
                            flow_percent = (money / total_money * 100) if total_money > 0 else 0
                            
                            if key not in event_tracking:
                                event_tracking[key] = {
                                    "time": datetime.now(),
                                    "odd": odd,
                                    "money": money,
                                    "name": event_name,
                                    "league": league,
                                    "bet_type": bet_type,
                                    "total_money": total_money,
                                }
                            else:
                                tracked = event_tracking[key]
                                old_odd = tracked["odd"]
                                old_money = tracked["money"]
                                
                                # 1️⃣ SHARP DROP с динамическими порогами
                                sharp_drop = detect_sharp_drop(old_odd, odd, money)
                                
                                if sharp_drop:
                                    signal_key = f"sharp_{event_id}_{bet_type}"
                                    
                                    if should_send_signal(signal_key, reported_signals):
                                        logger.warning(
                                            f"📉 SHARP DROP [{sharp_drop['range'].upper()}]: {event_name} | "
                                            f"{bet_type} | {sharp_drop['old_odd']:.2f} → {sharp_drop['new_odd']:.2f} "
                                            f"({sharp_drop['drop_percent']:.1f}%) | €{money:,.0f}"
                                        )
                                        
                                        text = (
                                            f"📉 <b>SHARP DROP!</b>\n\n"
                                            f"⚽ {event_name}\n"
                                            f"🏆 {league}\n"
                                            f"💰 Market: {bet_type}\n\n"
                                            f"<b>{sharp_drop['old_odd']:.2f} → {sharp_drop['new_odd']:.2f}</b>\n"
                                            f"Drop: <b>{sharp_drop['drop_percent']:.1f}%</b>\n"
                                            f"Money: €{money:,.0f}\n\n"
                                            f"📊 Range: {sharp_drop['range_desc']} "
                                            f"(threshold: {sharp_drop['min_threshold']}%)"
                                        )
                                        send_telegram(text)
                                        save_signal('sharp_drop', event_id, event_name, league, True,
                                                   match_time, bet_type, odd, money, 
                                                   sharp_drop['old_odd'], sharp_drop['new_odd'], 
                                                   sharp_drop['drop_percent'])
                                
                                # 2️⃣ VALUE BET с задержкой 7 секунд
                                if bk_odds:
                                    bk_odd = bk_odds.get('odd_1', 0)
                                    if bk_odd > 0:
                                        value_diff = ((bk_odd - odd) / odd)
                                        
                                        if value_diff >= CONFIG["value_bet_threshold"]:
                                            signal_key = f"value_{event_id}_{bet_type}"
                                            
                                            # Первое обнаружение
                                            if signal_key not in pending_value_bets:
                                                pending_value_bets[signal_key] = {
                                                    "first_seen": datetime.now(),
                                                    "event_name": event_name,
                                                    "league": league,
                                                    "bf_odd": odd,
                                                    "bk_odd": bk_odd,
                                                    "value_diff": value_diff,
                                                    "money": money,
                                                    "bet_type": bet_type,
                                                    "match_time": match_time,
                                                    "event_id": event_id,
                                                    "recheck_count": 0
                                                }
                                                logger.info(
                                                    f"⏳ PENDING VALUE: {event_name} | "
                                                    f"BF {odd:.2f} vs 22bet {bk_odd:.2f} ({value_diff*100:.1f}%) | "
                                                    f"Waiting 7s..."
                                                )
                                            else:
                                                # Проверка через 7 секунд
                                                pending = pending_value_bets[signal_key]
                                                time_passed = (datetime.now() - pending["first_seen"]).total_seconds()
                                                
                                                if time_passed >= CONFIG["value_confirmation_delay"]:
                                                    pending["recheck_count"] += 1
                                                    
                                                    logger.info(
                                                        f"🔄 RECHECK #{pending['recheck_count']}: {event_name} | "
                                                        f"BF {odd:.2f} vs 22bet {bk_odd:.2f} | "
                                                        f"{time_passed:.1f}s passed"
                                                    )
                                                    
                                                    # Подтверждение после 2 проверок
                                                    if pending["recheck_count"] >= CONFIG["value_recheck_cycles"]:
                                                        if should_send_signal(signal_key, reported_signals):
                                                            logger.warning(
                                                                f"💎 VALUE CONFIRMED: {event_name} | "
                                                                f"BF {odd:.2f} vs 22bet {bk_odd:.2f} | "
                                                                f"Value: {value_diff*100:.1f}%"
                                                            )
                                                            
                                                            text = (
                                                                f"💎 <b>VALUE BET CONFIRMED!</b>\n\n"
                                                                f"⚽ {event_name}\n"
                                                                f"🏆 {league}\n"
                                                                f"Market: {bet_type}\n\n"
                                                                f"Betfair: <b>{odd:.2f}</b>\n"
                                                                f"22bet: <b>{bk_odd:.2f}</b>\n"
                                                                f"Value: <b>{value_diff*100:.1f}%</b>\n"
                                                                f"Money: €{money:,.0f}\n\n"
                                                                f"✅ Confirmed after 7s delay"
                                                            )
                                                            send_telegram(text)
                                                            save_signal('value_bet', event_id, event_name, league, True,
                                                                       match_time, bet_type, odd, money, odd, odd, 0,
                                                                       flow_percent, total_money, bk_odd, '22bet')
                                                        
                                                        del pending_value_bets[signal_key]
                                
                                # 3️⃣ MINOR LEAGUE
                                if is_minor and money >= CONFIG["money_min"]:
                                    money_increase = money - old_money
                                    
                                    if money_increase >= CONFIG["money_min"]:
                                        signal_key = f"minor_{event_id}_{bet_type}"
                                        if should_send_signal(signal_key, reported_signals):
                                            logger.warning(f"🎯 MINOR LEAGUE: {event_name} | €{money:,.0f}")
                                            
                                            text = (
                                                f"🎯 <b>MINOR LEAGUE SPIKE!</b>\n\n"
                                                f"⚽ {event_name}\n🏆 {league}\n"
                                                f"Market: {bet_type}\n\n"
                                                f"Money: <b>€{money:,.0f}</b>"
                                            )
                                            send_telegram(text)
                                            save_signal('minor_league_spike', event_id, event_name, league, True,
                                                       match_time, bet_type, odd, money, old_odd, odd, 0,
                                                       flow_percent, total_money)
                                
                                # 4️⃣ UNBALANCED FLOW
                                if (flow_percent >= CONFIG["unbalanced_flow"] 
                                    and odd >= CONFIG["unbalanced_odd_min"]):
                                    
                                    signal_key = f"unbalanced_{event_id}_{bet_type}"
                                    if should_send_signal(signal_key, reported_signals):
                                        logger.warning(f"⚖️ UNBALANCED: {event_name} | {flow_percent:.1f}%")
                                        
                                        text = (
                                            f"⚖️ <b>UNBALANCED FLOW!</b>\n\n"
                                            f"⚽ {event_name}\n🏆 {league}\n"
                                            f"Market: {bet_type}\n\n"
                                            f"Odd: {odd:.2f}\nMoney: €{money:,.0f}\n"
                                            f"<b>{flow_percent:.1f}%</b> of total"
                                        )
                                        send_telegram(text)
                                        save_signal('unbalanced_flow', event_id, event_name, league, True,
                                                   match_time, bet_type, odd, money, old_odd, odd, 0,
                                                   flow_percent, total_money)
                                
                                # 5️⃣ TOTAL OVER
                                is_total_over = any(kw in bet_type for kw in CONFIG["total_over_keywords"])
                                if is_total_over and money >= CONFIG["money_min"]:
                                    money_increase = money - old_money
                                    
                                    if money_increase >= CONFIG["money_min"]:
                                        signal_key = f"total_over_{event_id}_{bet_type}"
                                        if should_send_signal(signal_key, reported_signals):
                                            logger.warning(f"📈 TOTAL OVER: {event_name} | €{money:,.0f}")
                                            
                                            text = (
                                                f"📈 <b>TOTAL OVER SPIKE!</b>\n\n"
                                                f"⚽ {event_name}\n🏆 {league}\n"
                                                f"Market: {bet_type}\n\n"
                                                f"Odd: {odd:.2f}\nMoney: <b>€{money:,.0f}</b>"
                                            )
                                            send_telegram(text)
                                            save_signal('total_over_spike', event_id, event_name, league, True,
                                                       match_time, bet_type, odd, money, old_odd, odd, 0,
                                                       flow_percent, total_money)
                                
                                # 6️⃣ LATE GAME
                                if is_late_game and is_total_over and money >= CONFIG["money_min"]:
                                    money_increase = money - old_money
                                    
                                    if money_increase >= CONFIG["money_min"]:
                                        signal_key = f"late_game_{event_id}_{bet_type}"
                                        if should_send_signal(signal_key, reported_signals):
                                            logger.warning(f"⏰ LATE GAME: {event_name} | {match_time}'")
                                            
                                            text = (
                                                f"⏰ <b>LATE GAME! (80+)</b>\n\n"
                                                f"⚽ {event_name}\n🏆 {league}\n"
                                                f"⏱️ <b>{match_time}'</b>\n"
                                                f"Market: {bet_type}\n\n"
                                                f"Odd: {odd:.2f}\nMoney: <b>€{money:,.0f}</b>"
                                            )
                                            send_telegram(text)
                                            save_signal('late_game_spike', event_id, event_name, league, True,
                                                       match_time, bet_type, odd, money, old_odd, odd, 0,
                                                       flow_percent, total_money)
                                
                                event_tracking[key]["odd"] = odd
                                event_tracking[key]["money"] = money
                                event_tracking[key]["total_money"] = total_money
                    
                    # Очистка устаревших pending VALUE BET (если разница исчезла)
                    to_remove = []
                    for sig_key, pending in pending_value_bets.items():
                        time_passed = (datetime.now() - pending["first_seen"]).total_seconds()
                        if time_passed > 30:  # Если больше 30 секунд - удаляем
                            to_remove.append(sig_key)
                    
                    for sig_key in to_remove:
                        logger.info(f"🗑️ EXPIRED: {pending_value_bets[sig_key]['event_name']} (30s timeout)")
                        del pending_value_bets[sig_key]
                    
                    await asyncio.sleep(CONFIG["pause_sec"])
                
                except Exception as e:
                    logger.error(f"❌ Cycle error: {e}", exc_info=True)
                    await asyncio.sleep(5)
        
        except Exception as e:
            logger.error(f"❌ Critical: {e}", exc_info=True)
        finally:
            await browser.close()

async def main():
    logger.info("=" * 80)
    logger.info("🎯 BETWATCH ADVANCED DETECTOR v2.0")
    logger.info("=" * 80)
    logger.info("📉 Dynamic Sharp Drop: 25%/15%/14% by odds range")
    logger.info("💎 Value Bet: 13% min + 7s confirmation delay")
    logger.info("💰 Money threshold: €3000")
    logger.info("⏱️ Signal cooldown: 15 minutes")
    logger.info("=" * 80)
    
    while True:
        try:
            await parse_betwatch()
        except Exception as e:
            logger.error(f"❌ Main error: {e}", exc_info=True)
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())

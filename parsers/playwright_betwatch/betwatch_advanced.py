# 🎯 BETWATCH ADVANCED DETECTOR v2.4
# Улучшенные Telegram уведомления + Флаги стран + Визуализация

import asyncio
import logging
import os
import requests
import mysql.connector
import json
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
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "ryban8991!"),
    "database": os.getenv("MYSQL_DB", "inforadar"),
}

CONFIG = {
    "pause_sec": 5,
    "money_min": 3000,
    "sharp_drop_high_odds_min": 3.0,
    "sharp_drop_mid_odds_min": 2.0,
    "sharp_drop_ranges": {
        "high": {"min": 25, "max": 50},
        "mid": {"min": 15, "max": 40},
        "low": {"min": 14, "max": 35}
    },
    "odd_min": 1.4,
    "odd_max": 10.0,
    "value_bet_threshold": 0.13,
    "value_confirmation_delay": 7,
    "value_recheck_cycles": 2,
    "value_bet_bookmakers": ["22bet"],
    "top_leagues": [
        "Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1",
        "Champions League", "Europa League", "World Cup", "Euro",
        "NBA", "Euroleague", "Super League"
    ],
    "unbalanced_flow": 70,
    "unbalanced_odd_min": 1.7,
    "unbalanced_total_min": 5000,
    "total_over_keywords": ["Over", "Total Over", "ТБ", "Goals Over"],
    "late_game_minute": 80,
    "signal_cooldown_minutes": 15,
    "browserHeadless": True,
}

TOP_LEAGUES = CONFIG["top_leagues"]

# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============

def get_country_flag(league_name):
    """Получить флаг страны по названию лиги"""
    flags = {
        # Футбол - топ лиги
        "Premier League": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
        "Championship": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
        "La Liga": "🇪🇸",
        "Serie A": "🇮🇹",
        "Bundesliga": "🇩🇪",
        "Ligue 1": "🇫🇷",
        "Eredivisie": "🇳🇱",
        "Primeira Liga": "🇵🇹",
        "Jupiler": "🇧🇪",
        "Super League": "🇬🇷",
        
        # Международные турниры
        "Champions League": "🇪🇺",
        "Europa League": "🇪🇺",
        "Conference League": "🇪🇺",
        "World Cup": "🌍",
        "Euro": "🇪🇺",
        "Copa America": "🌎",
        
        # Кубки
        "Copa del Rey": "🇪🇸",
        "FA Cup": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
        "Coppa Italia": "🇮🇹",
        "DFB-Pokal": "🇩🇪",
        "Coupe de France": "🇫🇷",
        
        # Другие страны
        "HNL": "🇭🇷",
        "Croatia": "🇭🇷",
        "Belgium": "🇧🇪",
        "Portugal": "🇵🇹",
        "Turkey": "🇹🇷",
        "Russia": "🇷🇺",
        "Greece": "🇬🇷",
        "Serbia": "🇷🇸",
        "Poland": "🇵🇱",
        "Czech": "🇨🇿",
        "Austria": "🇦🇹",
        "Switzerland": "🇨🇭",
        "Denmark": "🇩🇰",
        "Sweden": "🇸🇪",
        "Norway": "🇳🇴",
        
        # Баскетбол
        "NBA": "🇺🇸",
        "Euroleague": "🇪🇺",
        "VTB": "🇷🇺",
    }
    
    for key, flag in flags.items():
        if key.lower() in league_name.lower():
            return flag
    
    return "🌐"

def format_time_elapsed(seconds):
    """Форматировать время падения"""
    if seconds < 60:
        return f"{int(seconds)}s"
    else:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{int(minutes)}m {int(secs)}s"

def load_custom_thresholds():
    """Загрузка порогов из JSON файла"""
    config_file = "D:/Inforadar_Pro/config/thresholds.json"
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                custom = json.load(f)
            
            CONFIG['sharp_drop_ranges']['high']['min'] = custom.get('sharp_drop_high', 25)
            CONFIG['sharp_drop_ranges']['mid']['min'] = custom.get('sharp_drop_mid', 15)
            CONFIG['sharp_drop_ranges']['low']['min'] = custom.get('sharp_drop_low', 14)
            CONFIG['money_min'] = custom.get('money_min', 3000)
            CONFIG['value_bet_threshold'] = custom.get('value_bet', 13) / 100
            CONFIG['value_bet_bookmakers'] = custom.get('value_bet_bookmakers', ['22bet'])
            CONFIG['unbalanced_flow'] = custom.get('unbalanced_flow', 70)
            CONFIG['unbalanced_total_min'] = custom.get('unbalanced_total_min', 5000)
            
            logger.info("✅ Custom thresholds loaded from JSON")
            logger.info(f"📊 Sharp Drop: High={custom.get('sharp_drop_high')}% Mid={custom.get('sharp_drop_mid')}% Low={custom.get('sharp_drop_low')}%")
            logger.info(f"💰 Money min: €{CONFIG['money_min']}")
            logger.info(f"💎 Value Bet bookmakers: {', '.join(CONFIG['value_bet_bookmakers'])}")
            logger.info(f"⚖️ Unbalanced total min: €{CONFIG['unbalanced_total_min']}")
        
        except Exception as e:
            logger.warning(f"⚠️ Error loading thresholds: {e}")
    else:
        logger.info("ℹ️ Using default thresholds (no custom config)")

# ============ УЛУЧШЕННЫЕ TELEGRAM УВЕДОМЛЕНИЯ ============

def send_telegram_sharp_drop(event_name, league, bet_type, old_odd, new_odd, 
                             drop_percent, money, total_money, match_time=None, 
                             time_elapsed=None, is_live=True):
    """📉 SHARP DROP - улучшенный формат как в Test 1"""
    
    flag = get_country_flag(league)
    status = "✅ LIVE" if is_live else "📅 Prematch"
    
    # Основное сообщение
    text = f"{status}\n"
    text += f"{event_name}\n"
    text += f"{flag} League: {league}\n"
    text += f"💰 Money: €{money:,.0f}\n"
    
    if total_money:
        flow_percent = (money / total_money * 100) if total_money > 0 else 0
        text += f"📊 Percent: {flow_percent:.0f}%\n"
    
    text += f"🎯 Stake: {bet_type}\n"
    
    # Время в матче
    if match_time:
        text += f"⏱️ Time: {match_time}'\n"
    
    # Визуализация падения
    text += f"\n📉 Drop odd from {old_odd:.2f} to {new_odd:.2f} on {drop_percent:.2f}%\n"
    
    # Время падения
    if time_elapsed:
        text += f"⏳ Drop odd was in {format_time_elapsed(time_elapsed)}\n"
    
    text += f"\n🔗 https://www.betwatch.fr/money"
    
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            params = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
            requests.get(url, params=params, timeout=5)
            logger.info("✅ Telegram sent (Sharp Drop)")
        except Exception as e:
            logger.error(f"❌ Telegram error: {e}")


def send_telegram_value_bet(event_name, league, bet_type, bf_odd, bk_odd, 
                            bookmaker_name, value_diff, money, match_time=None, 
                            is_live=True):
    """💎 VALUE BET - улучшенный формат"""
    
    flag = get_country_flag(league)
    status = "✅ LIVE" if is_live else "📅 Prematch"
    
    text = f"💎 VALUE BET CONFIRMED!\n\n"
    text += f"{status}\n"
    text += f"⚽ {event_name}\n"
    text += f"{flag} {league}\n"
    text += f"📊 Market: {bet_type}\n"
    
    if match_time:
        text += f"⏱️ Time: {match_time}'\n"
    
    text += f"\n📈 Betfair: {bf_odd:.2f}\n"
    text += f"🏆 {bookmaker_name}: {bk_odd:.2f}\n"
    text += f"💎 Value: {value_diff*100:.1f}%\n"
    text += f"💰 Money: €{money:,.0f}\n"
    text += f"\n✅ Confirmed after 7s delay\n"
    text += f"🔗 https://www.betwatch.fr/money"
    
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            params = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
            requests.get(url, params=params, timeout=5)
            logger.info("✅ Telegram sent (Value Bet)")
        except Exception as e:
            logger.error(f"❌ Telegram error: {e}")


def send_telegram_unbalanced(event_name, league, bet_type, odd, money, 
                             flow_percent, total_money, match_time=None, 
                             is_live=True):
    """⚖️ UNBALANCED FLOW - улучшенный формат"""
    
    flag = get_country_flag(league)
    status = "✅ LIVE" if is_live else "📅 Prematch"
    
    text = f"⚖️ UNBALANCED FLOW!\n\n"
    text += f"{status}\n"
    text += f"⚽ {event_name}\n"
    text += f"{flag} {league}\n"
    text += f"📊 Market: {bet_type}\n"
    
    if match_time:
        text += f"⏱️ Time: {match_time}'\n"
    
    text += f"\n💰 Money on outcome: €{money:,.0f}\n"
    text += f"📊 Total market: €{total_money:,.0f}\n"
    text += f"⚖️ Flow: {flow_percent:.1f}%\n"
    text += f"🎯 Odd: {odd:.2f}\n"
    text += f"\n🔗 https://www.betwatch.fr/money"
    
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            params = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
            requests.get(url, params=params, timeout=5)
            logger.info("✅ Telegram sent (Unbalanced)")
        except Exception as e:
            logger.error(f"❌ Telegram error: {e}")


def send_telegram_minor_league(event_name, league, bet_type, money, match_time=None, is_live=True):
    """🎯 MINOR LEAGUE - улучшенный формат"""
    
    flag = get_country_flag(league)
    status = "✅ LIVE" if is_live else "📅 Prematch"
    
    text = f"🎯 MINOR LEAGUE SPIKE!\n\n"
    text += f"{status}\n"
    text += f"⚽ {event_name}\n"
    text += f"{flag} {league}\n"
    text += f"📊 Market: {bet_type}\n"
    
    if match_time:
        text += f"⏱️ Time: {match_time}'\n"
    
    text += f"\n💰 Money: €{money:,.0f}\n"
    text += f"🔗 https://www.betwatch.fr/money"
    
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            params = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
            requests.get(url, params=params, timeout=5)
            logger.info("✅ Telegram sent (Minor League)")
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

def get_bookmaker_odds(home_team, away_team, bookmaker, sport="Football"):
    """Получить коэффициенты от указанного букмекера"""
    conn = get_db_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT o.odd_1, o.odd_x, o.odd_2, o.bookmaker
            FROM events e
            JOIN odds o ON e.id = o.event_id
            WHERE e.home_team LIKE %s
              AND e.away_team LIKE %s
              AND e.sport = %s
              AND o.bookmaker = %s
            ORDER BY o.created_at DESC
            LIMIT 1
        """
        cursor.execute(query, (f"%{home_team}%", f"%{away_team}%", sport, bookmaker))
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
    """Проверяет падение кэфа с учётом динамических порогов"""
    if old_odd <= new_odd:
        return None
    
    if money < CONFIG["money_min"]:
        return None
    
    drop_percent = ((old_odd - new_odd) / old_odd) * 100
    
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

# ============ ОСНОВНОЙ ПАРСИНГ ============

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
            pending_value_bets = {}
            
            logger.info("✅ Detector started! Dynamic thresholds + Improved Telegram...")
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
                                time_elapsed = (datetime.now() - tracked["time"]).total_seconds()
                                
                                # 1️⃣ SHARP DROP
                                sharp_drop = detect_sharp_drop(old_odd, odd, money)
                                if sharp_drop:
                                    signal_key = f"sharp_{event_id}_{bet_type}"
                                    if should_send_signal(signal_key, reported_signals):
                                        logger.warning(
                                            f"📉 SHARP DROP [{sharp_drop['range'].upper()}]: {event_name} | "
                                            f"{bet_type} | {sharp_drop['old_odd']:.2f} → {sharp_drop['new_odd']:.2f} "
                                            f"({sharp_drop['drop_percent']:.1f}%) | €{money:,.0f}"
                                        )
                                        
                                        send_telegram_sharp_drop(
                                            event_name=event_name,
                                            league=league,
                                            bet_type=bet_type,
                                            old_odd=sharp_drop['old_odd'],
                                            new_odd=sharp_drop['new_odd'],
                                            drop_percent=sharp_drop['drop_percent'],
                                            money=money,
                                            total_money=total_money,
                                            match_time=match_time,
                                            time_elapsed=time_elapsed,
                                            is_live=True
                                        )
                                        
                                        save_signal('sharp_drop', event_id, event_name, league, True,
                                                  match_time, bet_type, odd, money,
                                                  sharp_drop['old_odd'], sharp_drop['new_odd'],
                                                  sharp_drop['drop_percent'])
                                
                                # 2️⃣ VALUE BET
                                for bookmaker in CONFIG['value_bet_bookmakers']:
                                    bk_odds = get_bookmaker_odds(home_team, away_team, bookmaker)
                                    
                                    if bk_odds:
                                        bk_odd = bk_odds.get('odd_1', 0)
                                        
                                        if bk_odd > 0:
                                            value_diff = ((bk_odd - odd) / odd)
                                            
                                            if value_diff >= CONFIG["value_bet_threshold"]:
                                                signal_key = f"value_{event_id}_{bet_type}_{bookmaker}"
                                                
                                                if signal_key not in pending_value_bets:
                                                    pending_value_bets[signal_key] = {
                                                        "first_seen": datetime.now(),
                                                        "event_name": event_name,
                                                        "league": league,
                                                        "bf_odd": odd,
                                                        "bk_odd": bk_odd,
                                                        "bookmaker_name": bookmaker,
                                                        "value_diff": value_diff,
                                                        "money": money,
                                                        "bet_type": bet_type,
                                                        "match_time": match_time,
                                                        "event_id": event_id,
                                                        "recheck_count": 0
                                                    }
                                                    logger.info(
                                                        f"⏳ PENDING VALUE: {event_name} | "
                                                        f"BF {odd:.2f} vs {bookmaker} {bk_odd:.2f} ({value_diff*100:.1f}%) | "
                                                        f"Waiting 7s..."
                                                    )
                                                else:
                                                    pending = pending_value_bets[signal_key]
                                                    time_passed = (datetime.now() - pending["first_seen"]).total_seconds()
                                                    
                                                    if time_passed >= CONFIG["value_confirmation_delay"]:
                                                        pending["recheck_count"] += 1
                                                        logger.info(
                                                            f"🔄 RECHECK #{pending['recheck_count']}: {event_name} | "
                                                            f"BF {odd:.2f} vs {bookmaker} {bk_odd:.2f} | "
                                                            f"{time_passed:.1f}s passed"
                                                        )
                                                        
                                                        if pending["recheck_count"] >= CONFIG["value_recheck_cycles"]:
                                                            if should_send_signal(signal_key, reported_signals):
                                                                logger.warning(
                                                                    f"💎 VALUE CONFIRMED: {event_name} | "
                                                                    f"BF {odd:.2f} vs {bookmaker} {bk_odd:.2f} | "
                                                                    f"Value: {value_diff*100:.1f}%"
                                                                )
                                                                
                                                                send_telegram_value_bet(
                                                                    event_name=event_name,
                                                                    league=league,
                                                                    bet_type=bet_type,
                                                                    bf_odd=odd,
                                                                    bk_odd=bk_odd,
                                                                    bookmaker_name=bookmaker,
                                                                    value_diff=value_diff,
                                                                    money=money,
                                                                    match_time=match_time,
                                                                    is_live=True
                                                                )
                                                                
                                                                save_signal('value_bet', event_id, event_name, league, True,
                                                                          match_time, bet_type, odd, money, odd, odd, 0,
                                                                          flow_percent, total_money, bk_odd, bookmaker)
                                                                
                                                                del pending_value_bets[signal_key]
                                
                                # 3️⃣ MINOR LEAGUE
                                if is_minor and money >= CONFIG["money_min"]:
                                    money_increase = money - old_money
                                    if money_increase >= CONFIG["money_min"]:
                                        signal_key = f"minor_{event_id}_{bet_type}"
                                        if should_send_signal(signal_key, reported_signals):
                                            logger.warning(f"🎯 MINOR LEAGUE: {event_name} | €{money:,.0f}")
                                            
                                            send_telegram_minor_league(
                                                event_name=event_name,
                                                league=league,
                                                bet_type=bet_type,
                                                money=money,
                                                match_time=match_time,
                                                is_live=True
                                            )
                                            
                                            save_signal('minor_league_spike', event_id, event_name, league, True,
                                                      match_time, bet_type, odd, money, old_odd, odd, 0,
                                                      flow_percent, total_money)
                                
                                # 4️⃣ UNBALANCED FLOW
                                if (flow_percent >= CONFIG["unbalanced_flow"]
                                    and odd >= CONFIG["unbalanced_odd_min"]
                                    and total_money >= CONFIG["unbalanced_total_min"]):
                                    
                                    signal_key = f"unbalanced_{event_id}_{bet_type}"
                                    if should_send_signal(signal_key, reported_signals):
                                        logger.warning(
                                            f"⚖️ UNBALANCED: {event_name} | {flow_percent:.1f}% | "
                                            f"Total: €{total_money:,.0f}"
                                        )
                                        
                                        send_telegram_unbalanced(
                                            event_name=event_name,
                                            league=league,
                                            bet_type=bet_type,
                                            odd=odd,
                                            money=money,
                                            flow_percent=flow_percent,
                                            total_money=total_money,
                                            match_time=match_time,
                                            is_live=True
                                        )
                                        
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
                                            save_signal('late_game_spike', event_id, event_name, league, True,
                                                      match_time, bet_type, odd, money, old_odd, odd, 0,
                                                      flow_percent, total_money)
                                
                                event_tracking[key]["odd"] = odd
                                event_tracking[key]["money"] = money
                                event_tracking[key]["total_money"] = total_money
                    
                    # Очистка устаревших pending VALUE BET
                    to_remove = []
                    for sig_key, pending in pending_value_bets.items():
                        time_passed = (datetime.now() - pending["first_seen"]).total_seconds()
                        if time_passed > 30:
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
    logger.info("🎯 BETWATCH ADVANCED DETECTOR v2.4")
    logger.info("=" * 80)
    
    load_custom_thresholds()
    
    logger.info("📉 Dynamic Sharp Drop: 25%/15%/14% by odds range")
    logger.info("💎 Value Bet: 13% min + 7s confirmation + Multiple bookmakers")
    logger.info(f"💰 Money threshold: €{CONFIG['money_min']}")
    logger.info(f"⚖️ Unbalanced min total: €{CONFIG['unbalanced_total_min']}")
    logger.info("⏱️ Signal cooldown: 15 minutes")
    logger.info("📱 Improved Telegram notifications with flags")
    logger.info("=" * 80)
    
    while True:
        try:
            await parse_betwatch()
        except Exception as e:
            logger.error(f"❌ Main error: {e}", exc_info=True)
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())

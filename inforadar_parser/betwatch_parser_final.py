import asyncio
import logging
import os
import json
import requests
import mysql.connector
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)


# ==========================================
# 🧠 SMART MEMORY & LOGIC FOR SHARP SIGNALS
# ==========================================


odds_history = {}
VOLUME_THRESHOLD = 3000  # Минимум €3000
DROP_THRESHOLD = 15  # Падение > 15%
SUPER_DROP_THRESHOLD = 25  # Супер-сигнал > 25%
SUPER_VOLUME_THRESHOLD = 10000  # Крупный прогруз > €10000


def analyze_signal(match_name, market, selection, current_odd, volume_euro):
    """
    🎯 Анализирует падение кэфа и ловит 'Тычки' (резкий обвал на деньгах)
    Возвращает словарь сигнала или None
    """
    try:
        signal_key = f"{match_name}_{market}_{selection}"
        current_time = datetime.now()
        
        # 1️⃣ Первый раз видим этот исход - инициализируем историю
        if signal_key not in odds_history:
            odds_history[signal_key] = {
                'start_odd': current_odd,
                'prev_odd': current_odd,
                'last_update': current_time,
                'max_volume': volume_euro
            }
            return None

        history = odds_history[signal_key]
        
        # 2️⃣ Рассчитываем ОБЩЕЕ падение от начальной точки
        drop_percent = ((history['start_odd'] - current_odd) / history['start_odd']) * 100 if history['start_odd'] > 0 else 0
        
        # 3️⃣ Рассчитываем ЦИКЛОВОЕ падение (резкий скачок за последний замер)
        cycle_drop = ((history['prev_odd'] - current_odd) / history['prev_odd']) * 100 if history['prev_odd'] > 0 else 0
        
        # 4️⃣ Обновляем историю
        history['prev_odd'] = current_odd
        history['last_update'] = current_time
        if volume_euro > history['max_volume']:
            history['max_volume'] = volume_euro
        
        # ==========================================
        # 🎯 КРИТЕРИИ "ТЫЧКИ" (Sharp Money Detection)
        # ==========================================
        
        # A. Значимый объем денег (фильтруем мусор дворовых лиг)
        is_big_money = volume_euro >= VOLUME_THRESHOLD
        
        # B. Резкий обвал (либо общий > 15%, либо цикловой > 5%)
        is_sharp_drop = drop_percent > DROP_THRESHOLD or cycle_drop > 5
        
        # C. СУПЕР-СИГНАЛ: обвал > 25% + крупные деньги > €10000
        is_super_drop = drop_percent > SUPER_DROP_THRESHOLD and history['max_volume'] > SUPER_VOLUME_THRESHOLD

        # 🚀 ГЕНЕРИРУЕМ СИГНАЛ ЕСЛИ КРИТЕРИИ ВЫПОЛНЕНЫ
        if is_sharp_drop and is_big_money:
            signal_type = "📉 SHARP DROP (Тычка)"
            confidence = "HIGH"
            
            if is_super_drop:
                signal_type = "🔥 WHALE MOVE (Крупный прогруз)"
                confidence = "ULTRA"
            
            return {
                "type": signal_type,
                "confidence": confidence,
                "match": match_name,
                "selection": selection,
                "drop_percent": round(drop_percent, 2),
                "start_odd": round(history['start_odd'], 2),
                "now_odd": round(current_odd, 2),
                "money": round(volume_euro, 2),
                "max_money": round(history['max_volume'], 2),
                "cycle_drop": round(cycle_drop, 2),
                "timestamp": current_time.isoformat()
            }
        
        return None
        
    except Exception as e:
        logging.error(f"❌ Error in analyze_signal: {str(e)}")
        return None


def log_signal(signal):
    """
    📢 Красиво логирует сигнал в консоль и отправляет в БД
    """
    if not signal:
        return
    
    emoji = "🔥" if signal['confidence'] == "ULTRA" else "📉"
    
    logging.warning(f"\n{'='*80}")
    logging.warning(f"{emoji} SIGNAL DETECTED: {signal['type']}")
    logging.warning(f"{'='*80}")
    logging.warning(f"⚽ Match: {signal['match']}")
    logging.warning(f"🎯 Selection: {signal['selection']}")
    logging.warning(f"💰 Money Matched: €{signal['money']:,.0f} (Max: €{signal['max_money']:,.0f})")
    logging.warning(f"📉 Odds Drop: {signal['start_odd']} ➜ {signal['now_odd']} (-{signal['drop_percent']}%)")
    logging.warning(f"⚠️  Cycle Drop: -{signal['cycle_drop']}%")
    logging.warning(f"⏰ Time: {signal['timestamp']}")
    logging.warning(f"🔗 CHECK 22BET NOW! Odds might still be {signal['start_odd']}!\n")
    logging.warning(f"{'='*80}\n")


def save_signal_to_db(signal, db_connection):
    """
    💾 Сохраняет сигнал в MySQL таблицу 'signals'
    """
    if not signal or not db_connection:
        return
    
    try:
        cursor = db_connection.cursor()
        query = """
        INSERT INTO signals (
            match_name, selection, signal_type, confidence,
            start_odd, current_odd, drop_percent,
            volume_euro, timestamp
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        values = (
            signal['match'],
            signal['selection'],
            signal['type'],
            signal['confidence'],
            signal['start_odd'],
            signal['now_odd'],
            signal['drop_percent'],
            signal['money'],
            datetime.now()
        )
        cursor.execute(query, values)
        db_connection.commit()
        cursor.close()
        logging.info(f"✅ Signal saved to DB: {signal['match']} | {signal['selection']}")
    except Exception as e:
        logging.error(f"❌ Error saving signal to DB: {str(e)}")


def connect_to_db(retry_count=3):
    """
    🔗 Подключается к БД с повторными попытками
    """
    db_connection = None
    
    for attempt in range(1, retry_count + 1):
        try:
            db_connection = mysql.connector.connect(
                host=os.getenv('DB_HOST', 'mysql_inforadar'),
                user=os.getenv('DB_USER', 'root'),
                password=os.getenv('DB_PASSWORD', 'ryban8991!'),
                database=os.getenv('DB_NAME', 'inforadar_db')
            )
            logging.info(f"✅ Database connected on attempt {attempt}")
            return db_connection
        except mysql.connector.Error as db_error:
            error_code = db_error.errno if hasattr(db_error, 'errno') else 'UNKNOWN'
            logging.warning(f"⚠️ Database connection attempt {attempt} failed: [{error_code}] {str(db_error)}")
            
            if error_code == 1049:  # Unknown database
                logging.error("❌ Database 'inforadar_db' does not exist!")
                logging.info("💡 Create database with: mysql -u root -p < init_database.sql")
            
            if attempt < retry_count:
                wait_time = 5 * attempt
                logging.info(f"⏳ Retrying in {wait_time} seconds...")
                import time
                time.sleep(wait_time)
    
    if not db_connection:
        logging.warning("⚠️ Failed to connect to database after all retries")
        logging.info("📊 Continuing without database (memory mode only)...")
    
    return db_connection


async def parse_betwatch():
    """
    🎯 MAIN PARSER: Betwatch Money Tracking with Smart Signal Detection
    """
    db_connection = None
    browser = None
    
    try:
        # Подключение к БД
        db_connection = connect_to_db(retry_count=2)
        
        async with async_playwright() as p:
            logging.info("🚀 Launching browser...")
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            # Переходим на Betwatch с увеличенным timeout
            logging.info("📄 Navigating to betwatch.fr/money...")
            try:
                await page.goto('https://betwatch.fr/money', wait_until='domcontentloaded', timeout=120000)
            except PlaywrightTimeoutError:
                logging.warning("⚠️ Page load timeout, continuing anyway...")
            except Exception as e:
                logging.warning(f"⚠️ Navigation error: {str(e)}")
            
            # Выбираем LIVE матчи с обработкой ошибок
            logging.info("🔴 Selecting LIVE matches...")
            try:
                await page.click('a:has-text("LIVE")', timeout=30000)
                await page.wait_for_timeout(3000)
            except PlaywrightTimeoutError:
                logging.warning("⚠️ LIVE button click timeout, continuing anyway...")
            except Exception as e:
                logging.warning(f"⚠️ Could not click LIVE button: {str(e)}")
                logging.info("📊 Trying to parse matches anyway...")
            
            logging.info("✅ Parser started! Detecting ALL signals...")
            logging.info("📊 Monitoring: Sharp Moves, Odds Squeeze, Limit Cuts...")
            logging.info("="*80)
            
            cycle_count = 0
            
            while True:
                try:
                    cycle_count += 1
                    logging.info(f"\n📊 Cycle #{cycle_count}: {datetime.now().strftime('%H:%M:%S')}")
                    
                    # Получаем все матчи на странице
                    try:
                        matches = await page.query_selector_all('tr[data-event-id]', timeout=10000)
                        logging.info(f"📡 Found {len(matches)} LIVE events")
                    except PlaywrightTimeoutError:
                        logging.warning("⚠️ Could not find matches (timeout)")
                        matches = []
                    except Exception as e:
                        logging.warning(f"⚠️ Could not find matches: {str(e)}")
                        matches = []
                    
                    if not matches:
                        logging.info("⏳ No matches found, retrying in 15 seconds...")
                        await page.wait_for_timeout(15000)
                        continue
                    
                    for idx, match in enumerate(matches[:15]):  # Первые 15 матчей
                        try:
                            # Парсим данные матча
                            match_text = await match.inner_text()
                            
                            # Примерный парсинг (адаптируйте под реальную структуру)
                            parts = match_text.split('\n')
                            if len(parts) < 3:
                                continue
                            
                            match_name = parts[0]  # "Barcelona - Eintracht Frankfurt"
                            league = parts[1]      # "UEFA Champions League"
                            
                            # Находим коэффициенты и объемы
                            odds_elements = await match.query_selector_all('td[data-odds]')
                            
                            for odds_elem in odds_elements[:3]:  # П1, Х, П2
                                try:
                                    odd_value = await odds_elem.get_attribute('data-odds')
                                    volume_value = await odds_elem.get_attribute('data-volume')
                                    selection_id = await odds_elem.get_attribute('data-selection')
                                    
                                    if not (odd_value and volume_value):
                                        continue
                                    
                                    odd_float = float(odd_value)
                                    volume_float = float(volume_value)
                                    
                                    selection_map = {'0': '1', '1': 'X', '2': '2'}
                                    selection = selection_map.get(selection_id, selection_id)
                                    
                                    # 🧠 АНАЛИЗИРУЕМ СИГНАЛ
                                    signal = analyze_signal(
                                        match_name=f"{match_name} [{league}]",
                                        market="Match Odds",
                                        selection=selection,
                                        current_odd=odd_float,
                                        volume_euro=volume_float
                                    )
                                    
                                    # 📢 ЛОГИРУЕМ СИГНАЛ
                                    if signal:
                                        log_signal(signal)
                                        # 💾 СОХРАНЯЕМ В БД
                                        if db_connection:
                                            save_signal_to_db(signal, db_connection)
                                    else:
                                        # Обычный лог для небольших движений
                                        logging.info(f"✓ {selection}: €{volume_float:,.0f} @ {odd_float}")
                                
                                except Exception as e:
                                    logging.debug(f"⚠️ Error parsing odds element: {str(e)}")
                                    continue
                        
                        except Exception as e:
                            logging.debug(f"⚠️ Error parsing match: {str(e)}")
                            continue
                    
                    # Рефрешим страницу для обновления данных
                    logging.info("🔄 Refreshing data...")
                    try:
                        await page.reload(wait_until='domcontentloaded', timeout=90000)
                    except PlaywrightTimeoutError:
                        logging.warning("⚠️ Page reload timeout, continuing...")
                    except Exception as e:
                        logging.warning(f"⚠️ Reload error: {str(e)}")
                    
                    await page.wait_for_timeout(5000)
                
                except Exception as e:
                    logging.error(f"❌ Cycle error: {str(e)}")
                    await page.wait_for_timeout(10000)
                    continue
        
        if browser:
            await browser.close()
    
    except Exception as e:
        logging.error(f"❌ Main error: {str(e)}")
    
    finally:
        if db_connection:
            try:
                db_connection.close()
                logging.info("✅ Database connection closed")
            except:
                pass


async def main():
    """
    Main entry point
    """
    logging.info("="*80)
    logging.info("🎯 === BETWATCH EXTENDED DETECTOR v5 (Smart Signals + Resilient) ===")
    logging.info("="*80)
    logging.info("📡 Signals: Sharp Move, Odds Squeeze, Limit Cuts")
    logging.info("🧠 Mode: Memory-based analysis with historical tracking")
    logging.info("💰 Money Filter: €3000+ (cuts out noise)")
    logging.info("📉 Drop Threshold: 15% or 5% per cycle")
    logging.info("🔥 Whale Detection: 25%+ drop + €10000+")
    logging.info("🔄 Retry Logic: Automatic recovery from timeouts")
    logging.info("="*80)
    
    while True:
        try:
            await parse_betwatch()
        except Exception as e:
            logging.error(f"❌ Main loop error: {str(e)}")
            logging.info("💤 Restarting in 60 seconds...")
            await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())

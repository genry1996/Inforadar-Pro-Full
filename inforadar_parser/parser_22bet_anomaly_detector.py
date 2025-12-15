import asyncio
import logging
from playwright.async_api import async_playwright
import mysql.connector
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

CONFIRMATION_DELAY = 5
DETECTION_THRESHOLD = -1.0  # ✅ Снижен порог до 1%
CONFIRMATION_THRESHOLD = -1.0  # ✅ Согласованный порог

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "ryban8991!"),
        database=os.getenv("MYSQL_DB", "inforadar"),
        autocommit=True
    )

PROXY_CONFIG = {
    "server": "http://213.137.91.35:12323",
    "username": "14ab48c9d85c1",
    "password": "5d234f6517"
}

async def parse_single_event(page, event_name):
    """Повторно парсит один конкретный матч для подтверждения"""
    try:
        all_events = await page.query_selector_all(".c-events__item.c-events__item_col")
        for event in all_events:
            teams = await event.query_selector_all(".c-events__team")
            if len(teams) < 2:
                continue
            home = (await teams[0].inner_text()).strip()
            away = (await teams[1].inner_text()).strip()
            current_event_name = f"{home} vs {away}"
            if current_event_name == event_name:
                odds_elems = await event.query_selector_all(".c-bets__inner")
                odds_list = []
                for o in odds_elems[:3]:
                    try:
                        txt = (await o.inner_text()).strip()
                        if txt:
                            odds_list.append(float(txt))
                    except:
                        pass
                if len(odds_list) >= 2:
                    while len(odds_list) < 3:
                        odds_list.append(1.0)
                    return {'1': odds_list[0], 'X': odds_list[1], '2': odds_list[2]}
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка парсинга {event_name}: {e}")
        return None

class AnomalyDetector:
    def __init__(self):
        self.previous_state = {}
    
    async def detect_anomalies_with_confirmation(self, current_events, page=None):
        """Детектор с подтверждением падения через 5 секунд"""
        anomalies = []
        
        # REMOVED
        for event_name, prev_data in list(self.previous_state.items()):
            if event_name not in current_events:
                anomalies.append({
                    'event_name': event_name,
                    'sport': prev_data.get('sport', 'Unknown'),
                    'anomaly_type': 'REMOVED',
                    'before_value': 'active',
                    'after_value': 'removed',
                    'diff_pct': -100.00,
                    'status': 'removed',
                    'comment': 'Событие исчезло с линии'
                })
        
        for event_name, current_data in current_events.items():
            prev_data = self.previous_state.get(event_name, {})
            if not prev_data:
                continue
            
            # FROZEN
            if prev_data.get('status') == 'active' and current_data.get('status') == 'frozen':
                anomalies.append({
                    'event_name': event_name,
                    'sport': current_data.get('sport', prev_data.get('sport', 'Unknown')),
                    'anomaly_type': 'FROZEN',
                    'before_value': 'active',
                    'after_value': 'frozen',
                    'diff_pct': 0,
                    'status': 'frozen',
                    'comment': 'Линия заморозилась'
                })
            
            # ODDS_DROP / ODDS_RISE
            for outcome in ['1', 'X', '2']:
                prev_odd = prev_data.get('odds', {}).get(outcome, 0)
                curr_odd = current_data.get('odds', {}).get(outcome, 0)
                
                if prev_odd > 0 and curr_odd > 0:
                    change_pct = ((curr_odd - prev_odd) / prev_odd * 100)
                    
                    # ✅ ЛОГИРУЕМ ВСЕ ИЗМЕНЕНИЯ > 0.5%
                    if abs(change_pct) > 0.5:
                        logger.info(
                            f"🔄 Изменение: {event_name} ({outcome}): "
                            f"{prev_odd:.3f} → {curr_odd:.3f} ({change_pct:+.2f}%)"
                        )
                    
                    sport_name = current_data.get('sport', prev_data.get('sport', 'Unknown'))
                    
                    # ✅ ПАДЕНИЕ КОЭФФИЦИЕНТА (порог -1%)
                    if change_pct < DETECTION_THRESHOLD:
                        logger.warning(
                            f"⏳ Возможное падение: {event_name} ({outcome}), "
                            f"ждем {CONFIRMATION_DELAY} сек..."
                        )
                        
                        await asyncio.sleep(CONFIRMATION_DELAY)
                        
                        if page:
                            confirmed_odds = await parse_single_event(page, event_name)
                            if confirmed_odds and confirmed_odds[outcome] > 0:
                                confirmed_change = (
                                    (confirmed_odds[outcome] - prev_odd) / prev_odd * 100
                                )
                                
                                # ✅ ПОДТВЕРЖДЕНИЕ С ПОРОГОМ -1%
                                if confirmed_change < CONFIRMATION_THRESHOLD:
                                    anomalies.append({
                                        'event_name': event_name,
                                        'sport': sport_name,
                                        'anomaly_type': 'ODDS_DROP',
                                        'before_value': f"{prev_odd:.3f}",
                                        'after_value': f"{confirmed_odds[outcome]:.3f}",
                                        'diff_pct': round(confirmed_change, 2),
                                        'status': 'confirmed',
                                        'comment': (
                                            f'{outcome}: {prev_odd:.3f} -> '
                                            f'{confirmed_odds[outcome]:.3f} (подтверждено)'
                                        )
                                    })
                                    logger.info(
                                        f"✅ Подтверждено падение: {event_name} ({outcome})"
                                    )
                                else:
                                    logger.info(
                                        f"✓ Ложный сигнал: {event_name} ({outcome}) - "
                                        f"кэф вернулся ({confirmed_change:+.2f}%)"
                                    )
                            else:
                                anomalies.append({
                                    'event_name': event_name,
                                    'sport': sport_name,
                                    'anomaly_type': 'ODDS_DROP',
                                    'before_value': f"{prev_odd:.3f}",
                                    'after_value': f"{curr_odd:.3f}",
                                    'diff_pct': round(change_pct, 2),
                                    'status': 'unconfirmed',
                                    'comment': (
                                        f'{outcome}: {prev_odd:.3f} -> '
                                        f'{curr_odd:.3f} (не подтверждено)'
                                    )
                                })
                        else:
                            anomalies.append({
                                'event_name': event_name,
                                'sport': sport_name,
                                'anomaly_type': 'ODDS_DROP',
                                'before_value': f"{prev_odd:.3f}",
                                'after_value': f"{curr_odd:.3f}",
                                'diff_pct': round(change_pct, 2),
                                'status': 'active',
                                'comment': (
                                    f'{outcome}: {prev_odd:.3f} -> {curr_odd:.3f}'
                                )
                            })
                    
                    # РОСТ КОЭФФИЦИЕНТА
                    if change_pct > 10:
                        anomalies.append({
                            'event_name': event_name,
                            'sport': sport_name,
                            'anomaly_type': 'ODDS_RISE',
                            'before_value': f"{prev_odd:.3f}",
                            'after_value': f"{curr_odd:.3f}",
                            'diff_pct': round(change_pct, 2),
                            'status': 'active',
                            'comment': (
                                f'{outcome}: {prev_odd:.3f} -> {curr_odd:.3f}'
                            )
                        })
        
        self.previous_state = current_events.copy()
        return anomalies

async def parse_22bet():
    detector = AnomalyDetector()
    
    async with async_playwright() as p:
        logger.info("🚀 Парсер 22BET запущен")
        
        browser = await p.chromium.launch(
            headless=True,
            proxy=PROXY_CONFIG,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        
        page = await context.new_page()
        
        MIRRORS = ["https://22betluck.com", "https://22bet.com"]
        working_mirror = None
        
        for mirror in MIRRORS:
            try:
                logger.info(f"🌐 Пробуем: {mirror}")
                response = await page.goto(mirror, wait_until="domcontentloaded", timeout=15000)
                if response.status < 400:
                    logger.info(f"✅ Работает: {mirror}")
                    working_mirror = mirror
                    break
            except Exception as e:
                logger.warning(f"❌ Недоступно {mirror}")
        
        if not working_mirror:
            await browser.close()
            logger.error("❌ Все зеркала недоступны")
            return
        
        SPORTS = [{"name": "Football", "slug": "football"}]
        
        for sport in SPORTS:
            try:
                sport_url = f"{working_mirror}/line/{sport['slug']}/"
                logger.info(f"📌 Загружаем: {sport_url}")
                
                await page.goto(sport_url, wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(3)
                await page.wait_for_selector(".c-events__item_col", timeout=10000)
                
                all_events = await page.query_selector_all(".c-events__item.c-events__item_col")
                logger.info(f"📊 Найдено событий: {len(all_events)}")
                
                current_events = {}
                conn = get_db_connection()
                cursor = conn.cursor()
                success_count = 0
                
                for event in all_events[:20]:
                    try:
                        teams = await event.query_selector_all(".c-events__team")
                        if len(teams) < 2:
                            continue
                        
                        home = (await teams[0].inner_text()).strip()
                        away = (await teams[1].inner_text()).strip()
                        event_name = f"{home} vs {away}"
                        
                        if event_name in ("Home vs Away", "Team1 vs Team2"):
                            continue
                        
                        odds_elems = await event.query_selector_all(".c-bets__inner")
                        odds_list = []
                        
                        for o in odds_elems[:3]:
                            try:
                                txt = (await o.inner_text()).strip()
                                if txt:
                                    odds_list.append(float(txt))
                            except:
                                pass
                        
                        if len(odds_list) < 2:
                            continue
                        
                        while len(odds_list) < 3:
                            odds_list.append(1.0)
                        
                        current_events[event_name] = {
                            'sport': sport['name'],
                            'status': 'active',
                            'odds': {'1': odds_list[0], 'X': odds_list[1], '2': odds_list[2]}
                        }
                        
                        sql = """
                        INSERT INTO odds_22bet (event_name, sport, market_type, odd_1, odd_x, odd_2, status)
                        VALUES (%s, %s, '1x2', %s, %s, %s, 'active')
                        ON DUPLICATE KEY UPDATE odd_1=VALUES(odd_1), odd_x=VALUES(odd_x), odd_2=VALUES(odd_2), updated_at=NOW()
                        """
                        cursor.execute(sql, (event_name, sport['name'], float(odds_list[0]), float(odds_list[1]), float(odds_list[2])))
                        success_count += 1
                        logger.info(f" ✓ {event_name}: {odds_list[0]:.2f} | {odds_list[1]:.2f} | {odds_list[2]:.2f}")
                    
                    except Exception as e:
                        logger.debug(f" ⚠️ Событие: {str(e)[:60]}")
                
                anomalies = await detector.detect_anomalies_with_confirmation(current_events, page)
                
                if anomalies:
                    logger.warning(f"\n🚨 АНОМАЛИИ: {len(anomalies)}\n")
                    for anom in anomalies:
                        try:
                            sql = """
                            INSERT INTO anomalies_22bet (event_name, sport, league, anomaly_type, before_value, after_value, diff_pct, status, comment)
                            VALUES (%s, %s, 'Mixed', %s, %s, %s, %s, %s, %s)
                            """
                            cursor.execute(sql, (
                                anom['event_name'],
                                anom.get('sport', 'Unknown'),
                                anom['anomaly_type'],
                                str(anom['before_value'])[:50],
                                str(anom['after_value'])[:50],
                                anom['diff_pct'],
                                anom['status'],
                                str(anom['comment'])[:255]
                            ))
                            logger.warning(f" 📍 {anom['anomaly_type']}: {anom['event_name']} [{anom['status']}]")
                        except Exception as e:
                            logger.error(f" ❌ Аномалия: {e}")
                else:
                    logger.info("✅ Аномалий не обнаружено")
                
                conn.commit()
                cursor.close()
                conn.close()
                logger.info(f"✅ {sport['name']}: {success_count} событий, {len(anomalies)} аномалий\n")
            
            except Exception as e:
                logger.error(f"❌ {sport['name']}: {e}")
        
        await browser.close()

async def main():
    while True:
        try:
            await parse_22bet()
        except Exception as e:
            logger.error(f"💥 Ошибка: {e}")
        
        logger.info("⏱️ Пауза 60 сек...\n")
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())

# -*- coding: utf-8 -*-
"""
22bet PREMATCH Parser v30 WITH FULL HISTORY TRACKING
Добавлено: полное отслеживание истории коэффициентов + обнаружение аномалий
"""

import asyncio
import pymysql
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

# ============================================
# КОНФИГУРАЦИЯ
# ============================================

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'ryban8991!',
    'database': 'inforadar',
    'charset': 'utf8mb4'
}

PROXY_CONFIG = {
    'server': 'http://46.182.207.241:12323',
    'username': '14ab0fcf235c2',
    'password': '380da05609'
}

UPDATE_INTERVAL = 60  # секунды
HOURS_AHEAD = 12

# Лиги
HIGH_LIQ_LEAGUES = [
    "England. Premier League",
    "Spain. La Liga",
    "Germany. Bundesliga",
    "Italy. Serie A",
    "France. Ligue 1",
]

LOW_LIQ_WHITELIST = [
    "India. Santosh Trophy",
    "Vietnam Championship U19",
    "Honduras. Liga Nacional. Reserve League",
]

EXCLUDE_KEYWORDS = [
    "ХОККЕЙ", "HOCKEY", "КХЛ", "KHL", "VHL",
    "БАСКЕТБОЛ", "BASKETBALL", "NBA",
    "ТЕННИС", "TENNIS",
    "ВОЛЕЙБОЛ", "VOLLEYBALL",
    "MLS",
]

# ============================================
# ПОРОГИ ДЛЯ ОБНАРУЖЕНИЯ АНОМАЛИЙ
# ============================================

SHARP_DROP_THRESHOLD = -3.0   # Резкое падение: -3% и больше
SHARP_RISE_THRESHOLD = 5.0     # Резкий рост: +5% и больше

print("=" * 60)
print("🚀 22bet PREMATCH Parser v30 - WITH HISTORY TRACKING")
print("=" * 60)
print(f"📊 Update: {UPDATE_INTERVAL}s | Window: {HOURS_AHEAD}h")
print(f"🔗 Proxy: {PROXY_CONFIG['server']}")
print(f"📈 Sharp Drop Threshold: {SHARP_DROP_THRESHOLD}%")
print(f"📈 Sharp Rise Threshold: {SHARP_RISE_THRESHOLD}%")
print("=" * 60)


# ============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

def classify_league(league_name: str):
    """Классификация ликвидности лиги"""
    if league_name in HIGH_LIQ_LEAGUES:
        return 'high', 0
    if league_name in LOW_LIQ_WHITELIST:
        return 'low', 0
    return 'low', 1


def calculate_change_percent(old_value, new_value):
    """Вычисляет процент изменения коэффициента"""
    if old_value is None or new_value is None or old_value == 0:
        return 0.0
    return ((new_value - old_value) / old_value) * 100


def detect_anomaly(change_percent):
    """Обнаруживает аномалию и определяет серьезность"""
    is_sharp_drop = change_percent <= SHARP_DROP_THRESHOLD
    is_sharp_rise = change_percent >= SHARP_RISE_THRESHOLD
    
    # Определяем серьезность
    abs_change = abs(change_percent)
    if abs_change >= 10:
        severity = 'critical'
    elif abs_change >= 7:
        severity = 'high'
    elif abs_change >= 5:
        severity = 'medium'
    else:
        severity = 'low'
    
    return {
        'is_sharp_drop': is_sharp_drop,
        'is_sharp_rise': is_sharp_rise,
        'severity': severity
    }


# ============================================
# КЛАСС ПАРСЕРА
# ============================================

class PrematchParser:
    def __init__(self):
        self.conn, self.cursor = None, None
        self.seen_keys = set()
        self.previous_odds = {}  # Кэш предыдущих коэффициентов для отслеживания изменений
        
    def connect_db(self):
        """Подключение к БД"""
        self.conn = pymysql.connect(**DB_CONFIG)
        self.cursor = self.conn.cursor()
        print("✅ MySQL connected")
        
    def clear_old(self):
        """Удаление старых/неактуальных матчей"""
        now = datetime.now()
        cutoff = now + timedelta(hours=HOURS_AHEAD)
        stale_time = now - timedelta(minutes=5)
        
        # Удаляем начавшиеся матчи
        self.cursor.execute(
            "DELETE FROM odds_22bet WHERE bookmaker='22bet' AND match_time IS NOT NULL AND match_time <= %s",
            (now,)
        )
        deleted_started = self.cursor.rowcount
        
        # Удаляем матчи за пределами окна
        self.cursor.execute(
            "DELETE FROM odds_22bet WHERE bookmaker='22bet' AND match_time IS NOT NULL AND match_time > %s",
            (cutoff,)
        )
        deleted_outside = self.cursor.rowcount
        
        # Удаляем устаревшие данные
        self.cursor.execute(
            "DELETE FROM odds_22bet WHERE bookmaker='22bet' AND updated_at < %s",
            (stale_time,)
        )
        deleted_stale = self.cursor.rowcount
        
        self.conn.commit()
        print(f"🗑️  Deleted: {deleted_started} started | {deleted_outside} outside | {deleted_stale} stale")
        
    def parse_time(self, time_str: str):
        """Парсинг времени матча"""
        try:
            parts = time_str.strip().split()
            if len(parts) != 2:
                return None
                
            date_part, time_part = parts[0], parts[1]
            
            if '.' in date_part:
                day, month = date_part.split('.')
            else:
                day, month = date_part.split('/')
                
            hour, minute = time_part.split(':')
            
            now = datetime.now()
            year = now.year
            dt = datetime(year, int(month), int(day), int(hour), int(minute))
            
            # Если дата в прошлом, значит это следующий год
            if dt < now:
                dt = datetime(year + 1, int(month), int(day), int(hour), int(minute))
                
            return dt
        except Exception:
            return None
    
    def get_previous_odds(self, event_name, market_type='1X2'):
        """Получает предыдущие коэффициенты из кэша"""
        key = f"{event_name}_{market_type}"
        return self.previous_odds.get(key)
    
    def save_odds_history(self, event_name, event_id, odds_data, match_time, league):
        """Сохраняет историю изменения коэффициентов"""
        try:
            # Получаем предыдущие коэффициенты
            prev_data = self.get_previous_odds(event_name, '1X2')
            
            # Вычисляем изменения для каждого коэффициента
            changes = {}
            if prev_data:
                changes['home_change'] = calculate_change_percent(prev_data.get('odd1'), odds_data['odd1'])
                changes['draw_change'] = calculate_change_percent(prev_data.get('oddx'), odds_data['oddx'])
                changes['away_change'] = calculate_change_percent(prev_data.get('odd2'), odds_data['odd2'])
            else:
                changes = {'home_change': 0, 'draw_change': 0, 'away_change': 0}
            
            # Проверяем на аномалии
            max_change = max(abs(changes['home_change']), abs(changes['draw_change']), abs(changes['away_change']))
            anomaly_info = detect_anomaly(max_change) if max_change != 0 else {
                'is_sharp_drop': False,
                'is_sharp_rise': False,
                'severity': 'low'
            }
            
            # Сохраняем в odds_history
            sql_history = """
                INSERT INTO odds_history (
                    event_id, event_name, bookmaker, market_type,
                    home_win, draw, away_win,
                    match_status, change_percent, 
                    is_sharp_drop, is_sharp_rise
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            self.cursor.execute(sql_history, (
                event_id or event_name[:50],
                event_name,
                '22bet',
                '1X2',
                odds_data['odd1'],
                odds_data['oddx'],
                odds_data['odd2'],
                'prematch',
                max_change,
                anomaly_info['is_sharp_drop'],
                anomaly_info['is_sharp_rise']
            ))
            
            # Если обнаружена аномалия, сохраняем в odds_anomalies
            if anomaly_info['is_sharp_drop'] or anomaly_info['is_sharp_rise']:
                # Определяем, какой коэффициент изменился больше всего
                changes_abs = {
                    'home': abs(changes['home_change']),
                    'draw': abs(changes['draw_change']),
                    'away': abs(changes['away_change'])
                }
                max_change_type = max(changes_abs, key=changes_abs.get)
                
                if max_change_type == 'home':
                    odds_before = prev_data.get('odd1')
                    odds_after = odds_data['odd1']
                    change_val = changes['home_change']
                elif max_change_type == 'draw':
                    odds_before = prev_data.get('oddx')
                    odds_after = odds_data['oddx']
                    change_val = changes['draw_change']
                else:
                    odds_before = prev_data.get('odd2')
                    odds_after = odds_data['odd2']
                    change_val = changes['away_change']
                
                anomaly_type = 'sharp_drop' if anomaly_info['is_sharp_drop'] else 'sharp_rise'
                
                sql_anomaly = """
                    INSERT INTO odds_anomalies (
                        event_id, event_name, bookmaker, market_type,
                        odds_before, odds_after, change_percent,
                        anomaly_type, severity
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                
                self.cursor.execute(sql_anomaly, (
                    event_id or event_name[:50],
                    event_name,
                    '22bet',
                    f'1X2-{max_change_type}',
                    odds_before,
                    odds_after,
                    change_val,
                    anomaly_type,
                    anomaly_info['severity']
                ))
                
                # Логируем аномалию
                emoji = "🔴" if anomaly_info['is_sharp_drop'] else "🟢"
                print(f"{emoji} ANOMALY: {event_name[:40]} | {max_change_type.upper()} {change_val:+.2f}% | {anomaly_info['severity'].upper()}")
            
            # Обновляем кэш
            key = f"{event_name}_1X2"
            self.previous_odds[key] = {
                'odd1': odds_data['odd1'],
                'oddx': odds_data['oddx'],
                'odd2': odds_data['odd2'],
                'timestamp': datetime.now()
            }
            
        except Exception as e:
            print(f"❌ History error: {e}")
    
    async def parse_prematch(self, page):
        """Основная функция парсинга"""
        try:
            print("⏳ Loading football page...")
            await page.goto('https://22betluck.com/ru/line/football', timeout=90000)
            await page.wait_for_timeout(8000)
            
            current_url = page.url
            print(f"📍 Current URL: {current_url}")
            
            if 'football' not in current_url.lower():
                print(f"❌ WRONG PAGE! Expected football, got {current_url}")
                return 0
                
        except Exception as e:
            print(f"❌ Page load error: {e}")
            return 0
        
        # Скроллинг
        print("📜 Scrolling to bottom...")
        previous_height = 0
        scroll_iterations = 0
        max_iterations = 200
        
        while scroll_iterations < max_iterations:
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await page.wait_for_timeout(500)
            current_height = await page.evaluate('document.body.scrollHeight')
            
            if current_height == previous_height:
                print(f"✅ Reached bottom after {scroll_iterations} scrolls")
                break
                
            previous_height = current_height
            scroll_iterations += 1
            
            if scroll_iterations % 20 == 0:
                print(f"   ... {scroll_iterations}")
        
                # Раскрытие свернутых лиг
        print("🔓 Expanding collapsed league blocks...")
        for attempt in range(5):
            try:
                league_info = await page.evaluate("""
                    async () => {
                        let totalExpanded = 0;
                        const leagueBlocks = document.querySelectorAll('.c-events');
                        for (const block of leagueBlocks) {
                            const header = block.querySelector('.c-events__item--head');
                            if (!header) continue;
                            const visibleMatches = block.querySelectorAll('.c-events__item--col .c-events__item');
                            if (visibleMatches.length < 100) {
                                const leagueName = header.querySelector('.c-events__name');
                                if (leagueName) {
                                    leagueName.click();
                                    totalExpanded++;
                                    await new Promise(r => setTimeout(r, 500));
                                }
                            }
                        }
                        return totalExpanded;
                    }
                """)
                print(f"   #{attempt + 1}: {league_info}")
                if league_info == 0:
                    break
                await page.wait_for_timeout(3000)
            except Exception as e:
                print(f"❌ Expand error: {e}")
        
        # Получаем блоки лиг
        league_blocks = await page.query_selector_all('.c-events')
        print(f"📦 Found {len(league_blocks)} league blocks")
        
        now = datetime.now()
        cutoff = now + timedelta(hours=HOURS_AHEAD)
        saved = 0
        skipped = 0
        
        self.seen_keys.clear()
        
        for idx, league_block in enumerate(league_blocks):
            try:
                league_name = "Unknown"
                head_liga = await league_block.query_selector('.c-events__item--head .c-events__name .c-events__liga')
                if head_liga:
                    league_name = (await head_liga.inner_text()).strip()
                
                # Фильтрация по ключевым словам
                if any(keyword in league_name.upper() for keyword in EXCLUDE_KEYWORDS):
                    continue
                
                # Получаем матчи
                match_rows = await league_block.query_selector_all('.c-events__item--col .c-events__item')
                
                for row in match_rows:
                    try:
                        # Время матча
                        time_el = await row.query_selector('.c-events__time.min span')
                        if not time_el:
                            skipped += 1
                            continue
                        
                        time_str = (await time_el.inner_text()).strip()
                        match_time = self.parse_time(time_str)
                        
                        if not match_time:
                            skipped += 1
                            continue
                        
                        if match_time > cutoff:
                            skipped += 1
                            continue
                        
                        # Команды
                        team_nodes = await row.query_selector_all('.c-events__name .c-events__teams .c-events__team')
                        if len(team_nodes) != 2:
                            skipped += 1
                            continue
                        
                        team1 = (await team_nodes[0].inner_text()).strip()
                        team2 = (await team_nodes[1].inner_text()).strip()
                        
                        # Проверка валидности команд
                        if (team1 == "Home" or team2 == "Away" or team1 == team2 or 
                            "?" in team1 or "?" in team2 or not team1 or not team2):
                            skipped += 1
                            continue
                        
                        # Проверка уникальности
                        key = (league_name, team1, team2, match_time)
                        if key in self.seen_keys:
                            continue
                        self.seen_keys.add(key)
                        
                        # Коэффициенты
                        odds_nodes = await row.query_selector_all('.c-bets .c-bets__bet.c-bets__bet--sm')
                        if len(odds_nodes) < 3:
                            skipped += 1
                            continue
                        
                        try:
                            odd1 = float((await odds_nodes[0].inner_text()).strip())
                            oddx = float((await odds_nodes[1].inner_text()).strip())
                            odd2 = float((await odds_nodes[2].inner_text()).strip())
                        except Exception:
                            skipped += 1
                            continue
                        
                        event_name = f"{team1} vs {team2}"
                        liquidity_level, is_suspicious = classify_league(league_name)
                        
                        # Сохраняем в основную таблицу odds_22bet
                        sql = """
                            INSERT INTO odds_22bet 
                            (event_name, sport, league, odd1, oddx, odd2, status, bookmaker, match_time, liquidity_level, is_suspicious, updated_at)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                            ON DUPLICATE KEY UPDATE 
                            odd1=%s, oddx=%s, odd2=%s, match_time=%s, league=%s, liquidity_level=%s, is_suspicious=%s, status='active', updated_at=NOW()
                        """
                        
                        params = (
                            event_name, 'Football', league_name,
                            round(odd1, 2), round(oddx, 2), round(odd2, 2),
                            'active', '22bet', match_time,
                            liquidity_level, is_suspicious,
                            # ON DUPLICATE KEY UPDATE
                            round(odd1, 2), round(oddx, 2), round(odd2, 2),
                            match_time, league_name, liquidity_level, is_suspicious
                        )
                        
                        try:
                            self.cursor.execute(sql, params)
                            
                            # 🆕 СОХРАНЯЕМ ИСТОРИЮ КОЭФФИЦИЕНТОВ
                            odds_data = {'odd1': odd1, 'oddx': oddx, 'odd2': odd2}
                            self.save_odds_history(
                                event_name=event_name,
                                event_id=None,  # У 22bet нет явного event_id в prematch
                                odds_data=odds_data,
                                match_time=match_time,
                                league=league_name
                            )
                            
                        except Exception as e:
                            print(f"❌ DB error for {event_name}: {e}")
                            self.conn.rollback()
                            skipped += 1
                            continue
                        
                        saved += 1
                        time_left = (match_time - now).total_seconds() / 3600
                        
                        # Логирование
                        if "🔥" in league_name.upper() or "⚽" in league_name.upper():
                            print(f"💾 {saved:3d}. {event_name:50s} | {league_name[:40]:40s} | {odd1:.2f}/{oddx:.2f}/{odd2:.2f} | {time_left:.1f}h")
                        else:
                            print(f"💾 {saved:3d}. {event_name:50s} | {league_name[:40]:40s} | {odd1:.2f}/{oddx:.2f}/{odd2:.2f} | {time_left:.1f}h")
                    
                    except Exception:
                        skipped += 1
                        
            except Exception:
                skipped += 1
        
        self.conn.commit()
        print(f"\n✅ SAVED: {saved} | ⏭️  SKIPPED: {skipped}")
        return saved
    
    async def run(self):
        """Основной цикл парсера"""
        self.connect_db()
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                proxy=PROXY_CONFIG
            )
            page = await browser.new_page()
            
            while True:
                try:
                    self.clear_old()
                    await self.parse_prematch(page)
                    print(f"\n⏰ Next in {UPDATE_INTERVAL}s...\n")
                    await asyncio.sleep(UPDATE_INTERVAL)
                except Exception as e:
                    print(f"❌ Error: {e}")
                    await asyncio.sleep(15)


if __name__ == '__main__':
    parser = PrematchParser()
    asyncio.run(parser.run())

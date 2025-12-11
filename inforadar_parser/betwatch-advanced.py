import asyncio
import logging
import json
import os
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from collections import defaultdict
import mysql.connector

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

class BetWatchAdvancedParser:
    """
    Advanced Betwatch parser с:
    - Sharp Move (падение кэф)
    - Line Shift (движение за сутки)
    - Odds Squeeze (сжатие диапазона)
    - Volume Spike (скачок объёма)
    - Фильтр по топ-лигам
    """
    
    TOP_LEAGUES = {
        'Premier League', 'La Liga', 'Serie A', 'Bundesliga', 'Ligue 1',
        'Champions League', 'Europa League', 'World Cup', 'European Championship'
    }
    
    def __init__(self):
        self.session = None
        self.previous_data = {}  # Для детектирования изменений
        self.daily_history = defaultdict(list)  # История за день
        self.db = None
        
    async def init(self):
        """Инициализируем браузер и БД"""
        self.session = async_playwright().__aenter__()
        self.browser = await self.session.chromium.launch(headless=True)
        
        try:
            self.db = mysql.connector.connect(
                host='mysql_inforadar',
                user='inforadar_user',
                password='inforadar_pass',
                database='inforadar'
            )
        except:
            logger.warning("⚠️  MySQL недоступен, работаем без сохранения")
            
    async def fetch_data(self):
        """Получаем данные с Betwatch"""
        page = await self.browser.new_page()
        try:
            logger.info("📡 Подключаемся к betwatch.fr/money...")
            await page.goto('https://betwatch.fr/money', wait_until='domcontentloaded', timeout=20000)
            await page.click('button:has-text("Live")', timeout=5000)
            await page.wait_for_timeout(2000)
            
            # Парсим данные из Alpine.js
            data = await page.evaluate('''() => {
                if (!window.__NUXT__) return null;
                const store = window.__NUXT__.$store.state;
                return store.moneywayDetails || [];
            }''')
            
            return data or []
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга: {e}")
            return []
        finally:
            await page.close()
    
    def filter_by_league(self, events):
        """Фильтруем только топ-лиги"""
        return [e for e in events if e.get('ln', '') in self.TOP_LEAGUES]
    
    def detect_sharp_move(self, event_id, new_odds):
        """Детектирует падение коэффициента (Sharp Move)"""
        if event_id not in self.previous_data:
            return None
        
        old_odds = self.previous_data[event_id]['odds']
        sharp_moves = []
        
        for bet_type in ['1', 'X', '2']:
            if bet_type in old_odds and bet_type in new_odds:
                old = old_odds[bet_type]
                new = new_odds[bet_type]
                
                if old > 0:
                    change_percent = ((old - new) / old) * 100
                    
                    # Sharp Move: падение 10-30% за 3 мин
                    if 10 <= change_percent <= 30:
                        sharp_moves.append({
                            'type': 'SHARP_MOVE',
                            'bet': bet_type,
                            'old_odds': old,
                            'new_odds': new,
                            'change_percent': round(change_percent, 2),
                            'severity': 'MEDIUM' if change_percent < 20 else 'HIGH'
                        })
        
        return sharp_moves if sharp_moves else None
    
    def detect_line_shift(self, event_id, new_odds):
        """Детектирует движение линии за сутки (Line Shift)"""
        history = self.daily_history[event_id]
        if len(history) < 2:
            return None
        
        oldest = history[0]['odds']
        newest = new_odds
        line_shifts = []
        
        for bet_type in ['1', 'X', '2']:
            if bet_type in oldest and bet_type in newest:
                old = oldest[bet_type]
                new = newest[bet_type]
                
                if old > 0:
                    shift_percent = ((new - old) / old) * 100
                    
                    # Line Shift: движение > 15% за день
                    if abs(shift_percent) > 15:
                        line_shifts.append({
                            'type': 'LINE_SHIFT',
                            'bet': bet_type,
                            'start_odds': old,
                            'current_odds': new,
                            'shift_percent': round(shift_percent, 2),
                            'direction': 'DOWN' if shift_percent < 0 else 'UP'
                        })
        
        return line_shifts if line_shifts else None
    
    def detect_odds_squeeze(self, event_id, new_odds, event_name):
        """Детектирует сжатие диапазона котировок (Odds Squeeze)"""
        if event_id not in self.previous_data:
            return None
        
        old_odds = self.previous_data[event_id]['odds']
        
        # Squeeze: диапазон (max - min) сокращается на 20%+
        old_range = max(old_odds.values()) - min(old_odds.values())
        new_range = max(new_odds.values()) - min(new_odds.values())
        
        if old_range > 0:
            squeeze_percent = ((old_range - new_range) / old_range) * 100
            
            if squeeze_percent > 20:
                return {
                    'type': 'ODDS_SQUEEZE',
                    'old_range': round(old_range, 2),
                    'new_range': round(new_range, 2),
                    'squeeze_percent': round(squeeze_percent, 2)
                }
        return None
    
    def detect_volume_spike(self, event_id, new_volume):
        """Детектирует скачок объёма ставок (Volume Spike)"""
        if event_id not in self.previous_data:
            return None
        
        old_volume = self.previous_data[event_id]['volume']
        
        if old_volume > 0:
            spike_percent = ((new_volume - old_volume) / old_volume) * 100
            
            # Spike: скачок > 50% за 3 минуты
            if spike_percent > 50:
                return {
                    'type': 'VOLUME_SPIKE',
                    'old_volume': int(old_volume),
                    'new_volume': int(new_volume),
                    'spike_percent': round(spike_percent, 2)
                }
        return None
    
    async def analyze_events(self, events):
        """Анализируем события и детектируем сигналы"""
        signals = []
        
        for event in events:
            event_id = event.get('e')
            event_name = event.get('m', '')
            league = event.get('ln', '')
            
            if not event_id or league not in self.TOP_LEAGUES:
                continue
            
            # Парсим коэффициенты
            odds = {}
            for odd in event.get('i', []):
                if len(odd) >= 3:
                    odds[odd[0]] = odd[2]
            
            volume = event.get('v', 0)
            
            # Детектируем сигналы
            sharp_move = self.detect_sharp_move(event_id, odds)
            line_shift = self.detect_line_shift(event_id, odds)
            squeeze = self.detect_odds_squeeze(event_id, odds, event_name)
            spike = self.detect_volume_spike(event_id, volume)
            
            signal = {
                'event_id': event_id,
                'event_name': event_name,
                'league': league,
                'odds': odds,
                'volume': volume,
                'timestamp': datetime.now().isoformat()
            }
            
            if sharp_move:
                signal['sharp_moves'] = sharp_move
                signals.append(signal)
                logger.info(f"🔴 SHARP MOVE: {event_name} | {sharp_move}")
            
            if line_shift:
                signal['line_shifts'] = line_shift
                signals.append(signal)
                logger.info(f"📊 LINE SHIFT: {event_name} | {line_shift}")
            
            if squeeze:
                signal['squeeze'] = squeeze
                signals.append(signal)
                logger.info(f"✂️ ODDS SQUEEZE: {event_name}")
            
            if spike:
                signal['volume_spike'] = spike
                signals.append(signal)
                logger.info(f"💥 VOLUME SPIKE: {event_name} | +{spike['spike_percent']}%")
            
            # Обновляем историю
            self.previous_data[event_id] = {'odds': odds, 'volume': volume}
            self.daily_history[event_id].append({'odds': odds, 'timestamp': datetime.now()})
        
        return signals
    
    async def save_to_db(self, signals):
        """Сохраняем сигналы в БД"""
        if not self.db:
            return
        
        try:
            cursor = self.db.cursor()
            for signal in signals:
                signal_type = 'SHARP_MOVE' if 'sharp_moves' in signal else \
                              'LINE_SHIFT' if 'line_shifts' in signal else \
                              'SQUEEZE' if 'squeeze' in signal else 'VOLUME_SPIKE'
                
                sql = '''INSERT INTO betwatch_signals 
                        (event_id, event_name, league, signal_type, data, timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s)'''
                
                cursor.execute(sql, (
                    signal['event_id'],
                    signal['event_name'],
                    signal['league'],
                    signal_type,
                    json.dumps(signal),
                    signal['timestamp']
                ))
            
            self.db.commit()
            logger.info(f"✅ Сохранено сигналов: {len(signals)}")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения: {e}")
    
    async def run(self):
        """Основной цикл парсинга"""
        await self.init()
        cycle = 0
        
        try:
            while True:
                cycle += 1
                logger.info(f"🔄 Цикл #{cycle}")
                
                # Получаем данные
                events = await self.fetch_data()
                
                # Фильтруем по лигам
                filtered = self.filter_by_league(events)
                logger.info(f"📊 События: всего {len(events)}, топ-лиги {len(filtered)}")
                
                # Анализируем
                signals = await self.analyze_events(filtered)
                
                # Сохраняем
                if signals:
                    await self.save_to_db(signals)
                
                logger.info(f"✅ Цикл #{cycle} завершен\n")
                await asyncio.sleep(180)  # 3 минуты
        
        except KeyboardInterrupt:
            logger.info("🛑 Парсер остановлен")
        finally:
            if self.db:
                self.db.close()
            await self.browser.close()


async def main():
    parser = BetWatchAdvancedParser()
    await parser.run()


if __name__ == "__main__":
    asyncio.run(main())

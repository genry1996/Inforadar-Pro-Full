import asyncio
import logging
import mysql.connector
from mysql.connector import Error
from playwright.async_api import async_playwright
from datetime import datetime
import os

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

class ArbitrageDetector:
    def __init__(self):
        self.db_config = {
            'host': os.getenv('MYSQL_HOST', 'mysql_inforadar'),
            'user': os.getenv('MYSQL_USER', 'inforadar_user'),
            'password': os.getenv('MYSQL_PASSWORD', 'inforadar_password'),
            'database': os.getenv('MYSQL_DB', 'inforadar'),
            'port': 3306
        }
        self.connection = None
        self.browser = None
        self.page = None
        self.playwright = None

    async def connect_db(self):
        """Подключение к БД"""
        try:
            self.connection = mysql.connector.connect(**self.db_config)
            logger.info("✅ Подключено к базе данных")
            return True
        except Error as e:
            logger.error(f"❌ Ошибка БД: {e}")
            return False

    async def init_browser(self):
        """Инициализация браузера"""
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=True)
            logger.info("✅ Браузер запущен")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка браузера: {e}")
            return False

    async def close_browser(self):
        """Закрытие браузера"""
        if self.page:
            await self.page.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("✅ Браузер закрыт")

    async def fetch_signals(self):
        """Получение сигналов из БД"""
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM signals WHERE status='active' ORDER BY created_at DESC LIMIT 10")
            signals = cursor.fetchall()
            cursor.close()
            
            if signals:
                logger.info(f"📊 Найдено {len(signals)} сигналов")
                for signal in signals:
                    logger.info(f"  • {signal['event_name']} - {signal['signal_type']}")
            else:
                logger.info("⏳ Сигналов не найдено")
            
            return signals
        except Error as e:
            logger.error(f"❌ Ошибка при получении сигналов: {e}")
            return []

    async def calculate_arbitrage(self, signal):
        """Расчет арбитража для сигнала"""
        try:
            # Получи коэффициенты из БД
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute("""
                SELECT * FROM arbitrage_signals 
                WHERE signal_id = %s 
                ORDER BY created_at DESC LIMIT 1
            """, (signal['id'],))
            arb = cursor.fetchone()
            cursor.close()
            
            if arb:
                profit_percent = arb.get('profit_percent', 0)
                logger.info(f"💰 Прибыль: {profit_percent}%")
                return arb
            else:
                logger.info(f"ℹ️ Арбитраж не рассчитан")
                return None
        except Error as e:
            logger.error(f"❌ Ошибка расчета: {e}")
            return None

    async def run(self):
        """Основной цикл"""
        logger.info("=" * 80)
        logger.info("🎯 === ARBITRAGE DETECTOR v1 ===")
        logger.info("=" * 80)
        logger.info("📊 Мониторинг: Betwatch + 22bet")
        logger.info("💰 Расчет прибыли в реальном времени")
        logger.info("=" * 80)
        
        # Подключение к БД
        if not await self.connect_db():
            logger.error("❌ Не удалось подключиться к БД")
            return
        
        # Инициализация браузера
        if not await self.init_browser():
            logger.error("❌ Не удалось запустить браузер")
            return
        
        cycle = 0
        try:
            while True:
                cycle += 1
                logger.info(f"\n📊 Цикл #{cycle}: {datetime.now().strftime('%H:%M:%S')}")
                
                # Получение сигналов
                signals = await self.fetch_signals()
                
                if signals:
                    logger.info(f"✅ Обработка {len(signals)} сигналов...")
                    for signal in signals:
                        arb = await self.calculate_arbitrage(signal)
                        if arb and arb.get('profit_percent', 0) > 2:
                            logger.warning(f"🚨 ВЫСОКИЙ АРБИТРАЖ: {arb['profit_percent']}%")
                else:
                    logger.info("⏳ Нет активных сигналов, жду 30 секунд...")
                
                # Пауза перед следующим циклом
                await asyncio.sleep(30)
                
        except KeyboardInterrupt:
            logger.info("\n⛔ Остановка детектора...")
        except Exception as e:
            logger.error(f"❌ Ошибка в основном цикле: {e}")
        finally:
            await self.close_browser()
            if self.connection:
                self.connection.close()
            logger.info("✅ Детектор остановлен")

async def main():
    detector = ArbitrageDetector()
    await detector.run()

if __name__ == "__main__":
    asyncio.run(main())

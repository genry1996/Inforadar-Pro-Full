import logging

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self):
        logger.info("📱 Telegram отключен (demo режим)")
    
    def send_anomaly(self, bookmaker, anomaly):
        logger.info(f"📨 [Telegram] {bookmaker}: {anomaly['event_name']}")

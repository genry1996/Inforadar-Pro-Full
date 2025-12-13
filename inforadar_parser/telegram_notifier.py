# telegram_notifier.py

import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self):
        self.bots = {
            '22bet': {
                'token': '8403963559:AAFoF6QYeRr2CIH2NEeLBxh5BYRX6XTHNxo',
                'chat_id': '5377484616'
            }
        }
    
    def send_anomaly(self, source: str, anomaly: dict):
        """Отправить уведомление об аномалии"""
        
        bot_config = self.bots.get(source)
        if not bot_config:
            logger.error(f"❌ Бот {source} не настроен")
            return False
        
        # Форматирование сообщения
        emoji_map = {
            'ODDS_DROP': '📉',
            'ODDS_RISE': '📈',
            'REMOVED': '🚫',
            'FROZEN': '❄️'
        }
        
        emoji = emoji_map.get(anomaly['anomaly_type'], '⚠️')
        status_emoji = '✅' if anomaly['status'] == 'confirmed' else '⏳'
        
        message = f"""
{emoji} <b>{anomaly['anomaly_type']}</b> {status_emoji}

🏆 <b>{anomaly['event_name']}</b>
⚽ {anomaly.get('sport', 'Unknown')}
🎯 Лига: {anomaly.get('league', 'Mixed')}

💰 Было: <code>{anomaly['before_value']}</code>
💸 Стало: <code>{anomaly['after_value']}</code>
📊 Изменение: <b>{anomaly['diff_pct']}%</b>

📝 {anomaly.get('comment', '')}

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
        
        # Отправка
        url = f"https://api.telegram.org/bot{bot_config['token']}/sendMessage"
        payload = {
            'chat_id': bot_config['chat_id'],
            'text': message,
            'parse_mode': 'HTML'
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info(f"✅ Telegram: {anomaly['event_name']} → {source}")
                return True
            else:
                logger.error(f"❌ Telegram error: {response.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Telegram exception: {e}")
            return False
    
    def test_connection(self, source: str):
        """Проверить подключение к боту"""
        
        bot_config = self.bots.get(source)
        if not bot_config:
            return False
        
        message = f"""
🤖 <b>Тест подключения</b>

✅ Бот подключен успешно!
📱 Источник: {source}
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        url = f"https://api.telegram.org/bot{bot_config['token']}/sendMessage"
        payload = {
            'chat_id': bot_config['chat_id'],
            'text': message,
            'parse_mode': 'HTML'
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Test failed: {e}")
            return False

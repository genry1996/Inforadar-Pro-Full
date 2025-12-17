import requests
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

class TelegramNotifier:
    """Класс для отправки уведомлений в Telegram"""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
    
    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Отправляет сообщение в Telegram"""
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }
            
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                logger.info(f"✅ Telegram сообщение отправлено в чат {self.chat_id}")
                return True
            else:
                logger.error(f"❌ Ошибка Telegram API: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в Telegram: {e}")
            return False
    
    def send_anomaly_alert(self, anomaly: Dict) -> bool:
        """Отправляет уведомление об аномалии"""
        
        # Определяем эмодзи в зависимости от типа аномалии
        emoji = "📉" if "DROP" in anomaly.get('anomaly_type', '') else "📈"
        
        # Определяем критичность
        diff_pct = abs(anomaly.get('diff_pct', 0))
        if diff_pct >= 10:
            urgency = "🔴 КРИТИЧНО"
        elif diff_pct >= 5:
            urgency = "🟠 ВАЖНО"
        elif diff_pct >= 2:
            urgency = "🟡 ЗНАЧИТЕЛЬНО"
        else:
            urgency = "🟢 НЕЗНАЧИТЕЛЬНО"
        
        # Формируем сообщение
        message = f"""
{urgency} {emoji} <b>АНОМАЛИЯ ОБНАРУЖЕНА!</b>

<b>Событие:</b> {anomaly.get('event_name', 'N/A')}
<b>Спорт:</b> {anomaly.get('sport', 'N/A')}
<b>Тип:</b> {anomaly.get('anomaly_type', 'N/A')}

<b>Изменение:</b> {anomaly.get('before_value', 'N/A')} → {anomaly.get('after_value', 'N/A')}
<b>Процент:</b> {diff_pct:.2f}%

<b>Комментарий:</b>
{anomaly.get('comment', 'N/A')}

<i>Время обнаружения: {anomaly.get('detected_at', 'N/A')}</i>
        """.strip()
        
        return self.send_message(message)
    
    def send_batch_alert(self, anomalies: List[Dict]) -> bool:
        """Отправляет групповое уведомление о нескольких аномалиях"""
        
        if not anomalies:
            return False
        
        count = len(anomalies)
        
        # Сортируем по размеру изменения
        sorted_anomalies = sorted(
            anomalies, 
            key=lambda x: abs(x.get('diff_pct', 0)), 
            reverse=True
        )
        
        # Берём топ-5 самых крупных
        top_anomalies = sorted_anomalies[:5]
        
        message = f"""
🚨 <b>ОБНАРУЖЕНО {count} АНОМАЛИЙ!</b>

<b>ТОП-5 КРУПНЕЙШИХ ИЗМЕНЕНИЙ:</b>

"""
        
        for i, anom in enumerate(top_anomalies, 1):
            emoji = "📉" if "DROP" in anom.get('anomaly_type', '') else "📈"
            message += f"""
{i}. {emoji} <b>{anom.get('event_name', 'N/A')}</b>
   {anom.get('before_value', 'N/A')} → {anom.get('after_value', 'N/A')} ({anom.get('diff_pct', 0):.2f}%)
"""
        
        message += f"""
<i>Всего обнаружено: {count} аномалий</i>
        """
        
        return self.send_message(message.strip())
    
    def send_test_message(self) -> bool:
        """Отправляет тестовое сообщение"""
        message = """
✅ <b>Тестовое сообщение</b>

Telegram бот успешно подключен!
Система мониторинга аномалий работает.

🤖 Бот готов к отправке уведомлений.
        """.strip()
        
        return self.send_message(message)


# Пример использования
if __name__ == "__main__":
    # Ваши данные
    BOT_TOKEN = "8403963559:AAFoF6QYeRr2CIH2NEeLBxh5BYRX6XTHNxo"
    CHAT_ID = "5377484616"
    
    notifier = TelegramNotifier(BOT_TOKEN, CHAT_ID)
    
    # Отправляем тестовое сообщение
    print("📤 Отправляю тестовое сообщение...")
    success = notifier.send_test_message()
    
    if success:
        print("✅ Тестовое сообщение успешно отправлено!")
    else:
        print("❌ Не удалось отправить тестовое сообщение")

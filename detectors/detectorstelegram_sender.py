# detectors/telegram_sender.py
import asyncio
from telegram import Bot

class TelegramAlertSender:
    def __init__(self, bot_token):
        self.bot = Bot(token=bot_token)
        
    async def send_alert(self, anomaly, user_alerts):
        """Отправляет алерт пользователям по их настройкам"""
        for user_alert in user_alerts:
            # Проверяем соответствие фильтрам пользователя
            if self.matches_user_filter(anomaly, user_alert):
                message = self.format_alert_message(anomaly)
                await self.bot.send_message(
                    chat_id=user_alert['telegram_id'],
                    text=message,
                    parse_mode='HTML'
                )
    
    def format_alert_message(self, anomaly):
        return f"""
🚨 <b>ODDS DROP DETECTED</b>

⚽ {anomaly['match_info']['home_team']} vs {anomaly['match_info']['away_team']}
🏆 {anomaly['match_info']['league']}

📉 Home Win: {anomaly['before']} → {anomaly['after']} ({anomaly['change_pct']:.1f}%)
⚠️ Severity: {anomaly['severity']}
🕐 {anomaly['timestamp']}

🔗 <a href="http://localhost:5000/match/{anomaly['match_id']}">View Details</a>
        """

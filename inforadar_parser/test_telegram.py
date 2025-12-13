# test_telegram.py
from telegram_notifier import TelegramNotifier

notifier = TelegramNotifier()

# Тест подключения
print("🧪 Тестируем Telegram бота...")
if notifier.test_connection('22bet'):
    print("✅ Telegram бот работает!")
else:
    print("❌ Ошибка подключения")

# Тест отправки аномалии
test_anomaly = {
    'event_name': 'Тестовый матч vs Тестовый соперник',
    'sport': 'Football',
    'league': 'Test League',
    'anomaly_type': 'ODDS_DROP',
    'before_value': '2.50',
    'after_value': '1.80',
    'diff_pct': -28.0,
    'status': 'confirmed',
    'comment': '1: 2.500 -> 1.800 (подтверждено)'
}

print("\n📤 Отправляем тестовое уведомление...")
if notifier.send_anomaly('22bet', test_anomaly):
    print("✅ Тестовое уведомление отправлено!")
else:
    print("❌ Ошибка отправки")

# bot/main.py

import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.filters import Command

# Настройки Telegram
API_TOKEN = "8395433352:AAEIvIuX7cJ-_is2NbCjs7uA0-QF3e_eoTY"
CHAT_ID = "5377484616"

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Простой хендлер команды /start
@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer("🤖 Oddly Odds Production — бот работает.")

# Функция отправки алерта
async def send_alert(text: str):
    await bot.send_message(chat_id=CHAT_ID, text=text)

# Пример отправки тестового алерта
async def main():
    try:
        await send_alert("✅ Oddly Odds бот успешно запущен.")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())

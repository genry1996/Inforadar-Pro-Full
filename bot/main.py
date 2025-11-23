from aiogram import Bot, Dispatcher, types
import asyncio
import logging
import os

API_TOKEN = "8395433352:AAEIvIuX7cJ-_is2NbCjs7uA0-QF3e_eoTY"
CHAT_ID = "5377484616"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

@dp.message_handler(commands=["start"])
async def send_welcome(message: types.Message):
    await message.reply("👋 Привет! OddlyOdds бот на связи.")

async def main():
    await dp.start_polling()

if __name__ == "__main__":
    asyncio.run(main())

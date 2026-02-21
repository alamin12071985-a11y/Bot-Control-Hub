import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from config import BOT_TOKEN
import database as db
import handlers
import client_instance

# Logging
logging.basicConfig(level=logging.INFO)

async def main():
    # Init DB
    db.init_db()
    
    # Controller Bot
    bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher()
    
    # Register Handlers
    dp.include_router(handlers.router)
    
    # Load existing Client Bots
    await client_instance.load_all_bots()
    
    # Start Polling
    print("🚀 Bot Control Hub is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

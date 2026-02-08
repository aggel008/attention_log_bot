#!/usr/bin/env python3
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from config import load_config
from handlers.admin import admin_router
from middlewares.album import AlbumMiddleware
from services.gpt import GPTService

async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    config = load_config()
    
    # Инициализация
    bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    
    # Сервисы
    gpt_service = GPTService(config)
    
    # Прокидываем объекты внутрь хендлеров
    dp['config'] = config
    dp['gpt'] = gpt_service
    
    # Подключаем Middleware и Роутеры
    dp.message.middleware(AlbumMiddleware())
    dp.include_router(admin_router)
    
    logging.info('🚀 Attention Log Bot started!')
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('Exit')
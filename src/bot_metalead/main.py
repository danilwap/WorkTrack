import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from dotenv import load_dotenv


from src.bot_metalead.db.session import engine
from src.bot_metalead.db.models import Base
from src.bot_metalead.routers.handlers_start_manu import router as r_start
from src.bot_metalead.routers.user import router as r_tasks
from src.bot_metalead.routers.notes import router as r_notes
from src.bot_metalead.services.reminders_service import reminders_loop
from src.bot_metalead.routers.manager_tasks import router as manager_tasks_router
from src.bot_metalead.routers.admin_roles import router as admin_roles_router
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")



logging.basicConfig(level=logging.INFO)

dp = Dispatcher()


async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer("Привет! Я бот. Нажми /help или просто напиши сообщение 🙂")


@dp.message()
async def echo_handler(message: Message):
    await message.answer(f"Ты написал: {message.text}")


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Set BOT_TOKEN env var")

    await on_startup()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin_roles_router)
    dp.include_router(manager_tasks_router)
    dp.include_router(r_start)
    dp.include_router(r_tasks)
    dp.include_router(r_notes)

    # фон по напоминаниям (в рамках процесса)
    asyncio.create_task(reminders_loop(bot))

    await dp.start_polling(bot)

    bot = Bot(token=BOT_TOKEN)
    await dp.start_polling(bot)

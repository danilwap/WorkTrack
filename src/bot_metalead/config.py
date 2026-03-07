import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
from dotenv import load_dotenv
from dataclasses import dataclass

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not BOT_TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN. Укажи его в .env")

logging.basicConfig(level=logging.INFO)

dp = Dispatcher()




@dp.message()
async def echo_handler(message: Message):
    await message.answer(f"Ты написал: {message.text}")




def parse_admin_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    result: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ValueError(f"ADMIN_TG_IDS must be comma-separated integers, got: {part!r}")
        result.add(int(part))
    return result


@dataclass(frozen=True)
class Settings:
    admin_tg_ids: set[int]


settings = Settings(
    admin_tg_ids=parse_admin_ids(os.getenv("ADMIN_TG_IDS")),
)


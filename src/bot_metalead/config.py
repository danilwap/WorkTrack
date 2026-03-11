import logging
import os

from aiogram import Dispatcher
from dotenv import load_dotenv
from dataclasses import dataclass

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

DATABASE_URL = (
    f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

if not BOT_TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN. Укажи его в .env")

logging.basicConfig(level=logging.INFO)

dp = Dispatcher()



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


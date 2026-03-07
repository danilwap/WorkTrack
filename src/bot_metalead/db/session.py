# session.py
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import DATABASE_URL

# Пример: postgresql+asyncpg://user:pass@localhost:5432/dbname
#DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/app")

# В проде часто ставят pool_pre_ping=True, чтобы не падать на "stale connections"
engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,          # True, если хочешь видеть SQL в логах
    pool_pre_ping=True,
)

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """
    Контекст для работы с БД:
      - на успех: commit
      - на исключение: rollback
      - всегда: close
    """
    session = SessionFactory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    """Корректно закрыть пул соединений (например, при остановке приложения)."""
    await engine.dispose()
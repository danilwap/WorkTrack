from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from sqlalchemy import select

from src.bot_metalead.config import settings
from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.models import User, UserRole


router = Router()


def is_admin(tg_id: int) -> bool:
    return tg_id in settings.admin_tg_ids


def normalize_role(raw: str) -> UserRole | None:
    raw = raw.strip().lower()
    try:
        return UserRole(raw)
    except Exception:
        return None


@router.message(Command("set_role"))
async def cmd_set_role(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("⛔️ Нет доступа (только админы из ADMIN_TG_IDS).")

    # ожидаем: /set_role @username manager
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        return await message.answer(
            "Использование:\n"
            "/set_role @username manager\n"
            "или\n"
            "/set_role 123456789 employee\n\n"
            f"Роли: {', '.join([r.value for r in UserRole])}"
        )

    target_raw = parts[1].strip()
    role_raw = parts[2].strip()

    role = normalize_role(role_raw)
    if not role:
        return await message.answer(
            f"Неизвестная роль: {role_raw}\n"
            f"Доступные: {', '.join([r.value for r in UserRole])}"
        )

    # Разрешаем: @username или tg_id
    target_username: str | None = None
    target_tg_id: int | None = None

    if target_raw.startswith("@"):
        target_username = target_raw[1:].strip().lstrip("@")
        if not target_username:
            return await message.answer("Неверный username. Пример: /set_role @username manager")
    else:
        if not target_raw.isdigit():
            return await message.answer("Цель должна быть @username или tg_id цифрами.")
        target_tg_id = int(target_raw)

    async with session_scope() as session:
        if target_username:
            q = await session.execute(select(User).where(User.username == target_username))
        else:
            q = await session.execute(select(User).where(User.tg_id == target_tg_id))

        user = q.scalar_one_or_none()
        if not user:
            who = f"@{target_username}" if target_username else str(target_tg_id)
            return await message.answer(
                f"Пользователь {who} не найден в БД.\n"
                "Пусть сначала нажмёт /start, чтобы мы его создали."
            )

        old_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        user.role = role
        await session.commit()

    who = f"@{target_username}" if target_username else str(target_tg_id)
    await message.answer(f"✅ Роль обновлена: {who} — {old_role} → {role.value}")
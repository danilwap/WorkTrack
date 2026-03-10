from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select

from src.bot_metalead.db.models import User, UserRole
from src.bot_metalead.db.session import session_scope


class IsManager(BaseFilter):
    def __init__(self):
        pass

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        tg_id = event.from_user.id

        async with session_scope() as session:
            q = await session.execute(
                select(User.id).where(
                    User.tg_id == tg_id,
                    User.role == UserRole.manager.value,
                )
            )
            user_id = q.scalar_one_or_none()

        if user_id is not None:
            return True

        if isinstance(event, Message):
            await event.answer("⛔️ Доступ только для руководителя.")
        elif isinstance(event, CallbackQuery):
            await event.answer("⛔️ Доступ только для руководителя.", show_alert=True)

        return False

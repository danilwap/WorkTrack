from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot_metalead.db.models import User, UserRole



async def ensure_user(session: AsyncSession, tg_user) -> User:
    q = await session.execute(
        select(User).where(User.tg_id == tg_user.id)
    )

    user = q.scalar_one_or_none()

    if not user:
        user = User(
            tg_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
            role=UserRole.employee,
        )
        session.add(user)

    else:
        user.username = tg_user.username
        user.full_name = tg_user.full_name

    return user
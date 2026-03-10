from sqlalchemy import select, exists
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


async def get_user_tg_id_by_id(session: AsyncSession, user_id: int) -> int | None:
    q = await session.execute(
        select(User.tg_id).where(User.id == user_id)
    )
    return q.scalar_one_or_none()



async def is_manager(session: AsyncSession, tg_id: int) -> bool:
    q = await session.execute(
        select(exists().where(
            User.tg_id == tg_id,
            User.role == UserRole.manager
        ))
    )
    return q.scalar()


async def get_employees(session: AsyncSession) -> list[User]:
    q = await session.execute(
        select(User)
        .where(User.role == UserRole.employee)
        .order_by(User.full_name.asc().nulls_last())
    )
    return list(q.scalars().all())


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    q = await session.execute(
        select(User).where(User.id == user_id)
    )
    return q.scalar_one_or_none()
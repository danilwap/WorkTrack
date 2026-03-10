from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.repositories.tasks_repo import get_task_with_creator
from src.bot_metalead.db.models import User, Task


async def notify_task_creator_on_employee_comment(
    bot: Bot,
    task_id: int,
    author_name: str,
    comment_text: str,
    reply_markup=None,
) -> bool:
    """
    Уведомляем постановщика задачи о комментарии исполнителя.
    """

    try:
        async with session_scope() as session:
            task = await get_task_with_creator(session, task_id)

        if not task or not task.creator or not task.creator.tg_id:
            return False

        text = (
            f"💬 Комментарий от исполнителя\n"
            f"🧩 Задача #{task_id}: {task.title}\n"
            f"👤 {author_name}\n\n"
            f"{comment_text}"
        )

        await bot.send_message(task.creator.tg_id, text, reply_markup=reply_markup)

        return True

    except Exception:
        return False


async def notify_assignee(bot: Bot, task_id: int,
                          text: str, reply_markup=None) -> bool:
    """
    Уведомляет исполнителя задачи.
    Возвращает True если отправили, иначе False.
    """
    try:
        async with session_scope() as session:
            q = await session.execute(
                select(Task)
                .where(Task.id == task_id)
                .options(selectinload(Task.assignee))
            )
            t = q.scalar_one_or_none()

        if not t or not t.assignee or not t.assignee.tg_id:
            return False

        await bot.send_message(t.assignee.tg_id, text, reply_markup=reply_markup)
        return True
    except Exception:
        return False


async def notify_user_tg(bot: Bot, tg_id: int, text: str, reply_markup=None) -> bool:
    """Уведомление по tg_id (для кейса: уведомить старого исполнителя при смене)."""
    try:
        await bot.send_message(tg_id, text, reply_markup=reply_markup)
        return True
    except Exception:
        return False
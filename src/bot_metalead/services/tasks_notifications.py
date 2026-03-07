from aiogram import Bot

from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.repositories.tasks_repo import get_task_with_creator
from src.bot_metalead.db.models import User


async def notify_task_creator_on_employee_comment(
    bot: Bot,
    task_id: int,
    author_user: User,
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

        author_name = (
            author_user.full_name
            or (f"@{author_user.username}" if author_user.username else str(author_user.tg_id))
        )

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
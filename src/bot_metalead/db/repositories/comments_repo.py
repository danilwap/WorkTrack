from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot_metalead.db.models import Task, TaskComment


async def add_comment_to_assignee_task(
    session: AsyncSession,
    task_id: int,
    assignee_id: int,
    author_id: int,
    text: str,
) -> bool:
    q = await session.execute(
        select(Task.id).where(
            Task.id == task_id,
            Task.assignee_id == assignee_id,
        )
    )
    exists_task = q.scalar_one_or_none()

    if not exists_task:
        return False

    session.add(
        TaskComment(
            task_id=task_id,
            author_id=author_id,
            text=text,
        )
    )
    await session.commit()
    return True

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.bot_metalead.db.models import Task, TaskStatus



#
async def get_task_with_creator(session, task_id: int) -> Task | None:
    q = await session.execute(
        select(Task)
        .where(Task.id == task_id)
        .options(selectinload(Task.creator))
    )
    return q.scalar_one_or_none()


ACTIVE_TASK_STATUSES = [
    TaskStatus.new,
    TaskStatus.in_progress,
    TaskStatus.on_review,
]


async def get_active_tasks_by_assignee(
    session: AsyncSession,
    assignee_id: int,
    limit: int = 50,
) -> list[Task]:
    q = await session.execute(
        select(Task)
        .where(
            Task.assignee_id == assignee_id,
            Task.status.in_(ACTIVE_TASK_STATUSES),
        )
        .options(selectinload(Task.assignee))
        .order_by(Task.created_at.desc())
        .limit(limit)
    )
    return q.scalars().all()
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.bot_metalead.db.repositories.users_repo import ensure_user, get_user_by_id
from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.models import Task, TaskStatus, TaskComment, User, UserRole, TaskPriority

ACTIVE_TASK_STATUSES = [
    TaskStatus.new,
    TaskStatus.in_progress,
    TaskStatus.on_review,
    TaskStatus.rejected,
]

CLOSED_TASK_STATUSES = (
    TaskStatus.done,
    TaskStatus.cancelled,
    TaskStatus.rejected,
)

DONE_ALLOWED_STATUSES = [TaskStatus.new, TaskStatus.in_progress]
#
async def get_task_with_creator(session, task_id: int) -> Task | None:
    q = await session.execute(
        select(Task)
        .where(Task.id == task_id)
        .options(selectinload(Task.creator))
    )
    return q.scalar_one_or_none()


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



async def get_active_task_for_assignee_with_details(
    session: AsyncSession,
    task_id: int,
    assignee_id: int,
) -> Task | None:
    q = await session.execute(
        select(Task)
        .options(
            selectinload(Task.creator),
            selectinload(Task.comments).selectinload(TaskComment.author),
        )
        .where(
            Task.id == task_id,
            Task.assignee_id == assignee_id,
            Task.status.in_(ACTIVE_TASK_STATUSES),
        )
    )
    return q.scalar_one_or_none()


async def is_active_task_for_assignee(
    session: AsyncSession,
    task_id: int,
    assignee_id: int
) -> bool:
    q = await session.execute(
        select(Task.id).where(
            Task.id == task_id,
            Task.assignee_id == assignee_id,
            Task.status.in_(ACTIVE_TASK_STATUSES),
        )
    )
    return q.scalar_one_or_none() is not None






async def get_task_for_done_by_assignee(
    session: AsyncSession,
    task_id: int,
    assignee_id: int,
) -> Task | None:
    q = await session.execute(
        select(Task).where(
            Task.id == task_id,
            Task.assignee_id == assignee_id,
            Task.status.in_(DONE_ALLOWED_STATUSES),
        )
    )
    return q.scalar_one_or_none()


async def get_employees(session: AsyncSession) -> list[User]:
    q = await session.execute(
        select(User)
        .where(User.role == UserRole.employee.value)
        .order_by(User.full_name.asc().nulls_last())
    )
    return q.scalars().all()


async def load_task(task_id: int):
    async with session_scope() as session:
        q = await session.execute(
            select(Task)
            .where(Task.id == task_id)
            .options(
                selectinload(Task.assignee),
                selectinload(Task.creator),
                selectinload(Task.comments).selectinload(TaskComment.author)
            )
        )
        return q.scalar_one_or_none()


async def fetch_task_comments(task_id: int, page: int, per_page: int = 5):
    """
    page=0 показывает самые новые.
    """
    async with session_scope() as session:
        total_q = await session.execute(
            select(func.count(TaskComment.id)).where(TaskComment.task_id == task_id)
        )
        total = int(total_q.scalar() or 0)
        total_pages = max(1, math.ceil(total / per_page)) if total else 1
        page = max(0, min(page, total_pages - 1))

        offset = page * per_page

        q = await session.execute(
            select(TaskComment)
            .where(TaskComment.task_id == task_id)
            .options(selectinload(TaskComment.author))
            .order_by(TaskComment.created_at.desc())
            .offset(offset)
            .limit(per_page)
        )
        items = q.scalars().all()

    return total, total_pages, page, items


@dataclass
class CreatedTaskDTO:
    task_id: int
    title: str
    description: Optional[str]
    deadline_at: Optional[datetime]
    priority: str
    assignee_tg_id: int


async def create_task_record(
    session: AsyncSession,
    manager_tg_user,
    assignee_id: int,
    data: dict,
) -> CreatedTaskDTO | None:
    manager = await ensure_user(session, manager_tg_user)

    assignee = await get_user_by_id(session, assignee_id)
    if not assignee:
        return None

    task = Task(
        title=data["title"],
        description=data.get("description"),
        creator_id=manager.id,
        assignee_id=assignee_id,
        priority=TaskPriority(data["priority"]),
        deadline_at=data.get("deadline_at"),
        status=TaskStatus.new,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    return CreatedTaskDTO(
        task_id=task.id,
        title=task.title,
        description=task.description,
        deadline_at=task.deadline_at,
        priority=task.priority,
        assignee_tg_id=assignee.tg_id,
    )


async def get_overdue_tasks(
    session: AsyncSession,
    now_utc: datetime,
    limit: int = 50,
) -> list[Task]:
    q = await session.execute(
        select(Task)
        .where(
            and_(
                Task.deadline_at.is_not(None),
                Task.deadline_at < now_utc,
                Task.status.not_in([TaskStatus.done, TaskStatus.cancelled]),
            )
        )
        .options(selectinload(Task.assignee))
        .order_by(Task.deadline_at.asc())
        .limit(limit)
    )
    return list(q.scalars().all())


async def get_tasks_for_manager_filter(
    session: AsyncSession,
    flt: str,
    now_utc: datetime,
    limit: int = 50,
) -> list[Task]:
    stmt = (
        select(Task)
        .options(selectinload(Task.assignee))
        .order_by(Task.created_at.desc())
    )

    if flt == "active":
        stmt = stmt.where(
            Task.status.in_([
                TaskStatus.new,
                TaskStatus.in_progress,
                TaskStatus.on_review,
            ])
        )
    elif flt == "overdue":
        stmt = stmt.where(
            and_(
                Task.deadline_at.is_not(None),
                Task.deadline_at < now_utc,
                Task.status.not_in([
                    TaskStatus.done,
                    TaskStatus.cancelled,
                    TaskStatus.rejected,
                ]),
            )
        )
    elif flt == "all":
        pass
    else:
        return []

    q = await session.execute(stmt.limit(limit))
    return list(q.scalars().all())

async def get_tasks_by_ids(
    session: AsyncSession,
    ids: list[int],
) -> list[Task]:
    if not ids:
        return []

    q = await session.execute(
        select(Task)
        .where(Task.id.in_(ids))
        .order_by(Task.created_at.desc())
    )
    return list(q.scalars().all())


async def update_task_priority(
    session: AsyncSession,
    task_id: int,
    priority: TaskPriority,
) -> bool:
    q = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = q.scalar_one_or_none()
    if not task:
        return False

    task.priority = priority
    await session.commit()
    return True


async def get_editable_task(
    session: AsyncSession,
    task_id: int,
) -> Task | None:
    q = await session.execute(
        select(Task).where(
            Task.id == task_id,
            Task.status.not_in(CLOSED_TASK_STATUSES),
        )
    )
    return q.scalar_one_or_none()


async def get_task_by_id(
    session: AsyncSession,
    task_id: int,
) -> Task | None:
    q = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    return q.scalar_one_or_none()


def is_task_closed(task: Task) -> bool:
    return task.status in CLOSED_TASK_STATUSES


async def update_task_deadline(
    session: AsyncSession,
    task_id: int,
    deadline_at: datetime | None,
) -> Task | None:
    """
    Обновляет дедлайн задачи.

    Возвращает:
    - Task если дедлайн обновлён
    - None если задача не найдена или закрыта
    """

    q = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = q.scalar_one_or_none()

    if not task:
        return None

    if is_task_closed(task):
        return None

    if task.deadline_at == deadline_at:
        return task

    task.deadline_at = deadline_at
    await session.commit()

    return task

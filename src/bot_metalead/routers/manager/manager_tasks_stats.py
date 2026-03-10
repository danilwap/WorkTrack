from __future__ import annotations

from datetime import datetime, timedelta, UTC

from typing import Optional

from aiogram import Bot
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext

from sqlalchemy import and_, select, func
from sqlalchemy.orm import selectinload

from src.bot_metalead.filters.is_manager import IsManager
from src.bot_metalead.services.tasks_notifications import notify_assignee, notify_user_tg
from src.bot_metalead.db.repositories.tasks_repo import get_employees, load_task, fetch_task_comments
from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.repositories.users_repo import ensure_user, is_manager
from src.bot_metalead.utils.manager_tasks import render_tasks_table, _short, _fmt_dt
from src.bot_metalead.utils.wizard_logic import wizard_add_extra, wizard_show_from_message, wizard_show_from_callback, \
    wizard_clear
from src.bot_metalead.db.models import (
    UserRole,
    Task, TaskStatus, TaskPriority,
    TaskReminder, ReminderType,
    TaskApproval, ApprovalDecision, TaskComment, User
)
from src.bot_metalead.keyboards.all_keyboards import kb_back_to_menu
from sqlalchemy.orm import aliased
from src.bot_metalead.utils.text import clamp, split_for_tg, fmt_task
from src.bot_metalead.states.manager_tasks import ManagerTasks

from src.bot_metalead.keyboards.manager_tasks import (
    kb_tasks_filters,
    kb_priority_pick,
    kb_task_open_manager,
    kb_task_card,
    kb_remind_when,
    kb_edit_fields,
    kb_yes_no,
    kb_task_comments,
    kb_comment_full, kb_tasks_pick, kb_employees_pick
)

from src.bot_metalead.keyboards.user_tasks import kb_task_open_user

router = Router()



@router.callback_query(F.data == "mgr:tasks:stats", IsManager())
async def cb_manager_tasks_stats(call: CallbackQuery):
    async with session_scope() as session:
        now = datetime.now(UTC)

        q = await session.execute(
            select(Task.status, func.count(Task.id))
            .where(Task.status.in_([
                TaskStatus.new,
                TaskStatus.in_progress,
                TaskStatus.on_review
            ]))
            .group_by(Task.status)
        )
        grouped = {status: count for status, count in q.all()}

        new_count = grouped.get(TaskStatus.new, 0)
        cancel_count = grouped.get(TaskStatus.cancelled, 0)
        in_progress_count = grouped.get(TaskStatus.in_progress, 0)
        on_review_count = grouped.get(TaskStatus.on_review, 0)
        active_total = new_count + in_progress_count + on_review_count

        q = await session.execute(
            select(func.count(Task.id))
            .where(
                Task.status.in_([
                    TaskStatus.new,
                    TaskStatus.in_progress,
                    TaskStatus.on_review
                ]),
                Task.deadline_at.is_not(None),
                Task.deadline_at < now
            )
        )
        overdue_count = q.scalar() or 0

        q = await session.execute(
            select(func.count(Task.id))
            .where(
                Task.status.in_([
                    TaskStatus.new,
                    TaskStatus.in_progress,
                    TaskStatus.on_review
                ]),
                Task.assignee_id.is_(None)
            )
        )
        unassigned_count = q.scalar() or 0

        q = await session.execute(
            select(func.count(Task.id))
            .where(Task.status == TaskStatus.done)
        )
        done_count = q.scalar() or 0

        Assignee = aliased(User)

        q = await session.execute(
            select(
                Task.title,
                Task.deadline_at,
                Assignee.full_name,
                Assignee.username
            )
            .select_from(Task)
            .join(Assignee, Assignee.id == Task.assignee_id, isouter=True)
            .where(
                Task.status.in_([
                    TaskStatus.new,
                    TaskStatus.in_progress,
                    TaskStatus.on_review
                ])
            )
            .order_by(
                Task.deadline_at.is_(None),
                Task.deadline_at.asc(),
                Task.created_at.desc()
            )
        )
        items = q.all()

    text = (
        "📊 Статистика по задачам\n\n"
        f"Всего активных: {active_total}\n"
        f"• New: {new_count}\n"
        f"• Отменённые: {cancel_count}\n"
        f"• Просрочено: {overdue_count}\n"
        f"• Без исполнителя: {unassigned_count}\n\n"
        f"Завершённых: {done_count}"
    )

    if call.message:
        rows: list[tuple[str, str, str]] = []

        for title, deadline_at, full_name, username in items:
            assignee = full_name or (f"@{username}" if username else "—")
            rows.append((
                _short(assignee, 18),
                _short(title, 36),
                _fmt_dt(deadline_at),
            ))

        images = render_tasks_table(
            rows=rows,
            title="Активные задачи",
            rows_per_image=20
        )

        # Удаляем старое сообщение с кнопкой, чтобы вместо него отправить фото с caption
        try:
            await call.message.delete()
        except Exception:
            pass

        for i, bio in enumerate(images, start=1):
            photo = BufferedInputFile(
                bio.getvalue(),
                filename=f"tasks_{i}.png"
            )

            if i == 1:
                await call.message.answer_photo(
                    photo=photo,
                    caption=text,
                    reply_markup=kb_back_to_menu()
                )
            else:
                await call.message.answer_photo(photo=photo)

    await call.answer()

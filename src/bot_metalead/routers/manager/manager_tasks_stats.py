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
from src.bot_metalead.db.repositories.tasks_repo import get_employees, load_task, fetch_task_comments, get_tasks_stats, \
    get_tasks_for_export
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
    kb_comment_full, kb_tasks_pick, kb_employees_pick, kb_export_period_pick, kb_tasks_stats_actions
)

from src.bot_metalead.keyboards.user_tasks import kb_task_open_user
from src.bot_metalead.utils.excel_tasks_export import build_tasks_export_excel

router = Router()



@router.callback_query(F.data == "mgr:tasks:stats", IsManager())
async def cb_manager_tasks_stats(call: CallbackQuery):
    async with session_scope() as session:
        stats = await get_tasks_stats(session=session)

    counts = stats["counts"]
    items = stats["items"]

    text = (
        "📊 Статистика по задачам\n\n"
        f"Всего активных: {counts['active_total']}\n"
        f"• 🆕 Новая: {counts['new']}\n"
        f"• 🔧 В работе: {counts['in_progress']}\n"
        f"• ❌ Отклоненных, ожидают исправления: {counts['rejected']}\n"
        f"• 👀 На проверке: {counts['on_review']}\n"
        f"• ⏰ Просроченных: {counts['overdue']}\n"
        f"• ✅ Завершённых: {counts['done']}\n"
        f"• 🚫 Отменённых: {counts['cancelled']}"
    )

    if not call.message:
        await call.answer("Не удалось открыть статистику.", show_alert=True)
        return

    if not items:
        try:
            await call.message.delete()
        except Exception:
            pass

        await call.message.answer(
            text + "\n\nАктивных задач для отображения нет.",
            reply_markup=kb_tasks_stats_actions(),
        )
        await call.answer()
        return

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
        rows_per_image=20,
    )

    if not images:
        try:
            await call.message.delete()
        except Exception:
            pass

        await call.message.answer(
            text + "\n\nНе удалось сформировать таблицу задач.",
            reply_markup=kb_tasks_stats_actions(),
        )
        await call.answer()
        return

    try:
        await call.message.delete()
    except Exception:
        pass

    for i, bio in enumerate(images, start=1):
        photo = BufferedInputFile(
            bio.getvalue(),
            filename=f"tasks_{i}.png",
        )

        if i == 1:
            await call.message.answer_photo(
                photo=photo,
                caption=text,
                reply_markup=kb_tasks_stats_actions(),
            )
        else:
            await call.message.answer_photo(photo=photo)

    await call.answer()

@router.callback_query(F.data == "mgr:tasks:export", IsManager())
async def cb_tasks_export_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(ManagerTasks.export_stats_period)

    await wizard_show_from_callback(
        call,
        state,
        "📥 Выгрузка статистики\n\nВыбери период:",
        reply_markup=kb_export_period_pick(),
    )
    await call.answer()


@router.callback_query(
    ManagerTasks.export_stats_period,
    F.data.startswith("mgr:tasks:export_period:"),
    IsManager()
)
async def cb_tasks_export_period(call: CallbackQuery, state: FSMContext):
    if not call.message:
        await state.clear()
        await call.answer("Не удалось отправить файл.", show_alert=True)
        return

    period = call.data.split(":")[-1]
    now = datetime.now(UTC)

    if period == "week":
        date_from = now - timedelta(days=7)
        period_label = "неделю"
        filename_suffix = "week"
    elif period == "month":
        date_from = now - timedelta(days=30)
        period_label = "месяц"
        filename_suffix = "month"
    elif period == "quarter":
        date_from = now - timedelta(days=90)
        period_label = "квартал"
        filename_suffix = "quarter"
    else:
        await call.answer("Неизвестный период.", show_alert=True)
        return

    async with session_scope() as session:
        tasks = await get_tasks_for_export(
            session=session,
            date_from=date_from,
            date_to=now,
        )

    if not tasks:
        await state.clear()
        await call.message.answer(
            f"За {period_label} задач не найдено.",
            reply_markup=kb_back_to_menu(),
        )
        await call.answer()
        return

    excel_io = build_tasks_export_excel(tasks)

    file = BufferedInputFile(
        excel_io.getvalue(),
        filename=f"tasks_export_{filename_suffix}_{now.strftime('%Y%m%d_%H%M')}.xlsx",
    )

    await call.message.answer_document(
        document=file,
        caption=f"📥 Excel-выгрузка задач за {period_label}",
        reply_markup=kb_back_to_menu(),
    )

    await state.clear()
    await call.answer()

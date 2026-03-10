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



@router.callback_query(F.data.startswith("mtask:remind:"), IsManager())
async def cb_task_remind(call: CallbackQuery, state: FSMContext):
    task_id = int(call.data.split(":")[-1])
    await state.update_data(task_id=task_id)
    await state.set_state(ManagerTasks.remind_pick)

    await wizard_show_from_callback(
        call,
        state,
        "🔔 Когда напомнить?",
        reply_markup=kb_remind_when(task_id),
    )
    await call.answer()



@router.callback_query(ManagerTasks.remind_pick, F.data.startswith("mtask:remwhen:"))
async def cb_task_remind_when(call: CallbackQuery, state: FSMContext, bot: Bot):
    parts = call.data.split(":")
    task_id = int(parts[2])
    key = parts[3]

    if key == "in_hours":
        await state.set_state(ManagerTasks.remind_in_hours)
        await wizard_show_from_callback(call, state, "Введи N (через сколько часов напомнить), например: 3",
                                        reply_markup=kb_back_to_menu())
        await call.answer()
        return

    if key == "custom":
        await state.set_state(ManagerTasks.remind_custom_dt)
        await wizard_show_from_callback(call, state,
                                        "Введи дату/время в формате YYYY-MM-DD HH:MM (например 2026-03-10 18:30)",
                                        reply_markup=kb_back_to_menu())
        await call.answer()
        return

    now = datetime.utcnow()
    if key == "today_18":
        remind_at = now.replace(hour=18, minute=0, second=0, microsecond=0)
        if remind_at < now:
            remind_at = remind_at + timedelta(days=1)
    elif key == "tomorrow_10":
        remind_at = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    else:
        await call.answer("Неизвестный вариант", show_alert=True)
        return

    async with session_scope() as session:
        t = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not t:
            await call.answer("Задача не найдена", show_alert=True)
            return

        session.add(TaskReminder(task_id=task_id, remind_at=remind_at, type=ReminderType.manual))
        await session.commit()

    await notify_assignee(
        bot,
        task_id,
        f"🔔 Менеджер поставил напоминание по задаче #{task_id} на {remind_at.strftime('%d.%m %H:%M')}",
        reply_markup=kb_task_open_user(task_id),
    )

    await state.set_state(ManagerTasks.menu)

    await wizard_show_from_callback(
        call,
        state,
        f"⏰ Напоминание создано на {remind_at.strftime('%Y-%m-%d %H:%M')}",
        reply_markup=kb_task_open_manager(task_id),
    )
    await wizard_clear(state)
    await call.answer()


@router.message(ManagerTasks.remind_in_hours)
async def msg_task_remind_in_hours(message: Message, state: FSMContext, bot: Bot):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        return await message.answer("Введи число часов (например 3).")

    hours = int(raw)
    if hours <= 0 or hours > 240:
        return await message.answer("Число часов должно быть от 1 до 240.")

    task_id = (await state.get_data()).get("task_id")
    remind_at = datetime.utcnow() + timedelta(hours=hours)

    async with session_scope() as session:
        t = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not t:
            await state.set_state(ManagerTasks.menu)
            return await message.answer("Задача не найдена.")
        session.add(TaskReminder(task_id=task_id, remind_at=remind_at, type=ReminderType.manual))
        await session.commit()

    await notify_assignee(
        bot,
        task_id,
        f"🔔 Менеджер поставил напоминание по задаче #{task_id} на {remind_at.strftime('%d.%m %H:%M')}",
        reply_markup=kb_task_open_user(task_id),
    )

    await state.set_state(ManagerTasks.menu)

    await wizard_show_from_message(
        message,
        state,
        f"⏰ Напоминание создано на {remind_at.strftime('%Y-%m-%d %H:%M')}",
        reply_markup=kb_task_open_manager(task_id),
        delete_previous=True,
    )
    await wizard_clear(state)


@router.message(ManagerTasks.remind_custom_dt)
async def msg_task_remind_custom(message: Message, state: FSMContext, bot: Bot):
    raw = (message.text or "").strip()
    try:
        remind_at = datetime.strptime(raw, "%Y-%m-%d %H:%M")
    except Exception:
        return await message.answer("Неверный формат. Нужно YYYY-MM-DD HH:MM (например 2026-03-10 18:30)")

    task_id = (await state.get_data()).get("task_id")

    async with session_scope() as session:
        t = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not t:
            await state.set_state(ManagerTasks.menu)
            return await message.answer("Задача не найдена.")
        session.add(TaskReminder(task_id=task_id, remind_at=remind_at, type=ReminderType.manual))
        await session.commit()

    await notify_assignee(
        bot,
        task_id,
        f"🔔 Менеджер поставил напоминание по задаче #{task_id} на {remind_at.strftime('%d.%m %H:%M')}",
        reply_markup=kb_task_open_user(task_id),
    )

    await state.set_state(ManagerTasks.menu)

    await wizard_show_from_message(
        message,
        state,
        f"⏰ Напоминание создано на {remind_at.strftime('%Y-%m-%d %H:%M')}",
        reply_markup=kb_task_open_manager(task_id),
        delete_previous=True,
    )
    await wizard_clear(state)
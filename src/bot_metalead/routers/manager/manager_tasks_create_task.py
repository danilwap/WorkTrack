from __future__ import annotations

from datetime import datetime

from aiogram import Bot
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext


from src.bot_metalead.services.tasks_notifications import notify_assignee
from src.bot_metalead.filters.is_manager import IsManager
from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.repositories.users_repo import get_employees
from src.bot_metalead.db.repositories.tasks_repo import create_task_record
from src.bot_metalead.utils.wizard_logic import wizard_show_from_message, wizard_show_from_callback

from src.bot_metalead.keyboards.all_keyboards import kb_back_to_menu
from src.bot_metalead.states.manager_tasks import ManagerTasks

from src.bot_metalead.keyboards.manager_tasks import (
    kb_priority_pick,
    kb_task_open_manager,
    kb_assignee_pick, kb_deadline_calendar, kb_deadline_hours, kb_deadline_minutes,
)

from src.bot_metalead.keyboards.user_tasks import kb_task_open_user
from src.bot_metalead.utils.helpers import now_msk, msk_to_utc, fmt_msk

router = Router()


async def show_task_create_start(
        event: Message | CallbackQuery,
        state: FSMContext,
):
    await state.set_state(ManagerTasks.new_title)

    if isinstance(event, Message):
        await wizard_show_from_message(
            event,
            state,
            "➕ Создание задачи\n\nВведи название задачи:",
            reply_markup=kb_back_to_menu(),
            delete_previous=True,
        )
    else:
        await wizard_show_from_callback(
            event,
            state,
            "➕ Создание задачи\n\nВведи название задачи:",
            reply_markup=kb_back_to_menu(),
        )
        await event.answer()


@router.message(Command("task_new"), IsManager())
async def cmd_task_new(message: Message, state: FSMContext):
    await show_task_create_start(message, state)


@router.callback_query(F.data == "mtasks:new", IsManager())
async def cb_mtasks_new(call: CallbackQuery, state: FSMContext):
    await show_task_create_start(call, state)


@router.message(ManagerTasks.new_title, IsManager())
async def msg_new_title(message: Message, state: FSMContext):
    if not message.text:
        return await message.answer(
            "Название нужно отправить текстом.",
            reply_markup=kb_back_to_menu()
        )
    title = (message.text or "").strip()
    if not title:
        return await message.answer(
            "Название не может быть пустым. Введи ещё раз.",
            reply_markup=kb_back_to_menu()
        )

    await state.update_data(title=title)
    await state.set_state(ManagerTasks.new_description)

    await wizard_show_from_message(
        message,
        state,
        "Ок. Теперь введи описание (можно коротко, можно '-'):",
        reply_markup=kb_back_to_menu(),
        delete_previous=True,
    )


@router.message(ManagerTasks.new_description, IsManager())
async def msg_new_description(message: Message, state: FSMContext):
    if not message.text:
        return await message.answer(
            "Описание нужно отправить текстом. Или отправь '-' без описания.",
            reply_markup=kb_back_to_menu()
        )
    desc = (message.text or "").strip()
    await state.update_data(description=None if desc == "-" else desc)

    now = now_msk().replace(tzinfo=None)
    await state.set_state(ManagerTasks.new_deadline)

    await wizard_show_from_message(
        message,
        state,
        "📅 Выбери дедлайн:",
        reply_markup=kb_deadline_calendar(year=now.year, month=now.month),
        delete_previous=True,
    )


@router.callback_query(ManagerTasks.new_deadline, F.data.startswith("mcal:open:"), IsManager())
async def cb_deadline_calendar_open(call: CallbackQuery, state: FSMContext):
    year, month = map(int, call.data.split(":")[2:])

    now = now_msk().replace(tzinfo=None)
    current_month_start = datetime(now.year, now.month, 1)
    requested_month_start = datetime(year, month, 1)

    if requested_month_start < current_month_start:
        await call.answer("Нельзя выбрать прошедший месяц", show_alert=True)
        return

    await wizard_show_from_callback(
        call,
        state,
        "📅 Выбери дедлайн:",
        reply_markup=kb_deadline_calendar(year=year, month=month),
    )
    await call.answer()


@router.callback_query(ManagerTasks.new_deadline, F.data == "mcal:none", IsManager())
async def cb_deadline_none(call: CallbackQuery, state: FSMContext):
    await state.update_data(deadline_at=None)
    await state.set_state(ManagerTasks.new_priority)

    await wizard_show_from_callback(
        call,
        state,
        "Выбери приоритет:",
        reply_markup=kb_priority_pick(),
    )
    await call.answer()


@router.callback_query(ManagerTasks.new_deadline, F.data.startswith("mcal:hour:"), IsManager())
async def cb_deadline_pick_hour(call: CallbackQuery, state: FSMContext):
    _, _, year, month, day, hour = call.data.split(":")
    year, month, day, hour = int(year), int(month), int(day), int(hour)

    await wizard_show_from_callback(
        call,
        state,
        f"🕒 Выбери минуты для {day:02d}.{month:02d}.{year} {hour:02d}:00:",
        reply_markup=kb_deadline_minutes(year, month, day, hour),
    )
    await call.answer()


@router.callback_query(ManagerTasks.new_deadline, F.data.startswith("mcal:day:"), IsManager())
async def cb_deadline_pick_day(call: CallbackQuery, state: FSMContext):
    _, _, year, month, day = call.data.split(":")
    year, month, day = int(year), int(month), int(day)

    # защита от выбора прошедшего дня руками
    picked_date = datetime(year, month, day).date()
    if picked_date < now_msk().date():
        await call.answer("Нельзя выбрать прошедшую дату", show_alert=True)
        return

    await wizard_show_from_callback(
        call,
        state,
        f"🕒 Выбери час для {day:02d}.{month:02d}.{year}:",
        reply_markup=kb_deadline_hours(year, month, day),
    )
    await call.answer()


@router.callback_query(ManagerTasks.new_deadline, F.data.startswith("mcal:minute:"), IsManager())
async def cb_deadline_pick_minute(call: CallbackQuery, state: FSMContext):
    _, _, year, month, day, hour, minute = call.data.split(":")
    year, month, day, hour, minute = map(int, [year, month, day, hour, minute])

    picked_local = datetime(year, month, day, hour, minute)

    if picked_local <= now_msk().replace(tzinfo=None):
        await call.answer("Нельзя выбрать время в прошлом", show_alert=True)
        return

    deadline = msk_to_utc(picked_local)

    await state.update_data(deadline_at=deadline)
    await state.set_state(ManagerTasks.new_priority)

    await wizard_show_from_callback(
        call,
        state,
        f"📅 Дедлайн выбран: {fmt_msk(deadline, '%Y-%m-%d %H:%M')}\n\nВыбери приоритет:",
        reply_markup=kb_priority_pick(),
    )
    await call.answer()


@router.callback_query(ManagerTasks.new_deadline, F.data == "mcal:ignore", IsManager())
async def cb_calendar_ignore(call: CallbackQuery):
    await call.answer()


@router.callback_query(ManagerTasks.new_priority, F.data.startswith("mtasks:prio:"), IsManager())
async def cb_new_priority(call: CallbackQuery, state: FSMContext):
    pr = call.data.split(":")[-1]
    await state.update_data(priority=pr)
    await state.set_state(ManagerTasks.new_assignee)

    async with session_scope() as session:
        employees = await get_employees(session)

    if not employees:
        await wizard_show_from_callback(
            call,
            state,
            "Нет сотрудников с ролью employee в БД. Сначала добавь сотрудников.",
            reply_markup=kb_back_to_menu(),
        )
        await call.answer()
        return

    await state.update_data(assignee_ids=[u.id for u in employees], assignee_page=0)

    await wizard_show_from_callback(
        call,
        state,
        "👤 Выбери исполнителя:",
        reply_markup=kb_assignee_pick(employees, page=0),
    )
    await call.answer()


@router.callback_query(ManagerTasks.new_assignee, F.data.startswith("mtasks:assigneepage:"), IsManager())
async def cb_assignee_page(call: CallbackQuery, state: FSMContext):
    page = int(call.data.split(":")[-1])

    async with session_scope() as session:
        employees = await get_employees(session)

    if not employees:
        await wizard_show_from_callback(call, state, "Список сотрудников пуст.", reply_markup=kb_back_to_menu())
        await call.answer()
        return

    await state.update_data(assignee_page=page, assignee_ids=[u.id for u in employees])

    try:
        await call.message.edit_reply_markup(reply_markup=kb_assignee_pick(employees, page=page))
    except Exception:
        await wizard_show_from_callback(
            call,
            state,
            "👤 Выбери исполнителя:",
            reply_markup=kb_assignee_pick(employees, page=page),
        )

    await call.answer()


@router.callback_query(ManagerTasks.new_assignee, F.data.startswith("mtasks:assignee:"), IsManager())
async def cb_assignee_pick(call: CallbackQuery, state: FSMContext, bot: Bot):
    assignee_id = int(call.data.split(":")[-1])

    data = await state.get_data()
    allowed = set(data.get("assignee_ids", []))

    if assignee_id not in allowed:
        await call.answer("Исполнитель не из списка. Открой создание заново.", show_alert=True)
        return

    async with session_scope() as session:
        task = await create_task_record(
            session=session,
            manager_tg_user=call.from_user,
            assignee_id=assignee_id,
            data=data,
        )

    if not task:
        await call.answer("Исполнитель не найден.", show_alert=True)
        return

    deadline = fmt_msk(task.deadline_at)

    text = (
        f"📌 Вам назначена новая задача\n\n"
        f"🧩 #{task.task_id}\n"
        f"Название: {task.title}\n"
        f"Дедлайн: {deadline}\n"
        f"Приоритет: {task.priority.label}"
    )

    if task.description:
        text += f"\n\nОписание:\n{task.description}"

    sent = await notify_assignee(
        bot,
        task.task_id,
        text,
        kb_task_open_user(task.task_id),
    )

    manager_text = f"✅ Задача создана: #{task.task_id}"
    if not sent:
        manager_text += (
            "\n\n⚠️ Не удалось отправить уведомление исполнителю "
            "(возможно он ещё не запускал бота или заблокировал его)."
        )

    await wizard_show_from_callback(
        call,
        state,
        manager_text,
        reply_markup=kb_task_open_manager(task.task_id),
    )
    await state.clear()
    await call.answer()
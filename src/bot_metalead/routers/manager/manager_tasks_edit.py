from __future__ import annotations

from datetime import datetime


from aiogram import Bot
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext


from src.bot_metalead.filters.is_manager import IsManager
from src.bot_metalead.services.tasks_notifications import notify_assignee, notify_user_tg
from src.bot_metalead.db.repositories.tasks_repo import get_employees, \
    update_task_priority, get_task_by_id, is_task_closed, update_task_deadline
from src.bot_metalead.db.session import session_scope
from src.bot_metalead.utils.wizard_logic import wizard_show_from_callback
from src.bot_metalead.db.models import TaskPriority
from src.bot_metalead.keyboards.all_keyboards import kb_back_to_menu, kb_main_menu
from src.bot_metalead.states.manager_tasks import ManagerTasks

from src.bot_metalead.keyboards.manager_tasks import (
    kb_priority_pick,
    kb_task_open_manager,
    kb_edit_fields,
    kb_assignee_pick, kb_deadline_calendar, kb_deadline_minutes,
    kb_deadline_hours
)

from src.bot_metalead.keyboards.user_tasks import kb_task_open_user
from src.bot_metalead.utils.helpers import now_msk, fmt_msk, msk_to_utc

router = Router()


@router.callback_query(F.data.startswith("mtask:edit:"), IsManager())
async def cb_task_edit(call: CallbackQuery, state: FSMContext):
    task_id = int(call.data.split(":")[-1])

    async with session_scope() as session:
        t = await get_task_by_id(session=session, task_id=task_id)

    if not t:
        await call.answer("Задача не найдена", show_alert=True)
        return

    if is_task_closed(t):
        await wizard_show_from_callback(
            call,
            state,
            "ℹ️ Задача закрыта — редактирование недоступно.",
            reply_markup=kb_back_to_menu(),
        )
        await call.answer()
        return

    await state.update_data(task_id=task_id)
    await state.set_state(ManagerTasks.edit_pick_field)

    await wizard_show_from_callback(
        call,
        state,
        "✏️ Что изменить?",
        reply_markup=kb_edit_fields(task_id),
    )
    await call.answer()


@router.callback_query(ManagerTasks.edit_pick_field, F.data.startswith("mtask:editfield:"), IsManager())
async def cb_task_edit_field(call: CallbackQuery, state: FSMContext):
    try:
        _, _, task_id_s, field = call.data.split(":")
        task_id = int(task_id_s)
    except (ValueError, IndexError):
        await call.answer("Некорректные данные кнопки.", show_alert=True)
        return

    await state.update_data(task_id=task_id)

    if field == "deadline":
        await state.set_state(ManagerTasks.edit_deadline)

        now = now_msk()
        await wizard_show_from_callback(
            call,
            state,
            "📅 Выбери новый дедлайн:",
            reply_markup=kb_deadline_calendar(
                year=now.year,
                month=now.month,
                prefix="meditcal",
            ),
        )
        await call.answer()
        return

    if field == "priority":
        await state.set_state(ManagerTasks.edit_priority)
        await wizard_show_from_callback(
            call,
            state,
            "⚡ Выбери приоритет:",
            reply_markup=kb_priority_pick(),
        )
        await call.answer()
        return

    if field == "assignee":
        await state.set_state(ManagerTasks.edit_assignee)

        async with session_scope() as session:
            employees = await get_employees(session)

        if not employees:
            await wizard_show_from_callback(
                call,
                state,
                "Нет сотрудников с ролью employee в БД.",
                reply_markup=kb_back_to_menu(),
            )
            await call.answer()
            return

        await state.update_data(
            assignee_ids=[u.id for u in employees],
            assignee_page=0,
        )

        await wizard_show_from_callback(
            call,
            state,
            "👤 Выбери нового исполнителя:",
            reply_markup=kb_assignee_pick(employees, page=0),
        )
        await call.answer()
        return

    await call.answer("Неизвестное поле", show_alert=True)



@router.callback_query(ManagerTasks.edit_priority, F.data.startswith("mtasks:prio:"), IsManager())
async def cb_task_edit_priority(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        pr = call.data.split(":")[-1]
        new_priority = TaskPriority(pr)
    except (ValueError, IndexError):
        await call.answer("Некорректный приоритет.", show_alert=True)
        return

    task_id = (await state.get_data()).get("task_id")
    if not task_id:
        await state.clear()
        await call.answer("Контекст задачи потерян. Открой задачу заново.", show_alert=True)
        return

    async with session_scope() as session:
        task = await get_task_by_id(session=session, task_id=task_id)
        if not task:
            await wizard_show_from_callback(
                call,
                state,
                "❌ Задача не найдена.",
                reply_markup=kb_back_to_menu(),
            )
            await state.clear()
            await call.answer()
            return

        if is_task_closed(task):
            await wizard_show_from_callback(
                call,
                state,
                "ℹ️ Задача уже закрыта. Изменение приоритета недоступно.",
                reply_markup=kb_back_to_menu(),
            )
            await state.clear()
            await call.answer()
            return

        updated = await update_task_priority(
            session=session,
            task_id=task_id,
            priority=new_priority,
        )

    if not updated:
        await call.answer("Не удалось обновить приоритет.", show_alert=True)
        return

    await notify_assignee(
        bot,
        task_id,
        f"⚡ Менеджер изменил приоритет задачи #{task_id}\nНовый приоритет: {new_priority.label}",
        reply_markup=kb_task_open_user(task_id),
    )

    await wizard_show_from_callback(
        call,
        state,
        "✅ Приоритет обновлён.",
        reply_markup=kb_task_open_manager(task_id),
    )
    await state.clear()
    await call.answer()


@router.callback_query(ManagerTasks.edit_deadline, F.data.startswith("meditcal:open:"), IsManager())
async def cb_edit_deadline_calendar_open(call: CallbackQuery, state: FSMContext):
    try:
        year, month = map(int, call.data.split(":")[2:])
    except (ValueError, IndexError):
        await call.answer("Некорректные данные кнопки.", show_alert=True)
        return

    now = now_msk().replace(tzinfo=None)
    current_month_start = datetime(now.year, now.month, 1)
    requested_month_start = datetime(year, month, 1)

    if requested_month_start < current_month_start:
        await call.answer("Нельзя выбрать прошедший месяц", show_alert=True)
        return

    await wizard_show_from_callback(
        call,
        state,
        "📅 Выбери новый дедлайн:",
        reply_markup=kb_deadline_calendar(
            year=year,
            month=month,
            prefix="meditcal",
        ),
    )
    await call.answer()


@router.callback_query(ManagerTasks.edit_deadline, F.data == "meditcal:none", IsManager())
async def cb_edit_deadline_none(call: CallbackQuery, state: FSMContext, bot: Bot):
    task_id = (await state.get_data()).get("task_id")
    if not task_id:
        await state.clear()
        await call.answer("Контекст задачи потерян.", show_alert=True)
        return

    async with session_scope() as session:
        t = await get_task_by_id(session=session, task_id=task_id)
        if not t:
            await wizard_show_from_callback(
                call,
                state,
                "❌ Задача не найдена.",
                reply_markup=kb_back_to_menu(),
            )
            await state.clear()
            await call.answer()
            return

        if is_task_closed(t):
            await wizard_show_from_callback(
                call,
                state,
                "ℹ️ Задача уже закрыта. Убрать дедлайн нельзя.",
                reply_markup=kb_back_to_menu(),
            )
            await state.clear()
            await call.answer()
            return

        t.deadline_at = None
        await session.commit()

    await notify_assignee(
        bot,
        task_id,
        f"📅 Менеджер убрал дедлайн у задачи #{task_id}.",
        reply_markup=kb_task_open_user(task_id),
    )

    await wizard_show_from_callback(
        call,
        state,
        "✅ Дедлайн убран.",
        reply_markup=kb_task_open_manager(task_id),
    )
    await state.clear()
    await call.answer()


@router.callback_query(ManagerTasks.edit_deadline, F.data.startswith("meditcal:day:"), IsManager())
async def cb_edit_deadline_pick_day(call: CallbackQuery, state: FSMContext):
    try:
        _, _, year, month, day = call.data.split(":")
        year, month, day = int(year), int(month), int(day)
    except (ValueError, IndexError):
        await call.answer("Некорректные данные кнопки.", show_alert=True)
        return

    picked_date = datetime(year, month, day).date()
    if picked_date < now_msk().date():
        await call.answer("Нельзя выбрать прошедшую дату", show_alert=True)
        return

    await wizard_show_from_callback(
        call,
        state,
        f"🕒 Выбери час для {day:02d}.{month:02d}.{year}:",
        reply_markup=kb_deadline_hours(
            year,
            month,
            day,
            prefix="meditcal",
        ),
    )
    await call.answer()


@router.callback_query(ManagerTasks.edit_deadline, F.data.startswith("meditcal:hour:"), IsManager())
async def cb_edit_deadline_pick_hour(call: CallbackQuery, state: FSMContext):
    try:
        _, _, year, month, day, hour = call.data.split(":")
        year, month, day, hour = int(year), int(month), int(day), int(hour)
    except (ValueError, IndexError):
        await call.answer("Некорректные данные кнопки.", show_alert=True)
        return

    await wizard_show_from_callback(
        call,
        state,
        f"🕒 Выбери минуты для {day:02d}.{month:02d}.{year} {hour:02d}:00:",
        reply_markup=kb_deadline_minutes(
            year,
            month,
            day,
            hour,
            prefix="meditcal",
        ),
    )
    await call.answer()


@router.callback_query(ManagerTasks.edit_deadline, F.data.startswith("meditcal:minute:"), IsManager())
async def cb_edit_deadline_pick_minute(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        _, _, year, month, day, hour, minute = call.data.split(":")
        year, month, day, hour, minute = map(int, [year, month, day, hour, minute])
        picked_local = datetime(year, month, day, hour, minute)
    except (ValueError, IndexError):
        await call.answer("Некорректные данные кнопки.", show_alert=True)
        return

    now_local = now_msk().replace(tzinfo=None)
    if picked_local <= now_local:
        await call.answer("Нельзя выбрать время в прошлом", show_alert=True)
        return

    deadline_utc = msk_to_utc(picked_local)

    task_id = (await state.get_data()).get("task_id")
    if not task_id:
        await state.clear()
        await call.answer("Контекст задачи потерян.", show_alert=True)
        return



    async with session_scope() as session:
        t = await get_task_by_id(session=session, task_id=task_id)
        if not t:
            await wizard_show_from_callback(
                call,
                state,
                "❌ Задача не найдена.",
                reply_markup=kb_back_to_menu(),
            )

            await state.clear()
            await call.answer()
            return

        if is_task_closed(t):
            await wizard_show_from_callback(
                call,
                state,
                "ℹ️ Задача уже закрыта. Изменение дедлайна недоступно.",
                reply_markup=kb_back_to_menu(),
            )

            await state.clear()
            await call.answer()
            return

        if t.deadline_at == deadline_utc:
            await call.answer("Этот дедлайн уже установлен.", show_alert=True)
            return

        await update_task_deadline(session=session, task_id=task_id, deadline_at=deadline_utc)



    await notify_assignee(
        bot,
        task_id,
        f"📅 Менеджер изменил дедлайн задачи #{task_id}\nНовый дедлайн: {fmt_msk(deadline_utc)}",
        reply_markup=kb_task_open_user(task_id),
    )

    await wizard_show_from_callback(
        call,
        state,
        f"✅ Дедлайн обновлён: {fmt_msk(deadline_utc)}",
        reply_markup=kb_task_open_manager(task_id),
    )

    await state.clear()
    await call.answer()


@router.callback_query(ManagerTasks.edit_deadline, F.data == "meditcal:ignore", IsManager())
async def cb_edit_deadline_ignore(call: CallbackQuery):
    await call.answer()



@router.callback_query(ManagerTasks.edit_assignee, F.data.startswith("mtasks:assignee:"), IsManager())
async def cb_task_edit_assignee(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        new_assignee_id = int(call.data.split(":")[-1])
    except (ValueError, IndexError):
        await call.answer("Некорректный исполнитель.", show_alert=True)
        return

    data = await state.get_data()
    task_id = data.get("task_id")
    allowed = set(data.get("assignee_ids", []))

    if not task_id:
        await state.clear()
        await call.answer("Контекст задачи потерян.", show_alert=True)
        return

    if new_assignee_id not in allowed:
        await call.answer("Этого исполнителя нет в списке.", show_alert=True)
        return

    async with session_scope() as session:
        t = await get_task_by_id(session=session, task_id=task_id)
        if not t:
            await wizard_show_from_callback(
                call,
                state,
                "❌ Задача не найдена.",
                reply_markup=kb_back_to_menu(),
            )
            await state.clear()
            await call.answer()
            return

        if is_task_closed(t):
            await wizard_show_from_callback(
                call,
                state,
                "ℹ️ Задача уже закрыта. Изменение исполнителя недоступно.",
                reply_markup=kb_back_to_menu(),
            )
            await state.clear()
            await call.answer()
            return

        if t.assignee_id == new_assignee_id:
            await call.answer("Этот сотрудник уже назначен исполнителем.", show_alert=True)
            return

        old_assignee_id = t.assignee_id
        t.assignee_id = new_assignee_id
        await session.commit()

    await notify_assignee(
        bot,
        task_id,
        f"👤 Менеджер назначил вас исполнителем задачи #{task_id}.",
        reply_markup=kb_task_open_user(task_id),
    )

    await notify_user_tg(
        bot,
        old_assignee_id,
        f"❗ Вы больше не исполнитель задачи #{task_id}"
    )

    await wizard_show_from_callback(
        call,
        state,
        "✅ Исполнитель обновлён.",
        reply_markup=kb_task_open_manager(task_id),
    )
    await state.clear()
    await call.answer()

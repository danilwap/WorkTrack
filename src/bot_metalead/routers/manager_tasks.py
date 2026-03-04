from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from sqlalchemy import and_, select, func
from sqlalchemy.orm import selectinload

from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.models import (
    UserRole,
    Task, TaskStatus, TaskPriority,
    TaskReminder, ReminderType,
    TaskApproval, ApprovalDecision, TaskComment, User
)
from src.bot_metalead.keyboards.all_keyboards import kb_back_to_menu
from sqlalchemy.orm import aliased
from src.bot_metalead.utils.text import clamp, split_for_tg
from src.bot_metalead.states.manager_tasks import ManagerTasks

from src.bot_metalead.keyboards.manager_tasks import (
    kb_tasks_filters,
    kb_priority_pick,
    kb_task_open,
    kb_task_card,
    kb_remind_when,
    kb_edit_fields,
    kb_yes_no,
    kb_assignee_pick,
    kb_task_comments,
    kb_comment_full, kb_tasks_pick,
)

from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup

router = Router()

WIZARD_KEY = "wizard_msg_id"
WIZARD_EXTRA_KEY = "wizard_extra_msg_ids"

TASKS_PICK_IDS = "tasks_pick_ids"
TASKS_PICK_PAGE = "tasks_pick_page"

EMP_PICK_IDS = "emp_pick_ids"
EMP_PICK_PAGE = "emp_pick_page"

# где-нибудь в роутере
@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()


@router.callback_query(F.data.startswith("mtasks:employeepage:"))
async def cb_employees_page(call: CallbackQuery, state: FSMContext):
    page = int(call.data.split(":")[-1])

    async with session_scope() as session:
        q = await session.execute(
            select(User)
            .where(User.role == UserRole.employee.value)
            .order_by(User.full_name.asc().nulls_last())
        )
        employees = q.scalars().all()

    if not employees:
        await wizard_show_from_callback(call, state, "Сотрудники (employee) не найдены.", reply_markup=kb_back_to_menu())
        await call.answer()
        return

    await state.update_data(**{EMP_PICK_IDS: [u.id for u in employees], EMP_PICK_PAGE: page})

    await wizard_show_from_callback(
        call,
        state,
        "👤 Выбери сотрудника:",
        reply_markup=kb_employees_pick(employees, page=page),
    )
    await call.answer()


@router.callback_query(F.data.startswith("mtasks:employee:"))
async def cb_pick_employee(call: CallbackQuery, state: FSMContext):
    uid = int(call.data.split(":")[-1])

    # грузим задачи сотрудника и показываем по кнопке
    async with session_scope() as session:
        q = await session.execute(
            select(Task)
            .where(Task.assignee_id == uid)
            .options(selectinload(Task.assignee))
            .order_by(Task.created_at.desc())
            .limit(50)
        )
        tasks = q.scalars().all()

        # можно ещё имя сотрудника подтянуть (не обязательно)
        q2 = await session.execute(select(User).where(User.id == uid))
        emp = q2.scalar_one_or_none()

    if not tasks:
        name = emp.full_name or (f"@{emp.username}" if emp and emp.username else "сотрудника")
        await wizard_show_from_callback(
            call,
            state,
            f"У {name} пока нет задач.",
            reply_markup=kb_back_to_menu(),  # меню есть
        )
        await call.answer()
        return

    await state.update_data(**{TASKS_PICK_IDS: [t.id for t in tasks], TASKS_PICK_PAGE: 0})

    await wizard_show_from_callback(
        call,
        state,
        "📋 Задачи сотрудника (выбери по кнопке):",
        reply_markup=kb_tasks_pick(tasks, page=0),
    )
    await call.answer()



def kb_employees_pick(employees, page: int = 0, per_page: int = 8) -> InlineKeyboardMarkup:
    """
    callback: mtasks:employee:<user_id>
    пагинация: mtasks:employeepage:<page>
    """
    kb = InlineKeyboardBuilder()

    total = len(employees)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))

    start = page * per_page
    end = start + per_page
    chunk = employees[start:end]

    for u in chunk:
        name = u.full_name or (f"@{u.username}" if u.username else str(u.tg_id))
        name = (name[:30] + "…") if len(name) > 31 else name
        kb.button(text=f"👤 {name}", callback_data=f"mtasks:employee:{u.id}")

    nav = InlineKeyboardBuilder()
    if page > 0:
        nav.button(text="⬅️", callback_data=f"mtasks:employeepage:{page-1}")
    nav.button(text=f"{page+1}/{pages}", callback_data="noop")
    if page < pages - 1:
        nav.button(text="➡️", callback_data=f"mtasks:employeepage:{page+1}")

    kb.adjust(1)
    kb.row(*nav.buttons)

    # кнопка меню
    kb.row(*InlineKeyboardBuilder().button(text="🏠 Меню", callback_data="menu").buttons)

    return kb.as_markup()

async def wizard_add_extra(state: FSMContext, msg_id: int) -> None:
    data = await state.get_data()
    arr = list(data.get(WIZARD_EXTRA_KEY) or [])
    arr.append(msg_id)
    await state.update_data(**{WIZARD_EXTRA_KEY: arr})

async def wizard_delete_extras(bot: Bot, chat_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    arr = list(data.get(WIZARD_EXTRA_KEY) or [])
    for mid in arr:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass
    await state.update_data(**{WIZARD_EXTRA_KEY: []})

async def wizard_drop_markup(bot: Bot, chat_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    mid = data.get(WIZARD_KEY)
    if not mid:
        return
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=mid, reply_markup=None)
    except Exception:
        pass

async def wizard_clear(message_or_call, state: FSMContext) -> None:
    try:
        bot = message_or_call.bot
        chat_id = message_or_call.message.chat.id if hasattr(message_or_call, "message") and message_or_call.message else message_or_call.chat.id
    except Exception:
        # если не смогли вытащить chat_id/bot — просто чистим ключ
        await state.update_data(**{WIZARD_KEY: None})
        return

    await wizard_drop_markup(bot, chat_id, state)
    await state.update_data(**{WIZARD_KEY: None})

async def wizard_show_from_callback(call: CallbackQuery, state: FSMContext, text: str, reply_markup=None) -> int:
    data = await state.get_data()
    old_id = data.get(WIZARD_KEY)

    # 1) пробуем редактировать текущий месседж (идеальный кейс)
    try:
        if call.message:
            msg = await call.message.edit_text(text, reply_markup=reply_markup)
            await state.update_data(**{WIZARD_KEY: msg.message_id})
            return msg.message_id
    except Exception:
        pass

    # 2) если редактировать нельзя — удаляем прошлый wizard-msg (если был)
    if old_id:
        try:
            await call.bot.delete_message(call.message.chat.id if call.message else call.from_user.id, old_id)
        except Exception:
            pass

    # 3) и отправляем новый
    msg = await call.bot.send_message(call.from_user.id, text, reply_markup=reply_markup)
    await state.update_data(**{WIZARD_KEY: msg.message_id})
    return msg.message_id


async def wizard_show_from_message(
    message: Message,
    state: FSMContext,
    text: str,
    reply_markup=None,
    delete_previous: bool = True,
) -> int:
    """
    Показ шага из message-хендлера:
    - по умолчанию удаляем предыдущий wizard-месседж (чтобы нельзя было нажать старые кнопки)
    - отправляем новый шаг
    - сохраняем его message_id
    """
    data = await state.get_data()
    old_id = data.get(WIZARD_KEY)
    if delete_previous:
        await wizard_delete_extras(message.bot, message.chat.id, state)

    if delete_previous and old_id:
        try:
            await message.bot.delete_message(message.chat.id, old_id)
        except Exception:
            pass

    msg = await message.answer(text, reply_markup=reply_markup)
    await state.update_data(**{WIZARD_KEY: msg.message_id})
    return msg.message_id



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


CLOSE_PREFIX = "Закрыто администратором бота"


# ============================================================
# helpers (formatting / misc)
# ============================================================

def enum_value(x):
    return x.value if hasattr(x, "value") else str(x)


def fmt_task(task: Task) -> str:
    dl = task.deadline_at.strftime("%Y-%m-%d %H:%M") if task.deadline_at else "—"

    priority = enum_value(task.priority)  # low / medium / high / urgent
    status = enum_value(task.status)  # new / in_progress / ...

    assignee = task.assignee

    name_assignee = (
        f"@{assignee.username}"
        if assignee and assignee.username
        else assignee.full_name
        if assignee and assignee.full_name
        else str(assignee.tg_id)
        if assignee
        else "—"
    )

    text = (
        f"🧩 Задача #{task.id}\n"
        f"Название: {task.title}\n"
        f"Дедлайн: {dl}\n"
        f"Приоритет: {priority}\n"
        f"Статус: {status}\n\n"
        f"Ответственный: {name_assignee}\n\n"
        f"{task.description or ''}"
    ).strip()

    if task.comments:
        text += "\n\n💬 Комментарии:\n"
        for c in task.comments[-5:]:
            author = (c.author.full_name or c.author.username) if c.author else "—"
            created = c.created_at.strftime("%d.%m %H:%M")
            text += f"\n• {author} ({created})\n{c.text}"
    return text


# ============================================================
# db helpers
# ============================================================

async def get_or_create_user(tg_id: int, username: str | None, full_name: str | None) -> User:
    async with session_scope() as session:
        q = await session.execute(select(User).where(User.tg_id == tg_id))
        u = q.scalar_one_or_none()
        if not u:
            u = User(tg_id=tg_id, username=username, full_name=full_name, role=UserRole.employee.value)
            session.add(u)
            await session.commit()
            await session.refresh(u)
        else:
            u.username = username
            u.full_name = full_name
            await session.commit()
        return u


async def is_manager(tg_id: int) -> bool:
    async with session_scope() as session:
        q = await session.execute(select(User.role).where(User.tg_id == tg_id))
        role = q.scalar_one_or_none()
        return role in (UserRole.manager, UserRole.admin, UserRole.manager.value, UserRole.admin.value)


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


# ============================================================
# entrypoints (commands)
# ============================================================

@router.message(Command("task_new"))
async def cmd_task_new(message: Message, state: FSMContext):
    if not await is_manager(message.from_user.id):
        return await message.answer("⛔️ Доступ только для руководителя.")

    await state.set_state(ManagerTasks.new_title)

    await wizard_show_from_message(
        message,
        state,
        "➕ Создание задачи\n\nВведи название задачи:",
        reply_markup=kb_back_to_menu(),
        delete_previous=True,
    )


@router.message(Command("tasks"))
async def cmd_tasks(message: Message, state: FSMContext):
    if not await is_manager(message.from_user.id):
        return await message.answer("⛔️ Доступ только для руководителя.")
    await state.set_state(ManagerTasks.list_pick_filter)

    await wizard_show_from_message(
        message,
        state,
        "📋 Список задач — выбери фильтр:",
        reply_markup=kb_tasks_filters(),
        delete_previous=True,
    )


# ============================================================
# menu callbacks
# ============================================================

@router.callback_query(F.data == "mtasks:new")
async def cb_mtasks_new(call: CallbackQuery, state: FSMContext):
    if not await is_manager(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(ManagerTasks.new_title)

    await wizard_show_from_callback(
        call,
        state,
        "➕ Создание задачи\n\nВведи название задачи:",
        reply_markup=kb_back_to_menu(),
    )
    await call.answer()


@router.callback_query(F.data == "mtasks:list")
async def cb_mtasks_list(call: CallbackQuery, state: FSMContext):
    if not await is_manager(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(ManagerTasks.list_pick_filter)

    await wizard_show_from_callback(
        call,
        state,
        "📋 Список задач — выбери фильтр:",
        reply_markup=kb_tasks_filters(),
    )
    await call.answer()


# ============================================================
# create task FSM (/task_new)
# ============================================================

@router.message(ManagerTasks.new_title)
async def msg_new_title(message: Message, state: FSMContext):
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


@router.message(ManagerTasks.new_description)
async def msg_new_description(message: Message, state: FSMContext):
    desc = (message.text or "").strip()
    await state.update_data(description=None if desc == "-" else desc)

    await state.set_state(ManagerTasks.new_deadline)

    await wizard_show_from_message(
        message,
        state,
        "Дедлайн:\n"
        "• отправь '-' если без дедлайна\n"
        "• или дату/время в формате YYYY-MM-DD HH:MM (например 2026-03-10 18:30)",
        reply_markup=kb_back_to_menu(),
        delete_previous=True,
    )



@router.message(ManagerTasks.new_deadline)
async def msg_new_deadline(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    deadline: Optional[datetime] = None

    if raw != "-":
        try:
            deadline = datetime.strptime(raw, "%Y-%m-%d %H:%M")
        except Exception:
            return await message.answer(
                "Неверный формат. Нужно YYYY-MM-DD HH:MM (например 2026-03-10 18:30) или '-'.",
                reply_markup=kb_back_to_menu()
            )

    await state.update_data(deadline_at=deadline)
    await state.set_state(ManagerTasks.new_priority)

    await wizard_show_from_message(
        message,
        state,
        "Выбери приоритет:",
        reply_markup=kb_priority_pick(),
        delete_previous=True,
    )


@router.callback_query(ManagerTasks.new_priority, F.data.startswith("mtasks:prio:"))
async def cb_new_priority(call: CallbackQuery, state: FSMContext):
    pr = call.data.split(":")[-1]
    await state.update_data(priority=pr)
    await state.set_state(ManagerTasks.new_assignee)

    async with session_scope() as session:
        q = await session.execute(
            select(User)
            .where(User.role == UserRole.employee.value)
            .order_by(User.full_name.asc().nulls_last())
        )
        employees = q.scalars().all()

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


@router.message(ManagerTasks.new_assignee)
async def msg_new_assignee(message: Message, state: FSMContext, bot: Bot):
    if not (message.text or "").strip().isdigit():
        return await message.answer("Введи ID исполнителя цифрами (как в списке).")

    assignee_id = int(message.text.strip())
    data = await state.get_data()
    allowed = set(data.get("assignee_ids", []))
    if assignee_id not in allowed:
        return await message.answer("Этого исполнителя нет в списке. "
                                    "Открой создание задачи заново или введи корректный ID.",
                                    reply_markup=kb_back_to_menu())

    manager = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)

    async with session_scope() as session:
        # 1) достаём выбранного исполнителя (из пользователей бота)
        q = await session.execute(select(User).where(User.id == assignee_id))
        assignee = q.scalar_one_or_none()
        if not assignee:
            return await message.answer("Исполнитель не найден в базе.")

        # 2) создаём задачу
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

        # 3) отвечаем менеджеру (как wizard-финал)
    await state.set_state(ManagerTasks.menu)

    await wizard_show_from_message(
        message,
        state,
        f"✅ Задача создана: #{task.id}",
        reply_markup=kb_task_open(task.id),
        delete_previous=True,
    )
    await wizard_clear(state)

    # 4) отправляем уведомление исполнителю
    deadline = task.deadline_at.strftime("%d.%m %H:%M") if task.deadline_at else "—"
    notify_text = (
        f"📌 Вам назначена новая задача\n\n"
        f"🧩 #{task.id}\n"
        f"Название: {task.title}\n"
        f"Дедлайн: {deadline}\n"
        f"Приоритет: {task.priority.value}\n"
    )

    try:
        await bot.send_message(assignee.tg_id, notify_text, reply_markup=kb_task_open(task.id))
    except Exception:
        await wizard_show_from_message(
            message,
            state,
            "⚠️ Не удалось отправить уведомление исполнителю. "
            "Скорее всего он ещё не нажимал /start у бота или заблокировал бота.",
            reply_markup=kb_task_open(task.id),
            delete_previous=False,  # важно: не удаляем финальный экран “Задача создана”
        )


# ---- assignee pagination & pick (for create flow) ----

@router.callback_query(ManagerTasks.new_assignee, F.data.startswith("mtasks:assigneepage:"))
async def cb_assignee_page(call: CallbackQuery, state: FSMContext):
    page = int(call.data.split(":")[-1])

    async with session_scope() as session:
        q = await session.execute(
            select(User)
            .where(User.role == UserRole.employee.value)
            .order_by(User.full_name.asc().nulls_last())
        )
        employees = q.scalars().all()

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


@router.callback_query(ManagerTasks.new_assignee, F.data.startswith("mtasks:assignee:"))
async def cb_assignee_pick(call: CallbackQuery, state: FSMContext, bot: Bot):
    assignee_id = int(call.data.split(":")[-1])

    data = await state.get_data()
    allowed = set(data.get("assignee_ids", []))

    if assignee_id not in allowed:
        await call.answer("Исполнитель не из списка. Открой создание заново.", show_alert=True)
        return

    manager = await get_or_create_user(
        call.from_user.id,
        call.from_user.username,
        call.from_user.full_name
    )

    async with session_scope() as session:

        # ✅ получаем исполнителя
        q = await session.execute(select(User).where(User.id == assignee_id))
        assignee = q.scalar_one_or_none()

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

    await state.set_state(ManagerTasks.menu)

    await wizard_show_from_callback(
        call,
        state,
        f"✅ Задача создана: #{task.id}",
        reply_markup=kb_task_open(task.id),
    )
    await wizard_clear(call, state)

    await call.answer()

    # =========================
    # 📩 Уведомление исполнителю
    # =========================
    if assignee:
        deadline = task.deadline_at.strftime("%d.%m %H:%M") if task.deadline_at else "—"

        text = (
            f"📌 Вам назначена новая задача\n\n"
            f"🧩 #{task.id}\n"
            f"Название: {task.title}\n"
            f"Дедлайн: {deadline}\n"
            f"Приоритет: {task.priority.value}"
        )

        if task.description:
            text += f"\n\nОписание:\n{task.description}"

        try:
            await bot.send_message(
                assignee.tg_id,
                text,
                reply_markup=kb_task_open(task.id)
            )
        except Exception:
            # если пользователь ещё не нажимал /start
            await call.message.answer(
                "⚠️ Не удалось отправить уведомление исполнителю "
                "(возможно он ещё не запускал бота)."
            )


# ============================================================
# tasks list
# ============================================================

@router.callback_query(ManagerTasks.list_pick_filter, F.data.startswith("mtasks:filter:"))
async def cb_tasks_pick_filter(call: CallbackQuery, state: FSMContext):
    flt = call.data.split(":")[-1]

    if flt == "by_employee":
        await state.set_state(ManagerTasks.list_pick_employee)

        async with session_scope() as session:
            q = await session.execute(
                select(User)
                .where(User.role == UserRole.employee.value)
                .order_by(User.full_name.asc().nulls_last())
            )
            employees = q.scalars().all()

        if not employees:
            await wizard_show_from_callback(
                call,
                state,
                "Сотрудники (employee) не найдены.",
                reply_markup=kb_back_to_menu(),
            )
            await call.answer()
            return

        await state.update_data(**{EMP_PICK_IDS: [u.id for u in employees], EMP_PICK_PAGE: 0})

        await wizard_show_from_callback(
            call,
            state,
            "👤 Выбери сотрудника:",
            reply_markup=kb_employees_pick(employees, page=0),
        )
        await call.answer()
        return

    await state.update_data(tasks_filter=flt)
    await state.set_state(ManagerTasks.list_pick_filter)  # остаёмся в фильтрах, но покажем список

    now = datetime.utcnow()
    async with session_scope() as session:
        stmt = select(Task).options(selectinload(Task.assignee)).order_by(Task.created_at.desc())

        if flt == "active":
            stmt = stmt.where(Task.status.in_([TaskStatus.new, TaskStatus.in_progress, TaskStatus.on_review]))
        elif flt == "overdue":
            stmt = stmt.where(
                and_(
                    Task.deadline_at.is_not(None),
                    Task.deadline_at < now,
                    Task.status.not_in([TaskStatus.done, TaskStatus.cancelled]),
                )
            )
        else:  # all
            pass

        q = await session.execute(stmt.limit(50))
        tasks = q.scalars().all()

    if not tasks:
        await call.message.edit_text("Нет задач по выбранному фильтру.", reply_markup=kb_tasks_filters())
        await call.answer()
        return

    text = "📋 Задачи:\n\n" + "\n".join([f"• #{t.id} — {t.title}" for t in tasks[:20]])
    text += "\n\nНажми «Открыть» под нужной задачей:"
    # сохраним ids (чтобы дальше доставать по ним, если надо)
    await state.update_data(**{TASKS_PICK_IDS: [t.id for t in tasks], TASKS_PICK_PAGE: 0})

    text = "📋 Задачи (выбери по кнопке):"
    await wizard_show_from_callback(
        call,
        state,
        text,
        reply_markup=kb_tasks_pick(tasks, page=0),
    )
    await call.answer()


@router.callback_query(F.data.startswith("mtasks:pickpage:"))
async def cb_tasks_pick_page(call: CallbackQuery, state: FSMContext):
    page = int(call.data.split(":")[-1])
    data = await state.get_data()
    ids = data.get(TASKS_PICK_IDS) or []
    if not ids:
        await call.answer("Список задач устарел. Открой /tasks заново.", show_alert=True)
        return

    async with session_scope() as session:
        q = await session.execute(
            select(Task).where(Task.id.in_(ids)).order_by(Task.created_at.desc())
        )
        tasks = q.scalars().all()

    await state.update_data(**{TASKS_PICK_PAGE: page})

    await wizard_show_from_callback(
        call,
        state,
        "📋 Задачи (выбери по кнопке):",
        reply_markup=kb_tasks_pick(tasks, page=page),
    )
    await call.answer()


@router.message(ManagerTasks.list_pick_employee)
async def msg_tasks_pick_employee(message: Message, state: FSMContext):
    data = await state.get_data()
    allowed = set(data.get("employee_ids", []))

    if not (message.text or "").strip().isdigit():
        return await message.answer("Введи ID сотрудника цифрами.")
    uid = int(message.text.strip())
    if uid not in allowed:
        return await message.answer("Такого сотрудника нет в списке. Открой /tasks заново.")

    async with session_scope() as session:
        q = await session.execute(
            select(Task)
            .where(Task.assignee_id == uid)
            .options(selectinload(Task.assignee))
            .order_by(Task.created_at.desc())
            .limit(50)
        )
        tasks = q.scalars().all()

    if not tasks:
        return await message.answer("У этого сотрудника пока нет задач.", reply_markup=kb_tasks_filters())

    await state.update_data(**{TASKS_PICK_IDS: [t.id for t in tasks], TASKS_PICK_PAGE: 0})

    await wizard_show_from_message(
        message,
        state,
        "📋 Задачи сотрудника (выбери по кнопке):",
        reply_markup=kb_tasks_pick(tasks, page=0),
        delete_previous=True,
    )


@router.callback_query(F.data == "mtasks:overdue")
async def cb_tasks_overdue(call: CallbackQuery, state: FSMContext):
    if not await is_manager(call.from_user.id):
        return await call.answer("⛔️ Нет доступа", show_alert=True)

    now = datetime.utcnow()

    async with session_scope() as session:
        q = await session.execute(
            select(Task)
            .where(
                and_(
                    Task.deadline_at.is_not(None),
                    Task.deadline_at < now,
                    Task.status.not_in([TaskStatus.done, TaskStatus.cancelled]),
                )
            )
            .options(selectinload(Task.assignee))
            .order_by(Task.deadline_at.asc())
            .limit(50)
        )

        tasks = q.scalars().all()

    if not tasks:
        await call.message.edit_text("✅ Просроченных задач нет.", reply_markup=kb_back_to_menu())
        return await call.answer()

    text = "⏰ Просроченные задачи:\n\n"

    for t in tasks[:20]:
        assignee = "—"
        if t.assignee:
            assignee = t.assignee.full_name or t.assignee.username or str(t.assignee.tg_id)

        deadline = t.deadline_at.strftime("%Y-%m-%d %H:%M") if t.deadline_at else "—"

        text += f"• #{t.id} — {t.title}\n"
        text += f"  👤 {assignee}\n"
        text += f"  📅 {deadline}\n\n"

    from src.bot_metalead.keyboards.manager_tasks import kb_tasks_pick

    await state.update_data(**{TASKS_PICK_IDS: [t.id for t in tasks], TASKS_PICK_PAGE: 0})

    await wizard_show_from_callback(
        call,
        state,
        "⏰ Просроченные задачи (выбери по кнопке):",
        reply_markup=kb_tasks_pick(tasks, page=0),
    )
    await call.answer()


# ============================================================
# task card
# ============================================================

@router.callback_query(F.data.startswith("mtask:open:"))
async def cb_task_open(call: CallbackQuery, state: FSMContext):
    task_id = int(call.data.split(":")[-1])
    t = await load_task(task_id)
    if not t:
        await call.answer("Задача не найдена", show_alert=True)
        return

    status = t.status.value if hasattr(t.status, "value") else str(t.status)
    await state.update_data(task_id=task_id)
    await call.message.edit_text(fmt_task(t), reply_markup=kb_task_card(task_id, status))
    await call.answer()


# ============================================================
# task actions: comments (add / list / full)
# ============================================================

@router.callback_query(F.data.startswith("mtask:comment:"))
async def cb_task_comment(call: CallbackQuery, state: FSMContext):
    task_id = int(call.data.split(":")[-1])
    await state.update_data(task_id=task_id)
    await state.set_state(ManagerTasks.comment_text)

    await wizard_show_from_callback(
        call,
        state,
        "➕ Введи комментарий к задаче:",
        reply_markup=kb_back_to_menu(),
    )
    await call.answer()


@router.message(ManagerTasks.comment_text)
async def msg_task_comment(message: Message, state: FSMContext, bot: Bot):
    text = (message.text or "").strip()
    if not text:
        return await message.answer("Комментарий не может быть пустым.")

    if not await is_manager(message.from_user.id):
        return await message.answer("⛔️ Доступ только для руководителя.")

    task_id = (await state.get_data()).get("task_id")
    if not task_id:
        await state.set_state(ManagerTasks.menu)
        return await message.answer("Контекст задачи потерян. Открой задачу заново.")

    manager = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)

    async with session_scope() as session:
        t = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not t:
            await state.set_state(ManagerTasks.menu)
            return await message.answer("Задача не найдена.")

        session.add(TaskComment(task_id=task_id, author_id=manager.id, text=text))
        await session.commit()

    manager_name = message.from_user.full_name or message.from_user.username or "Менеджер"
    notify_text = (
        f"💬 Новый комментарий от менеджера\n"
        f"Задача #{task_id}: {t.title}\n\n"
        f"{text}"
    )
    await notify_assignee(bot, task_id, notify_text, reply_markup=kb_task_open(task_id))

    await state.set_state(ManagerTasks.menu)

    await wizard_show_from_message(
        message,
        state,
        "✅ Комментарий добавлен.",
        reply_markup=kb_task_open(task_id),
        delete_previous=True,
    )
    await wizard_clear(state)


@router.callback_query(F.data.startswith("mtask:comments:"))
async def cb_task_comments(call: CallbackQuery, state: FSMContext):
    # формат: mtask:comments:<task_id>:<page>
    _, _, task_id_s, page_s = call.data.split(":")
    task_id = int(task_id_s)
    page = int(page_s)

    t = await load_task(task_id)  # можно облегчить load_task, но пусть пока так
    if not t:
        await call.answer("Задача не найдена", show_alert=True)
        return

    total, total_pages, page, comments = await fetch_task_comments(task_id, page, per_page=5)

    if total == 0:
        await call.message.edit_text(
            "💬 Комментариев пока нет.",
            reply_markup=kb_task_comments(task_id, 0, 1)
        )
        await call.answer()
        return

    header = f"💬 Комментарии к задаче #{task_id}\nСтраница {page + 1}/{total_pages} • Всего: {total}\n"

    lines = [header]
    for c in comments:
        author = (c.author.full_name or c.author.username) if c.author else "—"
        created = c.created_at.strftime("%d.%m %H:%M")
        # Превью коммента, чтобы не раздувать сообщение
        preview = clamp(c.text, 600)
        lines.append(f"\n• {author} ({created})\n{preview}")

        # если урезали — добавим подсказку, как открыть полностью
        if c.text and len(c.text) > 600:
            lines.append(f"\n   ↳ Открыть полностью: / (кнопкой ниже)")

    text = "\n".join(lines).strip()

    # защита от лимита: если вдруг всё равно раздули
    parts = split_for_tg(text)

    if len(parts) == 1:
        comment_ids = [c.id for c in comments]

        await call.message.edit_text(parts[0], reply_markup=kb_task_comments(task_id, page, total_pages, comment_ids))
    else:
        comment_ids = [c.id for c in comments]

        # 1-я часть редактируем, остальные докидываем сообщениями
        await call.message.edit_text(parts[0], reply_markup=kb_task_comments(task_id, page, total_pages, comment_ids))
        for p in parts[1:]:
            m = await call.message.answer(p)
            await wizard_add_extra(state, m.message_id)

    # Дополнительно: если есть урезанные — можно дать кнопки на “полный текст” по каждому,
    # но чтобы не спамить клавиатурой, сделаем отдельный хендлер ниже по нажатию на конкретный коммент.
    # Для этого нужно сделать кнопки "📄 Коммент #ID". Если хочешь — добавлю.

    await call.answer()


@router.callback_query(F.data.startswith("mtask:commentfull:"))
async def cb_task_comment_full(call: CallbackQuery, state: FSMContext):
    # формат: mtask:commentfull:<task_id>:<comment_id>:<back_page>
    _, _, task_id_s, comment_id_s, back_page_s = call.data.split(":")
    task_id = int(task_id_s)
    comment_id = int(comment_id_s)
    back_page = int(back_page_s)

    async with session_scope() as session:
        q = await session.execute(
            select(TaskComment)
            .where(TaskComment.id == comment_id, TaskComment.task_id == task_id)
            .options(selectinload(TaskComment.author))
        )
        c = q.scalar_one_or_none()

    if not c:
        await call.answer("Комментарий не найден", show_alert=True)
        return

    author = (c.author.full_name or c.author.username) if c.author else "—"
    created = c.created_at.strftime("%d.%m %H:%M")

    text = f"📄 Комментарий #{c.id} к задаче #{task_id}\n• {author} ({created})\n\n{c.text or ''}".strip()

    parts = split_for_tg(text)
    await call.message.edit_text(parts[0], reply_markup=kb_comment_full(task_id, comment_id, back_page))
    for p in parts[1:]:
        m = await call.message.answer(p)
        await wizard_add_extra(state, m.message_id)

    await call.answer()


# ============================================================
# task actions: reminders
# ============================================================

@router.callback_query(F.data.startswith("mtask:remind:"))
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

    manager_name = call.from_user.full_name or call.from_user.username or "Менеджер"
    await notify_assignee(
        bot,
        task_id,
        f"🔔 Менеджер поставил напоминание по задаче #{task_id} на {remind_at.strftime('%d.%m %H:%M')}",
        reply_markup=kb_task_open(task_id),
    )

    await state.set_state(ManagerTasks.menu)

    await wizard_show_from_callback(
        call,
        state,
        f"⏰ Напоминание создано на {remind_at.strftime('%Y-%m-%d %H:%M')}",
        reply_markup=kb_task_open(task_id),
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
        reply_markup=kb_task_open(task_id),
    )

    await state.set_state(ManagerTasks.menu)

    await wizard_show_from_message(
        message,
        state,
        f"⏰ Напоминание создано на {remind_at.strftime('%Y-%m-%d %H:%M')}",
        reply_markup=kb_task_open(task_id),
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
        reply_markup=kb_task_open(task_id),
    )

    await state.set_state(ManagerTasks.menu)

    await wizard_show_from_message(
        message,
        state,
        f"⏰ Напоминание создано на {remind_at.strftime('%Y-%m-%d %H:%M')}",
        reply_markup=kb_task_open(task_id),
        delete_previous=True,
    )
    await wizard_clear(state)


# ============================================================
# task actions: edit task
# ============================================================

@router.callback_query(F.data.startswith("mtask:edit:"))
async def cb_task_edit(call: CallbackQuery, state: FSMContext):
    task_id = int(call.data.split(":")[-1])

    async with session_scope() as session:
        t = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()

    if not t:
        await call.answer("Задача не найдена", show_alert=True)
        return

    closed_statuses = {TaskStatus.done, TaskStatus.cancelled, TaskStatus.rejected}
    if t.status in closed_statuses:
        await wizard_show_from_callback(
            call,
            state,
            "ℹ️ Задача закрыта — редактирование недоступно.",
            reply_markup=kb_back_to_menu(),
        )
        await wizard_clear(state)
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


@router.callback_query(ManagerTasks.edit_pick_field, F.data.startswith("mtask:editfield:"))
async def cb_task_edit_field(call: CallbackQuery, state: FSMContext):
    _, _, task_id_s, field = call.data.split(":")
    task_id = int(task_id_s)
    await state.update_data(task_id=task_id)

    if field == "deadline":
        await state.set_state(ManagerTasks.edit_deadline)
        await wizard_show_from_callback(
            call,
            state,
            "📅 Введи новый дедлайн YYYY-MM-DD HH:MM или '-' чтобы убрать:",
            reply_markup=kb_back_to_menu(),
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
            q = await session.execute(
                select(User)
                .where(User.role == UserRole.employee.value)
                .order_by(User.full_name.asc().nulls_last())
            )
            employees = q.scalars().all()

        if not employees:
            await wizard_show_from_callback(
                call,
                state,
                "Нет сотрудников с ролью employee в БД.",
                reply_markup=kb_back_to_menu(),
            )
            await call.answer()
            return

        await state.update_data(assignee_ids=[u.id for u in employees])

        txt = "👤 Введи ID нового исполнителя:\n\n" + "\n".join(
            [f"• {u.id} — {(u.full_name or u.username or str(u.tg_id))}" for u in employees[:30]]
        )

        await wizard_show_from_callback(
            call,
            state,
            txt,
            reply_markup=kb_back_to_menu(),
        )
        await call.answer()
        return

    await call.answer("Неизвестное поле", show_alert=True)


@router.message(ManagerTasks.edit_deadline)
async def msg_task_edit_deadline(message: Message, state: FSMContext, bot: Bot):
    raw = (message.text or "").strip()
    deadline: Optional[datetime] = None

    if raw != "-":
        try:
            deadline = datetime.strptime(raw, "%Y-%m-%d %H:%M")
        except Exception:
            return await message.answer("Неверный формат. Нужно YYYY-MM-DD HH:MM или '-'.")

    task_id = (await state.get_data()).get("task_id")
    async with session_scope() as session:
        t = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not t:
            await state.set_state(ManagerTasks.menu)
            return await message.answer("Задача не найдена.")
        t.deadline_at = deadline
        await session.commit()

    dl_txt = deadline.strftime("%d.%m %H:%M") if deadline else "—"
    await notify_assignee(
        bot,
        task_id,
        f"📅 Менеджер изменил дедлайн задачи #{task_id}\nНовый дедлайн: {dl_txt}",
        reply_markup=kb_task_open(task_id),
    )

    await state.set_state(ManagerTasks.menu)

    await wizard_show_from_message(
        message,
        state,
        "✅ Дедлайн обновлён.",
        reply_markup=kb_task_open(task_id),
        delete_previous=True,
    )
    await wizard_clear(state)


@router.callback_query(ManagerTasks.edit_priority, F.data.startswith("mtasks:prio:"))
async def cb_task_edit_priority(call: CallbackQuery, state: FSMContext, bot: Bot):
    pr = call.data.split(":")[-1]
    task_id = (await state.get_data()).get("task_id")

    async with session_scope() as session:
        t = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not t:
            await call.answer("Задача не найдена", show_alert=True)
            return
        t.priority = TaskPriority(pr)
        await session.commit()

    await notify_assignee(
        bot,
        task_id,
        f"⚡ Менеджер изменил приоритет задачи #{task_id}\nНовый приоритет: {pr}",
        reply_markup=kb_task_open(task_id),
    )

    await state.set_state(ManagerTasks.menu)

    await wizard_show_from_callback(
        call,
        state,
        "✅ Приоритет обновлён.",
        reply_markup=kb_task_open(task_id),
    )
    await wizard_clear(state)
    await call.answer()


@router.message(ManagerTasks.edit_assignee)
async def msg_task_edit_assignee(message: Message, state: FSMContext, bot: Bot):
    if not (message.text or "").strip().isdigit():
        return await message.answer("Введи ID исполнителя цифрами.")

    new_assignee_id = int(message.text.strip())
    data = await state.get_data()
    allowed = set(data.get("assignee_ids", []))
    if new_assignee_id not in allowed:
        return await message.answer("Этого исполнителя нет в списке.")

    task_id = data.get("task_id")

    async with session_scope() as session:
        t = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not t:
            await state.set_state(ManagerTasks.menu)
            return await message.answer("Задача не найдена.")
        old_assignee_tg = None
        if t.assignee_id:
            q_old = await session.execute(select(User.tg_id).where(User.id == t.assignee_id))
            old_assignee_tg = q_old.scalar_one_or_none()

        t.assignee_id = new_assignee_id
        await session.commit()

    # 🔔 уведомим старого исполнителя (если был)
    if old_assignee_tg:
        await notify_user_tg(
            bot,
            old_assignee_tg,
            f"👤 Менеджер снял вас с задачи #{task_id}.",
        )

    # 🔔 уведомим нового исполнителя
    await notify_assignee(
        bot,
        task_id,
        f"👤 Менеджер назначил вас исполнителем задачи #{task_id}.",
        reply_markup=kb_task_open(task_id),
    )

    await state.set_state(ManagerTasks.menu)

    await wizard_show_from_message(
        message,
        state,
        "✅ Исполнитель обновлён.",
        reply_markup=kb_task_open(task_id),
        delete_previous=True,
    )
    await wizard_clear(state)


# ============================================================
# task actions: approve / reject
# ============================================================

@router.callback_query(F.data.startswith("mtask:approve:"))
async def cb_task_approve(call: CallbackQuery, state: FSMContext, bot: Bot):
    task_id = int(call.data.split(":")[-1])
    manager = await get_or_create_user(call.from_user.id, call.from_user.username, call.from_user.full_name)

    async with session_scope() as session:
        t = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not t:
            await call.answer("Задача не найдена", show_alert=True)
            return
        if t.status != TaskStatus.on_review:
            await call.answer("Задача не на ревью", show_alert=True)
            return

        # фиксируем решение
        appr = TaskApproval(task_id=task_id, manager_id=manager.id, decision=ApprovalDecision.approved)
        session.add(appr)

        # меняем статус задачи
        t.status = TaskStatus.done
        t.finished_at = datetime.utcnow()
        await session.commit()
    await notify_assignee(
        bot,
        task_id,
        f"✅ Менеджер принял работу и завершил задачу #{task_id}.",
        reply_markup=kb_task_open(task_id),
    )

    await wizard_show_from_callback(
        call,
        state,
        "✅ Апрув: задача завершена.",
        reply_markup=kb_task_open(task_id),
    )
    await wizard_clear(call, state)


@router.callback_query(F.data.startswith("mtask:reject:"))
async def cb_task_reject(call: CallbackQuery, state: FSMContext, bot: Bot):
    task_id = int(call.data.split(":")[-1])
    manager = await get_or_create_user(call.from_user.id, call.from_user.username, call.from_user.full_name)

    async with session_scope() as session:
        t = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not t:
            await call.answer("Задача не найдена", show_alert=True)
            return
        if t.status != TaskStatus.on_review:
            await call.answer("Задача не на ревью", show_alert=True)
            return

        appr = TaskApproval(task_id=task_id, manager_id=manager.id, decision=ApprovalDecision.rejected)
        session.add(appr)

        t.status = TaskStatus.rejected
        await session.commit()

    await notify_assignee(
        bot,
        task_id,
        f"❌ Менеджер отклонил выполнение задачи #{task_id}. Статус: rejected.",
        reply_markup=kb_task_open(task_id),
    )

    await call.message.edit_text("❌ Отклонено: задача переведена в rejected.", reply_markup=kb_task_open(task_id))
    await call.answer()


# ============================================================
# task actions: cancel
# ============================================================

@router.callback_query(F.data.startswith("mtask:cancel:"))
async def cb_task_cancel(call: CallbackQuery, state: FSMContext):
    task_id = int(call.data.split(":")[-1])

    # ✅ проверяем статус задачи
    async with session_scope() as session:
        t = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()

    if not t:
        await call.answer("Задача не найдена", show_alert=True)
        return

    # если уже закрыта/отменена
    if t.status in (TaskStatus.done, TaskStatus.cancelled, TaskStatus.rejected):
        await state.clear()
        await call.message.edit_text("ℹ️ Задача уже закрыта.", reply_markup=kb_back_to_menu())
        await call.answer()
        return

    # обычный сценарий отмены
    await state.update_data(task_id=task_id)
    await call.message.edit_text(
        "🗑 Отменить задачу?",
        reply_markup=kb_yes_no(f"mtask:cancelconfirm:{task_id}")
    )
    await call.answer()


@router.callback_query(F.data.startswith("mtask:cancelconfirm:"))
async def cb_task_cancel_confirm(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    task_id = int(parts[2])
    decision = parts[3]

    if decision == "no":
        t = await load_task(task_id)
        if not t:
            await call.answer("Задача не найдена", show_alert=True)
            return

        status = t.status.value if hasattr(t.status, "value") else str(t.status)
        await call.message.edit_text(fmt_task(t), reply_markup=kb_task_card(task_id, status))
        await call.answer()
        return

    # YES → спрашиваем про комментарий
    await state.update_data(task_id=task_id)
    await state.set_state(ManagerTasks.cancel_comment_ask)

    await call.message.edit_text(
        "🗑 Задача будет отменена.\n\nДобавить комментарий?",
        reply_markup=kb_yes_no(f"mtask:cancelcomment:{task_id}")
    )

    await call.answer()


@router.callback_query(
    ManagerTasks.cancel_comment_ask,
    F.data.startswith("mtask:cancelcomment:")
)
async def cb_task_cancel_comment(call: CallbackQuery, state: FSMContext, bot: Bot):
    parts = call.data.split(":")
    task_id = int(parts[2])
    decision = parts[3]

    if decision == "no":

        async with session_scope() as session:
            t = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()

            if not t:
                await call.answer("Задача не найдена", show_alert=True)
                return

            manager = await get_or_create_user(
                call.from_user.id,
                call.from_user.username,
                call.from_user.full_name
            )

            session.add(
                TaskComment(
                    task_id=task_id,
                    author_id=manager.id,
                    text="Закрыто администратором бота"
                )
            )

            t.status = TaskStatus.cancelled
            await session.commit()

        await notify_assignee(
            bot,
            task_id,
            f"🗑 Менеджер отменил задачу #{task_id}.",
            reply_markup=kb_task_open(task_id),
        )

        await state.clear()

        await call.message.edit_text(
            "🗑 Задача отменена (cancelled).",
            reply_markup=kb_task_open(task_id)
        )

        await call.answer()
        return

    # YES → просим комментарий
    await state.update_data(task_id=task_id)
    await state.set_state(ManagerTasks.cancel_comment_text)

    await call.message.edit_text(
        "✍️ Введите комментарий для закрытия задачи:"
    )

    await call.answer()


@router.message(ManagerTasks.cancel_comment_text)
async def msg_task_cancel_comment_text(message: Message, state: FSMContext, bot: Bot):
    text = (message.text or "").strip()
    if not text:
        return await message.answer("Комментарий не может быть пустым. Напиши текст или нажми меню/назад.")

    data = await state.get_data()
    task_id = data.get("task_id")
    if not task_id:
        await state.clear()
        return await message.answer("Контекст потерян. Открой задачу заново.")

    async with session_scope() as session:
        t = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not t:
            await state.clear()
            return await message.answer("Задача не найдена.")

        q = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        me = q.scalar_one_or_none()
        author_id = me.id if me else t.creator_id

        session.add(
            TaskComment(
                task_id=task_id,
                author_id=author_id,
                text=f"{CLOSE_PREFIX}, комментарий: {text}"
            )
        )
        t.status = TaskStatus.cancelled
        await session.commit()

    await notify_assignee(
        bot,
        task_id,
        f"🗑 Менеджер отменил задачу #{task_id}.\nКомментарий:\n{text}",
        reply_markup=kb_task_open(task_id),
    )

    await state.set_state(ManagerTasks.menu)

    await wizard_show_from_message(
        message,
        state,
        "🗑 Задача отменена (cancelled).",
        reply_markup=kb_task_open(task_id),
        delete_previous=True,
    )
    await wizard_clear(state)


def _short(s: Optional[str], limit: int = 60) -> str:
    if not s:
        return "—"
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return "—"
    return dt.strftime("%d.%m %H:%M")


def _render_table(rows: list[tuple[str, str, str, str]], title: str) -> str:
    """
    rows: (исполнитель, задача, дедлайн, последний_коммент)
    """
    if not rows:
        return f"{title}\n(нет)\n"

    # фиксируем ширины, чтобы таблица не расползалась
    h1, h2, h3, h4 = "Исполнитель", "Задача", "Дедлайн", "Последний коммент/результат"
    w1 = min(max(len(h1), max(len(r[0]) for r in rows)), 18)
    w2 = min(max(len(h2), max(len(r[1]) for r in rows)), 22)
    w3 = len(h3)
    w4 = min(max(len(h4), max(len(r[3]) for r in rows)), 40)

    def cut(val: str, w: int) -> str:
        val = val or "—"
        if len(val) <= w:
            return val.ljust(w)
        return (val[: w - 1] + "…")

    lines = [
        title,
        f"{cut(h1, w1)} | {cut(h2, w2)} | {cut(h3, w3)} | {cut(h4, w4)}",
        f"{'-' * w1}-+-{'-' * w2}-+-{'-' * w3}-+-{'-' * w4}",
    ]
    for a, t, d, c in rows:
        lines.append(f"{cut(a, w1)} | {cut(t, w2)} | {cut(d, w3)} | {cut(c, w4)}")

    return "```text\n" + "\n".join(lines) + "\n```\n"


def _split_for_tg(text: str, limit: int = 3500) -> list[str]:
    # Telegram лимит 4096, но оставим запас
    parts = []
    buf = ""
    for chunk in text.split("\n"):
        add = chunk + "\n"
        if len(buf) + len(add) > limit:
            parts.append(buf.rstrip())
            buf = add
        else:
            buf += add
    if buf.strip():
        parts.append(buf.rstrip())
    return parts


@router.callback_query(F.data == "mgr:tasks:stats")
async def cb_manager_tasks_stats(call: CallbackQuery):
    async with session_scope() as session:
        # 1) Проверка роли
        q = await session.execute(select(User).where(User.tg_id == call.from_user.id))
        me = q.scalar_one_or_none()
        if not me or me.role not in (UserRole.manager, UserRole.admin):
            await call.answer("Доступно только менеджеру", show_alert=True)
            return

        # 2) Коррелированные подзапросы: последний комментарий по задаче
        last_comment_text = (
            select(TaskComment.text)
            .where(TaskComment.task_id == Task.id)
            .order_by(TaskComment.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )

        # 3) Вытаскиваем активные и done
        #    assignee может быть NULL, поэтому left join через relationship (просто читаем Task.assignee отдельно)
        Assignee = aliased(User)

        q = await session.execute(
            select(
                Task.id,
                Task.title,
                Task.deadline_at,
                Task.status,
                Assignee.full_name,
                Assignee.username,
                last_comment_text.label("last_comment"),
            )
            .select_from(Task)
            .join(Assignee, Assignee.id == Task.assignee_id, isouter=True)
            .where(Task.status.in_([TaskStatus.new, TaskStatus.in_progress, TaskStatus.on_review, TaskStatus.done]))
            .order_by(Task.status.asc(), Task.created_at.desc())
        )
        items = q.all()

    # 4) Формируем строки
    active_rows: list[tuple[str, str, str, str]] = []
    done_rows: list[tuple[str, str, str, str]] = []

    for _id, title, deadline_at, status, full_name, username, last_comment in items:
        assignee = full_name or (f"@{username}" if username else "—")
        row = (
            _short(assignee, 18),
            _short(title, 22),
            _fmt_dt(deadline_at),
            _short(last_comment, 60),
        )
        if status == TaskStatus.done:
            done_rows.append(row)
        else:
            active_rows.append(row)

    text = "📊 Статистика по задачам\n\n"
    text += _render_table(active_rows, "🟡 В работе (new / in_progress / on_review)")
    text += _render_table(done_rows, "🟢 Завершённые (done)")

    # 5) Отправка (режем на части)
    parts = _split_for_tg(text)
    if call.message:
        # первое — редактируем, остальные — отдельными сообщениями
        await call.message.edit_text(parts[0], reply_markup=kb_back_to_menu())
        for p in parts[1:]:
            await call.message.answer(p)
    await call.answer()

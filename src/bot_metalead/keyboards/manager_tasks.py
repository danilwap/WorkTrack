from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot_metalead.db.models import TaskPriority, TaskStatus
from src.bot_metalead.db.models import User

import calendar
from datetime import datetime

from src.bot_metalead.utils.helpers import now_msk


def kb_tasks_filters() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🟢 Активные", callback_data="mtasks:filter:active")
    kb.button(text="📦 Все", callback_data="mtasks:filter:all")
    kb.button(text="⏰ Просроченные", callback_data="mtasks:filter:overdue")
    kb.button(text="👤 По сотруднику", callback_data="mtasks:filter:by_employee")
    kb.button(text="🏠 Меню", callback_data="main:menu")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def kb_priority_pick() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🟢 Низкий", callback_data=f"mtasks:prio:{TaskPriority.low.value}")
    kb.button(text="🟡 Средний", callback_data=f"mtasks:prio:{TaskPriority.medium.value}")
    kb.button(text="🟠 Высокий", callback_data=f"mtasks:prio:{TaskPriority.high.value}")
    kb.button(text="🔴 Срочный", callback_data=f"mtasks:prio:{TaskPriority.urgent.value}")
    kb.button(text="🏠 Меню", callback_data="main:menu")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def kb_task_open_manager(task_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Открыть", callback_data=f"mtask:open:{task_id}")
    kb.button(text="🏠 Меню", callback_data="main:menu")
    kb.adjust(1)
    return kb.as_markup()


def kb_task_card(task_id: int, status: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(text="➕ Добавить комментарий", callback_data=f"mtask:comment:{task_id}")
    kb.button(text="💬 Комментарии", callback_data=f"mtask:comments:{task_id}:0")
    kb.button(text="🔔 Напомнить", callback_data=f"mtask:remind:{task_id}")
    kb.button(text="✏️ Изменить", callback_data=f"mtask:edit:{task_id}")

    if status == TaskStatus.on_review.value:
        kb.button(text="✅ Апрув", callback_data=f"mtask:approve:{task_id}")
        kb.button(text="❌ Отклонить", callback_data=f"mtask:reject:{task_id}")

    kb.button(text="🗑 Отменить", callback_data=f"mtask:cancel:{task_id}")
    kb.button(text="⬅️ Назад к списку", callback_data="mtasks:list")
    kb.adjust(1, 1, 1, 2, 1, 1)
    return kb.as_markup()


def kb_remind_when(task_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Сегодня (в 18:00)", callback_data=f"mtask:remwhen:{task_id}:today_18")
    kb.button(text="Завтра (в 10:00)", callback_data=f"mtask:remwhen:{task_id}:tomorrow_10")
    kb.button(text="Через N часов", callback_data=f"mtask:remwhen:{task_id}:in_hours")
    kb.button(text="Ввести дату/время", callback_data=f"mtask:remwhen:{task_id}:custom")
    kb.button(text="⬅️ Назад", callback_data=f"mtask:open:{task_id}")
    kb.adjust(1, 1, 2, 1)
    return kb.as_markup()


def kb_edit_fields(task_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 Дедлайн", callback_data=f"mtask:editfield:{task_id}:deadline")
    kb.button(text="⚡ Приоритет", callback_data=f"mtask:editfield:{task_id}:priority")
    kb.button(text="👤 Исполнитель", callback_data=f"mtask:editfield:{task_id}:assignee")
    kb.button(text="⬅️ Назад", callback_data=f"mtask:open:{task_id}")
    kb.adjust(1)
    return kb.as_markup()


def kb_yes_no(prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data=f"{prefix}:yes")
    kb.button(text="❌ Нет", callback_data=f"{prefix}:no")
    kb.adjust(2)
    return kb.as_markup()

def kb_assignee_pick(employees: list[User], page: int = 0, per_page: int = 8) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    start = page * per_page
    end = start + per_page
    chunk = employees[start:end]

    for u in chunk:
        label = u.full_name or u.username or str(u.tg_id)
        kb.button(text=f"👤 {label}", callback_data=f"mtasks:assignee:{u.id}")

    # навигация
    nav = InlineKeyboardBuilder()
    if page > 0:
        nav.button(text="⬅️", callback_data=f"mtasks:assigneepage:{page-1}")
    if end < len(employees):
        nav.button(text="➡️", callback_data=f"mtasks:assigneepage:{page+1}")

    # собрать
    kb.adjust(1)

    if nav.buttons:
        kb.row(*nav.buttons)

    kb.button(text="🏠 Меню", callback_data="main:menu")
    kb.adjust(1)

    return kb.as_markup()


def kb_task_comments(task_id: int, page: int, total_pages: int, comment_ids: list[int] | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    # кнопки "открыть полностью" для комментов текущей страницы
    if comment_ids:
        for cid in comment_ids:
            kb.button(text=f"📄 Коммент #{cid}", callback_data=f"mtask:commentfull:{task_id}:{cid}:{page}")
        kb.adjust(1)

    nav = InlineKeyboardBuilder()
    if page > 0:
        nav.button(text="⬅️ Новее", callback_data=f"mtask:comments:{task_id}:{page-1}")
    if page + 1 < total_pages:
        nav.button(text="➡️ Старее", callback_data=f"mtask:comments:{task_id}:{page+1}")
    if nav.buttons:
        kb.row(*nav.buttons)

    kb.button(text="⬅️ Назад к задаче", callback_data=f"mtask:open:{task_id}")
    kb.adjust(1)
    return kb.as_markup()

def kb_comment_full(task_id: int, comment_id: int, back_page: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад к комментариям", callback_data=f"mtask:comments:{task_id}:{back_page}")
    return kb.as_markup()


def kb_tasks_pick(
    tasks,
    page: int = 0,
    per_page: int = 8,
    prefix: str = "mtask:open:",
    back_text: str | None = None,
    back_callback: str | None = None,
    show_menu: bool = True,
) -> InlineKeyboardMarkup:
    """
    tasks: список Task (у которых есть .id и .title)
    Кнопки: по 1 задаче в строке + навигация
    callback задачи: mtask:open:<id>
    """

    kb = InlineKeyboardBuilder()

    total = len(tasks)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))

    start = page * per_page
    end = start + per_page
    chunk = tasks[start:end]

    for t in chunk:
        title = (t.title[:30] + "…") if len(t.title) > 30 else t.title
        kb.button(text=f"🧩 #{t.id} — {title}", callback_data=f"{prefix}{t.id}")

    kb.adjust(1)

    # навигация
    nav = InlineKeyboardBuilder()
    if page > 0:
        nav.button(text="⬅️", callback_data=f"mtasks:pickpage:{page-1}")
    nav.button(text=f"{page+1}/{pages}", callback_data="noop")
    if page < pages - 1:
        nav.button(text="➡️", callback_data=f"mtasks:pickpage:{page+1}")

    if nav.buttons:
        kb.row(*nav.buttons)

    # нижние кнопки
    bottom = []
    if back_text and back_callback:
        bottom.append(
            InlineKeyboardButton(text=back_text, callback_data=back_callback)
        )
    if show_menu:
        bottom.append(
            InlineKeyboardButton(text="🏠 Меню", callback_data="main:menu")
        )

    if bottom:
        kb.row(*bottom)

    return kb.as_markup()


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
        nav.button(text="⬅️", callback_data=f"mtasks:employeepage:{page - 1}")
    nav.button(text=f"{page + 1}/{pages}", callback_data="noop")
    if page < pages - 1:
        nav.button(text="➡️", callback_data=f"mtasks:employeepage:{page + 1}")

    kb.adjust(1)
    kb.row(*nav.buttons)

    # кнопка меню
    kb.row(*InlineKeyboardBuilder().button(text="⬅️ К фильтрам", callback_data="mtasks:list").buttons)
    kb.row(*InlineKeyboardBuilder().button(text="🏠 Меню", callback_data="main:menu").buttons)

    return kb.as_markup()


def kb_deadline_calendar(year: int, month: int, *, prefix: str = "mcal") -> InlineKeyboardMarkup:
    now = now_msk().replace(tzinfo=None)
    today = now.date()

    rows = []

    current_month_start = datetime(today.year, today.month, 1)
    shown_month_start = datetime(year, month, 1)

    can_go_prev = shown_month_start > current_month_start

    prev_year, prev_month = year, month - 1
    next_year, next_month = year, month + 1

    if prev_month == 0:
        prev_month = 12
        prev_year -= 1

    if next_month == 13:
        next_month = 1
        next_year += 1

    rows.append([
        InlineKeyboardButton(
            text="◀️" if can_go_prev else " ",
            callback_data=f"{prefix}:open:{prev_year}:{prev_month}" if can_go_prev else f"{prefix}:ignore",
        ),
        InlineKeyboardButton(
            text=f"{calendar.month_name[month]} {year}",
            callback_data=f"{prefix}:ignore",
        ),
        InlineKeyboardButton(
            text="▶️",
            callback_data=f"{prefix}:open:{next_year}:{next_month}",
        ),
    ])

    rows.append([
        InlineKeyboardButton(text="Пн", callback_data=f"{prefix}:ignore"),
        InlineKeyboardButton(text="Вт", callback_data=f"{prefix}:ignore"),
        InlineKeyboardButton(text="Ср", callback_data=f"{prefix}:ignore"),
        InlineKeyboardButton(text="Чт", callback_data=f"{prefix}:ignore"),
        InlineKeyboardButton(text="Пт", callback_data=f"{prefix}:ignore"),
        InlineKeyboardButton(text="Сб", callback_data=f"{prefix}:ignore"),
        InlineKeyboardButton(text="Вс", callback_data=f"{prefix}:ignore"),
    ])

    month_days = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    while len(month_days) < 6:
        month_days.append([0] * 7)

    for week in month_days:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data=f"{prefix}:ignore"))
                continue

            cell_date = datetime(year, month, day).date()

            if cell_date < today:
                row.append(InlineKeyboardButton(text="·", callback_data=f"{prefix}:ignore"))
            else:
                row.append(
                    InlineKeyboardButton(
                        text=str(day),
                        callback_data=f"{prefix}:day:{year}:{month}:{day}",
                    )
                )
        rows.append(row)

    rows.append([InlineKeyboardButton(text="🚫 Без дедлайна", callback_data=f"{prefix}:none")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:back")])

    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_deadline_hours(year: int, month: int, day: int, *, prefix: str = "mcal"):
    builder = InlineKeyboardBuilder()
    now = now_msk().replace(tzinfo=None)

    for hour in range(24):
        dt = datetime(year, month, day, hour, 0)

        if dt < now:
            builder.button(text="·", callback_data=f"{prefix}:ignore")
        else:
            builder.button(
                text=f"{hour:02d}",
                callback_data=f"{prefix}:hour:{year}:{month}:{day}:{hour}"
            )

    builder.button(text="⬅️ К календарю", callback_data=f"{prefix}:open:{year}:{month}")
    builder.adjust(6, 6, 6, 6, 1)
    return builder.as_markup()


def kb_deadline_minutes(year: int, month: int, day: int, hour: int, *, prefix: str = "mcal"):
    builder = InlineKeyboardBuilder()
    now = now_msk().replace(tzinfo=None)

    for minute in [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]:
        dt = datetime(year, month, day, hour, minute)

        if dt < now:
            builder.button(text="·", callback_data=f"{prefix}:ignore")
        else:
            builder.button(
                text=f"{minute:02d}",
                callback_data=f"{prefix}:minute:{year}:{month}:{day}:{hour}:{minute}"
            )

    builder.button(text="⬅️ К часам", callback_data=f"{prefix}:day:{year}:{month}:{day}")
    builder.adjust(4, 4, 4, 1)
    return builder.as_markup()


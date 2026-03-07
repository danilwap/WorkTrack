from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot_metalead.db.models import TaskPriority, TaskStatus
from src.bot_metalead.db.models import User


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
    kb.button(text="🟢 Low", callback_data=f"mtasks:prio:{TaskPriority.low.value}")
    kb.button(text="🟡 Medium", callback_data=f"mtasks:prio:{TaskPriority.medium.value}")
    kb.button(text="🟠 High", callback_data=f"mtasks:prio:{TaskPriority.high.value}")
    kb.button(text="🔴 Urgent", callback_data=f"mtasks:prio:{TaskPriority.urgent.value}")
    kb.button(text="🏠 Меню", callback_data="main:menu")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def kb_task_open(task_id: int) -> InlineKeyboardMarkup:
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


def kb_tasks_pick(tasks, page: int = 0, per_page: int = 8, prefix: str = "mtask:open:") -> InlineKeyboardMarkup:
    """
    tasks: список Task (у которых есть .id и .title)
    Кнопки: по 1 задаче в строке + навигация
    callback: mtask:open:<id>
    """
    kb = InlineKeyboardBuilder()

    total = len(tasks)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))

    start = page * per_page
    end = start + per_page
    chunk = tasks[start:end]

    for t in chunk:
        kb.button(text=f"🧩 #{t.id} — {t.title[:30]}", callback_data=f"{prefix}{t.id}")

    kb.button(text="🏠 Меню", callback_data="main:menu")


    # навигация
    nav = InlineKeyboardBuilder()
    if page > 0:
        nav.button(text="⬅️", callback_data=f"mtasks:pickpage:{page-1}")
    nav.button(text=f"{page+1}/{pages}", callback_data="noop")
    if page < pages - 1:
        nav.button(text="➡️", callback_data=f"mtasks:pickpage:{page+1}")

    kb.adjust(1)
    kb.row(*nav.buttons)

    return kb.as_markup()
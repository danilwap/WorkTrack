from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot_metalead.db.models import TaskPriority, TaskStatus
from src.bot_metalead.db.models import User

def kb_task_card_user(task_id: int, status: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(text="➕ Добавить комментарий", callback_data=f"mtask:comment:{task_id}")
    kb.button(text="💬 Комментарии", callback_data=f"mtask:comments:{task_id}:0")
    kb.button(text="🔔 Напомнить", callback_data=f"mtask:remind:{task_id}")
    kb.button(text="✏️ Изменить", callback_data=f"mtask:edit:{task_id}")
    kb.button(text="🗑 Отменить", callback_data=f"mtask:cancel:{task_id}")
    kb.button(text="⬅️ Назад к списку", callback_data="tasks:active")
    kb.adjust(1, 1, 1, 2, 1, 1)
    return kb.as_markup()


from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def kb_user_tasks_pick(tasks, page: int = 0, per_page: int = 8, prefix: str = "task:open:") -> InlineKeyboardMarkup:
    """
    tasks: список Task (у которых есть .id и .title)
    Кнопки: по 1 задаче в строке + навигация
    callback: task:open:<id>
    """

    kb = InlineKeyboardBuilder()

    total = len(tasks)
    pages = max(1, (total + per_page - 1) // per_page)

    page = max(0, min(page, pages - 1))

    start = page * per_page
    end = start + per_page
    chunk = tasks[start:end]

    # задачи
    for t in chunk:
        title = (t.title or "")[:30]
        kb.button(
            text=f"🧩 #{t.id} — {title}",
            callback_data=f"{prefix}{t.id}"
        )

    kb.adjust(1)

    # навигация
    nav = InlineKeyboardBuilder()

    if page > 0:
        nav.button(
            text="⬅️",
            callback_data=f"tasks:page:{page-1}"
        )

    nav.button(
        text=f"{page+1}/{pages}",
        callback_data="noop"
    )

    if page < pages - 1:
        nav.button(
            text="➡️",
            callback_data=f"tasks:page:{page+1}"
        )

    kb.row(*nav.buttons)

    # меню
    kb.button(
        text="🏠 Меню",
        callback_data="main:menu"
    )

    return kb.as_markup()



def kb_user_task_open(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Комментарий", callback_data=f"task:comment:{task_id}")],
            [InlineKeyboardButton(text="✅ Завершить", callback_data=f"task:done:{task_id}")],
            [InlineKeyboardButton(text="⬅️ К задачам", callback_data="tasks:active")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="main:menu")],
        ]
    )
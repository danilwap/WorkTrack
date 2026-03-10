from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton





def kb_reminder_types() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ежедневно", callback_data="notes:rtype:daily")],
        [InlineKeyboardButton(text="Еженедельно", callback_data="notes:rtype:weekly")],
        [InlineKeyboardButton(text="Ежемесячно", callback_data="notes:rtype:monthly")],
        [InlineKeyboardButton(text="Отмена", callback_data="notes:menu")],
    ])


# Клавиатура, которая отправляется при запросе названия заметки
def kb_back_menu_notes() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="notes:back")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="main:menu")],
    ])


def kb_notes_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать заметку", callback_data="notes:create")],
        [InlineKeyboardButton(text="📋 Мои заметки", callback_data="notes:list")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="main:menu")],
    ])



def kb_yes_no_back(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да", callback_data=f"{prefix}:yes"),
            InlineKeyboardButton(text="Нет", callback_data=f"{prefix}:no"),
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="notes:back")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="main:menu")],
    ])

def kb_notes_list_paginated(notes: list, page: int, page_size: int = 5) -> InlineKeyboardMarkup:
    start = page * page_size
    end = start + page_size
    page_notes = notes[start:end]

    rows = []

    for n in page_notes:
        title = n.title if len(n.title) <= 25 else n.title[:22] + "..."
        rows.append([
            InlineKeyboardButton(
                text=f"#{n.id} — {title}",
                callback_data=f"notes:open:{n.id}"
            )
        ])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"notes:list:page:{page-1}"))
    if end < len(notes):
        nav_row.append(InlineKeyboardButton(text="➡️ Вперёд", callback_data=f"notes:list:page:{page+1}"))

    if nav_row:
        rows.append(nav_row)

    rows.append([InlineKeyboardButton(text="🧾 К заметкам", callback_data="notes:menu")])
    rows.append([InlineKeyboardButton(text="🏠 Меню", callback_data="main:menu")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_note_view(note_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Изменить", callback_data=f"notes:edit:{note_id}"),
            InlineKeyboardButton(text="💬 Комментарий", callback_data=f"notes:comment:{note_id}"),
        ],
        [InlineKeyboardButton(text="✅ Завершить", callback_data=f"notes:close:{note_id}")],
        [
            InlineKeyboardButton(text="🧾 К заметкам", callback_data="notes:list"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="main:menu"),
        ],
    ])



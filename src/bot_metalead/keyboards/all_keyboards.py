from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def kb_main_menu(role: str = "employee") -> InlineKeyboardMarkup:
    rows = []

    # --- сотрудник ---
    if role == "employee":
        rows += [
            [InlineKeyboardButton(text="✅ Мои активные задачи", callback_data="tasks:active")],
        ]

    # --- менеджер ---
    if role in ["manager", "admin"]:
        rows += [
            [InlineKeyboardButton(text="➕ Создать задачу", callback_data="mtasks:new")],
            [InlineKeyboardButton(text="📋 Все задачи", callback_data="mtasks:list")],
            [InlineKeyboardButton(text="⏰ Просроченные задачи", callback_data="mtasks:overdue")],
            [InlineKeyboardButton(text="📊 Статистика по задачам", callback_data="mgr:tasks:stats")],
        ]

    # --- общие ---
    rows += [
        [InlineKeyboardButton(text="🧾 Заметки", callback_data="notes:menu")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Меню", callback_data="main:menu")]
    ])


def kb_notes_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать заметку", callback_data="notes:create")],
        [InlineKeyboardButton(text="📋 Мои заметки", callback_data="notes:list")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="main:menu")],
    ])


def kb_yes_no(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да", callback_data=f"{prefix}:yes"),
            InlineKeyboardButton(text="Нет", callback_data=f"{prefix}:no"),
        ]
    ])


def kb_reminder_types() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ежедневно", callback_data="notes:rtype:daily")],
        [InlineKeyboardButton(text="Еженедельно", callback_data="notes:rtype:weekly")],
        [InlineKeyboardButton(text="Ежемесячно", callback_data="notes:rtype:monthly")],
        [InlineKeyboardButton(text="Отмена", callback_data="notes:menu")],
    ])


def kb_leader_approval(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"leader:approve:{task_id}"),
            InlineKeyboardButton(text="❌ Вернуть в работу", callback_data=f"leader:return:{task_id}"),
        ]
    ])
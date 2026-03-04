from __future__ import annotations

from datetime import datetime, time as dtime, timezone

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from src.bot_metalead.keyboards.manager_tasks import kb_task_open, kb_tasks_pick
from src.bot_metalead.routers.manager_tasks import (
    wizard_show_from_callback,
    wizard_show_from_message,
    wizard_add_extra,
    wizard_clear,
    WIZARD_KEY,
    WIZARD_EXTRA_KEY,
)

from src.bot_metalead.states.tasks import Tasks
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from sqlalchemy import select

from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.models import User, Task, TaskStatus
from src.bot_metalead.keyboards.all_keyboards import kb_back_to_menu
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.bot_metalead.db.models import Task, TaskStatus, User
from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.models import (
    User,
    UserRole,
    Note,
    NoteComment,
    NoteReminder,
    NoteStatus,     # enum для notes.status
    ScheduleType,   # enum для note_reminders.schedule_type
    TaskComment,
)
from src.bot_metalead.states.tasks import Notes, Main
from src.bot_metalead.keyboards.all_keyboards import (
    kb_notes_menu,
    kb_back_to_menu,
    kb_yes_no,
    kb_reminder_types,
)

router = Router()

TASKS_PICK_IDS = "tasks_pick_ids"
TASKS_PICK_PAGE = "tasks_pick_page"
async def notify_task_creator_on_employee_comment(
    bot: Bot,
    task_id: int,
    author_user: User,
    comment_text: str,
    reply_markup=None,
) -> bool:
    """
    Уведомляем менеджера/создателя (Task.creator) о комментарии исполнителя.
    Возвращает True если отправили.
    """
    try:
        async with session_scope() as session:
            q = await session.execute(
                select(Task)
                .where(Task.id == task_id)
                .options(selectinload(Task.creator))
            )
            t = q.scalar_one_or_none()

        if not t or not t.creator or not t.creator.tg_id:
            return False

        author_name = author_user.full_name or (f"@{author_user.username}" if author_user.username else str(author_user.tg_id))
        text = (
            f"💬 Комментарий от исполнителя\n"
            f"🧩 Задача #{task_id}: {t.title}\n"
            f"👤 {author_name}\n\n"
            f"{comment_text}"
        )
        await bot.send_message(t.creator.tg_id, text, reply_markup=reply_markup)
        return True
    except Exception:
        return False


# -------------------------
# Helpers
# -------------------------
async def get_or_create_user(tg_id: int, username: str | None, full_name: str | None) -> User:
    async with session_scope() as session:
        q = await session.execute(select(User).where(User.tg_id == tg_id))
        u = q.scalar_one_or_none()

        if not u:
            u = User(
                tg_id=tg_id,
                username=username,
                full_name=full_name,
                role=UserRole.employee,  # FIX: enum, не строка
            )
            session.add(u)
        else:
            u.username = username
            u.full_name = full_name

        await session.commit()
        return u


def _schedule_type_from_ui(raw: str) -> ScheduleType:
    """
    UI отдаёт строки типа 'daily'/'weekly'/'monthly'.
    В БД поле schedule_type — enum ScheduleType.
    """
    raw = (raw or "").strip().lower()
    mapping = {
        "daily": ScheduleType.daily,
        "weekly": ScheduleType.weekly,
        "monthly": ScheduleType.monthly,
    }
    return mapping.get(raw, ScheduleType.daily)


# -------------------------
# Menu
# -------------------------
@router.callback_query(F.data == "notes:menu")
async def cb_notes_menu(call: CallbackQuery, state: FSMContext):
    await state.set_state(Notes.menu)
    await call.message.edit_text("🧾 Заметки", reply_markup=kb_notes_menu())
    await call.answer()



@router.callback_query(F.data == "tasks:inbox")
async def cb_tasks_inbox(call: CallbackQuery, state: FSMContext):
    async with session_scope() as session:
        q = await session.execute(select(User).where(User.tg_id == call.from_user.id))
        u = q.scalar_one_or_none()
        if not u:
            await call.answer("Пользователь не найден. Нажми /start", show_alert=True)
            return

        q = await session.execute(
            select(Task)
            .where(
                Task.assignee_id == u.id,
                Task.status.in_([TaskStatus.new, TaskStatus.in_progress, TaskStatus.on_review]),
            )
            .order_by(Task.created_at.desc())
            .limit(50)
        )
        tasks = q.scalars().all()

    if not tasks:
        await wizard_show_from_callback(call, state, "📥 Входящие задачи\n\nЗадач пока нет ✅", reply_markup=kb_back_to_menu())
        await call.answer()
        return

    await state.update_data(**{TASKS_PICK_IDS: [t.id for t in tasks], TASKS_PICK_PAGE: 0})

    await wizard_show_from_callback(
        call,
        state,
        "📥 Входящие задачи (выбери по кнопке):",
        reply_markup=kb_tasks_pick(tasks, page=0),
    )
    await call.answer()


# -------------------------
# ✅ Мои активные задачи
# -------------------------
@router.callback_query(F.data == "tasks:active")
async def cb_tasks_active(call: CallbackQuery, state: FSMContext):
    async with session_scope() as session:
        q = await session.execute(select(User).where(User.tg_id == call.from_user.id))
        user = q.scalar_one_or_none()

        if not user:
            await call.answer("Пользователь не найден. Нажми /start", show_alert=True)
            return

        q = await session.execute(
            select(Task)
            .where(
                Task.assignee_id == user.id,
                Task.status.in_([TaskStatus.new, TaskStatus.in_progress, TaskStatus.on_review]),
            )
            .options(selectinload(Task.assignee))
            .order_by(Task.created_at.desc())
            .limit(50)
        )
        tasks = q.scalars().all()

    if not tasks:
        await wizard_show_from_callback(
            call,
            state,
            "📋 Активных задач нет.",
            reply_markup=kb_back_to_menu(),
        )
        await call.answer()
        return

    # сохраняем список для пагинации
    await state.update_data(**{TASKS_PICK_IDS: [t.id for t in tasks], TASKS_PICK_PAGE: 0})

    await wizard_show_from_callback(
        call,
        state,
        "📋 Мои активные задачи (выбери по кнопке):",
        reply_markup=kb_tasks_pick(tasks, page=0),
    )
    await call.answer()



@router.callback_query(F.data.startswith("tasks:pickpage:"))
async def cb_tasks_pick_page_employee(call: CallbackQuery, state: FSMContext):
    page = int(call.data.split(":")[-1])
    data = await state.get_data()
    ids = data.get(TASKS_PICK_IDS) or []
    if not ids:
        await call.answer("Список задач устарел. Открой меню заново.", show_alert=True)
        return

    async with session_scope() as session:
        q = await session.execute(select(Task).where(Task.id.in_(ids)).order_by(Task.created_at.desc()))
        tasks = q.scalars().all()

    await state.update_data(**{TASKS_PICK_PAGE: page})

    await wizard_show_from_callback(
        call,
        state,
        "📋 Задачи (выбери по кнопке):",
        reply_markup=kb_tasks_pick(tasks, page=page),
    )
    await call.answer()

# -------------------------
# 💬 Комментарий к задаче (старт)
# -------------------------
@router.callback_query(F.data == "tasks:comment")
async def cb_tasks_comment(call: CallbackQuery, state: FSMContext):
    await state.set_state(Tasks.comment_choose_task)
    await call.message.edit_text(
        "💬 Добавление комментария\n\n"
        "Введи номер задачи, к которой добавить комментарий:",
        reply_markup=kb_back_to_menu(),
    )
    await call.answer()


# -------------------------
# 💬 Комментарий к задаче: выбрать задачу
# -------------------------
@router.message(Tasks.comment_choose_task)
async def msg_tasks_comment_choose_task(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        return await message.answer("Введи номер задачи цифрами (например: 12).")

    task_id = int(raw)

    async with session_scope() as session:
        q = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        user = q.scalar_one_or_none()
        if not user:
            await state.clear()
            return await message.answer("Пользователь не найден. Нажми /start")

        # Проверяем: задача существует и назначена этому пользователю
        q = await session.execute(
            select(Task).where(
                Task.id == task_id,
                Task.assignee_id == user.id,
                Task.status.in_([TaskStatus.new, TaskStatus.in_progress, TaskStatus.on_review]),
            )
        )
        task = q.scalar_one_or_none()

    if not task:
        return await message.answer("Не нашёл активную задачу с таким номером (или она не твоя). Введи другой номер.")

    await state.update_data(task_id=task_id)
    await state.set_state(Tasks.comment_enter_text)
    await message.answer(
        f"🧩 Задача #{task_id}\n\nТеперь введи текст комментария:",
        reply_markup=kb_back_to_menu(),
    )


# -------------------------
# 💬 Комментарий к задаче: текст -> запись в БД
# -------------------------
@router.message(Tasks.comment_enter_text)
async def msg_tasks_comment_enter_text(message: Message, state: FSMContext, bot: Bot):
    text = (message.text or "").strip()
    if not text:
        return await message.answer("Комментарий не может быть пустым. Напиши текст комментария.")

    data = await state.get_data()
    task_id = data.get("task_id")

    if not task_id:
        await state.clear()
        return await message.answer("Контекст потерян. Открой меню и попробуй ещё раз.")

    async with session_scope() as session:
        q = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        user = q.scalar_one_or_none()
        if not user:
            await state.clear()
            return await message.answer("Пользователь не найден. Нажми /start")

        # (опционально) ещё раз убедимся что задача существует и назначена пользователю
        q = await session.execute(
            select(Task.id).where(
                Task.id == task_id,
                Task.assignee_id == user.id,
            )
        )
        ok = q.scalar_one_or_none()
        if not ok:
            await state.clear()
            return await message.answer("Задача не найдена или больше не принадлежит тебе.")

        session.add(TaskComment(task_id=task_id, author_id=user.id, text=text))
        await session.commit()

    await notify_task_creator_on_employee_comment(
        bot=bot,
        task_id=task_id,
        author_user=user,
        comment_text=text,
        reply_markup=kb_task_open(task_id),  # менеджеру удобно открыть карточку
    )

    await state.clear()
    await message.answer("✅ Комментарий добавлен.", reply_markup=kb_back_to_menu())


# -------------------------
# Create note
# -------------------------
@router.callback_query(F.data == "notes:create")
async def cb_notes_create(call: CallbackQuery, state: FSMContext):
    await state.set_state(Notes.create_title)
    await call.message.edit_text("➕ Создание заметки\n\nВведи название:", reply_markup=kb_back_to_menu())
    await call.answer()


@router.message(Notes.create_title)
async def msg_notes_title(message: Message, state: FSMContext):
    title = (message.text or "").strip()
    if not title:
        return await message.answer("Название не может быть пустым. Введи ещё раз.")

    await state.update_data(title=title)
    await state.set_state(Notes.create_body)
    await message.answer("Теперь введи описание (можно коротко):")


@router.message(Notes.create_body)
async def msg_notes_body(message: Message, state: FSMContext):
    # В модели Note поле называется description
    description = (message.text or "").strip()

    data = await state.get_data()
    u = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)

    async with session_scope() as session:
        note = Note(owner_id=u.id, title=data["title"], description=description)
        session.add(note)
        await session.commit()
        await session.refresh(note)

    await state.update_data(note_id=note.id)
    await state.set_state(Notes.create_reminder_ask)
    await message.answer("Добавить напоминание для этой заметки?", reply_markup=kb_yes_no("notes:remind"))


# -------------------------
# Reminder create flow
# -------------------------
@router.callback_query(F.data.in_(["notes:remind:yes", "notes:remind:no"]))
async def cb_notes_remind_ask(call: CallbackQuery, state: FSMContext):
    if call.data.endswith(":no"):
        await state.set_state(Notes.menu)
        await call.message.edit_text("✅ Заметка создана без напоминания.", reply_markup=kb_notes_menu())
        return await call.answer()

    await state.set_state(Notes.reminder_type)
    await call.message.edit_text("Выбери тип напоминания:", reply_markup=kb_reminder_types())
    await call.answer()


@router.callback_query(F.data.startswith("notes:rtype:"))
async def cb_notes_reminder_type(call: CallbackQuery, state: FSMContext):
    # UI-шная строка: daily/weekly/monthly
    raw = call.data.split(":")[-1]
    await state.update_data(rtype=raw)

    await state.set_state(Notes.reminder_time)
    await call.message.edit_text(
        "Введи время напоминания в формате HH:MM (например 09:30):",
        reply_markup=kb_back_to_menu(),
    )
    await call.answer()


@router.message(Notes.reminder_time)
async def msg_notes_reminder_time(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    try:
        hh, mm = raw.split(":")
        t = dtime(hour=int(hh), minute=int(mm))
    except Exception:
        return await message.answer("Неверный формат. Нужно HH:MM, например 09:30.")

    data = await state.get_data()
    note_id = data["note_id"]

    # FIX: schedule_type должен быть ScheduleType (enum), а не строка
    schedule_type = _schedule_type_from_ui(data.get("rtype", "daily"))

    # MVP: weekly/monthly без weekday/day_of_month — оставляем NULL
    async with session_scope() as session:
        q = await session.execute(select(Note).where(Note.id == note_id))
        note = q.scalar_one_or_none()
        if not note:
            await state.set_state(Main.menu)
            return await message.answer("Заметка не найдена.", reply_markup=kb_back_to_menu())

        rem = NoteReminder(
            note_id=note_id,
            schedule_type=schedule_type,  # FIX
            hour=t.hour,
            minute=t.minute,
            weekday=None,
            day_of_month=None,
            timezone="Europe/Helsinki",
            is_enabled=True,
        )
        session.add(rem)
        await session.commit()

    await state.set_state(Notes.menu)
    await message.answer("⏰ Напоминание сохранено.", reply_markup=kb_notes_menu())


# -------------------------
# List notes
# -------------------------
@router.callback_query(F.data == "notes:list")
async def cb_notes_list(call: CallbackQuery, state: FSMContext):
    u = await get_or_create_user(call.from_user.id, call.from_user.username, call.from_user.full_name)

    async with session_scope() as session:
        q = await session.execute(
            select(Note)
            .options(selectinload(Note.reminders))
            .where(Note.owner_id == u.id, Note.status == NoteStatus.active)
            .order_by(Note.created_at.desc())
        )
        notes = q.scalars().all()

    if not notes:
        await call.message.edit_text("📋 Активных заметок нет.", reply_markup=kb_notes_menu())
        return await call.answer()

    text = "📋 Мои заметки:\n\n" + "\n".join([f"• #{n.id} — {n.title}" for n in notes])
    text += "\n\nНапиши номер заметки в чат (например: 5), чтобы открыть."
    await state.set_state(Notes.list_notes)
    await state.update_data(note_ids=[n.id for n in notes])
    await call.message.edit_text(text, reply_markup=kb_notes_menu())
    await call.answer()


@router.message(Notes.list_notes)
async def msg_note_open(message: Message, state: FSMContext):
    data = await state.get_data()
    allowed = set(data.get("note_ids", []))

    if not message.text or not message.text.strip().isdigit():
        return await message.answer("Введи номер заметки цифрами (например: 5) или нажми 🏠 Меню.")

    note_id = int(message.text.strip())
    if note_id not in allowed:
        return await message.answer("Этой заметки нет в текущем списке. Открой список заново.")

    async with session_scope() as session:
        q = await session.execute(
            select(Note)
            .options(selectinload(Note.reminders))
            .where(Note.id == note_id)
        )
        n = q.scalar_one()

    active_rem = next((r for r in (n.reminders or []) if r.is_enabled), None)
    rem_text = ""
    if active_rem:
        rem_text = f"\n⏰ Напоминание: {active_rem.schedule_type.value} в {active_rem.hour:02d}:{active_rem.minute:02d}"

    text = f"🧾 Заметка #{n.id}\nНазвание: {n.title}\n\n{n.description or ''}{rem_text}"
    await message.answer(text, reply_markup=kb_notes_menu())


# -------------------------
# Add comment
# -------------------------
@router.callback_query(F.data == "notes:comment")
async def cb_note_comment(call: CallbackQuery, state: FSMContext):
    await state.set_state(Notes.comment_choose)
    await call.message.edit_text("💬 Введи номер заметки, к которой добавить комментарий:", reply_markup=kb_notes_menu())
    await call.answer()


@router.message(Notes.comment_choose)
async def msg_note_comment_choose(message: Message, state: FSMContext):
    if not message.text or not message.text.strip().isdigit():
        return await message.answer("Введи номер заметки цифрами.")
    note_id = int(message.text.strip())

    u = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)

    async with session_scope() as session:
        q = await session.execute(
            select(Note).where(
                Note.id == note_id,
                Note.owner_id == u.id,
                Note.status == NoteStatus.active,
            )
        )
        n = q.scalar_one_or_none()
        if not n:
            return await message.answer("Не нашёл активную заметку с таким номером.")

    await state.update_data(note_id=note_id)
    await state.set_state(Notes.comment_text)
    await message.answer("Напиши комментарий:")


@router.message(Notes.comment_text)
async def msg_note_comment_text(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        return await message.answer("Комментарий не может быть пустым.")

    note_id = (await state.get_data())["note_id"]
    u = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)

    async with session_scope() as session:
        session.add(NoteComment(note_id=note_id, author_id=u.id, text=text))
        await session.commit()

    await state.set_state(Notes.menu)
    await message.answer("💬 Комментарий добавлен.", reply_markup=kb_notes_menu())


# -------------------------
# Close note
# -------------------------
@router.callback_query(F.data == "notes:close")
async def cb_note_close(call: CallbackQuery, state: FSMContext):
    await state.set_state(Notes.close_choose)
    await call.message.edit_text("✅ Введи номер заметки, которую завершить:", reply_markup=kb_notes_menu())
    await call.answer()


@router.message(Notes.close_choose)
async def msg_note_close_choose(message: Message, state: FSMContext):
    if not message.text or not message.text.strip().isdigit():
        return await message.answer("Введи номер заметки цифрами.")
    note_id = int(message.text.strip())

    u = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)

    async with session_scope() as session:
        q = await session.execute(
            select(Note).where(
                Note.id == note_id,
                Note.owner_id == u.id,
                Note.status == NoteStatus.active,
            )
        )
        n = q.scalar_one_or_none()
        if not n:
            return await message.answer("Не нашёл активную заметку с таким номером.")

        n.status = NoteStatus.done
        # FIX: timezone-aware datetime для DateTime(timezone=True)
        n.done_at = datetime.now(timezone.utc)
        await session.commit()

    await state.set_state(Notes.menu)
    await message.answer("✅ Заметка завершена.", reply_markup=kb_notes_menu())
from __future__ import annotations

from datetime import datetime, time as dtime

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.models import User, Note, NoteComment, NoteReminder
from src.bot_metalead.states.tasks import Notes, Main
from src.bot_metalead.keyboards.all_keyboards import kb_notes_menu, kb_back_to_menu, kb_yes_no, kb_reminder_types

router = Router()


async def get_or_create_user(tg_id: int, username: str | None, full_name: str | None) -> User:
    async with session_scope() as session:
        q = await session.execute(select(User).where(User.tg_id == tg_id))
        u = q.scalar_one_or_none()
        if not u:
            u = User(tg_id=tg_id, username=username, full_name=full_name, role="employee")
            session.add(u)
        else:
            u.username = username
            u.full_name = full_name
        await session.commit()
        return u


@router.callback_query(F.data == "notes:menu")
async def cb_notes_menu(call: CallbackQuery, state: FSMContext):
    await state.set_state(Notes.menu)
    await call.message.edit_text("🧾 Заметки", reply_markup=kb_notes_menu())
    await call.answer()


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
    rtype = call.data.split(":")[-1]
    await state.update_data(rtype=rtype)
    await state.set_state(Notes.reminder_time)
    await call.message.edit_text(
        "Введи время напоминания в формате HH:MM (например 09:30):",
        reply_markup=kb_back_to_menu()
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
    rtype = data.get("rtype", "daily")

    # MVP: weekly/monthly без доп. параметров — отправляем “как daily”.
    # (расширишь: weekday / monthday)
    async with session_scope() as session:
        q = await session.execute(select(Note).where(Note.id == note_id))
        note = q.scalar_one_or_none()
        if not note:
            await state.set_state(Main.menu)
            return await message.answer("Заметка не найдена.", reply_markup=kb_back_to_menu())

        rem = NoteReminder(note_id=note_id, rtype=rtype, remind_time=t, enabled=True)
        session.add(rem)
        await session.commit()

    await state.set_state(Notes.menu)
    await message.answer("⏰ Напоминание сохранено.", reply_markup=kb_notes_menu())


@router.callback_query(F.data == "notes:list")
async def cb_notes_list(call: CallbackQuery, state: FSMContext):
    u = await get_or_create_user(call.from_user.id, call.from_user.username, call.from_user.full_name)

    async with session_scope() as session:
        q = await session.execute(
            select(Note).options(selectinload(Note.reminders)).where(Note.owner_id == u.id, Note.status == "active")
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
        q = await session.execute(select(Note).options(selectinload(Note.reminders)).where(Note.id == note_id))
        n = q.scalar_one()

    rem = ""
    if n.reminder and n.reminder.enabled:
        rem = f"\n⏰ Напоминание: {n.reminder.rtype} в {n.reminder.remind_time.strftime('%H:%M')}"
    text = f"🧾 Заметка #{n.id}\nНазвание: {n.title}\n\n{n.description or ''}{rem}"
    await message.answer(text, reply_markup=kb_notes_menu())


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
        q = await session.execute(select(Note).where(Note.id == note_id, Note.owner_id == u.id, Note.status == "active"))
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
    async with session_scope() as session:
        session.add(NoteComment(note_id=note_id, author_tg_id=message.from_user.id, text=text))
        await session.commit()

    await state.set_state(Notes.menu)
    await message.answer("💬 Комментарий добавлен.", reply_markup=kb_notes_menu())


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
        q = await session.execute(select(Note).where(Note.id == note_id, Note.owner_id == u.id, Note.status == "active"))
        n = q.scalar_one_or_none()
        if not n:
            return await message.answer("Не нашёл активную заметку с таким номером.")
        n.status = "closed"
        n.closed_at = datetime.utcnow()
        await session.commit()

    await state.set_state(Notes.menu)
    await message.answer("✅ Заметка завершена.", reply_markup=kb_notes_menu())
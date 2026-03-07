from __future__ import annotations

from datetime import datetime, time as dtime

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.models import User, Note, NoteComment, NoteReminder, ScheduleType
from src.bot_metalead.states.tasks import Notes
from src.bot_metalead.keyboards.notes_keyboards import (
    kb_notes_menu,
    kb_yes_no_back,
    kb_reminder_types,
    kb_back_menu_notes,
    kb_notes_list_paginated,
    kb_note_view,
)

router = Router()


SCHEDULE_TYPE_LABELS = {
    ScheduleType.daily: "ежедневно",
    ScheduleType.weekly: "еженедельно",
    ScheduleType.monthly: "ежемесячно",
}


@router.callback_query(F.data == "notes:back")
async def cb_notes_back(call: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()

    back_map = {
        Notes.create_body.state: Notes.create_title,
        Notes.create_reminder_ask.state: Notes.create_body,
        Notes.reminder_type.state: Notes.create_reminder_ask,
        Notes.reminder_time.state: Notes.reminder_type,

        Notes.edit_body.state: Notes.edit_title,
    }

    prev_state = back_map.get(current_state)
    if not prev_state:
        await state.set_state(Notes.menu)
        await call.message.edit_text("🧾 Заметки", reply_markup=kb_notes_menu())
        await call.answer()
        return

    await state.set_state(prev_state)

    if prev_state == Notes.create_title:
        await call.message.edit_text(
            "➕ Создание заметки\n\nВведи название:",
            reply_markup=kb_back_menu_notes()
        )
    elif prev_state == Notes.create_body:
        await call.message.edit_text(
            "Теперь введи описание (можно коротко):",
            reply_markup=kb_back_menu_notes()
        )
    elif prev_state == Notes.create_reminder_ask:
        await call.message.edit_text(
            "Добавить напоминание для этой заметки?",
            reply_markup=kb_yes_no_back("notes:remind")
        )
    elif prev_state == Notes.reminder_type:
        await call.message.edit_text(
            "Выбери тип напоминания:",
            reply_markup=kb_reminder_types()
        )
    elif prev_state == Notes.edit_title:
        data = await state.get_data()
        note_id = data.get("note_id")
        await call.message.edit_text(
            f"✏️ Редактирование заметки #{note_id}\n\nВведи новое название:",
            reply_markup=kb_back_menu_notes()
        )

    await call.answer()


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
    await state.clear()
    await state.set_state(Notes.menu)
    await call.message.edit_text("🧾 Заметки", reply_markup=kb_notes_menu())
    await call.answer()


@router.callback_query(F.data == "notes:create")
async def cb_notes_create(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Notes.create_title)
    await call.message.edit_text(
        "➕ Создание заметки\n\nВведи название:",
        reply_markup=kb_back_menu_notes()
    )
    await call.answer()


@router.message(Notes.create_title)
async def msg_notes_title(message: Message, state: FSMContext):
    title = (message.text or "").strip()
    if not title:
        return await message.answer(
            "Название не может быть пустым. Введи ещё раз.",
            reply_markup=kb_back_menu_notes()
        )

    await state.update_data(title=title)
    await state.set_state(Notes.create_body)
    await message.answer(
        "Теперь введи описание (можно коротко):",
        reply_markup=kb_back_menu_notes()
    )


@router.message(Notes.create_body)
async def msg_notes_body(message: Message, state: FSMContext):
    description = (message.text or "").strip()

    await state.update_data(description=description)
    await state.set_state(Notes.create_reminder_ask)
    await message.answer(
        "Добавить напоминание для этой заметки?",
        reply_markup=kb_yes_no_back("notes:remind")
    )


@router.callback_query(F.data.in_(["notes:remind:yes", "notes:remind:no"]))
async def cb_notes_remind_ask(call: CallbackQuery, state: FSMContext):
    if call.data.endswith(":no"):
        data = await state.get_data()
        u = await get_or_create_user(
            call.from_user.id,
            call.from_user.username,
            call.from_user.full_name
        )

        async with session_scope() as session:
            note = Note(
                owner_id=u.id,
                title=data["title"],
                description=data.get("description", "")
            )
            session.add(note)
            await session.commit()

        await state.clear()
        await state.set_state(Notes.menu)
        await call.message.edit_text(
            "✅ Заметка создана без напоминания.",
            reply_markup=kb_notes_menu()
        )
        return await call.answer()

    await state.set_state(Notes.reminder_type)
    await call.message.edit_text(
        "Выбери тип напоминания:",
        reply_markup=kb_reminder_types()
    )
    await call.answer()


@router.callback_query(F.data.startswith("notes:rtype:"))
async def cb_notes_reminder_type(call: CallbackQuery, state: FSMContext):
    rtype = call.data.split(":")[-1]
    await state.update_data(rtype=rtype)
    await state.set_state(Notes.reminder_time)
    await call.message.edit_text(
        "Введи время напоминания в формате HH:MM (например 09:30):",
        reply_markup=kb_back_menu_notes()
    )
    await call.answer()


@router.message(Notes.reminder_time)
async def msg_notes_reminder_time(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    try:
        hh, mm = raw.split(":")
        hour = int(hh)
        minute = int(mm)
        dtime(hour=hour, minute=minute)
    except Exception:
        return await message.answer(
            "Неверный формат. Нужно HH:MM, например 09:30.",
            reply_markup=kb_back_menu_notes()
        )

    data = await state.get_data()
    rtype = data.get("rtype", "daily")

    u = await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name
    )

    async with session_scope() as session:
        note = Note(
            owner_id=u.id,
            title=data["title"],
            description=data.get("description", "")
        )
        session.add(note)
        await session.flush()

        rem = NoteReminder(
            note_id=note.id,
            schedule_type=ScheduleType(rtype),
            hour=hour,
            minute=minute,
            is_enabled=True,
        )
        session.add(rem)
        await session.commit()

    await state.clear()
    await state.set_state(Notes.menu)
    await message.answer("⏰ Заметка и напоминание сохранены.", reply_markup=kb_notes_menu())


@router.callback_query(F.data.startswith("notes:comment:"))
async def cb_note_comment(call: CallbackQuery, state: FSMContext):
    note_id = int(call.data.split(":")[-1])
    await state.update_data(note_id=note_id)
    await state.set_state(Notes.comment_text)
    await call.message.edit_text(
        "💬 Напиши комментарий:",
        reply_markup=kb_note_view(note_id)
    )
    await call.answer()


@router.message(Notes.comment_choose)
async def msg_note_comment_choose(message: Message, state: FSMContext):
    if not message.text or not message.text.strip().isdigit():
        return await message.answer("Введи номер заметки цифрами.")

    note_id = int(message.text.strip())
    u = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)

    async with session_scope() as session:
        q = await session.execute(
            select(Note).where(Note.id == note_id, Note.owner_id == u.id, Note.status == "active")
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
    u = await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name
    )

    async with session_scope() as session:
        session.add(
            NoteComment(
                note_id=note_id,
                author_id=u.id,
                text=text
            )
        )
        await session.commit()

    await state.clear()
    await state.set_state(Notes.menu)
    await message.answer("💬 Комментарий добавлен.", reply_markup=kb_notes_menu())



@router.callback_query(F.data.startswith("notes:close:"))
async def cb_note_close(call: CallbackQuery, state: FSMContext):
    note_id = int(call.data.split(":")[-1])

    u = await get_or_create_user(call.from_user.id, call.from_user.username, call.from_user.full_name)
    async with session_scope() as session:
        q = await session.execute(
            select(Note).where(Note.id == note_id, Note.owner_id == u.id, Note.status == "active")
        )
        n = q.scalar_one_or_none()
        if not n:
            await call.answer("Заметка не найдена или уже закрыта", show_alert=True)
            return

        n.status = "done"
        n.closed_at = datetime.utcnow()
        await session.commit()

    await state.set_state(Notes.menu)
    await call.message.edit_text("✅ Заметка завершена.", reply_markup=kb_notes_menu())
    await call.answer()


@router.callback_query(F.data == "notes:list")
async def cb_notes_list(call: CallbackQuery, state: FSMContext):
    u = await get_or_create_user(call.from_user.id, call.from_user.username, call.from_user.full_name)

    async with session_scope() as session:
        q = await session.execute(
            select(Note)
            .options(selectinload(Note.reminders))
            .where(Note.owner_id == u.id, Note.status == "active")
            .order_by(Note.created_at.desc())
        )
        notes = q.scalars().all()

    if not notes:
        await call.message.edit_text("📋 Активных заметок нет.", reply_markup=kb_notes_menu())
        return await call.answer()

    await state.update_data(note_ids=[n.id for n in notes], notes_page=0)

    await call.message.edit_text(
        "📋 Мои заметки:\n\nВыбери заметку кнопкой ниже:",
        reply_markup=kb_notes_list_paginated(notes, page=0, page_size=5)
    )
    await call.answer()


@router.callback_query(F.data.startswith("notes:list:page:"))
async def cb_notes_list_page(call: CallbackQuery, state: FSMContext):
    page = int(call.data.split(":")[-1])
    u = await get_or_create_user(call.from_user.id, call.from_user.username, call.from_user.full_name)

    async with session_scope() as session:
        q = await session.execute(
            select(Note)
            .options(selectinload(Note.reminders))
            .where(Note.owner_id == u.id, Note.status == "active")
            .order_by(Note.created_at.desc())
        )
        notes = q.scalars().all()

    if not notes:
        await state.set_state(Notes.menu)
        await call.message.edit_text("📋 Активных заметок нет.", reply_markup=kb_notes_menu())
        return await call.answer()

    await state.update_data(notes_page=page, note_ids=[n.id for n in notes])

    await call.message.edit_text(
        f"📋 Мои заметки:\n\nСтраница {page + 1}\nВыбери заметку кнопкой ниже:",
        reply_markup=kb_notes_list_paginated(notes, page=page, page_size=5)
    )
    await call.answer()


@router.callback_query(F.data.startswith("notes:open:"))
async def cb_note_open(call: CallbackQuery, state: FSMContext):
    note_id = int(call.data.split(":")[-1])
    u = await get_or_create_user(call.from_user.id, call.from_user.username, call.from_user.full_name)

    async with session_scope() as session:
        q = await session.execute(
            select(Note)
            .options(
                selectinload(Note.reminders),
                selectinload(Note.comments).selectinload(NoteComment.author),
            )
            .where(Note.id == note_id, Note.owner_id == u.id)
        )
        n = q.scalar_one_or_none()

    if not n:
        await call.answer("Заметка не найдена", show_alert=True)
        return

    rem = ""
    if n.reminders:
        active_reminder = next((r for r in n.reminders if r.is_enabled), None)
        if active_reminder:
            label = SCHEDULE_TYPE_LABELS.get(
                active_reminder.schedule_type,
                active_reminder.schedule_type.value
            )
            rem = (
                f"\n⏰ Напоминание: {label} "
                f"в {active_reminder.hour:02d}:{active_reminder.minute:02d}"
            )

    comments_block = "\n\n💬 Комментарии:\n"
    if n.comments:
        comments_lines = []
        for c in n.comments:
            author_name = c.author.full_name or c.author.username or f"id {c.author_id}"
            comments_lines.append(
                f"• {author_name} ({c.created_at.strftime('%d.%m %H:%M')})\n{c.text}"
            )
        comments_block += "\n\n".join(comments_lines)
    else:
        comments_block += "\nПока нет комментариев."

    text = (
        f"🧾 Заметка #{n.id}\n"
        f"Название: {n.title}\n\n"
        f"{n.description or ''}"
        f"{rem}"
        f"{comments_block}"
    )

    await call.message.edit_text(text, reply_markup=kb_note_view(n.id))
    await call.answer()


@router.callback_query(F.data.startswith("notes:edit:"))
async def cb_note_edit(call: CallbackQuery, state: FSMContext):
    note_id = int(call.data.split(":")[-1])

    u = await get_or_create_user(
        call.from_user.id,
        call.from_user.username,
        call.from_user.full_name
    )

    async with session_scope() as session:
        q = await session.execute(
            select(Note).where(
                Note.id == note_id,
                Note.owner_id == u.id,
                Note.status == "active"
            )
        )
        note = q.scalar_one_or_none()

    if not note:
        await call.answer("Заметка не найдена или уже закрыта", show_alert=True)
        return

    await state.clear()
    await state.update_data(note_id=note_id)
    await state.set_state(Notes.edit_title)

    await call.message.edit_text(
        f"✏️ Редактирование заметки #{note.id}\n\n"
        f"Текущее название: {note.title}\n\n"
        f"Введи новое название:",
        reply_markup=kb_back_menu_notes()
    )
    await call.answer()

@router.message(Notes.edit_title)
async def msg_note_edit_title(message: Message, state: FSMContext):
    title = (message.text or "").strip()
    if not title:
        return await message.answer(
            "Название не может быть пустым. Введи новое название ещё раз.",
            reply_markup=kb_back_menu_notes()
        )

    await state.update_data(new_title=title)
    await state.set_state(Notes.edit_body)

    await message.answer(
        "Введи новое описание:",
        reply_markup=kb_back_menu_notes()
    )

@router.message(Notes.edit_body)
async def msg_note_edit_body(message: Message, state: FSMContext):
    description = (message.text or "").strip()
    data = await state.get_data()
    note_id = data["note_id"]
    new_title = data["new_title"]

    u = await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name
    )

    async with session_scope() as session:
        q = await session.execute(
            select(Note).where(
                Note.id == note_id,
                Note.owner_id == u.id,
                Note.status == "active"
            )
        )
        note = q.scalar_one_or_none()

        if not note:
            await state.clear()
            await state.set_state(Notes.menu)
            return await message.answer("Заметка не найдена.", reply_markup=kb_notes_menu())

        note.title = new_title
        note.description = description
        await session.commit()

    await state.clear()
    await state.set_state(Notes.menu)
    await message.answer("✅ Заметка обновлена.", reply_markup=kb_notes_menu())
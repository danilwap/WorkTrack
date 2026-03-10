from __future__ import annotations

from datetime import datetime, timedelta, UTC

from typing import Optional

from aiogram import Bot
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext

from sqlalchemy import and_, select, func
from sqlalchemy.orm import selectinload

from src.bot_metalead.filters.is_manager import IsManager
from src.bot_metalead.services.tasks_notifications import notify_assignee, notify_user_tg
from src.bot_metalead.db.repositories.tasks_repo import get_employees, load_task, fetch_task_comments
from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.repositories.users_repo import ensure_user, is_manager
from src.bot_metalead.utils.manager_tasks import render_tasks_table, _short, _fmt_dt
from src.bot_metalead.utils.wizard_logic import wizard_add_extra, wizard_show_from_message, wizard_show_from_callback, \
    wizard_clear
from src.bot_metalead.db.models import (
    UserRole,
    Task, TaskStatus, TaskPriority,
    TaskReminder, ReminderType,
    TaskApproval, ApprovalDecision, TaskComment, User
)
from src.bot_metalead.keyboards.all_keyboards import kb_back_to_menu
from sqlalchemy.orm import aliased
from src.bot_metalead.utils.text import clamp, split_for_tg, fmt_task
from src.bot_metalead.states.manager_tasks import ManagerTasks

from src.bot_metalead.keyboards.manager_tasks import (
    kb_tasks_filters,
    kb_priority_pick,
    kb_task_open_manager,
    kb_task_card,
    kb_remind_when,
    kb_edit_fields,
    kb_yes_no,
    kb_task_comments,
    kb_comment_full, kb_tasks_pick, kb_employees_pick
)

from aiogram import Router

from src.bot_metalead.routers.manager.manager_tasks_create_task import router as manager_tasks_create_task_router
from src.bot_metalead.routers.manager.manager_tasks_list import router as manager_tasks_list
from src.bot_metalead.routers.manager.manager_tasks_card import router as manager_tasks_card
from src.bot_metalead.routers.manager.manager_tasks_edit import router as manager_tasks_edit
from src.bot_metalead.routers.manager.manager_tasks_workflow import router as manager_tasks_workflow
from src.bot_metalead.routers.manager.manager_tasks_stats import router as manager_tasks_stats
from src.bot_metalead.keyboards.user_tasks import kb_task_open_user



router = Router()

router.include_router(manager_tasks_create_task_router)
router.include_router(manager_tasks_list)
router.include_router(manager_tasks_card)
router.include_router(manager_tasks_edit)
router.include_router(manager_tasks_workflow)
router.include_router(manager_tasks_stats)









# ============================================================
# task actions: comments (add / list / full)
# ============================================================

@router.callback_query(F.data.startswith("mtask:comment:"), IsManager())
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


@router.message(ManagerTasks.comment_text, IsManager())
async def msg_task_comment(message: Message, state: FSMContext, bot: Bot):
    text = (message.text or "").strip()
    if not text:
        return await message.answer("Комментарий не может быть пустым.")

    task_id = (await state.get_data()).get("task_id")
    if not task_id:
        await state.set_state(ManagerTasks.menu)
        return await message.answer("Контекст задачи потерян. Открой задачу заново.")

    async with session_scope() as session:
        manager = await ensure_user(session, message.from_user)

        t = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not t:
            await state.set_state(ManagerTasks.menu)
            return await message.answer("Задача не найдена.")

        session.add(TaskComment(task_id=task_id, author_id=manager.id, text=text))
        await session.commit()

    notify_text = (
        f"💬 Новый комментарий от менеджера\n"
        f"Задача #{task_id}: {t.title}\n\n"
        f"{text}"
    )
    await notify_assignee(bot, task_id, notify_text, reply_markup=kb_task_open_user(task_id))

    await state.set_state(ManagerTasks.menu)

    await wizard_show_from_message(
        message,
        state,
        "✅ Комментарий добавлен.",
        reply_markup=kb_task_open_manager(task_id),
        delete_previous=True,
    )
    await wizard_clear(message, state)


@router.callback_query(F.data.startswith("mtask:comments:"), IsManager())
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


@router.callback_query(F.data.startswith("mtask:commentfull:"), IsManager())
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



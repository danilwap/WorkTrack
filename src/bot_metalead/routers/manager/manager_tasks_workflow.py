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

from src.bot_metalead.keyboards.user_tasks import kb_task_open_user

router = Router()



@router.callback_query(F.data.startswith("mtask:approve:"), IsManager())
async def cb_task_approve(call: CallbackQuery, state: FSMContext, bot: Bot):
    task_id = int(call.data.split(":")[-1])

    async with session_scope() as session:
        manager = await ensure_user(session, call.from_user)
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
        reply_markup=kb_task_open_user(task_id),
    )

    await wizard_show_from_callback(
        call,
        state,
        "✅ Апрув: задача завершена.",
        reply_markup=kb_task_open_manager(task_id),
    )
    await wizard_clear(call, state)


@router.callback_query(F.data.startswith("mtask:reject:"), IsManager())
async def cb_task_reject(call: CallbackQuery, state: FSMContext, bot: Bot):
    task_id = int(call.data.split(":")[-1])

    async with session_scope() as session:
        manager = await ensure_user(session, call.from_user)
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
        reply_markup=kb_task_open_user(task_id),
    )

    await call.message.edit_text("❌ Отклонено: задача переведена в rejected.",
                                 reply_markup=kb_task_open_manager(task_id))
    await call.answer()


# ============================================================
# task actions: cancel
# ============================================================

@router.callback_query(F.data.startswith("mtask:cancel:"), IsManager())
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


@router.callback_query(F.data.startswith("mtask:cancelconfirm:"), IsManager())
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
    F.data.startswith("mtask:cancelcomment:"),
    IsManager()
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

            manager = await ensure_user(session, call.from_user)

            session.add(
                TaskComment(
                    task_id=task_id,
                    author_id=manager.id,
                    text="Отменена администратором бота"
                )
            )

            t.status = TaskStatus.cancelled
            await session.commit()

        await notify_assignee(
            bot,
            task_id,
            f"🗑 Менеджер отменил задачу #{task_id}.",
            reply_markup=kb_task_open_user(task_id),
        )

        await state.clear()

        await call.message.edit_text(
            "🗑 Задача отменена (cancelled).",
            reply_markup=kb_task_open_manager(task_id)
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
                text=f"Закрыто администратором бота, комментарий: {text}"
            )
        )
        t.status = TaskStatus.cancelled
        await session.commit()

    await notify_assignee(
        bot,
        task_id,
        f"🗑 Менеджер отменил задачу #{task_id}.\nКомментарий:\n{text}",
        reply_markup=kb_task_open_user(task_id),
    )

    await state.set_state(ManagerTasks.menu)

    await wizard_show_from_message(
        message,
        state,
        "🗑 Задача отменена (cancelled).",
        reply_markup=kb_task_open_manager(task_id),
        delete_previous=True,
    )
    await wizard_clear(state)
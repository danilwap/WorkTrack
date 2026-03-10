from __future__ import annotations
from aiogram import Bot
from aiogram import Router, F

from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from src.bot_metalead.keyboards.manager_tasks import kb_yes_no_back_menu, kb_yes_no_cancel_task
from src.bot_metalead.filters.is_manager import IsManager
from src.bot_metalead.services.tasks_notifications import notify_assignee
from src.bot_metalead.db.repositories.tasks_repo import approve_task, \
    reject_task_by_manager, get_task_by_id, is_task_closed, cancel_task_by_manager
from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.repositories.users_repo import ensure_user, is_manager
from src.bot_metalead.utils.wizard_logic import wizard_show_from_message, wizard_show_from_callback

from src.bot_metalead.db.models import (TaskStatus, TaskComment)
from src.bot_metalead.keyboards.all_keyboards import kb_back_to_menu
from src.bot_metalead.utils.text import fmt_task
from src.bot_metalead.states.manager_tasks import ManagerTasks
from src.bot_metalead.keyboards.manager_tasks import (kb_task_open_manager, kb_task_card)

from src.bot_metalead.keyboards.user_tasks import kb_task_open_user

router = Router()


# Обработка принятие задачи
@router.callback_query(F.data.startswith("mtask:approve:"), IsManager())
async def cb_task_approve(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        task_id = int(call.data.split(":")[-1])
    except (ValueError, IndexError):
        await call.answer("Некорректные данные кнопки.", show_alert=True)
        return

    async with session_scope() as session:
        manager = await ensure_user(session, call.from_user)

        task, error = await approve_task(
            session=session,
            task_id=task_id,
            manager_id=manager.id,
        )

    if error == "not_found":
        await call.answer("Задача не найдена", show_alert=True)
        return

    if error == "wrong_status":
        await call.answer("Задача не на ревью", show_alert=True)
        return

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
    await state.clear()


# Обработка отправки задачи на доработку
@router.callback_query(F.data.startswith("mtask:reject:"), IsManager())
async def cb_task_reject(call: CallbackQuery, state: FSMContext):
    try:
        task_id = int(call.data.split(":")[-1])
    except (ValueError, IndexError):
        await call.answer("Некорректные данные кнопки.", show_alert=True)
        return

    async with session_scope() as session:
        task = await get_task_by_id(session=session, task_id=task_id)

    if not task:
        await call.answer("Задача не найдена", show_alert=True)
        return

    if task.status != TaskStatus.on_review:
        await call.answer("Задача уже не находится на проверке.", show_alert=True)
        return

    await state.update_data(task_id=task_id)
    await state.set_state(ManagerTasks.reject_comment_ask)

    await wizard_show_from_callback(
        call,
        state,
        "❌ Вернуть задачу на доработку.\n\nДобавить комментарий исполнителю?",
        reply_markup=kb_yes_no_back_menu(
            yes_data=f"mtask:rejectcomment:{task_id}:yes",
            no_data=f"mtask:rejectcomment:{task_id}:no",
            back_data=f"mtask:open:{task_id}",
        ),
    )
    await call.answer()


# Комментарий для возврата на доработку
@router.callback_query(
    ManagerTasks.reject_comment_ask,
    F.data.startswith("mtask:rejectcomment:"),
    IsManager()
)
async def cb_task_reject_comment_decision(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        _, _, task_id_s, decision = call.data.split(":")
        task_id = int(task_id_s)
    except (ValueError, IndexError):
        await call.answer("Некорректные данные кнопки.", show_alert=True)
        return

    if decision == "no":
        async with session_scope() as session:
            manager = await ensure_user(session, call.from_user)

            task, error = await reject_task_by_manager(
                session=session,
                task_id=task_id,
                manager_id=manager.id,
            )

        if error == "not_found":
            await state.clear()
            await call.answer("Задача не найдена", show_alert=True)
            return

        if error == "wrong_status":
            await state.clear()
            await call.answer("Задача уже не находится на проверке.", show_alert=True)
            return

        await notify_assignee(
            bot,
            task_id,
            f"❌ Менеджер вернул задачу #{task_id} на доработку.",
            reply_markup=kb_task_open_user(task_id),
        )

        await wizard_show_from_callback(
            call,
            state,
            "❌ Задача возвращена на доработку.",
            reply_markup=kb_task_open_manager(task_id),
        )
        await state.clear()
        await call.answer()
        return

    if decision == "yes":
        await state.update_data(task_id=task_id)
        await state.set_state(ManagerTasks.reject_comment_text)

        await wizard_show_from_callback(
            call,
            state,
            "✍️ Напиши комментарий для исполнителя:",
            reply_markup=kb_back_to_menu(),
        )
        await call.answer()
        return

    await call.answer("Неизвестное действие.", show_alert=True)


# Обработка комментария для доработки
@router.message(ManagerTasks.reject_comment_text)
async def msg_task_reject_comment_text(message: Message, state: FSMContext, bot: Bot):
    text = (message.text or "").strip()
    if not text:
        await message.answer("Комментарий не может быть пустым.")
        return

    data = await state.get_data()
    task_id = data.get("task_id")
    if not task_id:
        await state.clear()
        await message.answer("Контекст задачи потерян. Открой задачу заново.")
        return

    async with session_scope() as session:
        manager = await ensure_user(session, message.from_user)

        task, error = await reject_task_by_manager(
            session=session,
            task_id=task_id,
            manager_id=manager.id,
        )

        if error == "not_found":
            await state.clear()
            await message.answer("Задача не найдена.")
            return

        if error == "wrong_status":
            await state.clear()
            await message.answer("Задача уже не находится на проверке.")
            return

        session.add(
            TaskComment(
                task_id=task_id,
                author_id=manager.id,
                text=text,
            )
        )
        await session.commit()

    await notify_assignee(
        bot,
        task_id,
        f"❌ Менеджер вернул задачу #{task_id} на доработку.\n\n"
        f"Последний комментарий:\n{text}",
        reply_markup=kb_task_open_user(task_id),
    )

    await wizard_show_from_message(
        message,
        state,
        "❌ Задача возвращена на доработку. Комментарий сохранён.",
        reply_markup=kb_task_open_manager(task_id),
        delete_previous=True,
    )
    await state.clear()


# Отмена задачи
@router.callback_query(F.data.startswith("mtask:cancel:"), IsManager())
async def cb_task_cancel(call: CallbackQuery, state: FSMContext):
    try:
        task_id = int(call.data.split(":")[-1])
    except (ValueError, IndexError):
        await call.answer("Некорректные данные кнопки.", show_alert=True)
        return

    async with session_scope() as session:
        t = await get_task_by_id(session=session, task_id=task_id)

    if not t:
        await call.answer("Задача не найдена", show_alert=True)
        return

    if is_task_closed(t):
        await state.clear()
        await wizard_show_from_callback(
            call,
            state,
            "️ Задача уже закрыта.",
            reply_markup=kb_back_to_menu(),
        )
        await call.answer()
        return

    await state.update_data(task_id=task_id)
    await wizard_show_from_callback(
        call,
        state,
        "️🗑 Отменить задачу?",
        reply_markup=kb_yes_no_cancel_task(
            prefix=f"mtask:cancelconfirm:{task_id}",
            prefix_command="mtask:open",
            task_id=task_id
        ),
    )
    await call.answer()


# Добавляем или нет комментарий к отменённой задаче
@router.callback_query(F.data.startswith("mtask:cancelconfirm:"), IsManager())
async def cb_task_cancel_confirm(call: CallbackQuery, state: FSMContext):
    try:
        parts = call.data.split(":")
        task_id = int(parts[2])
        decision = parts[3]
    except (ValueError, IndexError):
        await call.answer("Некорректные данные кнопки.", show_alert=True)
        return

    if decision == "no":
        async with session_scope() as session:
            t = await get_task_by_id(session=session, task_id=task_id)
        if not t:
            await call.answer("Задача не найдена", show_alert=True)
            return

        status = t.status.value if hasattr(t.status, "value") else str(t.status)

        await wizard_show_from_callback(
            call,
            state,
            fmt_task(t),
            reply_markup=kb_task_card(task_id, status)
        )
        await call.answer()
        return

    # YES → спрашиваем про комментарий
    await state.update_data(task_id=task_id)
    await state.set_state(ManagerTasks.cancel_comment_ask)

    await wizard_show_from_callback(
        call,
        state,
        "🗑 Задача будет отменена.\n\nДобавить комментарий?",
        reply_markup=kb_yes_no_cancel_task(
            prefix=f"mtask:cancelcomment:{task_id}",
            prefix_command="mtask:cancel",
            task_id=task_id
        ),
    )
    await call.answer()


@router.callback_query(
    ManagerTasks.cancel_comment_ask,
    F.data.startswith("mtask:cancelcomment:"),
    IsManager()
)
async def cb_task_cancel_comment(call: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        parts = call.data.split(":")
        task_id = int(parts[2])
        decision = parts[3]
    except (ValueError, IndexError):
        await call.answer("Некорректные данные кнопки.", show_alert=True)
        return

    if decision == "no":
        async with session_scope() as session:
            manager = await ensure_user(session, call.from_user)

            task, error = await cancel_task_by_manager(
                session=session,
                task_id=task_id,
                manager_id=manager.id,
            )

        if error == "not_found":
            await state.clear()
            await call.answer("Задача не найдена", show_alert=True)
            return

        if error == "already_cancelled":
            await state.clear()
            await call.answer("Задача уже отменена", show_alert=True)
            return

        if error == "already_closed":
            await state.clear()
            await call.answer("Задача уже закрыта", show_alert=True)
            return

        await notify_assignee(
            bot,
            task_id,
            f"🗑 Менеджер отменил задачу #{task_id}.",
            reply_markup=kb_task_open_user(task_id),
        )

        await wizard_show_from_callback(
            call,
            state,
            "🗑 Задача отменена.",
            reply_markup=kb_task_open_manager(task_id)
        )
        await state.clear()
        await call.answer()
        return

    await state.update_data(task_id=task_id)
    await state.set_state(ManagerTasks.cancel_comment_text)

    await wizard_show_from_callback(
        call,
        state,
        "✍️ Введите комментарий для Отмены задачи:"
    )
    await call.answer()


@router.message(ManagerTasks.cancel_comment_text)
async def msg_task_cancel_comment_text(message: Message, state: FSMContext, bot: Bot):
    text = (message.text or "").strip()
    if not text:
        await message.answer("Комментарий не может быть пустым. Напиши текст или нажми меню/назад.",
                             reply_markup=kb_back_to_menu())
        return

    data = await state.get_data()
    task_id = data.get("task_id")
    if not task_id:
        await state.clear()
        await message.answer("Контекст потерян. Открой задачу заново.", reply_markup=kb_back_to_menu())
        return

    async with session_scope() as session:
        manager = await ensure_user(session, message.from_user)

        task, error = await cancel_task_by_manager(
            session=session,
            task_id=task_id,
            manager_id=manager.id,
            comment_text=text,
        )

    if error == "not_found":
        await state.clear()
        await message.answer("Задача не найдена.", reply_markup=kb_back_to_menu())
        return

    if error == "already_cancelled":
        await state.clear()
        await message.answer("Задача уже отменена.", reply_markup=kb_back_to_menu())
        return

    if error == "already_closed":
        await state.clear()
        await message.answer("Задача уже закрыта.", reply_markup=kb_back_to_menu())
        return

    await notify_assignee(
        bot,
        task_id,
        f"🗑 Менеджер отменил задачу #{task_id}.\nКомментарий:\n{text}",
        reply_markup=kb_task_open_user(task_id),
    )

    await wizard_show_from_message(
        message,
        state,
        "🗑 Задача отменена.",
        reply_markup=kb_task_open_manager(task_id),
        delete_previous=True,
    )
    await state.clear()

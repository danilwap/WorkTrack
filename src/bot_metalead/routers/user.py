from __future__ import annotations

from datetime import datetime

from aiogram import Bot
from aiogram.types import  Message

from src.bot_metalead.db.repositories.users_repo import ensure_user, get_user_tg_id_by_id
from src.bot_metalead.db.repositories.comments_repo import add_comment_to_assignee_task
from src.bot_metalead.db.repositories.tasks_repo import get_active_tasks_by_assignee, \
    get_active_task_for_assignee_with_details, is_active_task_for_assignee, get_task_for_done_by_assignee

from src.bot_metalead.keyboards.manager_tasks import kb_task_open_manager
from src.bot_metalead.keyboards.user_tasks import kb_task_open_user
from src.bot_metalead.routers.manager.manager_tasks import (
    wizard_show_from_callback, _fmt_dt,

)
from src.bot_metalead.keyboards.user_tasks import kb_user_tasks_pick, kb_user_task_open
from src.bot_metalead.states.tasks import Tasks
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext


from src.bot_metalead.db.models import TaskStatus
from src.bot_metalead.db.session import session_scope
from src.bot_metalead.keyboards.all_keyboards import kb_back_to_menu
from src.bot_metalead.services.tasks_notifications import notify_task_creator_on_employee_comment
from src.bot_metalead.utils.text import fmt_task

router = Router()


# -------------------------
# ✅ Мои активные задачи
# -------------------------
@router.callback_query(F.data == "tasks:active")
async def cb_tasks_active(call: CallbackQuery, state: FSMContext):
    async with session_scope() as session:
        user = await ensure_user(session, call.from_user)
        tasks = await get_active_tasks_by_assignee(session, user.id, limit=50)

    if not tasks:
        await wizard_show_from_callback(
            call,
            state,
            "📋 Активных задач нет.",
            reply_markup=kb_back_to_menu(),
        )
        await call.answer()
        return


    await wizard_show_from_callback(
        call,
        state,
        "📋 Мои активные задачи (выбери по кнопке):",
        reply_markup=kb_user_tasks_pick(tasks, page=0),
    )
    await call.answer()


@router.callback_query(F.data.startswith("tasks:page:"))
async def cb_user_tasks_page(call: CallbackQuery, state: FSMContext):
    page = int(call.data.split(":")[-1])

    async with session_scope() as session:
        user = await ensure_user(session, call.from_user)
        tasks = await get_active_tasks_by_assignee(session, user.id, limit=50)

    if not tasks:
        await call.message.edit_text(
            "📋 У тебя пока нет задач.",
            reply_markup=kb_back_to_menu()
        )
        await call.answer()
        return

    await call.message.edit_text(
        "📋 Мои задачи:",
        reply_markup=kb_user_tasks_pick(tasks, page=page)
    )
    await call.answer()


@router.callback_query(F.data.startswith("task:open:"))
async def cb_user_task_open(call: CallbackQuery, state: FSMContext):
    try:
        task_id = int(call.data.split(":")[-1])
    except (ValueError, IndexError):
        await call.answer("Некорректные данные кнопки.", show_alert=True)
        return

    async with session_scope() as session:
        user = await ensure_user(session, call.from_user)

        task = await get_active_task_for_assignee_with_details(
            session=session,
            task_id=task_id,
            assignee_id=user.id,
        )

    if not task:
        await call.answer("Задача не найдена или недоступна", show_alert=True)
        return

    full_text = fmt_task(
        task,
        show_assignee=False,
        comments_limit=5,
        max_comment_len=500,
        max_total_len=3900,
    )

    await call.message.edit_text(
        full_text,
        reply_markup=kb_user_task_open(task.id)
    )
    await call.answer()



@router.callback_query(F.data.startswith("task:comment:"))
async def cb_user_task_comment(call: CallbackQuery, state: FSMContext):
    task_id = int(call.data.split(":")[-1])

    async with (session_scope() as session):
        me = await ensure_user(session, call.from_user)
        if not me:
            await call.answer("Пользователь не найден", show_alert=True)
            return

        exists_task = await get_active_task_for_assignee_with_details(
            session=session,
            task_id=task_id,
            assignee_id=me.id
        )

    if not exists_task:
        await call.answer("Задача не найдена или недоступна", show_alert=True)
        return

    await state.update_data(task_id=task_id)
    await state.set_state(Tasks.comment_enter_text)

    await call.message.edit_text(
        f"💬 Комментарий к задаче #{task_id}\n\nНапиши текст комментария:",
        reply_markup=kb_back_to_menu()
    )
    await call.answer()

@router.callback_query(F.data.startswith("task:done:"))
async def cb_user_task_done(call: CallbackQuery, state: FSMContext):
    task_id = int(call.data.split(":")[-1])

    async with session_scope() as session:
        me = await ensure_user(session, call.from_user)
        if not me:
            await call.answer("Пользователь не найден", show_alert=True)
            return

        task = await get_task_for_done_by_assignee(
            session=session,
            task_id=task_id,
            assignee_id=me.id,
        )

        if not task:
            await call.answer("Задача недоступна для завершения", show_alert=True)
            return

        task.status = TaskStatus.on_review
        await session.commit()

        creator_tg_id = None
        if task.creator_id:
            creator_tg_id = await get_user_tg_id_by_id(
                session=session,
                user_id=task.creator_id,
            )

    if creator_tg_id:
        try:
            await call.bot.send_message(
                creator_tg_id,
                (
                    f"✅ Исполнитель отправил задачу на подтверждение\n\n"
                    f"🧩 Задача #{task_id}: {task.title}\n"
                    f"👤 Исполнитель: {call.from_user.full_name}"
                ),
                reply_markup=kb_task_open_manager(task_id)
            )
        except Exception:
            pass

    await call.message.edit_text(
        f"✅ Задача #{task_id} отправлена руководителю на подтверждение.",
        reply_markup=kb_back_to_menu()
    )
    await call.answer()



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
        user = await ensure_user(session, message.from_user)

        ok = await add_comment_to_assignee_task(
            session=session,
            task_id=task_id,
            assignee_id=user.id,
            author_id=user.id,
            text=text,
        )

        if not ok:
            await state.clear()
            return await message.answer("Задача не найдена или больше не принадлежит тебе.")

        author_name = user.full_name or (f"@{user.username}" if user.username else str(user.tg_id))

    await notify_task_creator_on_employee_comment(
        bot=bot,
        task_id=task_id,
        author_name=author_name,
        comment_text=text,
        reply_markup=kb_task_open_user(task_id),
    )

    await state.clear()
    await message.answer("✅ Комментарий добавлен.", reply_markup=kb_back_to_menu())


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
        user = await ensure_user(session, message.from_user)

        # Проверяем: задача существует и назначена этому пользователю
        task = await is_active_task_for_assignee(
            session=session,
            task_id=task_id,
            assignee_id=user.id,
        )

    if not task:
        return await message.answer("Не нашёл активную задачу с таким номером (или она не твоя). Введи другой номер.")

    await state.update_data(task_id=task_id)
    await state.set_state(Tasks.comment_enter_text)
    await message.answer(
        f"🧩 Задача #{task_id}\n\nТеперь введи текст комментария:",
        reply_markup=kb_back_to_menu(),
    )
from __future__ import annotations

from datetime import datetime, time as dtime, timezone

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message

from db.repositories.users_repo import ensure_user
from src.bot_metalead.db.repositories.tasks_repo import get_active_tasks_by_assignee

from src.bot_metalead.keyboards.manager_tasks import kb_task_open, kb_tasks_pick
from src.bot_metalead.routers.manager_tasks import (
    wizard_show_from_callback, get_current_user_by_tg_id, _fmt_dt,

)
from src.bot_metalead.keyboards.user_tasks import kb_user_tasks_pick, kb_user_task_open
from src.bot_metalead.states.tasks import Tasks
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext



from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.bot_metalead.db.models import Task, TaskStatus, User
from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.models import (
    User,
    TaskComment,
)
from src.bot_metalead.keyboards.all_keyboards import kb_back_to_menu
from src.bot_metalead.services.tasks_notifications import notify_task_creator_on_employee_comment

router = Router()

TASKS_PICK_IDS = "tasks_pick_ids"
TASKS_PICK_PAGE = "tasks_pick_page"

ACTIVE_TASK_STATUSES = [
    TaskStatus.new,
    TaskStatus.in_progress,
    TaskStatus.on_review,
]


# -------------------------
# ✅ Мои активные задачи
# -------------------------
@router.callback_query(F.data == "tasks:active")
async def cb_tasks_active(call: CallbackQuery, state: FSMContext):
    async with session_scope() as session:
        user = await ensure_user(session, call.from_user.id)

        if not user:
            await call.answer("Пользователь не найден. Нажми /start", show_alert=True)
            return

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

    await state.update_data(**{
        TASKS_PICK_IDS: [t.id for t in tasks],
        TASKS_PICK_PAGE: 0,
    })

    await wizard_show_from_callback(
        call,
        state,
        "📋 Мои активные задачи (выбери по кнопке):",
        reply_markup=kb_user_tasks_pick(tasks, page=0),
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



@router.callback_query(F.data.startswith("tasks:page:"))
async def cb_user_tasks_page(call: CallbackQuery, state: FSMContext):
    page = int(call.data.split(":")[-1])

    async with session_scope() as session:
        me = await get_current_user_by_tg_id(session, call.from_user.id)
        if not me:
            await call.answer("Пользователь не найден", show_alert=True)
            return

        q = await session.execute(
            select(Task)
            .where(
                Task.assignee_id == me.id,
                Task.status.in_([
                    TaskStatus.new,
                    TaskStatus.in_progress,
                    TaskStatus.on_review,
                ])
            )
            .order_by(Task.created_at.desc())
        )
        tasks = q.scalars().all()

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
    task_id = int(call.data.split(":")[-1])

    async with session_scope() as session:
        me = await get_current_user_by_tg_id(session, call.from_user.id)
        if not me:
            await call.answer("Пользователь не найден", show_alert=True)
            return

        q = await session.execute(
            select(Task)
            .options(
                selectinload(Task.creator),
                selectinload(Task.assignee),
                selectinload(Task.comments).selectinload(TaskComment.author),
            )
            .where(
                Task.id == task_id,
                Task.assignee_id == me.id,
                Task.status.in_([
                    TaskStatus.new,
                    TaskStatus.in_progress,
                    TaskStatus.on_review,
                ])
            )
        )
        task = q.scalar_one_or_none()

    if not task:
        await call.answer("Задача не найдена или недоступна", show_alert=True)
        return

    comments_block = "\n\n💬 Комментарии:\n"
    if task.comments:
        comments_lines = []
        for c in task.comments[-5:]:
            author_name = c.author.full_name or c.author.username or f"id {c.author_id}"
            comments_lines.append(
                f"• {author_name} ({c.created_at.strftime('%d.%m %H:%M')})\n{c.text}"
            )
        comments_block += "\n\n".join(comments_lines)
    else:
        comments_block += "\nПока нет комментариев."

    creator_name = "—"
    if task.creator:
        creator_name = task.creator.full_name or task.creator.username or f"id {task.creator_id}"

    text = (
        f"🧩 Задача #{task.id}\n"
        f"Название: {task.title}\n"
        f"Статус: {task.status.value}\n"
        f"Дедлайн: {_fmt_dt(task.deadline_at)}\n"
        f"Постановщик: {creator_name}\n\n"
        f"{task.description or 'Описание отсутствует.'}"
        f"{comments_block}"
    )

    await call.message.edit_text(
        text,
        reply_markup=kb_user_task_open(task.id)
    )
    await call.answer()



@router.callback_query(F.data.startswith("task:comment:"))
async def cb_user_task_comment(call: CallbackQuery, state: FSMContext):
    task_id = int(call.data.split(":")[-1])

    async with session_scope() as session:
        me = await get_current_user_by_tg_id(session, call.from_user.id)
        if not me:
            await call.answer("Пользователь не найден", show_alert=True)
            return

        q = await session.execute(
            select(Task.id).where(
                Task.id == task_id,
                Task.assignee_id == me.id,
                Task.status.in_([
                    TaskStatus.new,
                    TaskStatus.in_progress,
                    TaskStatus.on_review,
                ])
            )
        )
        exists_task = q.scalar_one_or_none()

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
        me = await get_current_user_by_tg_id(session, call.from_user.id)
        if not me:
            await call.answer("Пользователь не найден", show_alert=True)
            return

        q = await session.execute(
            select(Task).where(
                Task.id == task_id,
                Task.assignee_id == me.id,
                Task.status.in_([TaskStatus.new, TaskStatus.in_progress])
            )
        )
        task = q.scalar_one_or_none()

        if not task:
            await call.answer("Задача недоступна для завершения", show_alert=True)
            return

        task.status = TaskStatus.on_review
        await session.commit()

        creator_tg_id = None
        if task.creator_id:
            q = await session.execute(select(User).where(User.id == task.creator_id))
            creator = q.scalar_one_or_none()
            if creator and creator.tg_id:
                creator_tg_id = creator.tg_id

    if creator_tg_id:
        try:
            await call.bot.send_message(
                creator_tg_id,
                (
                    f"✅ Исполнитель отправил задачу на подтверждение\n\n"
                    f"🧩 Задача #{task_id}: {task.title}\n"
                    f"👤 Исполнитель: {call.from_user.full_name}"
                ),
                reply_markup=kb_task_open(task_id)  # если у менеджера уже есть карточка
            )
        except Exception:
            pass

    await call.message.edit_text(
        f"✅ Задача #{task_id} отправлена руководителю на подтверждение.",
        reply_markup=kb_back_to_menu()
    )
    await call.answer()
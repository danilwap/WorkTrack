from __future__ import annotations

from aiogram import Router, F

from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from src.bot_metalead.filters.is_manager import IsManager

from src.bot_metalead.db.repositories.tasks_repo import load_task
from src.bot_metalead.utils.text import fmt_task

from src.bot_metalead.keyboards.manager_tasks import kb_task_card
from src.bot_metalead.utils.wizard_logic import wizard_show_from_callback

router = Router()


@router.callback_query(F.data.startswith("mtask:open:"), IsManager())
async def cb_task_open(call: CallbackQuery, state: FSMContext):
    try:
        task_id = int(call.data.split(":")[-1])
    except (ValueError, IndexError):
        await call.answer("Некорректные данные кнопки.", show_alert=True)
        return

    t = await load_task(task_id)
    if not t:
        await call.answer("Задача не найдена", show_alert=True)
        return

    text = fmt_task(
        t,
        show_assignee=True,
        comments_limit=5,
        max_comment_len=600,
        max_total_len=3900,
    )

    await state.update_data(task_id=task_id)
    await wizard_show_from_callback(
        call,
        state,
        text,
        reply_markup=kb_task_card(task_id, t.status.value),
    )
    await call.answer()

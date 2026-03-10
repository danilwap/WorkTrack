from aiogram.fsm.context import FSMContext
from aiogram import Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile

from src.bot_metalead.keyboards.manager_tasks import kb_task_open_manager
from src.bot_metalead.states.manager_tasks import ManagerTasks

WIZARD_KEY = "wizard_msg_id"
WIZARD_EXTRA_KEY = "wizard_extra_msg_ids"

async def wizard_add_extra(state: FSMContext, msg_id: int) -> None:
    data = await state.get_data()
    arr = list(data.get(WIZARD_EXTRA_KEY) or [])
    arr.append(msg_id)
    await state.update_data(**{WIZARD_EXTRA_KEY: arr})


async def wizard_delete_extras(bot: Bot, chat_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    arr = list(data.get(WIZARD_EXTRA_KEY) or [])
    for mid in arr:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass
    await state.update_data(**{WIZARD_EXTRA_KEY: []})


async def wizard_drop_markup(bot: Bot, chat_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    mid = data.get(WIZARD_KEY)
    if not mid:
        return
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=mid, reply_markup=None)
    except Exception:
        pass


async def wizard_clear(message_or_call, state: FSMContext) -> None:
    try:
        bot = message_or_call.bot
        chat_id = message_or_call.message.chat.id if hasattr(message_or_call,
                                                             "message") and message_or_call.message else message_or_call.chat.id
    except Exception:
        # если не смогли вытащить chat_id/bot — просто чистим ключ
        await state.update_data(**{WIZARD_KEY: None})
        return

    await wizard_drop_markup(bot, chat_id, state)
    await state.update_data(**{WIZARD_KEY: None})


async def wizard_show_from_callback(call: CallbackQuery, state: FSMContext, text: str, reply_markup=None) -> int:
    data = await state.get_data()
    old_id = data.get(WIZARD_KEY)

    # 1) пробуем редактировать текущий месседж (идеальный кейс)
    try:
        if call.message:
            msg = await call.message.edit_text(text, reply_markup=reply_markup)
            await state.update_data(**{WIZARD_KEY: msg.message_id})
            return msg.message_id
    except Exception:
        pass

    # 2) если редактировать нельзя — удаляем прошлый wizard-msg (если был)
    if old_id:
        try:
            await call.bot.delete_message(call.message.chat.id if call.message else call.from_user.id, old_id)
        except Exception:
            pass

    # 3) и отправляем новый
    msg = await call.bot.send_message(call.from_user.id, text, reply_markup=reply_markup)
    await state.update_data(**{WIZARD_KEY: msg.message_id})
    return msg.message_id


async def wizard_show_from_message(
        message: Message,
        state: FSMContext,
        text: str,
        reply_markup=None,
        delete_previous: bool = True,) -> int:
    """
    Показ шага из message-хендлера:
    - по умолчанию удаляем предыдущий wizard-месседж (чтобы нельзя было нажать старые кнопки)
    - отправляем новый шаг
    - сохраняем его message_id
    """
    data = await state.get_data()
    old_id = data.get(WIZARD_KEY)
    if delete_previous:
        await wizard_delete_extras(message.bot, message.chat.id, state)

    if delete_previous and old_id:
        try:
            await message.bot.delete_message(message.chat.id, old_id)
        except Exception:
            pass

    msg = await message.answer(text, reply_markup=reply_markup)
    await state.update_data(**{WIZARD_KEY: msg.message_id})
    return msg.message_id


async def finalize_created_task_from_message(
    message: Message,
    state: FSMContext,
    task_id: int,
    notification_sent: bool,
) -> None:
    await state.set_state(ManagerTasks.menu)

    await wizard_show_from_message(
        message,
        state,
        f"✅ Задача создана: #{task_id}",
        reply_markup=kb_task_open_manager(task_id),
        delete_previous=True,
    )

    if not notification_sent:
        await wizard_show_from_message(
            message,
            state,
            "⚠️ Не удалось отправить уведомление исполнителю. "
            "Скорее всего он ещё не нажимал /start у бота или заблокировал бота.",
            reply_markup=kb_task_open_manager(task_id),
            delete_previous=False,
        )
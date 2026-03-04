from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from sqlalchemy import select

from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.models import User
from src.bot_metalead.states.tasks import Main
from src.bot_metalead.keyboards.all_keyboards import kb_main_menu

router = Router()


async def upsert_user(tg_id: int, username: str | None, full_name: str | None) -> User:
    async with session_scope() as session:
        q = await session.execute(select(User).where(User.tg_id == tg_id))
        user = q.scalar_one_or_none()
        if user is None:
            user = User(tg_id=tg_id, username=username, full_name=full_name, role="employee")
            session.add(user)
        else:
            user.username = username
            user.full_name = full_name
        await session.commit()
        return user


@router.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    user = await upsert_user(
        tg_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name
    )
    await state.set_state(Main.menu)
    await message.answer(
        "🏠 Главное меню",
        reply_markup=kb_main_menu(role=user.role)
    )


@router.callback_query(F.data == "main:menu")
async def cb_main_menu(call: CallbackQuery, state: FSMContext):
    user = await upsert_user(
        tg_id=call.from_user.id,
        username=call.from_user.username,
        full_name=call.from_user.full_name
    )
    await state.set_state(Main.menu)
    await call.message.edit_text(
        "🏠 Главное меню",
        reply_markup=kb_main_menu(role=user.role)
    )
    await call.answer()
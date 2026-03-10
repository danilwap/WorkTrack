from __future__ import annotations


from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext


from src.bot_metalead.filters.is_manager import IsManager
from src.bot_metalead.db.repositories.tasks_repo import get_employees, \
    get_overdue_tasks, get_active_tasks_by_assignee, get_tasks_for_manager_filter, get_tasks_by_ids
from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.repositories.users_repo import get_user_by_id
from src.bot_metalead.utils.wizard_logic import wizard_show_from_message, wizard_show_from_callback

from src.bot_metalead.keyboards.all_keyboards import kb_back_to_menu
from src.bot_metalead.states.manager_tasks import ManagerTasks

from src.bot_metalead.keyboards.manager_tasks import (
    kb_tasks_filters,
    kb_tasks_pick, kb_employees_pick
)
from src.bot_metalead.utils.helpers import now_utc

EMP_PICK_IDS = "emp_pick_ids"
EMP_PICK_PAGE = "emp_pick_page"
TASKS_PICK_IDS = "tasks_pick_ids"
TASKS_PICK_PAGE = "tasks_pick_page"

TASKS_PICK_BACK_TEXT = "tasks_pick_back_text"
TASKS_PICK_BACK_CALLBACK = "tasks_pick_back_callback"

router = Router()


# Хелпер для выбора фильтра
async def show_tasks_list_start(event: Message | CallbackQuery, state: FSMContext, ):
    await state.set_state(ManagerTasks.list_pick_filter)

    if isinstance(event, Message):
        await wizard_show_from_message(
            event,
            state,
            "📋 Список задач — выбери фильтр:",
            reply_markup=kb_tasks_filters(),
            delete_previous=True,
        )
    else:
        await wizard_show_from_callback(
            event,
            state,
            "📋 Список задач — выбери фильтр:",
            reply_markup=kb_tasks_filters(),
        )
        await event.answer()


# Основное меню выбора фильтра задач 1
@router.message(Command("tasks"), IsManager())
async def cmd_tasks(message: Message, state: FSMContext):
    await show_tasks_list_start(message, state)


# Основное меню выбора фильтра задач 2
@router.callback_query(F.data == "mtasks:list", IsManager())
async def cb_mtasks_list(call: CallbackQuery, state: FSMContext):
    await show_tasks_list_start(call, state)


@router.callback_query(F.data.startswith("mtasks:employeepage:"), IsManager())
async def cb_employees_page(call: CallbackQuery, state: FSMContext):
    page = int(call.data.split(":")[-1])

    async with session_scope() as session:
        employees = await get_employees(session)

    if not employees:
        await wizard_show_from_callback(call, state, "Сотрудники (employee) не найдены.",
                                        reply_markup=kb_back_to_menu())
        await call.answer()
        return

    await state.update_data(**{EMP_PICK_IDS: [u.id for u in employees], EMP_PICK_PAGE: page})

    await wizard_show_from_callback(
        call,
        state,
        "👤 Выбери сотрудника:",
        reply_markup=kb_employees_pick(employees, page=page),
    )
    await call.answer()


@router.callback_query(F.data.startswith("mtasks:employee:"), IsManager())
async def cb_pick_employee(call: CallbackQuery, state: FSMContext):
    try:
        uid = int(call.data.split(":")[-1])
    except (ValueError, IndexError):
        await call.answer("Некорректные данные кнопки.", show_alert=True)
        return

    # грузим задачи сотрудника и показываем по кнопке
    async with session_scope() as session:
        tasks = await get_active_tasks_by_assignee(session, assignee_id=uid, limit=50)
        emp = await get_user_by_id(session, uid)

    if not tasks:
        name = "сотрудника"
        if emp:
            name = emp.full_name or (f"@{emp.username}" if emp.username else "сотрудника")

        await wizard_show_from_callback(
            call,
            state,
            f"У {name} пока нет задач.",
            reply_markup=kb_back_to_menu(),
        )
        await call.answer()
        return

    await state.update_data(**{
        TASKS_PICK_IDS: [t.id for t in tasks],
        TASKS_PICK_PAGE: 0,
        TASKS_PICK_BACK_TEXT: "⬅️ К сотрудникам",
        TASKS_PICK_BACK_CALLBACK: "mtasks:employeepage:0",
    })

    await wizard_show_from_callback(
        call,
        state,
        "📋 Задачи сотрудника (выбери по кнопке):",
        reply_markup=kb_tasks_pick(tasks, page=0, back_text="⬅️ К сотрудникам",
                                   back_callback="mtasks:employeepage:0", ),
    )
    await call.answer()


@router.callback_query(ManagerTasks.list_pick_filter, F.data.startswith("mtasks:filter:"), IsManager())
async def cb_tasks_pick_filter(call: CallbackQuery, state: FSMContext):
    flt = call.data.split(":")[-1]

    if flt == "by_employee":
        async with session_scope() as session:
            employees = await get_employees(session)

        if not employees:
            await wizard_show_from_callback(
                call,
                state,
                "Сотрудники (employee) не найдены.",
                reply_markup=kb_back_to_menu(),
            )
            await call.answer()
            return

        await state.update_data(**{
            EMP_PICK_IDS: [u.id for u in employees],
            EMP_PICK_PAGE: 0,
        })

        await wizard_show_from_callback(
            call,
            state,
            "👤 Выбери сотрудника:",
            reply_markup=kb_employees_pick(employees, page=0),
        )
        await call.answer()
        return

    await state.update_data(tasks_filter=flt)
    await state.set_state(ManagerTasks.list_pick_filter)

    async with session_scope() as session:
        tasks = await get_tasks_for_manager_filter(
            session=session,
            flt=flt,
            now_utc=now_utc(),
            limit=50,
        )

    if not tasks:
        await wizard_show_from_callback(
            call,
            state,
            "Нет задач по выбранному фильтру.",
            reply_markup=kb_tasks_filters(),
        )
        await call.answer()
        return

    await state.update_data(**{
        TASKS_PICK_IDS: [t.id for t in tasks],
        TASKS_PICK_PAGE: 0,
        TASKS_PICK_BACK_TEXT: "⬅️ К фильтрам",
        TASKS_PICK_BACK_CALLBACK: "mtasks:list",
    })

    await wizard_show_from_callback(
        call,
        state,
        "📋 Задачи (выбери по кнопке):",
        reply_markup=kb_tasks_pick(
            tasks,
            page=0,
            back_text="⬅️ К фильтрам",
            back_callback="mtasks:list",
        ),
    )
    await call.answer()


@router.callback_query(F.data.startswith("mtasks:pickpage:"), IsManager())
async def cb_tasks_pick_page(call: CallbackQuery, state: FSMContext):
    try:
        page = int(call.data.split(":")[-1])
    except (ValueError, IndexError):
        await call.answer("Некорректные данные кнопки.", show_alert=True)
        return

    data = await state.get_data()
    ids = data.get(TASKS_PICK_IDS) or []
    back_text = data.get(TASKS_PICK_BACK_TEXT)
    back_callback = data.get(TASKS_PICK_BACK_CALLBACK)

    if not ids:
        await call.answer("Список задач устарел. Открой /tasks заново.", show_alert=True)
        return

    async with session_scope() as session:
        tasks = await get_tasks_by_ids(session, ids)

    if not tasks:
        await call.answer("Список задач пуст или устарел. Открой /tasks заново.", show_alert=True)
        return

    await state.update_data(**{TASKS_PICK_PAGE: page})

    await wizard_show_from_callback(
        call,
        state,
        "📋 Задачи (выбери по кнопке):",
        reply_markup=kb_tasks_pick(
            tasks,
            page=page,
            back_text=back_text,
            back_callback=back_callback,
        ),
    )
    await call.answer()


@router.callback_query(F.data == "mtasks:overdue", IsManager())
async def cb_tasks_overdue(call: CallbackQuery, state: FSMContext):
    async with session_scope() as session:
        tasks = await get_overdue_tasks(session, now_utc=now_utc(), limit=50)

    if not tasks:
        await wizard_show_from_callback(
            call,
            state,
            "✅ Просроченных задач нет.",
            reply_markup=kb_back_to_menu(),
        )
        await call.answer()
        return

    await state.update_data(**{
        TASKS_PICK_IDS: [t.id for t in tasks],
        TASKS_PICK_PAGE: 0,
        TASKS_PICK_BACK_TEXT: "⬅️ К фильтрам",
        TASKS_PICK_BACK_CALLBACK: "mtasks:list",
    })

    await wizard_show_from_callback(
        call,
        state,
        "⏰ Просроченные задачи (выбери по кнопке):",
        reply_markup=kb_tasks_pick(tasks, page=0),
    )
    await call.answer()

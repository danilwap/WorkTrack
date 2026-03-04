from aiogram.fsm.state import StatesGroup, State


class Main(StatesGroup):
    menu = State()


class Tasks(StatesGroup):
    inbox_list = State()
    active_list = State()

    accept_confirm = State()

    comment_choose_task = State()
    comment_enter_text = State()

    finish_choose_task = State()
    finish_enter_result = State()


class Notes(StatesGroup):
    menu = State()

    create_title = State()
    create_body = State()
    create_reminder_ask = State()

    reminder_type = State()
    reminder_time = State()

    list_notes = State()

    comment_choose = State()
    comment_text = State()

    close_choose = State()
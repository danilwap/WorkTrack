from aiogram.fsm.state import State, StatesGroup


class ManagerTasks(StatesGroup):
    menu = State()

    # /task_new
    new_title = State()
    new_description = State()
    new_deadline = State()
    new_priority = State()
    new_assignee = State()

    # comment
    comment_text = State()

    # remind
    remind_pick = State()
    remind_in_hours = State()
    remind_custom_dt = State()

    # edit
    edit_pick_field = State()
    edit_deadline = State()
    edit_priority = State()
    edit_assignee = State()

    # tasks list filters
    list_pick_filter = State()

    # Отмена задачи
    cancel_comment_ask = State()
    cancel_comment_text = State()

    # Возращение на доработку
    reject_comment_ask = State()
    reject_comment_text = State()

    # Выгрузка статистики
    export_stats_period = State()

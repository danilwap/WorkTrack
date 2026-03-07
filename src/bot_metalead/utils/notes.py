from src.bot_metalead.db.models import ScheduleType


def schedule_type_from_ui(raw: str) -> ScheduleType:
    raw = (raw or "").strip().lower()
    mapping = {
        "daily": ScheduleType.daily,
        "weekly": ScheduleType.weekly,
        "monthly": ScheduleType.monthly,
    }
    return mapping.get(raw, ScheduleType.daily)
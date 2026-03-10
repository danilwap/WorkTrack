from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")


def now_msk() -> datetime:
    return datetime.now(MSK)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def msk_to_utc(dt: datetime) -> datetime:
    """
    На входе naive datetime, который пользователь выбрал как московское время.
    На выходе aware datetime в UTC.
    """
    if dt.tzinfo is not None:
        raise ValueError("msk_to_utc expects naive datetime")
    return dt.replace(tzinfo=MSK).astimezone(timezone.utc)


def fmt_msk(dt: datetime | None, fmt: str = "%d.%m %H:%M") -> str:
    if not dt:
        return "—"

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(MSK).strftime(fmt)
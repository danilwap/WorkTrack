from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.bot_metalead.db.session import session_scope
from src.bot_metalead.db.models import NoteReminder, Note


def _is_due(rem: NoteReminder, now: datetime) -> bool:
    if not rem.enabled:
        return False

    # Чтобы не спамить: не чаще 1 раза в сутки (MVP)
    if rem.last_sent_at and (now - rem.last_sent_at) < timedelta(hours=23):
        return False

    # Проверяем совпадение времени (минутная точность)
    return (now.hour == rem.remind_time.hour) and (now.minute == rem.remind_time.minute)


async def reminders_loop(bot):
    while True:
        now = datetime.now()  # локальное время сервера; при желании переведи на Europe/Helsinki
        try:
            async with session_scope() as session:
                q = await session.execute(
                    select(NoteReminder)
                    .options(selectinload(NoteReminder.note).selectinload(Note.owner))
                    .where(NoteReminder.enabled == True)
                )
                reminders = q.scalars().all()

                for rem in reminders:
                    note = rem.note
                    if not note or note.status != "active":
                        continue
                    if _is_due(rem, now):
                        owner_tg = note.owner.tg_id
                        await bot.send_message(
                            owner_tg,
                            f"⏰ Напоминание по заметке #{note.id}\n\n{note.title}\n\n{note.body or ''}".strip()
                        )
                        rem.last_sent_at = datetime.utcnow()
                await session.commit()
        except Exception:
            # логирование добавишь позже
            pass

        await asyncio.sleep(60)
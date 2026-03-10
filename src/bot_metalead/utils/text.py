from datetime import datetime

from src.bot_metalead.db.models import Task
from src.bot_metalead.utils.helpers import fmt_msk

TG_MAX = 4096


def clamp(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def split_for_tg(text: str, limit: int = TG_MAX) -> list[str]:
    """
    Режет текст на чанки <= limit.
    Ставит разбиение по '\n' когда возможно.
    """
    text = text or ""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    buf = text
    while len(buf) > limit:
        cut = buf.rfind("\n", 0, limit)
        if cut < 100:  # если не нашли нормальный перенос — режем по лимиту
            cut = limit
        chunks.append(buf[:cut].rstrip())
        buf = buf[cut:].lstrip("\n")
    if buf:
        chunks.append(buf)
    return chunks


def enum_value(x):
    return x.value if hasattr(x, "value") else str(x)


def fmt_task(
    task: Task,
    *,
    show_assignee: bool = True,
    comments_limit: int = 5,
    max_comment_len: int = 600,
    max_total_len: int | None = 3900,
) -> str:
    dl = fmt_msk(task.deadline_at)

    parts: list[str] = [
        f"🧩 Задача #{task.id}",
        f"Название: {task.title}",
        f"Дедлайн: {dl}",
        f"Приоритет: {task.priority.label}",
        f"Статус: {task.status.label}",
    ]

    if show_assignee:
        assignee = task.assignee
        name_assignee = (
            f"@{assignee.username}"
            if assignee and assignee.username
            else assignee.full_name
            if assignee and assignee.full_name
            else str(assignee.tg_id)
            if assignee
            else "—"
        )
        parts.append(f"Ответственный: {name_assignee}")

    if task.description:
        parts.append(task.description)

    text = "\n".join(parts).strip()

    if task.comments:
        text += "\n\n💬 Комментарии:\n"

        comments = sorted(
            task.comments,
            key=lambda c: c.created_at or datetime.min,
        )[-comments_limit:]

        for c in comments:
            author = (c.author.full_name or c.author.username) if c.author else "—"
            created = fmt_msk(c.created_at, "%d.%m %H:%M")
            comment_text = clamp(c.text or "", max_comment_len)
            text += f"\n• {author} ({created})\n{comment_text}"

    if max_total_len is not None and len(text) > max_total_len:
        text = clamp(text, max_total_len)

    return text

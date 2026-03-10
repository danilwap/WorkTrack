from datetime import datetime
from io import BytesIO
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from src.bot_metalead.db.models import UserRole
from src.bot_metalead.db.repositories.users_repo import is_manager


def render_tasks_table(
        rows: list[tuple[str, str, str]],
        title: str = "Активные задачи",
        rows_per_image: int = 20,
) -> list[BytesIO]:
    """
    Рисует таблицу задач и возвращает список PNG-картинок в BytesIO.
    rows: [(assignee, task_title, deadline), ...]
    """

    if not rows:
        rows = [("—", "Нет активных задач", "—")]

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font_bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    try:
        font = ImageFont.truetype(font_path, 20)
        font_bold = ImageFont.truetype(font_bold_path, 22)
        font_title = ImageFont.truetype(font_bold_path, 24)
    except Exception:
        font = ImageFont.load_default()
        font_bold = ImageFont.load_default()
        font_title = ImageFont.load_default()

    padding = 30
    row_h = 42
    header_h = 45
    title_h = 55
    bottom_pad = 20

    # Исполнитель | Задача | Дедлайн
    col_widths = [260, 520, 180]
    total_width = sum(col_widths) + padding * 2

    chunks = [
        rows[i:i + rows_per_image]
        for i in range(0, len(rows), rows_per_image)
    ]

    result: list[BytesIO] = []

    for page_num, chunk in enumerate(chunks, start=1):
        page_title = title
        if len(chunks) > 1:
            page_title += f" — часть {page_num}/{len(chunks)}"

        total_height = (
                padding
                + title_h
                + header_h
                + len(chunk) * row_h
                + bottom_pad
                + padding
        )

        img = Image.new("RGB", (total_width, total_height), "white")
        draw = ImageDraw.Draw(img)

        # Заголовок
        draw.text((padding, padding), page_title, font=font_title, fill="black")

        y = padding + title_h

        headers = ["Исполнитель", "Задача", "Дедлайн"]

        x = padding
        for idx, header in enumerate(headers):
            w = col_widths[idx]
            draw.rectangle((x, y, x + w, y + header_h), outline="black", width=2)
            draw.text((x + 10, y + 10), header, font=font_bold, fill="black")
            x += w

        y += header_h

        for assignee, task_title, deadline in chunk:
            x = padding
            values = [assignee, task_title, deadline]

            for idx, value in enumerate(values):
                w = col_widths[idx]
                draw.rectangle((x, y, x + w, y + row_h), outline="black", width=1)
                draw.text((x + 10, y + 10), str(value), font=font, fill="black")
                x += w

            y += row_h

        bio = BytesIO()
        img.save(bio, format="PNG")
        bio.seek(0)
        result.append(bio)

    return result

#  Сокращает строку для заданной длины
def _short(s: Optional[str], limit: int = 60) -> str:
    if not s:
        return "—"
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


# Форматирование даты
def _fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return "—"
    return dt.strftime("%d.%m %H:%M")




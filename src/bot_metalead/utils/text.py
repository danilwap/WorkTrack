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
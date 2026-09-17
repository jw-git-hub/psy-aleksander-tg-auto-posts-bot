"""Сборка расширенного сообщения («Статьи») для sendRichMessage.

Используется режим blocks, а не html: текст поста уходит простой строкой,
поэтому не нужно HTML-экранирование и не нужны ссылки tg://photo?id=, про
которые документация Bot API противоречит сама себе («Media blocks support
only HTTP and HTTPS URLs»).
"""

# Имя multipart-части с картинкой: InputMediaPhoto.media = "attach://cover".
RICH_COVER_ATTACH = "cover"

# Лимит Bot API: «Up to 500 blocks, including nested blocks…».
RICH_MAX_BLOCKS = 500


def build_rich_message(text: str) -> dict | None:
    """InputRichMessage: блок-картинка, затем абзац на каждую непустую строку.

    Как Telegram показывает перенос строки внутри абзаца, в документации не
    описано, поэтому каждая непустая строка — отдельный абзац: так список
    «— пункт» не склеится в одну строку. Возвращает None, если текста нет или
    блоков больше лимита, — тогда пост отправляется по-старому (classic).
    """
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    if not paragraphs or len(paragraphs) + 1 > RICH_MAX_BLOCKS:
        return None
    blocks = [{
        "type": "photo",
        "photo": {"type": "photo", "media": f"attach://{RICH_COVER_ATTACH}"},
    }]
    blocks.extend({"type": "paragraph", "text": paragraph} for paragraph in paragraphs)
    return {"blocks": blocks}

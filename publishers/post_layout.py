"""Раскладка текста поста на абзацы: общая для classic и rich.

Первая непустая строка — заголовок (печатается жирным), каждая следующая
непустая строка — отдельный абзац.
"""

import html

# Между абзацами classic-поста — пустая строка, чтобы текст легче читался.
CLASSIC_PARAGRAPH_SEPARATOR = "\n\n"


def split_paragraphs(text: str) -> list[str]:
    """Непустые строки текста без крайних пробелов."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def build_classic_html(text: str) -> str:
    """Текст для sendMessage с parse_mode=HTML: заголовок в <b>, абзацы через пустую строку."""
    paragraphs = [html.escape(paragraph, quote=False) for paragraph in split_paragraphs(text)]
    if paragraphs:
        paragraphs[0] = f"<b>{paragraphs[0]}</b>"
    return CLASSIC_PARAGRAPH_SEPARATOR.join(paragraphs)


def build_classic_plain(text: str) -> str:
    """Тот же текст без разметки — запасной вариант, если Telegram не разобрал HTML."""
    return CLASSIC_PARAGRAPH_SEPARATOR.join(split_paragraphs(text))

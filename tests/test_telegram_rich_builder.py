import json

from publishers.telegram_rich import RICH_COVER_ATTACH, RICH_MAX_BLOCKS, build_rich_message

PHOTO_BLOCK = {"type": "photo", "photo": {"type": "photo", "media": "attach://cover"}}


def test_photo_first_then_paragraph_per_line():
    text = (
        "Первый абзац.\nВторая строка абзаца.\n\n"
        "— пункт один\n— пункт два\n\n"
        "#отношения #психология"
    )

    assert build_rich_message(text) == {
        "blocks": [
            PHOTO_BLOCK,
            {"type": "paragraph", "text": "Первый абзац."},
            {"type": "paragraph", "text": "Вторая строка абзаца."},
            {"type": "paragraph", "text": "— пункт один"},
            {"type": "paragraph", "text": "— пункт два"},
            {"type": "paragraph", "text": "#отношения #психология"},
        ]
    }


def test_cover_attach_name():
    assert RICH_COVER_ATTACH == "cover"


def test_whitespace_trimmed_and_blank_lines_dropped():
    message = build_rich_message("\n\n   текст с пробелами   \n \t \n")

    assert message["blocks"][1:] == [{"type": "paragraph", "text": "текст с пробелами"}]


def test_special_characters_kept_verbatim():
    line = 'a < b && c > d "кавычки" \'апостроф\' <b>не тег</b> &amp;'

    message = build_rich_message(line)

    assert message["blocks"][1] == {"type": "paragraph", "text": line}


def test_empty_text_returns_none():
    assert build_rich_message("") is None
    assert build_rich_message("  \n\n \t ") is None


def test_block_limit():
    assert RICH_MAX_BLOCKS == 500
    fits = "\n".join(f"строка {i}" for i in range(RICH_MAX_BLOCKS - 1))
    assert len(build_rich_message(fits)["blocks"]) == RICH_MAX_BLOCKS
    too_many = "\n".join(f"строка {i}" for i in range(RICH_MAX_BLOCKS))
    assert build_rich_message(too_many) is None


def test_serializable_to_json():
    message = build_rich_message("Привет & пока")

    assert json.loads(json.dumps(message, ensure_ascii=False)) == message

import json
import logging

import pytest

from publishers import TelegramPublisher
from publishers.telegram_rich import build_rich_message
from tests.tg_fakes import error, not_json, ok, timeout

CHAT_ID = "-100500"
TEXT = "Первый абзац поста.\n\nВторой абзац.\n#отношения"
IMAGE = b"jpeg-bytes"


def rich_publisher() -> TelegramPublisher:
    return TelegramPublisher(bot_token="123:TEST", chat_id=CHAT_ID, retry_max=3,
                             post_format="rich")


@pytest.mark.parametrize("value, expected", [
    ("classic", "classic"),
    ("rich", "rich"),
    (" RICH ", "rich"),
    (None, "classic"),
    ("", "classic"),
])
def test_post_format_normalized(value, expected):
    assert TelegramPublisher("t", "c", post_format=value).post_format == expected


def test_default_post_format_is_classic():
    assert TelegramPublisher("t", "c").post_format == "classic"


def test_unknown_post_format_falls_back_to_classic_with_warning(caplog):
    with caplog.at_level(logging.WARNING):
        publisher = TelegramPublisher("t", "c", post_format="fancy")

    assert publisher.post_format == "classic"
    assert "fancy" in caplog.text


def test_classic_result_marked_classic(fake_tg):
    fake_tg.script("sendPhoto", ok(10))
    fake_tg.script("sendMessage", ok(11))

    result = TelegramPublisher("t", CHAT_ID).publish(TEXT, None, IMAGE)

    assert result.post_format == "classic"


def test_rich_sends_one_message_with_photo(fake_tg):
    fake_tg.script("sendRichMessage", ok(21))

    result = rich_publisher().publish(TEXT, None, IMAGE)

    assert result.ok is True
    assert result.post_id == "21"
    assert result.photo_post_id is None
    assert result.post_format == "rich"
    assert fake_tg.methods() == ["sendRichMessage"]
    call = fake_tg.kwargs(0)
    assert call["data"]["chat_id"] == CHAT_ID
    assert json.loads(call["data"]["rich_message"]) == build_rich_message(TEXT)
    assert call["files"] == {"cover": ("image.jpg", IMAGE, "image/jpeg")}
    assert call["timeout"] == 30


def test_rich_payload_keeps_cyrillic_readable(fake_tg):
    fake_tg.script("sendRichMessage", ok(21))

    rich_publisher().publish(TEXT, None, IMAGE)

    assert "Первый абзац" in fake_tg.kwargs(0)["data"]["rich_message"]


def test_rich_without_image_goes_classic(fake_tg):
    fake_tg.script("sendMessage", ok(11))

    result = rich_publisher().publish(TEXT, None, None)

    assert result.ok is True
    assert result.post_format == "classic"
    assert fake_tg.methods() == ["sendMessage"]


def test_rich_too_many_blocks_goes_classic_without_rich_request(fake_tg):
    fake_tg.script("sendPhoto", ok(10))
    fake_tg.script("sendMessage", ok(11))
    text = "\n".join("с" for _ in range(600))  # 600 строк, 1199 символов

    result = rich_publisher().publish(text, None, IMAGE)

    assert result.post_format == "classic"
    assert fake_tg.methods() == ["sendPhoto", "sendMessage"]


def test_long_text_truncated_before_rich(fake_tg):
    fake_tg.script("sendRichMessage", ok(21))

    rich_publisher().publish("а" * 5000, None, IMAGE)

    blocks = json.loads(fake_tg.kwargs(0)["data"]["rich_message"])["blocks"]
    assert blocks[1]["text"] == "а" * 4090 + "..."


@pytest.mark.parametrize("refusal", [
    error(400, "Bad Request: RICH_MESSAGE_INVALID"),
    error(403, "Forbidden: not enough rights to send photos to the chat"),
])
def test_explicit_refusal_falls_back_to_classic(fake_tg, caplog, refusal):
    fake_tg.script("sendRichMessage", refusal)
    fake_tg.script("sendPhoto", ok(10))
    fake_tg.script("sendMessage", ok(11))

    with caplog.at_level(logging.WARNING):
        result = rich_publisher().publish(TEXT, None, IMAGE)

    assert result.ok is True
    assert result.post_format == "classic"
    assert result.post_id == "11"
    assert result.photo_post_id == "10"
    assert fake_tg.methods() == ["sendRichMessage", "sendPhoto", "sendMessage"]
    assert refusal.json()["description"] in caplog.text


def test_timeouts_exhausted_fail_without_classic(fake_tg):
    fake_tg.script("sendRichMessage", timeout(), timeout(), timeout())

    result = rich_publisher().publish(TEXT, None, IMAGE)

    assert result.ok is False
    assert result.error == "rich retries exhausted"
    assert fake_tg.methods() == ["sendRichMessage"] * 3


def test_5xx_exhausted_fail_without_classic(fake_tg):
    fake_tg.script(
        "sendRichMessage",
        error(502, "Bad Gateway"), error(502, "Bad Gateway"), error(502, "Bad Gateway"),
    )

    result = rich_publisher().publish(TEXT, None, IMAGE)

    assert result.ok is False
    assert fake_tg.methods() == ["sendRichMessage"] * 3


@pytest.mark.parametrize("unclear", [timeout(), error(502, "Bad Gateway"), not_json()])
def test_refusal_after_unclear_attempt_fails_without_classic(fake_tg, unclear):
    # Первая попытка могла создать сообщение — classic после неё дал бы дубль.
    fake_tg.script("sendRichMessage", unclear, error(400, "Bad Request: RICH_MESSAGE_INVALID"))

    result = rich_publisher().publish(TEXT, None, IMAGE)

    assert result.ok is False
    assert "RICH_MESSAGE_INVALID" in result.error
    assert fake_tg.methods() == ["sendRichMessage", "sendRichMessage"]


def test_429_then_refusal_still_falls_back(fake_tg, sleeps):
    # 429 — однозначный отказ: сообщение не создано, classic безопасен.
    fake_tg.script(
        "sendRichMessage",
        error(429, "Too Many Requests: retry after 3", retry_after=3),
        error(400, "Bad Request: RICH_MESSAGE_INVALID"),
    )
    fake_tg.script("sendPhoto", ok(10))
    fake_tg.script("sendMessage", ok(11))

    result = rich_publisher().publish(TEXT, None, IMAGE)

    assert result.ok is True
    assert result.post_format == "classic"
    assert 3 in sleeps
    assert fake_tg.methods() == [
        "sendRichMessage", "sendRichMessage", "sendPhoto", "sendMessage",
    ]


def test_429_then_success(fake_tg, sleeps):
    fake_tg.script(
        "sendRichMessage",
        error(429, "Too Many Requests: retry after 5", retry_after=5),
        ok(21),
    )

    result = rich_publisher().publish(TEXT, None, IMAGE)

    assert result.ok is True
    assert result.post_format == "rich"
    assert 5 in sleeps


def test_timeout_then_success(fake_tg):
    fake_tg.script("sendRichMessage", timeout(), ok(21))

    result = rich_publisher().publish(TEXT, None, IMAGE)

    assert result.ok is True
    assert result.post_format == "rich"
    assert fake_tg.methods() == ["sendRichMessage", "sendRichMessage"]

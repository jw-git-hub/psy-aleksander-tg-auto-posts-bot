"""Характеризация текущей отправки в Telegram (classic): sendPhoto, затем sendMessage.

Тесты фиксируют поведение ДО добавления формата rich и должны проходить
без изменений после него.
"""

from publishers import TelegramPublisher
from tests.tg_fakes import error, ok, timeout

CHAT_ID = "-100500"


def make_publisher() -> TelegramPublisher:
    return TelegramPublisher(bot_token="123:TEST", chat_id=CHAT_ID, retry_max=3)


def test_photo_then_text_two_messages(fake_tg):
    fake_tg.script("sendPhoto", ok(10))
    fake_tg.script("sendMessage", ok(11))

    result = make_publisher().publish("Текст поста", None, b"jpeg-bytes")

    assert result.ok is True
    assert result.channel == "telegram"
    assert result.post_id == "11"
    assert result.photo_post_id == "10"
    assert fake_tg.methods() == ["sendPhoto", "sendMessage"]
    photo = fake_tg.kwargs(0)
    assert photo["data"] == {"chat_id": CHAT_ID}
    assert photo["files"] == {"photo": ("image.jpg", b"jpeg-bytes", "image/jpeg")}
    assert photo["timeout"] == 30
    message = fake_tg.kwargs(1)
    assert message["json"] == {
        "chat_id": CHAT_ID,
        "text": "Текст поста",
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    assert message["timeout"] == 30


def test_without_image_only_text(fake_tg):
    fake_tg.script("sendMessage", ok(11))

    result = make_publisher().publish("Текст поста", None, None)

    assert result.ok is True
    assert result.post_id == "11"
    assert result.photo_post_id is None
    assert fake_tg.methods() == ["sendMessage"]


def test_photo_failure_text_still_sent(fake_tg):
    fake_tg.script("sendPhoto", error(400, "Bad Request: IMAGE_PROCESS_FAILED"))
    fake_tg.script("sendMessage", ok(11))

    result = make_publisher().publish("Текст поста", None, b"jpeg-bytes")

    assert result.ok is True
    assert result.post_id == "11"
    assert result.photo_post_id is None
    assert fake_tg.methods() == ["sendPhoto", "sendMessage"]


def test_text_refused_returns_error(fake_tg):
    fake_tg.script("sendMessage", error(400, "Bad Request: chat not found"))

    result = make_publisher().publish("Текст поста", None, None)

    assert result.ok is False
    assert "chat not found" in result.error
    assert fake_tg.methods() == ["sendMessage"]


def test_429_waits_retry_after_and_retries(fake_tg, sleeps):
    fake_tg.script(
        "sendMessage",
        error(429, "Too Many Requests: retry after 7", retry_after=7),
        ok(11),
    )

    result = make_publisher().publish("Текст поста", None, None)

    assert result.ok is True
    assert 7 in sleeps
    assert fake_tg.methods() == ["sendMessage", "sendMessage"]


def test_5xx_retries(fake_tg, sleeps):
    fake_tg.script("sendMessage", error(502, "Bad Gateway"), ok(11))

    result = make_publisher().publish("Текст поста", None, None)

    assert result.ok is True
    assert 2 in sleeps


def test_network_error_retries(fake_tg):
    fake_tg.script("sendMessage", timeout(), ok(11))

    result = make_publisher().publish("Текст поста", None, None)

    assert result.ok is True
    assert fake_tg.methods() == ["sendMessage", "sendMessage"]


def test_html_parse_error_resends_without_parse_mode(fake_tg):
    fake_tg.script(
        "sendMessage",
        error(400, "Bad Request: can't parse entities: unsupported start tag"),
        ok(12),
    )

    result = make_publisher().publish("a < b", None, None)

    assert result.ok is True
    assert result.post_id == "12"
    assert "parse_mode" not in fake_tg.kwargs(1)["json"]


def test_long_text_truncated_to_4093(fake_tg):
    fake_tg.script("sendMessage", ok(11))

    make_publisher().publish("а" * 5000, None, None)

    sent = fake_tg.kwargs(0)["json"]["text"]
    assert len(sent) == 4093
    assert sent.endswith("...")


def test_retries_exhausted(fake_tg):
    fake_tg.script(
        "sendMessage",
        error(500, "Internal"), error(500, "Internal"), error(500, "Internal"),
    )

    result = make_publisher().publish("Текст поста", None, None)

    assert result.ok is False
    assert result.error == "retries exhausted"
    assert fake_tg.methods() == ["sendMessage"] * 3

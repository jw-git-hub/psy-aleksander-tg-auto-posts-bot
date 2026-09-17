import json

import pytest

import post_bot
import publishers.telegram as telegram_module
from tests.tg_fakes import FakeTelegram

CONFIG_ENV_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_TEST_CHAT_ID",
    "TELEGRAM_POST_FORMAT",
    "FACEBOOK_PAGE_ID",
    "FACEBOOK_PAGE_ACCESS_TOKEN",
    "INSTAGRAM_BUSINESS_ACCOUNT_ID",
)


@pytest.fixture
def fake_tg(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(telegram_module.requests, "post", fake.post)
    yield fake
    assert not fake.unexpected, f"Неожиданные вызовы Bot API: {fake.unexpected}"


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Никаких реальных пауз в тестах; записываем, сколько ждал бы код."""
    recorded: list[float] = []
    monkeypatch.setattr(telegram_module.time, "sleep", recorded.append)
    return recorded


@pytest.fixture
def bot_config(tmp_path, monkeypatch):
    """config.json во временной папке для post_bot.load_config(); окружение очищено."""
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(post_bot, "BASE_DIR", tmp_path)

    def write(**values) -> None:
        config = {"telegram_bot_token": "123:TEST", "telegram_chat_id": "-100500"}
        config.update(values)
        (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")

    return write

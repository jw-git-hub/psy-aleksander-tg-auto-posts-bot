import pytest

import publishers.telegram as telegram_module
from tests.tg_fakes import FakeTelegram


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

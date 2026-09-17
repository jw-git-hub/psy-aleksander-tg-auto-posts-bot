import logging
from pathlib import Path

import pytest

import post_bot
import preview_telegram_format as preview
from publishers import PublishResult
from tests.tg_fakes import FakeResponse, ok

REPO_ROOT = Path(__file__).resolve().parent.parent


def chat_response(chat_id: int) -> FakeResponse:
    return FakeResponse(200, {"ok": True, "result": {"id": chat_id, "type": "channel"}})


def fake_get_chat(monkeypatch, responses: dict) -> None:
    monkeypatch.setattr(
        preview.requests, "get",
        lambda url, **kwargs: responses[kwargs["params"]["chat_id"]],
    )


def forbid_get(monkeypatch) -> None:
    def fail(url, **kwargs):
        raise AssertionError("сетевой вызов не ожидался")
    monkeypatch.setattr(preview.requests, "get", fail)


def test_test_chat_id_env_overrides_config(bot_config, monkeypatch):
    bot_config(telegram_test_chat_id="-100111")
    monkeypatch.setenv("TELEGRAM_TEST_CHAT_ID", "-100222")

    assert post_bot.load_config()["telegram_test_chat_id"] == "-100222"


def test_resolve_test_chat_id_returns_test_channel():
    config = {"telegram_chat_id": "-100500", "telegram_test_chat_id": " -100999 "}

    assert preview.resolve_test_chat_id(config) == "-100999"


@pytest.mark.parametrize("config", [
    {"telegram_chat_id": "-100500"},
    {"telegram_chat_id": "-100500", "telegram_test_chat_id": ""},
    {"telegram_chat_id": "-100500", "telegram_test_chat_id": None},
])
def test_resolve_test_chat_id_requires_value(config):
    with pytest.raises(ValueError, match="telegram_test_chat_id"):
        preview.resolve_test_chat_id(config)


@pytest.mark.parametrize("main_id, test_id", [
    ("-100500", "-100500"),
    (-100500, "-100500"),
    ("@my_channel", "@My_Channel"),
])
def test_resolve_test_chat_id_refuses_main_channel(main_id, test_id):
    with pytest.raises(ValueError, match="совпадает"):
        preview.resolve_test_chat_id({"telegram_chat_id": main_id, "telegram_test_chat_id": test_id})


def test_same_channel_detected_via_get_chat(monkeypatch):
    fake_get_chat(monkeypatch, {
        "@main_channel": chat_response(-100500),
        "-100500": chat_response(-100500),
    })

    with pytest.raises(ValueError, match="совпадает"):
        preview.ensure_different_channels("123:TEST", "@main_channel", "-100500")


def test_different_channels_pass(monkeypatch):
    fake_get_chat(monkeypatch, {
        "-100500": chat_response(-100500),
        "-100999": chat_response(-100999),
    })

    assert preview.ensure_different_channels("123:TEST", -100500, "-100999") is None


def test_unreachable_test_channel_refused(monkeypatch):
    fake_get_chat(monkeypatch, {
        "-100500": chat_response(-100500),
        "-100999": FakeResponse(400, {"ok": False, "description": "Bad Request: chat not found"}),
    })

    with pytest.raises(ValueError, match="-100999"):
        preview.ensure_different_channels("123:TEST", "-100500", "-100999")


def test_extract_channels_from_updates():
    updates = [
        {"update_id": 1, "channel_post": {"chat": {"id": -100777, "type": "channel", "title": "Тест"}}},
        {"update_id": 2, "my_chat_member": {"chat": {"id": -100888, "type": "channel", "title": "Другой"}}},
        {"update_id": 3, "message": {"chat": {"id": 42, "type": "private"}}},
        {"update_id": 4, "channel_post": {"chat": {"id": -100777, "type": "channel", "title": "Тест"}}},
    ]

    assert preview.extract_channels(updates) == {"-100777": "Тест", "-100888": "Другой"}


def test_find_chat_id_prints_channels(monkeypatch, capsys):
    updates = {"ok": True, "result": [
        {"update_id": 1, "channel_post": {"chat": {"id": -100777, "type": "channel", "title": "Тест"}}},
    ]}
    monkeypatch.setattr(preview.requests, "get", lambda url, **kwargs: FakeResponse(200, updates))

    assert preview.find_chat_id("123:TEST", None) == 0
    assert "-100777" in capsys.readouterr().out


def test_find_chat_id_marks_main_channel(monkeypatch, capsys):
    updates = {"ok": True, "result": [
        {"update_id": 1, "channel_post": {"chat": {"id": -100500, "type": "channel", "title": "Основной"}}},
        {"update_id": 2, "channel_post": {"chat": {"id": -100777, "type": "channel", "title": "Тест"}}},
    ]}
    monkeypatch.setattr(preview.requests, "get", lambda url, **kwargs: FakeResponse(200, updates))

    assert preview.find_chat_id("123:TEST", "-100500") == 0
    out = capsys.readouterr().out
    lines = {line.split()[0]: line for line in out.splitlines() if line.strip().startswith("-100")}
    assert "ОСНОВНОЙ" in lines["-100500"]
    assert "ОСНОВНОЙ" not in lines["-100777"]


def test_default_image_is_first_screenshot():
    expected = sorted((REPO_ROOT / "docs" / "screenshots").glob("*.jpg"))[0]

    assert preview.default_image_path() == expected


def test_samples_fit_telegram_limit():
    for name, text in preview.SAMPLES:
        assert 0 < len(text) <= 4096, name
    assert any(len(text) > 3700 for _, text in preview.SAMPLES), "нужен длинный образец"


def test_send_previews_only_to_test_chat(fake_tg):
    fake_tg.script("sendPhoto", ok(1))
    fake_tg.script("sendMessage", ok(2))
    fake_tg.script("sendRichMessage", *[ok(10 + i) for i in range(len(preview.SAMPLES))])
    config = {"telegram_bot_token": "123:TEST", "telegram_chat_id": "-100500", "retry_max": 3}

    results = preview.send_previews(config, "-100999", b"jpeg-bytes")

    chat_ids = {(kw.get("data") or kw.get("json"))["chat_id"] for _, kw in fake_tg.calls}
    assert chat_ids == {"-100999"}
    assert [expected for _, expected, _ in results] == ["classic"] + ["rich"] * len(preview.SAMPLES)
    assert preview.summarize(results)[1] is True


def test_summary_flags_rich_fallback_and_errors():
    results = [
        ("образец / classic", "classic",
         PublishResult(channel="telegram", ok=True, post_id="1", post_format="classic")),
        ("образец / rich", "rich",
         PublishResult(channel="telegram", ok=True, post_id="2", post_format="classic")),
        ("эмодзи / rich", "rich",
         PublishResult(channel="telegram", ok=False, error="rich retries exhausted")),
    ]

    lines, all_as_expected = preview.summarize(results)

    assert all_as_expected is False
    assert any("образец / rich" in line and "classic" in line for line in lines)
    assert any("эмодзи / rich" in line and "rich retries exhausted" in line for line in lines)


def test_main_refuses_main_channel_without_sending(bot_config, fake_tg, monkeypatch):
    bot_config(telegram_test_chat_id="-100500")  # совпадает с telegram_chat_id
    forbid_get(monkeypatch)

    assert preview.main([]) == 2
    assert fake_tg.calls == []


def test_main_redacts_token_in_library_logs(bot_config, monkeypatch, capsys, caplog):
    """Логи сторонних библиотек (urllib3 и т.п.) не должны сливать токен бота.

    urllib3 при проблемах с ответом логирует "Failed to parse headers
    (url=%s)" с полным URL запроса — токен в нём. install_filter() должен
    маскировать такие записи, даже если они пришли не через logging нашего
    кода, а через дочерний логгер (urllib3.connection).
    """
    bot_config(telegram_bot_token="123456:AAFakeSecretToken")

    def fake_get(url, **kwargs):
        logging.getLogger("urllib3.connection").warning(
            "Failed to parse headers (url=%s): x", url
        )
        return FakeResponse(200, {"ok": True, "result": []})

    monkeypatch.setattr(preview.requests, "get", fake_get)

    preview.main(["--find-chat-id"])

    captured = capsys.readouterr()
    assert "AAFakeSecretToken" not in captured.out
    assert "AAFakeSecretToken" not in captured.err
    assert "AAFakeSecretToken" not in caplog.text

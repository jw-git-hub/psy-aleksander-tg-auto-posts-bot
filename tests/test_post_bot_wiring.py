from pathlib import Path

import post_bot
from publishers import PublishResult, TelegramPublisher

REPO_ROOT = Path(__file__).resolve().parent.parent


def telegram_of(publishers: list) -> TelegramPublisher:
    return next(p for p in publishers if p.name == "telegram")


def test_build_publishers_passes_post_format():
    pubs = post_bot._build_publishers({
        "telegram_bot_token": "t",
        "telegram_chat_id": "c",
        "telegram_post_format": "rich",
    })

    assert telegram_of(pubs).post_format == "rich"


def test_build_publishers_defaults_to_classic():
    pubs = post_bot._build_publishers({"telegram_bot_token": "t", "telegram_chat_id": "c"})

    assert telegram_of(pubs).post_format == "classic"


def test_post_format_read_from_config_json(bot_config):
    bot_config(telegram_post_format="rich")

    assert post_bot.load_config()["telegram_post_format"] == "rich"


def test_post_format_has_no_env_override(bot_config, monkeypatch):
    # Переключатель живёт только в config.json: откат одним словом не должен
    # молча перекрываться переменной окружения.
    bot_config(telegram_post_format="classic")
    monkeypatch.setenv("TELEGRAM_POST_FORMAT", "rich")

    assert post_bot.load_config()["telegram_post_format"] == "classic"


def test_record_fields_for_rich_post():
    result = PublishResult(channel="telegram", ok=True, post_id="21", post_format="rich")

    assert post_bot._telegram_record_fields({"telegram_chat_id": "-100500"}, result) == {
        "telegram_chat_id": "-100500",
        "telegram_message_id": 21,
        "telegram_photo_message_id": None,
        "telegram_post_format": "rich",
    }


def test_record_fields_for_classic_post():
    result = PublishResult(channel="telegram", ok=True, post_id="11",
                           photo_post_id="10", post_format="classic")

    assert post_bot._telegram_record_fields({"telegram_chat_id": "-100500"}, result) == {
        "telegram_chat_id": "-100500",
        "telegram_message_id": 11,
        "telegram_photo_message_id": 10,
        "telegram_post_format": "classic",
    }


def test_main_uses_record_fields_helper():
    source = (REPO_ROOT / "post_bot.py").read_text(encoding="utf-8")

    assert "**_telegram_record_fields(config, tg_result)," in source


def test_publish_marker_for_run_with_retry_unchanged():
    source = (REPO_ROOT / "post_bot.py").read_text(encoding="utf-8")
    wrapper = (REPO_ROOT / "run_with_retry.sh").read_text(encoding="utf-8")

    assert 'logging.info(f"Опубликовано: {topic} (цикл {current_cycle})")' in source
    assert "PUBLISH_MARKER='INFO Опубликовано: '" in wrapper

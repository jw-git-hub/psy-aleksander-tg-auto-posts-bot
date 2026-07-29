#!/usr/bin/env python3
"""Smoke-test конфигурации publisher-ов.

Читает .env / config.json, инстанцирует все publisher-ы, печатает is_configured().
Реальных запросов к API не делает.

Запуск:
    ./venv/bin/python3 test_publishers.py
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from publishers import FacebookPublisher, InstagramPublisher, TelegramPublisher

BASE_DIR = Path(__file__).resolve().parent


def main():
    load_dotenv(BASE_DIR / ".env")
    cfg_path = BASE_DIR / "config.json"
    config = {}
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    # env vars переопределяют
    for env_key, cfg_key in (
        ("TELEGRAM_BOT_TOKEN", "telegram_bot_token"),
        ("TELEGRAM_CHAT_ID", "telegram_chat_id"),
        ("FACEBOOK_PAGE_ID", "facebook_page_id"),
        ("FACEBOOK_PAGE_ACCESS_TOKEN", "facebook_page_access_token"),
        ("INSTAGRAM_BUSINESS_ACCOUNT_ID", "instagram_business_account_id"),
    ):
        v = os.getenv(env_key)
        if v:
            config[cfg_key] = v

    graph_v = config.get("graph_api_version", "v21.0")

    tg = TelegramPublisher(
        bot_token=config.get("telegram_bot_token", ""),
        chat_id=config.get("telegram_chat_id", ""),
        retry_max=config.get("retry_max", 3),
    )
    fb = FacebookPublisher(
        page_id=config.get("facebook_page_id", ""),
        page_access_token=config.get("facebook_page_access_token", ""),
        graph_api_version=graph_v,
    )
    ig = InstagramPublisher(
        ig_business_id=config.get("instagram_business_account_id", ""),
        page_access_token=config.get("facebook_page_access_token", ""),
        graph_api_version=graph_v,
    )

    print("Publisher configuration check:")
    print(f"  telegram : configured={tg.is_configured()}")
    print(f"  facebook : configured={fb.is_configured()}")
    print(f"  instagram: configured={ig.is_configured()}")
    print(f"  graph_api_version={graph_v}")

    if not tg.is_configured():
        print("\nERROR: telegram is mandatory but not configured", file=sys.stderr)
        sys.exit(1)

    print("\nOK: configuration check passed (no live API calls made).")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Проверка формата постов в ТЕСТОВОМ Telegram-канале.

Отправляет образцы постов в telegram_test_chat_id: один в формате classic и
набор в формате rich («Статья»), чтобы сравнить вид на телефоне и компьютере.

Безопасность:
  - не пишет в posted-topics.json, не вызывает Claude, не публикует в
    Facebook/Instagram;
  - отказывается работать, если telegram_test_chat_id пуст или указывает на
    основной канал (сравнение и по строке, и по числовому id через getChat).

Запуск (из папки проекта):
    ./venv/bin/python3 preview_telegram_format.py --find-chat-id
    ./venv/bin/python3 preview_telegram_format.py [--image путь/к/картинке.jpg]
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import requests

from post_bot import load_config
from publishers import PublishResult, TelegramPublisher
from publishers.log_safety import describe_exception

BASE_DIR = Path(__file__).resolve().parent
API_BASE = "https://api.telegram.org/bot"

SAMPLE_POST = (
    "Бывает, что пара годами живёт рядом, но разговаривает только о бытовом: "
    "кто заберёт ребёнка, что купить к ужину, когда платить за квартиру.\n"
    "\n"
    "В моей практике это одна из самых частых причин, по которым люди "
    "приходят на консультацию. Не измена и не громкие ссоры, а тихое "
    "отдаление, которое никто не замечает, пока не становится поздно.\n"
    "\n"
    "Что помогает вернуть близость:\n"
    "— десять минут в день без телефонов, только друг для друга;\n"
    "— вопрос «как ты?» с готовностью услышать честный ответ;\n"
    "— благодарность за мелочи, которые обычно воспринимаются как должное.\n"
    "\n"
    "Это не волшебная таблетка, но с таких маленьких шагов начинается "
    "разговор, которого вам, возможно, давно не хватает.\n"
    "\n"
    "#отношения #близость #семейнаяпсихология"
)

SYMBOLS_POST = (
    "Проверка символов: 2 < 3, 5 > 4, «ёлочки», \"прямые кавычки\", "
    "'апострофы' и амперсанд & в тексте.\n"
    "\n"
    "Строка, похожая на разметку: <b>это не жирный</b> и &amp; как есть.\n"
    "\n"
    "#проверка"
)

LIST_POST = (
    "Пять признаков того, что вам нужна пауза в споре:\n"
    "— вы спорите об одном и том же третий раз за неделю;\n"
    "— после разговора остаётся усталость, а не облегчение;\n"
    "— вы заранее знаете, что ответит партнёр;\n"
    "— хочется выиграть, а не договориться;\n"
    "— тело напряжено ещё до начала разговора.\n"
    "\n"
    "1. Сделайте паузу.\n"
    "2. Назовите своё чувство.\n"
    "3. Вернитесь к разговору в договорённое время.\n"
    "\n"
    "#конфликты #общение"
)

EMOJI_POST = (
    "Маленькие ритуалы пары 💛\n"
    "\n"
    "☕ Утренний кофе вместе, даже если он длится пять минут.\n"
    "🚶 Вечерняя прогулка без обсуждения дел.\n"
    "📝 Записка на холодильнике просто так.\n"
    "\n"
    "#ритуалы #семья"
)

_LONG_PARAGRAPH = (
    "Длинный абзац для проверки объёма: когда партнёры перестают делиться "
    "переживаниями, каждый начинает додумывать мысли другого, и эти догадки "
    "почти всегда мрачнее реальности. Поэтому так важно проговаривать даже "
    "то, что кажется очевидным, и спрашивать, а не предполагать."
)


def _build_long_post(limit: int = 4000) -> str:
    paragraphs: list[str] = []
    while len("\n\n".join(paragraphs + [_LONG_PARAGRAPH])) <= limit:
        paragraphs.append(_LONG_PARAGRAPH)
    return "\n\n".join(paragraphs)


SAMPLES = [
    ("обычный пост", SAMPLE_POST),
    ("символы < > & и кавычки", SYMBOLS_POST),
    ("длинный пост", _build_long_post()),
    ("списки", LIST_POST),
    ("эмодзи", EMOJI_POST),
]


def resolve_test_chat_id(config: dict) -> str:
    """Id тестового канала из конфига; ValueError, если его нет или это основной канал."""
    test_id = str(config.get("telegram_test_chat_id") or "").strip()
    if not test_id:
        raise ValueError(
            "не задан telegram_test_chat_id (config.json или TELEGRAM_TEST_CHAT_ID). "
            "Узнать id: --find-chat-id"
        )
    main_id = str(config.get("telegram_chat_id") or "").strip()
    if test_id.lower() == main_id.lower():
        raise ValueError("telegram_test_chat_id совпадает с основным каналом — отказ")
    return test_id


def _fetch_numeric_chat_id(token: str, chat_ref: str) -> int:
    try:
        resp = requests.get(f"{API_BASE}{token}/getChat", params={"chat_id": chat_ref}, timeout=30)
        data = resp.json()
    except Exception as e:
        raise ValueError(f"getChat для {chat_ref} не удался: {describe_exception(e)}") from None
    chat_id = (data.get("result") or {}).get("id") if data.get("ok") else None
    if not isinstance(chat_id, int):
        raise ValueError(f"бот не видит канал {chat_ref}: {data.get('description', 'нет описания')}")
    return chat_id


def ensure_different_channels(token: str, main_ref, test_ref: str) -> None:
    """Сверяет числовые id через getChat: @username и -100… могут оказаться одним каналом."""
    if _fetch_numeric_chat_id(token, str(main_ref)) == _fetch_numeric_chat_id(token, test_ref):
        raise ValueError("telegram_test_chat_id совпадает с основным каналом (по getChat) — отказ")


def extract_channels(updates: list[dict]) -> dict[str, str]:
    """id → название каналов, из которых боту приходили обновления."""
    channels: dict[str, str] = {}
    for update in updates:
        for key in ("channel_post", "edited_channel_post", "my_chat_member"):
            chat = (update.get(key) or {}).get("chat") or {}
            if chat.get("type") == "channel" and "id" in chat:
                channels[str(chat["id"])] = chat.get("title", "")
    return channels


def find_chat_id(token: str) -> int:
    try:
        resp = requests.get(f"{API_BASE}{token}/getUpdates", timeout=30)
        data = resp.json()
    except Exception as e:
        print(f"getUpdates не удался: {describe_exception(e)}", file=sys.stderr)
        return 1
    if not data.get("ok"):
        print(f"Telegram отказал в getUpdates: {data.get('description', 'нет описания')}",
              file=sys.stderr)
        return 1
    channels = extract_channels(data.get("result") or [])
    if not channels:
        print("Каналов не найдено. Добавьте бота администратором в тестовый канал, "
              "напишите там любое сообщение и запустите снова (Telegram хранит "
              "обновления 24 часа).")
        return 1
    print("Каналы, откуда боту приходили обновления:")
    for chat_id, title in channels.items():
        print(f"  {chat_id}  {title}")
    print('Впишите id ТЕСТОВОГО канала в config.json: "telegram_test_chat_id": "<id>"')
    return 0


def default_image_path() -> Path:
    images = sorted((BASE_DIR / "docs" / "screenshots").glob("*.jpg"))
    if not images:
        raise ValueError("нет картинок в docs/screenshots/ — укажите --image")
    return images[0]


def send_previews(config: dict, chat_id: str,
                  image_bytes: bytes) -> list[tuple[str, str, PublishResult]]:
    token = config["telegram_bot_token"]
    retry_max = config.get("retry_max", 3)
    classic = TelegramPublisher(token, chat_id, retry_max, post_format="classic")
    rich = TelegramPublisher(token, chat_id, retry_max, post_format="rich")

    first_name, first_text = SAMPLES[0]
    results = [(f"{first_name} / classic", "classic",
                classic.publish(first_text, None, image_bytes))]
    for name, text in SAMPLES:
        time.sleep(2)  # не упираться в лимиты Telegram
        results.append((f"{name} / rich", "rich", rich.publish(text, None, image_bytes)))
    return results


def summarize(results: list[tuple[str, str, PublishResult]]) -> tuple[list[str], bool]:
    lines: list[str] = []
    all_as_expected = True
    for name, expected, result in results:
        if not result.ok:
            all_as_expected = False
            lines.append(f"ОШИБКА   {name}: {result.error}")
        elif result.post_format != expected:
            all_as_expected = False
            lines.append(f"ВНИМАНИЕ {name}: ушло как {result.post_format} — "
                         f"Telegram отказал в rich, причина выше в логе")
        else:
            lines.append(f"ок       {name} (msg_id={result.post_id})")
    return lines, all_as_expected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Образцы постов в тестовый Telegram-канал")
    parser.add_argument("--find-chat-id", action="store_true",
                        help="показать id каналов, откуда боту приходили обновления")
    parser.add_argument("--image", type=Path,
                        help="картинка для образцов (по умолчанию — из docs/screenshots/)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    token = config["telegram_bot_token"]

    if args.find_chat_id:
        return find_chat_id(token)

    try:
        chat_id = resolve_test_chat_id(config)
        ensure_different_channels(token, config["telegram_chat_id"], chat_id)
        image_bytes = (args.image or default_image_path()).read_bytes()
    except (ValueError, OSError) as e:
        print(f"Отказ: {e}", file=sys.stderr)
        return 2

    results = send_previews(config, chat_id, image_bytes)
    lines, all_as_expected = summarize(results)
    print("\nИтог:")
    for line in lines:
        print("  " + line)
    return 0 if all_as_expected else 1


if __name__ == "__main__":
    sys.exit(main())

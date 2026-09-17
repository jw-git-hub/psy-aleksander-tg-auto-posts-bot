"""TelegramPublisher: classic (sendPhoto + sendMessage) или rich (sendRichMessage).

429/5xx retry, HTML fallback для classic. Rich при явном отказе Telegram
откатывается на classic; при неясном исходе (сеть, 5xx) — нет, чтобы не
получить дубль.
"""

import json
import logging
import time

import requests

from .base import Publisher, PublishResult
from .log_safety import describe_exception, install_filter
from .telegram_rich import RICH_COVER_ATTACH, build_rich_message

# Маскируем токен бота в логах при первом же импорте модуля — независимо от
# того, когда/кем настроен логгер (см. publishers/log_safety.py).
install_filter()

TEXT_LIMIT = 4096
POST_FORMATS = ("classic", "rich")

# Итоги попытки отправить rich-сообщение.
RICH_OK = "ok"
# Telegram явно отказал: сообщение точно не создано — можно слать classic.
RICH_REJECTED = "rejected"
# Исход неясен (сеть/5xx) или попытки исчерпаны — classic слать нельзя:
# при потерянном ответе в канале оказался бы дубль.
RICH_FAILED = "failed"


def _sanitize_for_logging(data: dict) -> dict:
    """Убирает чувствительные данные из ответа Telegram API перед логированием"""
    safe = {}
    for key, value in data.items():
        if key in ("result",):
            if isinstance(value, dict):
                safe[key] = {k: v for k, v in value.items()
                             if k in ("message_id", "chat", "date", "ok")}
            else:
                safe[key] = value
        elif key in ("ok", "error_code", "description", "parameters"):
            safe[key] = value
    return safe


def _truncate_text(text: str) -> str:
    """Страховочный обрез до лимита sendMessage (валидатор в post_bot.py
    и так не пропускает посты длиннее 4096)."""
    if len(text) <= TEXT_LIMIT:
        return text
    original_len = len(text)
    logging.warning(f"Текст обрезан: {original_len} → 4093 символов (убрано {original_len - 4093})")
    return text[:4090] + "..."


def _normalize_post_format(value) -> str:
    normalized = str(value or "classic").strip().lower()
    if normalized not in POST_FORMATS:
        logging.warning(f"TG: неизвестный telegram_post_format={value!r}, используем classic")
        return "classic"
    return normalized


class TelegramPublisher(Publisher):
    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str, retry_max: int = 3,
                 post_format: str = "classic"):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.retry_max = retry_max
        self.post_format = _normalize_post_format(post_format)

    def is_configured(self) -> bool:
        return bool(self.bot_token) and bool(self.chat_id)

    def publish(
        self,
        text: str,
        image_url: str | None,
        image_bytes: bytes | None,
    ) -> PublishResult:
        # Rich имеет смысл только с картинкой: без неё объединять нечего,
        # а classic-путь проверен.
        if self.post_format == "rich" and image_bytes:
            rich_message = build_rich_message(_truncate_text(text))
            if rich_message is None:
                logging.warning("TG: текст не укладывается в rich-сообщение — отправляем classic")
            else:
                status, msg_id, err = self._send_rich(rich_message, image_bytes)
                if status == RICH_OK:
                    return PublishResult(
                        channel=self.name,
                        ok=True,
                        post_id=str(msg_id) if msg_id else None,
                        post_format="rich",
                    )
                if status == RICH_FAILED:
                    return PublishResult(channel=self.name, ok=False, error=err or "send_rich failed")
                logging.warning("TG: Telegram отказал в rich-сообщении — отправляем classic")
        elif self.post_format == "rich" and not image_bytes:
            logging.info("TG: в посте нет картинки — отправляем classic")
        return self._publish_classic(text, image_bytes)

    def _publish_classic(self, text: str, image_bytes: bytes | None) -> PublishResult:
        # Если есть bytes картинки — сначала отправляем фото, потом текст.
        # Если фото не отправилось — продолжаем только с текстом (как раньше в main).
        photo_msg_id = None
        if image_bytes:
            photo_ok, photo_msg_id = self._send_photo(image_bytes)
            if not photo_ok:
                logging.warning("TG: фото не отправлено, продолжаем с текстом")
            time.sleep(1)  # Пауза между фото и текстом

        ok, msg_id, err = self._send_message(text)
        if ok:
            logging.info("TG: пост отправлен в формате classic")
            return PublishResult(
                channel=self.name,
                ok=True,
                post_id=str(msg_id) if msg_id else None,
                photo_post_id=str(photo_msg_id) if photo_msg_id else None,
                post_format="classic",
            )
        return PublishResult(channel=self.name, ok=False, error=err or "send_message failed")

    def _send_rich(self, rich_message: dict, image_data: bytes) -> tuple[str, int | None, str | None]:
        """Одно rich-сообщение (картинка + абзацы). Возвращает (статус, message_id, ошибка).

        RICH_REJECTED — только если Telegram явно отказал (`ok: false` и HTTP
        4xx, кроме 429), а все предыдущие попытки закончились однозначно
        (429): сообщение точно не создано. Сеть, 5xx, ответ не-JSON или любой
        другой ответ без явного отказа делают исход неясным — дальше только
        RICH_FAILED.
        """
        api_url = f"https://api.telegram.org/bot{self.bot_token}/sendRichMessage"
        payload = json.dumps(rich_message, ensure_ascii=False)
        unclear = False
        for attempt in range(1, self.retry_max + 1):
            try:
                resp = requests.post(
                    api_url,
                    data={"chat_id": self.chat_id, "rich_message": payload},
                    files={RICH_COVER_ATTACH: ("image.jpg", image_data, "image/jpeg")},
                    timeout=30,
                )
                data = resp.json()
                if not isinstance(data, dict):
                    data = {}
            except Exception as e:
                unclear = True
                logging.error(
                    f"Ошибка отправки rich-сообщения (попытка {attempt}/{self.retry_max}): "
                    f"{describe_exception(e)}"
                )
                if attempt < self.retry_max:
                    time.sleep(2)
                continue

            if data.get("ok") is True:
                result = data.get("result")
                msg_id = result.get("message_id") if isinstance(result, dict) else None
                logging.info(
                    f"Rich-сообщение («Статья») отправлено в канал "
                    f"(msg_id={msg_id if msg_id is not None else '?'})"
                )
                return RICH_OK, msg_id if isinstance(msg_id, int) else None, None

            if resp.status_code == 429:
                parameters = data.get("parameters")
                retry_after = parameters.get("retry_after", 5) if isinstance(parameters, dict) else 5
                if not isinstance(retry_after, (int, float)):
                    retry_after = 5
                logging.warning(f"Telegram 429: ждём {retry_after}с (попытка {attempt}/{self.retry_max})")
                time.sleep(retry_after)
                continue

            if 500 <= resp.status_code < 600:
                unclear = True
                logging.warning(f"Telegram 5xx ({resp.status_code}): ждём 2с (попытка {attempt}/{self.retry_max})")
                time.sleep(2)
                continue

            explicit_refusal = data.get("ok") is False and 400 <= resp.status_code < 500
            if not explicit_refusal:
                unclear = True
                logging.warning(
                    f"Telegram sendRichMessage: ответ без явного отказа "
                    f"(HTTP {resp.status_code}, {_sanitize_for_logging(data)}), "
                    f"исход неясен (попытка {attempt}/{self.retry_max})"
                )
                if attempt < self.retry_max:
                    time.sleep(2)
                continue

            err_desc = str(_sanitize_for_logging(data))
            if unclear:
                logging.error(
                    "Telegram sendRichMessage отказ после попытки с неясным исходом — "
                    f"classic не отправляем, чтобы не было дубля: {err_desc}"
                )
                return RICH_FAILED, None, err_desc
            logging.warning(f"Telegram sendRichMessage отказ: {err_desc}")
            return RICH_REJECTED, None, err_desc

        logging.error(f"Rich: все {self.retry_max} попыток исчерпаны")
        return RICH_FAILED, None, "rich retries exhausted"

    def _send_photo(self, image_data: bytes) -> tuple[bool, int | None]:
        api_url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        for attempt in range(1, self.retry_max + 1):
            try:
                resp = requests.post(
                    api_url,
                    data={"chat_id": self.chat_id},
                    files={"photo": ("image.jpg", image_data, "image/jpeg")},
                    timeout=30,
                )
                data = resp.json()

                if data.get("ok"):
                    msg_id = data.get("result", {}).get("message_id")
                    logging.info(f"Фото отправлено в канал (msg_id={msg_id if msg_id is not None else '?'})")
                    return True, msg_id if isinstance(msg_id, int) else None

                if resp.status_code == 429:
                    retry_after = data.get("parameters", {}).get("retry_after", 5)
                    if not isinstance(retry_after, (int, float)):
                        retry_after = 5
                    logging.warning(f"Telegram 429: ждём {retry_after}с (попытка {attempt}/{self.retry_max})")
                    time.sleep(retry_after)
                    continue

                if 500 <= resp.status_code < 600:
                    logging.warning(f"Telegram 5xx ({resp.status_code}): ждём 2с (попытка {attempt}/{self.retry_max})")
                    time.sleep(2)
                    continue

                logging.error(f"Telegram sendPhoto ошибка: {_sanitize_for_logging(data)}")
                return False, None

            except Exception as e:
                logging.error(
                    f"Ошибка отправки фото (попытка {attempt}/{self.retry_max}): "
                    f"{describe_exception(e)}"
                )
                if attempt < self.retry_max:
                    time.sleep(2)
                    continue

        logging.error(f"Все {self.retry_max} попыток исчерпаны")
        return False, None

    def _send_message(self, text: str) -> tuple[bool, int | None, str | None]:
        api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        # Telegram лимит: 4096 символов
        text = _truncate_text(text)

        for attempt in range(1, self.retry_max + 1):
            try:
                resp = requests.post(
                    api_url,
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                    timeout=30,
                )
                data = resp.json()

                if data.get("ok"):
                    msg_id = data.get("result", {}).get("message_id", "?")
                    logging.info(f"Сообщение отправлено в канал (msg_id={msg_id})")
                    return True, msg_id if isinstance(msg_id, int) else None, None

                if resp.status_code == 429:
                    retry_after = data.get("parameters", {}).get("retry_after", 5)
                    if not isinstance(retry_after, (int, float)):
                        retry_after = 5
                    logging.warning(f"Telegram 429: ждём {retry_after}с (попытка {attempt}/{self.retry_max})")
                    time.sleep(retry_after)
                    continue

                if 500 <= resp.status_code < 600:
                    logging.warning(f"Telegram 5xx ({resp.status_code}): ждём 2с (попытка {attempt}/{self.retry_max})")
                    time.sleep(2)
                    continue

                # HTML parse_mode ошибка — fallback на plain text
                if "can't parse entities" in data.get("description", "").lower():
                    logging.warning("Ошибка парсинга HTML, отправляем без parse_mode")
                    try:
                        resp2 = requests.post(
                            api_url,
                            json={
                                "chat_id": self.chat_id,
                                "text": text,
                                "disable_web_page_preview": True,
                            },
                            timeout=30,
                        )
                        data2 = resp2.json()
                        if data2.get("ok"):
                            msg_id2 = data2.get("result", {}).get("message_id", "?")
                            logging.info(f"Сообщение отправлено (без parse_mode, msg_id={msg_id2})")
                            return True, msg_id2 if isinstance(msg_id2, int) else None, None
                        logging.warning(f"Telegram sendMessage fallback ошибка: {_sanitize_for_logging(data2)}, retry")
                    except Exception as e2:
                        logging.warning(
                            f"Telegram sendMessage fallback exception: "
                            f"{describe_exception(e2)}, retry"
                        )
                    continue

                err_desc = str(_sanitize_for_logging(data))
                logging.error(f"Telegram sendMessage ошибка: {err_desc}")
                return False, None, err_desc

            except Exception as e:
                logging.error(
                    f"Ошибка отправки сообщения (попытка {attempt}/{self.retry_max}): "
                    f"{describe_exception(e)}"
                )
                if attempt < self.retry_max:
                    time.sleep(2)
                    continue

        logging.error(f"Все {self.retry_max} попыток исчерпаны")
        return False, None, "retries exhausted"

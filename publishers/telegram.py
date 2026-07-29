"""TelegramPublisher: sendPhoto + sendMessage с 429/5xx retry и HTML fallback."""

import logging
import time

import requests

from .base import Publisher, PublishResult
from .log_safety import describe_exception, install_filter

# Маскируем токен бота в логах при первом же импорте модуля — независимо от
# того, когда/кем настроен логгер (см. publishers/log_safety.py).
install_filter()


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


class TelegramPublisher(Publisher):
    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str, retry_max: int = 3):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.retry_max = retry_max

    def is_configured(self) -> bool:
        return bool(self.bot_token) and bool(self.chat_id)

    def publish(
        self,
        text: str,
        image_url: str | None,
        image_bytes: bytes | None,
    ) -> PublishResult:
        # Если есть bytes картинки — сначала отправляем фото, потом текст.
        # Если фото не отправилось — продолжаем только с текстом (как раньше в main).
        if image_bytes:
            photo_ok = self._send_photo(image_bytes)
            if not photo_ok:
                logging.warning("TG: фото не отправлено, продолжаем с текстом")
            time.sleep(1)  # Пауза между фото и текстом

        ok, msg_id, err = self._send_message(text)
        if ok:
            return PublishResult(channel=self.name, ok=True, post_id=str(msg_id) if msg_id else None)
        return PublishResult(channel=self.name, ok=False, error=err or "send_message failed")

    def _send_photo(self, image_data: bytes) -> bool:
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
                    msg_id = data.get("result", {}).get("message_id", "?")
                    logging.info(f"Фото отправлено в канал (msg_id={msg_id})")
                    return True

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
                return False

            except Exception as e:
                logging.error(
                    f"Ошибка отправки фото (попытка {attempt}/{self.retry_max}): "
                    f"{describe_exception(e)}"
                )
                if attempt < self.retry_max:
                    time.sleep(2)
                    continue

        logging.error(f"Все {self.retry_max} попыток исчерпаны")
        return False

    def _send_message(self, text: str) -> tuple[bool, int | None, str | None]:
        api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        # Telegram лимит: 4096 символов
        if len(text) > 4096:
            original_len = len(text)
            text = text[:4090] + "..."
            logging.warning(f"Текст обрезан: {original_len} → 4093 символов (убрано {original_len - 4093})")

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

"""InstagramPublisher: двухшаговая публикация через Graph API (media + media_publish)."""

import logging
import time

import requests

from .base import Publisher, PublishResult
from .log_safety import describe_exception, install_filter

# Маскируем access_token в логах при первом же импорте модуля — независимо
# от того, когда/кем настроен логгер (см. publishers/log_safety.py).
install_filter()


IG_CAPTION_LIMIT = 2200


class InstagramPublisher(Publisher):
    name = "instagram"

    def __init__(self, ig_business_id: str, page_access_token: str, graph_api_version: str = "v21.0"):
        self.ig_business_id = ig_business_id
        self.page_access_token = page_access_token
        self.graph_api_version = graph_api_version

    def is_configured(self) -> bool:
        return bool(self.ig_business_id) and bool(self.page_access_token)

    def publish(
        self,
        text: str,
        image_url: str | None,
        image_bytes: bytes | None,
    ) -> PublishResult:
        if not image_url:
            # IG Graph API не поддерживает текст-only посты
            logging.info("IG: нет image_url, пропускаем")
            return PublishResult(channel=self.name, ok=False, error="no image url")

        caption = text
        if len(caption) > IG_CAPTION_LIMIT:
            caption = caption[:IG_CAPTION_LIMIT - 1] + "…"

        base = f"https://graph.facebook.com/{self.graph_api_version}/{self.ig_business_id}"

        # Шаг A: создать media container
        try:
            resp = requests.post(
                f"{base}/media",
                data={
                    "image_url": image_url,
                    "caption": caption,
                    "access_token": self.page_access_token,
                },
                timeout=30,
            )
            data = resp.json() if resp.content else {}
        except requests.Timeout:
            logging.error("IG: таймаут 30с на шаге /media")
            return PublishResult(channel=self.name, ok=False, error="timeout on /media")
        except Exception as e:
            logging.error(f"IG: ошибка запроса /media: {describe_exception(e)}")
            return PublishResult(channel=self.name, ok=False, error=str(e))

        creation_id = data.get("id") if isinstance(data, dict) else None
        if resp.status_code != 200 or not creation_id:
            err_msg = _extract_error(data, resp.status_code)
            logging.error(f"IG: /media не удался: {err_msg}")
            return PublishResult(channel=self.name, ok=False, error=f"/media: {err_msg}")

        # IG нужно время обработать медиа
        time.sleep(2)

        # Шаг B: publish
        try:
            resp2 = requests.post(
                f"{base}/media_publish",
                data={
                    "creation_id": creation_id,
                    "access_token": self.page_access_token,
                },
                timeout=30,
            )
            data2 = resp2.json() if resp2.content else {}
        except requests.Timeout:
            logging.error("IG: таймаут 30с на шаге /media_publish")
            return PublishResult(channel=self.name, ok=False, error="timeout on /media_publish")
        except Exception as e:
            logging.error(f"IG: ошибка запроса /media_publish: {describe_exception(e)}")
            return PublishResult(channel=self.name, ok=False, error=str(e))

        pub_id = data2.get("id") if isinstance(data2, dict) else None
        if resp2.status_code == 200 and pub_id:
            logging.info(f"IG: пост опубликован (id={pub_id})")
            return PublishResult(channel=self.name, ok=True, post_id=str(pub_id))

        err_msg = _extract_error(data2, resp2.status_code)
        logging.error(f"IG: /media_publish не удался: {err_msg}")
        return PublishResult(channel=self.name, ok=False, error=f"/media_publish: {err_msg}")


def _extract_error(data, status_code: int) -> str:
    if isinstance(data, dict):
        err = data.get("error") or {}
        if isinstance(err, dict):
            msg = err.get("message")
            if msg:
                return msg
            return str(err)
        if err:
            return str(err)
    return f"http {status_code}"

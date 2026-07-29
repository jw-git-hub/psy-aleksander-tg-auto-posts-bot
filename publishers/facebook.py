"""FacebookPublisher: публикация поста на Facebook Page через Graph API."""

import logging

import requests

from .base import Publisher, PublishResult
from .log_safety import describe_exception, install_filter

# Маскируем access_token в логах при первом же импорте модуля — независимо
# от того, когда/кем настроен логгер (см. publishers/log_safety.py).
install_filter()


class FacebookPublisher(Publisher):
    name = "facebook"

    def __init__(self, page_id: str, page_access_token: str, graph_api_version: str = "v21.0"):
        self.page_id = page_id
        self.page_access_token = page_access_token
        self.graph_api_version = graph_api_version

    def is_configured(self) -> bool:
        return bool(self.page_id) and bool(self.page_access_token)

    def publish(
        self,
        text: str,
        image_url: str | None,
        image_bytes: bytes | None,
    ) -> PublishResult:
        base = f"https://graph.facebook.com/{self.graph_api_version}/{self.page_id}"

        if image_url:
            endpoint = f"{base}/photos"
            payload = {
                "url": image_url,
                "caption": text,
                "access_token": self.page_access_token,
            }
        else:
            # Fallback: чисто текстовый пост
            endpoint = f"{base}/feed"
            payload = {
                "message": text,
                "access_token": self.page_access_token,
            }

        try:
            resp = requests.post(endpoint, data=payload, timeout=30)
            data = resp.json() if resp.content else {}
        except requests.Timeout:
            logging.error("FB: таймаут 30с")
            return PublishResult(channel=self.name, ok=False, error="timeout")
        except Exception as e:
            logging.error(f"FB: ошибка запроса: {describe_exception(e)}")
            return PublishResult(channel=self.name, ok=False, error=str(e))

        if resp.status_code == 200 and isinstance(data, dict) and (data.get("id") or data.get("post_id")):
            post_id = data.get("post_id") or data.get("id")
            logging.info(f"FB: пост опубликован (id={post_id})")
            return PublishResult(channel=self.name, ok=True, post_id=str(post_id))

        err_msg = ""
        if isinstance(data, dict):
            err = data.get("error") or {}
            if isinstance(err, dict):
                err_msg = err.get("message") or str(err)
            else:
                err_msg = str(err)
        if not err_msg:
            err_msg = f"http {resp.status_code}"
        logging.error(f"FB: публикация не удалась: {err_msg}")
        return PublishResult(channel=self.name, ok=False, error=err_msg)

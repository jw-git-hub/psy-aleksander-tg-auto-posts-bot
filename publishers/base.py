"""Базовые типы для publisher-ов."""

from dataclasses import dataclass


@dataclass
class PublishResult:
    channel: str
    ok: bool
    error: str | None = None
    post_id: str | None = None


class Publisher:
    """Контракт publisher-а. Конкретные реализации — в отдельных модулях."""
    name: str = "base"

    def is_configured(self) -> bool:
        raise NotImplementedError

    def publish(
        self,
        text: str,
        image_url: str | None,
        image_bytes: bytes | None,
    ) -> PublishResult:
        raise NotImplementedError

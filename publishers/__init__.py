"""Пакет publishers: абстракция над Telegram/Facebook/Instagram публикацией."""

from .base import Publisher, PublishResult
from .telegram import TelegramPublisher
from .facebook import FacebookPublisher
from .instagram import InstagramPublisher

__all__ = [
    "Publisher",
    "PublishResult",
    "TelegramPublisher",
    "FacebookPublisher",
    "InstagramPublisher",
]

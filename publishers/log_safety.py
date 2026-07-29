"""Маскирование секретов (токенов) в логах.

Публикация в внешние API (Telegram, Graph API) может упасть с сетевой
ошибкой (ConnectionError/HTTPError/Retry), а requests вшивает в текст такого
исключения полный URL запроса — вместе с токеном бота или access_token.
Если такое исключение просто залогировать как `{e}`, токен утечёт в
logs/post.log и logs/cron.log.

Этот модуль даёт:
  - SecretRedactionFilter — logging.Filter, который редактирует сообщение
    ЛЮБОЙ лог-записи (и record.msg, и record.args) до того, как она попадёт
    в хендлеры (файл/stdout).
  - install_filter() — вешает фильтр на root-логгер. Идемпотентно и не
    зависит от того, кто и когда настраивает логгер (post_bot.py делает это
    через logging.basicConfig в setup_logging(), которая может быть вызвана
    до или после импорта publishers) — фильтр, повешенный на сам Logger,
    применяется к записи раньше, чем она уходит в любые хендлеры, в т.ч.
    те, что будут добавлены позже.
  - redact_text() / describe_exception() — для явного редактирования текста
    прямо в except-блоках publisher-ов (defense in depth поверх фильтра).
"""

import logging
import re

# https://api.telegram.org/bot<TOKEN>/sendPhoto — токен вида "123456:AAFake..."
_TELEGRAM_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")

# Graph API: access_token=... / ?access_token=... / "access_token": "..."
_GRAPH_TOKEN_RE = re.compile(
    r'(access_token["\']?\s*[:=]\s*["\']?)([^"\'&\s]+)',
    re.IGNORECASE,
)

_TELEGRAM_REPLACEMENT = "bot***REDACTED***"
_GRAPH_REPLACEMENT = r"\1***REDACTED***"


def redact_text(text: str) -> str:
    """Заменяет токен Telegram-бота и access_token Graph API на плейсхолдер."""
    if not isinstance(text, str):
        return text
    text = _TELEGRAM_TOKEN_RE.sub(_TELEGRAM_REPLACEMENT, text)
    text = _GRAPH_TOKEN_RE.sub(_GRAPH_REPLACEMENT, text)
    return text


def describe_exception(e: BaseException) -> str:
    """Тип исключения + отредактированное сообщение — вместо голого `{e}`."""
    return f"{type(e).__name__}: {redact_text(str(e))}"


class SecretRedactionFilter(logging.Filter):
    """Редактирует секреты в message и args любой лог-записи."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: redact_text(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            else:
                record.args = tuple(
                    redact_text(a) if isinstance(a, str) else a for a in record.args
                )
        return True


def install_filter() -> None:
    """Вешает SecretRedactionFilter на root-логгер И на его хендлеры.

    Фильтр на самом Logger применяется только к записям, созданным ЧЕРЕЗ этот
    логгер (logging.info(...) в нашем коде). Записи дочерних логгеров
    (requests/urllib3 и т.п.) всплывают сразу в хендлеры root-а, минуя его
    фильтры — поэтому тот же фильтр вешаем и на каждый хендлер.

    Идемпотентно; вызывать можно повторно (в т.ч. после того, как хендлеры
    появились — setup_logging() вызывает install_filter() после basicConfig).
    """
    root = logging.getLogger()
    if not any(isinstance(f, SecretRedactionFilter) for f in root.filters):
        root.addFilter(SecretRedactionFilter())
    for handler in root.handlers:
        if not any(isinstance(f, SecretRedactionFilter) for f in handler.filters):
            handler.addFilter(SecretRedactionFilter())

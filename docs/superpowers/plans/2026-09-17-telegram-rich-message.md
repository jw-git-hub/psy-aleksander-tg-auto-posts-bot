# Публикация в Telegram «Статьёй» (sendRichMessage) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** добавить второй формат публикации в Telegram — одно расширенное сообщение (картинка + текст) — за переключателем, выключенным по умолчанию, с откатом на текущий формат при явном отказе Telegram.

**Architecture:** `TelegramPublisher` получает параметр `post_format` (`classic` | `rich`). Rich собирается чистой функцией в новом модуле `publishers/telegram_rich.py` (режим `blocks` Bot API) и отправляется через `sendRichMessage` multipart-запросом с картинкой. Текущий путь `sendPhoto` + `sendMessage` выносится в `_publish_classic` без изменения поведения и служит запасным вариантом. Отдельный скрипт `preview_telegram_format.py` шлёт образцы только в тестовый канал.

**Tech Stack:** Python 3.10, requests, pytest 9.1.1 (только для тестов), Telegram Bot API 10.3.

**Spec:** `docs/superpowers/specs/2026-09-17-telegram-rich-message-design.md`

## Global Constraints

- Работать только в worktree `.claude/worktrees/telegram-rich-message` (ветка `worktree-telegram-rich-message`). Основную папку проекта не трогать: из неё cron запускает живого бота.
- Интерпретатор — из worktree: `../../../venv/bin/python3` (Python 3.10.12, pytest 9.1.1 уже установлен). Все команды ниже запускаются из корня worktree.
- Новых runtime-зависимостей нет. `pytest==9.1.1` — только в `requirements-dev.txt`.
- Никаких реальных запросов к Telegram во время реализации: в тестах сеть подменена.
- `.env` и `config.json` не читать, не создавать, не печатать. Репозиторий публичный: никаких токенов, id каналов, имён, абсолютных путей с именем пользователя.
- Сообщения коммитов — на русском, заканчиваются содержательной строкой. **Никаких** трейлеров `Co-Authored-By: …` и `Claude-Session: …`.
- Не менять: строку `logging.info(f"Опубликовано: {topic} (цикл {current_cycle})")` (по ней `run_with_retry.sh` определяет успех), `run_with_retry.sh`, `POST_MAX_LEN`, валидаторы и фильтры утечек, `publishers/facebook.py`, `publishers/instagram.py`, дедупликацию, cron.
- Формат по умолчанию — `classic`. Переключатель `telegram_post_format` читается **только** из `config.json`, переменной окружения для него нет.
- Логи и комментарии — на русском, в стиле существующего кода. Исключения логировать через `describe_exception(e)`, токен в логи не выводить.

## Карта файлов

| Файл | Что делает |
|---|---|
| `pytest.ini` (новый) | `testpaths = tests`, корень проекта в `sys.path` |
| `requirements-dev.txt` (новый) | runtime-зависимости + pytest |
| `tests/__init__.py` (новый, пустой) | делает `tests` пакетом для `from tests.tg_fakes import …` |
| `tests/tg_fakes.py` (новый) | поддельный Bot API: `FakeResponse`, `ok`, `error`, `not_json`, `timeout`, `FakeTelegram` |
| `tests/conftest.py` (новый) | фикстуры `fake_tg`, `sleeps` (autouse), `bot_config` |
| `tests/test_telegram_classic.py` (новый) | характеризация текущей отправки |
| `publishers/telegram_rich.py` (новый) | `build_rich_message(text)` — блоки «Статьи» |
| `tests/test_telegram_rich_builder.py` (новый) | тесты сборки блоков |
| `publishers/base.py` | `PublishResult.post_format` |
| `publishers/telegram.py` | `post_format`, `_publish_classic`, `_send_rich`, `_truncate_text` |
| `tests/test_telegram_rich_publish.py` (новый) | тесты rich-отправки и запасного варианта |
| `post_bot.py` | передача `post_format`, `_telegram_record_fields`, `TELEGRAM_TEST_CHAT_ID` |
| `tests/test_post_bot_wiring.py` (новый) | тесты связки с `post_bot.py` |
| `preview_telegram_format.py` (новый) | образцы постов в тестовый канал |
| `tests/test_preview_telegram_format.py` (новый) | тесты защит скрипта |
| `config.example.json`, `.env.example`, `README.md`, `CLAUDE.md`, `JOURNAL.md` | документация |

---

### Task 1: Тестовая инфраструктура и характеризация текущей отправки

Тесты этой задачи фиксируют поведение **существующего** кода. Они должны пройти сразу, без правок в `publishers/` — это страховка от регрессий в следующих задачах. Если какой-то тест падает, код не менять: остановиться и сообщить, какое реальное поведение отличается от описанного.

**Files:**
- Create: `pytest.ini`
- Create: `requirements-dev.txt`
- Create: `tests/__init__.py`
- Create: `tests/tg_fakes.py`
- Create: `tests/conftest.py`
- Create: `tests/test_telegram_classic.py`

**Interfaces:**
- Consumes: `publishers.TelegramPublisher(bot_token, chat_id, retry_max=3)` и его `publish(text, image_url, image_bytes) -> PublishResult` (текущий код).
- Produces:
  - `tests.tg_fakes.FakeResponse(status_code: int, payload: dict | None = None, json_error: Exception | None = None)` с методом `json()`;
  - `tests.tg_fakes.ok(message_id: int) -> FakeResponse`;
  - `tests.tg_fakes.error(status_code: int, description: str, **parameters) -> FakeResponse`;
  - `tests.tg_fakes.not_json(status_code: int = 502) -> FakeResponse`;
  - `tests.tg_fakes.timeout() -> requests.Timeout`;
  - `tests.tg_fakes.FakeTelegram` с методами `script(method, *outcomes)`, `post(url, **kwargs)`, `methods() -> list[str]`, `kwargs(index) -> dict` и полем `calls: list[tuple[str, dict]]`;
  - фикстуры `fake_tg` (подменяет `requests.post`) и `sleeps` (autouse, подменяет `time.sleep`, возвращает список пауз).

- [ ] **Step 1: Создать `pytest.ini`**

```ini
[pytest]
testpaths = tests
pythonpath = .
```

- [ ] **Step 2: Создать `requirements-dev.txt`**

```text
-r requirements.txt
pytest==9.1.1
```

- [ ] **Step 3: Создать пустой `tests/__init__.py`**

```bash
touch tests/__init__.py
```

(каталог `tests/` создать, если его нет: `mkdir -p tests`)

- [ ] **Step 4: Создать `tests/tg_fakes.py`**

```python
"""Поддельный Telegram Bot API для тестов publisher-а: без сети и без ожиданий."""

import requests


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None,
                 json_error: Exception | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


def ok(message_id: int) -> FakeResponse:
    return FakeResponse(200, {
        "ok": True,
        "result": {"message_id": message_id, "chat": {"id": -100500}, "date": 0},
    })


def error(status_code: int, description: str, **parameters) -> FakeResponse:
    payload = {"ok": False, "error_code": status_code, "description": description}
    if parameters:
        payload["parameters"] = parameters
    return FakeResponse(status_code, payload)


def not_json(status_code: int = 502) -> FakeResponse:
    """Ответ, который не разбирается как JSON (например, HTML-страница прокси)."""
    return FakeResponse(status_code, json_error=ValueError("not json"))


def timeout() -> requests.Timeout:
    return requests.Timeout("read timed out")


class FakeTelegram:
    """Подменяет requests.post: отдаёт заранее заданные ответы по имени метода Bot API."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self._outcomes: dict[str, list] = {}

    def script(self, method: str, *outcomes) -> None:
        self._outcomes.setdefault(method, []).extend(outcomes)

    def post(self, url: str, **kwargs):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, kwargs))
        queue = self._outcomes.get(method)
        if not queue:
            raise AssertionError(f"Неожиданный вызов Bot API: {method}")
        outcome = queue.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def methods(self) -> list[str]:
        return [method for method, _ in self.calls]

    def kwargs(self, index: int) -> dict:
        return self.calls[index][1]
```

- [ ] **Step 5: Создать `tests/conftest.py`**

```python
import pytest

import publishers.telegram as telegram_module
from tests.tg_fakes import FakeTelegram


@pytest.fixture
def fake_tg(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(telegram_module.requests, "post", fake.post)
    return fake


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Никаких реальных пауз в тестах; записываем, сколько ждал бы код."""
    recorded: list[float] = []
    monkeypatch.setattr(telegram_module.time, "sleep", recorded.append)
    return recorded
```

- [ ] **Step 6: Создать `tests/test_telegram_classic.py`**

```python
"""Характеризация текущей отправки в Telegram (classic): sendPhoto, затем sendMessage.

Тесты фиксируют поведение ДО добавления формата rich и должны проходить
без изменений после него.
"""

from publishers import TelegramPublisher
from tests.tg_fakes import error, ok, timeout

CHAT_ID = "-100500"


def make_publisher() -> TelegramPublisher:
    return TelegramPublisher(bot_token="123:TEST", chat_id=CHAT_ID, retry_max=3)


def test_photo_then_text_two_messages(fake_tg):
    fake_tg.script("sendPhoto", ok(10))
    fake_tg.script("sendMessage", ok(11))

    result = make_publisher().publish("Текст поста", None, b"jpeg-bytes")

    assert result.ok is True
    assert result.channel == "telegram"
    assert result.post_id == "11"
    assert result.photo_post_id == "10"
    assert fake_tg.methods() == ["sendPhoto", "sendMessage"]
    photo = fake_tg.kwargs(0)
    assert photo["data"] == {"chat_id": CHAT_ID}
    assert photo["files"] == {"photo": ("image.jpg", b"jpeg-bytes", "image/jpeg")}
    assert photo["timeout"] == 30
    message = fake_tg.kwargs(1)
    assert message["json"] == {
        "chat_id": CHAT_ID,
        "text": "Текст поста",
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    assert message["timeout"] == 30


def test_without_image_only_text(fake_tg):
    fake_tg.script("sendMessage", ok(11))

    result = make_publisher().publish("Текст поста", None, None)

    assert result.ok is True
    assert result.post_id == "11"
    assert result.photo_post_id is None
    assert fake_tg.methods() == ["sendMessage"]


def test_photo_failure_text_still_sent(fake_tg):
    fake_tg.script("sendPhoto", error(400, "Bad Request: IMAGE_PROCESS_FAILED"))
    fake_tg.script("sendMessage", ok(11))

    result = make_publisher().publish("Текст поста", None, b"jpeg-bytes")

    assert result.ok is True
    assert result.post_id == "11"
    assert result.photo_post_id is None
    assert fake_tg.methods() == ["sendPhoto", "sendMessage"]


def test_text_refused_returns_error(fake_tg):
    fake_tg.script("sendMessage", error(400, "Bad Request: chat not found"))

    result = make_publisher().publish("Текст поста", None, None)

    assert result.ok is False
    assert "chat not found" in result.error
    assert fake_tg.methods() == ["sendMessage"]


def test_429_waits_retry_after_and_retries(fake_tg, sleeps):
    fake_tg.script(
        "sendMessage",
        error(429, "Too Many Requests: retry after 7", retry_after=7),
        ok(11),
    )

    result = make_publisher().publish("Текст поста", None, None)

    assert result.ok is True
    assert 7 in sleeps
    assert fake_tg.methods() == ["sendMessage", "sendMessage"]


def test_5xx_retries(fake_tg, sleeps):
    fake_tg.script("sendMessage", error(502, "Bad Gateway"), ok(11))

    result = make_publisher().publish("Текст поста", None, None)

    assert result.ok is True
    assert 2 in sleeps


def test_network_error_retries(fake_tg):
    fake_tg.script("sendMessage", timeout(), ok(11))

    result = make_publisher().publish("Текст поста", None, None)

    assert result.ok is True
    assert fake_tg.methods() == ["sendMessage", "sendMessage"]


def test_html_parse_error_resends_without_parse_mode(fake_tg):
    fake_tg.script(
        "sendMessage",
        error(400, "Bad Request: can't parse entities: unsupported start tag"),
        ok(12),
    )

    result = make_publisher().publish("a < b", None, None)

    assert result.ok is True
    assert result.post_id == "12"
    assert "parse_mode" not in fake_tg.kwargs(1)["json"]


def test_long_text_truncated_to_4093(fake_tg):
    fake_tg.script("sendMessage", ok(11))

    make_publisher().publish("а" * 5000, None, None)

    sent = fake_tg.kwargs(0)["json"]["text"]
    assert len(sent) == 4093
    assert sent.endswith("...")


def test_retries_exhausted(fake_tg):
    fake_tg.script(
        "sendMessage",
        error(500, "Internal"), error(500, "Internal"), error(500, "Internal"),
    )

    result = make_publisher().publish("Текст поста", None, None)

    assert result.ok is False
    assert result.error == "retries exhausted"
    assert fake_tg.methods() == ["sendMessage"] * 3
```

- [ ] **Step 7: Запустить тесты — ожидается PASS на неизменённом коде**

Run: `../../../venv/bin/python3 -m pytest -q`
Expected: `10 passed`. Если что-то падает — **не править** `publishers/`, остановиться и доложить.

- [ ] **Step 8: Убедиться, что код бота не менялся**

Run: `git status --short`
Expected: только новые файлы `pytest.ini`, `requirements-dev.txt`, `tests/…`.

- [ ] **Step 9: Commit**

```bash
git add pytest.ini requirements-dev.txt tests/__init__.py tests/tg_fakes.py tests/conftest.py tests/test_telegram_classic.py
git commit -m "Тесты: поддельный Bot API и характеризация текущей отправки в Telegram"
```

---

### Task 2: Сборка блоков «Статьи»

**Files:**
- Create: `publishers/telegram_rich.py`
- Test: `tests/test_telegram_rich_builder.py`

**Interfaces:**
- Consumes: ничего из предыдущих задач, кроме `pytest.ini`.
- Produces:
  - `publishers.telegram_rich.RICH_COVER_ATTACH: str = "cover"` — имя multipart-части с картинкой;
  - `publishers.telegram_rich.RICH_MAX_BLOCKS: int = 500`;
  - `publishers.telegram_rich.build_rich_message(text: str) -> dict | None` — `{"blocks": [...]}` или `None`.

- [ ] **Step 1: Написать падающие тесты `tests/test_telegram_rich_builder.py`**

```python
import json

from publishers.telegram_rich import RICH_COVER_ATTACH, RICH_MAX_BLOCKS, build_rich_message

PHOTO_BLOCK = {"type": "photo", "photo": {"type": "photo", "media": "attach://cover"}}


def test_photo_first_then_paragraph_per_line():
    text = (
        "Первый абзац.\nВторая строка абзаца.\n\n"
        "— пункт один\n— пункт два\n\n"
        "#отношения #психология"
    )

    assert build_rich_message(text) == {
        "blocks": [
            PHOTO_BLOCK,
            {"type": "paragraph", "text": "Первый абзац."},
            {"type": "paragraph", "text": "Вторая строка абзаца."},
            {"type": "paragraph", "text": "— пункт один"},
            {"type": "paragraph", "text": "— пункт два"},
            {"type": "paragraph", "text": "#отношения #психология"},
        ]
    }


def test_cover_attach_name():
    assert RICH_COVER_ATTACH == "cover"


def test_whitespace_trimmed_and_blank_lines_dropped():
    message = build_rich_message("\n\n   текст с пробелами   \n \t \n")

    assert message["blocks"][1:] == [{"type": "paragraph", "text": "текст с пробелами"}]


def test_special_characters_kept_verbatim():
    line = 'a < b && c > d "кавычки" \'апостроф\' <b>не тег</b> &amp;'

    message = build_rich_message(line)

    assert message["blocks"][1] == {"type": "paragraph", "text": line}


def test_empty_text_returns_none():
    assert build_rich_message("") is None
    assert build_rich_message("  \n\n \t ") is None


def test_block_limit():
    assert RICH_MAX_BLOCKS == 500
    fits = "\n".join(f"строка {i}" for i in range(RICH_MAX_BLOCKS - 1))
    assert len(build_rich_message(fits)["blocks"]) == RICH_MAX_BLOCKS
    too_many = "\n".join(f"строка {i}" for i in range(RICH_MAX_BLOCKS))
    assert build_rich_message(too_many) is None


def test_serializable_to_json():
    message = build_rich_message("Привет & пока")

    assert json.loads(json.dumps(message, ensure_ascii=False)) == message
```

- [ ] **Step 2: Запустить — ожидается FAIL**

Run: `../../../venv/bin/python3 -m pytest tests/test_telegram_rich_builder.py -q`
Expected: ошибка сбора `ModuleNotFoundError: No module named 'publishers.telegram_rich'`.

- [ ] **Step 3: Создать `publishers/telegram_rich.py`**

```python
"""Сборка расширенного сообщения («Статьи») для sendRichMessage.

Используется режим blocks, а не html: текст поста уходит простой строкой,
поэтому не нужно HTML-экранирование и не нужны ссылки tg://photo?id=, про
которые документация Bot API противоречит сама себе («Media blocks support
only HTTP and HTTPS URLs»).
"""

# Имя multipart-части с картинкой: InputMediaPhoto.media = "attach://cover".
RICH_COVER_ATTACH = "cover"

# Лимит Bot API: «Up to 500 blocks, including nested blocks…».
RICH_MAX_BLOCKS = 500


def build_rich_message(text: str) -> dict | None:
    """InputRichMessage: блок-картинка, затем абзац на каждую непустую строку.

    Как Telegram показывает перенос строки внутри абзаца, в документации не
    описано, поэтому каждая непустая строка — отдельный абзац: так список
    «— пункт» не склеится в одну строку. Возвращает None, если текста нет или
    блоков больше лимита, — тогда пост отправляется по-старому (classic).
    """
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    if not paragraphs or len(paragraphs) + 1 > RICH_MAX_BLOCKS:
        return None
    blocks = [{
        "type": "photo",
        "photo": {"type": "photo", "media": f"attach://{RICH_COVER_ATTACH}"},
    }]
    blocks.extend({"type": "paragraph", "text": paragraph} for paragraph in paragraphs)
    return {"blocks": blocks}
```

- [ ] **Step 4: Запустить — ожидается PASS**

Run: `../../../venv/bin/python3 -m pytest -q`
Expected: все тесты зелёные (`17 passed`).

- [ ] **Step 5: Commit**

```bash
git add publishers/telegram_rich.py tests/test_telegram_rich_builder.py
git commit -m "Сборка блоков «Статьи» для sendRichMessage: картинка и абзац на каждую строку"
```

---

### Task 3: Формат rich в `TelegramPublisher` с запасным вариантом classic

**Files:**
- Modify: `publishers/base.py` (dataclass `PublishResult`)
- Modify: `publishers/telegram.py` (весь файл, итоговый текст ниже)
- Test: `tests/test_telegram_rich_publish.py`

**Interfaces:**
- Consumes: `build_rich_message`, `RICH_COVER_ATTACH` (Task 2); фикстуры `fake_tg`, `sleeps` и хелперы `tests.tg_fakes` (Task 1).
- Produces:
  - `PublishResult.post_format: str | None = None` (`"classic"` / `"rich"` у Telegram, `None` у FB/IG);
  - `TelegramPublisher(bot_token: str, chat_id: str, retry_max: int = 3, post_format: str = "classic")`, атрибут `post_format` (нормализованный: `"classic"` или `"rich"`);
  - `publishers.telegram.POST_FORMATS = ("classic", "rich")`.

- [ ] **Step 1: Написать падающие тесты `tests/test_telegram_rich_publish.py`**

```python
import json
import logging

import pytest

from publishers import TelegramPublisher
from publishers.telegram_rich import build_rich_message
from tests.tg_fakes import error, not_json, ok, timeout

CHAT_ID = "-100500"
TEXT = "Первый абзац поста.\n\nВторой абзац.\n#отношения"
IMAGE = b"jpeg-bytes"


def rich_publisher() -> TelegramPublisher:
    return TelegramPublisher(bot_token="123:TEST", chat_id=CHAT_ID, retry_max=3,
                             post_format="rich")


@pytest.mark.parametrize("value, expected", [
    ("classic", "classic"),
    ("rich", "rich"),
    (" RICH ", "rich"),
    (None, "classic"),
    ("", "classic"),
])
def test_post_format_normalized(value, expected):
    assert TelegramPublisher("t", "c", post_format=value).post_format == expected


def test_default_post_format_is_classic():
    assert TelegramPublisher("t", "c").post_format == "classic"


def test_unknown_post_format_falls_back_to_classic_with_warning(caplog):
    with caplog.at_level(logging.WARNING):
        publisher = TelegramPublisher("t", "c", post_format="fancy")

    assert publisher.post_format == "classic"
    assert "fancy" in caplog.text


def test_classic_result_marked_classic(fake_tg):
    fake_tg.script("sendPhoto", ok(10))
    fake_tg.script("sendMessage", ok(11))

    result = TelegramPublisher("t", CHAT_ID).publish(TEXT, None, IMAGE)

    assert result.post_format == "classic"


def test_rich_sends_one_message_with_photo(fake_tg):
    fake_tg.script("sendRichMessage", ok(21))

    result = rich_publisher().publish(TEXT, None, IMAGE)

    assert result.ok is True
    assert result.post_id == "21"
    assert result.photo_post_id is None
    assert result.post_format == "rich"
    assert fake_tg.methods() == ["sendRichMessage"]
    call = fake_tg.kwargs(0)
    assert call["data"]["chat_id"] == CHAT_ID
    assert json.loads(call["data"]["rich_message"]) == build_rich_message(TEXT)
    assert call["files"] == {"cover": ("image.jpg", IMAGE, "image/jpeg")}
    assert call["timeout"] == 30


def test_rich_payload_keeps_cyrillic_readable(fake_tg):
    fake_tg.script("sendRichMessage", ok(21))

    rich_publisher().publish(TEXT, None, IMAGE)

    assert "Первый абзац" in fake_tg.kwargs(0)["data"]["rich_message"]


def test_rich_without_image_goes_classic(fake_tg):
    fake_tg.script("sendMessage", ok(11))

    result = rich_publisher().publish(TEXT, None, None)

    assert result.ok is True
    assert result.post_format == "classic"
    assert fake_tg.methods() == ["sendMessage"]


def test_rich_too_many_blocks_goes_classic_without_rich_request(fake_tg):
    fake_tg.script("sendPhoto", ok(10))
    fake_tg.script("sendMessage", ok(11))
    text = "\n".join("с" for _ in range(600))  # 600 строк, 1199 символов

    result = rich_publisher().publish(text, None, IMAGE)

    assert result.post_format == "classic"
    assert fake_tg.methods() == ["sendPhoto", "sendMessage"]


def test_long_text_truncated_before_rich(fake_tg):
    fake_tg.script("sendRichMessage", ok(21))

    rich_publisher().publish("а" * 5000, None, IMAGE)

    blocks = json.loads(fake_tg.kwargs(0)["data"]["rich_message"])["blocks"]
    assert blocks[1]["text"] == "а" * 4090 + "..."


@pytest.mark.parametrize("refusal", [
    error(400, "Bad Request: RICH_MESSAGE_INVALID"),
    error(403, "Forbidden: not enough rights to send photos to the chat"),
])
def test_explicit_refusal_falls_back_to_classic(fake_tg, caplog, refusal):
    fake_tg.script("sendRichMessage", refusal)
    fake_tg.script("sendPhoto", ok(10))
    fake_tg.script("sendMessage", ok(11))

    with caplog.at_level(logging.WARNING):
        result = rich_publisher().publish(TEXT, None, IMAGE)

    assert result.ok is True
    assert result.post_format == "classic"
    assert result.post_id == "11"
    assert result.photo_post_id == "10"
    assert fake_tg.methods() == ["sendRichMessage", "sendPhoto", "sendMessage"]
    assert refusal.json()["description"] in caplog.text


def test_timeouts_exhausted_fail_without_classic(fake_tg):
    fake_tg.script("sendRichMessage", timeout(), timeout(), timeout())

    result = rich_publisher().publish(TEXT, None, IMAGE)

    assert result.ok is False
    assert result.error == "rich retries exhausted"
    assert fake_tg.methods() == ["sendRichMessage"] * 3


def test_5xx_exhausted_fail_without_classic(fake_tg):
    fake_tg.script(
        "sendRichMessage",
        error(502, "Bad Gateway"), error(502, "Bad Gateway"), error(502, "Bad Gateway"),
    )

    result = rich_publisher().publish(TEXT, None, IMAGE)

    assert result.ok is False
    assert fake_tg.methods() == ["sendRichMessage"] * 3


@pytest.mark.parametrize("unclear", [timeout(), error(502, "Bad Gateway"), not_json()])
def test_refusal_after_unclear_attempt_fails_without_classic(fake_tg, unclear):
    # Первая попытка могла создать сообщение — classic после неё дал бы дубль.
    fake_tg.script("sendRichMessage", unclear, error(400, "Bad Request: RICH_MESSAGE_INVALID"))

    result = rich_publisher().publish(TEXT, None, IMAGE)

    assert result.ok is False
    assert "RICH_MESSAGE_INVALID" in result.error
    assert fake_tg.methods() == ["sendRichMessage", "sendRichMessage"]


def test_429_then_refusal_still_falls_back(fake_tg, sleeps):
    # 429 — однозначный отказ: сообщение не создано, classic безопасен.
    fake_tg.script(
        "sendRichMessage",
        error(429, "Too Many Requests: retry after 3", retry_after=3),
        error(400, "Bad Request: RICH_MESSAGE_INVALID"),
    )
    fake_tg.script("sendPhoto", ok(10))
    fake_tg.script("sendMessage", ok(11))

    result = rich_publisher().publish(TEXT, None, IMAGE)

    assert result.ok is True
    assert result.post_format == "classic"
    assert 3 in sleeps
    assert fake_tg.methods() == [
        "sendRichMessage", "sendRichMessage", "sendPhoto", "sendMessage",
    ]


def test_429_then_success(fake_tg, sleeps):
    fake_tg.script(
        "sendRichMessage",
        error(429, "Too Many Requests: retry after 5", retry_after=5),
        ok(21),
    )

    result = rich_publisher().publish(TEXT, None, IMAGE)

    assert result.ok is True
    assert result.post_format == "rich"
    assert 5 in sleeps


def test_timeout_then_success(fake_tg):
    fake_tg.script("sendRichMessage", timeout(), ok(21))

    result = rich_publisher().publish(TEXT, None, IMAGE)

    assert result.ok is True
    assert result.post_format == "rich"
    assert fake_tg.methods() == ["sendRichMessage", "sendRichMessage"]
```

- [ ] **Step 2: Запустить — ожидается FAIL**

Run: `../../../venv/bin/python3 -m pytest tests/test_telegram_rich_publish.py -q`
Expected: падения с `TypeError: TelegramPublisher.__init__() got an unexpected keyword argument 'post_format'` и `AttributeError: 'PublishResult' object has no attribute 'post_format'`.

- [ ] **Step 3: Добавить поле в `publishers/base.py`**

В `PublishResult` после строки `photo_post_id: str | None = None` добавить:

```python
    post_format: str | None = None
```

- [ ] **Step 4: Заменить `publishers/telegram.py` целиком на этот текст**

Функции `_send_photo` и `_send_message` переносятся без изменений, кроме одного места: обрез текста в `_send_message` теперь делает `_truncate_text` (сообщение в логе то же).

```python
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

        RICH_REJECTED — только если Telegram явно отказал, а все предыдущие
        попытки закончились однозначно (429): сообщение точно не создано.
        Сеть, 5xx или ответ не-JSON делают исход неясным — дальше только
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
            except Exception as e:
                unclear = True
                logging.error(
                    f"Ошибка отправки rich-сообщения (попытка {attempt}/{self.retry_max}): "
                    f"{describe_exception(e)}"
                )
                if attempt < self.retry_max:
                    time.sleep(2)
                continue

            if data.get("ok"):
                msg_id = data.get("result", {}).get("message_id")
                logging.info(
                    f"Rich-сообщение («Статья») отправлено в канал "
                    f"(msg_id={msg_id if msg_id is not None else '?'})"
                )
                return RICH_OK, msg_id if isinstance(msg_id, int) else None, None

            if resp.status_code == 429:
                retry_after = data.get("parameters", {}).get("retry_after", 5)
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
```

- [ ] **Step 5: Проверить, что `_send_photo` и `_send_message` не изменились по смыслу**

Run: `git diff -U0 publishers/telegram.py`
Expected: в теле `_send_photo` и `_send_message` изменён только блок обреза (4 строки `if len(text) > 4096: …` заменены на `text = _truncate_text(text)`); остальное — добавленный код.

- [ ] **Step 6: Запустить все тесты — ожидается PASS**

Run: `../../../venv/bin/python3 -m pytest -q`
Expected: все зелёные, в том числе 10 характеризационных тестов из Task 1 **без правок**.

- [ ] **Step 7: Commit**

```bash
git add publishers/base.py publishers/telegram.py tests/test_telegram_rich_publish.py
git commit -m "TelegramPublisher: формат rich (sendRichMessage) с откатом на classic при явном отказе Telegram"
```

---

### Task 4: Связка с `post_bot.py`, трекер тем и документация формата

**Files:**
- Modify: `post_bot.py` (`_build_publishers` ~стр. 1736, новая функция `_telegram_record_fields` перед ней, запись в `main()` ~стр. 2445–2448)
- Modify: `tests/conftest.py` (фикстура `bot_config`)
- Test: `tests/test_post_bot_wiring.py`
- Modify: `config.example.json`, `README.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: `TelegramPublisher(..., post_format=...)`, `PublishResult.post_format` (Task 3).
- Produces:
  - `post_bot._telegram_record_fields(config: dict, tg_result: PublishResult) -> dict` с ключами `telegram_chat_id`, `telegram_message_id`, `telegram_photo_message_id`, `telegram_post_format`;
  - фикстура `bot_config` в `tests/conftest.py`: вызывается как `bot_config(**values)`, пишет `config.json` (с `telegram_bot_token="123:TEST"`, `telegram_chat_id="-100500"` плюс `values`) во временную папку, подменяет `post_bot.BASE_DIR`, очищает переменные окружения `CONFIG_ENV_KEYS`.

- [ ] **Step 1: Дописать в `tests/conftest.py` фикстуру `bot_config`**

Итоговый файл целиком:

```python
import json

import pytest

import post_bot
import publishers.telegram as telegram_module
from tests.tg_fakes import FakeTelegram

CONFIG_ENV_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_TEST_CHAT_ID",
    "TELEGRAM_POST_FORMAT",
    "FACEBOOK_PAGE_ID",
    "FACEBOOK_PAGE_ACCESS_TOKEN",
    "INSTAGRAM_BUSINESS_ACCOUNT_ID",
)


@pytest.fixture
def fake_tg(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(telegram_module.requests, "post", fake.post)
    return fake


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Никаких реальных пауз в тестах; записываем, сколько ждал бы код."""
    recorded: list[float] = []
    monkeypatch.setattr(telegram_module.time, "sleep", recorded.append)
    return recorded


@pytest.fixture
def bot_config(tmp_path, monkeypatch):
    """config.json во временной папке для post_bot.load_config(); окружение очищено."""
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(post_bot, "BASE_DIR", tmp_path)

    def write(**values) -> None:
        config = {"telegram_bot_token": "123:TEST", "telegram_chat_id": "-100500"}
        config.update(values)
        (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")

    return write
```

- [ ] **Step 2: Написать тесты `tests/test_post_bot_wiring.py`**

```python
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
```

- [ ] **Step 3: Запустить — ожидается FAIL**

Run: `../../../venv/bin/python3 -m pytest tests/test_post_bot_wiring.py -q`
Expected: падают `test_build_publishers_passes_post_format` (`'classic' == 'rich'`), оба `test_record_fields_*` (`AttributeError: … '_telegram_record_fields'`), `test_main_uses_record_fields_helper`. Остальные проходят.

- [ ] **Step 4: Передать формат в `_build_publishers` (`post_bot.py`)**

Было:

```python
        TelegramPublisher(
            bot_token=config.get("telegram_bot_token", ""),
            chat_id=config.get("telegram_chat_id", ""),
            retry_max=config.get("retry_max", 3),
        ),
```

Стало:

```python
        TelegramPublisher(
            bot_token=config.get("telegram_bot_token", ""),
            chat_id=config.get("telegram_chat_id", ""),
            retry_max=config.get("retry_max", 3),
            post_format=config.get("telegram_post_format", "classic"),
        ),
```

- [ ] **Step 5: Добавить `_telegram_record_fields` в `post_bot.py`**

Вставить сразу перед строкой `def _build_publishers(config: dict) -> list:`:

```python
def _telegram_record_fields(config: dict, tg_result: PublishResult) -> dict:
    """Telegram-поля записи posted-topics.json — по ним потом правят пост.

    Rich-пост («Статья») правится через editMessageText с rich_message, а не
    с text, поэтому формат сохраняется вместе с message_id.
    """
    return {
        "telegram_chat_id": config.get("telegram_chat_id"),
        "telegram_message_id": int(tg_result.post_id) if tg_result.post_id else None,
        "telegram_photo_message_id": int(tg_result.photo_post_id) if tg_result.photo_post_id else None,
        "telegram_post_format": tg_result.post_format,
    }


```

- [ ] **Step 6: Использовать её в `main()` (`post_bot.py`)**

Было:

```python
                # Только для новых записей: старые посты публиковались до того,
                # как TelegramPublisher начал возвращать message_id, — бэкфилить их нечем.
                "telegram_chat_id": config.get("telegram_chat_id"),
                "telegram_message_id": int(tg_result.post_id) if tg_result.post_id else None,
                "telegram_photo_message_id": int(tg_result.photo_post_id) if tg_result.photo_post_id else None,
            })
```

Стало:

```python
                # Только для новых записей: старые посты публиковались до того,
                # как TelegramPublisher начал возвращать message_id, — бэкфилить их нечем.
                **_telegram_record_fields(config, tg_result),
            })
```

- [ ] **Step 7: Запустить все тесты — ожидается PASS**

Run: `../../../venv/bin/python3 -m pytest -q`
Expected: все зелёные.

- [ ] **Step 8: `config.example.json` — добавить ключ формата**

После строки `"telegram_chat_id": "@YOUR_CHANNEL",` добавить:

```json
  "telegram_post_format": "classic",
```

Проверить: `../../../venv/bin/python3 -m json.tool config.example.json > /dev/null` — без ошибок.

- [ ] **Step 9: `README.md` — описание формата (раздел «Как это выглядит»)**

Было:

```markdown
Формат — два отдельных сообщения: сначала `sendPhoto`, затем `sendMessage` с текстом
(так лимит на текст остаётся полным, 4096 символов, а не 1024 как у подписи к фото).
```

Стало:

```markdown
Формат задаётся переключателем `telegram_post_format` в `config.json`. `classic` — два
отдельных сообщения: сначала `sendPhoto`, затем `sendMessage` с текстом (так лимит на текст
остаётся полным, 4096 символов, а не 1024 как у подписи к фото). `rich` — одно расширенное
сообщение («Статья», `sendRichMessage`): картинка сверху, текст абзацами под ней; если
Telegram явно отказал, пост уходит в формате `classic`.
```

- [ ] **Step 10: `README.md` — схема конвейера**

Было:

```text
    E --> F["Публикация<br/>sendPhoto + отдельный sendMessage"]
```

Стало:

```text
    E --> F["Публикация<br/>sendPhoto + sendMessage<br/>или «Статья» (sendRichMessage)"]
```

- [ ] **Step 11: `README.md` — структура проекта**

Было:

```text
  telegram.py          # sendPhoto + sendMessage, retry на 429/5xx, HTML→plain fallback
```

Стало:

```text
  telegram.py          # classic (sendPhoto + sendMessage) или rich (sendRichMessage),
                       #   retry на 429/5xx, HTML→plain fallback, rich→classic при отказе
  telegram_rich.py     # сборка «Статьи»: блок-картинка + абзац на каждую строку
```

И после строки `test_publishers.py     # smoke-test конфигурации publisher-ов, без живых запросов к API` добавить:

```text
tests/                 # pytest без сети: поддельный Bot API, отправка classic/rich
pytest.ini             # настройки pytest
requirements-dev.txt   # зависимости для тестов (pytest)
```

- [ ] **Step 12: `README.md` — команды и таблица `config.json`**

В блоке «Установка и запуск» после строк

```text
# проверка конфигурации без живых запросов к API:
./venv/bin/python3 test_publishers.py
```

добавить:

```text

# автотесты (без сети, ничего не публикуют):
./venv/bin/pip install -r requirements-dev.txt
./venv/bin/python3 -m pytest -q
```

В таблице `config.json` после строки с `retry_max` добавить:

```markdown
| `telegram_post_format` | да | формат поста: `classic` (по умолчанию) или `rich` («Статья»); задаётся только здесь, переменной окружения нет |
```

- [ ] **Step 13: `README.md` — английская часть**

Было:

```markdown
`claude -p` (Sonnet), validates the result, and publishes to Telegram (`sendPhoto` + separate
`sendMessage`). Facebook/Instagram publishing (Graph API v21.0) is best-effort and optional.
```

Стало:

```markdown
`claude -p` (Sonnet), validates the result, and publishes to Telegram (`sendPhoto` + separate
`sendMessage`, or a single rich "Article" message via `sendRichMessage` — switchable in
config, with automatic fallback). Facebook/Instagram publishing (Graph API v21.0) is
best-effort and optional.
```

- [ ] **Step 14: `CLAUDE.md` — правило формата и команда тестов**

Было:

```markdown
- **Формат поста**: сначала sendPhoto (картинка из источника), затем отдельно sendMessage (текст). Два отдельных сообщения — это увеличивает лимит символов для текста. Картинку скачиваем от источника, не генерируем.
```

Стало:

```markdown
- **Формат поста**: переключатель `telegram_post_format` в config.json (только там, без env). `classic` (по умолчанию) — сначала sendPhoto (картинка из источника), затем отдельно sendMessage (текст, лимит 4096). `rich` — одно сообщение-«Статья» (sendRichMessage, режим blocks): картинка сверху, каждая непустая строка — абзац. Явный отказ Telegram → пост уходит classic; неясный исход (сеть, 5xx) → classic НЕ шлём, иначе дубль. Картинку скачиваем от источника, не генерируем.
```

В разделе «Команды» после блока `# Тест публикации` добавить:

```bash
# Автотесты (без сети)
./venv/bin/python3 -m pytest -q
```

- [ ] **Step 15: Commit**

```bash
git add post_bot.py tests/conftest.py tests/test_post_bot_wiring.py config.example.json README.md CLAUDE.md
git commit -m "post_bot: переключатель telegram_post_format, формат поста в posted-topics.json, документация"
```

---

### Task 5: Скрипт проверки в тестовом канале

**Files:**
- Create: `preview_telegram_format.py`
- Modify: `post_bot.py` (`load_config`: переменная `TELEGRAM_TEST_CHAT_ID`)
- Test: `tests/test_preview_telegram_format.py`
- Modify: `config.example.json`, `.env.example`, `README.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: `post_bot.load_config()`; `TelegramPublisher(..., post_format=...)`, `PublishResult.post_format` (Task 3); фикстуры `fake_tg`, `bot_config` и `tests.tg_fakes` (Tasks 1, 4).
- Produces (модуль `preview_telegram_format`):
  - `SAMPLES: list[tuple[str, str]]` — (название, текст);
  - `resolve_test_chat_id(config: dict) -> str` (ValueError при пустом id или совпадении с основным);
  - `ensure_different_channels(token: str, main_ref, test_ref: str) -> None` (ValueError);
  - `extract_channels(updates: list[dict]) -> dict[str, str]`;
  - `find_chat_id(token: str) -> int`;
  - `default_image_path() -> Path`;
  - `send_previews(config: dict, chat_id: str, image_bytes: bytes) -> list[tuple[str, str, PublishResult]]` — (название, ожидаемый формат, результат);
  - `summarize(results) -> tuple[list[str], bool]`;
  - `main(argv: list[str] | None = None) -> int` — коды: 0 всё как ожидалось, 1 есть ошибки или откаты на classic, 2 отказ до отправки.

- [ ] **Step 1: Написать падающие тесты `tests/test_preview_telegram_format.py`**

```python
from pathlib import Path

import pytest

import post_bot
import preview_telegram_format as preview
from publishers import PublishResult
from tests.tg_fakes import FakeResponse, ok

REPO_ROOT = Path(__file__).resolve().parent.parent


def chat_response(chat_id: int) -> FakeResponse:
    return FakeResponse(200, {"ok": True, "result": {"id": chat_id, "type": "channel"}})


def fake_get_chat(monkeypatch, responses: dict) -> None:
    monkeypatch.setattr(
        preview.requests, "get",
        lambda url, **kwargs: responses[kwargs["params"]["chat_id"]],
    )


def forbid_get(monkeypatch) -> None:
    def fail(url, **kwargs):
        raise AssertionError("сетевой вызов не ожидался")
    monkeypatch.setattr(preview.requests, "get", fail)


def test_test_chat_id_env_overrides_config(bot_config, monkeypatch):
    bot_config(telegram_test_chat_id="-100111")
    monkeypatch.setenv("TELEGRAM_TEST_CHAT_ID", "-100222")

    assert post_bot.load_config()["telegram_test_chat_id"] == "-100222"


def test_resolve_test_chat_id_returns_test_channel():
    config = {"telegram_chat_id": "-100500", "telegram_test_chat_id": " -100999 "}

    assert preview.resolve_test_chat_id(config) == "-100999"


@pytest.mark.parametrize("config", [
    {"telegram_chat_id": "-100500"},
    {"telegram_chat_id": "-100500", "telegram_test_chat_id": ""},
    {"telegram_chat_id": "-100500", "telegram_test_chat_id": None},
])
def test_resolve_test_chat_id_requires_value(config):
    with pytest.raises(ValueError, match="telegram_test_chat_id"):
        preview.resolve_test_chat_id(config)


@pytest.mark.parametrize("main_id, test_id", [
    ("-100500", "-100500"),
    (-100500, "-100500"),
    ("@my_channel", "@My_Channel"),
])
def test_resolve_test_chat_id_refuses_main_channel(main_id, test_id):
    with pytest.raises(ValueError, match="совпадает"):
        preview.resolve_test_chat_id({"telegram_chat_id": main_id, "telegram_test_chat_id": test_id})


def test_same_channel_detected_via_get_chat(monkeypatch):
    fake_get_chat(monkeypatch, {
        "@main_channel": chat_response(-100500),
        "-100500": chat_response(-100500),
    })

    with pytest.raises(ValueError, match="совпадает"):
        preview.ensure_different_channels("123:TEST", "@main_channel", "-100500")


def test_different_channels_pass(monkeypatch):
    fake_get_chat(monkeypatch, {
        "-100500": chat_response(-100500),
        "-100999": chat_response(-100999),
    })

    preview.ensure_different_channels("123:TEST", -100500, "-100999")


def test_unreachable_test_channel_refused(monkeypatch):
    fake_get_chat(monkeypatch, {
        "-100500": chat_response(-100500),
        "-100999": FakeResponse(400, {"ok": False, "description": "Bad Request: chat not found"}),
    })

    with pytest.raises(ValueError, match="-100999"):
        preview.ensure_different_channels("123:TEST", "-100500", "-100999")


def test_extract_channels_from_updates():
    updates = [
        {"update_id": 1, "channel_post": {"chat": {"id": -100777, "type": "channel", "title": "Тест"}}},
        {"update_id": 2, "my_chat_member": {"chat": {"id": -100888, "type": "channel", "title": "Другой"}}},
        {"update_id": 3, "message": {"chat": {"id": 42, "type": "private"}}},
        {"update_id": 4, "channel_post": {"chat": {"id": -100777, "type": "channel", "title": "Тест"}}},
    ]

    assert preview.extract_channels(updates) == {"-100777": "Тест", "-100888": "Другой"}


def test_find_chat_id_prints_channels(monkeypatch, capsys):
    updates = {"ok": True, "result": [
        {"update_id": 1, "channel_post": {"chat": {"id": -100777, "type": "channel", "title": "Тест"}}},
    ]}
    monkeypatch.setattr(preview.requests, "get", lambda url, **kwargs: FakeResponse(200, updates))

    assert preview.find_chat_id("123:TEST") == 0
    assert "-100777" in capsys.readouterr().out


def test_default_image_is_first_screenshot():
    expected = sorted((REPO_ROOT / "docs" / "screenshots").glob("*.jpg"))[0]

    assert preview.default_image_path() == expected


def test_samples_fit_telegram_limit():
    for name, text in preview.SAMPLES:
        assert 0 < len(text) <= 4096, name
    assert any(len(text) > 3700 for _, text in preview.SAMPLES), "нужен длинный образец"


def test_send_previews_only_to_test_chat(fake_tg):
    fake_tg.script("sendPhoto", ok(1))
    fake_tg.script("sendMessage", ok(2))
    fake_tg.script("sendRichMessage", *[ok(10 + i) for i in range(len(preview.SAMPLES))])
    config = {"telegram_bot_token": "123:TEST", "telegram_chat_id": "-100500", "retry_max": 3}

    results = preview.send_previews(config, "-100999", b"jpeg-bytes")

    chat_ids = {(kw.get("data") or kw.get("json"))["chat_id"] for _, kw in fake_tg.calls}
    assert chat_ids == {"-100999"}
    assert [expected for _, expected, _ in results] == ["classic"] + ["rich"] * len(preview.SAMPLES)
    assert preview.summarize(results)[1] is True


def test_summary_flags_rich_fallback_and_errors():
    results = [
        ("образец / classic", "classic",
         PublishResult(channel="telegram", ok=True, post_id="1", post_format="classic")),
        ("образец / rich", "rich",
         PublishResult(channel="telegram", ok=True, post_id="2", post_format="classic")),
        ("эмодзи / rich", "rich",
         PublishResult(channel="telegram", ok=False, error="rich retries exhausted")),
    ]

    lines, all_as_expected = preview.summarize(results)

    assert all_as_expected is False
    assert any("образец / rich" in line and "classic" in line for line in lines)
    assert any("эмодзи / rich" in line and "rich retries exhausted" in line for line in lines)


def test_main_refuses_main_channel_without_sending(bot_config, fake_tg, monkeypatch):
    bot_config(telegram_test_chat_id="-100500")  # совпадает с telegram_chat_id
    forbid_get(monkeypatch)

    assert preview.main([]) == 2
    assert fake_tg.calls == []
```

- [ ] **Step 2: Запустить — ожидается FAIL**

Run: `../../../venv/bin/python3 -m pytest tests/test_preview_telegram_format.py -q`
Expected: ошибка сбора `ModuleNotFoundError: No module named 'preview_telegram_format'`.

- [ ] **Step 3: `post_bot.py` — переменная `TELEGRAM_TEST_CHAT_ID` в `load_config`**

Было:

```python
    if os.getenv("TELEGRAM_CHAT_ID"):
        config["telegram_chat_id"] = os.getenv("TELEGRAM_CHAT_ID")
```

Стало:

```python
    if os.getenv("TELEGRAM_CHAT_ID"):
        config["telegram_chat_id"] = os.getenv("TELEGRAM_CHAT_ID")
    if os.getenv("TELEGRAM_TEST_CHAT_ID"):
        config["telegram_test_chat_id"] = os.getenv("TELEGRAM_TEST_CHAT_ID")
```

- [ ] **Step 4: Создать `preview_telegram_format.py`**

```python
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
```

- [ ] **Step 5: Запустить все тесты — ожидается PASS**

Run: `../../../venv/bin/python3 -m pytest -q`
Expected: все зелёные.

- [ ] **Step 6: Проверить, что `--help` работает без конфига и сети**

Run: `../../../venv/bin/python3 preview_telegram_format.py --help`
Expected: справка argparse, код 0 (argparse завершает работу до `load_config`).

- [ ] **Step 7: `config.example.json` и `.env.example`**

В `config.example.json` после строки `"telegram_post_format": "classic",` добавить:

```json
  "telegram_test_chat_id": "",
```

Проверить: `../../../venv/bin/python3 -m json.tool config.example.json > /dev/null`.

В `.env.example` после строки `TELEGRAM_CHAT_ID=@your_channel_username` добавить:

```text

# (Опционально) ID тестового канала для preview_telegram_format.py.
# Скрипт отказывается работать, если это основной канал.
TELEGRAM_TEST_CHAT_ID=
```

- [ ] **Step 8: `README.md` — таблицы, структура, команды**

В таблице «Переменные окружения» после строки `TELEGRAM_CHAT_ID` добавить:

```markdown
| `TELEGRAM_TEST_CHAT_ID` | нет | тестовый канал для `preview_telegram_format.py` (не основной) |
```

В таблице `config.json` после строки `telegram_post_format` добавить:

```markdown
| `telegram_test_chat_id` | да | тестовый канал для `preview_telegram_format.py`; скрипт откажется работать, если это основной канал |
```

В структуре проекта после строки `test_publishers.py …` добавить:

```text
preview_telegram_format.py  # образцы постов classic/rich в ТЕСТОВЫЙ канал
```

В «Установка и запуск» после блока автотестов добавить:

```text

# образцы постов в тестовый канал (бот — админ канала, id в telegram_test_chat_id):
./venv/bin/python3 preview_telegram_format.py --find-chat-id
./venv/bin/python3 preview_telegram_format.py
```

- [ ] **Step 9: `CLAUDE.md` — команда**

В разделе «Команды» после блока `# Автотесты (без сети)` добавить:

```bash
# Образцы постов classic/rich в ТЕСТОВЫЙ канал (telegram_test_chat_id)
./venv/bin/python3 preview_telegram_format.py --find-chat-id
./venv/bin/python3 preview_telegram_format.py
```

- [ ] **Step 10: Commit**

```bash
git add preview_telegram_format.py post_bot.py tests/test_preview_telegram_format.py config.example.json .env.example README.md CLAUDE.md
git commit -m "Скрипт образцов постов для тестового канала с защитой от отправки в основной"
```

---

### Task 6: Итоговая проверка и журнал

**Files:**
- Modify: `JOURNAL.md`

**Interfaces:**
- Consumes: всё из Tasks 1–5.
- Produces: запись в журнале; ветка готова к ревью.

- [ ] **Step 1: Полный прогон тестов**

Run: `../../../venv/bin/python3 -m pytest -q`
Expected: все зелёные, 0 failed, 0 errors.

- [ ] **Step 2: Модули импортируются**

Run: `../../../venv/bin/python3 -c "import post_bot, preview_telegram_format, publishers; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Не тронуто то, что трогать нельзя**

Run: `git diff --stat main -- run_with_retry.sh setup.sh sources.json publishers/facebook.py publishers/instagram.py publishers/log_safety.py requirements.txt`
Expected: пустой вывод.

Run: `git diff main -- post_bot.py | grep -n "Опубликовано" || echo "маркер не менялся"`
Expected: `маркер не менялся`.

- [ ] **Step 4: Нет секретов и личных путей**

Run: `git diff main -- . ':!docs/superpowers' | grep -nE "bot[0-9]+:[A-Za-z0-9_-]{20,}|/home/" || echo "чисто"`
Expected: `чисто` (документы плана исключены: в них есть сам этот шаблон).

- [ ] **Step 5: Запись в `JOURNAL.md`**

Вставить сразу после строки `# JOURNAL` и пустой строки (новая запись — первой):

```markdown
2026-09-17: Telegram — второй формат поста `rich` («Статья», `sendRichMessage`, Bot API 10.2+) рядом с `classic` (sendPhoto + sendMessage). Переключатель `telegram_post_format` — только в config.json, без env (иначе .env молча перекрыл бы откат), по умолчанию classic. Rich собирается в режиме `blocks` (publishers/telegram_rich.py): блок-картинка `attach://cover` + абзац на каждую непустую строку. Режим `html` не используем: в доках противоречие «Media blocks support only HTTP and HTTPS URLs» против `tg://photo?id=`, перенос строки внутри абзаца не описан. Явный отказ Telegram (не 429/5xx) → classic; сеть/5xx/не-JSON → исход неясен, classic НЕ шлём (дубль), отказ после такой попытки — тоже провал. Пустой текст или >500 блоков → сразу classic. В posted-topics.json новое поле `telegram_post_format` (rich правится editMessageText с `rich_message`, не `text`). Появились автотесты: tests/ (pytest, поддельный Bot API), `./venv/bin/python3 -m pytest -q`. `preview_telegram_format.py` шлёт образцы в `telegram_test_chat_id` (сверка с основным каналом по строке и через getChat). До прогона в тестовом канале не подтверждено: принимает ли Telegram картинку через `attach://` в rich и нужен ли боту Premium.

```

- [ ] **Step 6: Commit**

```bash
git add JOURNAL.md
git commit -m "Журнал: формат rich для Telegram и автотесты"
```

- [ ] **Step 7: Итог ветки**

Run: `git log --oneline main..HEAD`
Expected: 2 коммита документов (дизайн, план) и 6 коммитов задач; ни в одном нет `Co-Authored-By` / `Claude-Session` (`git log main..HEAD --format=%B | grep -ciE "co-authored-by|claude-session"` → `0`).

---

## Внедрение (вместе с владельцем, не для субагентов)

1. **Ревью.** Аудитор (Opus) проверяет весь дифф ветки против спеки: риск дублей, отсутствие изменений в classic-пути, секреты.
2. **Слияние в `main`** — вне окон публикации (не 02:50–03:30 и не 10:50–11:30 UTC). В основной папке: `git status` чистый → `git merge --ff-only worktree-telegram-rich-message` → `./venv/bin/python3 -m pytest -q` → `./venv/bin/python3 test_publishers.py`. В `config.json` ключа `telegram_post_format` нет — бот работает в classic.
3. **Контроль classic.** Ближайший пост по расписанию: в `logs/post.log` есть «Фото отправлено», «Сообщение отправлено», «Опубликовано:»; пост в канале выглядит как раньше.
4. **Тестовый канал.** Владелец создаёт закрытый канал, добавляет бота администратором с правом публиковать сообщения (включая медиа) и пишет в канал любое сообщение. Затем:
   - `./venv/bin/python3 preview_telegram_format.py --find-chat-id` → id вписывается в `config.json` как `"telegram_test_chat_id"`;
   - `./venv/bin/python3 preview_telegram_format.py` → итог «ок» по всем строкам;
   - владелец смотрит посты на телефоне и компьютере: картинка, абзацы, списки, эмодзи, вид в списке чатов и в уведомлении.
   **Точка остановки:** если в итоге есть «ВНИМАНИЕ … ушло как classic» (Telegram не принял картинку через `attach://` или требует Premium) — rich не включаем, возвращаемся к владельцу с изменённым планом.
5. **Включение.** В `config.json` основной папки: `"telegram_post_format": "rich"`. Два ближайших поста (10:00 и 18:00 по Бангкоку): в логе «Rich-сообщение («Статья») отправлено», в канале — одно сообщение с картинкой.
6. **Откат** при любой проблеме (в том числе жалобах подписчиков со старым Telegram): `"telegram_post_format": "classic"`.
7. **Итоги** проверки вживую — одной записью в `JOURNAL.md`. Пуш в GitHub — только по команде владельца. Worktree удалить после слияния.

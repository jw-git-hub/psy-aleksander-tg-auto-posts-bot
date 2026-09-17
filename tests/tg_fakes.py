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
        self.unexpected: list[str] = []

    def script(self, method: str, *outcomes) -> None:
        self._outcomes.setdefault(method, []).extend(outcomes)

    def post(self, url: str, **kwargs):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, kwargs))
        queue = self._outcomes.get(method)
        if not queue:
            self.unexpected.append(method)
            raise AssertionError(f"Неожиданный вызов Bot API: {method}")
        outcome = queue.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def methods(self) -> list[str]:
        return [method for method, _ in self.calls]

    def kwargs(self, index: int) -> dict:
        return self.calls[index][1]

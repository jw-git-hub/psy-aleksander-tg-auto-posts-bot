"""Ротация неудачных тем (topic-attempts.json, post_bot.py).

Проблема: узкие темы плана стоят первыми и по многу прогонов подряд не
находят статью — блокируют очередь unposted[:MAX_TOPIC_ATTEMPTS]. Решение —
запоминать время последней неудачи по теме и откладывать такие темы в конец
очереди (order_topics_for_attempt), но не выбрасывать совсем. Без сети.
"""

import json

import pytest

import post_bot

TOPIC_A = post_bot.ALL_TOPICS[0]
TOPIC_B = post_bot.ALL_TOPICS[1]
TOPIC_C = post_bot.ALL_TOPICS[2]
TOPIC_D = post_bot.ALL_TOPICS[3]


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    """Файл состояния пишется в tmp_path, а не в рабочую копию проекта."""
    monkeypatch.setattr(post_bot, "BASE_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# order_topics_for_attempt — чистая функция порядка
# ---------------------------------------------------------------------------

def test_order_keeps_plan_order_when_no_attempts():
    unposted = [TOPIC_A, TOPIC_B, TOPIC_C]

    assert post_bot.order_topics_for_attempt(unposted, {}) == [TOPIC_A, TOPIC_B, TOPIC_C]


def test_order_puts_fresh_topics_before_failed():
    unposted = [TOPIC_A, TOPIC_B, TOPIC_C]
    attempts = {TOPIC_A: "2026-01-01T00:00:00"}

    result = post_bot.order_topics_for_attempt(unposted, attempts)

    assert result == [TOPIC_B, TOPIC_C, TOPIC_A]


def test_order_sorts_failed_topics_oldest_first():
    unposted = [TOPIC_A, TOPIC_B, TOPIC_C]
    attempts = {
        TOPIC_A: "2026-01-03T00:00:00",
        TOPIC_B: "2026-01-01T00:00:00",
        TOPIC_C: "2026-01-02T00:00:00",
    }

    result = post_bot.order_topics_for_attempt(unposted, attempts)

    assert result == [TOPIC_B, TOPIC_C, TOPIC_A]


def test_order_mixed_fresh_and_failed():
    unposted = [TOPIC_A, TOPIC_B, TOPIC_C, TOPIC_D]
    attempts = {
        TOPIC_A: "2026-01-02T00:00:00",
        TOPIC_C: "2026-01-01T00:00:00",
    }

    result = post_bot.order_topics_for_attempt(unposted, attempts)

    # Свежие (B, D) в порядке плана, затем неудачные от самой давней (C, A)
    assert result == [TOPIC_B, TOPIC_D, TOPIC_C, TOPIC_A]


def test_order_ignores_attempts_for_topics_not_in_unposted():
    unposted = [TOPIC_A, TOPIC_B]
    attempts = {TOPIC_C: "2026-01-01T00:00:00"}

    result = post_bot.order_topics_for_attempt(unposted, attempts)

    assert result == [TOPIC_A, TOPIC_B]


# ---------------------------------------------------------------------------
# load_topic_attempts / save_topic_attempts — персистентность
# ---------------------------------------------------------------------------

def test_load_topic_attempts_missing_file_returns_empty():
    assert post_bot.load_topic_attempts() == {}


def test_save_then_load_roundtrip(cache_dir):
    post_bot.save_topic_attempts({TOPIC_A: "2026-01-01T00:00:00"})

    assert post_bot.load_topic_attempts() == {TOPIC_A: "2026-01-01T00:00:00"}
    saved = json.loads((cache_dir / post_bot.TOPIC_ATTEMPTS_FILE).read_text(encoding="utf-8"))
    assert saved["version"] == post_bot.TOPIC_ATTEMPTS_VERSION
    assert saved["data"] == {TOPIC_A: "2026-01-01T00:00:00"}


def test_load_topic_attempts_corrupt_file_returns_empty(cache_dir, caplog):
    (cache_dir / post_bot.TOPIC_ATTEMPTS_FILE).write_text("не json{{{", encoding="utf-8")

    with caplog.at_level("WARNING"):
        attempts = post_bot.load_topic_attempts()

    assert attempts == {}
    assert "повреждён" in caplog.text


def test_load_topic_attempts_version_mismatch_resets(cache_dir):
    payload = {"version": "старая-версия", "data": {TOPIC_A: "2026-01-01T00:00:00"}}
    (cache_dir / post_bot.TOPIC_ATTEMPTS_FILE).write_text(json.dumps(payload), encoding="utf-8")

    assert post_bot.load_topic_attempts() == {}


def test_load_topic_attempts_drops_topics_not_in_plan(cache_dir):
    payload = {
        "version": post_bot.TOPIC_ATTEMPTS_VERSION,
        "data": {TOPIC_A: "2026-01-01T00:00:00", "Тема, которой больше нет в плане": "2026-01-01T00:00:00"},
    }
    (cache_dir / post_bot.TOPIC_ATTEMPTS_FILE).write_text(json.dumps(payload), encoding="utf-8")

    assert post_bot.load_topic_attempts() == {TOPIC_A: "2026-01-01T00:00:00"}


def test_load_topic_attempts_drops_non_string_values(cache_dir):
    payload = {
        "version": post_bot.TOPIC_ATTEMPTS_VERSION,
        "data": {TOPIC_A: "2026-01-01T00:00:00", TOPIC_B: 12345},
    }
    (cache_dir / post_bot.TOPIC_ATTEMPTS_FILE).write_text(json.dumps(payload), encoding="utf-8")

    assert post_bot.load_topic_attempts() == {TOPIC_A: "2026-01-01T00:00:00"}


# ---------------------------------------------------------------------------
# record_topic_failure / record_topic_success
# ---------------------------------------------------------------------------

def test_record_topic_failure_writes_timestamp_and_persists(cache_dir):
    attempts: dict = {}

    post_bot.record_topic_failure(attempts, TOPIC_A, dry_run=False)

    assert TOPIC_A in attempts
    saved = json.loads((cache_dir / post_bot.TOPIC_ATTEMPTS_FILE).read_text(encoding="utf-8"))
    assert saved["data"][TOPIC_A] == attempts[TOPIC_A]


def test_record_topic_failure_dry_run_does_not_write_disk(cache_dir):
    attempts: dict = {}

    post_bot.record_topic_failure(attempts, TOPIC_A, dry_run=True)

    assert not (cache_dir / post_bot.TOPIC_ATTEMPTS_FILE).exists()


def test_record_topic_success_removes_topic_and_persists(cache_dir):
    attempts = {TOPIC_A: "2026-01-01T00:00:00"}
    post_bot.save_topic_attempts(attempts)

    post_bot.record_topic_success(attempts, TOPIC_A, dry_run=False)

    assert TOPIC_A not in attempts
    saved = json.loads((cache_dir / post_bot.TOPIC_ATTEMPTS_FILE).read_text(encoding="utf-8"))
    assert TOPIC_A not in saved["data"]


def test_record_topic_success_dry_run_does_not_write_disk(cache_dir):
    attempts = {TOPIC_A: "2026-01-01T00:00:00"}
    post_bot.save_topic_attempts(attempts)

    post_bot.record_topic_success(attempts, TOPIC_A, dry_run=True)

    # На диске запись о прошлой неудаче осталась нетронутой
    saved = json.loads((cache_dir / post_bot.TOPIC_ATTEMPTS_FILE).read_text(encoding="utf-8"))
    assert saved["data"] == {TOPIC_A: "2026-01-01T00:00:00"}


def test_record_topic_success_no_op_when_topic_not_recorded(cache_dir):
    attempts: dict = {}

    post_bot.record_topic_success(attempts, TOPIC_A, dry_run=False)

    assert attempts == {}
    assert not (cache_dir / post_bot.TOPIC_ATTEMPTS_FILE).exists()


def test_record_topic_failure_survives_disk_save_failure(tmp_path, monkeypatch, caplog):
    missing_dir = tmp_path / "no-such-directory"
    monkeypatch.setattr(post_bot, "BASE_DIR", missing_dir)
    attempts: dict = {}

    with caplog.at_level("WARNING"):
        post_bot.record_topic_failure(attempts, TOPIC_A, dry_run=False)

    # Прогон не падает — запись в памяти сделана, диск просто не обновился
    assert TOPIC_A in attempts
    assert "не удалось сохранить" in caplog.text.lower()

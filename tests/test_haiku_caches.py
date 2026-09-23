"""Персистентные кэши вызовов Claude Haiku: ключевые слова тем и оценки
релевантности статей (post_bot.py). Цель — сократить число вызовов Haiku
между прогонами без изменения логики отбора. Без сети: claude CLI мокается
через post_bot._run_claude.
"""

import json
import subprocess
from datetime import date, timedelta

import pytest

import post_bot

TOPIC = "Здоровые отношения"


def claude_ok(stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["claude"], returncode=0, stdout=stdout, stderr="")


def claude_fail(stderr: str = "boom") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["claude"], returncode=1, stdout="", stderr=stderr)


def _no_haiku_calls(monkeypatch):
    """Мокает _run_claude так, что любой вызов проваливает тест — используется
    в тестах кэш-хита, где обращения к Haiku быть не должно."""
    def _fail(*_args, **_kwargs):
        raise AssertionError("Haiku не должен вызываться при кэш-хите")
    monkeypatch.setattr(post_bot, "_run_claude", _fail)


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    """Кэш-файлы пишутся в tmp_path, а не в рабочую копию проекта."""
    monkeypatch.setattr(post_bot, "BASE_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Кэш ключевых слов тем
# ---------------------------------------------------------------------------

def test_keyword_cache_hit_skips_haiku(monkeypatch):
    _no_haiku_calls(monkeypatch)
    persistent_cache = {TOPIC: ["отношен", "пара", "любов"]}

    keywords = post_bot._get_topic_keywords(TOPIC, {}, persistent_cache)

    assert keywords == ["отношен", "пара", "любов"]


def test_keyword_cache_memoizes_in_run_cache(monkeypatch):
    _no_haiku_calls(monkeypatch)
    persistent_cache = {TOPIC: ["отношен"]}
    run_cache: dict = {}

    post_bot._get_topic_keywords(TOPIC, run_cache, persistent_cache)

    assert run_cache[TOPIC] == ["отношен"]


def test_keyword_fallback_not_persisted(monkeypatch, cache_dir):
    monkeypatch.setattr(post_bot, "_run_claude", lambda *a, **k: claude_fail())
    persistent_cache: dict = {}

    keywords = post_bot._get_topic_keywords(TOPIC, {}, persistent_cache)

    assert keywords == post_bot._topic_keywords_fallback(TOPIC)
    assert persistent_cache == {}
    assert not (cache_dir / post_bot.TOPIC_KEYWORDS_CACHE_FILE).exists()


def test_keyword_success_persisted_to_disk(monkeypatch, cache_dir):
    monkeypatch.setattr(
        post_bot, "_run_claude",
        lambda *a, **k: claude_ok('["отношен","пара","love","trust"]'),
    )
    persistent_cache: dict = {}

    keywords = post_bot._get_topic_keywords(TOPIC, {}, persistent_cache)

    assert keywords == ["отношен", "пара", "love", "trust"]
    assert persistent_cache[TOPIC] == keywords
    saved = json.loads((cache_dir / post_bot.TOPIC_KEYWORDS_CACHE_FILE).read_text(encoding="utf-8"))
    assert saved[TOPIC] == keywords


def test_load_topic_keywords_cache_corrupt_file_returns_empty(cache_dir, caplog):
    (cache_dir / post_bot.TOPIC_KEYWORDS_CACHE_FILE).write_text("не json{{{", encoding="utf-8")

    with caplog.at_level("WARNING"):
        cache = post_bot.load_topic_keywords_cache()

    assert cache == {}
    assert "повреждён" in caplog.text


def test_load_topic_keywords_cache_missing_file_returns_empty(cache_dir):
    assert post_bot.load_topic_keywords_cache() == {}


# ---------------------------------------------------------------------------
# Кэш оценок релевантности
# ---------------------------------------------------------------------------

def make_article(url: str, title: str = "Статья") -> dict:
    return {"url": url, "title": title, "body": "Текст статьи " * 5}


def test_score_cache_hit_skips_haiku(monkeypatch):
    _no_haiku_calls(monkeypatch)
    article = make_article("https://example.com/a")
    norm_url = post_bot._normalize_url(article["url"])
    score_cache = {norm_url: {TOPIC: {"score": 8, "date": date.today().isoformat()}}}

    result = post_bot.score_articles_batch_cached([article], TOPIC, score_cache)

    assert result == [(8, True)]


def test_score_failure_not_cached(monkeypatch, cache_dir):
    monkeypatch.setattr(post_bot, "_run_claude", lambda *a, **k: claude_fail())
    article = make_article("https://example.com/b")
    score_cache: dict = {}

    result = post_bot.score_articles_batch_cached([article], TOPIC, score_cache)

    assert result == [(0, False)]
    assert score_cache == {}
    assert not (cache_dir / post_bot.RELEVANCE_SCORE_CACHE_FILE).exists()


def test_score_success_cached_and_saved(monkeypatch, cache_dir):
    monkeypatch.setattr(post_bot, "_run_claude", lambda *a, **k: claude_ok("[7]"))
    article = make_article("https://example.com/c")
    norm_url = post_bot._normalize_url(article["url"])
    score_cache: dict = {}

    result = post_bot.score_articles_batch_cached([article], TOPIC, score_cache)

    assert result == [(7, False)]
    assert score_cache[norm_url][TOPIC]["score"] == 7
    saved = json.loads((cache_dir / post_bot.RELEVANCE_SCORE_CACHE_FILE).read_text(encoding="utf-8"))
    assert saved[norm_url][TOPIC]["score"] == 7


def test_score_mixed_batch_only_uncached_sent_to_haiku(monkeypatch):
    cached_article = make_article("https://example.com/cached", "Кэшированная")
    new_article = make_article("https://example.com/new", "Новая статья")
    cached_norm_url = post_bot._normalize_url(cached_article["url"])
    score_cache = {cached_norm_url: {TOPIC: {"score": 5, "date": date.today().isoformat()}}}

    calls = []

    def fake_run_claude(prompt, model, timeout):
        calls.append(prompt)
        return claude_ok("[9]")

    monkeypatch.setattr(post_bot, "_run_claude", fake_run_claude)

    result = post_bot.score_articles_batch_cached(
        [cached_article, new_article], TOPIC, score_cache
    )

    assert result == [(5, True), (9, False)]
    # Ушла в Haiku только новая статья
    assert len(calls) == 1
    assert "Новая статья" in calls[0]
    assert "Кэшированная" not in calls[0]


def test_score_batch_respects_batch_size_chunking(monkeypatch):
    articles = [make_article(f"https://example.com/{i}", f"Статья {i}")
                for i in range(post_bot.BATCH_SIZE + 3)]
    score_cache: dict = {}
    calls = []

    def fake_run_claude(prompt, model, timeout):
        n = len(calls)
        calls.append(prompt)
        # Размер текущего чанка определяем по числу "Заголовок:" в промпте
        count = prompt.count("Заголовок:")
        return claude_ok(json.dumps([1] * count))

    monkeypatch.setattr(post_bot, "_run_claude", fake_run_claude)

    result = post_bot.score_articles_batch_cached(articles, TOPIC, score_cache)

    assert len(calls) == 2
    assert len(result) == len(articles)
    assert all(sc == 1 for sc, _ in result)


def test_relevance_score_cache_ttl_cleanup(cache_dir):
    old_date = (date.today() - timedelta(days=post_bot.RELEVANCE_SCORE_CACHE_TTL_DAYS + 5)).isoformat()
    fresh_date = date.today().isoformat()
    raw_cache = {
        "https://example.com/old": {TOPIC: {"score": 3, "date": old_date}},
        "https://example.com/fresh": {TOPIC: {"score": 9, "date": fresh_date}},
    }
    (cache_dir / post_bot.RELEVANCE_SCORE_CACHE_FILE).write_text(
        json.dumps(raw_cache), encoding="utf-8"
    )

    cache = post_bot.load_relevance_score_cache()

    assert "https://example.com/old" not in cache
    assert cache["https://example.com/fresh"][TOPIC]["score"] == 9


def test_relevance_score_cache_save_prunes_expired(cache_dir):
    old_date = (date.today() - timedelta(days=post_bot.RELEVANCE_SCORE_CACHE_TTL_DAYS + 1)).isoformat()
    cache = {"https://example.com/old": {TOPIC: {"score": 1, "date": old_date}}}

    post_bot.save_relevance_score_cache(cache)

    saved = json.loads((cache_dir / post_bot.RELEVANCE_SCORE_CACHE_FILE).read_text(encoding="utf-8"))
    assert saved == {}


def test_load_relevance_score_cache_corrupt_file_returns_empty(cache_dir, caplog):
    (cache_dir / post_bot.RELEVANCE_SCORE_CACHE_FILE).write_text("{не json", encoding="utf-8")

    with caplog.at_level("WARNING"):
        cache = post_bot.load_relevance_score_cache()

    assert cache == {}
    assert "повреждён" in caplog.text

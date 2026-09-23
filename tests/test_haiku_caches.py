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


def make_article(url: str, title: str = "Статья", body: str | None = None) -> dict:
    return {"url": url, "title": title, "body": body or ("Текст статьи " * 5)}


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
    assert saved["version"] == post_bot.TOPIC_KEYWORDS_CACHE_VERSION
    assert saved["data"][TOPIC] == keywords


def test_load_topic_keywords_cache_corrupt_file_returns_empty(cache_dir, caplog):
    (cache_dir / post_bot.TOPIC_KEYWORDS_CACHE_FILE).write_text("не json{{{", encoding="utf-8")

    with caplog.at_level("WARNING"):
        cache = post_bot.load_topic_keywords_cache()

    assert cache == {}
    assert "повреждён" in caplog.text


def test_load_topic_keywords_cache_missing_file_returns_empty(cache_dir):
    assert post_bot.load_topic_keywords_cache() == {}


# --- Валидация значений из персистентного кэша (промах, не краш) ----------

def test_is_valid_cached_keywords():
    assert post_bot._is_valid_cached_keywords(["a", "b"]) is True
    assert post_bot._is_valid_cached_keywords([]) is False
    assert post_bot._is_valid_cached_keywords(["a", ""]) is False
    assert post_bot._is_valid_cached_keywords(["a", 5]) is False
    assert post_bot._is_valid_cached_keywords("not-a-list") is False
    assert post_bot._is_valid_cached_keywords(None) is False


def test_keyword_empty_list_in_cache_triggers_regeneration(monkeypatch):
    monkeypatch.setattr(
        post_bot, "_run_claude",
        lambda *a, **k: claude_ok('["новый","список"]'),
    )
    persistent_cache = {TOPIC: []}  # невалидное значение — пустой список

    keywords = post_bot._get_topic_keywords(TOPIC, {}, persistent_cache)

    assert keywords == ["новый", "список"]


def test_keyword_wrong_type_in_cache_triggers_regeneration(monkeypatch):
    monkeypatch.setattr(
        post_bot, "_run_claude",
        lambda *a, **k: claude_ok('["новый"]'),
    )
    persistent_cache = {TOPIC: "не список"}  # невалидное значение — строка

    keywords = post_bot._get_topic_keywords(TOPIC, {}, persistent_cache)

    assert keywords == ["новый"]


# --- Версионирование формата -----------------------------------------------

def test_topic_keywords_cache_version_mismatch_resets(cache_dir):
    payload = {"version": "старая-версия", "data": {TOPIC: ["a", "b"]}}
    (cache_dir / post_bot.TOPIC_KEYWORDS_CACHE_FILE).write_text(json.dumps(payload), encoding="utf-8")

    assert post_bot.load_topic_keywords_cache() == {}


def test_topic_keywords_cache_version_match_loads(cache_dir):
    payload = {"version": post_bot.TOPIC_KEYWORDS_CACHE_VERSION, "data": {TOPIC: ["a", "b"]}}
    (cache_dir / post_bot.TOPIC_KEYWORDS_CACHE_FILE).write_text(json.dumps(payload), encoding="utf-8")

    assert post_bot.load_topic_keywords_cache() == {TOPIC: ["a", "b"]}


def test_topic_keywords_cache_legacy_unversioned_file_resets_without_crash(cache_dir):
    # Файл в старом (довиженном) плоском формате — без обёртки version/data.
    (cache_dir / post_bot.TOPIC_KEYWORDS_CACHE_FILE).write_text(
        json.dumps({TOPIC: ["a"]}), encoding="utf-8"
    )

    assert post_bot.load_topic_keywords_cache() == {}


# ---------------------------------------------------------------------------
# Кэш оценок релевантности
# ---------------------------------------------------------------------------

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
    assert saved["version"] == post_bot.RELEVANCE_SCORE_CACHE_VERSION
    assert saved["data"][norm_url][TOPIC]["score"] == 7


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
        "version": post_bot.RELEVANCE_SCORE_CACHE_VERSION,
        "data": {
            "https://example.com/old": {TOPIC: {"score": 3, "date": old_date}},
            "https://example.com/fresh": {TOPIC: {"score": 9, "date": fresh_date}},
        },
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
    assert saved["data"] == {}


def test_load_relevance_score_cache_corrupt_file_returns_empty(cache_dir, caplog):
    (cache_dir / post_bot.RELEVANCE_SCORE_CACHE_FILE).write_text("{не json", encoding="utf-8")

    with caplog.at_level("WARNING"):
        cache = post_bot.load_relevance_score_cache()

    assert cache == {}
    assert "повреждён" in caplog.text


# --- Валидация значений из персистентного кэша (промах, не краш) ----------

def test_is_valid_cached_score():
    assert post_bot._is_valid_cached_score({"score": 5, "date": "2020-01-01"}) is True
    assert post_bot._is_valid_cached_score({"score": 0, "date": "2020-01-01"}) is True
    assert post_bot._is_valid_cached_score({"score": 10, "date": "2020-01-01"}) is True
    assert post_bot._is_valid_cached_score({"score": True, "date": "2020-01-01"}) is False
    assert post_bot._is_valid_cached_score({"score": 11, "date": "2020-01-01"}) is False
    assert post_bot._is_valid_cached_score({"score": -1, "date": "2020-01-01"}) is False
    assert post_bot._is_valid_cached_score({"score": "5", "date": "2020-01-01"}) is False
    assert post_bot._is_valid_cached_score({}) is False
    assert post_bot._is_valid_cached_score("не словарь") is False


def test_score_cache_bool_value_is_treated_as_miss(monkeypatch):
    article = make_article("https://example.com/bool-score")
    norm_url = post_bot._normalize_url(article["url"])
    score_cache = {norm_url: {TOPIC: {"score": True, "date": date.today().isoformat()}}}
    monkeypatch.setattr(post_bot, "_run_claude", lambda *a, **k: claude_ok("[4]"))

    result = post_bot.score_articles_batch_cached([article], TOPIC, score_cache)

    assert result == [(4, False)]


def test_score_cache_out_of_range_value_is_treated_as_miss(monkeypatch):
    article = make_article("https://example.com/oor-score")
    norm_url = post_bot._normalize_url(article["url"])
    score_cache = {norm_url: {TOPIC: {"score": 11, "date": date.today().isoformat()}}}
    monkeypatch.setattr(post_bot, "_run_claude", lambda *a, **k: claude_ok("[6]"))

    result = post_bot.score_articles_batch_cached([article], TOPIC, score_cache)

    assert result == [(6, False)]


def test_score_cache_non_int_value_is_treated_as_miss(monkeypatch):
    article = make_article("https://example.com/str-score")
    norm_url = post_bot._normalize_url(article["url"])
    score_cache = {norm_url: {TOPIC: {"score": "8", "date": date.today().isoformat()}}}
    monkeypatch.setattr(post_bot, "_run_claude", lambda *a, **k: claude_ok("[6]"))

    result = post_bot.score_articles_batch_cached([article], TOPIC, score_cache)

    assert result == [(6, False)]


# --- Версионирование формата -----------------------------------------------

def test_relevance_score_cache_version_mismatch_resets(cache_dir):
    payload = {
        "version": "старая-версия",
        "data": {"https://example.com/x": {TOPIC: {"score": 5, "date": date.today().isoformat()}}},
    }
    (cache_dir / post_bot.RELEVANCE_SCORE_CACHE_FILE).write_text(json.dumps(payload), encoding="utf-8")

    assert post_bot.load_relevance_score_cache() == {}


def test_relevance_score_cache_version_match_loads(cache_dir):
    payload = {
        "version": post_bot.RELEVANCE_SCORE_CACHE_VERSION,
        "data": {"https://example.com/x": {TOPIC: {"score": 5, "date": date.today().isoformat()}}},
    }
    (cache_dir / post_bot.RELEVANCE_SCORE_CACHE_FILE).write_text(json.dumps(payload), encoding="utf-8")

    cache = post_bot.load_relevance_score_cache()

    assert cache["https://example.com/x"][TOPIC]["score"] == 5


# ---------------------------------------------------------------------------
# _score_articles_batch_once: невалидный элемент ответа губит весь батч
# ---------------------------------------------------------------------------

def _three_articles():
    return [make_article(f"https://example.com/once-{i}") for i in range(3)]


def test_score_once_non_numeric_element_invalidates_whole_batch(monkeypatch):
    monkeypatch.setattr(post_bot, "_run_claude", lambda *a, **k: claude_ok('[7, "bad", 3]'))

    assert post_bot._score_articles_batch_once(_three_articles(), TOPIC) is None


def test_score_once_out_of_range_element_invalidates_whole_batch(monkeypatch):
    monkeypatch.setattr(post_bot, "_run_claude", lambda *a, **k: claude_ok("[7, 15, 3]"))

    assert post_bot._score_articles_batch_once(_three_articles(), TOPIC) is None


def test_score_once_bool_element_invalidates_whole_batch(monkeypatch):
    monkeypatch.setattr(post_bot, "_run_claude", lambda *a, **k: claude_ok("[7, true, 3]"))

    assert post_bot._score_articles_batch_once(_three_articles(), TOPIC) is None


def test_score_once_valid_elements_pass_through(monkeypatch):
    monkeypatch.setattr(post_bot, "_run_claude", lambda *a, **k: claude_ok("[0, 10, 5]"))

    assert post_bot._score_articles_batch_once(_three_articles(), TOPIC) == [0, 10, 5]


def test_public_score_articles_batch_falls_back_to_zeros_on_invalid_element(monkeypatch):
    monkeypatch.setattr(post_bot, "_run_claude", lambda *a, **k: claude_ok('[7, "bad", 3]'))

    result = post_bot.score_articles_batch(_three_articles(), TOPIC)

    assert result == [0, 0, 0]


def test_coerce_score():
    assert post_bot._coerce_score(5) == 5
    assert post_bot._coerce_score("7") == 7
    assert post_bot._coerce_score(0) == 0
    assert post_bot._coerce_score(10) == 10
    assert post_bot._coerce_score(11) is None
    assert post_bot._coerce_score(-1) is None
    assert post_bot._coerce_score(True) is None
    assert post_bot._coerce_score(False) is None
    assert post_bot._coerce_score("bad") is None
    assert post_bot._coerce_score(None) is None


# ---------------------------------------------------------------------------
# Запись кэша не должна падать при ошибке диска (P1) и не должна блокировать
# получение результата (кэш просто не обновится в этот раз).
# ---------------------------------------------------------------------------

def test_save_json_cache_oserror_is_caught_not_raised(tmp_path, caplog):
    missing_dir = tmp_path / "no-such-directory"  # каталог намеренно не создаём
    path = missing_dir / "cache.json"

    with caplog.at_level("WARNING"):
        post_bot._save_json_cache(path, {"a": 1})  # не должно бросить исключение

    assert not path.exists()
    assert "не удалось сохранить" in caplog.text.lower()


def test_keyword_success_survives_disk_save_failure(monkeypatch, tmp_path, caplog):
    missing_dir = tmp_path / "no-such-directory"
    monkeypatch.setattr(post_bot, "BASE_DIR", missing_dir)
    monkeypatch.setattr(post_bot, "_run_claude", lambda *a, **k: claude_ok('["отношен","love"]'))
    persistent_cache: dict = {}

    with caplog.at_level("WARNING"):
        keywords = post_bot._get_topic_keywords(TOPIC, {}, persistent_cache)

    # Результат прогона не пострадал, хотя запись на диск провалилась
    assert keywords == ["отношен", "love"]
    assert persistent_cache[TOPIC] == keywords
    assert "не удалось сохранить" in caplog.text.lower()


def test_score_success_survives_disk_save_failure(monkeypatch, tmp_path, caplog):
    missing_dir = tmp_path / "no-such-directory"
    monkeypatch.setattr(post_bot, "BASE_DIR", missing_dir)
    monkeypatch.setattr(post_bot, "_run_claude", lambda *a, **k: claude_ok("[7]"))
    article = make_article("https://example.com/disk-fail")
    score_cache: dict = {}

    with caplog.at_level("WARNING"):
        result = post_bot.score_articles_batch_cached([article], TOPIC, score_cache)

    assert result == [(7, False)]
    assert "не удалось сохранить" in caplog.text.lower()


# ---------------------------------------------------------------------------
# stats["scored"] / stats["score_cache_hits"] — считаем реально отправленные
# в Haiku статьи отдельно от кэш-хитов (см. _find_best_article_for_topic).
# ---------------------------------------------------------------------------

def test_find_best_article_stats_count_haiku_calls_and_cache_hits_separately(monkeypatch):
    long_body = "Слово про отношения. " * 20  # >=200 символов

    cached_article = make_article("https://example.com/stats-cached", "Кэшированная статья", long_body)
    new_article = make_article("https://example.com/stats-new", "Новая статья", long_body)

    cached_norm_url = post_bot._normalize_url(cached_article["url"])
    score_cache = {cached_norm_url: {TOPIC: {"score": 5, "date": date.today().isoformat()}}}
    topic_keywords_persistent_cache = {TOPIC: ["отношени"]}

    monkeypatch.setattr(post_bot, "_run_claude", lambda *a, **k: claude_ok("[9]"))

    stats = {"duplicates": 0, "too_short": 0, "scored": 0, "score_cache_hits": 0}

    post_bot._find_best_article_for_topic(
        TOPIC, [cached_article, new_article], [], stats, {}, {},
        topic_keywords_persistent_cache, score_cache, set(),
    )

    assert stats["scored"] == 1
    assert stats["score_cache_hits"] == 1

"""Тесты на fetch_articles_html — без сети, HTML-страницы подсовываем через
monkeypatch поверх post_bot._safe_download_html (url -> html строкой).

Покрывает регрессии, найденные при чистке sources.json (2026-09-23/24):
- фильтр (whitelist/blacklist, boilerplate-ссылки, самоссылка на листинг,
  пагинация) должен применяться ДО среза до MAX_LINKS_PER_SOURCE, а не после;
- дедуп кандидатов — по нормализованному href, с сохранением самого длинного
  не-boilerplate текста ссылки;
- заголовок статьи берётся со страницы САМОЙ статьи (og:title → h1 → текст
  ссылки с листинга), с обрезкой суффикса вида "Заголовок | Название сайта".
"""

import post_bot


SOURCE_URL = "https://example.com/blog/"


def make_source(**overrides) -> dict:
    source = {
        "name": "Example Blog",
        "url": SOURCE_URL,
        "type": "html",
        "rss_url": None,
        "selector_title": "a.card-link",
        "selector_body": ".post-body",
        "selector_image": ".post-body img",
        "language": "en",
        "category": "relationships",
    }
    source.update(overrides)
    return source


def article_page(title_tag: str = "", h1: str = "", body: str = "Body text long enough to pass filters. " * 5) -> str:
    return f"""
    <html><head>{title_tag}</head><body>
    {f'<h1>{h1}</h1>' if h1 else ''}
    <div class="post-body"><p>{body}</p></div>
    </body></html>
    """


def og_title_tag(content: str) -> str:
    return f'<meta property="og:title" content="{content}">'


def install_pages(monkeypatch, pages: dict[str, str]) -> None:
    def fake_download(url: str, max_size: int = 5_000_000) -> str:
        if url not in pages:
            raise AssertionError(f"Неожиданный запрос страницы: {url}")
        return pages[url]

    monkeypatch.setattr(post_bot, "_safe_download_html", fake_download)


# ---------------------------------------------------------------------------
# Фильтр ДО среза MAX_LINKS_PER_SOURCE (P2, регрессия Мамсила: 12 category-
# ссылок раньше статейных в разметке съедали весь лимit(10) до фильтрации).
# ---------------------------------------------------------------------------

def test_filters_blacklisted_links_before_slicing_to_max(monkeypatch):
    nav_links = "".join(
        f'<a class="card-link" href="/category/cat-{i}/">Категория {i}</a>'
        for i in range(12)
    )
    article_links = "".join(
        f'<a class="card-link" href="/post-{i}/">Заголовок статьи {i}</a>'
        for i in range(3)
    )
    listing_html = f"<html><body>{nav_links}{article_links}</body></html>"

    source = make_source(url_path_blacklist=["/category/"])
    pages = {SOURCE_URL: listing_html}
    for i in range(3):
        pages[f"https://example.com/post-{i}/"] = article_page(h1=f"Заголовок статьи {i}")
    install_pages(monkeypatch, pages)

    articles = post_bot.fetch_articles_html(source)

    assert len(articles) == 3
    assert {a["url"] for a in articles} == {
        f"https://example.com/post-{i}/" for i in range(3)
    }


def test_max_links_per_source_cap_applies_after_filtering(monkeypatch):
    article_links = "".join(
        f'<a class="card-link" href="/post-{i}/">Заголовок статьи {i}</a>'
        for i in range(15)
    )
    listing_html = f"<html><body>{article_links}</body></html>"

    source = make_source()
    pages = {SOURCE_URL: listing_html}
    for i in range(15):
        pages[f"https://example.com/post-{i}/"] = article_page(h1=f"Заголовок статьи {i}")
    install_pages(monkeypatch, pages)

    articles = post_bot.fetch_articles_html(source)

    assert len(articles) == post_bot.MAX_LINKS_PER_SOURCE


# ---------------------------------------------------------------------------
# Дедуп по нормализованному href, с сохранением самого длинного заголовка.
# ---------------------------------------------------------------------------

def test_dedup_by_normalized_href_keeps_longest_title(monkeypatch):
    listing_html = """
    <html><body>
        <a class="card-link" href="/post-1/?utm_source=rss">Коротко</a>
        <a class="card-link" href="/post-1/">Полный настоящий заголовок статьи</a>
    </body></html>
    """
    source = make_source()
    article_html = article_page(h1="Полный настоящий заголовок статьи")
    pages = {
        SOURCE_URL: listing_html,
        # Первый встреченный вариант href (с utm) остаётся URL-ом записи —
        # реальный запрос по нему вернул бы ту же страницу.
        "https://example.com/post-1/?utm_source=rss": article_html,
        "https://example.com/post-1/": article_html,
    }
    install_pages(monkeypatch, pages)

    articles = post_bot.fetch_articles_html(source)

    assert len(articles) == 1
    assert articles[0]["title"] == "Полный настоящий заголовок статьи"


def test_dedup_keeps_longest_listing_title_as_fallback_when_no_og_or_h1(monkeypatch):
    listing_html = """
    <html><body>
        <a class="card-link" href="/post-1/">Коротко</a>
        <a class="card-link" href="/post-1/#anchor">Полный настоящий заголовок статьи карточки</a>
    </body></html>
    """
    source = make_source()
    pages = {
        SOURCE_URL: listing_html,
        # Ни og:title, ни h1 на странице статьи — берём заголовок с листинга.
        "https://example.com/post-1/": article_page(),
    }
    install_pages(monkeypatch, pages)

    articles = post_bot.fetch_articles_html(source)

    assert len(articles) == 1
    assert articles[0]["title"] == "Полный настоящий заголовок статьи карточки"


# ---------------------------------------------------------------------------
# Служебные "read more"/"читать далее"-ссылки не становятся заголовком и не
# создают вторую запись для того же href.
# ---------------------------------------------------------------------------

def test_boilerplate_link_text_is_skipped(monkeypatch):
    listing_html = """
    <html><body>
        <a class="card-link" href="/post-1/">Read More</a>
        <a class="card-link" href="/post-1/">Настоящий заголовок статьи</a>
        <a class="card-link" href="/post-2/">Читать далее →</a>
    </body></html>
    """
    source = make_source()
    pages = {
        SOURCE_URL: listing_html,
        "https://example.com/post-1/": article_page(h1="Настоящий заголовок статьи"),
    }
    install_pages(monkeypatch, pages)

    articles = post_bot.fetch_articles_html(source)

    # post-2 отфильтрован целиком (единственная ссылка на него — boilerplate).
    assert len(articles) == 1
    assert articles[0]["title"] == "Настоящий заголовок статьи"


# ---------------------------------------------------------------------------
# Самоссылка на листинг и пагинация (регрессия Attachment Project: "Blog"/
# "All Posts" ссылки на /blog/ матчились тем же selector_title, что статьи).
# ---------------------------------------------------------------------------

def test_self_link_to_listing_page_is_skipped(monkeypatch):
    listing_html = """
    <html><body>
        <a class="card-link" href="/blog/">All Posts</a>
        <a class="card-link" href="/post-1/">Настоящая статья</a>
    </body></html>
    """
    source = make_source()
    pages = {
        SOURCE_URL: listing_html,
        "https://example.com/post-1/": article_page(h1="Настоящая статья"),
    }
    install_pages(monkeypatch, pages)

    articles = post_bot.fetch_articles_html(source)

    assert len(articles) == 1
    assert articles[0]["url"] == "https://example.com/post-1/"


def test_pagination_links_are_skipped(monkeypatch):
    listing_html = """
    <html><body>
        <a class="card-link" href="/blog/page/2/">Следующая страница</a>
        <a class="card-link" href="/post-1/">Настоящая статья</a>
    </body></html>
    """
    source = make_source()
    pages = {
        SOURCE_URL: listing_html,
        "https://example.com/post-1/": article_page(h1="Настоящая статья"),
    }
    install_pages(monkeypatch, pages)

    articles = post_bot.fetch_articles_html(source)

    assert len(articles) == 1
    assert articles[0]["url"] == "https://example.com/post-1/"


# ---------------------------------------------------------------------------
# Относительные URL резолвятся в абсолютные.
# ---------------------------------------------------------------------------

def test_relative_urls_are_resolved_to_absolute(monkeypatch):
    listing_html = """
    <html><body>
        <a class="card-link" href="/relative-post/">Статья по относительной ссылке</a>
    </body></html>
    """
    source = make_source()
    pages = {
        SOURCE_URL: listing_html,
        "https://example.com/relative-post/": article_page(h1="Статья по относительной ссылке"),
    }
    install_pages(monkeypatch, pages)

    articles = post_bot.fetch_articles_html(source)

    assert len(articles) == 1
    assert articles[0]["url"] == "https://example.com/relative-post/"


# ---------------------------------------------------------------------------
# Заголовок — со страницы статьи (og:title → h1 → текст ссылки с листинга),
# а не мусорный текст всей карточки с листинга (регрессия Психологос/
# BetterHelp/Attachment Project: карточка = дата+анонс+CTA одним текстом).
# ---------------------------------------------------------------------------

def test_title_prefers_og_title_over_messy_listing_card_text(monkeypatch):
    listing_html = """
    <html><body>
        <a class="card-link" href="/post-1/">22 сент. 2017«Заголовок»Анонс статьи текст</a>
    </body></html>
    """
    source = make_source()
    pages = {
        SOURCE_URL: listing_html,
        "https://example.com/post-1/": article_page(
            title_tag=og_title_tag("Чистый заголовок статьи"),
            h1="Чистый заголовок статьи",
        ),
    }
    install_pages(monkeypatch, pages)

    articles = post_bot.fetch_articles_html(source)

    assert articles[0]["title"] == "Чистый заголовок статьи"


def test_title_falls_back_to_h1_when_no_og_title(monkeypatch):
    listing_html = '<html><body><a class="card-link" href="/post-1/">Мусор с карточки</a></body></html>'
    source = make_source()
    pages = {
        SOURCE_URL: listing_html,
        "https://example.com/post-1/": article_page(h1="Заголовок из h1"),
    }
    install_pages(monkeypatch, pages)

    articles = post_bot.fetch_articles_html(source)

    assert articles[0]["title"] == "Заголовок из h1"


def test_title_falls_back_to_listing_text_when_no_og_title_or_h1(monkeypatch):
    listing_html = '<html><body><a class="card-link" href="/post-1/">Текст ссылки с листинга</a></body></html>'
    source = make_source()
    pages = {
        SOURCE_URL: listing_html,
        "https://example.com/post-1/": article_page(),  # ни og:title, ни h1
    }
    install_pages(monkeypatch, pages)

    articles = post_bot.fetch_articles_html(source)

    assert articles[0]["title"] == "Текст ссылки с листинга"


def test_title_strips_known_site_name_suffix(monkeypatch):
    listing_html = '<html><body><a class="card-link" href="/post-1/">заглушка</a></body></html>'
    source = make_source(name="Example Blog")
    pages = {
        SOURCE_URL: listing_html,
        "https://example.com/post-1/": article_page(
            title_tag=og_title_tag("Реальный заголовок статьи | Example Blog"),
        ),
    }
    install_pages(monkeypatch, pages)

    articles = post_bot.fetch_articles_html(source)

    assert articles[0]["title"] == "Реальный заголовок статьи"


def test_title_does_not_strip_dash_inside_real_title(monkeypatch):
    """Разделитель "‑" внутри заголовка не должен резаться, если то, что после
    него, не похоже на название сайта/домен (Attachment Project: "Secure
    Attachment - from Childhood to Adult Relationships" резался бы неверно
    наивной проверкой "режь всё после последнего дефиса")."""
    listing_html = '<html><body><a class="card-link" href="/post-1/">заглушка</a></body></html>'
    source = make_source(name="Example Blog")
    pages = {
        SOURCE_URL: listing_html,
        "https://example.com/post-1/": article_page(
            title_tag=og_title_tag("Secure Attachment - from Childhood to Adult Relationships"),
        ),
    }
    install_pages(monkeypatch, pages)

    articles = post_bot.fetch_articles_html(source)

    assert articles[0]["title"] == "Secure Attachment - from Childhood to Adult Relationships"


def test_title_skips_first_h1_when_it_is_site_brand(monkeypatch):
    """Регрессия psyjournal.ru: на странице статьи два <h1> — первый шапка-
    логотип сайта, второй настоящий заголовок статьи."""
    listing_html = '<html><body><a class="card-link" href="/post-1/">заглушка</a></body></html>'
    source = make_source(name="Example Blog")
    html = """
    <html><head></head><body>
    <h1>Example Blog</h1>
    <h1>Настоящий заголовок статьи</h1>
    <div class="post-body"><p>Тело статьи достаточно длинное для фильтра. </p></div>
    </body></html>
    """
    pages = {SOURCE_URL: listing_html, "https://example.com/post-1/": html}
    install_pages(monkeypatch, pages)

    articles = post_bot.fetch_articles_html(source)

    assert articles[0]["title"] == "Настоящий заголовок статьи"


def test_title_prefers_h1_when_og_title_has_extra_category_tail(monkeypatch):
    """Регрессия 7ya.ru: og:title = h1 + добавленная категория ("... . Зрение").
    h1 без хвоста надёжнее для дедупа, чем og:title с примесью."""
    listing_html = '<html><body><a class="card-link" href="/post-1/">заглушка</a></body></html>'
    source = make_source(name="Example Blog")
    pages = {
        SOURCE_URL: listing_html,
        "https://example.com/post-1/": article_page(
            title_tag=og_title_tag("Настоящий заголовок статьи. Категория"),
            h1="Настоящий заголовок статьи",
        ),
    }
    install_pages(monkeypatch, pages)

    articles = post_bot.fetch_articles_html(source)

    assert articles[0]["title"] == "Настоящий заголовок статьи"

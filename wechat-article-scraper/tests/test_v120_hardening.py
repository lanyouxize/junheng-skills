"""v1.2.0 加固回归：重试退避、限流可见、HTML 实体还原、路径越界、凭证与文档对账。"""

import json
import os
import re
import subprocess
import sys
import warnings
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.utils import (
    fetch_with_retry,
    join_within,
    merge_article,
    parse_date,
    resolve_credential,
)
from core.article_parser import extract_article_meta_from_html
from core.image_downloader import ImageDownloader


# ---------------------------------------------------------------------------
# HTTP fakes
# ---------------------------------------------------------------------------

class Resp:
    def __init__(self, status=200, text="", headers=None, url=""):
        self.status_code = status
        self._text = text
        self.headers = dict(headers or {})
        self.url = url
        self.encoding = "utf-8"

    @property
    def text(self):
        return self._text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class ConnectTimeout(Exception):
    """Named like requests' own error so the retry classifier picks it up."""


class BrokenValue(Exception):
    """Not a network problem — must never be retried."""


class SeqSession:
    """Serves a queue of responses/exceptions and records every call."""

    def __init__(self, items):
        self.items = list(items)
        self.calls = []
        self.headers = {}
        self.proxies = {}

    def get(self, url, timeout=None, allow_redirects=True, headers=None):
        self.calls.append(url)
        if not self.items:
            raise AssertionError("fake session ran out of queued responses")
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


ARTICLE_HTML = """
<html><head><meta property="og:title" content="测试文章">
</head><body><div id="js_content"><p>正文正文正文</p></div></body></html>
"""


@pytest.fixture
def mcp():
    import mcp_server

    return mcp_server


def _send_seq(*items):
    """Return (callable, calls) that replays a queue of responses.

    An exception instance in the queue is raised rather than returned —
    that is how a test simulates a timeout instead of a bad status code.
    """
    queue = list(items)
    calls = []

    def send():
        calls.append(len(calls) + 1)
        if not queue:
            raise AssertionError("ran out of queued responses")
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    return send, calls


# ---------------------------------------------------------------------------
# core.utils.fetch_with_retry
# ---------------------------------------------------------------------------

class TestFetchWithRetry:
    def test_429_then_200_returns_second_response(self):
        first, second = Resp(429), Resp(200, "ok")
        queue = [first, second]
        waits = []

        def send():
            return queue.pop(0)

        resp, attempts = fetch_with_retry(
            send, max_attempts=3, backoff=2.0, jitter=0, sleeper=waits.append
        )
        assert resp is second
        assert attempts == 2
        assert waits == [2.0]

    def test_exponential_backoff_sequence(self):
        queue = [Resp(500), Resp(502), Resp(503), Resp(200, "ok")]
        waits = []
        resp, attempts = fetch_with_retry(
            lambda: queue.pop(0), max_attempts=4, backoff=1.5, jitter=0,
            sleeper=waits.append,
        )
        assert resp.status_code == 200
        assert attempts == 4
        assert waits == [1.5, 3.0, 6.0]

    def test_honours_retry_after_seconds(self):
        queue = [Resp(429, headers={"Retry-After": "7"}), Resp(200, "ok")]
        waits = []
        fetch_with_retry(
            lambda: queue.pop(0), max_attempts=3, backoff=1.0, jitter=0,
            sleeper=waits.append,
        )
        assert waits == [7.0]

    def test_retry_after_capped_by_max_wait(self):
        queue = [Resp(503, headers={"Retry-After": "3600"}), Resp(200, "ok")]
        waits = []
        fetch_with_retry(
            lambda: queue.pop(0), max_attempts=2, backoff=1.0, max_wait=30.0,
            jitter=0, sleeper=waits.append,
        )
        assert waits == [30.0]

    def test_retry_after_http_date_is_parsed(self):
        later = datetime.now(timezone.utc) + timedelta(seconds=5)
        queue = [Resp(429, headers={"Retry-After": format_datetime(later, usegmt=True)}),
                 Resp(200, "ok")]
        waits = []
        fetch_with_retry(
            lambda: queue.pop(0), max_attempts=2, backoff=1.0, jitter=0,
            sleeper=waits.append,
        )
        assert 0 <= waits[0] <= 6

    def test_garbage_retry_after_falls_back_to_backoff(self):
        queue = [Resp(429, headers={"Retry-After": "not-a-date"}), Resp(200, "ok")]
        waits = []
        fetch_with_retry(
            lambda: queue.pop(0), max_attempts=2, backoff=4.0, jitter=0,
            sleeper=waits.append,
        )
        assert waits == [4.0]

    def test_permanent_4xx_is_not_retried(self):
        send, _ = _send_seq(Resp(404))
        waits = []
        resp, attempts = fetch_with_retry(
            send, max_attempts=3, jitter=0, sleeper=waits.append
        )
        assert resp.status_code == 404
        assert attempts == 1
        assert waits == []

    def test_returns_last_transient_response_when_exhausted(self):
        """A stuck 503 comes back as a response, not an exception, so the
        caller can still report the status it actually saw."""
        send, _ = _send_seq(Resp(503), Resp(504), Resp(500))
        waits = []
        resp, attempts = fetch_with_retry(
            send, max_attempts=3, jitter=0, sleeper=waits.append
        )
        assert resp.status_code == 500
        assert attempts == 3

    def test_retries_network_exception_by_class_name(self):
        queue = [ConnectTimeout("timed out"), Resp(200, "ok")]
        waits = []

        def send():
            item = queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        resp, attempts = fetch_with_retry(
            send, max_attempts=3, jitter=0, sleeper=waits.append
        )
        assert resp.status_code == 200
        assert attempts == 2

    def test_raises_at_last_attempt_for_network_exception(self):
        def send():
            raise ConnectTimeout("still down")

        with pytest.raises(ConnectTimeout):
            fetch_with_retry(send, max_attempts=2, jitter=0, sleeper=lambda s: None)

    def test_non_transient_exception_raises_immediately(self):
        send, _ = _send_seq(BrokenValue("bug"))
        waits = []
        with pytest.raises(BrokenValue):
            fetch_with_retry(send, max_attempts=3, jitter=0, sleeper=waits.append)
        assert waits == []

    def test_single_attempt_means_no_waiting(self):
        send, _ = _send_seq(Resp(429))
        waits = []
        resp, attempts = fetch_with_retry(
            send, max_attempts=1, jitter=0, sleeper=waits.append
        )
        assert resp.status_code == 429
        assert attempts == 1
        assert waits == []


# ---------------------------------------------------------------------------
# scrapers.sogou_search — retry + throttle visibility
# ---------------------------------------------------------------------------

class TestSearcherRetry:
    def _searcher(self, **kwargs):
        from scrapers.sogou_search import SogouWeChatSearcher

        options = dict(rate_limit_min=0, rate_limit_max=0, retry_backoff=0, retry_jitter=0)
        options.update(kwargs)
        return SogouWeChatSearcher(**options)

    def _with_results(self, searcher, monkeypatch):
        monkeypatch.setattr(
            searcher, "_parse_search_results",
            lambda html, article_type: [{"title": "A", "link": "https://mp.weixin.qq.com/s/a"}],
        )
        return searcher

    def test_429_then_ok_counts_retries(self, monkeypatch):
        searcher = self._with_results(self._searcher(), monkeypatch)
        searcher.session = SeqSession([Resp(429), Resp(200, "<html>ok</html>")])
        results = searcher.search_articles("AI", page=1)
        assert len(results) == 1
        assert searcher.retries == 1
        assert searcher.blocked_pages == 0

    def test_persistent_throttle_is_reported_not_empty(self, monkeypatch):
        searcher = self._searcher()
        searcher.session = SeqSession([Resp(429), Resp(429), Resp(429)])
        assert searcher.search_articles("AI") == []
        assert searcher.blocked is True
        assert searcher.blocked_pages == 1

    def test_raise_on_block_turns_throttle_into_error(self):
        from scrapers.sogou_search import SogouBlocked

        searcher = self._searcher(raise_on_block=True)
        searcher.session = SeqSession([Resp(403), Resp(403), Resp(403)])
        with pytest.raises(SogouBlocked):
            searcher.search_articles("AI")

    def test_404_is_not_retried(self, monkeypatch):
        searcher = self._searcher()
        session = SeqSession([Resp(404)])
        searcher.session = session
        assert searcher.search_articles("AI") == []
        assert len(session.calls) == 1

    def test_timeout_is_retried_then_surfaces(self):
        searcher = self._searcher(retry_max_attempts=2)
        session = SeqSession([ConnectTimeout("t"), ConnectTimeout("t")])
        searcher.session = session
        assert searcher.search_articles("AI") == []
        assert len(session.calls) == 2
        assert searcher.retries == 1


# ---------------------------------------------------------------------------
# scrapers.article_fetcher — retry, dedup scoping
# ---------------------------------------------------------------------------

class TestFetcherRetry:
    def _fetcher(self, tmp_path, session, **kwargs):
        from scrapers.article_fetcher import ArticleFetcher

        options = dict(rate_limit_min=0, rate_limit_max=0, retry_backoff=0,
                       retry_jitter=0, cache_dir=tmp_path / "cache")
        options.update(kwargs)
        fetcher = ArticleFetcher(**options)
        fetcher.session = session
        return fetcher

    def test_503_then_200_records_retry(self, tmp_path):
        session = SeqSession([Resp(503), Resp(200, ARTICLE_HTML, url="https://mp.weixin.qq.com/s/a")])
        fetcher = self._fetcher(tmp_path, session)
        article = fetcher.fetch_article("https://mp.weixin.qq.com/s/a")
        assert article["title"] == "测试文章"
        assert fetcher.stats["retries"] == 1
        assert len(session.calls) == 2

    def test_permanent_failure_has_no_retry_cost(self, tmp_path):
        session = SeqSession([Resp(404)])
        fetcher = self._fetcher(tmp_path, session)
        article = fetcher.fetch_article("https://mp.weixin.qq.com/s/gone")
        assert article.get("error")
        assert fetcher.stats["retries"] == 0
        assert len(session.calls) == 1

    def test_retry_stats_default_to_zero(self, tmp_path):
        fetcher = self._fetcher(tmp_path, SeqSession([]))
        assert fetcher.stats["retries"] == 0

    def test_all_attempts_failing_still_counts_retries(self, tmp_path):
        """The counter lives in `finally`: a raised last attempt must not hide it."""
        session = SeqSession([ConnectTimeout("t"), ConnectTimeout("t")])
        fetcher = self._fetcher(tmp_path, session, retry_max_attempts=2)
        article = fetcher.fetch_article("https://mp.weixin.qq.com/s/down")
        assert article.get("error")
        assert len(session.calls) == 2
        assert fetcher.stats["retries"] == 1
        assert fetcher.stats["failed"] == 1


class TestFetcherDedupIsolation:
    def _two_batches_same_title(self, tmp_path):
        from scrapers.article_fetcher import ArticleFetcher

        html_a = ARTICLE_HTML.replace("测试文章", "同一个标题")
        fetcher = ArticleFetcher(
            rate_limit_min=0, rate_limit_max=0, cache_dir=tmp_path / "cache",
        )
        fetcher.session = SeqSession([
            Resp(200, html_a, url="https://mp.weixin.qq.com/s/one"),
            Resp(200, html_a, url="https://mp.weixin.qq.com/s/two"),
        ])
        first = fetcher.fetch_articles(["https://mp.weixin.qq.com/s/one"])
        second = fetcher.fetch_articles(["https://mp.weixin.qq.com/s/two"])
        return first, second

    def test_second_batch_is_not_dropped_by_previous_call(self, tmp_path):
        """The fetcher is a process-wide singleton; its dedup state must not
        leak, or a later batch silently loses look-alike titles."""
        first, second = self._two_batches_same_title(tmp_path)
        assert len(first) == 1
        assert len(second) == 1

    def test_duplicates_inside_one_batch_still_dropped(self, tmp_path):
        from scrapers.article_fetcher import ArticleFetcher

        html_a = ARTICLE_HTML.replace("测试文章", "同一个标题")
        fetcher = ArticleFetcher(
            rate_limit_min=0, rate_limit_max=0, cache_dir=tmp_path / "cache",
        )
        fetcher.session = SeqSession([
            Resp(200, html_a, url="https://mp.weixin.qq.com/s/one"),
            Resp(200, html_a, url="https://mp.weixin.qq.com/s/two"),
        ])
        both = fetcher.fetch_articles(
            ["https://mp.weixin.qq.com/s/one", "https://mp.weixin.qq.com/s/two"]
        )
        assert len(both) == 1


# ---------------------------------------------------------------------------
# meta entity handling
# ---------------------------------------------------------------------------

class TestMetaEntities:
    def test_escaped_meta_values_are_unescaped(self):
        html = (
            '<meta content="AI&amp;芯片：&#8220;下一个十年&#8221;" property="og:title">'
            '<meta content="作者张三 &amp; 李四" name="author">'
        )
        meta = extract_article_meta_from_html(html)
        assert meta["title"] == "AI&芯片：“下一个十年”"
        assert meta["author"] == "作者张三 & 李四"

    def test_og_url_keeps_single_ampersands(self):
        html = ('<meta property="og:url" '
                'content="https://mp.weixin.qq.com/s?__biz=MzA&amp;mid=123&amp;idx=1">')
        meta = extract_article_meta_from_html(html)
        assert meta["canonical_url"] == "https://mp.weixin.qq.com/s?__biz=MzA&mid=123&idx=1"
        assert "&amp;" not in meta["canonical_url"]

    def test_double_escaped_value_is_unescaped_once(self):
        html = '<meta property="og:title" content="A&amp;amp;B">'
        assert extract_article_meta_from_html(html)["title"] == "A&amp;B"

    def test_msg_link_var_is_unescaped(self):
        html = 'var msg_link = "https://mp.weixin.qq.com/s?mid=1&amp;idx=2";'
        meta = extract_article_meta_from_html(html)
        assert meta["canonical_url"] == "https://mp.weixin.qq.com/s?mid=1&idx=2"

    def test_nickname_entities_restored(self):
        html = 'var nickname = "36&#8209;氪 &amp; 研究院";'
        assert extract_article_meta_from_html(html)["account"] == "36‑氪 & 研究院"


# ---------------------------------------------------------------------------
# anchor pairing inside parsed content
# ---------------------------------------------------------------------------

class TestAnchorPairing:
    def _parse(self, body):
        from core.article_parser import parse_article_html

        html = f'<html><body><div id="js_content">{body}</div></body></html>'
        return parse_article_html(html)["content_markdown"]

    def test_empty_href_anchor_does_not_steal_neighbour_link(self):
        markdown = self._parse(
            '<a href="https://a.example/x">甲</a>'
            '<a href="">锚点占位</a>'
            '<a href="https://b.example/y">乙</a>'
        )
        assert "[甲](https://a.example/x)" in markdown
        assert "[乙](https://b.example/y)" in markdown
        assert "]()" not in markdown

    def test_bracket_pairing_balanced(self):
        markdown = self._parse('<p><a href="https://a.example/x">甲</a>与<a href="https://b.example/y">乙</a></p>')
        assert markdown.count("[") == markdown.count("]") == 2

    def test_anchor_outside_content_is_not_linked(self):
        from core.article_parser import parse_article_html

        html = ('<html><body><div id="js_content"><p>正文</p></div>'
                '<a href="https://footer.example">页脚</a></body></html>')
        markdown = parse_article_html(html)["content_markdown"]
        assert "footer.example" not in markdown


# ---------------------------------------------------------------------------
# export path containment
# ---------------------------------------------------------------------------

class TestJoinWithin:
    def test_nested_folder_allowed(self, tmp_path):
        target = join_within(tmp_path, "微信公众号/人民日报")
        assert str(target).startswith(str(tmp_path))

    def test_parent_traversal_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            join_within(tmp_path, "../outside")

    def test_deep_traversal_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            join_within(tmp_path, "a/../../outside")

    def test_absolute_path_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            join_within(tmp_path, os.path.abspath(os.path.sep))

    def test_no_parts_returns_base(self, tmp_path):
        assert join_within(tmp_path) == tmp_path.resolve()


class TestObsidianFolderSafety:
    def test_traversal_folder_is_refused_and_writes_nothing(self, tmp_path):
        from exporters.obsidian_exporter import ObsidianExporter

        vault = tmp_path / "vault"
        article = {"title": "安全测试", "link": "https://mp.weixin.qq.com/s/safe",
                   "content_text": "正文"}
        result = ObsidianExporter(vault_path=str(vault)).export_articles(
            [article], folder="../../escaped"
        )
        assert "error" in result
        assert not (tmp_path / "escaped").exists()
        assert not (tmp_path / ".." / "escaped").exists()

    def test_normal_folder_still_exports(self, tmp_path):
        from exporters.obsidian_exporter import ObsidianExporter

        vault = tmp_path / "vault"
        article = {"title": "正常导出", "link": "https://mp.weixin.qq.com/s/ok",
                   "content_text": "正文"}
        result = ObsidianExporter(vault_path=str(vault)).export_articles(
            [article], folder="微信公众号/人民日报"
        )
        assert result["files_created"] >= 1
        assert str(vault) in result["output_dir"]


# ---------------------------------------------------------------------------
# generated HTML escaping
# ---------------------------------------------------------------------------

class TestZipHtmlEscape:
    def _html(self, content_markdown):
        from exporters.zip_exporter import ZipExporter

        return ZipExporter(output_dir="/tmp")._to_html({
            "title": "标题", "account": "公众号", "link": "https://mp.weixin.qq.com/s/1",
            "content_markdown": content_markdown,
        })

    def test_script_tag_from_article_is_neutralised(self):
        page = self._html('<script>alert("xss")</script>')
        assert "<script>alert" not in page
        assert "&lt;script&gt;" in page

    def test_attribute_breakout_is_neutralised(self):
        page = self._html('" onmouseover="alert(1)')
        assert 'onmouseover="alert' not in page

    def test_markdown_still_converts_after_escaping(self):
        page = self._html("# 小标题\n\n**重点** 与 [链接](https://x.example/a?b=1&c=2)")
        assert "<h1>小标题</h1>" in page
        assert "<strong>重点</strong>" in page
        assert 'href="https://x.example/a?b=1&amp;c=2"' in page


# ---------------------------------------------------------------------------
# credentials
# ---------------------------------------------------------------------------

class TestCredentialResolution:
    def test_env_wins_over_config(self, monkeypatch):
        monkeypatch.setenv("WECHAT_SCRAPER_IMA_API_KEY", "from-env")
        cfg = {"ima": {"api_key": "from-config"}}
        assert resolve_credential(cfg, "ima") == "from-env"

    def test_config_used_when_env_absent(self, monkeypatch):
        monkeypatch.delenv("WECHAT_SCRAPER_IMA_API_KEY", raising=False)
        assert resolve_credential({"ima": {"api_key": "from-config"}}, "ima") == "from-config"

    def test_blank_values_are_treated_as_missing(self, monkeypatch):
        monkeypatch.setenv("WECHAT_SCRAPER_DIFY_API_KEY", "   ")
        assert resolve_credential({"dify": {"api_key": "x"}}, "dify") == "x"
        assert resolve_credential({"dify": {"api_key": "   "}}, "dify") is None
        assert resolve_credential({}, "dify") is None

    def test_skill_stats_never_echoes_the_key(self, monkeypatch):
        import mcp_server

        monkeypatch.setenv("WECHAT_SCRAPER_IMA_API_KEY", "SECRET-IMA-KEY")
        monkeypatch.setattr(mcp_server, "_config", {"ima": {"api_key": None},
                                                   "dify": {"api_key": None},
                                                   "obsidian": {"vault_path": None},
                                                   "fetch": {}, "sogou": {}, "net": {}})
        out = mcp_server.handle_skill_stats({})
        assert out["knowledge_base"]["ima"] is True
        assert out["knowledge_base"]["ima_key_from"] == "env"
        assert "SECRET-IMA-KEY" not in json.dumps(out, ensure_ascii=False)


# ---------------------------------------------------------------------------
# misc correctness
# ---------------------------------------------------------------------------

class TestMergeArticleBoolean:
    def test_false_is_meaningful_and_overwrites(self):
        merged = merge_article({"hot": True}, {"hot": False})
        assert merged["hot"] is False

    def test_zero_still_counts_as_empty(self):
        merged = merge_article({"word_count": 1200}, {"word_count": 0})
        assert merged["word_count"] == 1200


class TestImageFolderUniqueness:
    def test_same_title_different_link_gets_own_folder(self, tmp_path):
        downloader = ImageDownloader(output_dir=str(tmp_path))
        a = {"title": "同题文章", "link": "https://mp.weixin.qq.com/s/aaa", "images": []}
        b = {"title": "同题文章", "link": "https://mp.weixin.qq.com/s/bbb", "images": []}
        assert (downloader.download_article_images(a)["image_dir"]
                != downloader.download_article_images(b)["image_dir"])

    def test_explicit_folder_name_still_wins(self, tmp_path):
        downloader = ImageDownloader(output_dir=str(tmp_path))
        article = {"title": "任意", "link": "https://mp.weixin.qq.com/s/aaa", "images": []}
        res = downloader.download_article_images(article, folder_name="本周采集")
        assert res["image_dir"].endswith("本周采集")


class TestNoYearDate:
    def test_month_day_gets_current_year_without_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            parsed = parse_date("3月4日")
        assert parsed.year == datetime.now().year
        assert parsed.month == 3 and parsed.day == 4
        assert not [w for w in caught if issubclass(w.category, DeprecationWarning)]

    def test_impossible_month_day_is_rejected(self):
        with pytest.raises(ValueError):
            parse_date("13月40日")


# ---------------------------------------------------------------------------
# search full-text cap
# ---------------------------------------------------------------------------

class _FakeSearcher:
    def __init__(self, articles):
        self._articles = articles
        self.blocked_pages = 0
        self.retries = 0
        self.session = object()

    @property
    def blocked(self):
        return self.blocked_pages > 0

    def search_by_keyword(self, keyword, max_pages=5):
        return [dict(a) for a in self._articles]

    def search_account_articles(self, account, keyword=None, max_pages=5):
        return [dict(a) for a in self._articles]


class _FakeFetcher:
    def __init__(self):
        self.batches = []

    def enrich_articles(self, articles, session=None):
        self.batches.append(len(articles))
        enriched = []
        for article in articles:
            copy = dict(article)
            copy["content_text"] = "全文正文"
            enriched.append(copy)
        return enriched


def _articles(count):
    return [
        {"title": f"第{i}篇文章", "link": f"https://mp.weixin.qq.com/s/{i}",
         "account": "测试号", "snippet": "摘要"}
        for i in range(1, count + 1)
    ]


class TestSearchFullTextCap:
    def _run(self, mcp, monkeypatch, articles, args):
        fetcher = _FakeFetcher()
        monkeypatch.setattr(mcp, "_get_searcher", lambda: _FakeSearcher(articles))
        monkeypatch.setattr(mcp, "_get_fetcher", lambda: fetcher)
        return mcp.handle_search(args), fetcher

    def test_fetch_limit_bounds_full_text_only(self, mcp, monkeypatch):
        out, fetcher = self._run(mcp, monkeypatch, _articles(5),
                                 {"keyword": "AI", "fetch_content": True, "fetch_limit": 2})
        assert fetcher.batches == [2]
        assert out["total"] == 5
        assert [a for a in out["articles"] if a.get("content_text")] == out["articles"][:2]
        assert out["fetch_capped"] == {"cap": 2, "fetched": 2, "kept_without_content": 3}

    def test_zero_fetch_limit_means_unbounded(self, mcp, monkeypatch):
        out, fetcher = self._run(mcp, monkeypatch, _articles(4),
                                 {"keyword": "AI", "fetch_content": True, "fetch_limit": 0})
        assert fetcher.batches == [4]
        assert "fetch_capped" not in out

    def test_default_cap_comes_from_config(self, mcp, monkeypatch):
        monkeypatch.setattr(mcp, "_auto_fetch_cap", lambda: 3)
        out, fetcher = self._run(mcp, monkeypatch, _articles(6), {"keyword": "AI"})
        assert fetcher.batches == [3]
        assert out["fetch_capped"]["cap"] == 3

    def test_no_cap_reported_when_all_fetched(self, mcp, monkeypatch):
        monkeypatch.setattr(mcp, "_auto_fetch_cap", lambda: 20)
        out, fetcher = self._run(mcp, monkeypatch, _articles(3), {"keyword": "AI"})
        assert fetcher.batches == [3]
        assert "fetch_capped" not in out

    def test_max_articles_still_bounds_the_result_list(self, mcp, monkeypatch):
        out, fetcher = self._run(mcp, monkeypatch, _articles(6),
                                 {"keyword": "AI", "max_articles": 2, "fetch_limit": 10})
        assert out["total"] == 2
        assert fetcher.batches == [2]


class TestAutoFetchCapHelper:
    def test_reads_config_value(self, mcp, monkeypatch):
        monkeypatch.setattr(mcp, "_config", {"fetch": {"max_auto_fetch": 7}})
        assert mcp._auto_fetch_cap() == 7

    def test_zero_in_config_means_no_cap(self, mcp, monkeypatch):
        monkeypatch.setattr(mcp, "_config", {"fetch": {"max_auto_fetch": 0}})
        assert mcp._auto_fetch_cap() == 0

    def test_missing_key_defaults_to_twenty(self, mcp, monkeypatch):
        monkeypatch.setattr(mcp, "_config", {"fetch": {}})
        assert mcp._auto_fetch_cap() == 20


# ---------------------------------------------------------------------------
# net options wiring
# ---------------------------------------------------------------------------

class TestNetOptions:
    def test_net_options_shape(self, mcp):
        options = mcp._net_options({"net": {"retry_max_attempts": 4, "retry_backoff": 1.5,
                                           "retry_max_wait": 30, "retry_jitter": 0.1}})
        assert options == {"retry_max_attempts": 4, "retry_backoff": 1.5,
                           "retry_max_wait": 30, "retry_jitter": 0.1}

    def test_defaults_when_net_section_absent(self, mcp):
        options = mcp._net_options({})
        assert options["retry_max_attempts"] == 3
        assert options["retry_jitter"] == 0.5

    def test_searcher_and_fetcher_receive_net_options(self, mcp, monkeypatch):
        monkeypatch.setattr(mcp, "_config", {
            "sogou": {"rate_limit_min": 0, "rate_limit_max": 0, "timeout": 9},
            "fetch": {"rate_limit_min": 0, "rate_limit_max": 0, "timeout": 12},
            "net": {"retry_max_attempts": 2, "retry_backoff": 0.0,
                    "retry_max_wait": 5, "retry_jitter": 0.0},
        })
        mcp._searcher = None
        mcp._fetcher = None
        assert mcp._get_searcher().retry_max_attempts == 2
        assert mcp._get_searcher().timeout == 9
        assert mcp._get_fetcher().retry_max_attempts == 2
        assert mcp._get_fetcher().timeout == 12

    def test_shipped_config_declares_net_section(self):
        from core.utils import load_config

        cfg = load_config()
        assert cfg["net"]["retry_max_attempts"] >= 1
        assert cfg["fetch"]["max_auto_fetch"] == 20


# ---------------------------------------------------------------------------
# clean.py — artifact detection and upload packaging
# ---------------------------------------------------------------------------

class TestPackageZip:
    @pytest.fixture
    def pkg(self, tmp_path, monkeypatch):
        """A miniature skill tree; clean.py is pointed at it, not at the real package."""
        import clean

        root = tmp_path / "fake-skill"
        (root / "core").mkdir(parents=True)
        (root / "core" / "a.py").write_text("x = 1\n", encoding="utf-8")
        (root / "config.json").write_text('{"version": "9.9.9"}', encoding="utf-8")
        (root / "data" / "cache").mkdir(parents=True)
        (root / "data" / "cache" / "entry.json").write_text("{}", encoding="utf-8")
        (root / "data" / "scrape_history.json").write_text('{"v": 1}', encoding="utf-8")
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "clean.cpython-314.pyc").write_text("bin", encoding="utf-8")
        monkeypatch.setattr(clean, "PROJECT_ROOT", str(root))
        monkeypatch.setattr(clean, "PACKAGE_NAME", "fake-skill")
        return clean, root

    def test_check_finds_nested_cache_dir(self, pkg):
        """`data/cache` has a slash; matching it by basename alone used to miss it."""
        clean, root = pkg
        found = [clean._rel(p) for p in clean.check()]
        assert "__pycache__" in found
        assert "data/cache" in found, "嵌套目录漏检会让 --check 误报干净"

    def test_clean_removes_cache_dir_but_keeps_history(self, pkg):
        clean, root = pkg
        clean.clean()
        assert not (root / "data" / "cache").exists()
        assert not (root / "__pycache__").exists()
        assert (root / "data" / "scrape_history.json").exists(), "爬取历史是用户数据"

    def test_zip_excludes_binaries_and_user_data(self, pkg, tmp_path):
        clean, root = pkg
        target = clean.build_zip(str(tmp_path / "out"))
        import zipfile

        names = sorted(zipfile.ZipFile(target).namelist())
        assert names == ["fake-skill/config.json", "fake-skill/core/a.py"]
        assert not any("scrape_history" in n for n in names), "上传包不得带本地爬取历史"

    def test_zip_refuses_to_land_inside_the_package(self, pkg):
        clean, root = pkg
        with pytest.raises(ValueError):
            clean.build_zip(str(root))

    def test_real_package_zip_is_binary_free(self, tmp_path):
        """Building from the shipped tree must not leak .pyc/.db/cache into the archive."""
        import zipfile

        import clean

        target = clean.build_zip(str(tmp_path))
        names = zipfile.ZipFile(target).namelist()
        assert names, "空归档说明打包路径错了"
        for name in names:
            assert not name.endswith((".pyc", ".db", ".log")), name
            assert "__pycache__" not in name and "data/cache" not in name
            assert "scrape_history" not in name


# ---------------------------------------------------------------------------
# documentation reconciliation gate
# ---------------------------------------------------------------------------

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class TestDocsMatchCode:
    def test_skill_md_tool_table_equals_tools_schema(self, mcp):
        names = [t["name"] for t in mcp.TOOLS]
        rows = re.findall(r"^\| \d+ \| `([a-z_]+)`", _read("SKILL.md"), flags=re.MULTILINE)
        assert rows == names, f"文档工具表与 TOOLS 不一致: {set(rows) ^ set(names)}"

    def test_tool_count_in_docs_matches_schema(self, mcp):
        expected = len(mcp.TOOLS)
        for filename in ("SKILL.md", "README.md"):
            for digits in re.findall(r"(\d+)\s*个?\s*工具", _read(filename)):
                assert int(digits) == expected, f"{filename} 里的 {digits} 个工具已过时（实际 {expected}）"

    def test_documented_test_count_is_current(self, mcp):
        """文档写死的测试数量必须等于实际收集到的数量——套件绿了不代表数字没过期。"""
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
            cwd=ROOT,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            capture_output=True,
            text=True,
            timeout=180,
        )
        collected = re.search(r"(\d+) tests? collected", proc.stdout)
        assert collected, f"收集测试失败:\n{proc.stdout[-500:]}{proc.stderr[-500:]}"
        expected = int(collected.group(1))

        skill, readme = _read("SKILL.md"), _read("README.md")
        # 变更记录是新版在前，所以第一条 `测试 X→Y` 才是当前数量；旧条目留在历史里。
        head = re.search(r"- \*\*v([\d.]+)\*\*", skill[skill.index("变更记录"):])
        assert head and head.group(1) == mcp.SERVER_VERSION, "变更记录首条不是当前版本，无法定位当前数量"
        quoted = [int(n) for n in re.findall(r"(\d+) 项[，\n]", skill + readme)]
        latest = re.search(r"测试 \d+→(\d+)", skill)
        if latest:
            quoted.append(int(latest.group(1)))
        assert quoted, "文档里找不到测试数量，本闸门失效"
        for n in quoted:
            assert n == expected, f"文档写的 {n} 项已过时（实际 {expected}）"

    def test_search_schema_documents_fetch_limit(self, mcp):
        tool = next(t for t in mcp.TOOLS if t["name"] == "search_wechat_articles")
        assert "fetch_limit" in tool["inputSchema"]["properties"]

    def test_no_orphan_directories(self):
        for stale in ("scripts", "templates"):
            assert not os.path.isdir(os.path.join(ROOT, stale)), f"{stale}/ 是空目录，应删除"

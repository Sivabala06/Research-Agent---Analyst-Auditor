"""
tests/tests_fetch_tool.py

Fast tests mock httpx.get (no network). trafilatura itself runs for
real in these tests — it's a local library call, not the network, so
there's no reason to mock it. One real integration test hits an
actual URL and self-skips if the network/site is unavailable.
"""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fetch_tool
from fetch_tool import Fetcher, FetchError
from config import FETCH_MAX_HTML_BYTES

SAMPLE_HTML = """
<html><head><title>Test Article</title></head>
<body>
<article>
<h1>Tamil Nadu Overview</h1>
<p>Tamil Nadu is a state in southern India known for its rich Dravidian
culture, ancient temples, and long coastline along the Bay of Bengal.
It is one of the most industrialized states in the country, with a
long history of textile manufacturing, automobile production, and
information technology services concentrated around its major cities.</p>
<p>The state's capital is Chennai, a major hub for the automobile and
information technology industries, and home to a large port that
supports significant trade activity across the region. Chennai is
also known for its classical Carnatic music tradition, its film
industry, and its educational institutions, which attract students
from across India and abroad every year for engineering and medicine.</p>
<p>Beyond Chennai, cities like Coimbatore and Madurai are also
important economic centers, with Coimbatore known for engineering
and textiles, and Madurai known for its ancient Meenakshi temple and
its role as a major trading and pilgrimage center in the region.</p>
</article>
</body></html>  """


def test_fetch_extracts_clean_text(monkeypatch):
    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        return httpx.Response(200, content=SAMPLE_HTML.encode("utf-8"))

    monkeypatch.setattr(httpx, "get", fake_get)

    page = Fetcher().fetch("https://example.com/tamil-nadu")
    assert "Chennai" in page.text
    assert page.word_count > 0
    assert page.truncated is False


def test_fetch_raises_on_http_error(monkeypatch):
    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        return httpx.Response(404, content=b"Not Found")

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(FetchError):
        Fetcher().fetch("https://example.com/missing")


def test_fetch_raises_on_oversized_page(monkeypatch):
    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        return httpx.Response(200, content=b"x" * (FETCH_MAX_HTML_BYTES + 1))

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(FetchError):
        Fetcher().fetch("https://example.com/huge-page")


def test_fetch_raises_when_no_text_extractable(monkeypatch):
    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        return httpx.Response(200, content=b"<html><body></body></html>")

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(FetchError):
        Fetcher().fetch("https://example.com/empty-page")


def test_truncation_flags_correctly_on_long_text():
    long_text = " ".join(["word"] * 5000)
    page = Fetcher(max_text_words=100)._to_fetched_page("https://example.com", long_text)
    assert page.truncated is True
    assert page.word_count == 100
    assert page.original_word_count == 5000


def test_real_fetch_returns_text():
    candidates = [
        "https://www.thehindu.com",
        "https://www.bbc.com/news",
        "https://pib.gov.in",
    ]
    fetcher = Fetcher()
    last_error = None
    for url in candidates:
        try:
            page = fetcher.fetch(url)
            assert page.word_count > 50
            return
        except FetchError as exc:
            last_error = exc
    pytest.skip(f"No candidate URL reachable right now: {last_error}")


def test_extract_year_from_real_metadata(monkeypatch):
    monkeypatch.setattr(fetch_tool, "MIN_USEFUL_WORDS", 20)
    html_with_date = """
    <html><head><meta property="article:published_time" content="2021-05-01"></head>
    <body><article><p>Some article content that is long enough to extract, going on with
    more detail about the topic at hand for readability and length purposes here.</p></article></body></html>
    """
    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        return httpx.Response(200, content=html_with_date.encode("utf-8"))
    monkeypatch.setattr(httpx, "get", fake_get)
    page = Fetcher(max_text_words=3000).fetch("https://example.com/dated")
    assert page.source_year == 2021


def test_extract_year_returns_none_when_no_date_metadata(monkeypatch):
    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        return httpx.Response(200, content=SAMPLE_HTML.encode("utf-8"))
    monkeypatch.setattr(httpx, "get", fake_get)
    page = Fetcher().fetch("https://example.com/tamil-nadu")
    assert page.source_year is None
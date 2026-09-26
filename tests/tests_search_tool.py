"""
tests/tests_search_tool.py

Fast tests mock `ddgs.DDGS` entirely (no network, no flakiness).
One real test hits the actual internet and self-skips if DuckDuckGo
is unavailable right now — that's an expected occasional condition,
not a failure of our code.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from search_tool import DuckDuckGoSearchTool, SearchError, SearchResult


class _FakeDDGS:
    """Stand-in for ddgs.DDGS — tests our mapping/retry logic, not the network."""

    calls = 0
    fail_times = 0  # how many times to raise before succeeding

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def text(self, query, max_results=5):
        _FakeDDGS.calls += 1
        if _FakeDDGS.calls <= _FakeDDGS.fail_times:
            raise RuntimeError("simulated transient failure")
        return [
            {"title": "Result One", "href": "https://example.com/1", "body": "Snippet one"},
            {"title": "Result Two", "href": "https://example.com/2"},  # missing body on purpose
        ]


@pytest.fixture(autouse=True)
def reset_fake():
    _FakeDDGS.calls = 0
    _FakeDDGS.fail_times = 0


def test_search_maps_results_correctly(monkeypatch):
    import ddgs
    monkeypatch.setattr(ddgs, "DDGS", _FakeDDGS)

    tool = DuckDuckGoSearchTool()
    results = tool.search("test query", max_results=2)

    assert len(results) == 2
    assert isinstance(results[0], SearchResult)
    assert results[0].title == "Result One"
    assert results[0].url == "https://example.com/1"
    assert results[0].snippet == "Snippet one"
    assert results[1].snippet == ""  # missing 'body' handled gracefully


def test_search_retries_then_succeeds(monkeypatch):
    import ddgs
    _FakeDDGS.fail_times = 2  # fail twice, succeed on 3rd attempt
    monkeypatch.setattr(ddgs, "DDGS", _FakeDDGS)

    tool = DuckDuckGoSearchTool(max_retries=3, retry_delay_seconds=0.01)
    results = tool.search("test query")

    assert len(results) == 2
    assert _FakeDDGS.calls == 3


def test_search_raises_after_exhausting_retries(monkeypatch):
    import ddgs
    _FakeDDGS.fail_times = 99  # always fail
    monkeypatch.setattr(ddgs, "DDGS", _FakeDDGS)

    tool = DuckDuckGoSearchTool(max_retries=2, retry_delay_seconds=0.01)
    with pytest.raises(SearchError):
        tool.search("test query")

    assert _FakeDDGS.calls == 2


def test_real_search_returns_results():
    tool = DuckDuckGoSearchTool()
    try:
        results = tool.search("Tamil Nadu capital", max_results=3)
    except SearchError as exc:
        pytest.skip(f"Live DuckDuckGo search unavailable right now: {exc}")

    assert len(results) > 0
    assert all(isinstance(r, SearchResult) for r in results)
    assert all(r.url.startswith("http") for r in results)
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evidence import gather_evidence, EvidenceBundle
from fetch_tool import FetchedPage, FetchError
from router import RoutedSearchResults
from planner import ResearchPlan
from search_tool import SearchResult


def _dummy_plan():
    return ResearchPlan(
        original_question="test",
        entities=[],
        route="direct",
        sub_questions=["test"],
        reasoning="",
    )


def test_gather_evidence_collects_successful_fetches():
    routed = RoutedSearchResults(_dummy_plan())
    routed.add("test", [SearchResult(title="A", url="https://a.com", snippet="")])

    fetcher = MagicMock()
    fetcher.fetch.return_value = FetchedPage(url="https://a.com", text="real content here", word_count=3, truncated=False)

    bundle = gather_evidence(routed, fetcher)
    assert len(bundle.pieces) == 1
    assert bundle.pieces[0].url == "https://a.com"
    assert bundle.failed_urls == []


def test_gather_evidence_skips_failed_fetch_without_crashing():
    routed = RoutedSearchResults(_dummy_plan())
    routed.add("test", [
        SearchResult(title="Good", url="https://good.com", snippet=""),
        SearchResult(title="Bad", url="https://bad.com", snippet=""),
    ])

    fetcher = MagicMock()
    def side_effect(url):
        if url == "https://bad.com":
            raise FetchError("403")
        return FetchedPage(url=url, text="real content", word_count=2, truncated=False)
    fetcher.fetch.side_effect = side_effect

    bundle = gather_evidence(routed, fetcher)
    assert len(bundle.pieces) == 1
    assert bundle.pieces[0].url == "https://good.com"
    assert bundle.failed_urls == ["https://bad.com"]
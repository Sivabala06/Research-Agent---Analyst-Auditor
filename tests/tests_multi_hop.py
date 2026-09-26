import sys
from pathlib import Path
from unittest.mock import MagicMock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import multi_hop
from multi_hop import run_multi_hop
from planner import ResearchPlan
from search_tool import SearchResult
from fetch_tool import FetchedPage, FetchError


def _plan():
    return ResearchPlan(original_question="where did X work before?", entities=["X"],
                         route="multi_hop", sub_questions=["who is the CTO of X", "where did they work before"],
                         reasoning="")


def test_hop2_query_built_from_hop1_result(monkeypatch):
    search_calls = []
    search_tool = MagicMock()
    def fake_search(query, max_results=5):
        search_calls.append(query)
        return [SearchResult(title="t", url=f"https://site.com/{len(search_calls)}", snippet="")]
    search_tool.search.side_effect = fake_search

    fetcher = MagicMock()
    fetcher.fetch.return_value = FetchedPage(url="https://site.com", text="Jane Doe is the CTO of X.", word_count=6, truncated=False)

    def fake_llm(prompt, schema, max_output_tokens):
        return SimpleNamespace(parsed={"extracted_value": "Jane Doe", "found": True})
    monkeypatch.setattr(multi_hop, "_llm_client", SimpleNamespace(call=fake_llm))

    bundle = run_multi_hop(_plan(), search_tool, fetcher)
    assert len(bundle.pieces) == 2
    assert "Jane Doe" in search_calls[1]  # hop 2 query built from hop 1's real extracted fact


def test_stops_at_one_hop_if_extraction_fails(monkeypatch):
    search_tool = MagicMock()
    search_tool.search.return_value = [SearchResult(title="t", url="https://a.com", snippet="")]
    fetcher = MagicMock()
    fetcher.fetch.return_value = FetchedPage(url="https://a.com", text="unrelated text", word_count=2, truncated=False)

    def fake_llm(prompt, schema, max_output_tokens):
        return SimpleNamespace(parsed={"extracted_value": "", "found": False})
    monkeypatch.setattr(multi_hop, "_llm_client", SimpleNamespace(call=fake_llm))

    bundle = run_multi_hop(_plan(), search_tool, fetcher)
    assert len(bundle.pieces) == 1  # only hop 1, no crash


def test_hop1_total_failure_returns_empty_bundle():
    search_tool = MagicMock()
    search_tool.search.side_effect = Exception("network down")
    bundle = run_multi_hop(_plan(), MagicMock(), MagicMock())
    assert bundle.pieces == []
    assert len(bundle.failed_urls) == 1
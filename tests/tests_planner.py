"""
tests/tests_planner.py

Entity extraction and route classification are pure functions --
tested directly, no mocking needed. Sub-question generation is
tested with the LLM mocked (fast, deterministic) plus one test that
proves the fallback path works when the LLM misbehaves.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import planner
from planner import extract_entities, classify_route, generate_sub_questions, create_plan


def test_extract_entities_finds_company_names():
    entities = extract_entities("Which three Indian jewellery retailers opened the most new stores?")
    assert "Indian" in entities


def test_extract_entities_filters_stopwords():
    entities = extract_entities("What is the capital of France?")
    assert "What" not in entities


def test_classify_route_direct():
    assert classify_route("Who is the CEO of Infosys?") == "direct"


def test_classify_route_multi_source():
    assert classify_route("Which three retailers opened the most new stores?") == "multi_source"


def test_classify_route_multi_hop():
    assert classify_route("Find the CTO and where they worked before joining.") == "multi_hop"


def test_direct_route_skips_llm_entirely(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM should NOT be called for direct route")
    monkeypatch.setattr(planner._llm_client, "call", fail_if_called)

    sub_qs, reasoning = generate_sub_questions("Who is the CEO of Infosys?", ["Infosys"], "direct")
    assert sub_qs == ["Who is the CEO of Infosys?"]


def test_multi_source_calls_llm_and_parses_json(monkeypatch):
    def fake_llm(prompt, **kwargs):
        return SimpleNamespace(parsed={
            "sub_questions": ["top jewellery retailers India 2024", "jewellery retailer store count India"],
            "reasoning": "split by data need",
        })
    monkeypatch.setattr(planner._llm_client, "call", fake_llm)

    sub_qs, reasoning = generate_sub_questions("Which three jewellery retailers grew most?", [], "multi_source")
    assert len(sub_qs) == 2
    assert "reasoning" not in sub_qs  # sanity: didn't accidentally return the whole dict


def test_llm_failure_falls_back_gracefully(monkeypatch):
    def broken_llm(prompt, **kwargs):
        return SimpleNamespace(parsed=None)
    monkeypatch.setattr(planner._llm_client, "call", broken_llm)

    sub_qs, reasoning = generate_sub_questions("Compare X and Y", [], "multi_source")
    assert sub_qs == ["Compare X and Y"]
    assert "fell back" in reasoning.lower()


def test_create_plan_end_to_end(monkeypatch):
    def fake_llm(prompt, **kwargs):
        return SimpleNamespace(parsed={
            "sub_questions": ["query a", "query b"],
            "reasoning": "test",
        })
    monkeypatch.setattr(planner._llm_client, "call", fake_llm)

    plan = create_plan("Which three Indian jewellery retailers opened the most new stores?")
    assert plan.route == "multi_source"
    assert len(plan.sub_questions) == 2
    assert plan.original_question.startswith("Which three")
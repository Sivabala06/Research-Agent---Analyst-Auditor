import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import claims
from claims import generate_candidate_answer
from evidence import EvidenceBundle, EvidencePiece
from planner import ResearchPlan


def _dummy_plan():
    return ResearchPlan(original_question="Who is the CEO of Infosys?", entities=["Infosys"],
                         route="direct", sub_questions=["Who is the CEO of Infosys?"], reasoning="")


def _dummy_bundle():
    return EvidenceBundle(pieces=[
        EvidencePiece(sub_question="q", url="https://real-source.com", title="Infosys News",
                      text="Salil Parekh is the CEO of Infosys.", word_count=6)
    ])


def test_no_evidence_returns_honest_unresolved():
    result = generate_candidate_answer(_dummy_plan(), EvidenceBundle())
    assert result.claims == []
    assert "could not find" in result.answer_text.lower()


def test_valid_claim_gets_real_url_attached(monkeypatch):
    def fake_call(prompt, schema, max_output_tokens):
        return SimpleNamespace(parsed={
            "claims": [{"statement": "Salil Parekh is the CEO of Infosys.", "evidence_number": 1, "confidence": "stated"}],
            "unresolved": "",
        })
    monkeypatch.setattr(claims._llm_client, "call", fake_call)

    result = generate_candidate_answer(_dummy_plan(), _dummy_bundle())
    assert len(result.claims) == 1
    assert result.claims[0].url == "https://real-source.com"
    assert "[1]" in result.answer_text


def test_claim_with_invalid_evidence_number_is_dropped(monkeypatch):
    def fake_call(prompt, schema, max_output_tokens):
        return SimpleNamespace(parsed={
            "claims": [{"statement": "Made up fact.", "evidence_number": 99, "confidence": "stated"}],
            "unresolved": "",
        })
    monkeypatch.setattr(claims._llm_client, "call", fake_call)

    result = generate_candidate_answer(_dummy_plan(), _dummy_bundle())
    assert result.claims == []
    assert "could not confirm" in result.answer_text.lower()


def test_llm_parse_failure_degrades_honestly(monkeypatch):
    def fake_call(prompt, schema, max_output_tokens):
        return SimpleNamespace(parsed=None)
    monkeypatch.setattr(claims._llm_client, "call", fake_call)

    result = generate_candidate_answer(_dummy_plan(), _dummy_bundle())
    assert result.claims == []
    assert "unable to generate" in result.answer_text.lower()

def test_claim_echoing_the_question_is_dropped(monkeypatch):
    def fake_call(prompt, schema, max_output_tokens):
        return SimpleNamespace(parsed={
            "claims": [{"statement": _dummy_plan().original_question, "evidence_number": 1, "confidence": "stated"}],
            "unresolved": "",
        })
    monkeypatch.setattr(claims._llm_client, "call", fake_call)
    result = generate_candidate_answer(_dummy_plan(), _dummy_bundle())
    assert result.claims == []

def test_duplicate_claims_are_collapsed(monkeypatch):
    def fake_call(prompt, schema, max_output_tokens):
        return SimpleNamespace(parsed={
            "claims": [
                {"statement": "Salil Parekh is the CEO of Infosys.", "evidence_number": 1, "confidence": "stated"},
                {"statement": "Salil Parekh is the CEO of Infosys!", "evidence_number": 1, "confidence": "stated"},
            ],
            "unresolved": "",
        })
    monkeypatch.setattr(claims._llm_client, "call", fake_call)
    result = generate_candidate_answer(_dummy_plan(), _dummy_bundle())
    assert len(result.claims) == 1


# FIX 5.4 — Synthesis test

def test_synthesis_fires_for_comparative_multi_source_question(monkeypatch):
    """Synthesis LLM call must fire for a comparative multi_source question
    and prepend the verdict to answer_text."""
    plan = ResearchPlan(original_question="Which grew faster, X or Y?", entities=[],
                         route="multi_source", sub_questions=["q"], reasoning="")
    calls = {"n": 0}

    def fake_call(prompt, schema, max_output_tokens):
        calls["n"] += 1
        if calls["n"] == 1:
            # First call: claims extractor
            return SimpleNamespace(parsed={"claims": [
                {"statement": "X grew 10%", "evidence_number": 1, "confidence": "stated"},
                {"statement": "Y grew 30%", "evidence_number": 1, "confidence": "stated"},
            ], "unresolved": ""})
        # Second call: synthesis
        return SimpleNamespace(parsed={
            "verdict": "Y grew faster than X.",
            "based_on_claims": [1, 2],
            "could_not_decide": False,
        })

    monkeypatch.setattr(claims._llm_client, "call", fake_call)
    bundle = EvidenceBundle(pieces=[
        EvidencePiece(sub_question="q", url="https://src.com", title="T",
                      text="X grew 10% and Y grew 30%", word_count=8)
    ])
    result = generate_candidate_answer(plan, bundle)
    assert "Y grew faster" in result.answer_text
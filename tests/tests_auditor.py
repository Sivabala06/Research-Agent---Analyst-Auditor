import sys
from pathlib import Path
from unittest.mock import MagicMock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auditor
from auditor import audit_answer
from claims import CandidateAnswer, Claim
from fetch_tool import FetchedPage, FetchError
from evidence import EvidenceBundle, EvidencePiece


def _answer_with(claims):
    return CandidateAnswer(question="q", claims=claims, unresolved="", answer_text="")


def test_no_url_is_unsupported_without_llm_call(monkeypatch):
    def fail(*a, **k): raise AssertionError("LLM should not be called")
    monkeypatch.setattr(auditor._llm_client, "call", fail)
    claim = Claim(statement="X", evidence_number=1, url="", confidence="stated")
    report = audit_answer(_answer_with([claim]), MagicMock())
    assert report.audited_claims[0].verdict == "unsupported"
    assert report.passed is False


def test_fetch_failure_marks_unsupported_not_crash():
    claim = Claim(statement="X", evidence_number=1, url="https://gone.com", confidence="stated")
    fetcher = MagicMock()
    fetcher.fetch.side_effect = FetchError("404")
    report = audit_answer(_answer_with([claim]), fetcher)
    assert report.audited_claims[0].verdict == "unsupported"


def test_supported_verdict_passes(monkeypatch):
    def fake_call(prompt, schema, max_output_tokens):
        return SimpleNamespace(parsed={"verdict": "supported", "reason": "matches"})
    monkeypatch.setattr(auditor._llm_client, "call", fake_call)
    claim = Claim(statement="Salil Parekh is CEO", evidence_number=1, url="https://real.com", confidence="stated")
    fetcher = MagicMock()
    fetcher.fetch.return_value = FetchedPage(url="https://real.com", text="Salil Parekh is the CEO.", word_count=5, truncated=False)
    report = audit_answer(_answer_with([claim]), fetcher)
    assert report.audited_claims[0].verdict == "supported"
    assert report.passed is True


def test_contradicted_claim_fails_report(monkeypatch):
    def fake_call(prompt, schema, max_output_tokens):
        return SimpleNamespace(parsed={"verdict": "contradicted", "reason": "source says otherwise"})
    monkeypatch.setattr(auditor._llm_client, "call", fake_call)
    claim = Claim(statement="X is CEO", evidence_number=1, url="https://real.com", confidence="stated")
    fetcher = MagicMock()
    fetcher.fetch.return_value = FetchedPage(url="https://real.com", text="Y is actually the CEO.", word_count=5, truncated=False)
    report = audit_answer(_answer_with([claim]), fetcher)
    assert report.audited_claims[0].verdict == "contradicted"
    assert report.passed is False


# FIX 5.2 — Corroboration tests

def test_corroborated_claim_flagged_true(monkeypatch):
    def fake_call(prompt, schema, max_output_tokens):
        return SimpleNamespace(parsed={"verdict": "supported", "reason": "matches"})
    monkeypatch.setattr(auditor._llm_client, "call", fake_call)
    claim = Claim(statement="Kalyan reported 30.1% growth", evidence_number=1, url="https://a.com", confidence="stated")
    fetcher = MagicMock()
    fetcher.fetch.return_value = FetchedPage(url="https://a.com", text="Kalyan reported 30.1% growth", word_count=5, truncated=False)
    bundle = EvidenceBundle(pieces=[
        EvidencePiece(sub_question="q", url="https://a.com", title="t", text="Kalyan reported 30.1% growth", word_count=5),
        EvidencePiece(sub_question="q", url="https://b.com", title="t2", text="Other reports also confirm the 30.1% figure", word_count=6),
    ])
    report = audit_answer(_answer_with([claim]), fetcher, bundle)
    assert report.audited_claims[0].corroborated is True


def test_single_source_claim_flagged_uncorroborated(monkeypatch):
    def fake_call(prompt, schema, max_output_tokens):
        return SimpleNamespace(parsed={"verdict": "supported", "reason": "matches"})
    monkeypatch.setattr(auditor._llm_client, "call", fake_call)
    claim = Claim(statement="X reported 99% growth", evidence_number=1, url="https://a.com", confidence="stated")
    fetcher = MagicMock()
    fetcher.fetch.return_value = FetchedPage(url="https://a.com", text="X reported 99% growth", word_count=5, truncated=False)
    bundle = EvidenceBundle(pieces=[EvidencePiece(sub_question="q", url="https://a.com", title="t", text="X reported 99% growth", word_count=5)])
    report = audit_answer(_answer_with([claim]), fetcher, bundle)
    assert report.audited_claims[0].corroborated is False

def test_source_tier_and_confidence_computed(monkeypatch):
    def fake_call(prompt, schema, max_output_tokens):
        return SimpleNamespace(parsed={"verdict": "supported", "reason": "matches"})
    monkeypatch.setattr(auditor._llm_client, "call", fake_call)
    claim = Claim(statement="ISRO fact", evidence_number=1, url="https://www.isro.gov.in/x", confidence="stated")
    fetcher = MagicMock()
    fetcher.fetch.return_value = FetchedPage(url="https://www.isro.gov.in/x", text="ISRO fact confirmed here", word_count=4, truncated=False)
    report = audit_answer(_answer_with([claim]), fetcher)
    assert report.audited_claims[0].source_tier == "tier_1"
    assert report.confidence_score > 0.0
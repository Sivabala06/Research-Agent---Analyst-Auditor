import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import graph
from claims import CandidateAnswer
from planner import ResearchPlan
from router import RoutedSearchResults
from evidence import EvidenceBundle
from auditor import AuditReport
from memory import MemoryStore


def _patch_all(monkeypatch, tmp_path, passed=True):
    plan = ResearchPlan(original_question="q", entities=["X"], route="direct", sub_questions=["q"], reasoning="")
    monkeypatch.setattr(graph, "create_plan", lambda q: plan)
    monkeypatch.setattr(graph, "run_search_for_plan", lambda p, t: RoutedSearchResults(p))
    monkeypatch.setattr(graph, "gather_evidence", lambda r, f: EvidenceBundle())
    answer = CandidateAnswer(question="q", claims=[], unresolved="", answer_text="done")
    monkeypatch.setattr(graph, "generate_candidate_answer", lambda p, e, trace=None: answer)
    audit = AuditReport(question="q", audited_claims=[], passed=passed, supported_count=0, unsupported_count=0, contradicted_count=0)
    monkeypatch.setattr(graph, "audit_answer", lambda a, f, e=None, t=None: audit)
    monkeypatch.setattr(graph, "_memory", MemoryStore(tmp_path / "graph-memory.db"))

def test_pipeline_end_to_end_on_first_pass(monkeypatch, tmp_path):
    _patch_all(monkeypatch, tmp_path, passed=True)
    result = graph.run_pipeline("q", log_path=str(tmp_path / "runs.jsonl"))
    assert result.validated_answer.answer_text is not None
    assert result.audit_report.passed is True

def test_pipeline_retries_once_on_audit_fail_then_stops(monkeypatch, tmp_path):
    _patch_all(monkeypatch, tmp_path, passed=False)
    result = graph.run_pipeline("q", log_path=str(tmp_path / "runs.jsonl"))
    assert result.retry_count <= 1
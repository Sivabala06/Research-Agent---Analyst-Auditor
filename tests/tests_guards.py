import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from guards import input_guard, output_guard, InputGuardError
from claims import CandidateAnswer, Claim
from auditor import AuditReport, AuditedClaim


def test_empty_question_rejected():
    try:
        input_guard("   ")
        assert False
    except InputGuardError:
        pass


def test_valid_question_passes_through():
    assert input_guard(" Who is the CEO? ") == "Who is the CEO?"


from auditor import AuditedClaim, AuditReport

def test_output_guard_flags_all_tier3_sources():
    claim = Claim(statement="X", evidence_number=1, url="https://randomblog.com")
    answer = CandidateAnswer(question="q", claims=[claim], unresolved="", answer_text="X [1]")
    audited = AuditedClaim(statement="X", url="https://randomblog.com", verdict="supported", reason="ok", source_tier="tier_3", source_score=0.3)
    audit = AuditReport(question="q", audited_claims=[audited], passed=True, supported_count=1, unsupported_count=0, contradicted_count=0)
    validated = output_guard(answer, audit)
    assert "lower-tier" in validated.unresolved
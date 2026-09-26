"""guards.py — INPUT GUARD and OUTPUT GUARD. Deliberately rule-based,
not another LLM call — these are sanity/safety checks, not reasoning."""
from __future__ import annotations
from claims import CandidateAnswer
from auditor import AuditReport


class InputGuardError(ValueError):
    pass


def input_guard(question: str) -> str:
    q = question.strip()
    if not q:
        raise InputGuardError("Empty question.")
    if len(q) > 500:
        raise InputGuardError("Question too long — likely malformed input.")
    for marker in ["ignore previous instructions", "system prompt", "you are now"]:
        if marker in q.lower():
            raise InputGuardError(f"Disallowed pattern: {marker!r}")
    return q


def output_guard(answer: CandidateAnswer, audit: AuditReport) -> CandidateAnswer:
    verdicts = {ac.statement: ac.verdict for ac in audit.audited_claims}
    tiers = {ac.statement: ac.source_tier for ac in audit.audited_claims}
    kept = [c for c in answer.claims if verdicts.get(c.statement) == "supported"]
    dropped = len(answer.claims) - len(kept)
    text = " ".join(f"{c.statement} [{c.url}]" for c in kept) or "No claims could be independently verified."
    note = answer.unresolved
    if dropped:
        note = f"{note} {dropped} claim(s) failed audit and were removed.".strip()
    if kept and all(tiers.get(c.statement) == "tier_3" for c in kept):
        note = f"{note} Note: this answer relies only on lower-tier/unclassified sources; treat with extra caution.".strip()
    return CandidateAnswer(question=answer.question, claims=kept, unresolved=note, answer_text=text)
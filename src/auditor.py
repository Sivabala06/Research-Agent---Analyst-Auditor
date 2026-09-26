"""
auditor.py

Part B: independently verifies a CandidateAnswer. For each claim,
RE-FETCHES the cited URL fresh -- does not reuse the analyst's
already-gathered evidence text. Reusing it would let an analyst bug
and an auditor bug cancel out silently; re-fetching means the
auditor is a genuinely separate check, not a rubber stamp.

HONESTY REQUIREMENT (explicit, from the problem statement: "an
auditor that approves everything is telling us nothing"): every
claim gets exactly one of three verdicts -- never a default pass.
A claim with no citation at all is automatically unsupported, no
LLM call spent on it.

FIX 5.2: _check_corroboration is now wired into _audit_single_claim
and audit_answer accepts an evidence_bundle parameter so the auditor
can cross-check claims against OTHER retrieved sources, not just the
cited one.

FIX 5.3: prompt strengthened to check internal logical consistency,
not just literal source-text overlap. HONEST LIMITATION: this is a
prompt instruction, not a formal logic checker — it improves catch
rate on obvious cases (e.g. "worked at VSSC before joining ISRO" when
VSSC is part of ISRO) but is not guaranteed.
"""

from __future__ import annotations
from text_utils import best_snippet
from source_scoring import score_source
import logging
import re
from typing import Literal
from pydantic import BaseModel
from claims import CandidateAnswer, Claim
from fetch_tool import Fetcher, FetchError
from llm_client import OllamaClient
from config import AUDITOR_MAX_OUTPUT_TOKENS

logger = logging.getLogger("research_agent.auditor")
_llm_client = OllamaClient()

Verdict = Literal["supported", "unsupported", "contradicted"]


class AuditedClaim(BaseModel):
    statement: str
    url: str
    verdict: Verdict
    reason: str
    corroborated: bool = False
    corroboration_note: str = ""
    source_tier: str = "unscored"
    source_score: float = 0.0

class AuditReport(BaseModel):
    question: str
    audited_claims: list[AuditedClaim]
    passed: bool
    supported_count: int
    unsupported_count: int
    contradicted_count: int

    @property
    def confidence_score(self) -> float:
        """Return a verification-completeness signal, not a probability."""
        if not self.audited_claims:
            return 0.0
        support_weight = self.supported_count
        corroborated_bonus = sum(0.5 for claim in self.audited_claims
                                  if claim.corroborated and claim.verdict == "supported")
        max_possible = len(self.audited_claims) * 1.5
        return round((support_weight + corroborated_bonus) / max_possible, 2)


class VerdictResponse(BaseModel):
    verdict: Verdict
    reason: str = ""


# ---------------------------------------------------------------------------
# FIX 5.2 — Corroboration helpers
# ---------------------------------------------------------------------------

def _extract_check_tokens(statement: str) -> list[str]:
    """Crude but transparent: pulls numbers/percentages and proper-noun-like
    words out of a claim statement, used only to check whether ANOTHER
    fetched source also mentions the same fact. This is heuristic token
    overlap, not deep semantic matching -- stated honestly, not hidden."""
    numbers = re.findall(r"\d[\d,\.]*%?", statement)
    proper_nouns = re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", statement)
    return list(set(numbers + proper_nouns))


def _check_corroboration(claim: Claim, evidence_bundle) -> tuple[bool, str]:
    if evidence_bundle is None:
        return False, "Cross-check not performed (no evidence bundle passed)."
    tokens = _extract_check_tokens(claim.statement)
    if not tokens:
        return False, "No checkable numbers/names in this claim to cross-check."
    other_pieces = [p for p in evidence_bundle.pieces if p.url != claim.url]
    if not other_pieces:
        return False, "Only one source was retrieved for this topic; no other source available to cross-check against."
    for piece in other_pieces:
        if any(tok in piece.text for tok in tokens):
            return True, f"Corroborated: also appears in {piece.url}"
    return False, f"Not found in any of the {len(other_pieces)} other retrieved source(s) -- appears in only one source."


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------

def _audit_single_claim(claim: Claim, fetcher: Fetcher, evidence_bundle=None, trace=None) -> AuditedClaim:
    # Claims with no URL are auto-unsupported — no LLM cost spent.
    if not claim.url:
        corroborated, corroboration_note = _check_corroboration(claim, evidence_bundle)
        return AuditedClaim(
            statement=claim.statement, url="", verdict="unsupported",
            reason="No citation was provided for this claim.",
            corroborated=corroborated, corroboration_note=corroboration_note,
        )

    try:
        page = fetcher.fetch(claim.url)
    except FetchError as exc:
        # Can't re-verify a source that's no longer fetchable -- that's
        # itself a finding, not something to silently skip.
        corroborated, corroboration_note = _check_corroboration(claim, evidence_bundle)
        return AuditedClaim(
            statement=claim.statement, url=claim.url, verdict="unsupported",
            reason=f"Could not re-fetch cited source to verify: {exc}",
            corroborated=corroborated, corroboration_note=corroboration_note,
        )

    tier, score = score_source(claim.url, page.text)
    snippet = best_snippet(page.text, claim.statement, window_words=260)

    prompt = f"""You are a strict, independent fact-checking auditor. Evaluate whether the cited
source directly supports the claim. Check every material detail, including names,
dates, quantities, and relationships. Also flag contradictions or internal logical
inconsistencies evident from the source. Do not rely on outside knowledge.

CLAIM: {claim.statement}

SOURCE TEXT:
{snippet}

Respond with ONLY a JSON object in this exact shape:
{{"verdict": "supported" | "unsupported" | "contradicted", "reason": "one short sentence"}}

- "supported": the source clearly confirms all material parts of the claim.
- "contradicted": the source explicitly conflicts with a material part.
- "unsupported": the source does not provide enough information to verify it.

Be strict. If the source is ambiguous or only partially relevant, choose "unsupported".
"""
    result = _llm_client.call(prompt, schema=VerdictResponse, max_output_tokens=AUDITOR_MAX_OUTPUT_TOKENS)
    if trace:
        trace.log_llm_call("auditor", result)
    corroborated, corroboration_note = _check_corroboration(claim, evidence_bundle)

    if result.parsed is None:
        return AuditedClaim(statement=claim.statement, url=claim.url, verdict="unsupported",
                             reason="Auditor model failed to produce a valid verdict.",
                             corroborated=corroborated, corroboration_note=corroboration_note,
                             source_tier=tier, source_score=score)

    return AuditedClaim(statement=claim.statement, url=claim.url,
                         verdict=result.parsed["verdict"], reason=result.parsed.get("reason", ""),
                         corroborated=corroborated, corroboration_note=corroboration_note,
                         source_tier=tier, source_score=score)


def audit_answer(answer: CandidateAnswer, fetcher: Fetcher, evidence_bundle=None, trace=None) -> AuditReport:
    """FIX 5.2: evidence_bundle is now accepted and forwarded to _audit_single_claim
    so each claim can be cross-checked against OTHER retrieved sources."""
    audited = [_audit_single_claim(c, fetcher, evidence_bundle, trace) for c in answer.claims]

    supported = sum(1 for a in audited if a.verdict == "supported")
    unsupported = sum(1 for a in audited if a.verdict == "unsupported")
    contradicted = sum(1 for a in audited if a.verdict == "contradicted")

    return AuditReport(
        question=answer.question,
        audited_claims=audited,
        passed=(len(audited) > 0 and contradicted == 0 and unsupported == 0),
        supported_count=supported,
        unsupported_count=unsupported,
        contradicted_count=contradicted,
    )
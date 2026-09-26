"""
claims.py

Takes an EvidenceBundle and produces a CandidateAnswer: a set of
individual, citation-backed Claims plus a final answer string built
from them. This is the CLAIMS -> CANDIDATE ANSWER step in the
architecture diagram.

CITATION SAFETY DESIGN (the important part of this file):
We never let the LLM write a URL from memory into its output — it
would occasionally typo, truncate, or invent one. Instead, evidence
is shown to the model as a numbered list ([1], [2]...), the model
cites by number, and we map numbers back to real URLs in code. This
means a citation is either a real fetched URL or the claim is
rejected — never a hallucinated string that merely looks like one.

HONESTY REQUIREMENT (from the problem statement): if evidence is
thin or contradictory, the model is explicitly instructed to say so
rather than fill the gap with a plausible guess. We also mechanically
enforce a version of this: any claim citing an evidence number that
doesn't exist is dropped before it ever reaches the user.

FIX 5.4: synthesize_verdict() added — for comparative multi_source
questions ("which grew faster", "which is biggest") an extra cheap
LLM call is made using ONLY the already-extracted claim statements
to produce a single direct verdict, instead of leaving the user to
infer one from a list of atomic facts. Explicitly allowed to say
"could not decide" — never forced to pick a side it can't support.
"""

from __future__ import annotations
from tracer import TraceRecorder
from text_utils import best_snippet
import json
import logging
from pydantic import BaseModel, Field

from config import (
    CLAIMS_MAX_OUTPUT_TOKENS,
    MAX_EVIDENCE_PIECES_IN_PROMPT,
    SYNTHESIS_MAX_OUTPUT_TOKENS,
    COMPARISON_WORDS,
)
from evidence import EvidenceBundle
from planner import ResearchPlan
from llm_client import OllamaClient

logger = logging.getLogger("research_agent.claims")

_llm_client = OllamaClient()

from difflib import SequenceMatcher


class Claim(BaseModel):
    """One atomic, citable statement in the final answer."""
    statement: str
    evidence_number: int          # the [N] the LLM cited
    url: str = ""                 # filled in AFTER validation, not by the LLM
    confidence: str = "stated"    # "stated" | "uncertain" — model's own hedge


class ClaimsResponse(BaseModel):
    """Raw schema the LLM must fill — evidence_number only, no URLs yet."""
    claims: list[Claim]
    unresolved: str = ""   # what the model could NOT find evidence for, stated plainly


class CandidateAnswer(BaseModel):
    """Final structured output of this node — what the Auditor will check."""
    question: str
    claims: list[Claim]
    unresolved: str
    answer_text: str       # human-readable answer assembled from claims


# ---------------------------------------------------------------------------
# FIX 5.4 — Synthesis verdict for comparative questions
# ---------------------------------------------------------------------------

class SynthesisResponse(BaseModel):
    verdict: str
    based_on_claims: list[int] = Field(default_factory=list)
    could_not_decide: bool = False


def _question_needs_synthesis(question: str, route: str) -> bool:
    if route != "multi_source":
        return False
    q = question.lower()
    return any(word in q for word in COMPARISON_WORDS)


def synthesize_verdict(plan: ResearchPlan, valid_claims: list[Claim], trace=None) -> str:
    """For comparative multi_source questions with >=2 supported-looking
    claims, makes ONE extra cheap LLM call to state a direct verdict instead
    of leaving the person to infer one from a list of atomic facts. Uses only
    the already-extracted claim STATEMENTS (not full evidence text) to keep
    this cheap. Explicitly allowed to say it cannot decide -- never forced to
    pick a side it can't support."""
    if not _question_needs_synthesis(plan.original_question, plan.route) or len(valid_claims) < 2:
        return ""

    numbered = "\n".join(f"{i+1}. {c.statement}" for i, c in enumerate(valid_claims))
    prompt = f"""Question: {plan.original_question}

Here are verified facts relevant to this question:
{numbered}

Based ONLY on these facts, give a ONE-SENTENCE direct answer to the question
(e.g. state which option is faster/bigger/better, or explicitly say the facts
are insufficient/ambiguous to decide). Do not introduce new facts.

Respond with ONLY JSON: {{"verdict": "...", "based_on_claims": [1,2], "could_not_decide": false}}
"""
    result = _llm_client.call(prompt, schema=SynthesisResponse, max_output_tokens=SYNTHESIS_MAX_OUTPUT_TOKENS)
    if trace:
        trace.log_llm_call("synthesis", result)
    if result.parsed is None:
        return ""
    if result.parsed.get("could_not_decide"):
        return f"(Could not determine a clear answer from available evidence: {result.parsed.get('verdict', '')})"
    return result.parsed.get("verdict", "")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_near_duplicate(a: str, b: str, threshold: float = 0.85) -> bool:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio() >= threshold




def _build_evidence_block(bundle: EvidenceBundle, question: str) -> tuple[str, dict[int, str]]:
    capped = bundle.pieces[:MAX_EVIDENCE_PIECES_IN_PROMPT]
    if len(bundle.pieces) > MAX_EVIDENCE_PIECES_IN_PROMPT:
        logger.warning("Evidence capped at %d of %d pieces for prompt size.",
                        MAX_EVIDENCE_PIECES_IN_PROMPT, len(bundle.pieces))

    lines = []
    number_to_url: dict[int, str] = {}
    for i, piece in enumerate(capped, start=1):
        number_to_url[i] = piece.url
        year_tag = f"({piece.source_year}) " if piece.source_year else ""
        snippet = best_snippet(piece.text, question)
        lines.append(f"[{i}] {year_tag}SOURCE: {piece.title or piece.url}\n{snippet}")

    return "\n\n".join(lines), number_to_url

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_candidate_answer(
    plan: ResearchPlan,
    bundle: EvidenceBundle,
    trace: TraceRecorder | None = None,
) -> CandidateAnswer:
    if not bundle.pieces:
        return CandidateAnswer(
            question=plan.original_question,
            claims=[],
            unresolved="No usable evidence was retrieved for this question.",
            answer_text="I could not find reliable evidence to answer this question.",
        )

    evidence_block, number_to_url = _build_evidence_block(bundle, plan.original_question)
    prompt = f"""You are a careful research analyst. Answer the question using ONLY the
numbered evidence below. Every claim you make MUST cite the evidence number
it came from. If the evidence does not support something, do NOT include it
-- state it as unresolved instead of guessing.

QUESTION: {plan.original_question}

EVIDENCE:
{evidence_block}

Respond with ONLY a JSON object in this exact shape:
{{"claims": [{{"statement": "...", "evidence_number": 1, "confidence": "stated"}}],
  "unresolved": "one sentence on what could not be confirmed, or empty string"}}
"""

    result = _llm_client.call(prompt, schema=ClaimsResponse, max_output_tokens=CLAIMS_MAX_OUTPUT_TOKENS)
    if trace:
        trace.log_llm_call("claims", result)

    if result.parsed is None:
        logger.warning("Claims generation returned unparseable output; degrading to empty answer.")
        return CandidateAnswer(
            question=plan.original_question,
            claims=[],
            unresolved="The analyst model failed to produce a valid structured answer.",
            answer_text="I was unable to generate a reliable answer for this question.",
        )

    raw_claims = result.parsed["claims"]
    valid_claims: list[Claim] = []
    seen_statements: list[str] = []
    for c in raw_claims:
        statement = (c.get("statement") or "").strip()
        num = c.get("evidence_number")
        url = number_to_url.get(num)

        if url is None:
            logger.warning("Dropped claim citing invalid evidence number %r: %r", num, statement)
            continue
        if not statement:
            logger.warning("Dropped empty claim statement.")
            continue
        if _is_near_duplicate(statement, plan.original_question):
            logger.warning("Dropped claim that just echoes the question instead of answering it: %r", statement)
            continue
        if any(_is_near_duplicate(statement, seen) for seen in seen_statements):
            logger.warning("Dropped near-duplicate claim: %r", statement)
            continue

        seen_statements.append(statement)
        valid_claims.append(Claim(
            statement=statement, evidence_number=num, url=url,
            confidence=c.get("confidence", "stated"),
        ))

    # FIX 5.4: synthesis verdict for comparative questions
    verdict = synthesize_verdict(plan, valid_claims, trace)
    answer_text = " ".join(f"{c.statement} [{c.evidence_number}]" for c in valid_claims)
    if verdict:
        answer_text = f"{verdict} " + answer_text
    if not answer_text:
        answer_text = "I could not confirm any claims from the available evidence."

    return CandidateAnswer(
        question=plan.original_question,
        claims=valid_claims,
        unresolved=result.parsed.get("unresolved", ""),
        answer_text=answer_text,
    )
"""
report.py — prints the full, transparent per-question trace: plan,
memory/search/fetch/routing trace, the Analyst's candidate answer
with citations listed SEPARATELY, then the Auditor's per-citation
verdict (supported/unsupported/contradicted, however many there
are), then the final validated answer and cost.

FIX 5.2: corroboration line added per citation in the Auditor section.
"""
from __future__ import annotations
from graph import PipelineResult


def print_full_report(result: PipelineResult) -> None:
    print("=" * 78)
    print(f"QUESTION: {result.question}")
    print("=" * 78)

    plan = result.plan
    print("\n[PLAN]")
    print(f"  Route: {plan.route}")
    print(f"  Entities detected: {plan.entities or '(none)'}")
    print(f"  Sub-questions ({len(plan.sub_questions)}):")
    for i, sq in enumerate(plan.sub_questions, 1):
        print(f"    {i}. {sq}")
    if plan.reasoning:
        print(f"  Planner reasoning: {plan.reasoning}")

    print("\n[MEMORY / ROUTING / SEARCH / FETCH TRACE]")
    for event in result.trace.events:
        detail = ", ".join(f"{k}={v}" for k, v in event.detail.items())
        print(f"  - {event.node}.{event.event_type}: {detail}")

    if result.retry_count > 0:
        print(f"\n[GAP ANALYZER] Auditor flagged issues -> retried research {result.retry_count} time(s)")

    print("\n[ANALYST CANDIDATE ANSWER]")
    if not result.candidate_answer.claims:
        print("  (no claims generated)")
    for i, c in enumerate(result.candidate_answer.claims, 1):
        print(f"  Claim {i}: {c.statement}")
    if result.candidate_answer.unresolved:
        print(f"  Unresolved (analyst): {result.candidate_answer.unresolved}")

    print("\n[CITATIONS] (one per claim above)")
    if not result.candidate_answer.claims:
        print("  (none)")
    for i, c in enumerate(result.candidate_answer.claims, 1):
        print(f"  [{i}] {c.url}")

    print("\n[AUDITOR VERDICT] (per citation)")
    if not result.audit_report.audited_claims:
        print("  (no claims to audit)")
    for i, ac in enumerate(result.audit_report.audited_claims, 1):
        print(f"  [{i}] {ac.verdict.upper()} — {ac.statement}")
        print(f"      source: {ac.url or '(no citation given)'}")
        print(f"      reason: {ac.reason}")
        # FIX 5.2: cross-check corroboration line
        print(f"      source tier: {ac.source_tier} (score={ac.source_score})")
        print(f"      cross-check: {'CORROBORATED - ' + ac.corroboration_note if ac.corroborated else 'SINGLE-SOURCE - ' + ac.corroboration_note}")
    r = result.audit_report
    print(f"\n  Summary: {r.supported_count} supported, {r.unsupported_count} unsupported, "
          f"{r.contradicted_count} contradicted -> {'PASSED' if r.passed else 'FAILED'}")
    print(f"  Confidence score: {r.confidence_score} / 1.00")
    print("\n[FINAL VALIDATED ANSWER] (post Output Guard)")
    print(f"  {result.validated_answer.answer_text}")
    if result.validated_answer.unresolved:
        print(f"  Unresolved: {result.validated_answer.unresolved}")

    t = result.trace
    print("\n[COST / TRACE]")
    print(f"  Tokens: {t.total_tokens} (prompt={t.total_prompt_tokens}, completion={t.total_completion_tokens})")
    print(f"  Estimated cost: Rs.{t.estimated_cost_rupees:.4f} (local model -> real cost Rs.0)")
    print(f"  Wall clock: {t.wall_clock_seconds:.1f}s")
    print("=" * 78 + "\n")
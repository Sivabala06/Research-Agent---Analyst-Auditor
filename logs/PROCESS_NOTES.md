# Process Notes — What Was Done, What Wasn't, and Why

This document is deliberately honest rather than flattering. Its purpose is to
tell the evaluator exactly what was attempted, what was skipped on purpose,
and what is known to be broken — rather than let a clean README and a
polished demo run imply more than was actually achieved.

---

## 1. Hardware / environment conditions that shaped every decision

- **Machine**: an ELCOT (Tamil Nadu government) laptop, **8GB RAM**, CPU-only
  (no dedicated GPU). Every architectural choice — model size, truncation
  limits, batching, timeouts — was made against this constraint first.
- **Local LLM**: `qwen3:4b` via Ollama. On this hardware, a single LLM call
  routinely takes 8–60 seconds; a full research question (planner +
  claims + several auditor calls, sometimes doubled by a retry) can take
  anywhere from ~40 seconds to over 8 minutes.
- **Network**: an institutional/shared connection. One real diagnostic was
  needed mid-project when a live fetch test returned HTTP 403 from
  Wikipedia — this was confirmed, via a side-by-side test against
  `example.com` and a news site, to be Wikipedia's own bot-defense system,
  **not** an ELCOT network block or proxy issue. Documented here because it
  looked at first like an infrastructure problem and wasn't.
- **Consequence of the above**: aggressive RAM/token safety limits exist
  throughout the codebase (page-size caps, word-count truncation, a
  `MIN_USEFUL_WORDS` gate to reject paywall stubs) — these are load-bearing
  for running at all on this machine, not arbitrary choices.

---

## 2. Core requirements from the problem statement — status

**Part A (Analyst) — all core requirements were built and verified working
in real end-to-end runs, not just unit tests:**

- Plans before searching — yes (`planner.py`, route classification + entity
  extraction, rule-based to avoid an LLM call on the common case)
- Real web search + page fetching — yes (`ddgs` + `httpx`/`trafilatura`)
- Runs work in parallel where it makes sense — yes (evidence fetching uses a
  `ThreadPoolExecutor`); **honest caveat**: the Auditor's per-claim
  verification calls are still sequential, since parallelizing calls to one
  local Ollama process on one CPU would not have produced a real wall-clock
  win here — the bottleneck is compute, not I/O, at that stage.
- Cross-checks claims appearing in only one source — yes, but added late in
  the build (a heuristic token/number-overlap check against other retrieved
  sources, not a second LLM call, to keep this free)
- Carries learning across questions (memory) — yes, SQLite + `fastembed`
  semantic similarity gating. This went through a real, serious bug (see
  §4) before it worked correctly.
- Every answer carries citations — yes, and citations are structurally
  prevented from being hallucinated (the LLM cites evidence by number; the
  code maps numbers to real fetched URLs, never trusting the model to
  reproduce a URL string)
- States plainly when it can't find something — yes, and this was the
  single most reliably correct behavior observed across all test runs
- 8+ questions of increasing difficulty, 2+ reusing earlier entities — yes;
  ran 8, then 9, then 10-question sets across multiple domains
  (business, tourism, biomedical, technology, sports, energy, agriculture,
  archaeology) specifically to stress different code paths, not just
  re-run the same shape of question

**Part B (Auditor) — all core requirements were built and verified:**

- Re-opens the cited source independently (never reuses the Analyst's
  already-fetched text — a deliberate design choice so an Analyst bug and
  an Auditor bug can't silently cancel out)
- Marks every claim supported / unsupported / contradicted — yes, no
  default-pass path exists in the code
- Flags claims with no citation at all — yes, auto-unsupported, no LLM
  call spent on it
- Run across the Analyst's own answers, with what it caught reported — yes;
  the Auditor genuinely caught real problems in testing, including once
  converting a plausible-but-wrong circular answer into an honest refusal,
  and once catching a claim that was internally self-contradictory
  ("worked at [a division of ISRO] before joining ISRO")

**What we were asked to show (full traces, cost, honesty about the
Auditor's limits)** — all delivered; see the transparent per-question trace
output (`report.py`) and `sample_runs/` for real transcripts.

---

## 3. "Take it further" stretch goals — explicitly, none were fully achieved

All three stretch goals in the problem statement are stated as optional
("none of them are required. Solve one properly rather than four loosely").
Being direct about where each one actually stands:

1. **Cost falls by half, accuracy holds** — **not achieved.** Token cost per
   question varied widely (roughly 800 to 10,000+ tokens) with no clean
   downward trend across question sets. The memory fix that was built (§4)
   deliberately traded aggressive cache reuse for correctness once a serious
   bug was found — meaning the system now correctly refuses to reuse memory
   for same-entity-different-intent questions, which is the right call for
   correctness but means no reliable cost-halving is demonstrated in the
   logs.
2. **Handle sources that disagree** — **partially touched, not properly
   solved.** Two real runs produced genuine disagreement-handling examples
   (a population-figure question where the Analyst correctly explained *why*
   different sources reported different numbers; a solar-capacity ranking
   question with partially conflicting figures). A general "resolve and
   justify" synthesis step was added for comparative questions, but this was
   not deliberately tested against a constructed, known-conflicting source
   pair — the good examples we have were found in general testing, not
   built and proven against on purpose.
3. **Hard two-minute wall-clock ceiling** — **not met, and not enforced in
   code.** Regularly exceeded, up to ~5 minutes observed on `multi_source`
   questions with an audit-retry. 



---

## 4. Scope decisions made on purpose (not oversights)

- **Only one search provider (DuckDuckGo) is actually implemented**, even
  though the architecture's `SearchTool` is a proper abstract interface
  built to support swapping providers. A second engine was never added —
  the interface exists, the diversity doesn't.
- **No cross-session conversational memory** ("what about the CFO?" as a
  follow-up to a prior turn) was built. The problem statement's memory
  requirement is about reuse across independent research questions, which
  is what was built — conversational context is a different feature, judged
  out of scope.
- **No live-streaming UI.** The interactive CLI (`main.py`) prints a
  "working" message, then the full trace all at once when the pipeline
  finishes — not incrementally during the run. A genuinely live streaming
  view was scoped out early as high-effort relative to what the assignment
  actually asks for (full traces are still delivered, just not
  token-by-token live).
- **Source credibility scoring is a static domain allowlist**, not a
  learned or dynamic reputation model — a deliberately cheap, zero-cost
  heuristic rather than a more accurate but heavier system.

---

## 6. What would be done next with more time

In priority order, based on what testing actually surfaced as most
consequential:
1. Fix the near-duplicate over-filtering bug (§4) — this is the one bug
   that actively destroys correct answers rather than just producing an
   honest refusal, so it would be first.
2. Build a genuinely targeted Gap Analyzer — re-search based on *which*
   specific claim the Auditor flagged and *why*, instead of blindly
   re-running the same query.
3. Attempt the adversarial-Analyst stretch goal properly, since it wasn't
   attempted at all and is the cheapest of the five stretch goals to test.
4. Add a second search provider for real redundancy, using the abstraction
   that already exists but currently has only one implementation behind it.

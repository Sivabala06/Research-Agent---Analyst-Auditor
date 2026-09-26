# Research Agent — Analyst & Auditor (Zero-Cost, Local-First)

A two-agent research system built for the "Analyst and Auditor" problem statement:
an **Analyst** that answers open research questions using live web search with
citations, and an independent **Auditor** that re-verifies every claim by
re-fetching its cited source.

**Runs entirely locally, at zero API cost, on an 8GB RAM laptop.** No paid
services, no API keys, no cloud LLM calls.

---

## Architecture

```
USER -> INPUT GUARD -> PLANNER -> MEMORY LOOKUP
  -> [cache hit?]  -> use cached evidence -----+
  -> [multi_hop?]  -> multi_hop.py (2-hop)  ---+--> CLAIMS -> AUDITOR
  -> [else]        -> ROUTER -> EVIDENCE -------+         |
                                                      [PASS] or [FAIL]
                                                           |         \
                                                      OUTPUT GUARD   GAP ANALYZER
                                                           |          -> retry once (back to ROUTER)
                                                      VALIDATED ANSWER
                                                           |
                                                      MEMORY SAVE -> USER
```

Orchestrated with **LangGraph** (`StateGraph`) — chosen for genuine conditional
branching (memory cache hits, audit pass/fail retry), not a plain function chain.

### Pipeline stages
1. **Input Guard** — rejects empty/malformed/injection-pattern input before any cost is spent.
2. **Planner** — classifies the question's route (`direct` / `multi_source` / `multi_hop`) and extracts entities, using rule-based keyword matching (zero LLM cost for the common `direct` case).
3. **Memory Lookup** — SQLite + `fastembed` semantic similarity gating. Only reuses a cached fact if the entity matches **and** the new question is semantically similar (≥0.80) to the question that originally produced it — this prevents a serious bug found during testing (see Known Limitations) where same-entity, different-intent questions (e.g. "who is the CEO" vs "who is the CFO") wrongly reused each other's cached answers.
4. **Router / Evidence** — runs DuckDuckGo search (`ddgs`, no API key) in parallel per sub-question, fetches and extracts each page (`httpx` + `trafilatura`), and scores each source's credibility tier and publish-date freshness.
5. **Multi-hop** — for two-part chained questions ("who is X, and where did they work before"), runs a genuine two-step lookup: hop 2's search query is built from hop 1's actual extracted answer, not fired in parallel with it.
6. **Claims** — the Analyst's LLM call, constrained to cite evidence by number (never a freeform URL string, so citations can never be hallucinated). Filters out claims that just echo the question back, and collapses near-duplicate claims. For comparative questions ("which grew faster"), makes one extra cheap call to synthesize a direct verdict instead of leaving a list of facts unresolved.
7. **Auditor (Part B)** — independently **re-fetches** each cited source (never reuses the Analyst's already-gathered text) and marks each claim `supported` / `unsupported` / `contradicted`. Also cross-checks each claim against every *other* retrieved source for corroboration, and flags claims that only appear in one source.
8. **Gap Analyzer** — on audit failure, retries the research once (capped, no infinite loop).
9. **Output Guard** — drops any claim not marked `supported`, regardless of what the Analyst wrote; flags answers that rely only on lower-tier sources.
10. **Memory Save** — only audit-`supported` claims are persisted, tagged with the question that produced them (for the semantic gate above).

Every stage above is logged in full via `tracer.py` — see "Transparency & Tracing" below.

---

## Tech stack

| Component | Choice | Why |
|---|---|---|
| Orchestration | **LangGraph** | Conditional branching for cache hits and audit retry |
| LLM | **Ollama**, local model `qwen3:4b` | Zero cost, fully local, runs on 8GB RAM |
| Structured output | **Pydantic**, passed as `format=` to Ollama | Constrains the model to valid JSON at generation time |
| Search | **`ddgs`** (DuckDuckGo) | No API key required |
| Fetch / parse | **`httpx`** + **`trafilatura`** | Real page download + boilerplate-free text extraction |
| Memory | **SQLite** + **`fastembed`** (`BAAI/bge-small-en-v1.5`) | Local vector similarity, zero cost |
| Tracing | Custom `tracer.py`, JSONL logs | Full operational tracing (required) |

---

## Setup

1. **Install [Ollama](https://ollama.com)** and pull the model this project uses:
   ```
   ollama pull qwen3:4b
   ```
2. **Install Python dependencies:**
   ```
   pip install -r requirements.txt
   ```
3. **Start Ollama** (leave running in its own terminal):
   ```
   ollama serve
   ```

---

## Running

**Interactive mode** — ask questions one at a time, full trace printed after each:
```
python main.py
```

**Batch mode** — runs a fixed set of research questions end-to-end and prints a cost/time summary:
```
python run_questions.py
```

**Run the test suite:**
```
python -m pytest tests/ -v
```

Delete `research_memory.db` before a fresh evaluation run — it's regenerable
cache, not source of truth, and will otherwise carry over facts from prior
development runs.

---

## Transparency & tracing

Every question prints, in full:
- The Planner's chosen route and reasoning
- Every memory-cache decision, search call, and fetch (including failures — a `403`, a paywall stub, or a "no results found" from the search provider are all expected, routine events on the live web, not silent failures)
- Every claim the Analyst made, with its citation listed separately
- The Auditor's verdict on **every single citation** (supported / unsupported / contradicted), its source-credibility tier, and whether it was corroborated by another retrieved source
- The final validated answer (post Output Guard) and real cost: token count and wall-clock time (real cost is always ₹0 — 100% local inference)

Nothing about the pipeline's internal reasoning is hidden; only the LLM's raw
chain-of-thought (if any) is not exposed, per the project's design constraints.

---

## Known limitations (found through real testing, not fixed — documented deliberately)



1. **Near-duplicate claim filtering can over-delete distinct facts.** The
   duplicate-detection heuristic (`SequenceMatcher` on claim text) was found,
   during testing, to sometimes flag genuinely different facts as duplicates
   when they share a repeated sentence template (e.g. "Country A installed
   the 2nd most..." vs. "Country B installed the 3rd most..." scored as
   near-identical purely from shared boilerplate wording, dropping two of
   three correct rankings in one real run). A partial fix (also requiring
   overlap in the claim's actual names/numbers, not just sentence shape) was
   identified but not applied before this submission.
2. **Confidence score can reward corroboration on an incorrect claim.** The
   `confidence_score` heuristic currently adds a corroboration bonus
   regardless of the claim's verdict — so two sources agreeing on a
   contradicted/wrong fact can still show a non-zero confidence score. Should
   only credit corroboration on `supported` claims.
3. **Multi-hop can silently drop half of a two-part question.** When hop 2
   (e.g. "and where did they work before joining") fails to find an answer,
   the final answer only addresses hop 1, with no explicit note admitting the
   second half went unanswered — this looks like a complete answer to a
   two-part question when it isn't.
4. **Source credibility scoring is a domain allowlist, not a real
   trust model.** An unlisted domain is "unclassified" (tier 3), not
   verified-bad; a listed domain isn't guaranteed accurate either.
5. **Live/time-sensitive numeric data (e.g. stock prices) can be stale**,
   since `trafilatura`-based fetching cannot execute JavaScript and reads
   whatever was baked into the static HTML at scrape time.
6. **The 2-minute wall-clock target (an explicitly optional stretch goal) is
   regularly exceeded** on `multi_source` questions that trigger the audit
   retry loop — observed up to ~8 minutes on this 8GB CPU-only laptop, since
   a small local model runs sequentially, not from lack of parallelism in
   the code (evidence fetching is already threaded).
7. **Occasional local-model output corruption** (e.g. a garbled token
   mid-sentence) has been observed on this quantized local model; the
   duplicate/echo filters reduce but do not eliminate its impact.

These were deliberately left as documented limitations rather than iterated on
indefinitely, to avoid an unbounded fix-test-fix cycle against a small local
model's variable output — a real, considered trade-off, not an oversight.

---

## Project structure

```
research_agent/
├── main.py              # interactive CLI
├── run_questions.py     # batch runner + cost summary
├── graph.py              # LangGraph pipeline wiring
├── planner.py            # route classification, entity extraction
├── router.py              # search dispatch
├── multi_hop.py           # two-hop chained lookup
├── evidence.py            # parallel fetch orchestration
├── fetch_tool.py          # page download + text extraction
├── search_tool.py         # DuckDuckGo search wrapper
├── claims.py              # Analyst: candidate answer generation
├── auditor.py             # Auditor: independent verification
├── source_scoring.py      # domain credibility heuristic
├── text_utils.py          # shared snippet/token-matching helpers
├── memory.py              # SQLite + fastembed semantic cache
├── guards.py              # input/output guardrails
├── tracer.py              # cost & event tracing
├── report.py              # full transparent trace printer
├── llm_client.py          # Ollama wrapper
├── config.py              # all tunable constants
└── tests/                 # pytest suite (65+ tests)
```

## Cost

All inference is local (Ollama). **Real cost per question: ₹0.** Token counts
are tracked and reported per question purely as a compute-usage signal, not a
billing signal — see `sample_runs/` for real transcripts with per-question
token counts and wall-clock times.

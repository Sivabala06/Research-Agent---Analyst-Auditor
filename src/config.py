"""
config.py

Every tunable number/setting for the project lives HERE, in one
place. When the hardware, model, or a limit needs to change, we
change this file — not code scattered across the project.
"""

# --- Ollama connection ---
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "qwen3:4b"
OLLAMA_TIMEOUT_SECONDS = 180  # generous: our benchmark showed slow prefill can take minutes

# --- RAM-safety limits (from our benchmark: speed collapses past ~2000 input tokens) ---
MAX_INPUT_TOKENS = 1200        # hard ceiling on what we send to the model in one call
APPROX_TOKENS_PER_WORD = 1.35  # measured from our own benchmark data (not exact, just for budgeting)

# Hard ceiling on what the model is ALLOWED to generate per call.
# This is the real fix for runaway "thinking" (we measured 1509 tokens /
# 170s for a one-word answer without this cap) — deterministic, not
# dependent on the model choosing to cooperate.
MAX_OUTPUT_TOKENS = 500

# --- Search (DuckDuckGo via `ddgs`, zero-cost, no API key) ---
SEARCH_MAX_RESULTS = 5          # keep small — each result may get fetched + read by the LLM later
SEARCH_MAX_RETRIES = 3          # DuckDuckGo can rate-limit/block transiently — documented, not our bug
SEARCH_RETRY_DELAY_SECONDS = 2.0

# --- Fetch (page download + text extraction) ---
FETCH_TIMEOUT_SECONDS = 20.0
FETCH_MAX_HTML_BYTES = 3_000_000   # ~3MB raw HTML ceiling — protects RAM on our 8GB machine
FETCH_MAX_TEXT_WORDS = 3000        # outer sanity cap on extracted text (NOT the LLM's limit — see note below)
FETCH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0 Safari/537.36"
)

MIN_USEFUL_WORDS = 80


# --- Planner ---
PLANNER_MAX_OUTPUT_TOKENS = 400

# Words that suggest the question needs 2+ independent things researched then compared/ranked
MULTI_SOURCE_KEYWORDS = [
    "top", "most", "least", "compare", "every", "all companies",
    "list every", "how many", "which three", "which two", "ranking",
    "leading", "highest", "lowest", "biggest", "largest", "faster",
    "better", "more than", "rank", "vs", "versus",
]

# Words that suggest step 2 depends on the answer to step 1 (chained lookup).
# FIX 5.1: expanded list — previous version missed "where did they work before"
# and "before joining", causing all 18 real test questions of this type to be
# misclassified as route=direct. No duplicates retained.
MULTI_HOP_KEYWORDS = [
    "before that", "previously", "prior to", "former", "used to work",
    "where they worked before", "where did they work before", "then find",
    "after that", "before joining", "prior employer", "previous employer",
]

# --- Claims / Candidate Answer ---
CLAIMS_MAX_OUTPUT_TOKENS = 700
MAX_EVIDENCE_PIECES_IN_PROMPT = 8   # RAM/token guard — cap how much evidence we stuff into one prompt

# --- Synthesis (comparative verdict for multi_source questions) ---
# FIX 5.4: added — synthesis makes ONE extra cheap LLM call to state a direct
# verdict for "which grew faster / which is biggest" questions instead of
# leaving the user to infer an answer from a list of atomic facts.
SYNTHESIS_MAX_OUTPUT_TOKENS = 200
COMPARISON_WORDS = [
    "which", "compare", "faster", "better", "more", "most",
    "highest", "leading", "rank", "grew faster", "vs", "versus",
]

# --- Auditor ---
AUDITOR_MAX_OUTPUT_TOKENS = 200

# --- Tracing / Cost ---
RUPEES_PER_1K_TOKENS = 0.0  # local model = actual cost is zero. Set >0 only
                            # for a hypothetical "what would this cost on a
                            # paid API" comparison in the write-up.
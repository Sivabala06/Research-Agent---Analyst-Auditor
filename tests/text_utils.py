"""
text_utils.py — shared relevance-window logic for claims.py and auditor.py,
kept in one place so both don't silently diverge with two copies.
"""
from __future__ import annotations


def best_snippet(text: str, query: str, window_words: int = 140) -> str:
    """Returns the window_words-word window of text most relevant to query,
    instead of a flat text[:N] truncation that can cut a relevant fact off
    mid-sentence while keeping an irrelevant opening paragraph.

    HONEST LIMITATION: keyword-overlap scoring over a sliding window, not
    real semantic search. A cheap, zero-cost improvement over flat
    truncation, not a replacement for actual retrieval."""
    words = text.split()
    if len(words) <= window_words:
        return text

    query_words = {w.lower().strip(".,!?") for w in query.split() if len(w) > 3}
    if not query_words:
        return " ".join(words[:window_words])

    best_start, best_score = 0, -1
    step = max(1, window_words // 2)
    for i in range(0, len(words) - window_words + 1, step):
        chunk = words[i:i + window_words]
        score = sum(1 for w in chunk if w.lower().strip(".,!?") in query_words)
        if score > best_score:
            best_score, best_start = score, i
    return " ".join(words[best_start:best_start + window_words])
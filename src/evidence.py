"""
evidence.py

Takes RoutedSearchResults (URLs found per sub-question) and fetches
each one into usable evidence text. This is the FETCH -> PARSE ->
EVIDENCE tail of the architecture diagram's SEARCH -> FETCH -> PARSE
-> EVIDENCE chain.

Design boundary: this file does NOT decide what claims to make from
the evidence (that's the next node, Claims/Candidate Answer) — it
only turns "a URL that search found" into "clean text + provenance,
or a clearly logged failure."

COST/RELIABILITY NOTE: fetch_tool.py already raises FetchError for
HTTP errors, oversized pages, and now (per our MIN_USEFUL_WORDS gate)
paywall/JS-stub pages. Every one of those is expected, routine
behavior on the live web, not a bug — so failures here are collected
and reported, never raised up and never silently dropped.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from fetch_tool import Fetcher, FetchError, FetchedPage
from router import RoutedSearchResults
import concurrent.futures
logger = logging.getLogger("research_agent.evidence")


class EvidencePiece(BaseModel):
    """One successfully fetched, usable piece of evidence."""
    sub_question: str
    url: str
    title: str
    text: str
    word_count: int
    source_year: Optional[int] = None


class EvidenceBundle(BaseModel):
    """All evidence gathered for one research plan, plus what failed."""
    pieces: list[EvidencePiece] = Field(default_factory=list)
    failed_urls: list[str] = Field(default_factory=list)




def gather_evidence(routed: RoutedSearchResults, fetcher: Fetcher, max_workers: int = 5) -> EvidenceBundle:
    bundle = EvidenceBundle()

    def fetch_one(sub_q, result):
        try:
            return ("ok", sub_q, result, fetcher.fetch(result.url))
        except FetchError as exc:
            return ("fail", sub_q, result, str(exc))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(fetch_one, sq, r)
                   for sq, results in routed.results_by_subquestion.items() for r in results]
        for future in concurrent.futures.as_completed(futures):
            status, sub_q, result, payload = future.result()
            if status == "ok":
                bundle.pieces.append(EvidencePiece(sub_question=sub_q, url=result.url,
                    title=result.title, text=payload.text, word_count=payload.word_count,
                    source_year=payload.source_year))
            else:
                logger.info("Evidence fetch skipped for %s: %s", result.url, payload)
                bundle.failed_urls.append(result.url)
    return bundle
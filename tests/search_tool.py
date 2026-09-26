"""
search_tool.py

Abstract search interface + a DuckDuckGo-backed implementation.

Design principle: the rest of the agent (planner, router) only ever
imports SearchTool and SearchResult — never `ddgs` or `DDGS`
directly. If DuckDuckGo gets rate-limited or blocked, we swap the
concrete implementation here without touching any other file. This
is the "search provider must be abstracted" requirement made real,
not decorative.

RELIABILITY NOTE (stated honestly, not hidden): DuckDuckGo has no
official free API. `ddgs` works by querying DuckDuckGo's own search
page, which can rate-limit or block requests — this is documented,
known behavior, not a defect in our code. We handle it with a small
retry-with-backoff; the caller always gets a clear SearchError
rather than a silent empty result list.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel

from config import SEARCH_MAX_RESULTS, SEARCH_MAX_RETRIES, SEARCH_RETRY_DELAY_SECONDS

logger = logging.getLogger("research_agent.search_tool")


class SearchError(RuntimeError):
    """Raised when a search provider fails after all retries."""


class SearchResult(BaseModel):
    """One search hit — provider-agnostic shape."""
    title: str
    url: str
    snippet: str = ""


class SearchTool(ABC):
    """Abstract interface every search provider must implement."""

    @abstractmethod
    def search(self, query: str, max_results: int = SEARCH_MAX_RESULTS) -> list[SearchResult]:
        ...


class DuckDuckGoSearchTool(SearchTool):
    """SearchTool backed by the `ddgs` library (no API key, zero cost)."""

    def __init__(
        self,
        max_retries: int = SEARCH_MAX_RETRIES,
        retry_delay_seconds: float = SEARCH_RETRY_DELAY_SECONDS,
    ) -> None:
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds

    def search(self, query: str, max_results: int = SEARCH_MAX_RESULTS) -> list[SearchResult]:
        # Imported here (not at module top) so this file can be imported
        # and tested even in an environment where `ddgs` isn't installed.
        from ddgs import DDGS

        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with DDGS() as ddgs:
                    raw_results = list(ddgs.text(query, max_results=max_results))
                return [self._to_search_result(r) for r in raw_results]
            except Exception as exc:  # ddgs can raise several different exception types
                last_error = exc
                logger.warning(
                    "Search attempt %d/%d failed for query %r: %s",
                    attempt, self.max_retries, query, exc,
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_seconds)

        raise SearchError(
            f"Search failed for query {query!r} after {self.max_retries} attempts: {last_error}"
        ) from last_error

    @staticmethod
    def _to_search_result(raw: dict) -> SearchResult:
        # .get() everywhere: ddgs's return fields are documented to vary
        # slightly between versions — never crash on a missing key.
        return SearchResult(
            title=raw.get("title", "") or "",
            url=raw.get("href", "") or raw.get("url", "") or "",
            snippet=raw.get("body", "") or "",
        )
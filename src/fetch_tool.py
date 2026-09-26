"""
fetch_tool.py

Turns a URL into clean, readable text — the FETCH + PARSE steps in
the architecture diagram (SEARCH -> FETCH -> PARSE -> EVIDENCE).

Design boundary: this file's job ends at "clean text ready to read."
It does NOT decide which part of a long page is most relevant to a
claim, and it does NOT enforce the LLM's token budget — that's
llm_client.py's job.

FORWARD-LOOKING FIX (built in now, not after it breaks something):
trafilatura's own extraction timeout uses Python's `signal` module,
which only works on the MAIN thread. Since parallel fetching is a
real requirement later (two-minute wall-clock stretch goal runs
fetches on worker threads), we disable trafilatura's internal
timeout via its config — our own httpx timeout already covers this,
so trafilatura's would only ever be redundant anyway.

LIMITATION (stated honestly): we return the extracted text as-is,
truncated by a flat word count, not the most relevant excerpt of it.
A 3000-word article and a 300-word article on the same claim are
treated the same today. Smarter chunking (e.g. via fastembed,
selecting the passage most relevant to the actual claim being
checked) is a planned next step, not built yet.
"""

from __future__ import annotations

import logging
from typing import Optional
from config import MIN_USEFUL_WORDS
import httpx
import trafilatura
from trafilatura.settings import use_config
from pydantic import BaseModel

from config import (
    FETCH_TIMEOUT_SECONDS,
    FETCH_MAX_HTML_BYTES,
    FETCH_MAX_TEXT_WORDS,
    FETCH_USER_AGENT,
)

logger = logging.getLogger("research_agent.fetch_tool")

# Disable trafilatura's internal signal-based timeout once, at import
# time — see module docstring for why this matters for future
# parallel fetching.
_TRAFILATURA_CONFIG = use_config()
_TRAFILATURA_CONFIG.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")


class FetchError(RuntimeError):
    """Raised when a URL can't be downloaded or no readable text can be extracted."""


class FetchedPage(BaseModel):
    """Clean result of fetching one URL — what the rest of the agent works with."""

    url: str
    text: str
    word_count: int
    truncated: bool                        # True if text was cut for RAM safety
    original_word_count: Optional[int] = None
    source_year: Optional[int] = None


class Fetcher:
    """Downloads a URL and extracts its main readable text (no boilerplate)."""

    def __init__(
        self,
        timeout_seconds: float = FETCH_TIMEOUT_SECONDS,
        max_html_bytes: int = FETCH_MAX_HTML_BYTES,
        max_text_words: int = FETCH_MAX_TEXT_WORDS,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_html_bytes = max_html_bytes
        self.max_text_words = max_text_words

    def fetch(self, url: str) -> FetchedPage:
        html = self._download(url)
        text = self._extract(html, url)
        source_year = self._extract_year(html)
        return self._to_fetched_page(url, text, source_year)

    def _download(self, url: str) -> str:
        headers = {"User-Agent": FETCH_USER_AGENT}
        try:
            response = httpx.get(
                url, headers=headers, timeout=self.timeout_seconds, follow_redirects=True,
            )
        except httpx.RequestError as exc:
            raise FetchError(f"Could not reach {url}: {exc}") from exc

        if response.status_code != 200:
            raise FetchError(f"{url} returned HTTP {response.status_code}")

        if len(response.content) > self.max_html_bytes:
            raise FetchError(
                f"{url} page is {len(response.content)} bytes, over our "
                f"{self.max_html_bytes}-byte safety limit — skipping to protect RAM."
            )

        return response.text



    def _extract(self, html: str, url: str) -> str:
        text = trafilatura.extract(
            html, url=url, config=_TRAFILATURA_CONFIG,
            include_comments=False, include_tables=True,
        )
        if not text or not text.strip():
            raise FetchError(f"Could not extract readable text from {url}")

        text = text.strip()
        word_count = len(text.split())
        if word_count < MIN_USEFUL_WORDS:
            raise FetchError(
                f"{url} only yielded {word_count} words after extraction — "
                f"likely a paywall, login wall, or JS-rendered page, not real content."
            )
        return text
    def _extract_year(self, html: str) -> Optional[int]:
        """Uses trafilatura's own metadata extraction (backed by htmldate)
        to find the page's ACTUAL published/modified date -- not a
        body-text regex, which would false-match numbers in financial
        data, addresses, etc. Returns None rather than guessing when no
        reliable date metadata exists."""
        try:
            metadata = trafilatura.extract_metadata(html)
            if metadata and metadata.date:
                return int(metadata.date[:4])
        except Exception:
            pass
        return None

    def _to_fetched_page(self, url: str, text: str, source_year: Optional[int] = None) -> FetchedPage:
        words = text.split()
        if len(words) <= self.max_text_words:
            return FetchedPage(url=url, text=text, word_count=len(words), truncated=False, source_year=source_year)
        original_count = len(words)
        truncated_text = " ".join(words[: self.max_text_words])
        logger.warning("Page text truncated for RAM safety: %d words -> %d words (%s)",
                        original_count, self.max_text_words, url)
        return FetchedPage(url=url, text=truncated_text, word_count=self.max_text_words,
                            truncated=True, original_word_count=original_count, source_year=source_year)
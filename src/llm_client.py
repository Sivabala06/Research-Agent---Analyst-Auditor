"""
llm_client.py

The ONLY place in this project that talks to Ollama.

Every other component (planner, claim extractor, auditor) must call
the model through OllamaClient.call(...) — never directly. This is
what makes the "strict rules" from our benchmark actually stick:

  1. Always through Ollama's HTTP API (never `ollama run`).
  2. Every structured (JSON) call uses Ollama's `format` schema
     parameter — unconstrained JSON was unreliable on our hardware.
  3. Prompts are hard-capped at MAX_INPUT_TOKENS (input) AND
     MAX_OUTPUT_TOKENS (output) — see the two corrections below.
  4. Only one call runs at a time — no RAM headroom for a second
     model context.

CORRECTION 1: Ollama's `think: false` field does not reliably
suppress Qwen3's reasoning trace (known open bug: ollama/ollama#10809,
#14645; ollama-python#529, #576).

CORRECTION 2 (found by testing, reverses our first fix): appending
Qwen3's documented "/no_think" soft-switch to the prompt does NOT
help through Ollama's chat API — the model treated the literal text
"/no_think" as an ambiguous instruction to reason ABOUT, which made
things worse (1509 tokens / 170s for a one-sentence answer, vs 288
tokens / 30s without it). We tried the documented fix, measured it,
and it made cost 5x worse — so we removed it.

CORRECTION 3: our own <think> stripping was broken. Ollama's chat
template inserts the OPENING <think> tag as part of the prompt it
sends to the model — it never appears in the returned text, only the
model's own closing </think> does. Stripping logic below now keys
off </think> alone, not a matching open/close pair.

REAL FIX: none of the above reliably controls the model's behavior,
so the guardrail that actually matters is a hard, deterministic cap
on generated tokens (`num_predict`). Worst-case cost/latency is now
bounded by US, not by whether the model chooses to ramble.

KNOWN LIMITATION (stated honestly, not hidden): if num_predict cuts
generation off WHILE the model is still inside an unclosed thinking
block, no </think> tag will ever appear, and we cannot distinguish
"genuinely short answer" from "truncated mid-thought" by text alone.
We accept this risk for now and keep MAX_OUTPUT_TOKENS generous
enough that it's rare; revisit if it shows up in real runs.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from config import (
    OLLAMA_HOST,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SECONDS,
    MAX_INPUT_TOKENS,
    MAX_OUTPUT_TOKENS,
    APPROX_TOKENS_PER_WORD,
)

logger = logging.getLogger("research_agent.llm_client")

T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class OllamaConnectionError(RuntimeError):
    """Raised when Ollama isn't reachable (e.g. it isn't running)."""


class OllamaCallError(RuntimeError):
    """Raised when Ollama responds but with an error or unexpected shape."""


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

class LLMResult(BaseModel):
    """A clean, typed record of one model call — enough to trace and cost it."""

    text: str                      # the USABLE answer, with any thinking already removed
    parsed: Optional[dict] = None  # JSON dict, only set if a schema was requested AND validated
    model: str
    prompt_tokens: int              # Ollama's own real count
    completion_tokens: int          # includes any thinking tokens burned, even though text strips them
    latency_seconds: float
    truncated: bool                 # True if INPUT was cut to fit MAX_INPUT_TOKENS
    truncated_from_words: Optional[int] = None
    had_thinking: bool = False      # True if a thinking block was detected and stripped
    hit_output_cap: bool = False    # True if generation stopped because it hit MAX_OUTPUT_TOKENS


# ---------------------------------------------------------------------------
# Token estimation & input truncation
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Rough pre-call estimate — good enough to decide whether to truncate."""
    word_count = len(text.split())
    return int(word_count * APPROX_TOKENS_PER_WORD)


def truncate_to_token_limit(
    text: str, max_tokens: int = MAX_INPUT_TOKENS
) -> tuple[str, bool, Optional[int]]:
    """Cut `text` down so it fits under max_tokens (approximately)."""
    words = text.split()
    estimated = estimate_tokens(text)
    if estimated <= max_tokens:
        return text, False, None

    max_words = int(max_tokens / APPROX_TOKENS_PER_WORD)
    truncated_words = words[:max_words]
    truncated_text = " ".join(truncated_words)
    logger.warning(
        "Prompt truncated: %d words (~%d tokens) -> %d words (~%d tokens) "
        "to respect MAX_INPUT_TOKENS=%d",
        len(words), estimated, len(truncated_words), max_tokens, max_tokens,
    )
    return truncated_text, True, len(words)


# ---------------------------------------------------------------------------
# Thinking-block stripping — see CORRECTION 3 above
# ---------------------------------------------------------------------------

def _strip_thinking(raw_text: str) -> tuple[str, bool]:
    """
    Remove a leaked thinking block from model output.

    Keys off the CLOSING </think> tag only — the opening tag is
    injected by Ollama's prompt template and never appears in what
    the model returns to us. Everything up to and including the last
    </think> is discarded; what remains is the usable answer.
    """
    lower = raw_text.lower()
    if "</think>" in lower:
        idx = lower.rfind("</think>")
        cleaned = raw_text[idx + len("</think>"):].strip()
        return cleaned, True

    if "<think>" in lower:
        # Opened but never closed (e.g. cut off by MAX_OUTPUT_TOKENS
        # mid-thought). Nothing usable remains — see KNOWN LIMITATION.
        logger.warning("Model's <think> block was opened but never closed; discarding it.")
        return "", True

    return raw_text.strip(), False


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------

class OllamaClient:
    """
    Thin, safe wrapper around Ollama's HTTP /api/chat endpoint.

    Usage:
        client = OllamaClient()
        result = client.call("What is the capital of Tamil Nadu?")
        print(result.text)

        class Answer(BaseModel):
            city: str
        result = client.call("Capital of Tamil Nadu?", schema=Answer)
        print(result.parsed)   # {'city': 'Chennai'}
    """

    def __init__(
        self,
        host: str = OLLAMA_HOST,
        model: str = OLLAMA_MODEL,
        timeout_seconds: float = OLLAMA_TIMEOUT_SECONDS,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()  # enforces "only one LLM call at a time"

    def call(
        self,
        prompt: str,
        schema: Optional[Type[T]] = None,
        system: Optional[str] = None,
        max_output_tokens: int = MAX_OUTPUT_TOKENS,
    ) -> LLMResult:
        safe_prompt, was_truncated, original_words = truncate_to_token_limit(prompt)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": safe_prompt})

        body: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,  # kept — harmless when it works, ignored when it doesn't
            "options": {"num_predict": max_output_tokens},  # the real, deterministic cost cap
        }
        if schema is not None:
            body["format"] = schema.model_json_schema()

        with self._lock:
            start = time.perf_counter()
            try:
                response = httpx.post(
                    f"{self.host}/api/chat",
                    json=body,
                    timeout=self.timeout_seconds,
                )
            except httpx.ConnectError as exc:
                raise OllamaConnectionError(
                    f"Could not reach Ollama at {self.host}. Is `ollama serve` running?"
                ) from exc
            except httpx.TimeoutException as exc:
                raise OllamaCallError(
                    f"Ollama call timed out after {self.timeout_seconds}s."
                ) from exc
            latency = time.perf_counter() - start

        if response.status_code != 200:
            raise OllamaCallError(
                f"Ollama returned HTTP {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        try:
            raw_text = data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise OllamaCallError(f"Unexpected Ollama response shape: {data}") from exc

        text, had_thinking = _strip_thinking(raw_text)
        if had_thinking:
            logger.info("Thinking block detected and stripped from model output.")

        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)
        hit_output_cap = completion_tokens >= max_output_tokens

        parsed: Optional[dict] = None
        if schema is not None:
            try:
                raw = json.loads(text)
                validated = schema(**raw)
                parsed = validated.model_dump()
            except (json.JSONDecodeError, ValidationError, TypeError) as exc:
                logger.warning(
                    "Structured output did not match schema %s: %s", schema.__name__, exc
                )
                parsed = None

        return LLMResult(
            text=text,
            parsed=parsed,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_seconds=latency,
            truncated=was_truncated,
            truncated_from_words=original_words,
            had_thinking=had_thinking,
            hit_output_cap=hit_output_cap,
        )
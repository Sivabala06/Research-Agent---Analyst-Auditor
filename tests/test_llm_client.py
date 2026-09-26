"""
tests/test_llm_client.py

Two kinds of tests:

1. Pure logic tests (no Ollama needed) — token estimation and
   truncation. These always run and should always pass.
2. Real integration tests that call your local Ollama server. If
   Ollama isn't running, they SKIP (don't fail), so you can still
   run the fast tests without starting Ollama.
"""

import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm_client import OllamaClient, OllamaConnectionError, estimate_tokens, truncate_to_token_limit, _strip_thinking

from config import MAX_INPUT_TOKENS


# --- Pure logic tests — no Ollama required ---

def test_estimate_tokens_reasonable():
    text = "word " * 100  # 100 words
    tokens = estimate_tokens(text)
    assert 90 <= tokens <= 160


def test_truncate_under_limit_is_unchanged():
    short_text = "This is a short prompt."
    result, was_truncated, original_words = truncate_to_token_limit(short_text)
    assert result == short_text
    assert was_truncated is False
    assert original_words is None


def test_truncate_over_limit_cuts_and_flags():
    long_text = " ".join(["word"] * 5000)
    result, was_truncated, original_words = truncate_to_token_limit(long_text)
    assert was_truncated is True
    assert original_words == 5000
    assert estimate_tokens(result) <= MAX_INPUT_TOKENS
    assert len(result) < len(long_text)


# --- Real integration tests — need `ollama serve` running with qwen3:4b pulled ---

@pytest.fixture(scope="module")
def client():
    c = OllamaClient()
    try:
        c.call("Say OK.")  # cheap connectivity probe
    except OllamaConnectionError:
        pytest.skip("Ollama is not running (start it with `ollama serve`).")
    return c


def test_plain_call_returns_text_and_token_counts(client):
    result = client.call("In one word, what is the capital of France?")
    assert isinstance(result.text, str)
    assert len(result.text) > 0
    assert result.prompt_tokens > 0
    assert result.completion_tokens > 0
    assert result.latency_seconds > 0
    assert result.model == "qwen3:4b"


def test_structured_call_returns_parsed_dict(client):
    class CityAnswer(BaseModel):
        city: str

    result = client.call(
        "What is the capital of France? Answer with just the city name.",
        schema=CityAnswer,
    )
    assert result.parsed is not None
    assert "city" in result.parsed
    assert isinstance(result.parsed["city"], str)
    assert len(result.parsed["city"]) > 0

# add to the existing import line, or as a separate import


def test_strip_thinking_handles_close_tag_only():
    # Reflects the REAL pattern we observed: Ollama's template consumes
    # the opening <think> tag; only the model's own closing tag comes back.
    raw = "some reasoning text here</think>\n\nHello!"
    text, had_thinking = _strip_thinking(raw)
    assert text == "Hello!"
    assert had_thinking is True


def test_strip_thinking_leaves_normal_text_alone():
    raw = "Just a normal answer."
    text, had_thinking = _strip_thinking(raw)
    assert text == raw
    assert had_thinking is False


def test_output_is_capped_by_max_output_tokens(client):
    # Deliberately tiny cap — proves the guardrail actually bounds cost,
    # regardless of how much the model wants to ramble.
    result = client.call("Explain quantum computing in detail.", max_output_tokens=20)
    assert result.completion_tokens <= 25  # small buffer for stop-token overhead
    assert result.hit_output_cap is True
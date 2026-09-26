"""
planner.py

The first LangGraph node. Turns a raw user question into a
ResearchPlan: what entities it's about, how hard it is (route),
and what concrete search queries to run.

Design boundary: this file decides WHAT to search for, never
searches itself (that's search_tool.py) and never fetches pages
(that's fetch_tool.py).

COST DECISION (stated explicitly, not hidden):
- Entity extraction and route classification are pure rule-based
  regex/keyword logic. Zero LLM calls, zero tokens, fully
  deterministic and unit-testable without mocking anything.
- Sub-question decomposition uses the LLM ONLY for multi_source and
  multi_hop routes. For "direct" questions (the common, easy case),
  the original question IS the one sub-question -- no LLM call at
  all. This is the rule-based-first-with-LLM-fallback approach.

KNOWN LIMITATION (stated honestly): entity extraction is a
capitalized-phrase heuristic, not real NER (spaCy/similar would cost
RAM we don't have on 8GB). It will miss lowercase entities and
occasionally grab non-entities that happen to be capitalized (e.g.
sentence-starting words). Good enough to seed memory lookups; not
perfect. Revisit only if it causes measurable problems.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from config import (
    PLANNER_MAX_OUTPUT_TOKENS,
    MULTI_SOURCE_KEYWORDS,
    MULTI_HOP_KEYWORDS,
)

from llm_client import OllamaClient

logger = logging.getLogger("research_agent.planner")

Route = Literal["direct", "multi_source", "multi_hop"]

# Common capitalized words that are NOT entities (sentence starters,
# question words) -- filtered out of the regex-based entity grab.
_STOPWORDS = {
    "The", "A", "An", "Which", "What", "Who", "When", "Where", "Why",
    "How", "List", "Find", "For", "In", "On", "Is", "Are", "Does",
    "Do", "Name", "Every", "Company", "Companies",
}

# Matches sequences of 1+ capitalized words (naive proper-noun grab)
_ENTITY_PATTERN = re.compile(r"\b([A-Z][a-zA-Z0-9&]*(?:\s+[A-Z][a-zA-Z0-9&]*)*)\b")


class ResearchPlan(BaseModel):
    """Contract every later graph node (Router, Search, Evidence) relies on."""

    original_question: str
    entities: list[str] = Field(default_factory=list)
    route: Route
    sub_questions: list[str]
    reasoning: str  # short internal note for the trace log, never shown to user


class SubQuestionResponse(BaseModel):
    sub_questions: list[str]
    reasoning: str = ""


_llm_client = OllamaClient()


def extract_entities(question: str) -> list[str]:
    """Rule-based proper-noun grab. See module docstring for limitations."""
    candidates = _ENTITY_PATTERN.findall(question)
    entities = []
    for c in candidates:
        words = c.split()
        # Drop single-word matches that are just stopwords/question words
        if len(words) == 1 and c in _STOPWORDS:
            continue
        # Drop if EVERY word in a multi-word match is a stopword
        if all(w in _STOPWORDS for w in words):
            continue
        entities.append(c.strip())
    # De-duplicate, preserve order
    seen = set()
    unique = []
    for e in entities:
        if e not in seen:
            seen.add(e)
            unique.append(e)
    return unique


def classify_route(question: str) -> Route:
    """Rule-based route classification. Order matters: multi_hop checked first
    because a question can contain both multi_source AND multi_hop signals --
    chained dependency is the harder case, so it wins the classification."""
    q_lower = question.lower()

    if any(kw in q_lower for kw in MULTI_HOP_KEYWORDS):
        return "multi_hop"
    if any(kw in q_lower for kw in MULTI_SOURCE_KEYWORDS):
        return "multi_source"
    return "direct"


def generate_sub_questions(question: str, entities: list[str], route: Route) -> tuple[list[str], str]:
    """Returns (sub_questions, reasoning). Only calls the LLM for the two
    harder routes -- direct questions skip the LLM entirely (zero cost)."""

    if route == "direct":
        return [question], "Direct route: question stands as its own search query, no decomposition needed."

    prompt = f"""You are a research planning assistant. Break the following question into
2-4 concrete, independently-searchable web search queries. Each query should
be short and specific (like something you'd actually type into a search box).

Question: {question}
Known entities mentioned: {', '.join(entities) if entities else 'none detected'}
Question type: {route}

Respond with ONLY a JSON object, no other text, in this exact shape:
{{"sub_questions": ["query 1", "query 2", ...], "reasoning": "one short sentence"}}
"""

    try:
        result = _llm_client.call(
            prompt,
            schema=SubQuestionResponse,
            max_output_tokens=PLANNER_MAX_OUTPUT_TOKENS,
        )
        parsed = result.parsed
        if parsed is None:
            raise ValueError("LLM returned malformed structured output")
        sub_qs = parsed["sub_questions"]
        reasoning = parsed.get("reasoning", "")
        if not sub_qs or not isinstance(sub_qs, list):
            raise ValueError("LLM returned empty or malformed sub_questions list")
        return sub_qs, reasoning
    except Exception as exc:
        # FALLBACK: never let planning fully fail. Worst case, treat it like
        # a direct question -- one query, degraded but not broken.
        logger.warning("Sub-question generation failed (%s), falling back to raw question.", exc)
        return [question], f"LLM decomposition failed ({type(exc).__name__}), fell back to raw question."


def create_plan(question: str) -> ResearchPlan:
    """The Planner node's single public entry point."""
    entities = extract_entities(question)
    route = classify_route(question)
    sub_questions, reasoning = generate_sub_questions(question, entities, route)

    return ResearchPlan(
        original_question=question,
        entities=entities,
        route=route,
        sub_questions=sub_questions,
        reasoning=reasoning,
    )
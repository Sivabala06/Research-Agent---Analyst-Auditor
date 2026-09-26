"""
tracer.py

Full operational tracing + cost accounting -- required per the
problem statement's "full operational tracing" and "report cost per
question in tokens and rupees, show the trend" asks.

One TraceRecorder per question. Call log_event()/log_llm_call() as
the pipeline runs, then save_to_jsonl() appends one JSON line per
question to a run log file -- this is what the write-up's cost
trend and full traces get built from.
"""

from __future__ import annotations
import json
import time
from pathlib import Path
from pydantic import BaseModel, Field

from config import RUPEES_PER_1K_TOKENS


class TraceEvent(BaseModel):
    timestamp: float
    node: str
    event_type: str  # "plan" | "search" | "fetch" | "llm_call" | "audit" | "error"
    detail: dict = Field(default_factory=dict)


class QuestionTrace(BaseModel):
    question: str
    events: list[TraceEvent] = Field(default_factory=list)
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    wall_clock_seconds: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens

    @property
    def estimated_cost_rupees(self) -> float:
        return (self.total_tokens / 1000) * RUPEES_PER_1K_TOKENS


class TraceRecorder:
    def __init__(self, question: str):
        self._trace = QuestionTrace(question=question)
        self._start_time: float = 0.0

    def start(self) -> None:
        self._start_time = time.perf_counter()

    def log_event(self, node: str, event_type: str, detail: dict | None = None) -> None:
        self._trace.events.append(TraceEvent(timestamp=time.time(), node=node,
                                              event_type=event_type, detail=detail or {}))

    def log_llm_call(self, node: str, llm_result) -> None:
        """Accepts an LLMResult (has .prompt_tokens / .completion_tokens)."""
        self._trace.total_prompt_tokens += llm_result.prompt_tokens
        self._trace.total_completion_tokens += llm_result.completion_tokens
        self.log_event(node, "llm_call", {
            "prompt_tokens": llm_result.prompt_tokens,
            "completion_tokens": llm_result.completion_tokens,
            "latency_seconds": round(llm_result.latency_seconds, 3),
            "hit_output_cap": llm_result.hit_output_cap,
        })

    def finish(self) -> QuestionTrace:
        self._trace.wall_clock_seconds = round(time.perf_counter() - self._start_time, 3)
        return self._trace

    def save_to_jsonl(self, trace: QuestionTrace, path: str | Path) -> None:
        record = trace.model_dump()
        record["total_tokens"] = trace.total_tokens
        record["estimated_cost_rupees"] = trace.estimated_cost_rupees
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
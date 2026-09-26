import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tracer import TraceRecorder


class FakeLLMResult:
    def __init__(self, p, c):
        self.prompt_tokens = p
        self.completion_tokens = c
        self.latency_seconds = 0.1
        self.hit_output_cap = False


def test_recorder_accumulates_tokens_and_events():
    rec = TraceRecorder("test question")
    rec.start()
    rec.log_event("planner", "plan", {"route": "direct"})
    rec.log_llm_call("claims", FakeLLMResult(100, 50))
    rec.log_llm_call("claims", FakeLLMResult(30, 10))
    trace = rec.finish()
    assert trace.total_prompt_tokens == 130
    assert trace.total_completion_tokens == 60
    assert trace.total_tokens == 190
    assert len(trace.events) == 3


def test_save_to_jsonl_writes_one_line(tmp_path):
    rec = TraceRecorder("q1")
    rec.start()
    rec.log_llm_call("claims", FakeLLMResult(10, 5))
    trace = rec.finish()
    out_path = tmp_path / "runs.jsonl"
    rec.save_to_jsonl(trace, out_path)
    lines = out_path.read_text(encoding="utf-8").strip().split("\n")
    assert json.loads(lines[0])["total_prompt_tokens"] == 10
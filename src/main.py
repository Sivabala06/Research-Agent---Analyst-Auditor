"""
main.py — Interactive Research Agent CLI

One-at-a-time question loop. Every question runs the full LangGraph
pipeline (input guard -> planner -> memory -> search -> evidence ->
claims -> auditor -> output guard -> memory save) and prints the full
transparent trace to the terminal.

Type 'exit' or 'quit' to stop.  Ctrl-C also exits cleanly.

TRACING: every pipeline stage is printed live as the run completes —
plan route, memory cache hits, search/fetch events, claim/verdict
breakdown, corroboration flags, and wall-clock / token cost.
"""

from __future__ import annotations

import sys
import textwrap

from graph import run_pipeline
from report import print_full_report


BANNER = r"""
╔══════════════════════════════════════════════════════════════════════════════╗
║          RESEARCH AGENT  ·  Zero-Cost Local AI  ·  Analyst + Auditor       ║
║  Live web search  |  Citation-backed answers  |  Independent audit          ║
╚══════════════════════════════════════════════════════════════════════════════╝
  Type your research question and press ENTER.
  Type  exit  or  quit  to stop.  Ctrl-C also exits cleanly.
"""

SEPARATOR = "─" * 78


def _print_thinking(stage: str) -> None:
    """Show a live status line so the user knows the agent is working."""
    print(f"\n  ⟳  {stage} ...", flush=True)


def _prompt_user() -> str:
    print(f"\n{SEPARATOR}")
    try:
        raw = input("  YOUR QUESTION  ▶  ").strip()
    except EOFError:
        raw = "exit"
    return raw


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(BANNER)
    print("  NOTE: Ollama must be running (`ollama serve`) before you ask anything.")
    print(f"  Model: qwen3:4b  |  Memory: SQLite + fastembed semantic gating")
    print(f"  All tracing is printed in full after each answer.\n")

    session_count = 0
    try:
        while True:
            question = _prompt_user()

            if not question:
                print("  (empty input — please type a question)")
                continue

            if question.lower() in {"exit", "quit", "q", ":q", "bye"}:
                print(f"\n  Session ended. {session_count} question(s) answered. Goodbye!\n")
                return

            session_count += 1
            print(f"\n  [{session_count}] Running pipeline for: {question!r}")
            _print_thinking("Working (Input Guard → Planner → Memory → Search/Fetch → Claims → Audit)")

            try:
                result = run_pipeline(question)
            except Exception as exc:
                print(f"\n  ✗ Pipeline error: {exc}")
                print("  (Is Ollama running? Try: ollama serve)")
                continue

            print(f"\n  ✓ Done in {result.trace.wall_clock_seconds:.1f}s  |  "
                  f"Tokens used: {result.trace.total_tokens}  |  "
                  f"Audit: {'PASSED ✓' if result.audit_report.passed else 'FAILED ✗'}")

            print(f"\n{SEPARATOR}")
            print("  FULL TRACE  (plan → search → evidence → claims → audit → answer)")
            print(SEPARATOR)
            print_full_report(result)

            print(SEPARATOR)
            print("  QUICK ANSWER")
            print(SEPARATOR)
            wrapped = textwrap.fill(result.validated_answer.answer_text, width=74,
                                    initial_indent="  ", subsequent_indent="  ")
            print(wrapped)
            if result.validated_answer.unresolved:
                wrapped_ur = textwrap.fill(
                    f"Unresolved: {result.validated_answer.unresolved}", width=74,
                    initial_indent="  ", subsequent_indent="    "
                )
                print(wrapped_ur)
            print(SEPARATOR)
    except KeyboardInterrupt:
        print(f"\n  Session interrupted. {session_count} question(s) answered. Goodbye!\n")

if __name__ == "__main__":
    main()

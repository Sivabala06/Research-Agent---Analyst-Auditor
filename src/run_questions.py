"""
run_questions.py — runs the 8 required research questions end-to-end,
saves full traces to runs.jsonl, prints a cost/time summary table.
Questions #5, #6, #8 deliberately reuse entities from #1/#4 to
demonstrate memory making later questions cheaper/faster.
"""
from __future__ import annotations
import json
from pathlib import Path
from graph import run_pipeline

QUESTIONS = [
    "Which pharmaceutical company received the most recent FDA approval for an Alzheimer's drug, and what is the drug's name?",  # 1: direct, biomedical
    "Which three tourist destinations in Tamil Nadu attract the most visitors annually?",                                        # 2: multi_source, tourism
    "List the companies currently leading in AI chip market share, with approximate percentages.",                               # 3: multi_source, technology
    "Who is the current Chief Scientific Officer of Moderna, and where did they work before joining?",                           # 4: multi_hop, biomedical
    "What is Moderna's most recently FDA-approved vaccine or product?",                                                          # 5: direct, REUSES Moderna (from Q4)
    "What is the best time of year to visit Ooty in Tamil Nadu, and why?",                                                       # 6: direct, REUSES Tamil Nadu tourism (from Q2)
    "What is the current population of Chennai city, and why might different sources report different numbers?",                 # 7: multi_source, communication/demographics — conflicting-sources test
    "Who is the current Chairman of ISRO, and where did they work before joining?",                                              # 8: multi_hop, technology/space
    "What is ISRO's most recently launched satellite or space mission?",                                                         # 9: direct, REUSES ISRO (from Q8)
    "Which country currently ranks highest in life expectancy, and what factors are most commonly cited for it?",                # 10: multi_source, healthcare
]

LOG_PATH = "runs.jsonl"

from graph import run_pipeline
from report import print_full_report

def main():
    Path(LOG_PATH).write_text("")
    for i, q in enumerate(QUESTIONS, start=1):
        print(f"\n{'#'*10} Question {i}/{len(QUESTIONS)} {'#'*10}")
        result = run_pipeline(q, log_path=LOG_PATH)
        print_full_report(result)

    print("=== Cost / time summary ===")
    with open(LOG_PATH, encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            rec = json.loads(line)
            print(f"Q{i}: tokens={rec.get('total_tokens', 0):>5}  time={rec.get('wall_clock_seconds', 0):.1f}s")

if __name__ == "__main__":
    main()
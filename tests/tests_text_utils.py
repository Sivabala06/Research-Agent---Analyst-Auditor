import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from text_utils import best_snippet


def test_short_text_returned_unchanged():
    text = "short text here"
    assert best_snippet(text, "anything", window_words=140) == text


def test_picks_window_containing_query_keywords():
    filler = " ".join(["irrelevant"] * 200)
    relevant = "Kalyan Jewellers reported thirty percent growth in revenue"
    text = f"{filler} {relevant} {filler}"
    result = best_snippet(text, "Kalyan Jewellers revenue growth", window_words=20)
    assert "Kalyan" in result
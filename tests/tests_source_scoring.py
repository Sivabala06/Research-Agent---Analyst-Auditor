import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from source_scoring import score_source


def test_gov_domain_scores_tier_1():
    tier, score = score_source("https://www.isro.gov.in/leadership.html", "real content")
    assert tier == "tier_1" and score >= 0.8


def test_unknown_domain_scores_tier_3():
    tier, _ = score_source("https://randomblogsite123.com/article", "some content")
    assert tier == "tier_3"


def test_spam_signal_lowers_score():
    _, spammy = score_source("https://randomblogsite123.com/a", "click here for the top-10-list")
    _, clean = score_source("https://randomblogsite123.com/a", "a normal informative article")
    assert spammy < clean
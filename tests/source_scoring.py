"""
source_scoring.py — zero-cost domain-reputation heuristic. Does NOT verify
accuracy (the Auditor's fact-check job) -- flags whether a claim's cited
domain is well-known-authoritative, recognized-secondary, or unclassified.

HONEST LIMITATION: this is a domain allowlist, not a real credibility
model. A domain not listed isn't "bad" -- it's unclassified (tier 3). A
listed domain isn't guaranteed accurate either.
"""
from __future__ import annotations
from urllib.parse import urlparse

TIER_1_DOMAINS = {
    ".gov", ".gov.in", ".edu", "reuters.com", "apnews.com", "bbc.com",
    "thehindu.com", "livemint.com", "economictimes.com", "moneycontrol.com",
    "business-standard.com", "isro.gov.in", "rbi.org.in", "sebi.gov.in",
    "who.int", "fda.gov", "nature.com", "science.org",
}
TIER_2_DOMAINS = {
    "wikipedia.org", "crunchbase.com", "tracxn.com", "bloomberg.com",
    "forbes.com", "hindustantimes.com", "indianexpress.com",
    "timesofindia.indiatimes.com",
}
SPAM_SIGNALS = ["click here", "you won't believe", "top-10-list", "sponsored"]


def score_source(url: str, text: str) -> tuple[str, float]:
    domain = urlparse(url).netloc.lower()

    if any(domain.endswith(d) or d in domain for d in TIER_1_DOMAINS):
        base, tier = 0.9, "tier_1"
    elif any(domain.endswith(d) or d in domain for d in TIER_2_DOMAINS):
        base, tier = 0.6, "tier_2"
    else:
        base, tier = 0.3, "tier_3"

    if any(signal in text.lower() for signal in SPAM_SIGNALS):
        base = max(0.0, base - 0.3)

    return tier, round(base, 2)
"""
router.py

Reads plan.route (already decided by planner.py) and dispatches to
the matching search execution strategy. This file's job is ONLY
dispatch + running sub-questions through search_tool -- it does not
re-decide the route and does not fetch/parse pages itself.

Design note: multi_source sub-questions are independent of each
other by definition (that's what makes them multi_source, not
multi_hop) -- so they're the natural place to introduce parallel
execution later for the two-minute wall-clock stretch goal. Kept
sequential for now per "build incrementally"; noted here so we don't
forget it's the intended parallelization point.
"""

from __future__ import annotations

import logging
from typing import Callable

from planner import ResearchPlan
from search_tool import SearchTool, SearchResult  # adjust import to your actual module

logger = logging.getLogger("research_agent.router")


class RoutedSearchResults:
    """Search results grouped by which sub-question produced them."""

    def __init__(self, plan: ResearchPlan):
        self.plan = plan
        self.results_by_subquestion: dict[str, list[SearchResult]] = {}
        self.failed_subquestions: list[str] = []

    def add(self, sub_question: str, results: list[SearchResult]) -> None:
        self.results_by_subquestion[sub_question] = results

    def mark_failed(self, sub_question: str) -> None:
        self.failed_subquestions.append(sub_question)


def run_search_for_plan(plan: ResearchPlan, search_tool: SearchTool) -> RoutedSearchResults:
    """Single entry point. All three routes currently execute the same way
    (run each sub-question through search) -- the ROUTE VALUE ITSELF is
    still used downstream (Evidence/Auditor need to know if this was
    direct vs multi_source vs multi_hop to decide how many independent
    sources are needed to confirm a claim). Kept as one function now;
    split into per-route functions only if their execution actually
    needs to differ, not preemptively."""

    routed = RoutedSearchResults(plan)

    for sub_q in plan.sub_questions:
        try:
            results = search_tool.search(sub_q)
            if not results:
                logger.warning("No search results for sub-question: %r", sub_q)
                routed.mark_failed(sub_q)
                continue
            routed.add(sub_q, results)
        except Exception as exc:
            # A search provider failing on ONE sub-question must not kill
            # the whole plan -- log it, mark it, keep going. Matches the
            # problem statement's "state plainly when it cannot find
            # something" requirement, at the search layer.
            logger.warning("Search failed for sub-question %r: %s", sub_q, exc)
            routed.mark_failed(sub_q)

    return routed
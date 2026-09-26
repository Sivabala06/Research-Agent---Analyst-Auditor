"""
multi_hop.py

Real two-step chained lookup: hop 2's search query is built from
hop 1's ACTUAL fetched answer, not fired in the same batch as hop 1
(which is what router.py does for multi_source, and did for
multi_hop until now — see router.py's own note on this).

LIMITATION (stated honestly): handles exactly TWO hops
(fact -> extract -> second search). A three-hop chain would need
this generalized into a loop; not built, since none of the 8
required questions need more than two.
"""
from __future__ import annotations
import logging
from pydantic import BaseModel

from planner import ResearchPlan
from search_tool import SearchTool, SearchResult
from fetch_tool import Fetcher, FetchError, FetchedPage
from evidence import EvidenceBundle, EvidencePiece
from llm_client import OllamaClient
from config import PLANNER_MAX_OUTPUT_TOKENS

logger = logging.getLogger("research_agent.multi_hop")
_llm_client = OllamaClient()


class HopExtraction(BaseModel):
    extracted_value: str
    found: bool


def _fetch_first_usable(
    results: list[SearchResult], fetcher: Fetcher
) -> tuple[SearchResult, FetchedPage] | None:
    for result in results:
        try:
            return result, fetcher.fetch(result.url)
        except FetchError as exc:
            logger.info("Hop fetch skipped for %s: %s", result.url, exc)
    return None


def run_multi_hop(plan: ResearchPlan, search_tool: SearchTool, fetcher: Fetcher, trace=None) -> EvidenceBundle:
    bundle = EvidenceBundle()
    if not plan.sub_questions:
        return bundle

    hop1_query = plan.sub_questions[0]
    try:
        hop1_results = search_tool.search(hop1_query)
    except Exception as exc:
        logger.warning("Hop 1 search failed: %s", exc)
        bundle.failed_urls.append(hop1_query)
        return bundle

    fetched = _fetch_first_usable(hop1_results, fetcher)
    if fetched is None:
        bundle.failed_urls.append(hop1_query)
        return bundle
    r1, page1 = fetched
    hop1_text = page1.text
    bundle.pieces.append(EvidencePiece(sub_question=hop1_query, url=r1.url, title=r1.title,
                                        text=hop1_text, word_count=len(hop1_text.split()),
                                        source_year=page1.source_year))

    extraction_task = plan.sub_questions[1] if len(plan.sub_questions) > 1 else plan.original_question
    prompt = f"""Based on this text, extract the specific fact needed for the next step.

TEXT:
{hop1_text[:1500]}

FIRST-STEP QUESTION: {hop1_query}
FOLLOW-UP QUESTION: {extraction_task}

Extract the answer to the first-step question (usually a person's or organization's
name) so it can be used to research the follow-up question.

Respond with ONLY: {{"extracted_value": "the name/fact found, or empty string", "found": true/false}}
"""
    result = _llm_client.call(prompt, schema=HopExtraction, max_output_tokens=PLANNER_MAX_OUTPUT_TOKENS)
    if trace:
        trace.log_llm_call("multi_hop_extract", result)
    if result.parsed is None or not result.parsed.get("found"):
        logger.info("Hop 1 insufficient to build hop 2 query; stopping at one hop.")
        return bundle

    extracted_value = result.parsed.get("extracted_value", "").strip()
    if not extracted_value:
        logger.info("Hop 1 extraction returned no value; stopping at one hop.")
        return bundle

    hop2_query = f"{extracted_value} {extraction_task}"
    try:
        hop2_results = search_tool.search(hop2_query)
    except Exception as exc:
        logger.warning("Hop 2 search failed: %s", exc)
        bundle.failed_urls.append(hop2_query)
        return bundle

    fetched2 = _fetch_first_usable(hop2_results, fetcher)
    if fetched2 is None:
        bundle.failed_urls.append(hop2_query)
        return bundle
    r2, page2 = fetched2
    hop2_text = page2.text
    bundle.pieces.append(EvidencePiece(sub_question=hop2_query, url=r2.url, title=r2.title,
                                        text=hop2_text, word_count=len(hop2_text.split()),
                                        source_year=page2.source_year))
    return bundle

from __future__ import annotations
from typing import TypedDict, Optional

from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel

from multi_hop import run_multi_hop
from planner import create_plan, ResearchPlan
from router import run_search_for_plan, RoutedSearchResults
from evidence import gather_evidence, EvidenceBundle
from claims import generate_candidate_answer, CandidateAnswer
from auditor import audit_answer, AuditReport
from guards import input_guard, output_guard, InputGuardError
from memory import MemoryStore
from tracer import TraceRecorder
from search_tool import DuckDuckGoSearchTool
from fetch_tool import Fetcher

from tracer import QuestionTrace

class PipelineResult(BaseModel):
    question: str
    plan: ResearchPlan
    candidate_answer: CandidateAnswer
    audit_report: AuditReport
    validated_answer: CandidateAnswer
    retry_count: int
    trace: QuestionTrace

class GraphState(TypedDict, total=False):
    question: str
    plan: ResearchPlan
    routed: RoutedSearchResults
    evidence: EvidenceBundle
    cached_evidence: EvidenceBundle
    answer: CandidateAnswer
    audit: AuditReport
    retry_count: int
    validated_answer: CandidateAnswer
    trace: TraceRecorder


_search_tool = DuckDuckGoSearchTool()
_fetcher = Fetcher()
_memory = MemoryStore()


def input_guard_node(state: GraphState) -> dict:
    return {"question": input_guard(state["question"])}

def planner_node(state: GraphState) -> dict:
    plan = create_plan(state["question"])
    state["trace"].log_event("planner", "plan", {"route": plan.route, "entities": plan.entities})
    return {"plan": plan}

def memory_lookup_node(state: GraphState) -> dict:
    facts = _memory.get_facts_for_entities(
        state["plan"].entities,
        state["question"],
    )
    bundle = _memory.facts_to_evidence_bundle(facts)
    state["trace"].log_event("memory_lookup", "cache_check", {"cached_facts_found": len(bundle.pieces)})
    return {"cached_evidence": bundle}


def route_after_memory(state: GraphState) -> str:
    cached = state.get("cached_evidence")
    if cached and cached.pieces:
        state["trace"].log_event("router_decision", "route", {"chosen": "use_cache", "cached_pieces": len(cached.pieces)})
        return "use_cache"
    if state["plan"].route == "multi_hop":
        state["trace"].log_event("router_decision", "route", {"chosen": "multi_hop"})
        return "multi_hop"
    state["trace"].log_event("router_decision", "route", {"chosen": "search"})
    return "search"


def multi_hop_node(state: GraphState) -> dict:
    bundle = run_multi_hop(state["plan"], _search_tool, _fetcher, state["trace"])
    return {"evidence": bundle}

def use_cached_evidence_node(state: GraphState) -> dict:
    return {"evidence": state["cached_evidence"]}

def router_node(state: GraphState) -> dict:
    routed = run_search_for_plan(state["plan"], _search_tool)
    state["trace"].log_event("router", "search", {"sub_questions": len(state["plan"].sub_questions)})
    return {"routed": routed}

def evidence_node(state: GraphState) -> dict:
    fresh = gather_evidence(state["routed"], _fetcher)
    cached = state.get("cached_evidence") or EvidenceBundle()
    merged = EvidenceBundle(pieces=cached.pieces + fresh.pieces, failed_urls=fresh.failed_urls)
    state["trace"].log_event("evidence", "fetch", {"pieces": len(merged.pieces), "failed": len(merged.failed_urls)})
    return {"evidence": merged}

def claims_node(state: GraphState) -> dict:
    return {"answer": generate_candidate_answer(state["plan"], state["evidence"], state["trace"])}

def auditor_node(state: GraphState) -> dict:
    # FIX 5.2 + graph.py: pass state["evidence"] so the auditor can cross-check
    # claims against OTHER retrieved sources (corroboration check).
    report = audit_answer(state["answer"], _fetcher, state["evidence"], state["trace"])
    state["trace"].log_event("auditor", "audit", {"passed": report.passed,
        "supported": report.supported_count, "unsupported": report.unsupported_count,
        "contradicted": report.contradicted_count})
    return {"audit": report}

def route_after_audit(state: GraphState) -> str:
    if state["audit"].passed or state.get("retry_count", 0) >= 1:
        state["trace"].log_event("router_decision", "audit_route", {"chosen": "end", "passed": state["audit"].passed})
        return "end"
    state["trace"].log_event("router_decision", "audit_route", {"chosen": "retry"})
    return "retry"

def gap_analyzer_node(state: GraphState) -> dict:
    state["trace"].log_event("gap_analyzer", "retry_triggered", {})
    return {"retry_count": state.get("retry_count", 0) + 1}

def output_guard_node(state: GraphState) -> dict:
    return {"validated_answer": output_guard(state["answer"], state["audit"])}

def memory_save_node(state: GraphState) -> dict:
    supported = [(ac.statement, ac.url) for ac in state["audit"].audited_claims if ac.verdict == "supported"]
    _memory.save_facts(state["plan"].entities, supported, state["question"])
    state["trace"].log_event("memory_save", "saved", {"facts_saved": len(supported)})
    return {}


def build_graph():
    g = StateGraph(GraphState)
    for name, fn in [("input_guard", input_guard_node), ("planner", planner_node),
                      ("memory_lookup", memory_lookup_node), ("use_cached_evidence", use_cached_evidence_node),
                      ("router", router_node), ("multi_hop", multi_hop_node), ("evidence", evidence_node), ("claims", claims_node),
                      ("auditor", auditor_node), ("gap_analyzer", gap_analyzer_node),
                      ("output_guard", output_guard_node), ("memory_save", memory_save_node)]:
        g.add_node(name, fn)

    g.add_edge(START, "input_guard")
    g.add_edge("input_guard", "planner")
    g.add_edge("planner", "memory_lookup")
    g.add_conditional_edges("memory_lookup", route_after_memory,
    {"use_cache": "use_cached_evidence", "search": "router", "multi_hop": "multi_hop"})
    g.add_edge("multi_hop", "claims")
    g.add_edge("use_cached_evidence", "claims")
    g.add_edge("router", "evidence")
    g.add_edge("evidence", "claims")
    g.add_edge("claims", "auditor")
    g.add_conditional_edges("auditor", route_after_audit, {"end": "output_guard", "retry": "gap_analyzer"})
    g.add_edge("gap_analyzer", "router")

    g.add_edge("output_guard", "memory_save")
    g.add_edge("memory_save", END)
    return g.compile()


def run_pipeline(question: str, log_path: str = "runs.jsonl") -> PipelineResult:
    recorder = TraceRecorder(question)
    recorder.start()
    app = build_graph()
    try:
        final_state = app.invoke({"question": question, "trace": recorder})
    except InputGuardError as exc:
        recorder.log_event("input_guard", "error", {"reason": str(exc)})
        trace = recorder.finish()
        recorder.save_to_jsonl(trace, log_path)
        empty = CandidateAnswer(question=question, claims=[], unresolved=str(exc), answer_text=f"Input rejected: {exc}")
        empty_audit = AuditReport(question=question, audited_claims=[], passed=False,
                                   supported_count=0, unsupported_count=0, contradicted_count=0)
        return PipelineResult(question=question,
            plan=ResearchPlan(original_question=question, entities=[], route="direct", sub_questions=[], reasoning="rejected by input guard"),
            candidate_answer=empty, audit_report=empty_audit, validated_answer=empty, retry_count=0, trace=trace)

    trace = recorder.finish()
    recorder.save_to_jsonl(trace, log_path)
    return PipelineResult(
        question=question, plan=final_state["plan"], candidate_answer=final_state["answer"],
        audit_report=final_state["audit"], validated_answer=final_state["validated_answer"],
        retry_count=final_state.get("retry_count", 0), trace=trace,
    )
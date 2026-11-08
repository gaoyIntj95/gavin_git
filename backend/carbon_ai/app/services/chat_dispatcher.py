from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.services.agent.orchestrator import ask_with_agent
from app.services.agent.registry_center import build_default_registry
from app.services.agent.router import execute_tool_call
from app.services.agent.tools.emission_breakdown_tool import format_emission_breakdown_answer
from app.services.agent.tools.emission_summary_tool import format_emission_summary_answer
from app.services.chat_governance import (
    is_business_operation_query,
    resolve_execution_mode,
    should_apply_preset,
)
from app.services.rag_service import (
    ask_with_general_llm,
    ask_with_rag,
    ask_with_web_context,
    retrieve_relevant_docs,
)
from app.services.web_search_service import search_web

RAG_DISTANCE_THRESHOLD = 0.45
DEFAULT_TOOL_REGISTRY = build_default_registry()


def _execute_tool_call(db: Session, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return execute_tool_call(db, DEFAULT_TOOL_REGISTRY, tool_name, arguments)


@dataclass
class DispatchPlan:
    execution_mode: str
    chain: str  # "data" | "knowledge"
    allow_preset: bool
    route_reason: str


BREAKDOWN_HINTS = (
    "排放源",
    "各排放源",
    "各个排放源",
    "来源",
    "明细",
    "拆分",
    "细分",
    "占比",
    "top",
    "breakdown",
)

INTERNAL_ANSWER_NOISE = (
    "拆解用户请求",
    "分析输入数据",
    "json对象",
    "tool:",
    "调用说明",
    "返回结果",
)
DATA_MARKERS = (
    "总排放量",
    "吨二氧化碳当量",
    "scope 1",
    "scope 2",
    "scope 3",
    "占比",
)


def _has_confident_retrieval(docs: list[dict], threshold: float = RAG_DISTANCE_THRESHOLD) -> bool:
    if not docs:
        return False
    distances = [
        float(doc.get("distance"))
        for doc in docs
        if isinstance(doc, dict) and doc.get("distance") is not None
    ]
    if not distances:
        return True
    return min(distances) <= threshold


def _looks_like_carbon_domain(question: str) -> bool:
    lower_q = (question or "").lower()
    keywords = [
        "碳",
        "排放",
        "温室气体",
        "scope",
        "cbam",
        "核算",
        "盘查",
        "绿电",
        "因子",
        "ghg",
        "iso 14064",
        "iso14064",
        "js/t 303",
        "js/t303",
        "碳足迹",
        "碳市场",
        "配额",
        "履约",
        "esg",
    ]
    return any(k in lower_q for k in keywords)


def build_dispatch_plan(
    *,
    requested_mode: str,
    question: str,
    project_id: int | None,
    session_mode: str | None,
    last_mode: str | None,
    intake_active: bool,
) -> DispatchPlan:
    route_reason = "auto_default"
    execution_mode = resolve_execution_mode(
        requested_mode=requested_mode,
        question=question,
        project_id=project_id,
        session_mode=session_mode,
        last_mode=last_mode,
    )

    if intake_active:
        execution_mode = "agent"
        route_reason = "intake_active_forced_agent"

    chain = "data" if execution_mode == "agent" else "knowledge"
    if route_reason == "auto_default":
        if execution_mode == "agent" and project_id is not None and project_id > 0:
            route_reason = "business_with_project_context"
        elif execution_mode == "rag":
            route_reason = "knowledge_query"
        else:
            route_reason = "agent_default"
    if (
        chain == "data"
        and not intake_active
        and (project_id is None or project_id <= 0)
        and not is_business_operation_query(question)
    ):
        # Avoid forcing casual/general Q&A into the business-data tool chain.
        chain = "knowledge"
        route_reason = "non_business_guard_to_knowledge"

    allow_preset = (not intake_active) and should_apply_preset(
        requested_mode,
        execution_mode,
        question,
    )
    return DispatchPlan(
        execution_mode=execution_mode,
        chain=chain,
        allow_preset=allow_preset,
        route_reason=route_reason,
    )


def run_data_chain(
    *,
    question: str,
    session_id: str,
    project_id: int | None,
    db: Session,
    history_messages: list[dict[str, str]],
    forced_intent: str | None = None,
) -> tuple[str, list[str], dict[str, Any] | None]:
    # Single-intent, single-tool hard gate for project business queries.
    if project_id is not None and project_id > 0 and forced_intent in {"summary", "breakdown"}:
        if forced_intent == "breakdown":
            breakdown = _execute_tool_call(
                db,
                "get_emission_breakdown",
                {"project_id": project_id, "group_by": "source", "top_n": 10},
            )
            if isinstance(breakdown, dict) and not breakdown.get("error"):
                return (
                    format_emission_breakdown_answer(breakdown),
                    ["business_data:get_emission_breakdown"],
                    None,
                )
            return (
                format_emission_breakdown_answer(breakdown if isinstance(breakdown, dict) else {}),
                ["business_data:get_emission_breakdown"],
                None,
            )

        summary = _execute_tool_call(db, "get_emission_summary", {"project_id": project_id})
        if isinstance(summary, dict) and not summary.get("error"):
            return (
                format_emission_summary_answer(summary),
                ["business_data:get_emission_summary"],
                None,
            )
        return (
            format_emission_summary_answer(summary if isinstance(summary, dict) else {}),
            ["business_data:get_emission_summary"],
            None,
        )

    answer, references, chart = ask_with_agent(
        question=question,
        session_id=session_id,
        project_id=project_id,
        db=db,
        history_messages=history_messages,
    )
    references = list(references or [])

    def _has_tool_ref(tool_name: str) -> bool:
        marker = tool_name.lower()
        return any(marker in str(ref or "").lower() for ref in references)

    def _append_tool_ref(tool_name: str) -> None:
        ref = f"??????: {tool_name}"
        if ref not in references:
            references.append(ref)

    def _is_breakdown_by_rule() -> bool:
        q = (question or "").strip().lower()
        robust_hints = (
            "???", "????", "?????", "??", "??", "??", "??", "??",
            "source", "sources", "breakdown", "top",
        )
        return any(k in q for k in BREAKDOWN_HINTS) or any(k in q for k in robust_hints)

    def _is_breakdown_by_context() -> bool:
        q = (question or "").strip().lower()
        followup_hints = ("??", "??", "???", "???", "??", "??", "continue", "more detail")
        if not any(k in q for k in followup_hints):
            return False
        history_tail = "\n".join(str(m.get("content", "")) for m in (history_messages or [])[-6:]).lower()
        return ("scope" in history_tail) or ("???" in history_tail) or ("get_emission_summary" in history_tail)

    def _is_breakdown_by_proxy() -> bool:
        q = (question or "").strip().lower()
        soft_hints = ("?", "??", "??", "??", "source", "item")
        detail_hints = ("??", "??", "??", "??", "??", "detail")
        return any(a in q for a in soft_hints) and any(b in q for b in detail_hints)

    def _has_internal_noise() -> bool:
        text = (answer or "").lower()
        return any(k in text for k in INTERNAL_ANSWER_NOISE)

    def _has_renderable_breakdown_text() -> bool:
        text = (answer or "").lower()
        return (("?" in text or "co2e" in text) and ("1." in text or "1?" in text))

    def _is_breakdown_request() -> bool:
        score = 0
        if _is_breakdown_by_rule():
            score += 2
        if _is_breakdown_by_context():
            score += 2
        if _is_breakdown_by_proxy():
            score += 1
        return score >= 2

    breakdown_requested = _is_breakdown_request()

    if project_id is not None and project_id > 0 and breakdown_requested and not _has_tool_ref("get_emission_breakdown"):
        breakdown = _execute_tool_call(
            db,
            "get_emission_breakdown",
            {"project_id": project_id, "group_by": "source", "top_n": 10},
        )
        if isinstance(breakdown, dict) and not breakdown.get("error"):
            answer = format_emission_breakdown_answer(breakdown)
            _append_tool_ref("get_emission_breakdown")

    if project_id is not None and project_id > 0 and _has_internal_noise():
        if breakdown_requested:
            breakdown = _execute_tool_call(
                db,
                "get_emission_breakdown",
                {"project_id": project_id, "group_by": "source", "top_n": 10},
            )
            if isinstance(breakdown, dict) and not breakdown.get("error"):
                answer = format_emission_breakdown_answer(breakdown)
                _append_tool_ref("get_emission_breakdown")
        else:
            summary = _execute_tool_call(db, "get_emission_summary", {"project_id": project_id})
            if isinstance(summary, dict) and not summary.get("error"):
                answer = format_emission_summary_answer(summary)
                _append_tool_ref("get_emission_summary")

    if project_id is not None and project_id > 0:
        if breakdown_requested and not _has_renderable_breakdown_text():
            breakdown = _execute_tool_call(
                db,
                "get_emission_breakdown",
                {"project_id": project_id, "group_by": "source", "top_n": 10},
            )
            if isinstance(breakdown, dict) and not breakdown.get("error"):
                answer = format_emission_breakdown_answer(breakdown)
                _append_tool_ref("get_emission_breakdown")
        elif not breakdown_requested:
            if not any(m.lower() in (answer or "").lower() for m in DATA_MARKERS):
                summary = _execute_tool_call(db, "get_emission_summary", {"project_id": project_id})
                if isinstance(summary, dict) and not summary.get("error"):
                    answer = format_emission_summary_answer(summary)
                    _append_tool_ref("get_emission_summary")

    return answer, references, chart



def run_knowledge_chain(
    *,
    question: str,
    session_id: str,
    history_messages: list[dict[str, str]],
) -> tuple[str, str, list[str]]:
    # Knowledge chain: domain-aware RAG retrieval, then web, then generic LLM fallback.
    if not _looks_like_carbon_domain(question):
        answer, references = ask_with_general_llm(
            question=question,
            history_messages=history_messages,
        )
        return "llm", answer, references

    docs = retrieve_relevant_docs(question, k=3)
    if _has_confident_retrieval(docs):
        answer, references = ask_with_rag(
            question=question,
            session_id=session_id,
            docs=docs,
            history_messages=history_messages,
        )
        return "rag", answer, references

    web_results = search_web(question)
    if web_results:
        answer, references = ask_with_web_context(
            question=question,
            web_results=web_results,
            history_messages=history_messages,
        )
        return "web", answer, references

    answer, references = ask_with_general_llm(
        question=question,
        history_messages=history_messages,
    )
    return "llm", answer, references

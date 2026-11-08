from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.agent.registry_center import build_default_registry
from app.services.agent.router import execute_tool_call
from app.services.agent.tool_call_parser import parse_tool_calls
from app.services.agent.tool_prompt import build_agent_system_prompt
from app.services.agent.tools.emission_breakdown_tool import format_emission_breakdown_answer
from app.services.agent.tools.emission_summary_tool import format_emission_summary_answer
from app.services.answer_presenter import present_user_answer
from app.services.llm_gateway import chat_messages
from app.services.memory_service import recall_long_term_memories, render_long_term_memory_context

logger = logging.getLogger(__name__)

FALLBACK_ENABLED = True
DEFAULT_TOOL_REGISTRY = build_default_registry()
AGENT_SYSTEM_PROMPT = build_agent_system_prompt(DEFAULT_TOOL_REGISTRY.list_tools())

AGENT_SECURITY_GUARD_ENABLED = os.getenv("AGENT_SECURITY_GUARD_ENABLED", "true").lower() == "true"
AGENT_AUDIT_LOG_ENABLED = os.getenv("AGENT_AUDIT_LOG_ENABLED", "true").lower() == "true"
AGENT_AUDIT_MAX_TEXT = max(200, int(os.getenv("AGENT_AUDIT_MAX_TEXT", "2000")))
AGENT_REQUIRE_TRACE_SOURCE = os.getenv("AGENT_REQUIRE_TRACE_SOURCE", "true").lower() == "true"
AGENT_MAX_TOOL_ARG_STR = max(64, int(os.getenv("AGENT_MAX_TOOL_ARG_STR", "300")))

READ_ONLY_TOOL_WHITELIST = {
    "get_project_info",
    "get_emission_summary",
    "get_emission_breakdown",
    "query_by_nl2sql",
    "knowledge_graph_query",
    "get_compliance_summary",
    "simulate_compliance_plan",
    "get_compliance_history",
    "get_cbam_batches",
    "get_cbam_batch_summary",
    "get_cbam_compliance_risk",
}

RISKY_INPUT_PATTERNS = [
    r"(?i)\b(ignore|bypass|override)\b.*\b(instruction|system|policy)\b",
    r"(?i)\b(drop|delete|truncate|alter|insert|update)\b\s+\b(table|database|schema)\b",
    r"(?i)\b(exec|shell|cmd|powershell|bash|os\.system|subprocess)\b",
    r"(?i)\b(password|token|api[_-]?key|secret)\b.*\b(show|export|dump|reveal)\b",
]

TRACE_REQUIRED_HINTS = [
    "核算",
    "公式",
    "排放因子",
    "标准",
    "iso",
    "cbam",
    "规则",
    "合规",
]

BUSINESS_RULE_BASIS = [
    {
        "rule": "组织级温室气体核算范围按 Scope1/Scope2/Scope3 框架归类。",
        "version": "ISO 14064-1:2018 / GHG Protocol",
        "source": "固定规则库 v1.0",
    },
    {
        "rule": "排放量计算采用 活动数据 × 排放因子（并按 GWP 折算 CO2e）。",
        "version": "IPCC / 国家与行业指南",
        "source": "固定规则库 v1.0",
    },
    {
        "rule": "工具输出优先于模型自由生成，模型仅负责整合解读。",
        "version": "Agent Safety Policy 2026-04",
        "source": "固定规则库 v1.0",
    },
]

EXPLAINABLE_POLICY_PROMPT = """
You are the Carbon AI Agent. Output requirements:
1) Use natural language to explain your understanding and analysis approach for the current question.
2) Explain which tools/data sources were used and why they were selected.
3) If standards or rules are involved, cite concrete standards (e.g., ISO 14064-1:2018, GHG Protocol).
4) Quantitative results must come from tool outputs; do not fabricate numbers.
5) Provide actionable business recommendations in addition to conclusions.
6) Do not output internal monologue (e.g., 'I now need to process...').
7) Do not use rigid section titles such as: ????, ????, ????, ????, ????.
"""


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _clip(text: str, limit: int = AGENT_AUDIT_MAX_TEXT) -> str:
    s = _safe_text(text)
    return s if len(s) <= limit else s[:limit] + "..."


def _looks_like_data_question(question: str) -> bool:
    q = (question or "").strip().lower()
    interpretive_keywords = [
        "什么样的企业",
        "哪些企业",
        "一般会在",
        "一般出现于",
        "适用场景",
        "行业特征",
        "典型企业",
        "概念",
        "定义",
        "区别",
        "标准解读",
        "业务解读",
        "科普",
        "如何理解",
    ]
    explicit_data_keywords = [
        "项目",
        "project",
        "总量",
        "总排放",
        "占比",
        "明细",
        "细分",
        "分项",
        "图表",
        "饼图",
        "柱状图",
        "折线图",
        "趋势",
        "同比",
        "环比",
        "scope",
        "吨",
        "co2e",
        "多少",
        "数值",
        "统计",
        "汇总",
    ]
    has_interpretive = any(k in q for k in interpretive_keywords)
    has_explicit_data = any(k in q for k in explicit_data_keywords)
    if has_interpretive and not has_explicit_data:
        return False

    keywords = [
        "项目",
        "排放",
        "scope",
        "总量",
        "占比",
        "拆分",
        "明细",
        "细分",
        "来源",
        "对比",
        "趋势",
        "emission",
        "breakdown",
    ]
    return any(k in q for k in keywords)


def _is_interpretive_question(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False
    interpretive_keywords = [
        "什么样的企业",
        "哪些企业",
        "一般会在",
        "一般出现于",
        "适用场景",
        "行业特征",
        "典型企业",
        "概念",
        "定义",
        "区别",
        "标准解读",
        "业务解读",
        "科普",
        "如何理解",
        "为什么",
    ]
    explicit_data_keywords = [
        "项目1",
        "项目 1",
        "project id",
        "总量",
        "总排放",
        "占比",
        "明细",
        "分项",
        "图表",
        "饼图",
        "柱状图",
        "折线图",
        "趋势",
        "同比",
        "环比",
        "scope",
        "吨",
        "co2e",
        "多少",
        "数值",
    ]
    return any(k in q for k in interpretive_keywords) and not any(k in q for k in explicit_data_keywords)


def _is_breakdown_intent(question: str) -> bool:
    q = (question or "").strip().lower()
    keywords = [
        "拆分",
        "明细",
        "细分",
        "来源",
        "分项",
        "排放源",
        "各排放源",
        "各个排放源",
        "占比",
        "继续",
        "展开",
        "breakdown",
        "details",
        "top",
    ]
    return any(k in q for k in keywords)


def _looks_like_followup(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False
    followup_keywords = ["继续", "继续拆分", "明细", "细分", "展开", "进一步", "go on", "continue"]
    if any(k in q for k in followup_keywords):
        return True
    return len(q) <= 12


def _detect_chart_type(question: str) -> str | None:
    q = (question or "").strip().lower()
    if not q:
        return None

    pie_keywords = ["饼图", "饼状图", "占比图", "环形图", "pie chart", "pie"]
    bar_keywords = ["柱状图", "条形图", "对比图", "bar chart", "bar"]
    line_keywords = ["折线图", "趋势图", "变化曲线", "line chart", "line"]

    if any(k in q for k in pie_keywords):
        return "pie"
    if any(k in q for k in bar_keywords):
        return "bar"
    if any(k in q for k in line_keywords):
        return "line"
    return None


def _is_chart_only_request(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False
    compact = re.sub(r"\s+", "", q)
    chart_aliases = {
        "折线图",
        "柱状图",
        "条形图",
        "饼图",
        "饼状图",
        "趋势图",
        "linechart",
        "barchart",
        "piechart",
        "line",
        "bar",
        "pie",
    }
    return compact in chart_aliases


def _has_usable_chart_source(all_tool_results: list[dict[str, Any]]) -> bool:
    breakdown = _extract_latest_tool_result(all_tool_results, "get_emission_breakdown")
    if isinstance(breakdown, dict):
        items = breakdown.get("items")
        if isinstance(items, list) and len(items) > 0:
            return True
    nl2sql = _extract_latest_tool_result(all_tool_results, "query_by_nl2sql")
    if isinstance(nl2sql, dict):
        rows = nl2sql.get("rows")
        if isinstance(rows, list) and len(rows) > 0:
            return True
    return False


def _build_chart_data_missing_prompt() -> str:
    return "请先指定项目或先执行一次数据查询"


def _input_risk_reason(question: str) -> str | None:
    if not AGENT_SECURITY_GUARD_ENABLED:
        return None
    text = _safe_text(question)
    for pattern in RISKY_INPUT_PATTERNS:
        if re.search(pattern, text):
            return f"命中安全规则: {pattern}"
    return None


def _sanitize_string(v: Any) -> str:
    s = _safe_text(v)
    if not s:
        return ""
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", s)
    s = s.replace("```", "")
    s = s.replace(";", " ")
    s = s.replace("--", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:AGENT_MAX_TOOL_ARG_STR]


def _sanitize_tool_arguments(tool_name: str, arguments: dict[str, Any], project_id: int | None) -> dict[str, Any]:
    safe_args: dict[str, Any] = {}
    args = arguments if isinstance(arguments, dict) else {}

    if tool_name not in READ_ONLY_TOOL_WHITELIST:
        return {"_blocked": True, "_error": f"不允许调用非白名单工具: {tool_name}"}

    for key, value in args.items():
        if isinstance(value, str):
            safe_args[key] = _sanitize_string(value)
        elif isinstance(value, (int, float, bool)) or value is None:
            safe_args[key] = value
        else:
            safe_args[key] = _sanitize_string(value)

    if project_id is not None and safe_args.get("project_id") is None:
        safe_args["project_id"] = project_id

    if tool_name in {"get_project_info", "get_emission_summary", "get_emission_breakdown"}:
        if safe_args.get("project_id") is None:
            return {"_blocked": True, "_error": "project_id 缺失"}
        try:
            safe_args["project_id"] = int(safe_args["project_id"])
        except Exception:
            return {"_blocked": True, "_error": "project_id 非法"}

    if tool_name == "get_emission_breakdown":
        group_by = _safe_text(safe_args.get("group_by", "source")).lower()
        if group_by not in {"source", "scope", "category"}:
            group_by = "source"
        safe_args["group_by"] = group_by
        try:
            top_n = int(safe_args.get("top_n", 10))
        except Exception:
            top_n = 10
        safe_args["top_n"] = max(1, min(top_n, 50))

    if tool_name == "query_by_nl2sql":
        question = _safe_text(safe_args.get("question"))
        if not question:
            return {"_blocked": True, "_error": "question 缺失"}
        if re.search(r"(?i)\b(drop|delete|truncate|alter|insert|update|grant|revoke)\b", question):
            return {"_blocked": True, "_error": "检测到潜在危险SQL意图"}
        safe_args["question"] = _sanitize_string(question)
        try:
            limit = int(safe_args.get("limit", 50))
        except Exception:
            limit = 50
        safe_args["limit"] = max(1, min(limit, 200))
        if safe_args.get("project_id") is not None:
            try:
                safe_args["project_id"] = int(safe_args["project_id"])
            except Exception:
                safe_args["project_id"] = None

    if tool_name in {"get_compliance_summary", "simulate_compliance_plan", "get_compliance_history", "get_cbam_batches"}:
        if safe_args.get("project_id") is None:
            return {"_blocked": True, "_error": "project_id missing"}
        try:
            safe_args["project_id"] = int(safe_args["project_id"])
        except Exception:
            return {"_blocked": True, "_error": "project_id invalid"}
    if tool_name in {"get_cbam_batch_summary", "get_cbam_compliance_risk"}:
        if safe_args.get("batch_id") is None:
            return {"_blocked": True, "_error": "batch_id missing"}
        try:
            safe_args["batch_id"] = int(safe_args["batch_id"])
        except Exception:
            return {"_blocked": True, "_error": "batch_id invalid"}

    return safe_args


def _tool_call_reason(tool_name: str, question: str, arguments: dict[str, Any]) -> str:
    q = _safe_text(question)
    if tool_name == "get_emission_breakdown":
        return f"原因: 用户关注拆分/结构；用途: 获取排放构成；核心入参: project_id={arguments.get('project_id')}, group_by={arguments.get('group_by', 'source')}, top_n={arguments.get('top_n', 10)}"
    if tool_name == "get_emission_summary":
        return f"原因: 需要总览排放；用途: 获取总量与Scope分布；核心入参: project_id={arguments.get('project_id')}"
    if tool_name == "get_project_info":
        return f"原因: 需要项目元信息；用途: 确认核算口径与边界；核心入参: project_id={arguments.get('project_id')}"
    if tool_name == "query_by_nl2sql":
        return f"原因: 需要复杂只读数据查询；用途: 业务分析取数；核心入参: question={_clip(arguments.get('question', ''), 80)}, limit={arguments.get('limit', 50)}"
    if tool_name == "knowledge_graph_query":
        return f"原因: 需要术语关系/政策层级溯源；用途: 图谱关系检索；核心入参: entity={arguments.get('entity', '')}, top_k={arguments.get('top_k', 8)}"
    return f"原因: 补充业务证据；用途: 只读查询；核心入参: {json.dumps(arguments, ensure_ascii=False)}"


def _citation_from_doc(doc: dict[str, Any], idx: int) -> dict[str, str]:
    meta = doc.get("metadata") or {}
    source = _safe_text(meta.get("source_file") or f"文档{idx}")
    section = _safe_text(meta.get("section") or "main")
    page = _safe_text(meta.get("page"))
    page_show = page if page else "-"
    snippet = _clip(_safe_text(doc.get("content")).replace("\n", " "), 120)
    return {
        "source": source,
        "section": section,
        "page": page_show,
        "snippet": snippet,
    }


def _build_citation_lines(docs: list[dict[str, Any]], limit: int = 3) -> list[str]:
    lines: list[str] = []
    for i, doc in enumerate(docs[: max(1, limit)], 1):
        c = _citation_from_doc(doc, i)
        lines.append(
            f"- {c['source']} | 章节: {c['section']} | 页码: {c['page']} | 片段: \"{c['snippet']}\""
        )
    return lines


def _requires_trace(question: str) -> bool:
    q = _safe_text(question).lower()
    return any(k in q for k in TRACE_REQUIRED_HINTS)


def _build_rules_basis_lines() -> list[str]:
    lines = []
    for item in BUSINESS_RULE_BASIS:
        lines.append(f"- {item['rule']}（版本: {item['version']}，来源: {item['source']}）")
    return lines


def _ensure_structured_answer(
    question: str,
    answer: str,
    docs: list[dict[str, Any]],
    tool_records: list[dict[str, Any]],
) -> str:
    demand = _safe_text(question)
    final_answer = _clip(answer, 2500)
    citations = _build_citation_lines(docs, limit=4)
    rules = _build_rules_basis_lines()

    tool_lines: list[str] = []
    for rec in tool_records:
        tool_lines.append(f"- {rec.get('tool', '')}: {rec.get('explain', '')}")
    if not tool_lines:
        tool_lines.append("- No tool call was triggered in this turn; answer is based on retrieval and context.")

    if AGENT_REQUIRE_TRACE_SOURCE and _requires_trace(question) and not citations:
        citations = ['- No traceable citation found; current answer is for reference only.']

    intro = f"I understand your current focus is: {demand}."
    method = (
        "Analysis approach: determine whether business data tools are required, then synthesize a traceable answer. "
        f"Data analysis needed: {'yes' if _looks_like_data_question(question) else 'no'}; "
        f"standards trace needed: {'yes' if _requires_trace(question) else 'no'}."
    )
    basis = "Standards and evidence:\n" + "\n".join(rules + citations)
    tools = "Tools and data used:\n" + "\n".join(tool_lines)
    result = "Results and recommendations:\n" + final_answer

    return "\n\n".join([intro, method, basis, tools, result])


def _audit_log_path(session_id: str) -> Path:
    folder = settings.data_dir / "agent_audit_logs"
    folder.mkdir(parents=True, exist_ok=True)
    safe_session = re.sub(r"[^a-zA-Z0-9_\-]", "_", _safe_text(session_id) or "default")
    return folder / f"{safe_session}.jsonl"


def _append_audit_log(session_id: str, payload: dict[str, Any]) -> None:
    if not AGENT_AUDIT_LOG_ENABLED:
        return
    try:
        record = {"ts": datetime.utcnow().isoformat(), **payload}
        with _audit_log_path(session_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("append agent audit log failed: %s", exc)


def _build_user_content(
    question: str,
    project_id: int | None,
    docs: list[dict[str, Any]],
    history_messages: list[dict[str, str]] | None,
    long_term_memories: list[dict[str, Any]] | None = None,
    interpretive_mode: bool = False,
) -> str:
    context_parts = []
    for i, doc in enumerate(docs, 1):
        meta = doc.get("metadata") or {}
        source = meta.get("source_file", "未知来源")
        section = meta.get("section", "main")
        page = meta.get("page", "-")
        context_parts.append(
            f"[文档{i}] 来源:{source} 章节:{section} 页码:{page}\n{_clip(doc.get('content', ''), 600)}"
        )
    context_text = "\n\n".join(context_parts) if context_parts else "（未检索到相关文档）"

    last_turn_hint = ""
    if history_messages:
        tail = history_messages[-2:]
        if tail:
            rendered = []
            for m in tail:
                role = "用户" if m.get("role") == "user" else "助手"
                rendered.append(f"{role}: {_clip(m.get('content', ''), 220)}")
            last_turn_hint = "\n最近对话上下文：\n" + "\n".join(rendered)

    project_hint = ""
    if project_id is not None and not interpretive_mode:
        project_hint = (
            f"\n当前关联项目ID: {project_id}。"
            "如用户要求继续拆分/明细，优先调用 get_emission_breakdown。"
        )

    long_memory_hint = ""
    if long_term_memories:
        long_text = render_long_term_memory_context(long_term_memories)
        if long_text:
            long_memory_hint = (
                "\n长期记忆（跨会话语义召回，仅作为参考，必须结合当前工具真实数据）：\n"
                f"{_clip(long_text, 1200)}"
            )

    mode_hint = ""
    if interpretive_mode:
        mode_hint = (
            "\n当前问题属于行业解读/常识咨询场景："
            "请直接基于双碳行业知识给出专业解读，"
            "不要输出项目台账数据、总量、占比、Scope分项，也不要调用工具。"
        )

    return (
        f"用户问题：{question}\n\n"
        f"参考知识：\n{context_text}{project_hint}{last_turn_hint}{long_memory_hint}{mode_hint}\n\n"
        "???????????????????????????????????????"
    )


def _call_llm(messages: list[dict[str, str]], history_messages: list[dict[str, str]] | None = None) -> str:
    merged = []
    if history_messages:
        merged.extend(history_messages[-10:])
    merged.extend(messages)
    return chat_messages(messages=merged, task="agent", contains_sensitive=False)


def _collect_references(docs: list[dict[str, Any]], all_tool_results: list[dict[str, Any]]) -> list[str]:
    references: list[str] = []
    for doc in docs:
        c = _citation_from_doc(doc, 0)
        ref = f"{c['source']}|section={c['section']}|page={c['page']}"
        if ref not in references:
            references.append(ref)
    for tr in all_tool_results:
        ref = f"业务数据查询: {tr.get('tool', '')}"
        if ref not in references:
            references.append(ref)
    for item in BUSINESS_RULE_BASIS:
        rule_ref = f"规则白盒: {item['version']} / {item['source']}"
        if rule_ref not in references:
            references.append(rule_ref)
    return references


def _extract_latest_tool_result(all_tool_results: list[dict[str, Any]], tool_name: str) -> dict[str, Any] | None:
    for tr in reversed(all_tool_results):
        if tr.get("tool") == tool_name:
            result = tr.get("result")
            if isinstance(result, dict) and not result.get("error"):
                return result
    return None


def _build_chart_from_breakdown(
    breakdown: dict[str, Any],
    chart_type: str = "pie",
) -> dict[str, Any] | None:
    if not isinstance(breakdown, dict) or breakdown.get("error"):
        return None
    items = breakdown.get("items")
    if not isinstance(items, list) or not items:
        return None

    total = float(breakdown.get("total_emission", 0) or 0.0)
    group_by = str(breakdown.get("group_by", "source") or "source")
    project_name = str(breakdown.get("project_name", "当前项目") or "当前项目")

    chart_items: list[dict[str, Any]] = []
    used_value = 0.0
    for item in items:
        if not isinstance(item, dict):
            continue
        value = float(item.get("co2e", 0) or 0.0)
        used_value += value
        row = {
            "name": str(item.get("name", "未命名项")),
            "value": round(value, 4),
            "percentage": float(item.get("pct", 0) or 0.0),
        }
        if "scope" in item:
            row["scope"] = item.get("scope")
        if "category" in item:
            row["category"] = item.get("category")
        chart_items.append(row)

    remain = max(total - used_value, 0.0)
    if remain > 0.0001:
        remain_pct = round((remain / total * 100.0), 2) if total > 0 else 0.0
        chart_items.append({"name": "其他", "value": round(remain, 4), "percentage": remain_pct})

    title_map = {
        "pie": f"{project_name}排放占比",
        "bar": f"{project_name}排放源对比",
        "line": f"{project_name}排放变化趋势",
    }

    normalized_type = chart_type if chart_type in {"pie", "bar", "line"} else "pie"
    return {
        "type": normalized_type,
        "chart_type": normalized_type,
        "title": title_map.get(normalized_type, f"{project_name}排放占比"),
        "group_by": group_by,
        "unit": "tCO2e",
        "total_emission": round(total, 4),
        "items": chart_items,
    }


def _extract_chart_data_from_tool_results(
    all_tool_results: list[dict[str, Any]],
    chart_type: str,
) -> dict[str, Any] | None:
    breakdown = _extract_latest_tool_result(all_tool_results, "get_emission_breakdown")
    if breakdown is None:
        # Fallback: try NL2SQL rows -> chart items
        nl2sql = _extract_latest_tool_result(all_tool_results, "query_by_nl2sql")
        if isinstance(nl2sql, dict):
            rows = nl2sql.get("rows")
            if isinstance(rows, list) and rows:
                chart_items: list[dict[str, Any]] = []
                for row in rows[:12]:
                    if not isinstance(row, dict):
                        continue
                    # pick first string-like dim and first numeric metric
                    dim_name = None
                    dim_val = None
                    metric_val = None
                    for k, v in row.items():
                        if dim_name is None and isinstance(v, (str, int)):
                            dim_name = str(k)
                            dim_val = str(v)
                        if metric_val is None:
                            try:
                                fv = float(v)  # type: ignore[arg-type]
                                if fv == fv:  # not NaN
                                    metric_val = fv
                            except Exception:
                                pass
                    if dim_val is None or metric_val is None:
                        continue
                    chart_items.append({"name": dim_val, "value": round(metric_val, 4), "source_field": dim_name})
                if chart_items:
                    return {
                        "type": chart_type if chart_type in {"pie", "bar", "line"} else "bar",
                        "chart_type": chart_type if chart_type in {"pie", "bar", "line"} else "bar",
                        "unit": "",
                        "items": chart_items,
                        "source": "query_by_nl2sql",
                    }
        return None
    return _build_chart_from_breakdown(breakdown, chart_type=chart_type)


def _ensure_chart_data(
    question: str,
    project_id: int | None,
    db: Session,
    all_tool_results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    chart_type = _detect_chart_type(question)
    if chart_type is None:
        return None

    chart = _extract_chart_data_from_tool_results(all_tool_results, chart_type=chart_type)
    if chart is not None:
        return chart
    if project_id is None:
        return None

    tool_args = {"project_id": project_id, "group_by": "source", "top_n": 10}
    result = execute_tool_call(db, DEFAULT_TOOL_REGISTRY, "get_emission_breakdown", tool_args)
    all_tool_results.append(
        {
            "tool": "get_emission_breakdown",
            "result": result,
            "arguments": tool_args,
            "explain": _tool_call_reason("get_emission_breakdown", question, tool_args),
        }
    )
    return _build_chart_from_breakdown(result, chart_type=chart_type)


def build_emission_analysis_report(data: dict[str, Any], chart_type: str) -> str:
    if not isinstance(data, dict):
        return ""
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return ""

    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "未命名项"))
        value = float(item.get("value", item.get("co2e", 0)) or 0.0)
        pct = float(item.get("percentage", item.get("pct", 0)) or 0.0)
        rows.append({"name": name, "value": value, "pct": pct})
    if not rows:
        return ""

    rows.sort(key=lambda x: x["value"], reverse=True)
    top = rows[:3]
    unit = str(data.get("unit", "tCO2e") or "tCO2e")

    if chart_type == "pie":
        top1 = top[0]
        key_lines = [
            f"- {r['name']}：{round(r['value'], 4)} {unit}（占比 {round(r['pct'], 2)}%）"
            for r in top
        ]
        return (
            f"核心结论：{top1['name']}为最大排放源，占比约{round(top1['pct'], 2)}%，应优先治理。\n"
            "关键发现：\n"
            + "\n".join(key_lines)
            + "\n初步建议：优先针对前两大排放源制定减排措施（设备替换、能效优化与运行管控），"
              "再逐步覆盖长尾排放项。"
        )

    if chart_type == "bar":
        highest = top[0]
        lowest = rows[-1]
        gap = max(highest["value"] - lowest["value"], 0.0)
        key_lines = [
            f"- 最高项：{highest['name']}（{round(highest['value'], 4)} {unit}）",
            f"- 最低项：{lowest['name']}（{round(lowest['value'], 4)} {unit}）",
            f"- 高低差：{round(gap, 4)} {unit}",
        ]
        return (
            f"核心结论：排放项差异明显，{highest['name']}显著高于其他项，是治理优先级最高对象。\n"
            "关键发现：\n"
            + "\n".join(key_lines)
            + "\n初步建议：先聚焦高排放项开展专项治理，并对中低排放项采用标准化管控，"
              "以提升整体减排效率。"
        )

    if chart_type == "line":
        # 当前数据多为分项序列，按顺序做趋势近似解读。
        first = rows[0]
        last = rows[-1]
        trend = "下降" if first["value"] > last["value"] else "上升"
        key_lines = [
            f"- 起点：{first['name']}（{round(first['value'], 4)} {unit}）",
            f"- 终点：{last['name']}（{round(last['value'], 4)} {unit}）",
            f"- 整体趋势：{trend}",
        ]
        return (
            f"核心结论：当前序列呈{trend}趋势，存在重点波动节点需重点关注。\n"
            "关键发现：\n"
            + "\n".join(key_lines)
            + "\n初步建议：对波动较大的节点回溯活动数据与排放因子口径，"
              "优先定位异常增幅来源并制定分阶段压降方案。"
        )
    return ""


def _build_analysis_from_tool_results(
    all_tool_results: list[dict[str, Any]],
    chart: dict[str, Any] | None,
) -> str:
    if not isinstance(chart, dict):
        return ""
    chart_type = str(chart.get("type") or chart.get("chart_type") or "pie")
    if chart.get("items"):
        return build_emission_analysis_report(chart, chart_type)

    breakdown = _extract_latest_tool_result(all_tool_results, "get_emission_breakdown")
    if isinstance(breakdown, dict):
        return build_emission_analysis_report(breakdown, chart_type)
    summary = _extract_latest_tool_result(all_tool_results, "get_emission_summary")
    if isinstance(summary, dict):
        return build_emission_analysis_report(summary, chart_type)
    return ""


def _append_analysis_into_answer(answer: str, report: str) -> str:
    text = (answer or "").strip()
    r = (report or "").strip()
    if not text or not r:
        return text
    if "核心结论：" in text and "关键发现：" in text and "初步建议：" in text:
        return text
    return text + "\n\n" + r


def _fallback_from_tool_results(all_tool_results: list[dict[str, Any]]) -> str | None:
    breakdown = _extract_latest_tool_result(all_tool_results, "get_emission_breakdown")
    if breakdown is not None:
        return format_emission_breakdown_answer(breakdown)
    summary = _extract_latest_tool_result(all_tool_results, "get_emission_summary")
    if summary is not None:
        return format_emission_summary_answer(summary)
    return None


def _needs_retry_analysis(answer: str, has_tool_data: bool) -> bool:
    if not has_tool_data:
        return False
    text = (answer or "").strip()
    if not text:
        return True
    weak_cues = ["没有提供具体", "无法直接", "基于通用知识", "示例", "请提供更多信息", "用户现在需要", "现在组织内容"]
    if any(cue in text for cue in weak_cues):
        return True
    if text.lower().startswith("tool:"):
        return True
    if re.search(r"\d", text) is None:
        return True
    return False


def _build_blocked_answer(reason: str) -> str:
    return (
        "This request was blocked by safety guardrails.\n\n"
        "Allowed scope: read-only business query and controlled carbon accounting operations.\n"
        f"Risk reason: {reason}\n\n"
        "Please rephrase as a clear carbon-business query (e.g., emission accounting, structure analysis, standards interpretation)."
    )


def _build_agent_answer(
    question: str,
    session_id: str,
    project_id: int | None,
    db: Session,
    history_messages: list[dict[str, str]] | None = None,
) -> tuple[str, list[str], dict[str, Any] | None]:
    from app.services.vector_store import similarity_search_all

    is_interpretive = _is_interpretive_question(question)
    interpretive_mode = bool(is_interpretive)
    print(f"is_interpretive_question: {is_interpretive}")
    print(f"interpretive_mode: {interpretive_mode}")
    logger.info("is_interpretive_question=%s interpretive_mode=%s question=%s", is_interpretive, interpretive_mode, _clip(question, 200))

    risk_reason = _input_risk_reason(question)
    if risk_reason:
        blocked = _build_blocked_answer(risk_reason)
        _append_audit_log(
            session_id,
            {
                "event": "input_blocked",
                "question": _clip(question),
                "reason": risk_reason,
            },
        )
        return blocked, [f"安全拦截: {risk_reason}"], None

    docs = similarity_search_all(question, k=3)
    if project_id is not None and _looks_like_data_question(question):
        filtered_docs: list[dict[str, Any]] = []
        for doc in docs:
            meta = doc.get("metadata") or {}
            source = _safe_text(meta.get("source_file")).lower()
            if "industry_news" in source or "news" in source:
                continue
            filtered_docs.append(doc)
        docs = filtered_docs
    long_term_memories = recall_long_term_memories(question=question, project_id=project_id, top_k=6)
    user_content = _build_user_content(
        question,
        project_id,
        docs,
        history_messages,
        long_term_memories=long_term_memories,
        interpretive_mode=interpretive_mode,
    )

    messages = [
        {
            "role": "system",
            "content": (
                AGENT_SYSTEM_PROMPT
                + "\n\n"
                + EXPLAINABLE_POLICY_PROMPT
                + (
                    "\n\n补充要求：若当前问题属于行业解读/常识咨询，禁止调用业务数据工具，"
                      "禁止引用项目台账数值，直接给出行业通用解读。"
                    if interpretive_mode
                    else ""
                )
            ),
        },
        {"role": "user", "content": user_content},
    ]

    max_iterations = 5
    nudged_once = False
    analysis_retry_once = False
    breakdown_auto_once = False
    summary_auto_once = False
    all_tool_results: list[dict[str, Any]] = []
    response_text = ""
    decision_nodes: list[dict[str, Any]] = []

    for step in range(max_iterations):
        response_text = _call_llm(messages, history_messages)
        tool_calls = parse_tool_calls(response_text)
        if interpretive_mode and tool_calls:
            # Interpretive questions must not execute tools or reuse project ledger output.
            tool_calls = []
        decision_nodes.append(
            {
                "step": step + 1,
                "tool_calls": tool_calls,
                "model_output_preview": _clip(response_text, 400),
            }
        )

        if not tool_calls:
            has_tool_data = len(all_tool_results) > 0
            chart_requested = _detect_chart_type(question) is not None
            need_breakdown = (
                project_id is not None
                and _is_breakdown_intent(question)
                and not interpretive_mode
                and _extract_latest_tool_result(all_tool_results, "get_emission_breakdown") is None
            )
            if (
                project_id is not None
                and chart_requested
                and not interpretive_mode
                and _extract_latest_tool_result(all_tool_results, "get_emission_breakdown") is None
            ):
                need_breakdown = True
            need_summary = (
                project_id is not None
                and _looks_like_data_question(question)
                and not interpretive_mode
                and _extract_latest_tool_result(all_tool_results, "get_emission_summary") is None
            )

            if (
                project_id is not None
                and (_looks_like_data_question(question) or _looks_like_followup(question))
                and not interpretive_mode
                and not nudged_once
                and not has_tool_data
            ):
                nudged_once = True
                messages.append({"role": "assistant", "content": response_text})
                messages.append(
                    {
                        "role": "user",
                        "content": "该问题需要基于真实项目数据回答。请先调用工具（优先 get_emission_breakdown），再给出结论。",
                    }
                )
                continue

            if need_breakdown and not breakdown_auto_once:
                breakdown_auto_once = True
                tool_args = {"project_id": project_id, "group_by": "source", "top_n": 10}
                breakdown = execute_tool_call(db, DEFAULT_TOOL_REGISTRY, "get_emission_breakdown", tool_args)
                all_tool_results.append(
                    {
                        "tool": "get_emission_breakdown",
                        "result": breakdown,
                        "arguments": tool_args,
                        "explain": _tool_call_reason("get_emission_breakdown", question, tool_args),
                    }
                )
                messages.append({"role": "assistant", "content": response_text})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "系统已补充执行 get_emission_breakdown，结果如下：\n"
                            f"{json.dumps(breakdown, ensure_ascii=False, indent=2)}\n\n"
                            "请基于该结果输出最终分析，结构必须是：\n"
                            "??????????????????????????????????????????"
                        ),
                    }
                )
                continue

            if need_summary and not summary_auto_once and not need_breakdown:
                summary_auto_once = True
                tool_args = {"project_id": project_id}
                summary = execute_tool_call(db, DEFAULT_TOOL_REGISTRY, "get_emission_summary", tool_args)
                all_tool_results.append(
                    {
                        "tool": "get_emission_summary",
                        "result": summary,
                        "arguments": tool_args,
                        "explain": _tool_call_reason("get_emission_summary", question, tool_args),
                    }
                )
                messages.append({"role": "assistant", "content": response_text})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "System auto-executed get_emission_summary because this is a business data query. "
                            "Use this tool result as mandatory evidence and provide the final structured answer.\n"
                            f"{json.dumps(summary, ensure_ascii=False, indent=2)}"
                        ),
                    }
                )
                continue

            if _needs_retry_analysis(response_text, has_tool_data) and not analysis_retry_once:
                analysis_retry_once = True
                tool_snapshot = json.dumps([tr.get("result") for tr in all_tool_results], ensure_ascii=False, indent=2)
                messages.append({"role": "assistant", "content": response_text})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "请严格基于以下工具结果重新输出，禁止编造：\n"
                            f"{tool_snapshot}\n\n"
                            "???????????????????????????????????????"
                        ),
                    }
                )
                continue

            if _needs_retry_analysis(response_text, has_tool_data) and analysis_retry_once:
                fallback = _fallback_from_tool_results(all_tool_results)
                if fallback:
                    chart = _ensure_chart_data(question, project_id, db, all_tool_results)
                    analysis = _build_analysis_from_tool_results(all_tool_results, chart)
                    final_answer = _append_analysis_into_answer(
                        _ensure_structured_answer(question, fallback, docs, all_tool_results),
                        analysis,
                    )
                    _append_audit_log(
                        session_id,
                        {
                            "event": "final_with_fallback",
                            "question": _clip(question),
                            "decision_nodes": decision_nodes,
                            "tool_records": all_tool_results,
                            "references": _collect_references(docs, all_tool_results),
                        },
                    )
                    return final_answer, _collect_references(docs, all_tool_results), chart

            chart = None if interpretive_mode else _ensure_chart_data(question, project_id, db, all_tool_results)
            if (
                not interpretive_mode
                and _is_chart_only_request(question)
                and chart is None
                and not _has_usable_chart_source(all_tool_results)
            ):
                tip = _build_chart_data_missing_prompt()
                _append_audit_log(
                    session_id,
                    {
                        "event": "chart_missing_data_prompt",
                        "question": _clip(question),
                        "tool_records": all_tool_results,
                    },
                )
                return tip, _collect_references(docs, all_tool_results), None
            analysis = _build_analysis_from_tool_results(all_tool_results, chart)
            final_answer = _append_analysis_into_answer(
                _ensure_structured_answer(question, response_text, docs, all_tool_results),
                analysis,
            )
            _append_audit_log(
                session_id,
                {
                    "event": "final",
                    "question": _clip(question),
                    "decision_nodes": decision_nodes,
                    "tool_records": all_tool_results,
                    "references": _collect_references(docs, all_tool_results),
                },
            )
            return final_answer, _collect_references(docs, ([] if interpretive_mode else all_tool_results)), chart

        tool_results_text = ""
        for tc in tool_calls:
            tool_name = _safe_text(tc.get("name"))
            arguments = tc.get("arguments", {})
            safe_args = _sanitize_tool_arguments(tool_name, arguments if isinstance(arguments, dict) else {}, project_id)
            if safe_args.get("_blocked"):
                result = {"error": safe_args.get("_error", "工具参数被安全策略拦截")}
                explain = f"原因: 安全拦截；用途: 阻断危险调用；核心入参: {json.dumps(arguments, ensure_ascii=False)}"
            else:
                result = execute_tool_call(db, DEFAULT_TOOL_REGISTRY, tool_name, safe_args)
                explain = _tool_call_reason(tool_name, question, safe_args)

            record = {"tool": tool_name, "result": result, "arguments": safe_args, "explain": explain}
            all_tool_results.append(record)
            tool_results_text += (
                f"\n工具 {tool_name}\n"
                f"- 调用说明: {explain}\n"
                f"- 返回结果: {json.dumps(result, ensure_ascii=False, indent=2)}\n"
            )

        messages.append({"role": "assistant", "content": response_text})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"工具执行结果如下：\n{tool_results_text}\n\n"
                    "??????????????????????????????????????"
                    "涉及标准和核算结论必须附文档来源、章节、页码、原文片段。"
                ),
            }
        )

    fallback = None if interpretive_mode else _fallback_from_tool_results(all_tool_results)
    if fallback:
        chart = _ensure_chart_data(question, project_id, db, all_tool_results)
        analysis = _build_analysis_from_tool_results(all_tool_results, chart)
        structured = _append_analysis_into_answer(
            _ensure_structured_answer(question, fallback, docs, all_tool_results),
            analysis,
        )
        _append_audit_log(
            session_id,
            {
                "event": "final_after_max_iterations",
                "question": _clip(question),
                "decision_nodes": decision_nodes,
                "tool_records": all_tool_results,
                "references": _collect_references(docs, all_tool_results),
            },
        )
        return structured, _collect_references(docs, all_tool_results), chart

    chart = _ensure_chart_data(question, project_id, db, all_tool_results)
    if (
        not interpretive_mode
        and _is_chart_only_request(question)
        and chart is None
        and not _has_usable_chart_source(all_tool_results)
    ):
        tip = _build_chart_data_missing_prompt()
        _append_audit_log(
            session_id,
            {
                "event": "chart_missing_data_prompt_after_max_iterations",
                "question": _clip(question),
                "tool_records": all_tool_results,
            },
        )
        return tip, _collect_references(docs, all_tool_results), None
    analysis = _build_analysis_from_tool_results(all_tool_results, chart)
    structured = _append_analysis_into_answer(
        _ensure_structured_answer(question, response_text, docs, all_tool_results),
        analysis,
    )
    _append_audit_log(
        session_id,
        {
            "event": "final_after_max_iterations_no_fallback",
            "question": _clip(question),
            "decision_nodes": decision_nodes,
            "tool_records": all_tool_results,
            "references": _collect_references(docs, all_tool_results),
        },
    )
    return structured, _collect_references(docs, all_tool_results), chart


def ask_with_agent(
    question: str,
    session_id: str,
    project_id: int | None = None,
    db: Session | None = None,
    history_messages: list[dict[str, str]] | None = None,
) -> tuple[str, list[str], dict[str, Any] | None]:
    try:
        answer, references, chart = _build_agent_answer(question, session_id, project_id, db, history_messages)
        return present_user_answer(answer, "agent"), references, chart
    except Exception as exc:
        logger.error("Agent mode failed, fallback: %s", exc)
        _append_audit_log(
            session_id,
            {
                "event": "agent_exception",
                "question": _clip(question),
                "error": _clip(str(exc), 500),
            },
        )
        if (
            db is not None
            and project_id is not None
            and (_looks_like_data_question(question) or _looks_like_followup(question))
            and not _is_interpretive_question(question)
        ):
            try:
                breakdown = execute_tool_call(
                    db,
                    DEFAULT_TOOL_REGISTRY,
                    "get_emission_breakdown",
                    {"project_id": project_id, "group_by": "source", "top_n": 10},
                )
                if not breakdown.get("error"):
                    fallback_text = format_emission_breakdown_answer(breakdown)
                    answer = _ensure_structured_answer(
                        question,
                        fallback_text,
                        docs=[],
                        tool_records=[
                            {
                                "tool": "get_emission_breakdown",
                                "result": breakdown,
                                "arguments": {"project_id": project_id, "group_by": "source", "top_n": 10},
                                "explain": "原因: 异常兜底；用途: 保证输出可用；核心入参: project_id/group_by/top_n",
                            }
                        ],
                    )
                    return (
                        present_user_answer(answer, "agent"),
                        ["业务数据查询: get_emission_breakdown（异常兜底）"],
                        _build_chart_from_breakdown(
                            breakdown,
                            chart_type=_detect_chart_type(question) or "pie",
                        ),
                    )
            except Exception as fallback_exc:
                logger.error("Agent breakdown fallback failed: %s", fallback_exc)
        if FALLBACK_ENABLED and db is not None:
            answer = _ensure_structured_answer(
                question,
                "当前智能体执行链路出现异常，且未获取到可用项目工具结果。请稍后重试，或提供明确项目ID后重试。",
                docs=[],
                tool_records=[],
            )
            return present_user_answer(answer, "agent"), ["智能体链路异常（未触发预设规则降级）"], None
        raise

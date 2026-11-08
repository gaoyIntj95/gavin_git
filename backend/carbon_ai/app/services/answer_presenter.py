from __future__ import annotations

import json
import re


INTERNAL_SECTION_HEADERS = (
    "需求拆解",
    "条件判定",
    "规则依据",
    "工具选择",
    "参考来源",
)
INTERNAL_LINE_KEYWORDS = (
    "用户诉求",
    "目标",
    "是否涉及",
    "版本:",
    "来源:",
    "我现在需要处理",
    "首先回顾",
    "接下来",
    "不过，",
)
INTERNAL_SECTION_PATTERN = re.compile(
    r"(需求拆解|条件判定|规则依据|工具选择|参考来源|本轮未触发工具调用|规则白盒)",
    re.IGNORECASE,
)
SUMMARY_MARKER_PATTERN = re.compile(
    r"(?m)^\s*(?:\*{0,2}\s*)?(?:结果汇总|【回答】|回答|结论)(?:\s*\*{0,2})?\s*[:：]\s*",
    re.IGNORECASE,
)
NOISY_ENUM_SECTION_PATTERN = re.compile(
    r"^\s*\d+[\.\、]\s*(需求拆解|条件判定|规则依据|工具选择|结果汇总)\s*[:：]?\s*$"
)
DECISION_BLOCK_SPLITTER = "\n\n---\n\n"


def _strip_code_fences(text: str) -> str:
    s = text or ""
    s = re.sub(r"```[a-zA-Z0-9_-]*\s*", "", s)
    s = s.replace("```", "")
    return s


def _looks_already_presented(text: str) -> bool:
    s = text or ""
    return ("决策简述" in s) and ("正式回答" in s)


def _looks_user_ready_natural_answer(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    # Unified react/news answers and polished markdown-like answers should not be
    # re-wrapped into rigid "决策简述/正式回答" templates.
    if "资讯速览：" in s:
        return True
    if "简要分析：" in s:
        return True
    if re.search(r"\[[^\]]+\]\(https?://", s):
        return True
    # Already structured in natural sections.
    if ("来源" in s or "参考来源" in s) and len(s.splitlines()) >= 4:
        return True
    return False


def _dedupe_presented_blocks(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return s
    # Normalize accidental separators.
    s = re.sub(r"\n-{2,}\n", "\n---\n", s)
    if not _looks_already_presented(s):
        return s
    # If repeated, keep the last complete presented block.
    last_decision = s.rfind("决策简述")
    if last_decision > 0:
        tail = s[last_decision:].strip()
        if "正式回答" in tail:
            return tail
    return s


def _extract_after_summary_marker(text: str) -> str:
    s = text or ""
    matches = list(SUMMARY_MARKER_PATTERN.finditer(s))
    if not matches:
        return s
    # Use the last summary marker to avoid keeping previous analysis blocks.
    return s[matches[-1].end() :]


def _try_extract_from_json(text: str) -> str | None:
    s = (text or "").strip()
    if not s or "{" not in s or "}" not in s:
        return None
    # Try to isolate a JSON object region.
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = s[start : end + 1]
    try:
        data = json.loads(candidate)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    for key in ("结果汇总", "结论", "回答"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _drop_internal_lines(text: str) -> str:
    lines = (text or "").splitlines()
    kept: list[str] = []
    for line in lines:
        t = line.strip()
        if not t:
            kept.append("")
            continue
        if any(t.startswith(f"{h}:") or t.startswith(f"{h}：") for h in INTERNAL_SECTION_HEADERS):
            continue
        if t in INTERNAL_SECTION_HEADERS:
            continue
        if re.search(r"^\d+[\.\、]\s*(需求拆解|条件判定|规则依据|工具选择|参考来源|结果汇总)\s*[:：]?$", t):
            continue
        if re.search(r"^\d+[\.\、]\s*(需求拆解|条件判定|规则依据|工具选择|参考来源|结果汇总)\s*[:：].*$", t):
            continue
        if re.search(r"^(?:\*{0,2}\s*)?(需求拆解|条件判定|规则依据|工具选择|参考来源|结果汇总)(?:\s*\*{0,2})\s*[:：].*$", t):
            continue
        if NOISY_ENUM_SECTION_PATTERN.search(t):
            continue
        if "章节:" in t and "页码:" in t and "片段:" in t:
            continue
        if t.startswith("规则白盒:"):
            continue
        if t.startswith("tool:"):
            continue
        if t.startswith("参考来源:"):
            continue
        if any(k in t for k in INTERNAL_LINE_KEYWORDS):
            continue
        if re.search(r"^(我现在需要处理|首先回顾|接下来|先分析|然后|最后|不过，|因此需要)\b", t):
            continue
        if "需求拆解" in t or "条件判定" in t:
            continue
        if t.startswith("{") or t.endswith("}") or t.startswith("\""):
            # Drop likely JSON fragment lines from half-structured outputs.
            continue
        kept.append(line)
    # Collapse excessive empty lines.
    s = "\n".join(kept)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def _extract_demand_summary(raw: str, cleaned_summary: str) -> str:
    for pattern in (
        r"用户诉求\s*[:：]\s*(.+)",
        r"需求简述\s*[:：]\s*(.+)",
        r"用户(?:想|要|希望)(.+)",
    ):
        m = re.search(pattern, raw)
        if m:
            text = m.group(1).strip()
            if text:
                return text

    first_line = ""
    for line in cleaned_summary.splitlines():
        t = line.strip().lstrip("-* ")
        if re.match(r"^\d+[\.\、]\s*(总览|分项|结论|建议)\s*$", t):
            continue
        if t:
            first_line = t
            break
    if not first_line:
        return "用户希望获取当前问题的业务结论。"
    if len(first_line) > 40:
        first_line = first_line[:40] + "..."
    return first_line


def _has_business_data_need(text: str, demand: str = "") -> bool:
    t = ((text or "") + "\n" + (demand or "")).lower()
    if ("可直接回复：" in text) or ("为了准确落到你的业务场景" in text):
        return True
    interpretive_hints = (
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
    )
    explicit_data_hints = (
        "项目1",
        "项目 1",
        "project id",
        "总排放",
        "总量",
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
    )
    if any(k in t for k in interpretive_hints) and not any(k in t for k in explicit_data_hints):
        return False
    pure_knowledge_hints = ("是什么", "定义", "区别", "概念", "含义", "scope 1", "scope1")
    pure_knowledge = any(k in t for k in pure_knowledge_hints)
    explicit_business = any(
        k in t
        for k in ("项目", "企业", "台账", "业务数据", "project", "company", "ledger")
    )
    if pure_knowledge and not explicit_business:
        return False
    keys = (
        "项目",
        "企业",
        "台账",
        "排放",
        "核算",
        "统计",
        "总量",
        "占比",
        "明细",
        "业务数据",
        "project",
        "emission",
        "summary",
        "breakdown",
    )
    return any(k in t for k in keys)


def _is_interpretive_mode(text: str, demand: str = "") -> bool:
    t = ((text or "") + "\n" + (demand or "")).lower()
    interpretive_hints = (
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
    )
    explicit_data_hints = (
        "项目1",
        "项目 1",
        "project id",
        "总排放",
        "总量",
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
    )
    return any(k in t for k in interpretive_hints) and not any(k in t for k in explicit_data_hints)


def _has_tool_need(text: str) -> bool:
    t = text or ""
    if ("可直接回复：" in t) or ("为了准确落到你的业务场景" in t):
        return True
    if "必须调用工具" in t or "需调用工具" in t or "需要调用工具" in t:
        return True
    if "工具输出优先" in t:
        return True
    if "业务数据查询" in t:
        return True
    if "本轮未触发工具调用" in t:
        return True
    return False


def _extract_compliance_basis(raw: str) -> str:
    rules: list[str] = []
    in_rule = False
    for line in raw.splitlines():
        t = line.strip()
        if not t:
            if in_rule and rules:
                break
            continue
        if t.startswith("规则依据"):
            in_rule = True
            continue
        if in_rule:
            if t.startswith("工具选择") or t.startswith("参考来源") or t.startswith("结果汇总"):
                break
            if "片段:" in t or "章节:" in t:
                continue
            t = re.sub(r"[（(].*?(版本|来源|v\d+\.\d+).*?[)）]", "", t).strip()
            t = t.lstrip("-* ").strip()
            if t and t not in rules:
                rules.append(t)
            if len(rules) >= 2:
                break

    if not rules:
        return "遵循双碳核算通用原则，优先使用可追溯业务数据并给出可解释结论。"
    return "；".join(rules)


def _detect_chart_intent(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ("柱状图", "条形图", "对比图", "bar chart", "bar")):
        return "bar"
    if any(k in t for k in ("折线图", "趋势图", "变化曲线", "line chart", "line")):
        return "line"
    if any(k in t for k in ("饼图", "饼状图", "占比图", "环形图", "pie chart", "pie")):
        return "pie"
    return ""


def _build_expert_reasoning(
    demand: str,
    raw: str,
    formal_evidence: str,
    need_data: bool,
    interpretive_mode: bool = False,
) -> str:
    chart_kind = _detect_chart_intent((raw or "") + "\n" + (demand or ""))
    has_rank = bool(_extract_rank_lines(formal_evidence, limit=1))
    has_total = bool(_extract_total_line(formal_evidence))

    if interpretive_mode:
        return (
            "你关注的是这些排放源背后的企业类型与业态特征。"
            "我会从生产活动、能源使用方式和常见设备场景三个维度来判断其典型分布，"
            "再给出可用于业务沟通的行业解读。"
        )

    if chart_kind == "bar":
        if has_rank:
            return (
                "你关注的是排放项之间的差异对比。基于当前明细，我会先锁定高排放项与低排放项，"
                "再结合差值和占比判断治理优先级，确保结论既直观又可执行。"
            )
        return (
            "你希望看清排放项之间的高低差异。我会先建立对比口径，再按同一单位呈现各项差距，"
            "最后提炼出最值得优先治理的重点项。"
        )
    if chart_kind == "line":
        return (
            "你更关心排放变化的走势。我会围绕关键节点观察升降幅度与波动区间，"
            "再把变化最明显的阶段提炼出来，形成可落地的管理建议。"
        )
    if chart_kind == "pie":
        return (
            "你希望快速识别排放结构中的主导项。我会先看整体占比分布，再定位贡献最高的前几项，"
            "据此给出治理优先顺序。"
        )
    if need_data and (has_rank or has_total):
        return (
            "这个问题的核心是把业务数据转成可执行结论。我会先明确总量与结构，再识别贡献最大的排放来源，"
            "最后给出分层治理建议。"
        )
    if need_data:
        return (
            "你的问题聚焦在业务层面的定量判断。我会先统一核算口径，再结合可追溯数据形成结论，"
            "保证回答既专业又便于直接使用。"
        )
    return (
        "你的问题属于标准与方法理解场景。我会先给出清晰定义，再补充适用边界与实践要点，"
        "让结论可以直接用于业务沟通。"
    )


def _build_answer_mode_line(need_data: bool, formal_evidence: str) -> str:
    has_data_signal = bool(_extract_rank_lines(formal_evidence, limit=1) or _extract_total_line(formal_evidence))
    if need_data and has_data_signal:
        return "回答方式：基于当前项目数据给出定量结论。"
    if need_data:
        return "回答方式：围绕业务口径组织结论，并保持可追溯。"
    return "回答方式：以规则与方法解释为主，强调可落地理解。"


def _strip_residual_reasoning(summary: str) -> str:
    lines = summary.splitlines()
    kept: list[str] = []
    for line in lines:
        t = line.strip()
        if not t:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        if NOISY_ENUM_SECTION_PATTERN.search(t):
            continue
        if re.match(r"^\d+[\.\、]\s*", t) and any(k in t for k in ("需求拆解", "条件判定", "规则依据", "工具选择")):
            continue
        if "强制决策规则" in t or "工具选型指引" in t:
            continue
        if re.search(r"(我现在需要处理|首先回顾|接下来|不过，|先分析|然后|最后)", t):
            continue
        kept.append(t)
    text = "\n".join(kept).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _fallback_formal_answer(raw: str) -> str:
    if "在工具被调用并返回数据之前" in raw or "不能提供最终答案" in raw:
        return "该问题已判定为业务数据查询，我会先调用项目数据工具取数，再给出最终结论。"
    if "本轮未触发工具调用" in raw:
        return "当前轮次尚未获得有效工具结果，请继续由系统执行取数后返回正式结论。"
    return "已完成问题判定，请继续查看下一步业务结论。"


def _normalize_formal_answer(text: str, raw: str) -> str:
    s = (text or "").strip()
    if not s:
        return _fallback_formal_answer(raw)
    s = re.sub(r"^\s*[\-\*]\s*", "", s, flags=re.MULTILINE)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    # Remove trailing connective leftovers from chain-of-thought style drafts.
    s = re.sub(r"(?:\n|^)\s*(所以|因此|综上)\s*$", "", s).strip()
    if ("不能提供最终答案" in s) or ("在工具被调用并返回数据之前" in s):
        return _fallback_formal_answer(raw)
    return s if s else _fallback_formal_answer(raw)


def _strip_data_lines_for_interpretive(text: str) -> str:
    kept: list[str] = []
    for line in (text or "").splitlines():
        t = line.strip()
        if not t:
            kept.append("")
            continue
        if re.search(r"(total_emission|co2e|tco2e|scope\s*[123]|占比|总排放量|吨二氧化碳当量)", t, flags=re.IGNORECASE):
            continue
        if re.match(r"^\d+[\.\、]\s*.+[:：]\s*\d", t):
            continue
        if t.startswith("业务数据查询:"):
            continue
        kept.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def _extract_total_line(text: str) -> str:
    for line in (text or "").splitlines():
        t = line.strip()
        if not t:
            continue
        m = re.search(r"total_emission\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)", t, flags=re.IGNORECASE)
        if m:
            return f"总排放量：{m.group(1)} 吨二氧化碳当量"
        if ("总排放" in t) or ("总量" in t and ("排放" in t or "CO2" in t.upper() or "tco2" in t.lower())):
            return t
    return ""


def _extract_rank_lines(text: str, limit: int = 5) -> list[str]:
    rows: list[str] = []
    noisy_tokens = ("拆解用户请求", "分析输入数据", "json对象", "调用说明", "返回结果", "tool")
    for line in (text or "").splitlines():
        t = line.strip()
        if re.match(r"^\d+[\.\、]\s*(总览|分项|结论|建议)\s*$", t):
            continue
        if any(tok.lower() in t.lower() for tok in noisy_tokens):
            continue
        if re.match(r"^\d+[\.\、]\s*", t) and (
            ("吨" in t) or ("占比" in t) or ("scope" in t.lower())
        ):
            rows.append(t)
        if len(rows) >= limit:
            break
    return rows


def _extract_suggestion(text: str) -> str:
    for line in (text or "").splitlines():
        t = line.strip()
        if not t:
            continue
        if ("建议" in t) or ("可优先" in t) or ("下一步" in t):
            return t
    return ""


def _extract_analysis_blocks(text: str) -> tuple[str, str, str]:
    core = ""
    findings: list[str] = []
    advice = ""
    in_findings = False
    for line in (text or "").splitlines():
        t = line.strip()
        if not t:
            in_findings = False
            continue
        if t.startswith("核心结论："):
            core = t.replace("核心结论：", "", 1).strip()
            in_findings = False
        elif t.startswith("关键发现："):
            in_findings = True
        elif t.startswith("初步建议："):
            advice = t.replace("初步建议：", "", 1).strip()
            in_findings = False
        elif t.startswith("- ") and (in_findings or core):
            findings.append(t)
        else:
            in_findings = False
    return core, "\n".join(findings), advice


def _first_nonempty_line(text: str) -> str:
    for line in (text or "").splitlines():
        t = line.strip()
        if re.match(r"^\d+[\.\、]\s*(总览|分项|结论|建议)\s*$", t):
            continue
        if t:
            return t
    return ""


def _build_formal_sections(formal: str, need_data: bool, need_tool: bool, interpretive_mode: bool = False) -> str:
    analysis_core, analysis_findings, analysis_advice = _extract_analysis_blocks(formal)
    if interpretive_mode:
        first_line = _first_nonempty_line(formal) or "这类排放源通常对应具有能源消耗与设备运行场景的企业。"
        conclusion = first_line
        suggestion = (
            "可按行业业态（制造、园区商业、物流交通、公共机构）先做源项映射，"
            "再结合设备清单与能源结构逐步细化核算边界。"
        )
        return (
            "1. 总览\n"
            f"{first_line}\n\n"
            "2. 分项\n"
            "本问题以行业解读为主，回答基于通用业态与典型排放场景，不引用项目台账明细。\n\n"
            "3. 结论\n"
            f"{conclusion}\n\n"
            "4. 建议\n"
            f"{suggestion}"
        )

    data_rich = bool(
        re.search(r"(总排放量|吨二氧化碳当量|scope\s*[123]|占比)", formal, flags=re.IGNORECASE)
    ) or ("吨" in formal and bool(re.search(r"^\s*\d+[\.\、]\s*", formal, flags=re.MULTILINE)))
    if data_rich:
        # Data-first rendering: keep original business facts visible, do not replace
        # with placeholder templates.
        cleaned = "\n".join(
            line for line in formal.strip().splitlines() if not line.strip().startswith(("核心结论：", "关键发现：", "初步建议：", "- "))
        ).strip()
        conclusion_text = analysis_core or "从当前分项看，前几项排放源贡献占比较高，建议优先纳入治理清单。"
        if analysis_findings:
            conclusion_text = f"{conclusion_text}\n{analysis_findings}"
        suggestion_text = analysis_advice or "如需同比、趋势或治理优先级，我可以继续基于当前数据展开。"
        return (
            "1. 总览\n"
            f"{cleaned}\n\n"
            "2. 分项\n"
            "以上为已获取的真实业务数据明细。\n\n"
            "3. 结论\n"
            f"{conclusion_text}\n\n"
            "4. 建议\n"
            f"{suggestion_text}"
        )

    total_line = _extract_total_line(formal)
    rank_lines = _extract_rank_lines(formal, limit=5)
    suggestion = _extract_suggestion(formal)
    first_line = _first_nonempty_line(formal)

    overview = total_line or first_line or "已完成当前问题分析。"
    if rank_lines:
        breakdown = "；".join(rank_lines)
    elif analysis_findings:
        breakdown = analysis_findings
    elif need_data and need_tool:
        breakdown = "未获取到分项数据，已发起排放源明细补调。"
    elif need_data:
        breakdown = "已完成总览判断，当前轮次未返回可展示的分项明细。"
    else:
        breakdown = "当前问题以规则/知识解释为主，无需项目分项数据。"

    if analysis_core:
        conclusion = analysis_core
        if analysis_findings:
            conclusion = f"{conclusion}\n{analysis_findings}"
    elif rank_lines:
        conclusion = "从当前分项看，前几项排放源贡献占比较高，建议优先纳入治理清单。"
    elif need_data and need_tool:
        conclusion = "该问题属于业务数据场景，分项结论需以排放源明细工具结果为准。"
    elif need_tool:
        conclusion = "该问题属于业务数据场景，应以工具取数结果作为最终结论依据。"
    else:
        conclusion = first_line or "已给出可直接使用的回答。"

    if analysis_advice:
        suggestion = analysis_advice
    elif not suggestion:
        if need_data:
            suggestion = "可继续查看同比趋势、Scope结构占比与重点排放源治理优先级。"
        else:
            suggestion = "如需结合具体项目数据，我可以继续补充定量分析。"

    return (
        "1. 总览\n"
        f"{overview}\n\n"
        "2. 分项\n"
        f"{breakdown}\n\n"
        "3. 结论\n"
        f"{conclusion}\n\n"
        "4. 建议\n"
        f"{suggestion}"
    )


def _tool_judgement_label(raw: str, evidence_text: str, need_data: bool, need_tool: bool) -> str:
    has_total = bool(_extract_total_line(evidence_text))
    has_breakdown = bool(_extract_rank_lines(evidence_text, limit=1))
    breakdown_need = any(
        k in (raw or "").lower()
        for k in ("排放源", "各排放源", "各个排放源", "明细", "拆分", "细分", "占比", "breakdown")
    )
    if not need_data:
        return "无需工具调用"
    if breakdown_need and not has_breakdown:
        return "需要工具调用"
    if has_total or has_breakdown:
        return "需要工具调用（已完成取数）"
    if need_tool:
        return "需要工具调用"
    return "建议工具调用"


def present_user_answer(answer: str, mode: str) -> str:
    """Return user-facing clean answer; keep backend audit elsewhere."""
    s = _strip_code_fences(answer).strip()
    if not s:
        return s
    if _looks_already_presented(s):
        return _dedupe_presented_blocks(s)
    if _looks_user_ready_natural_answer(s):
        return s

    # Clean when explicitly agent-mode or when content clearly contains internal section blocks.
    if not INTERNAL_SECTION_PATTERN.search(s):
        return s

    raw = s
    # Prefer explicit "结果汇总"/"回答" content.
    s = _extract_after_summary_marker(raw).strip()

    # If summary is JSON-like, extract readable answer field.
    from_json = _try_extract_from_json(s)
    if from_json:
        s = from_json

    summary = _drop_internal_lines(s).strip()
    summary = _strip_residual_reasoning(summary).strip()

    demand = _extract_demand_summary(raw, summary)
    interpretive_mode = _is_interpretive_mode(raw, demand=demand)
    need_data = _has_business_data_need(raw, demand=demand)
    if interpretive_mode:
        need_data = False
    need_tool = _has_tool_need(raw)
    if interpretive_mode:
        need_tool = False
    compliance = _extract_compliance_basis(raw)

    formal_evidence = _normalize_formal_answer(summary, raw)
    if interpretive_mode:
        formal_evidence = _strip_data_lines_for_interpretive(formal_evidence)
    formal = _build_formal_sections(
        formal_evidence,
        need_data=need_data,
        need_tool=need_tool,
        interpretive_mode=interpretive_mode,
    )
    reasoning = _build_expert_reasoning(
        demand,
        raw,
        formal_evidence,
        need_data,
        interpretive_mode=interpretive_mode,
    )
    mode_line = _build_answer_mode_line(need_data, formal_evidence)

    # Adaptive user-facing format: keep reasoning + quantified result, avoid rigid five-section template.
    blocks: list[str] = []
    focus_line = f"?????{demand}" if demand else "?????????"
    blocks.append(focus_line)
    blocks.append(f"?????{reasoning}")
    blocks.append(f"?????{mode_line}")
    if compliance:
        blocks.append(f"?????{compliance}")

    result_block = formal.strip()
    if result_block:
        blocks.append("??????")
        blocks.append(result_block)

    return _dedupe_presented_blocks("\n\n".join(b for b in blocks if str(b or "").strip()))

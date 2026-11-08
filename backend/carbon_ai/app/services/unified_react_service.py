from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.chat_history import ChatHistory
from app.services.llm_gateway import chat_messages
from app.services.news_service import hybrid_search_industry_news

logger = logging.getLogger(__name__)


REACT_SYSTEM_PROMPT = """你是“智碳管家”统一咨询助手的调度器。
你有两个工具：
1) NEWS_SEARCH: 检索最新双碳政策/行业资讯（来自已入库新闻，含来源与发布时间）
2) KNOWLEDGE_ANSWER: 直接进行双碳专业知识解读（不查资讯）

请仅输出 JSON：
{"route":"news|knowledge|hybrid","news_query":"...","answer_style":"news|knowledge|hybrid"}

路由规则：
- 用户问“最新政策/动态/新规/通知/资讯/新闻/近期变化/发布” => news
- 用户问“概念解释/方法原理/核算常识/基础知识” => knowledge
- 用户既要政策动态又要专业解释/建议 => hybrid
禁止输出任何解释性文本。"""

FINAL_ANSWER_SYSTEM_PROMPT = """你是“智碳管家”统一咨询助手。
输出要求：
- 只输出最终用户可读答案，禁止暴露思考过程、工具日志、JSON。
- 若使用资讯数据，必须标注来源名称与发布时间；禁止编造政策。
- 语言简洁、专业、结构清晰。"""

KNOWLEDGE_ONLY_PROMPT = """你是双碳领域专业顾问。
请基于通用专业知识直接回答用户问题，避免编造具体政策编号/发布日期。
输出中文，简洁清晰。"""


@dataclass
class UnifiedResult:
    answer: str
    references: list[str]
    route: str


def _heuristic_route(question: str) -> str:
    q = (question or "").lower()
    news_keys = ["政策", "资讯", "新闻", "动态", "新规", "通知", "发布", "最新", "近期", "ccer", "cbam"]
    knowledge_keys = ["什么是", "原理", "区别", "方法", "核算", "scope", "概念", "口径", "框架"]
    has_news = any(k in q for k in news_keys)
    has_know = any(k in q for k in knowledge_keys)
    if has_news and has_know:
        return "hybrid"
    if has_news:
        return "news"
    return "knowledge"


def _plan_route(question: str, history_messages: list[dict[str, str]]) -> tuple[str, str]:
    payload = (
        f"用户问题：{question}\n"
        "请按要求输出 JSON。"
    )
    try:
        out = chat_messages(
            messages=[
                {"role": "system", "content": REACT_SYSTEM_PROMPT},
                *history_messages[-4:],
                {"role": "user", "content": payload},
            ],
            task="general",
            contains_sensitive=False,
        )
        text = (out or "").strip()
        m = re.search(r"\{[\s\S]*\}", text)
        data = json.loads(m.group(0) if m else text)
        route = str(data.get("route", "")).strip().lower()
        if route not in {"news", "knowledge", "hybrid"}:
            route = _heuristic_route(question)
        news_query = str(data.get("news_query", "")).strip() or question
        return route, news_query
    except Exception:
        return _heuristic_route(question), question


def _format_news_refs(rows: list) -> tuple[str, list[str]]:
    if not rows:
        return "", []
    blocks: list[str] = []
    refs: list[str] = []
    for r in rows[:6]:
        pub = r.published_at.strftime("%Y-%m-%d") if r.published_at else (r.fetched_at.strftime("%Y-%m-%d") if r.fetched_at else "")
        blocks.append(
            f"- 标题：{r.title}\n  来源：{r.source_name}\n  发布时间：{pub}\n  摘要：{r.summary}\n  链接：{r.source_url}"
        )
        refs.append(f"资讯来源: {r.source_name} | {pub} | {r.source_url}")
    return "\n".join(blocks), refs


def _build_news_brief(rows: list) -> str:
    if not rows:
        return ""
    lines: list[str] = []
    lines.append("资讯速览：")
    for i, r in enumerate(rows[:3], start=1):
        pub = (
            r.published_at.strftime("%Y-%m-%d")
            if r.published_at
            else (r.fetched_at.strftime("%Y-%m-%d") if r.fetched_at else "")
        )
        summary = str(r.summary or "").strip()
        if len(summary) > 80:
            summary = summary[:80].rstrip() + "..."
        title = str(r.title or "").strip()
        source = str(r.source_name or "").strip()
        url = str(r.source_url or "").strip()
        lines.append(
            f"{i}. **{title}**\n"
            f"   信息：{source}｜{pub}\n"
            f"   摘要：{summary}\n"
            f"   原文：[点击查看原文]({url})"
        )

    titles = " ".join(str(r.title or "") for r in rows[:6]).lower()
    insight = "政策发布以“通知/意见/方案”为主，建议优先关注与企业合规和项目申报直接相关条款。"
    if ("补贴" in titles) or ("资金" in titles):
        insight = "近期出现资金与补贴导向，建议同步梳理申报条件、支持范围和时间窗口。"
    elif ("碳市场" in titles) or ("ccer" in titles):
        insight = "碳市场相关信息活跃，建议重点跟踪履约规则、交易机制与核查要求。"
    elif ("园区" in titles) or ("零碳" in titles):
        insight = "园区与零碳方向持续升温，建议优先关注实施路径、评价指标和示范要求。"
    lines.append(f"\n简要分析：{insight}")
    return "\n".join(lines)


def _knowledge_answer(question: str, history_messages: list[dict[str, str]]) -> str:
    return chat_messages(
        messages=[
            {"role": "system", "content": KNOWLEDGE_ONLY_PROMPT},
            *history_messages[-6:],
            {"role": "user", "content": question},
        ],
        task="general",
        contains_sensitive=False,
    )


def run_unified_react(
    *,
    db: Session,
    session_id: str,
    question: str,
    history_messages: list[dict[str, str]],
) -> UnifiedResult:
    route, news_query = _plan_route(question, history_messages)

    news_rows = []
    if route in {"news", "hybrid"}:
        try:
            news_rows = hybrid_search_industry_news(
                db=db,
                question=news_query,
                track_tag=None,
                top_k=6,
                time_window="1m",
            )
        except Exception as exc:
            logger.warning("unified react news retrieval failed: %s", exc)
            news_rows = []

    news_context, refs = _format_news_refs(news_rows)
    news_brief = _build_news_brief(news_rows)

    if route == "knowledge":
        answer = _knowledge_answer(question, history_messages)
        return UnifiedResult(answer=answer.strip(), references=[], route=route)

    if route == "news" and not news_rows:
        # no-news fallback to knowledge, but explicit boundary
        k = _knowledge_answer(question, history_messages)
        answer = f"未检索到近期高相关资讯，先给出专业解读：\n{k}"
        return UnifiedResult(answer=answer.strip(), references=[], route=route)

    if route == "news":
        prompt = (
            f"用户问题：{question}\n\n"
            f"可用资讯：\n{news_context}\n\n"
            "请基于资讯回答，结尾给出“来源”小节，列出来源与发布时间。"
        )
    else:
        prompt = (
            f"用户问题：{question}\n\n"
            f"可用资讯：\n{news_context}\n\n"
            "请先给出资讯结论，再补充必要专业解读，避免冗长。"
        )

    answer = chat_messages(
        messages=[
            {"role": "system", "content": FINAL_ANSWER_SYSTEM_PROMPT},
            *history_messages[-6:],
            {"role": "user", "content": prompt},
        ],
        task="general",
        contains_sensitive=False,
    )
    clean_answer = (answer or "").strip()
    if news_brief:
        clean_answer = f"{news_brief}\n\n---\n\n{clean_answer}".strip()
    return UnifiedResult(answer=clean_answer, references=refs, route=route)


def load_recent_history_messages(db: Session, session_id: str, limit: int = 8) -> list[dict[str, str]]:
    rows = (
        db.query(ChatHistory)
        .filter(ChatHistory.session_id == session_id)
        .order_by(ChatHistory.created_at.desc())
        .limit(limit)
        .all()
    )
    rows = list(reversed(rows))
    msgs: list[dict[str, str]] = []
    for r in rows:
        q = str(r.question or "").strip()
        a = str(r.answer or "").strip()
        if q:
            msgs.append({"role": "user", "content": q})
        if a:
            msgs.append({"role": "assistant", "content": a})
    return msgs

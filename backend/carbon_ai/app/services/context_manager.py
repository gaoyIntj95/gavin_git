from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

CONTEXT_RECENT_TURNS = max(1, int(os.getenv("CHAT_CONTEXT_RECENT_TURNS", "6")))
CONTEXT_HISTORY_SCAN_LIMIT = max(12, int(os.getenv("CHAT_CONTEXT_HISTORY_SCAN_LIMIT", "60")))
CONTEXT_ENABLE_SUMMARY = os.getenv("CHAT_CONTEXT_ENABLE_SUMMARY", "true").lower() == "true"
CONTEXT_ENABLE_FILTER = os.getenv("CHAT_CONTEXT_ENABLE_FILTER", "true").lower() == "true"
CONTEXT_SUMMARY_MAX_CHARS = max(240, int(os.getenv("CHAT_CONTEXT_SUMMARY_MAX_CHARS", "900")))
CONTEXT_MAX_CORE_NEEDS = max(2, int(os.getenv("CHAT_CONTEXT_MAX_CORE_NEEDS", "4")))
CONTEXT_MAX_KEY_CONCLUSIONS = max(2, int(os.getenv("CHAT_CONTEXT_MAX_KEY_CONCLUSIONS", "4")))

_SMALL_TALK_PATTERNS = [
    r"^(你好|您好|hi|hello|hey)\W*$",
    r"^(谢谢|感谢|thx|thanks)\W*$",
    r"^(早上好|上午好|中午好|下午好|晚上好)\W*$",
    r"^(在吗|有人吗|忙吗)\W*$",
    r"^(好的|ok|收到|明白了)\W*$",
]

_DOMAIN_HINTS = [
    "碳",
    "排放",
    "核算",
    "盘查",
    "scope",
    "cbam",
    "因子",
    "配额",
    "履约",
    "项目",
    "排放源",
    "ghg",
    "iso",
    "js/t",
    "report",
    "emission",
]

_INTENT_HINTS = [
    "测算",
    "核算",
    "拆分",
    "分析",
    "对比",
    "优化",
    "预测",
    "合规",
    "核查",
    "问答",
    "报告",
]


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_for_dedup(text: str) -> str:
    lowered = _safe_text(text).lower()
    lowered = re.sub(r"\s+", "", lowered)
    lowered = re.sub(r"[^\w\u4e00-\u9fff]+", "", lowered)
    return lowered


def _is_small_talk(text: str) -> bool:
    s = _safe_text(text)
    if not s:
        return True
    if any(re.match(p, s, flags=re.IGNORECASE) for p in _SMALL_TALK_PATTERNS):
        return True
    if len(s) <= 12 and not any(k in s.lower() for k in _DOMAIN_HINTS):
        return True
    return False


def _is_business_related(text: str) -> bool:
    s = _safe_text(text).lower()
    if not s:
        return False
    return any(k in s for k in _DOMAIN_HINTS)


def _clip(text: str, limit: int) -> str:
    t = _safe_text(text)
    return t if len(t) <= limit else t[:limit] + "..."


def _record_to_turn(record: Any) -> dict[str, Any]:
    created_at = getattr(record, "created_at", None)
    if isinstance(created_at, datetime):
        created = created_at.isoformat()
    else:
        created = _safe_text(created_at)
    return {
        "question": _safe_text(getattr(record, "question", "")),
        "answer": _safe_text(getattr(record, "answer", "")),
        "mode": _safe_text(getattr(record, "mode", "")),
        "project_id": getattr(record, "project_id", None),
        "created_at": created,
    }


def _should_filter_turn(turn: dict[str, Any], seen_q: set[str]) -> bool:
    if not CONTEXT_ENABLE_FILTER:
        return False

    question = _safe_text(turn.get("question"))
    answer = _safe_text(turn.get("answer"))
    if not question and not answer:
        return True

    q_norm = _normalize_for_dedup(question)
    if q_norm and q_norm in seen_q:
        return True

    q_small = _is_small_talk(question)
    a_small = _is_small_talk(answer)
    if q_small and a_small:
        return True

    # Keep any domain/business turn to avoid over-filtering.
    if _is_business_related(question) or _is_business_related(answer):
        return False

    # Short unrelated chitchat round can be skipped.
    if len(question) <= 18 and len(answer) <= 64:
        return True
    return False


def _collect_intents(turns: list[dict[str, Any]]) -> list[str]:
    intents: list[str] = []
    for turn in turns:
        q = _safe_text(turn.get("question")).lower()
        for hint in _INTENT_HINTS:
            if hint in q and hint not in intents:
                intents.append(hint)
    return intents


def _build_history_summary(old_turns: list[dict[str, Any]]) -> str:
    if not old_turns:
        return ""

    core_needs: list[str] = []
    project_ids: list[str] = []
    key_conclusions: list[str] = []
    intents = _collect_intents(old_turns)

    for turn in old_turns:
        q = _safe_text(turn.get("question"))
        a = _safe_text(turn.get("answer"))
        pid = turn.get("project_id")

        if q and not _is_small_talk(q):
            clipped = _clip(q, 72)
            if clipped not in core_needs:
                core_needs.append(clipped)
        if pid is not None:
            pid_text = str(pid)
            if pid_text not in project_ids:
                project_ids.append(pid_text)

        if a:
            # Keep first meaningful sentence or numeric conclusion.
            pieces = re.split(r"[。！？!?;\n]+", a)
            for piece in pieces:
                p = _safe_text(piece)
                if not p:
                    continue
                if any(token in p.lower() for token in _DOMAIN_HINTS) or re.search(r"\d", p):
                    clipped = _clip(p, 86)
                    if clipped not in key_conclusions:
                        key_conclusions.append(clipped)
                    break

    core_needs = core_needs[:CONTEXT_MAX_CORE_NEEDS]
    key_conclusions = key_conclusions[:CONTEXT_MAX_KEY_CONCLUSIONS]

    needs_text = "；".join(core_needs) if core_needs else "无显式核心需求"
    project_text = ",".join(project_ids) if project_ids else "未绑定项目"
    conclusion_text = "；".join(key_conclusions) if key_conclusions else "暂无稳定结论"
    intent_text = "、".join(intents[:5]) if intents else "围绕业务问答与分析"

    summary = (
        "历史对话摘要（压缩）:\n"
        f"- 用户核心需求: {needs_text}\n"
        f"- 项目信息: {project_text}\n"
        f"- 关键结论: {conclusion_text}\n"
        f"- 业务意图: {intent_text}"
    )
    return _clip(summary, CONTEXT_SUMMARY_MAX_CHARS)


def build_context_messages(records: list[Any], recent_turns: int | None = None) -> list[dict[str, str]]:
    if not records:
        return []

    turns = [_record_to_turn(r) for r in records]
    seen_q: set[str] = set()
    filtered_turns: list[dict[str, Any]] = []

    for turn in turns:
        q_norm = _normalize_for_dedup(turn.get("question", ""))
        if _should_filter_turn(turn, seen_q):
            if q_norm:
                seen_q.add(q_norm)
            continue
        filtered_turns.append(turn)
        if q_norm:
            seen_q.add(q_norm)

    if not filtered_turns:
        return []

    keep_turns = max(1, int(recent_turns or CONTEXT_RECENT_TURNS))
    old_turns = filtered_turns[:-keep_turns] if len(filtered_turns) > keep_turns else []
    recent = filtered_turns[-keep_turns:]

    history_messages: list[dict[str, str]] = []
    if CONTEXT_ENABLE_SUMMARY and old_turns:
        summary = _build_history_summary(old_turns)
        if summary:
            history_messages.append({"role": "assistant", "content": summary})

    for turn in recent:
        question = _safe_text(turn.get("question"))
        answer = _safe_text(turn.get("answer"))
        if question:
            history_messages.append({"role": "user", "content": question})
        if answer:
            history_messages.append({"role": "assistant", "content": answer})

    return history_messages


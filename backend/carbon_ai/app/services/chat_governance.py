from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.models.quick_question import QuickQuestion
from app.services.rag_service import ask_with_preset_rules

QUICK_PRESET_THRESHOLD = 0.80

BUSINESS_OPERATION_KEYWORDS = [
    "\u9879\u76ee",
    "\u6392\u653e",
    "\u6838\u7b97",
    "\u76d8\u67e5",
    "\u7edf\u8ba1",
    "\u5206\u6790",
    "\u8d8b\u52bf",
    "\u5360\u6bd4",
    "\u62c6\u5206",
    "\u660e\u7ec6",
    "\u62a5\u8868",
    "\u62a5\u544a",
    "\u8ba1\u7b97",
    "\u6e05\u5355",
    "emission",
    "project",
    "breakdown",
    "report",
]

BUSINESS_SUBJECT_KEYWORDS = [
    "\u9879\u76ee",
    "\u4f01\u4e1a",
    "\u516c\u53f8",
    "\u4e3b\u4f53",
    "\u53f0\u8d26",
    "\u5e74\u5ea6",
    "project",
    "company",
    "ledger",
]

KNOWLEDGE_HINT_KEYWORDS = [
    "\u662f\u4ec0\u4e48",
    "\u5b9a\u4e49",
    "\u533a\u522b",
    "\u542b\u4e49",
    "\u6982\u5ff5",
    "\u4ecb\u7ecd",
    "\u4f5c\u7528",
    "scope",
    "iso",
    "cbam",
    "ghg",
    "\u5982\u4f55",
    "\u600e\u4e48",
    "\u65b9\u6cd5",
    "\u7b56\u7565",
    "\u8def\u5f84",
    "\u4f18\u5316",
    "\u914d\u989d",
    "\u5c65\u7ea6",
    "\u78b3\u5e02\u573a",
]

FOLLOWUP_KEYWORDS = [
    "\u7ee7\u7eed",
    "\u7ee7\u7eed\u62c6\u5206",
    "\u62c6\u5206",
    "\u5c55\u5f00",
    "\u7ec6\u5206",
    "\u660e\u7ec6",
    "\u8fdb\u4e00\u6b65",
    "\u7ee7\u7eed\u5206\u6790",
    "\u518d\u5206\u6790",
    "\u518d\u62c6\u5206",
    "go on",
    "continue",
    "breakdown",
    "details",
]


@dataclass
class PresetHit:
    answer: str
    references: list[str]
    source: str


def normalize_text(text: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", "", (text or "").lower())
    return cleaned.strip()


def is_followup_query(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False
    if re.search(r"scope\s*[1-3](?:\s*[/\\\\,+，、]\s*[1-3])+", q):
        return True
    if re.search(r"scope\s*[1-3]", q) and len(q) <= 24:
        return True
    if any(k in q for k in FOLLOWUP_KEYWORDS):
        return True
    return len(q) <= 8


def is_business_operation_query(question: str) -> bool:
    q = (question or "").strip().lower()
    has_data_term = any(k in q for k in BUSINESS_OPERATION_KEYWORDS)
    has_subject = any(k in q for k in BUSINESS_SUBJECT_KEYWORDS) or bool(
        re.search(r"(?:\u9879\u76ee|project)\s*[0-9]{1,9}", q, flags=re.IGNORECASE)
    )
    return has_data_term and has_subject


def is_generic_knowledge_query(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False
    has_hint = any(k in q for k in KNOWLEDGE_HINT_KEYWORDS)
    if not has_hint:
        return False
    # Generic strategy/policy queries should not be forced into business-data path.
    return not is_business_operation_query(q)


def is_pure_knowledge_short_query(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False
    has_hint = any(k in q for k in KNOWLEDGE_HINT_KEYWORDS)
    short_enough = len(q) <= 140
    if short_enough and has_hint and not is_business_operation_query(q):
        return True
    return is_generic_knowledge_query(q)


def resolve_execution_mode(
    requested_mode: str,
    question: str,
    project_id: int | None,
    session_mode: str | None = None,
    last_mode: str | None = None,
) -> str:
    mode = (requested_mode or "auto").lower()
    if mode == "agent":
        return "agent"
    if mode == "rag":
        return "rag"

    force_agent_by_followup = (
        project_id is not None
        and project_id > 0
        and is_followup_query(question)
        and ((last_mode or "") == "agent" or (session_mode or "") == "agent")
    )
    if force_agent_by_followup:
        return "agent"
    if is_pure_knowledge_short_query(question) or is_generic_knowledge_query(question):
        return "rag"
    return "agent"


def should_apply_preset(requested_mode: str, execution_mode: str, question: str) -> bool:
    mode = (requested_mode or "auto").lower()
    if execution_mode != "rag":
        return False
    if mode == "agent":
        return False
    if mode == "auto":
        return is_pure_knowledge_short_query(question)
    return mode == "rag"


def _quick_question_similarity(a: str, b: str) -> float:
    na = normalize_text(a)
    nb = normalize_text(b)
    if not na or not nb:
        return 0.0
    if na in nb or nb in na:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _match_quick_question(
    db: Session,
    question: str,
    threshold: float = QUICK_PRESET_THRESHOLD,
) -> tuple[QuickQuestion, float] | None:
    records = (
        db.query(QuickQuestion)
        .filter(QuickQuestion.is_active == True)
        .order_by(QuickQuestion.sort_order.asc(), QuickQuestion.id.asc())
        .all()
    )
    best_item = None
    best_score = 0.0
    for item in records:
        score = _quick_question_similarity(question, item.question)
        if score > best_score:
            best_item = item
            best_score = score
    if best_item is None or best_score < threshold:
        return None
    return best_item, best_score


def try_match_preset(db: Session, question: str) -> PresetHit | None:
    preset_match = _match_quick_question(db, question)
    if preset_match:
        matched_q, score = preset_match
        preset = ask_with_preset_rules(matched_q.question)
        if preset is not None:
            answer, refs = preset
            references = [f"\u5feb\u6377\u9884\u8bbe\u5339\u914d: {matched_q.question}\uff08\u5339\u914d\u5ea6 {score:.0%}\uff09"]
            references.extend(refs)
            return PresetHit(answer=answer, references=references, source="quick_question")

    direct = ask_with_preset_rules(question)
    if direct is None:
        return None
    answer, refs = direct
    references = ["\u9884\u8bbe\u89c4\u5219\u5339\u914d: \u5173\u952e\u8bcd\u547d\u4e2d"]
    references.extend(refs)
    return PresetHit(answer=answer, references=references, source="direct_keyword")

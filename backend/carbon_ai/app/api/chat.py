from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.chat_history import ChatHistory
from app.models.project import Project
from app.models.chat_session import ChatSession
from app.models.knowledge_document import KnowledgeDocument
from app.models.quick_question import QuickQuestion
from app.schemas.chat import (
    ChatAskRequest,
    ChatAskResponse,
    ChatMessage,
    ChatSessionCreateRequest,
    ChatSessionItem,
    ChatSessionListResponse,
    ChatSessionResponse,
    ChatSessionUpdateRequest,
    KnowledgeDocumentItem,
    KnowledgeListResponse,
    KnowledgeUploadResponse,
    QuickQuestionItem,
    QuickQuestionListResponse,
)
from app.services.document_parser import parse_and_chunk
from app.services.rag_service import (
    index_document_chunks,
)
from app.services.chat_governance import (
    is_business_operation_query,
    try_match_preset,
)
from app.services.web_search_service import WEB_SEARCH_ENABLED
from app.services.llm_gateway import (
    REMOTE_LLM_ENABLED,
    get_runtime_config,
    check_ollama_health,
    check_remote_llm_health,
)
from app.services.object_storage_service import (
    upload_bytes as upload_to_minio_bytes,
    delete_object as delete_minio_object,
    check_minio_health,
)
from app.services.memory_service import archive_chat_memory_turn, delete_memories_by_session
from app.services.vector_store import check_milvus_health
from app.services.context_manager import (
    CONTEXT_HISTORY_SCAN_LIMIT,
    CONTEXT_RECENT_TURNS,
    build_context_messages,
)
from app.services.progressive_intake import (
    deactivate_progressive_intake,
    handle_progressive_intake,
    is_progressive_intake_active,
    should_run_progressive_intake,
)
from app.services.answer_presenter import present_user_answer
from app.services.chat_dispatcher import (
    build_dispatch_plan,
    run_data_chain,
    run_knowledge_chain,
)
from app.services.agent.tools.emission_summary_tool import get_emission_summary
from app.services.unified_react_service import (
    load_recent_history_messages,
    run_unified_react,
)
from app.services.chat_observability import (
    record_result_event,
    record_route_event,
    snapshot_metrics as snapshot_routing_metrics,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

ALLOWED_FILE_TYPES = {".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".xls", ".xlsx"}


def _safe_json_loads(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _looks_like_news_consultation(question: str) -> bool:
    q = (question or "").lower()
    keys = (
        "政策",
        "资讯",
        "新闻",
        "动态",
        "新规",
        "通知",
        "发布",
        "最新",
        "近期",
        "赛碳",
        "双碳",
        "园区",
        "ccer",
        "cbam",
        "碳市场",
    )
    return any(k in q for k in keys)


def _contains_project_marker(question: str) -> bool:
    text = (question or "").strip()
    if not text:
        return False
    if "project_id" in text.lower():
        return True
    if re.search(r"(?:项目|project)\s*[12]\b", text, flags=re.IGNORECASE):
        return True
    return False


def _resolve_single_intent(question: str) -> str:
    q = (question or "").lower()
    breakdown_keys = ("明细", "排放源", "拆分", "详细", "各个", "breakdown")
    summary_keys = ("总览", "整体", "情况", "汇总", "summary")
    policy_keys = ("政策", "资讯", "新闻", "新规", "解读", "policy")
    if any(k in q for k in breakdown_keys):
        return "breakdown"
    if any(k in q for k in summary_keys):
        return "summary"
    if any(k in q for k in policy_keys):
        return "policy"
    return "summary"


def _clean_internal_output(text: str) -> str:
    s = str(text or "")
    blocked_phrases = (
        "我现在需要处理",
        "首先回顾",
        "检查",
        "组织内容",
        "禁止编造",
    )
    blocked_titles = (
        "需求拆解",
        "条件判定",
        "规则依据",
        "工具选择",
    )
    lines: list[str] = []
    for line in s.splitlines():
        t = line.strip()
        if not t:
            continue
        if any(p in t for p in blocked_phrases):
            continue
        if any(t.startswith(bt) for bt in blocked_titles):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _build_final_structured_answer(answer: str, references: list[str]) -> str:
    cleaned = _clean_internal_output(answer)
    quant_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:tCO2e|吨|%)", cleaned, flags=re.IGNORECASE)
    quant = quant_match.group(0) if quant_match else "未提取到量化值"
    conclusion = f"{cleaned}\n量化要点：{quant}" if cleaned else f"量化要点：{quant}"
    refs_text = "；".join([str(r) for r in (references or []) if str(r).strip()]) or "无"
    return (
        f"结论：\n{conclusion}\n\n"
        "口径依据：\n"
        "核算口径遵循 ISO14064 与 GHG Protocol，按项目边界与活动数据进行一致性统计。\n\n"
        "业务建议：\n"
        "建议优先锁定高排放环节，按月追踪总量与结构占比，并对异常波动执行复核与减排措施闭环。\n\n"
        f"数据来源：\n{refs_text}"
    )


def _present_references_for_user(references: list[str], mode: str) -> list[str]:
    refs = references or []
    if mode != "agent":
        return refs

    normalized = [str(ref or "").strip() for ref in refs if str(ref or "").strip()]
    normalized = [r for r in normalized if not r.startswith("规则白盒:")]
    if not normalized:
        return []

    business_refs = [
        r
        for r in normalized
        if ("业务数据查询:" in r) or ("project" in r.lower()) or ("emission" in r.lower())
    ]
    if business_refs:
        deduped: list[str] = []
        for ref in business_refs:
            if ref not in deduped:
                deduped.append(ref)
        return deduped[:3]

    shown: list[str] = []
    for ref in normalized:
        # Reduce noisy standard-document-only references in agent display.
        if "ISO" in ref.upper() and "业务数据查询:" not in ref:
            continue
        if ref not in shown:
            shown.append(ref)
    return shown[:3]


def _references_indicate_tool(references: list[str]) -> bool:
    for ref in references or []:
        text = str(ref or "").lower()
        if "业务数据查询:" in text or "get_emission_" in text or "query_by_nl2sql" in text:
            return True
    return False


def _infer_project_id_from_question(db: Session, question: str) -> int | None:
    text = (question or "").strip()
    if not text:
        return None

    # Match "项目1", "项目 1", "project 1" style references.
    m = re.search(r"(?:项目|project)\s*([0-9]{1,9})", text, flags=re.IGNORECASE)
    if m:
        # Explicit numeric project mention should prioritize tool execution.
        # Even if the project is invalid, tools can return a clear business error
        # instead of falling back to generic knowledge response.
        return int(m.group(1))

    # Match bare numeric list input like "1、2、3、4" or "1,2,3".
    # This commonly appears when UI asks the user to pick from numbered projects.
    list_like = re.fullmatch(r"\s*\d{1,9}(?:\s*[、,，/\s-]\s*\d{1,9})+\s*", text)
    if list_like:
        first = re.search(r"\d{1,9}", text)
        if first:
            return int(first.group(0))

    # Match exact project name mention.
    rows = (
        db.query(Project.id, Project.name)
        .filter(Project.is_deleted == False)
        .limit(200)
        .all()
    )
    for pid, name in rows:
        if name and name in text:
            return int(pid)

    # Fuzzy match by enterprise/company token + year (if present).
    company_match = re.search(
        r"([\u4e00-\u9fa5A-Za-z0-9（）()·\-_]{2,40}(?:公司|集团|厂|中心|研究院))",
        text,
    )
    year_match = re.search(r"(20\d{2})", text)
    company = (company_match.group(1).strip() if company_match else "")
    year = (year_match.group(1).strip() if year_match else "")
    if company:
        for pid, name in rows:
            n = str(name or "")
            if company in n and (not year or year in n):
                return int(pid)
    return None


def _extract_explicit_project_ids_from_question(db: Session, question: str) -> list[int]:
    text = (question or "").strip()
    if not text:
        return []
    # Support list-like selections from UI such as "1、2、3、4、5、6".
    is_list_like = re.fullmatch(r"\s*\d{1,9}(?:\s*[、,，/\s-]\s*\d{1,9})+\s*", text) is not None
    if not is_list_like:
        return []

    raw_ids = [int(v) for v in re.findall(r"\d{1,9}", text)]
    if len(raw_ids) < 2:
        return []

    deduped_ids: list[int] = []
    seen: set[int] = set()
    for pid in raw_ids:
        if pid not in seen:
            seen.add(pid)
            deduped_ids.append(pid)

    valid_rows = (
        db.query(Project.id)
        .filter(Project.is_deleted == False, Project.id.in_(deduped_ids))
        .all()
    )
    valid_set = {int(r[0]) for r in valid_rows}
    return [pid for pid in deduped_ids if pid in valid_set]


def _build_multi_project_summary_answer(db: Session, project_ids: list[int]) -> tuple[str, list[str]]:
    rows: list[tuple[int, str, float]] = []
    missing: list[int] = []
    for pid in project_ids:
        summary = get_emission_summary(db, int(pid))
        if not isinstance(summary, dict) or summary.get("error"):
            missing.append(int(pid))
            continue
        rows.append(
            (
                int(pid),
                str(summary.get("project_name") or f"项目{pid}"),
                float(summary.get("total_emission", 0) or 0),
            )
        )

    if not rows:
        missing_txt = "、".join(str(x) for x in (missing or project_ids))
        return (f"未能读取项目 {missing_txt} 的排放汇总数据，请确认项目是否存在且已完成排放源填报。", ["业务数据查询: get_emission_summary"])

    rows.sort(key=lambda x: x[2], reverse=True)
    total = sum(v for _, _, v in rows)
    max_row = rows[0]
    min_row = rows[-1]
    span = max_row[2] - min_row[2]
    span_pct = (span / min_row[2] * 100) if min_row[2] > 0 else 0.0

    lines = []
    lines.append(f"已按你选择的 {len(rows)} 个项目完成汇总对比（总排放合计 {total:.2f} tCO2e）。")
    lines.append("各项目总排放：")
    for idx, (_, name, value) in enumerate(rows, 1):
        lines.append(f"{idx}. {name}：{value:.2f} tCO2e")
    lines.append(f"最高项目为“{max_row[1]}”（{max_row[2]:.2f} tCO2e），最低项目为“{min_row[1]}”（{min_row[2]:.2f} tCO2e）。")
    lines.append(f"两者差值 {span:.2f} tCO2e，倍差约 {span_pct:.1f}%。")
    if missing:
        lines.append(f"未纳入统计的项目ID：{'、'.join(str(x) for x in missing)}。")

    refs = ["业务数据查询: get_emission_summary（多项目聚合）"]
    return ("\n".join(lines), refs)


def _infer_project_id_from_recent_history(
    db: Session,
    session_id: str,
    max_turns: int = 8,
) -> int | None:
    records = (
        db.query(ChatHistory)
        .filter(ChatHistory.session_id == session_id)
        .order_by(ChatHistory.created_at.desc())
        .limit(max_turns)
        .all()
    )
    for rec in records:
        if rec.project_id is not None and rec.project_id > 0:
            return int(rec.project_id)
        q_hit = _infer_project_id_from_question(db, rec.question or "")
        if q_hit is not None:
            return int(q_hit)
        a_hit = _infer_project_id_from_question(db, rec.answer or "")
        if a_hit is not None:
            return int(a_hit)
    return None


def _ensure_session(db: Session, session_id: str) -> ChatSession:
    session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    if not session:
        session = ChatSession(session_id=session_id, name="新会话", mode="rag")
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def _get_history_messages(db: Session, session_id: str, limit: int = 10) -> list[dict[str, str]]:
    """获取会话历史消息，用于多轮对话上下文。"""
    scan_limit = max(CONTEXT_HISTORY_SCAN_LIMIT, limit * 4)
    records = (
        db.query(ChatHistory)
        .filter(ChatHistory.session_id == session_id)
        .order_by(ChatHistory.created_at.desc())
        .limit(scan_limit)
        .all()
    )
    records = list(reversed(records))
    return build_context_messages(records, recent_turns=CONTEXT_RECENT_TURNS)


def _persist_chat_turn(
    db: Session,
    session: ChatSession | None,
    session_id: str,
    question: str,
    answer: str,
    references: list[str],
    mode: str,
    project_id: int | None,
    chart: dict | None = None,
) -> ChatAskResponse:
    display_answer = present_user_answer(answer, mode)
    display_references = _present_references_for_user(references, mode)

    message = ChatHistory(
        session_id=session_id,
        question=question,
        answer=display_answer,
        references=json.dumps(display_references, ensure_ascii=False),
        chart=(json.dumps(chart, ensure_ascii=False) if chart is not None else None),
        mode=mode,
        project_id=project_id,
    )
    db.add(message)

    if session:
        session.updated_at = datetime.utcnow()
        if project_id is not None:
            session.project_id = project_id
        if session.name == "新会话":
            truncated = question[:50]
            session.name = truncated + ("..." if len(question) > 50 else "")
        session.mode = mode

    db.commit()

    try:
        archive_chat_memory_turn(
            session_id=session_id,
            question=question,
            answer=display_answer,
            project_id=project_id,
            mode=mode,
            references=display_references,
            created_at=message.created_at,
        )
    except Exception as exc:
        logger.warning("archive chat memory failed: %s", exc)

    return ChatAskResponse(answer=display_answer, references=display_references, mode=mode, chart=chart)


@router.post("/ask", response_model=ChatAskResponse)
def ask_question(
    payload: ChatAskRequest,
    db: Session = Depends(get_db),
) -> ChatAskResponse:
    _ensure_session(db, payload.session_id)

    session = db.query(ChatSession).filter(ChatSession.session_id == payload.session_id).first()
    if session and payload.project_id is None:
        payload.project_id = session.project_id

    last_record = (
        db.query(ChatHistory)
        .filter(ChatHistory.session_id == payload.session_id)
        .order_by(ChatHistory.created_at.desc())
        .first()
    )
    if payload.project_id is None and last_record and last_record.project_id is not None:
        payload.project_id = last_record.project_id

    multi_project_ids = _extract_explicit_project_ids_from_question(db, payload.question)

    if payload.project_id is None and is_business_operation_query(payload.question):
        inferred_pid = _infer_project_id_from_question(db, payload.question)
        if inferred_pid is not None:
            payload.project_id = inferred_pid

    if payload.project_id is None:
        # Preserve multi-turn business context: follow-up detail questions should inherit
        # project scope from recent turns instead of falling back to summary-only behavior.
        recovered_pid = _infer_project_id_from_recent_history(db, payload.session_id, max_turns=8)
        if recovered_pid is not None:
            payload.project_id = recovered_pid

    if session is not None and payload.project_id is not None and payload.project_id > 0:
        # Once project context is explicitly resolved, close sticky intake state.
        deactivate_progressive_intake(session)

    intake_active = bool(session is not None and is_progressive_intake_active(session))
    forced_intent = _resolve_single_intent(payload.question)
    project_marker_hit = _contains_project_marker(payload.question)

    if project_marker_hit:
        dispatch_mode_hint = "agent"
        if forced_intent == "policy":
            forced_intent = "summary"
    elif forced_intent == "breakdown":
        dispatch_mode_hint = "agent"
    elif forced_intent == "policy":
        dispatch_mode_hint = "rag"
    else:
        dispatch_mode_hint = payload.mode

    dispatch_plan = build_dispatch_plan(
        requested_mode=dispatch_mode_hint,
        question=payload.question,
        project_id=payload.project_id,
        session_mode=(session.mode if session is not None else None),
        last_mode=(last_record.mode if last_record is not None else None),
        intake_active=intake_active,
    )
    execution_mode = dispatch_plan.execution_mode

    if execution_mode == "agent" and len(multi_project_ids) >= 2 and is_business_operation_query(payload.question):
        answer, references = _build_multi_project_summary_answer(db, multi_project_ids)
        record_route_event(
            session_id=payload.session_id,
            requested_mode=payload.mode,
            execution_mode=dispatch_plan.execution_mode,
            chain="data",
            route_reason="multi_project_aggregate",
            intake_active=False,
            has_project=True,
            allow_preset=False,
        )
        record_result_event(
            session_id=payload.session_id,
            chain="data",
            effective_mode="agent",
            used_preset=False,
            used_tool=True,
        )
        return _persist_chat_turn(
            db=db,
            session=session,
            session_id=payload.session_id,
            question=payload.question,
            answer=answer,
            references=references,
            mode="agent",
            project_id=(multi_project_ids[0] if multi_project_ids else payload.project_id),
            chart=None,
        )

    if dispatch_plan.allow_preset:
        preset_hit = try_match_preset(db, payload.question)
        if preset_hit is not None:
            record_route_event(
                session_id=payload.session_id,
                requested_mode=payload.mode,
                execution_mode=dispatch_plan.execution_mode,
                chain=dispatch_plan.chain,
                route_reason=dispatch_plan.route_reason,
                intake_active=intake_active,
                has_project=bool(payload.project_id and payload.project_id > 0),
                allow_preset=dispatch_plan.allow_preset,
            )
            record_result_event(
                session_id=payload.session_id,
                chain=dispatch_plan.chain,
                effective_mode="preset",
                used_preset=True,
                used_tool=False,
            )
            return _persist_chat_turn(
                db=db,
                session=session,
                session_id=payload.session_id,
                question=payload.question,
                answer=preset_hit.answer,
                references=preset_hit.references,
                mode="preset",
                project_id=payload.project_id,
                chart=None,
            )

    if (
        execution_mode == "agent"
        and session is not None
        and should_run_progressive_intake(session, payload.question, payload.project_id)
    ):
        intake_result = handle_progressive_intake(session, payload.question)
        if intake_result.get("should_ask"):
            answer = str(intake_result.get("followup_question") or "").strip() or "为保证结果准确，请先补充一个关键信息。"
            snapshot = str(intake_result.get("snapshot") or "").strip()
            references = ["渐进式信息收集已触发"]
            if snapshot:
                references.append(snapshot)
            record_route_event(
                session_id=payload.session_id,
                requested_mode=payload.mode,
                execution_mode=dispatch_plan.execution_mode,
                chain=dispatch_plan.chain,
                route_reason="progressive_intake_followup",
                intake_active=True,
                has_project=bool(payload.project_id and payload.project_id > 0),
                allow_preset=False,
            )
            record_result_event(
                session_id=payload.session_id,
                chain="data",
                effective_mode="agent",
                used_preset=False,
                used_tool=False,
            )
            return _persist_chat_turn(
                db=db,
                session=session,
                session_id=payload.session_id,
                question=payload.question,
                answer=answer,
                references=references,
                mode="agent",
                project_id=payload.project_id,
                chart=None,
            )

    history_messages = _get_history_messages(db, payload.session_id, limit=10)
    effective_mode = execution_mode
    answer = ""
    references: list[str] = []
    chart: dict | None = None

    if dispatch_plan.chain == "data":
        answer, references, chart = run_data_chain(
            question=payload.question,
            session_id=payload.session_id,
            project_id=payload.project_id,
            db=db,
            history_messages=history_messages,
            forced_intent=forced_intent,
        )
    else:
        if _looks_like_news_consultation(payload.question) and not project_marker_hit:
            unified = run_unified_react(
                db=db,
                session_id=payload.session_id,
                question=payload.question,
                history_messages=history_messages,
            )
            effective_mode = "agent"
            answer = unified.answer
            references = unified.references
        else:
            effective_mode, answer, references = run_knowledge_chain(
                question=payload.question,
                session_id=payload.session_id,
                history_messages=history_messages,
            )

    answer = _build_final_structured_answer(answer, references)

    record_route_event(
        session_id=payload.session_id,
        requested_mode=payload.mode,
        execution_mode=dispatch_plan.execution_mode,
        chain=dispatch_plan.chain,
        route_reason=dispatch_plan.route_reason,
        intake_active=intake_active,
        has_project=bool(payload.project_id and payload.project_id > 0),
        allow_preset=dispatch_plan.allow_preset,
    )
    record_result_event(
        session_id=payload.session_id,
        chain=dispatch_plan.chain,
        effective_mode=effective_mode,
        used_preset=False,
        used_tool=_references_indicate_tool(references),
    )

    return _persist_chat_turn(
        db=db,
        session=session,
        session_id=payload.session_id,
        question=payload.question,
        answer=answer,
        references=references,
        mode=effective_mode,
        project_id=payload.project_id,
        chart=chart,
    )


@router.post("/ask-unified", response_model=ChatAskResponse)
def ask_question_unified(
    payload: ChatAskRequest,
    db: Session = Depends(get_db),
) -> ChatAskResponse:
    session = _ensure_session(db, payload.session_id)
    history_messages = load_recent_history_messages(db, payload.session_id, limit=8)

    result = run_unified_react(
        db=db,
        session_id=payload.session_id,
        question=payload.question,
        history_messages=history_messages,
    )

    # Keep backward-compatible persistence shape.
    return _persist_chat_turn(
        db=db,
        session=session,
        session_id=payload.session_id,
        question=payload.question,
        answer=result.answer,
        references=result.references,
        mode="agent",
        project_id=payload.project_id,
        chart=None,
    )


@router.get("/sessions", response_model=ChatSessionListResponse)
def list_sessions(db: Session = Depends(get_db)) -> ChatSessionListResponse:
    sessions = db.query(ChatSession).order_by(ChatSession.updated_at.desc()).all()
    items = [
        ChatSessionItem(
            session_id=s.session_id,
            name=s.name,
            mode=s.mode,
            project_id=s.project_id,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]
    return ChatSessionListResponse(sessions=items)


@router.post("/sessions", response_model=ChatSessionItem)
def create_session(payload: ChatSessionCreateRequest, db: Session = Depends(get_db)) -> ChatSessionItem:
    existing = db.query(ChatSession).filter(ChatSession.session_id == payload.session_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="会话ID已存在")
    session = ChatSession(
        session_id=payload.session_id,
        name=payload.name,
        mode=payload.mode,
        project_id=payload.project_id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return ChatSessionItem(
        session_id=session.session_id,
        name=session.name,
        mode=session.mode,
        project_id=session.project_id,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.patch("/sessions/{session_id}", response_model=ChatSessionItem)
def update_session(
    session_id: str,
    payload: ChatSessionUpdateRequest,
    db: Session = Depends(get_db),
) -> ChatSessionItem:
    session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if payload.name is not None:
        session.name = payload.name
    if payload.project_id is not None:
        session.project_id = payload.project_id
    session.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    return ChatSessionItem(
        session_id=session.session_id,
        name=session.name,
        mode=session.mode,
        project_id=session.project_id,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.query(ChatHistory).filter(ChatHistory.session_id == session_id).delete()
    db.delete(session)
    db.commit()
    try:
        delete_memories_by_session(session_id)
    except Exception as exc:
        logger.warning("delete chat memories by session failed: %s", exc)
    return {"message": "会话已删除"}


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
def get_session_messages(session_id: str, db: Session = Depends(get_db)) -> ChatSessionResponse:
    records = (
        db.query(ChatHistory)
        .filter(ChatHistory.session_id == session_id)
        .order_by(ChatHistory.created_at.asc())
        .all()
    )
    messages = [
        ChatMessage(
            question=item.question,
            answer=present_user_answer(item.answer, item.mode),
            references=_present_references_for_user(
                _safe_json_loads(item.references, []),
                item.mode,
            ),
            chart=_safe_json_loads(item.chart, None),
            mode=item.mode,
            project_id=item.project_id,
            created_at=item.created_at,
        )
        for item in records
    ]
    return ChatSessionResponse(messages=messages)


@router.post("/knowledge/upload", response_model=KnowledgeUploadResponse)
async def upload_knowledge_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> KnowledgeUploadResponse:
    file_suffix = Path(file.filename or "").suffix.lower()
    if file_suffix not in ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file_suffix}，支持: {', '.join(sorted(ALLOWED_FILE_TYPES))}",
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="空文件，无法上传")

    storage = upload_to_minio_bytes(
        content,
        filename=file.filename or "unknown",
        object_key=f"knowledge/{timestamp}_{Path(file.filename or 'unknown').name}",
        content_type=file.content_type,
    )

    doc_record = KnowledgeDocument(
        filename=file.filename or "unknown",
        file_type=file_suffix.lstrip("."),
        file_path=storage.get("file_url") or "",
        object_key=storage.get("object_key"),
        file_url=storage.get("file_url"),
        file_size=int(storage.get("size") or len(content)),
        storage_provider="minio",
        chunk_count=0,
        status="processing",
    )
    db.add(doc_record)
    db.commit()
    db.refresh(doc_record)

    try:
        tmp_dir = settings.data_dir / "tmp_parse"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=file_suffix,
            delete=False,
            dir=tmp_dir,
        ) as tmp_file:
            tmp_file.write(content)
            tmp_path = Path(tmp_file.name)

        try:
            chunks = parse_and_chunk(tmp_path)
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass

        if not chunks:
            doc_record.status = "empty"
            doc_record.error_message = "文件解析结果为空"
            db.commit()
            return KnowledgeUploadResponse(
                document_id=doc_record.id,
                filename=doc_record.filename,
                chunk_count=0,
                status="empty",
                file_url=doc_record.file_url,
            )

        indexed_count = index_document_chunks(
            chunks,
            source_file=file.filename or "unknown",
            extra_metadata={
                "document_id": doc_record.id,
                "object_key": doc_record.object_key or "",
                "file_url": doc_record.file_url or "",
            },
        )
        doc_record.chunk_count = indexed_count
        doc_record.status = "completed"
        db.commit()

        return KnowledgeUploadResponse(
            document_id=doc_record.id,
            filename=doc_record.filename,
            chunk_count=indexed_count,
            status="completed",
            file_url=doc_record.file_url,
        )
    except Exception as exc:
        logger.error("Document processing failed: %s", exc)
        doc_record.status = "failed"
        doc_record.error_message = str(exc)[:500]
        db.commit()
        return KnowledgeUploadResponse(
            document_id=doc_record.id,
            filename=doc_record.filename,
            chunk_count=0,
            status="failed",
            file_url=doc_record.file_url,
        )
@router.get("/knowledge/documents", response_model=KnowledgeListResponse)
def list_knowledge_documents(db: Session = Depends(get_db)) -> KnowledgeListResponse:
    docs = db.query(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc()).all()
    items = [
        KnowledgeDocumentItem(
            id=d.id,
            filename=d.filename,
            file_type=d.file_type,
            object_key=d.object_key,
            file_url=d.file_url,
            file_size=d.file_size,
            storage_provider=d.storage_provider,
            chunk_count=d.chunk_count,
            status=d.status,
            created_at=d.created_at,
        )
        for d in docs
    ]
    return KnowledgeListResponse(documents=items)


@router.delete("/knowledge/documents/{document_id}")
def delete_knowledge_document(
    document_id: int,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    try:
        from app.services.vector_store import delete_by_source
        delete_by_source(doc.filename)
    except Exception as exc:
        logger.warning("Failed to delete document from vector store: %s", exc)

    try:
        if doc.object_key:
            delete_minio_object(doc.object_key)
    except Exception as exc:
        logger.warning("Failed to delete document object from MinIO: %s", exc)

    db.delete(doc)
    db.commit()
    return {"message": "文档已删除"}


@router.get("/quick-questions", response_model=QuickQuestionListResponse)
def list_quick_questions(db: Session = Depends(get_db)) -> QuickQuestionListResponse:
    records = (
        db.query(QuickQuestion)
        .filter(QuickQuestion.is_active == True)
        .order_by(QuickQuestion.sort_order.asc(), QuickQuestion.id.asc())
        .all()
    )
    items = [
        QuickQuestionItem(id=q.id, question=q.question, category=q.category)
        for q in records
    ]
    return QuickQuestionListResponse(questions=items)


@router.get("/health/dependencies")
def chat_dependency_health() -> dict:
    ollama_ok, ollama_msg = check_ollama_health()
    remote_ok, remote_msg = check_remote_llm_health()
    minio_ok, minio_msg = check_minio_health()
    milvus_ok, milvus_msg = check_milvus_health()
    return {
        "ollama": {
            "enabled": True,
            "ok": ollama_ok,
            "message": ollama_msg,
        },
        "remote_llm": {
            "enabled": REMOTE_LLM_ENABLED,
            "ok": remote_ok,
            "message": remote_msg,
        },
        "web_search": {
            "enabled": WEB_SEARCH_ENABLED,
        },
        "minio": {
            "enabled": True,
            "ok": minio_ok,
            "message": minio_msg,
        },
        "milvus": {
            "enabled": True,
            "ok": milvus_ok,
            "message": milvus_msg,
        },
    }


@router.get("/health/runtime-config")
def chat_runtime_config() -> dict:
    return {
        "pid": os.getpid(),
        "runtime_config": get_runtime_config(),
    }


@router.get("/metrics/routing")
def chat_routing_metrics() -> dict:
    return snapshot_routing_metrics()


from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timedelta
from typing import Any

import ollama
from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

from app.services.vector_store import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    MILVUS_DB,
    MILVUS_HOST,
    MILVUS_METRIC_TYPE,
    MILVUS_PASSWORD,
    MILVUS_PORT,
    MILVUS_USER,
)

logger = logging.getLogger(__name__)

CHAT_MEMORY_COLLECTION = "chat_memory"
CHAT_MEMORY_ALIAS = "chat_memory_alias"
PROJECT_ID_NONE = -1
MEMORY_EXPIRE_DAYS = 90
MEMORY_CLEANUP_INTERVAL = timedelta(hours=6)

# Memory re-rank weights: relevance + time decay + project priority.
WEIGHT_RELEVANCE = 0.60
WEIGHT_TIME = 0.25
WEIGHT_PROJECT = 0.15

_last_cleanup_at: datetime | None = None


def _connect_milvus() -> None:
    try:
        # get_connection_addr may return {} for a missing alias in some pymilvus versions,
        # so we must verify address content instead of returning unconditionally.
        addr = connections.get_connection_addr(CHAT_MEMORY_ALIAS)
        if isinstance(addr, dict) and addr.get("address"):
            return
    except Exception:
        pass

    kwargs: dict[str, str] = {
        "alias": CHAT_MEMORY_ALIAS,
        "host": MILVUS_HOST,
        "port": MILVUS_PORT,
        "db_name": MILVUS_DB,
    }
    if MILVUS_USER:
        kwargs["user"] = MILVUS_USER
    if MILVUS_PASSWORD:
        kwargs["password"] = MILVUS_PASSWORD
    connections.connect(**kwargs)


def _ensure_chat_memory_collection() -> Collection:
    _connect_milvus()
    if utility.has_collection(CHAT_MEMORY_COLLECTION, using=CHAT_MEMORY_ALIAS):
        col = Collection(CHAT_MEMORY_COLLECTION, using=CHAT_MEMORY_ALIAS)
        col.load()
        return col

    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="session_id", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="project_id", dtype=DataType.INT64),
        FieldSchema(name="memory_type", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="question", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="answer", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="analysis_instruction", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="created_at", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="metadata_json", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
    ]
    schema = CollectionSchema(fields=fields, description="Long-term chat memories")
    col = Collection(name=CHAT_MEMORY_COLLECTION, schema=schema, using=CHAT_MEMORY_ALIAS)
    col.create_index(
        field_name="embedding",
        index_params={
            "index_type": "IVF_FLAT",
            "metric_type": MILVUS_METRIC_TYPE,
            "params": {"nlist": 1024},
        },
    )
    col.load()
    return col


def _safe_text(value: Any, max_len: int = 65535) -> str:
    text = "" if value is None else str(value)
    return text[:max_len]


def _entity_value(entity: Any, key: str, default: Any = None) -> Any:
    """Read a field from Milvus hit/entity across pymilvus variants."""
    if entity is None:
        return default

    if isinstance(entity, dict):
        return entity.get(key, default)

    # Some pymilvus Hit-like objects only support get(key) (no default arg).
    try:
        value = entity.get(key)  # type: ignore[attr-defined]
        return default if value is None else value
    except TypeError:
        pass
    except Exception:
        pass

    try:
        value = entity[key]  # type: ignore[index]
        return default if value is None else value
    except Exception:
        pass

    try:
        value = getattr(entity, key)
        return default if value is None else value
    except Exception:
        return default


def _contains_any(text: str, keywords: list[str]) -> bool:
    lower = (text or "").lower()
    return any(k in lower for k in keywords)


def _normalize_question(text: str) -> str:
    lowered = (text or "").lower()
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", lowered)
    return normalized[:512]


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        # Supports ISO strings like "2026-04-25T18:30:10.123456".
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _age_days(created_at: str | None, now: datetime | None = None) -> float:
    dt = _parse_datetime(created_at)
    if dt is None:
        return 99999.0
    current = now or datetime.utcnow()
    delta = current - dt
    return max(0.0, delta.total_seconds() / 86400.0)


def _fallback_embed(text: str) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    for i, ch in enumerate(text[:EMBEDDING_DIM]):
        vec[i] = ord(ch) / 65535.0
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0:
        return [v / norm for v in vec]
    return vec


def _embed_text(text: str) -> list[float]:
    try:
        response = ollama.embed(model=EMBEDDING_MODEL, input=[text])
        vectors = response.get("embeddings", [])
        if vectors and len(vectors[0]) == EMBEDDING_DIM:
            return vectors[0]
        if vectors and len(vectors[0]) != EMBEDDING_DIM:
            logger.warning(
                "chat_memory embedding dim mismatch: expected=%s got=%s",
                EMBEDDING_DIM,
                len(vectors[0]),
            )
    except Exception as exc:
        logger.warning("chat_memory embedding fallback used: %s", exc)
    return _fallback_embed(text)


def _infer_analysis_instruction(question: str, answer: str) -> str:
    merged = f"{question or ''}\n{answer or ''}".lower()
    if _contains_any(merged, ["拆分", "明细", "来源", "细分", "breakdown", "source"]):
        return "按排放源拆分并计算占比，输出重点排放源。"
    if _contains_any(merged, ["scope1", "scope 1", "scope2", "scope 2", "scope3", "scope 3", "scope"]):
        return "按Scope1/2/3归类并给出总量与占比。"
    if _contains_any(merged, ["趋势", "同比", "环比", "变化", "trend"]):
        return "进行趋势对比分析并解释波动原因。"
    if _contains_any(merged, ["建议", "优化", "减排", "措施", "suggestion"]):
        return "结合历史结论输出可执行减排建议。"
    return "基于项目排放数据给出结构化分析结论。"


def _infer_preferred_dimensions(question: str, answer: str) -> list[str]:
    merged = f"{question or ''}\n{answer or ''}".lower()
    dim_map = {
        "scope": ["scope", "scope1", "scope 1", "scope2", "scope 2", "scope3", "scope 3"],
        "source": ["排放源", "来源", "source", "明细", "拆分", "细分"],
        "ratio": ["占比", "比例", "ratio", "percentage"],
        "trend": ["趋势", "同比", "环比", "变化", "trend"],
        "total": ["总量", "汇总", "summary", "total"],
    }
    dims: list[str] = []
    for name, keys in dim_map.items():
        if _contains_any(merged, keys):
            dims.append(name)
    return dims


def _infer_memory_types(question: str, answer: str, project_id: int | None = None) -> list[str]:
    merged = f"{question or ''}\n{answer or ''}".lower()
    memory_types: list[str] = []

    if _contains_any(
        merged,
        ["scope", "排放源", "总量", "占比", "拆分", "明细", "汇总", "breakdown", "emission"],
    ):
        memory_types.append("business_analysis")

    if _contains_any(
        merged,
        ["偏好", "习惯", "默认", "常用", "优先", "以后都", "后续都", "prefer", "default"],
    ):
        memory_types.append("user_preference")
    elif project_id is not None and project_id > 0:
        memory_types.append("user_preference")

    if _contains_any(
        merged,
        ["重点排放源", "结论", "建议", "发现", "异常", "风险", "top source", "insight"],
    ):
        memory_types.append("historical_conclusion")

    if not memory_types:
        memory_types.append("business_analysis")
    return list(dict.fromkeys(memory_types))


def _build_memory_content(
    memory_type: str,
    session_id: str,
    project_id: int,
    question: str,
    analysis_instruction: str,
    answer: str,
) -> str:
    return (
        f"[memory_type]{memory_type}\n"
        f"[session_id]{session_id}\n"
        f"[project_id]{project_id}\n"
        f"[question]{question}\n"
        f"[analysis_instruction]{analysis_instruction}\n"
        f"[answer]{answer}"
    )


def _insert_memory_rows(col: Collection, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    session_ids: list[str] = []
    project_ids: list[int] = []
    types: list[str] = []
    questions: list[str] = []
    answers: list[str] = []
    instructions: list[str] = []
    contents: list[str] = []
    timestamps: list[str] = []
    metadatas: list[str] = []
    embeddings: list[list[float]] = []

    for row in rows:
        content = _safe_text(row.get("content", ""))
        metadata = row.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        session_ids.append(_safe_text(row.get("session_id", ""), 128))
        project_ids.append(int(row.get("project_id", PROJECT_ID_NONE)))
        types.append(_safe_text(row.get("memory_type", "business_analysis"), 64))
        questions.append(_safe_text(row.get("question", "")))
        answers.append(_safe_text(row.get("answer", "")))
        instructions.append(_safe_text(row.get("analysis_instruction", "")))
        contents.append(content)
        timestamps.append(_safe_text(row.get("created_at", datetime.utcnow().isoformat()), 64))
        metadatas.append(_safe_text(json.dumps(metadata, ensure_ascii=False)))
        embeddings.append(_embed_text(content))

    col.insert(
        [
            session_ids,
            project_ids,
            types,
            questions,
            answers,
            instructions,
            contents,
            timestamps,
            metadatas,
            embeddings,
        ]
    )
    col.flush()
    return len(rows)


def _delete_by_ids(col: Collection, ids: list[int]) -> int:
    if not ids:
        return 0
    deleted = 0
    chunk_size = 200
    for i in range(0, len(ids), chunk_size):
        chunk = ids[i : i + chunk_size]
        col.delete(expr=f"id in {chunk}")
        deleted += len(chunk)
    col.flush()
    return deleted


def _escape_milvus_string(value: str) -> str:
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')


def _is_duplicate_question(col: Collection, question: str, project_id: int, session_id: str | None = None) -> bool:
    key = _normalize_question(question)
    if not key:
        return False
    try:
        vector = _embed_text(question)
        expr = f"project_id == {project_id}"
        sid = (session_id or "").strip()
        if sid:
            expr += f' and session_id == "{_escape_milvus_string(sid)}"'
        results = col.search(
            data=[vector],
            anns_field="embedding",
            param={"metric_type": MILVUS_METRIC_TYPE, "params": {"nprobe": 16}},
            limit=12,
            expr=expr,
            output_fields=["question"],
        )
        for hit in (results[0] if results else []):
            entity = hit.entity
            candidate = _entity_value(entity, "question", "")
            if _normalize_question(candidate) == key:
                return True
    except Exception as exc:
        logger.warning("duplicate-check fallback to insert due to: %s", exc)
    return False


def _compress_text(text: str, max_len: int) -> str:
    raw = (text or "").strip()
    if len(raw) <= max_len:
        return raw
    return raw[: max_len - 3] + "..."


def _maybe_cleanup_expired_low_frequency_memories(col: Collection) -> int:
    global _last_cleanup_at

    now = datetime.utcnow()
    if _last_cleanup_at is not None and (now - _last_cleanup_at) < MEMORY_CLEANUP_INTERVAL:
        return 0
    _last_cleanup_at = now

    try:
        rows = col.query(
            expr="id >= 0",
            output_fields=[
                "id",
                "session_id",
                "project_id",
                "memory_type",
                "question",
                "answer",
                "analysis_instruction",
                "created_at",
                "metadata_json",
            ],
        )
    except Exception as exc:
        logger.warning("cleanup query failed: %s", exc)
        return 0

    expired: list[dict[str, Any]] = []
    for row in rows:
        age = _age_days(row.get("created_at"), now=now)
        if age > MEMORY_EXPIRE_DAYS:
            expired.append(row)
    if not expired:
        return 0

    grouped: dict[tuple[int, str, str], list[dict[str, Any]]] = {}
    for row in expired:
        pid = int(row.get("project_id", PROJECT_ID_NONE))
        mtype = _safe_text(row.get("memory_type", "business_analysis"), 64)
        qkey = _normalize_question(_safe_text(row.get("question", "")))
        group_key = (pid, mtype, qkey)
        grouped.setdefault(group_key, []).append(row)

    compressed_rows: list[dict[str, Any]] = []
    to_delete_ids: list[int] = []
    for (_, mtype, qkey), group_rows in grouped.items():
        # Low-frequency definition: a question key appears once in expired memories.
        if len(group_rows) != 1:
            continue
        row = group_rows[0]
        meta_raw = row.get("metadata_json") or "{}"
        try:
            meta = json.loads(meta_raw)
        except Exception:
            meta = {}
        if isinstance(meta, dict) and meta.get("compressed") is True:
            continue

        pid = int(row.get("project_id", PROJECT_ID_NONE))
        question = _safe_text(row.get("question", ""))
        answer = _safe_text(row.get("answer", ""))
        instruction = _safe_text(row.get("analysis_instruction", ""))
        created_at = _safe_text(row.get("created_at", now.isoformat()), 64)

        compact_instruction = _compress_text(instruction, 100)
        compact_answer = _compress_text(answer, 220)
        compact_content = _build_memory_content(
            memory_type=mtype,
            session_id=_safe_text(row.get("session_id", ""), 128),
            project_id=pid,
            question=_compress_text(question, 180),
            analysis_instruction=compact_instruction,
            answer=compact_answer,
        )

        new_meta = {
            "compressed": True,
            "compressed_at": now.isoformat(),
            "source_question_key": qkey,
            "original_id": row.get("id"),
            "frequency": 1,
            "project_id": None if pid == PROJECT_ID_NONE else pid,
        }
        compressed_rows.append(
            {
                "session_id": _safe_text(row.get("session_id", ""), 128),
                "project_id": pid,
                "memory_type": mtype,
                "question": question,
                "answer": compact_answer,
                "analysis_instruction": compact_instruction,
                "content": compact_content,
                "created_at": created_at,
                "metadata": new_meta,
            }
        )
        if row.get("id") is not None:
            to_delete_ids.append(int(row["id"]))

    if not compressed_rows:
        return 0

    inserted = _insert_memory_rows(col, compressed_rows)
    deleted = _delete_by_ids(col, to_delete_ids)
    logger.info(
        "chat_memory cleanup: compressed=%s deleted=%s",
        inserted,
        deleted,
    )
    return inserted


def archive_chat_memory_turn(
    session_id: str,
    question: str,
    answer: str,
    project_id: int | None = None,
    mode: str = "agent",
    references: list[str] | None = None,
    created_at: datetime | None = None,
) -> int:
    if not session_id or not question or not answer:
        return 0

    try:
        col = _ensure_chat_memory_collection()
        pid = int(project_id) if project_id is not None else PROJECT_ID_NONE

        # 1) Dedup: only skip exact same question in the same session+project bucket.
        if _is_duplicate_question(col, question, pid, session_id=session_id):
            return 0

        memory_types = _infer_memory_types(question, answer, project_id=project_id)
        analysis_instruction = _infer_analysis_instruction(question, answer)
        preferred_dimensions = _infer_preferred_dimensions(question, answer)
        created_iso = (created_at or datetime.utcnow()).isoformat()
        refs = references or []
        question_key = _normalize_question(question)

        rows: list[dict[str, Any]] = []
        for memory_type in memory_types:
            content = _build_memory_content(
                memory_type=memory_type,
                session_id=session_id,
                project_id=pid,
                question=question,
                analysis_instruction=analysis_instruction,
                answer=answer,
            )
            meta = {
                "session_id": session_id,
                "project_id": None if pid == PROJECT_ID_NONE else pid,
                "memory_type": memory_type,
                "mode": mode,
                "preferred_dimensions": preferred_dimensions,
                "question_key": question_key,
                "references": refs,
                "created_at": created_iso,
            }
            rows.append(
                {
                    "session_id": _safe_text(session_id, 128),
                    "project_id": pid,
                    "memory_type": _safe_text(memory_type, 64),
                    "question": _safe_text(question),
                    "answer": _safe_text(answer),
                    "analysis_instruction": _safe_text(analysis_instruction),
                    "content": _safe_text(content),
                    "created_at": _safe_text(created_iso, 64),
                    "metadata": meta,
                }
            )

        inserted = _insert_memory_rows(col, rows)

        # 4) Expired cleanup: compact low-frequency memories older than 90 days.
        try:
            _maybe_cleanup_expired_low_frequency_memories(col)
        except Exception as cleanup_exc:
            logger.warning("memory cleanup skipped due to error: %s", cleanup_exc)

        return inserted
    except Exception as exc:
        logger.error("archive_chat_memory_turn failed: %s", exc)
        return 0


def _project_score(candidate_project_id: int | None, current_project_id: int | None) -> float:
    if current_project_id is None:
        return 0.7 if candidate_project_id is None else 0.5
    if candidate_project_id == current_project_id:
        return 1.0
    if candidate_project_id is None:
        return 0.45
    return 0.0


def _time_decay_score(created_at: str | None) -> float:
    days = _age_days(created_at)
    # Exponential decay. Recent memories are naturally stronger.
    return math.exp(-days / 30.0)


def _relevance_score(distance: float) -> float:
    # For COSINE distance in current stack, smaller is better.
    # Clamp into [0, 1].
    return max(0.0, 1.0 - min(max(distance, 0.0), 1.0))


def _weighted_score(
    distance: float,
    created_at: str | None,
    candidate_project_id: int | None,
    current_project_id: int | None,
) -> float:
    relevance = _relevance_score(distance)
    freshness = _time_decay_score(created_at)
    project = _project_score(candidate_project_id, current_project_id)
    return (
        WEIGHT_RELEVANCE * relevance
        + WEIGHT_TIME * freshness
        + WEIGHT_PROJECT * project
    )


def recall_long_term_memories(
    question: str,
    project_id: int | None = None,
    top_k: int = 6,
) -> list[dict[str, Any]]:
    if not question:
        return []
    try:
        col = _ensure_chat_memory_collection()
        if col.num_entities == 0:
            return []

        vector = _embed_text(question)
        search_res = col.search(
            data=[vector],
            anns_field="embedding",
            param={"metric_type": MILVUS_METRIC_TYPE, "params": {"nprobe": 16}},
            limit=max(20, top_k * 6),
            output_fields=[
                "id",
                "session_id",
                "project_id",
                "memory_type",
                "question",
                "answer",
                "analysis_instruction",
                "created_at",
                "metadata_json",
            ],
        )

        memories: list[dict[str, Any]] = []
        for hit in (search_res[0] if search_res else []):
            entity = hit.entity
            if entity is None:
                continue
            raw_pid = int(_entity_value(entity, "project_id", PROJECT_ID_NONE))
            pid = None if raw_pid == PROJECT_ID_NONE else raw_pid

            meta_raw = _entity_value(entity, "metadata_json", "{}") or "{}"
            try:
                meta = json.loads(meta_raw)
            except Exception:
                meta = {}

            memories.append(
                {
                    "id": _entity_value(entity, "id"),
                    "session_id": _entity_value(entity, "session_id"),
                    "project_id": pid,
                    "memory_type": _entity_value(entity, "memory_type", "business_analysis") or "business_analysis",
                    "question": _entity_value(entity, "question", "") or "",
                    "answer": _entity_value(entity, "answer", "") or "",
                    "analysis_instruction": _entity_value(entity, "analysis_instruction", "") or "",
                    "created_at": _entity_value(entity, "created_at", "") or "",
                    "distance": float(hit.distance),
                    "metadata": meta if isinstance(meta, dict) else {},
                }
            )

        # 2 + 5) Project-priority recall + weighted re-rank.
        for item in memories:
            item["_score"] = _weighted_score(
                distance=float(item.get("distance", 1.0)),
                created_at=item.get("created_at"),
                candidate_project_id=item.get("project_id"),
                current_project_id=project_id,
            )

        memories.sort(
            key=lambda x: (
                -float(x.get("_score", 0.0)),
                float(x.get("distance", 1.0)),
            )
        )

        # De-duplicate recalled memories by normalized question key.
        deduped: list[dict[str, Any]] = []
        seen_q: set[str] = set()
        for item in memories:
            qkey = _normalize_question(item.get("question", ""))
            if qkey in seen_q:
                continue
            seen_q.add(qkey)
            item.pop("_score", None)
            deduped.append(item)
            if len(deduped) >= max(1, top_k):
                break

        return deduped
    except Exception as exc:
        logger.error("recall_long_term_memories failed: %s", exc)
        return []


def render_long_term_memory_context(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return ""

    sections: list[str] = []
    for idx, item in enumerate(memories, 1):
        memory_type = item.get("memory_type", "business_analysis")
        pid = item.get("project_id")
        pid_text = "无项目" if pid is None else f"项目ID={pid}"
        created = item.get("created_at", "")
        q = _safe_text(item.get("question", ""), 220)
        a = _safe_text(item.get("answer", ""), 360)
        instruction = _safe_text(item.get("analysis_instruction", ""), 120)
        dims = item.get("metadata", {}).get("preferred_dimensions", [])
        dims_text = f" | 偏好维度={','.join(dims)}" if isinstance(dims, list) and dims else ""
        sections.append(
            f"[长期记忆{idx}] 类型={memory_type} | {pid_text} | 时间={created}{dims_text}\n"
            f"- 历史问题: {q}\n"
            f"- 历史分析指令: {instruction}\n"
            f"- 历史结论: {a}"
        )
    return "\n\n".join(sections)


def delete_memories_by_session(session_id: str) -> int:
    if not session_id:
        return 0
    try:
        col = _ensure_chat_memory_collection()
        escaped = session_id.replace("\\", "\\\\").replace('"', '\\"')
        expr = f'session_id == "{escaped}"'
        rows = col.query(expr=expr, output_fields=["id"])
        ids = [int(r.get("id")) for r in rows if r.get("id") is not None]
        return _delete_by_ids(col, ids)
    except Exception as exc:
        logger.warning("delete_memories_by_session failed: %s", exc)
        return 0

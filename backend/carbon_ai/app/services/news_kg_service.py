from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.industry_news import IndustryNews
from app.services.graph_service import GraphEdge, upsert_knowledge_edges
from app.services.llm_gateway import chat_messages

logger = logging.getLogger(__name__)

NEWS_KG_ENABLED = os.getenv("NEWS_KG_ENABLED", "false").strip().lower() == "true"
NEWS_KG_MAX_TRIPLES_PER_ARTICLE = max(1, int(os.getenv("NEWS_KG_MAX_TRIPLES_PER_ARTICLE", "30")))
NEWS_KG_MIN_TEXT_LEN = max(40, int(os.getenv("NEWS_KG_MIN_TEXT_LEN", "80")))
NEWS_KG_EXTRACT_VERSION = os.getenv("NEWS_KG_EXTRACT_VERSION", "v1").strip() or "v1"

ENTITY_LABEL_MAP = {
    "政策": "Policy",
    "行业": "Industry",
    "企业": "Enterprise",
    "园区": "Park",
    "工业园区": "Park",
    "专业术语": "Term",
    "术语": "Term",
    "核算标准": "Standard",
    "排放源": "EmissionSource",
}

RELATION_MAP = {
    "属于": "BELONGS_TO",
    "包含": "INCLUDES",
    "适用": "APPLIES_TO",
    "发布": "PUBLISHED_BY",
    "引用": "CITES",
    "对标": "BENCHMARKS",
    "管控": "GOVERNS",
    "关联": "ASSOCIATED_WITH",
    "下级": "HAS_CHILD",
    "依据": "BASED_ON",
}

EXTRA_ALLOWED_RELATION_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{1,63}$")

EXTRACT_SYSTEM_PROMPT = """你是双碳领域知识抽取专家，负责从政策/行业资讯正文里抽取知识图谱的实体、关系与属性。
严格只输出JSON，不要解释、不要多余文字。"""

EXTRACT_USER_TEMPLATE = """约束规则：
1. 只抽取双碳、环保、节能、碳市场、园区低碳、CBAM、CCER、碳排放核算相关实体。
2. 实体固定类型只能选：【政策、行业、企业、园区、专业术语、核算标准、排放源】
3. 关系语义要简洁，例如：适用、发布、包含、属于、引用、对标、管控、关联、下级、依据。
4. 输出严格遵循下面JSON结构，多条放在数组里。
5. 无关内容不要抽取，宁缺毋滥。

输出固定JSON格式：
[
  {
    "entity_a": "实体名称A",
    "type_a": "实体类型A",
    "relation": "关系描述",
    "entity_b": "实体名称B",
    "type_b": "实体类型B"
  }
]

资讯内容：
标题：{title}
来源：{source_name}
发布时间：{published_at}
正文：
{content}
"""


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    raw = _safe_text(text)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception:
        pass

    m = re.search(r"\[.*\]", raw, flags=re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception:
        return []
    return []


def _normalize_relation(raw_relation: str) -> str | None:
    rel = _safe_text(raw_relation)
    if not rel:
        return None
    mapped = RELATION_MAP.get(rel)
    if mapped:
        return mapped
    # Accept already-normalized enum style relations from model output.
    upper = rel.upper().replace(" ", "_").replace("-", "_")
    if EXTRA_ALLOWED_RELATION_PATTERN.match(upper):
        return upper
    return None


def _normalize_label(raw_type: str) -> str | None:
    t = _safe_text(raw_type)
    if not t:
        return None
    return ENTITY_LABEL_MAP.get(t)


def _llm_extract_triples(title: str, content: str, source_name: str = "", published_at: str = "") -> list[dict[str, Any]]:
    user_prompt = EXTRACT_USER_TEMPLATE.format(
        title=_safe_text(title)[:300],
        source_name=_safe_text(source_name)[:120],
        published_at=_safe_text(published_at)[:40],
        content=_safe_text(content)[:6000],
    )
    out = chat_messages(
        [
            {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        task="agent",
        contains_sensitive=False,
    )
    return _extract_json_array(out)


def _build_edges(rows: list[dict[str, Any]]) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for item in rows[:NEWS_KG_MAX_TRIPLES_PER_ARTICLE]:
        a = _safe_text(item.get("entity_a"))[:120]
        b = _safe_text(item.get("entity_b"))[:120]
        type_a = _normalize_label(item.get("type_a"))
        type_b = _normalize_label(item.get("type_b"))
        rel = _normalize_relation(item.get("relation"))
        if not a or not b or not type_a or not type_b or not rel:
            continue
        key = (type_a, a, rel, type_b, b)
        if key in seen:
            continue
        seen.add(key)
        edges.append(
            GraphEdge(
                source_label=type_a,
                source_name=a,
                relation=rel,
                target_label=type_b,
                target_name=b,
                props={"source": "industry_news_auto"},
            )
        )
    return edges


def ingest_news_text_to_kg(title: str, content: str, source_name: str = "", published_at: str = "") -> dict[str, Any]:
    if not NEWS_KG_ENABLED:
        return {"ok": False, "error": "news_kg_disabled", "count": 0}

    merged = f"{_safe_text(title)}\n{_safe_text(content)}".strip()
    if len(merged) < NEWS_KG_MIN_TEXT_LEN:
        return {"ok": False, "error": "content_too_short", "count": 0}

    try:
        triples = _llm_extract_triples(
            title=title,
            content=content,
            source_name=source_name,
            published_at=published_at,
        )
        edges = _build_edges(triples)
        if not edges:
            return {"ok": True, "count": 0, "message": "no_valid_triples"}
        res = upsert_knowledge_edges(edges)
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error", "kg_write_failed"), "count": 0}
        return {"ok": True, "count": int(res.get("count", 0)), "message": "ok"}
    except Exception as exc:
        logger.warning("news->kg ingest failed: %s", exc)
        return {"ok": False, "error": str(exc), "count": 0}


def ingest_news_row_to_kg(news: IndustryNews) -> dict[str, Any]:
    title = _safe_text(news.title)
    content = _safe_text(news.summary)
    source_name = _safe_text(news.source_name)
    published = news.published_at.isoformat() if news.published_at else ""
    return ingest_news_text_to_kg(title=title, content=content, source_name=source_name, published_at=published)


def _window_delta(time_window: str) -> timedelta | None:
    key = (time_window or "all").strip().lower()
    mapping = {
        "1d": timedelta(days=1),
        "1w": timedelta(weeks=1),
        "1m": timedelta(days=30),
        "1q": timedelta(days=90),
        "1y": timedelta(days=365),
        "3y": timedelta(days=365 * 3),
        "5y": timedelta(days=365 * 5),
        "all": None,
    }
    return mapping.get(key, timedelta(days=30))


def _mark_news_kg_status(news: IndustryNews, ok: bool, count: int, error: str = "", extract_version: str = NEWS_KG_EXTRACT_VERSION) -> None:
    news.kg_extract_version = extract_version[:32]
    news.kg_extracted_at = datetime.utcnow()
    if ok and count > 0:
        news.kg_last_status = "success"
        news.kg_last_error = ""
        return
    if ok and count <= 0:
        news.kg_last_status = "skipped"
        news.kg_last_error = ""
        return
    news.kg_last_status = "failed"
    news.kg_last_error = _safe_text(error)[:1000]


def ingest_news_row_to_kg_with_tracking(
    db: Session,
    news: IndustryNews,
    force: bool = False,
    extract_version: str = NEWS_KG_EXTRACT_VERSION,
) -> dict[str, Any]:
    version = (extract_version or NEWS_KG_EXTRACT_VERSION).strip()[:32] or NEWS_KG_EXTRACT_VERSION
    if not force and news.kg_last_status == "success" and (news.kg_extract_version or "") == version:
        return {"ok": True, "count": 0, "message": "already_extracted"}

    result = ingest_news_row_to_kg(news)
    ok = bool(result.get("ok"))
    count = int(result.get("count", 0) or 0)
    error = _safe_text(result.get("error"))
    _mark_news_kg_status(news, ok=ok, count=count, error=error, extract_version=version)
    db.add(news)
    return result


def backfill_news_to_kg(
    db: Session,
    limit: int = 500,
    source_name: str | None = None,
    time_window: str = "1m",
    force: bool = False,
    extract_version: str = NEWS_KG_EXTRACT_VERSION,
) -> dict[str, int]:
    if not NEWS_KG_ENABLED:
        return {"scanned": 0, "written": 0, "failed": 0, "skipped": 0}

    lim = max(1, min(int(limit), 5000))
    version = (extract_version or NEWS_KG_EXTRACT_VERSION).strip()[:32] or NEWS_KG_EXTRACT_VERSION
    query = db.query(IndustryNews)
    if source_name:
        query = query.filter(IndustryNews.source_name.contains(source_name.strip()))
    delta = _window_delta(time_window)
    if delta is not None:
        since = datetime.utcnow() - delta
        query = query.filter(IndustryNews.fetched_at >= since)
    if not force:
        query = query.filter(
            (IndustryNews.kg_extract_version != version) | (IndustryNews.kg_last_status != "success")
        )
    rows = query.order_by(IndustryNews.fetched_at.desc()).limit(lim).all()

    scanned = 0
    written = 0
    failed = 0
    skipped = 0
    for row in rows:
        scanned += 1
        result = ingest_news_row_to_kg_with_tracking(db=db, news=row, force=force, extract_version=version)
        if not result.get("ok"):
            if result.get("error") in {"content_too_short", "news_kg_disabled"}:
                skipped += 1
            else:
                failed += 1
            continue
        count = int(result.get("count", 0))
        if count <= 0:
            skipped += 1
        else:
            written += count
    db.commit()
    return {"scanned": scanned, "written": written, "failed": failed, "skipped": skipped}

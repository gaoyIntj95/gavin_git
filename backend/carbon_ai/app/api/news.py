from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.schemas.news import (
    IndustryNewsKGBackfillResponse,
    IndustryNewsItem,
    IndustryNewsListResponse,
    IndustryNewsManualAddResponse,
    IndustryNewsRefreshStartResponse,
    IndustryNewsRefreshStatusResponse,
    IndustryNewsSemanticSearchResponse,
    NewsDebugResponse,
    NewsRefreshWithFallbackResponse,
)
from app.services.news_kg_service import backfill_news_to_kg
from app.services.news_service import (
    debug_news_system,
    hybrid_search_industry_news,
    latest_news_fetched_at,
    list_industry_news_paginated,
    manual_add_industry_news,
    refresh_industry_news,
    refresh_news_with_fallback,
)

router = APIRouter(prefix="/news", tags=["news"])


_refresh_lock = threading.Lock()
_refresh_tasks: dict[str, dict] = {}
_latest_task_id: str | None = None
# Keep refresh async responsive; avoid frontend endless polling.
REFRESH_TASK_TIMEOUT_SEC = 300


def _to_item(row) -> IndustryNewsItem:
    try:
        tags = json.loads(row.tags_json or "[]")
        if not isinstance(tags, list):
            tags = []
    except Exception:
        tags = []
    return IndustryNewsItem(
        id=row.id,
        title=row.title,
        summary=row.summary,
        source_name=row.source_name,
        source_url=row.source_url,
        tags=tags,
        published_at=row.published_at,
        fetched_at=row.fetched_at,
    )


def _run_refresh_task(task_id: str, force: bool, time_window: str) -> None:
    try:
        with _refresh_lock:
            _refresh_tasks[task_id]["status"] = "running"
            _refresh_tasks[task_id]["started_at"] = datetime.utcnow().isoformat()

        def _refresh_job() :
            inner_db = SessionLocal()
            try:
                return refresh_news_with_fallback(inner_db, force=force, time_window=time_window)
            finally:
                inner_db.close()

        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(_refresh_job)
        try:
            stat = future.result(timeout=REFRESH_TASK_TIMEOUT_SEC)
        except FuturesTimeoutError:
            future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            with _refresh_lock:
                _refresh_tasks[task_id].update(
                    {
                        "status": "failed",
                        "message": f"News refresh timed out (>{REFRESH_TASK_TIMEOUT_SEC}s). Please retry later.",
                        "finished_at": datetime.utcnow().isoformat(),
                    }
                )
            return
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        with _refresh_lock:
            _refresh_tasks[task_id].update(
                {
                    "status": "completed",
                    "fetched": stat.fetched,
                    "inserted": stat.inserted,
                    "updated": stat.updated,
                    "skipped": stat.skipped,
                    "embedded": stat.embedded,
                    "filtered": stat.filtered,
                    "pruned": stat.pruned,
                    "fallback_layer": stat.fallback_layer,
                    "source": stat.source,
                    "message": stat.message,
                    "source_details": stat.source_details,
                    "finished_at": datetime.utcnow().isoformat(),
                }
            )
    except Exception as exc:
        with _refresh_lock:
            _refresh_tasks[task_id].update(
                {
                    "status": "failed",
                    "message": f"News refresh failed: {exc}",
                    "finished_at": datetime.utcnow().isoformat(),
                }
            )


@router.get("/list", response_model=IndustryNewsListResponse)
def get_news_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    time_window: str = Query(default="1w", pattern="^(1d|1w|1m|1q|1y|3y|5y|all)$"),
    track_tag: str | None = Query(default=None),
    question: str | None = Query(default=None),
    auto_refresh: bool = Query(default=False),
    stale_hours: int = Query(default=6, ge=1, le=48),
    db: Session = Depends(get_db),
) -> IndustryNewsListResponse:
    # Background refresh: if data is stale, trigger async refresh but don't block response.
    # The frontend should explicitly call POST /news/refresh for a fresh crawl.
    if auto_refresh:
        latest = latest_news_fetched_at(db)
        if latest is None or latest < datetime.utcnow() - timedelta(hours=stale_hours):
            # Fire-and-forget: don't block the list query
            def _bg_refresh():
                bg_db = SessionLocal()
                try:
                    refresh_news_with_fallback(bg_db, force=False, time_window=time_window)
                except Exception:
                    pass
                finally:
                    bg_db.close()

            threading.Thread(target=_bg_refresh, daemon=True).start()

    rows, total, total_pages = list_industry_news_paginated(
        db=db,
        page=page,
        page_size=page_size,
        time_window=time_window,
        track_tag=track_tag,
        question=question,
    )
    items = [_to_item(r) for r in rows]
    return IndustryNewsListResponse(
        data=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("/refresh", response_model=IndustryNewsRefreshStartResponse)
def refresh_news(
    force: bool = Query(default=False),
    time_window: str = Query(default="1w", pattern="^(1d|1w|1m|1q|1y|3y|5y|all)$"),
) -> IndustryNewsRefreshStartResponse:
    global _latest_task_id
    task_id = uuid.uuid4().hex
    with _refresh_lock:
        _refresh_tasks[task_id] = {
            "task_id": task_id,
            "status": "queued",
            "fetched": 0,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "embedded": 0,
            "filtered": 0,
            "pruned": 0,
            "message": "任务已创建",
            "time_window": time_window,
        }
        _latest_task_id = task_id
    thread = threading.Thread(target=_run_refresh_task, args=(task_id, force, time_window), daemon=True)
    thread.start()
    return IndustryNewsRefreshStartResponse(
        task_id=task_id,
        status="queued",
        message="刷新任务已启动，后台执行中",
    )


@router.get("/refresh-status", response_model=IndustryNewsRefreshStatusResponse)
def refresh_news_status(task_id: str | None = Query(default=None)) -> IndustryNewsRefreshStatusResponse:
    with _refresh_lock:
        target = task_id or _latest_task_id
        if not target or target not in _refresh_tasks:
            return IndustryNewsRefreshStatusResponse(
                task_id=task_id or "",
                status="not_found",
                message="未找到刷新任务",
            )
        task = _refresh_tasks[target]
        # watchdog: if still running beyond timeout, force fail to unblock frontend polling
        status_now = str(task.get("status", "unknown"))
        if status_now in {"queued", "running"}:
            started_raw = str(task.get("started_at", "") or "").strip()
            if started_raw:
                try:
                    started_at = datetime.fromisoformat(started_raw)
                    if datetime.utcnow() - started_at > timedelta(seconds=REFRESH_TASK_TIMEOUT_SEC):
                        task.update(
                            {
                                "status": "failed",
                                "message": f"News refresh timed out (>{REFRESH_TASK_TIMEOUT_SEC}s). Please retry later.",
                                "finished_at": datetime.utcnow().isoformat(),
                            }
                        )
                except Exception:
                    pass
    source_details_raw = task.get("source_details", [])
    if isinstance(source_details_raw, list):
        source_details = [str(x) for x in source_details_raw]
    else:
        source_details = []

    return IndustryNewsRefreshStatusResponse(
        task_id=target,
        status=task.get("status", "unknown"),
        fetched=int(task.get("fetched", 0) or 0),
        inserted=int(task.get("inserted", 0) or 0),
        updated=int(task.get("updated", 0) or 0),
        skipped=int(task.get("skipped", 0) or 0),
        embedded=int(task.get("embedded", 0) or 0),
        filtered=int(task.get("filtered", 0) or 0),
        pruned=int(task.get("pruned", 0) or 0),
        fallback_layer=int(task.get("fallback_layer", 0) or 0),
        source=str(task.get("source", "")),
        message=str(task.get("message", "")),
        source_details=source_details,
    )


@router.get("/search", response_model=IndustryNewsSemanticSearchResponse)
def search_news(
    question: str = Query(..., min_length=2),
    track_tag: str | None = Query(default=None),
    time_window: str = Query(default="1w", pattern="^(1d|1w|1m|1q|1y|3y|5y|all)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> IndustryNewsSemanticSearchResponse:
    rows = hybrid_search_industry_news(
        db=db,
        question=question,
        track_tag=track_tag,
        top_k=100,
        time_window=time_window,
    )
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 0
    start = (page - 1) * page_size
    page_rows = rows[start : start + page_size]
    items = [_to_item(r) for r in page_rows]
    return IndustryNewsSemanticSearchResponse(
        data=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        question=question,
        track_tag=track_tag,
    )


@router.post("/manual-add", response_model=IndustryNewsManualAddResponse)
def manual_add_news(
    url: str = Query(..., min_length=8),
    db: Session = Depends(get_db),
) -> IndustryNewsManualAddResponse:
    try:
        result = manual_add_industry_news(db=db, url=url)
        item = _to_item(result.item) if result.item else None
        return IndustryNewsManualAddResponse(
            success=result.success,
            message=result.message,
            item=item,
        )
    except Exception as exc:
        return IndustryNewsManualAddResponse(
            success=False,
            message=f"手动添加失败: {exc}",
            item=None,
        )


@router.post("/kg/backfill", response_model=IndustryNewsKGBackfillResponse)
def backfill_news_kg(
    limit: int = Query(default=500, ge=1, le=5000),
    source_name: str | None = Query(default=None),
    time_window: str = Query(default="1m", pattern="^(1d|1w|1m|1q|1y|3y|5y|all)$"),
    force: bool = Query(default=False),
    extract_version: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> IndustryNewsKGBackfillResponse:
    try:
        stats = backfill_news_to_kg(
            db=db,
            limit=limit,
            source_name=source_name,
            time_window=time_window,
            force=force,
            extract_version=extract_version or "",
        )
        return IndustryNewsKGBackfillResponse(
            success=True,
            scanned=int(stats.get("scanned", 0)),
            written=int(stats.get("written", 0)),
            failed=int(stats.get("failed", 0)),
            skipped=int(stats.get("skipped", 0)),
            message="ok",
        )
    except Exception as exc:
        return IndustryNewsKGBackfillResponse(
            success=False,
            scanned=0,
            written=0,
            failed=0,
            skipped=0,
            message=f"kg backfill failed: {exc}",
        )


# ---------------------------------------------------------------------------
# Debug endpoint — full system state inspection
# ---------------------------------------------------------------------------

@router.get("/debug", response_model=NewsDebugResponse)
def debug_news(
    time_window: str = Query(default="1w", pattern="^(1d|1w|1m|1q|1y|3y|5y|all)$"),
    db: Session = Depends(get_db),
) -> NewsDebugResponse:
    """Return full debug snapshot of the news system: DB state, sources, cooldown, etc."""
    data = debug_news_system(db, time_window=time_window)
    return NewsDebugResponse(**data)


# ---------------------------------------------------------------------------
# Sync refresh with three-tier fallback (returns result directly, no polling)
# ---------------------------------------------------------------------------

@router.post("/refresh-sync", response_model=NewsRefreshWithFallbackResponse)
def refresh_news_sync(
    force: bool = Query(default=False),
    time_window: str = Query(default="1w", pattern="^(1d|1w|1m|1q|1y|3y|5y|all)$"),
    db: Session = Depends(get_db),
) -> NewsRefreshWithFallbackResponse:
    """Synchronous news refresh with three-tier fallback.

    Returns the result immediately with full trace logs.
    Tier 0: live scrape → Tier 1: keyword API → Tier 2: DB cache.
    """
    result = refresh_news_with_fallback(db, force=force, time_window=time_window)
    return NewsRefreshWithFallbackResponse(
        fetched=result.fetched,
        inserted=result.inserted,
        updated=result.updated,
        skipped=result.skipped,
        filtered=result.filtered,
        pruned=result.pruned,
        embedded=result.embedded,
        fallback_layer=result.fallback_layer,
        source=result.source,
        message=result.message,
        source_details=result.source_details,
        trace=result.trace,
        db_cached_count=result.db_cached_count,
    )

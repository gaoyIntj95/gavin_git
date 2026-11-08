from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import email.utils
import hashlib
import math
import json
import logging
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any
import urllib.request
import xml.etree.ElementTree as ET
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from sqlalchemy import and_, func, inspect, or_, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.industry_news import IndustryNews
from app.services.llm_gateway import chat_messages
from app.services.news_kg_service import ingest_news_row_to_kg_with_tracking
from app.services.vector_store import (
    add_news_documents,
    delete_news_by_source,
    max_cosine_similarity,
    reset_news_collection,
    similarity_search_news,
)

logger = logging.getLogger(__name__)

CRAWLER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 "
    "Carbon-AI-NewsBot/1.0"
)
CRAWLER_REFERER = "https://carbon-ai.local/"
CRAWLER_MIN_DELAY_SEC = 2.0
CRAWLER_MAX_DELAY_SEC = 5.0
CRAWLER_TIMEOUT_SEC = 12
SOURCE_FETCH_TIMEOUT_SEC = 20
CRAWLER_COOLDOWN_HOURS = 1
MAX_ITEMS_PER_SOURCE = 20
SUMMARY_MAX_LEN = 140
AI_SUMMARY_MAX_LEN = 180
FETCH_RETRY_TIMES = 2
FETCH_BACKOFF_SEC = 1.5
NEWS_VECTOR_SOURCE_PREFIX = "industry_news:"
DEFAULT_SEMANTIC_TOP_K = 5
MAX_NEWS_RETURN = 100
MAX_FETCH_PER_REFRESH = 200
ACTIVE_CRAWL_WINDOWS = {"1d", "1w", "1m"}
HTML_MAX_LINKS_SCAN = 120
HTML_MIN_TITLE_LEN = 8
HTML_MAX_TITLE_LEN = 120
HTML_SUMMARY_LEN = 220
MIN_VALID_SUMMARY_LEN = 60
HTML_LIST_MAX_PAGES = 3

TRACK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "政策法规": ("政策", "条例", "办法", "通知", "指导意见", "实施方案", "国家发改委", "生态环境部", "能源局", "部委"),
    "工业低碳": ("绿色制造", "绿色工厂", "工业节能", "降碳", "能效", "工业园", "制造业", "节能改造"),
    "零碳园区": ("零碳园区", "低碳园区", "零碳建筑", "绿色建筑", "园区", "近零碳"),
    "碳市场": ("碳市场", "碳交易", "碳配额", "全国碳市场", "ccer", "碳核查", "履约", "配额"),
    "ESG": ("esg", "可持续发展", "绿色金融", "社会责任", "信息披露", "治理"),
    "新能源": ("光伏", "风电", "储能", "氢能", "新能源", "清洁能源", "充电桩"),
    "循环经济": ("循环经济", "资源综合利用", "再生资源", "节能环保", "固废", "减量化", "资源化"),
    "国际碳政策": ("cbam", "欧盟碳关税", "碳边境", "巴黎协定", "气候公约", "cop", "国际气候"),
}

CARBON_CORE_KEYWORDS = [
    # 核心目标类
    "双碳", "碳达峰", "碳中和", "低碳", "零碳", "降碳", "碳减排", "碳排放", "节能降碳", "绿色低碳", "低碳转型", "零碳转型",
    # 零碳体系
    "零碳", "零碳园区", "零碳工厂", "零碳建筑", "零碳城市", "零碳社区", "零碳产业", "零碳技术", "近零排放", "零碳目标",
    # 能源电力类
    "新能源", "绿电", "清洁能源", "可再生能源", "光伏", "风电", "储能", "风光储", "源网荷储", "虚拟电厂", "氢能", "绿氢", "煤电替代", "电力系统", "电网", "能效提升",
    # 碳市场与碳管理
    "碳市场", "碳交易", "ccer", "碳汇", "碳配额", "碳核算", "碳盘查", "碳足迹", "碳披露", "碳资产", "碳核查", "碳管理", "碳金融", "绿色金融", "ccus", "负碳技术",
    # 绿色制造/工业/园区
    "绿色制造", "绿色工厂", "绿色园区", "绿色供应链", "循环经济", "工业节能", "节能改造", "超低排放", "绿色建材", "绿色建筑",
    # 建筑/交通/城市
    "低碳建筑", "低碳交通", "绿色建筑", "超低能耗建筑", "新能源汽车", "绿色交通", "低碳城市", "智慧城市",
    # ESG与可持续发展
    "esg", "可持续发展", "绿色发展", "生态文明", "绿色低碳发展", "气候治理",
    # 数字化碳平台
    "碳平台", "碳管理平台", "数字化碳平台", "智慧碳平台", "碳数据平台", "双碳平台", "碳管控平台", "碳监测", "碳预警", "智慧双碳", "数字碳管理", "企业碳管理", "碳saas", "碳中台",
    # 节能设备 / 节能装备 / 低碳设备
    "节能设备", "节能装备", "节能器械", "高效节能设备", "工业节能设备",
    "节电设备", "节水设备", "余热利用设备", "余压回收", "节能风机", "节能水泵",
    # 节能技术 & 改造
    "节能技术", "节能技改", "能效改造", "设备升级", "节能降耗",
    "工业能效", "电机节能", "锅炉节能", "暖通节能", "空调节能",
    # 环保治理设备 & 减碳装备
    "环保设备", "废气治理", "废水处理", "固废处置", "除尘设备",
    "低碳装备", "减碳设备", "碳捕集设备", "节能系统",
    # 政策资金/补贴类（手动资讯常见）
    "资金补贴", "财政补贴", "奖补", "专项资金", "扶持政策", "支持政策", "补助", "贴息",
    # 国际/政策
    "碳关税", "cbam", "巴黎协定", "ndc", "气候目标", "绿色壁垒",
]
CARBON_WEAK_BLACKLIST = [
    "农业", "农业农村", "外交", "外事", "建交", "会见", "党建", "军事", "文化", "经济形势", "地方会议", "经济会议", "义乌经验", "党史",
]
CONTENT_GARBAGE_BLACKLIST = [
    "ICP备案", "网站备案", "京ICP备", "公网安备", "版权声明", "网站公告", "隐私政策", "联系我们",
]
SEMANTIC_NEWS_PROTOTYPES = [
    "双碳政策 碳达峰 碳中和 绿色低碳转型",
    "节能降碳 财政补贴 奖补 专项资金 支持政策",
    "碳市场 碳交易 CCER 碳核查 碳履约",
    "零碳园区 零碳工厂 绿色制造 工业低碳",
    "新能源 光伏 风电 储能 氢能 清洁能源",
    "ESG 可持续发展 绿色金融 绿色供应链",
]
SEMANTIC_RELEVANCE_THRESHOLD = float(os.getenv("NEWS_SEMANTIC_RELEVANCE_THRESHOLD", "0.52"))
CARBON_RELAXED_SOURCES = ("中国政府网", "发改委", "生态环境部", "工信部")

NEWS_WHITELIST = [
    # 稳定官方/权威行业来源（HTML）
    {"name": "生态环境部-要闻", "url": "https://www.mee.gov.cn/ywdt/szyw/", "kind": "html"},
    {"name": "发改委-新闻", "url": "https://www.ndrc.gov.cn/xwdt/", "kind": "html"},
    {"name": "国家能源局-新闻", "url": "http://www.nea.gov.cn/xwzx/index.htm", "kind": "html"},
    {"name": "工信部-节能与绿色发展", "url": "https://www.miit.gov.cn/jgsj/jns/", "kind": "html"},
    {"name": "中国政府网-政策", "url": "https://www.gov.cn/zhengce/zuixin/", "kind": "html"},
    {"name": "住建部-绿色建筑", "url": "https://www.mohurd.gov.cn/xinwen/gzdt/", "kind": "html"},
    {"name": "全国碳市场-动态", "url": "https://www.cneeex.com/", "kind": "html"},
    {"name": "北极星环保网-双碳", "url": "https://huanbao.bjx.com.cn/ditan/", "kind": "html"},
    {"name": "中国环境报-双碳", "url": "https://www.cenews.com.cn/", "kind": "html"},
]

NEWS_TIME_WINDOW_DEFAULT = "1w"  # 1d / 1w / 1m / 1q / 1y / 3y / all
NEWS_TIME_WINDOWS = {
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "1m": timedelta(days=30),
    "1q": timedelta(days=90),
    "1y": timedelta(days=365),
    "3y": timedelta(days=365 * 3),
    "all": None,
}

POLICY_KEYWORDS = [
    "双碳政策", "双碳资讯", "碳中和政策", "碳达峰政策",
    "零碳政策", "碳市场政策", "节能降碳政策",
    "绿色制造政策", "新能源政策", "CCER政策",
]

KEYWORD_SEARCH_SOURCES = [
    {"name": "中国政府网搜索", "url_template": "https://sousuo.www.gov.cn/s.htm?t=zhengce&q={q}"},
    {"name": "国家发改委站内搜索", "url_template": "https://so.ndrc.gov.cn/s?qt={q}"},
    {"name": "生态环境部站内搜索", "url_template": "https://www.mee.gov.cn/was5/web/search?channelid=233571&searchword={q}"},
]

NEWS_RETENTION_DAYS = int(os.getenv("NEWS_RETENTION_DAYS", "0"))


@dataclass
class RefreshStats:
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    cooldown_until: datetime | None = None
    message: str = ""
    embedded: int = 0
    filtered: int = 0
    pruned: int = 0
    source_details: list[str] = field(default_factory=list)


@dataclass
class ManualAddResult:
    success: bool
    message: str
    item: IndustryNews | None = None


_news_schema_checked = False


def _state_file() -> Path:
    path = settings.data_dir / "crawler_state" / "industry_news_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_news_schema(db: Session) -> None:
    global _news_schema_checked
    if _news_schema_checked:
        return
    try:
        table = IndustryNews.__tablename__
        existing = {c["name"] for c in inspect(db.bind).get_columns(table)}
        if "tags_json" not in existing:
            dialect = db.bind.dialect.name.lower()
            if dialect in {"mysql", "mariadb"}:
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN tags_json TEXT NOT NULL"))
                db.execute(text(f"UPDATE {table} SET tags_json='[]' WHERE tags_json IS NULL OR tags_json=''"))
            elif dialect == "sqlite":
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'"))
            else:
                logger.warning("tags_json missing, unsupported auto-migration dialect: %s", dialect)
            db.commit()
        if "fingerprint" not in existing:
            dialect = db.bind.dialect.name.lower()
            if dialect in {"mysql", "mariadb"}:
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN fingerprint VARCHAR(32) NOT NULL DEFAULT ''"))
            elif dialect == "sqlite":
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN fingerprint VARCHAR(32) NOT NULL DEFAULT ''"))
            else:
                logger.warning("fingerprint missing, unsupported auto-migration dialect: %s", dialect)
            db.commit()
            existing.add("fingerprint")
        dialect = db.bind.dialect.name.lower()
        if "kg_extract_version" not in existing:
            if dialect in {"mysql", "mariadb"}:
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN kg_extract_version VARCHAR(32) NOT NULL DEFAULT ''"))
            elif dialect == "sqlite":
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN kg_extract_version VARCHAR(32) NOT NULL DEFAULT ''"))
            db.commit()
            existing.add("kg_extract_version")
        if "kg_extracted_at" not in existing:
            if dialect in {"mysql", "mariadb"}:
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN kg_extracted_at DATETIME NULL"))
            elif dialect == "sqlite":
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN kg_extracted_at DATETIME"))
            db.commit()
            existing.add("kg_extracted_at")
        if "kg_last_status" not in existing:
            if dialect in {"mysql", "mariadb"}:
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN kg_last_status VARCHAR(32) NOT NULL DEFAULT ''"))
            elif dialect == "sqlite":
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN kg_last_status VARCHAR(32) NOT NULL DEFAULT ''"))
            db.commit()
            existing.add("kg_last_status")
        if "kg_last_error" not in existing:
            if dialect in {"mysql", "mariadb"}:
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN kg_last_error TEXT NOT NULL"))
                db.execute(text(f"UPDATE {table} SET kg_last_error='' WHERE kg_last_error IS NULL"))
            elif dialect == "sqlite":
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN kg_last_error TEXT NOT NULL DEFAULT ''"))
            db.commit()
            existing.add("kg_last_error")
        _backfill_news_fingerprint(db)
        _dedupe_existing_news(db)
        _ensure_unique_indexes(db, table)
        _news_schema_checked = True
    except Exception as exc:
        logger.warning("ensure news schema failed: %s", _safe_log_text(exc))


def _ensure_unique_indexes(db: Session, table: str) -> None:
    try:
        existing_indexes = {idx.get("name") for idx in inspect(db.bind).get_indexes(table)}
    except Exception:
        existing_indexes = set()
    try:
        if "ux_industry_news_source_url" not in existing_indexes:
            db.execute(text(f"CREATE UNIQUE INDEX ux_industry_news_source_url ON {table} (source_url)"))
        if "ux_industry_news_fingerprint" not in existing_indexes:
            db.execute(text(f"CREATE UNIQUE INDEX ux_industry_news_fingerprint ON {table} (fingerprint)"))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("ensure unique indexes failed: %s", _safe_log_text(exc))


def _normalize_text_key(raw: str, max_len: int = 50) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip()).lower()[:max_len]


def _build_news_fingerprint(
    title: str,
    published_at: datetime | None,
    source_name: str,
) -> str:
    pub_key = published_at.strftime("%Y-%m-%d") if published_at else ""
    payload = f"{_normalize_text_key(title, 256)}|{pub_key}|{_normalize_text_key(source_name, 50)}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _title_key(title: str) -> str:
    return _normalize_text_key(title, 120)


def _backfill_news_fingerprint(db: Session) -> None:
    rows = db.query(IndustryNews).filter((IndustryNews.fingerprint.is_(None)) | (IndustryNews.fingerprint == "")).all()
    if not rows:
        return
    for row in rows:
        row.fingerprint = _build_news_fingerprint(
            title=row.title or "",
            published_at=row.published_at,
            source_name=row.source_name or "",
        )
        db.add(row)
    db.commit()


def _dedupe_existing_news(db: Session) -> None:
    # Keep newest row by id, remove older duplicates on source_url / fingerprint.
    rows = db.query(IndustryNews).order_by(IndustryNews.id.desc()).all()
    seen_urls: set[str] = set()
    seen_fp: set[str] = set()
    removed = 0
    for row in rows:
        url_key = (row.source_url or "").strip()
        fp_key = (row.fingerprint or "").strip()
        duplicated = False
        if url_key and url_key in seen_urls:
            duplicated = True
        if fp_key and fp_key in seen_fp:
            duplicated = True
        if duplicated:
            try:
                delete_news_by_source(_news_vector_source(row.id))
            except Exception:
                pass
            db.delete(row)
            removed += 1
            continue
        if url_key:
            seen_urls.add(url_key)
        if fp_key:
            seen_fp.add(fp_key)
    if removed > 0:
        db.commit()
        logger.info("industry_news historical dedupe removed %s duplicate rows", removed)


def _load_existing_dedup_keys(db: Session) -> tuple[set[str], set[str]]:
    rows = db.query(IndustryNews.source_url, IndustryNews.title).all()
    seen_urls = {(u or "").strip() for u, _ in rows if (u or "").strip()}
    seen_title_keys = {_title_key(t or "") for _, t in rows if (t or "").strip()}
    return seen_urls, seen_title_keys


def _load_state() -> dict:
    path = _state_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    _state_file().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_in_cooldown() -> datetime | None:
    state = _load_state()
    raw = state.get("cooldown_until", "")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt if _now_utc() < dt else None


def _set_cooldown(hours: int = CRAWLER_COOLDOWN_HOURS) -> datetime:
    until = _now_utc() + timedelta(hours=hours)
    state = _load_state()
    state["cooldown_until"] = until.isoformat()
    _save_state(state)
    return until


def _clear_cooldown() -> None:
    state = _load_state()
    state.pop("cooldown_until", None)
    _save_state(state)


def _build_request(url: str) -> urllib.request.Request:
    safe_url = _sanitize_url(url)
    safe_user_agent = _to_header_ascii(CRAWLER_USER_AGENT)
    safe_referer = _to_header_ascii(CRAWLER_REFERER)
    return urllib.request.Request(
        url=safe_url,
        headers={
            "User-Agent": safe_user_agent,
            "Referer": safe_referer,
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        },
        method="GET",
    )


def _to_header_ascii(value: str) -> str:
    # HTTP header values are transmitted as ISO-8859-1-compatible bytes by stdlib.
    # Keep printable ASCII only to avoid latin-1 encode crashes on non-ASCII content.
    s = str(value or "")
    return "".join(ch if 32 <= ord(ch) <= 126 else "?" for ch in s)


def _sanitize_url(url: str) -> str:
    # Keep URL safe for urllib and avoid implicit encoding failures on non-ascii paths/query.
    raw = (url or "").strip()
    if not raw:
        return raw
    parts = urlsplit(raw)
    path = quote(parts.path or "", safe="/%:@-._~!$&'()*+,;=")
    query = quote(parts.query or "", safe="=&%:@-._~!$'()*+,;/?")
    fragment = quote(parts.fragment or "", safe="")
    return urlunsplit((parts.scheme, parts.netloc, path, query, fragment))


def _safe_log_text(value: Any) -> str:
    s = str(value)
    # Always return a utf-8-safe string representation for logs.
    return s.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def _strip_html(text: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", text or "")
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _trim_summary(text: str, max_len: int = SUMMARY_MAX_LEN) -> str:
    t = _strip_html(text)
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def _safe_decode_bytes(content: bytes) -> str:
    # RSS sources often mix encodings; decode progressively.
    for enc in ("utf-8", "utf-8-sig", "gb18030", "gbk", "big5"):
        try:
            return content.decode(enc)
        except Exception:
            continue
    return content.decode("utf-8", errors="replace")


def _parse_pubdate(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        pass
    # fallback for common date strings
    raw_text = (raw or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(raw_text, fmt)
            return dt
        except Exception:
            continue
    return None


def _window_start(window: str | None = None) -> datetime:
    key = (window or NEWS_TIME_WINDOW_DEFAULT).strip().lower()
    delta = NEWS_TIME_WINDOWS.get(key, NEWS_TIME_WINDOWS[NEWS_TIME_WINDOW_DEFAULT])
    if delta is None:
        return datetime.min
    return datetime.utcnow() - delta

def _normalize_window(window: str | None = None) -> str:
    key = (window or NEWS_TIME_WINDOW_DEFAULT).strip().lower()
    return key if key in NEWS_TIME_WINDOWS else NEWS_TIME_WINDOW_DEFAULT

def _is_active_crawl_window(window: str | None = None) -> bool:
    return _normalize_window(window) in ACTIVE_CRAWL_WINDOWS

def _within_time_window(published_at: datetime | None, window: str | None = None) -> bool:
    key = (window or NEWS_TIME_WINDOW_DEFAULT).strip().lower()
    if key == "all":
        return True
    if published_at is None:
        # keep unknown dates to avoid losing potentially important items
        return True
    return published_at >= _window_start(window)


def _row_within_time_window(news: IndustryNews, window: str | None = None) -> bool:
    key = (window or NEWS_TIME_WINDOW_DEFAULT).strip().lower()
    if key == "all":
        return True
    cutoff = _window_start(window)
    # Keep rows when either published_at or fetched_at is within window.
    pub = news.published_at
    fet = news.fetched_at
    if pub is None and fet is None:
        return False
    return ((pub is not None and pub >= cutoff) or (fet is not None and fet >= cutoff))


def _extract_item_field(node: ET.Element, *tags: str) -> str:
    for tag in tags:
        value = node.findtext(tag)
        if value:
            return value.strip()
    return ""


def _xml_children_text(node: ET.Element, suffix: str) -> str:
    for child in list(node):
        if child.tag.lower().endswith(suffix.lower()):
            text = (child.text or "").strip()
            if text:
                return text
    return ""


AI_SUMMARY_TIMEOUT_SEC = 25


def _run_chat_one_shot(prompt: str, system_prompt: str) -> str:
    return chat_messages(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        task="general",
        contains_sensitive=False,
    )


def _build_ai_summary(title: str, description: str, timeout_sec: int = AI_SUMMARY_TIMEOUT_SEC) -> str:
    raw = _strip_html(description) or _strip_html(title)
    if not raw:
        return ""
    prompt = f"标题：{title}\n正文：{raw[:1200]}"
    summary_system_prompt = (
        "你是专业资讯摘要员，只输出1-2句精简客观的新闻内容，"
        "禁止任何解释、思考、推理、模板、格式、对话。"
    )
    try:
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(_run_chat_one_shot, prompt, summary_system_prompt)
        try:
            out = future.result(timeout=timeout_sec)
        except FuturesTimeoutError:
            future.cancel()
            raise RuntimeError(f"AI summary timed out after {timeout_sec}s")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        out = _strip_html(out).strip()
        out = re.sub(r"\s+", " ", out).strip(" \n\r\t-#*`")
        # strip leaked prompt/template markers
        out = re.sub(r"\{[^{}]{1,40}\}", "", out)
        out = re.sub(r"(任务[:：]|要求[:：]|示例输出[:：])", "", out, flags=re.IGNORECASE)
        # 强清洗：删除含推理/过程词的句子，仅保留结果句。
        banned_words = ("思考", "需要", "首先", "其次", "用户", "任务", "要求", "示例", "分析", "拆解", "步骤", "模板")
        candidate_sentences = re.split(r"(?<=[。！？!?])", out)
        kept: list[str] = []
        for sent in candidate_sentences:
            s = sent.strip()
            if not s:
                continue
            if any(w in s for w in banned_words):
                continue
            kept.append(s)
            if len(kept) >= 2:
                break
        cleaned = "".join(kept).strip()
        if cleaned:
            return _trim_summary(cleaned, AI_SUMMARY_MAX_LEN)
    except Exception as exc:
        logger.warning("AI summary generation failed, fallback to trimmed description: %s", _safe_log_text(exc))
    # 清洗后为空时，兜底正文前50字（不再使用AI文本）。
    fallback = re.sub(r"\s+", " ", raw).strip()
    return _trim_summary((fallback[:50] or raw[:50]), AI_SUMMARY_MAX_LEN)


def _infer_tags(title: str, summary: str, source_name: str = "") -> list[str]:
    text = f"{title} {summary} {source_name}".lower()
    tags: list[str] = []
    for track, keywords in TRACK_KEYWORDS.items():
        if any(k.lower() in text for k in keywords):
            tags.append(track)
    if not tags:
        tags = ["政策法规"]
    return tags[:4]


def _news_vector_source(news_id: int) -> str:
    return f"{NEWS_VECTOR_SOURCE_PREFIX}{news_id}"


def _cleanup_old_news(db: Session, retention_days: int = NEWS_RETENTION_DAYS) -> int:
    if int(retention_days or 0) <= 0:
        return 0
    cutoff = datetime.utcnow() - timedelta(days=max(1, retention_days))
    rows = (
        db.query(IndustryNews)
        .filter(func.coalesce(IndustryNews.published_at, IndustryNews.fetched_at) < cutoff)
        .all()
    )
    if not rows:
        return 0
    count = 0
    for row in rows:
        try:
            delete_news_by_source(_news_vector_source(row.id))
        except Exception:
            pass
        db.delete(row)
        count += 1
    db.commit()
    return count


def _embed_news_row(news: IndustryNews) -> int:
    # Rebuild a single vector document for the news item.
    try:
        source_key = _news_vector_source(news.id)
        delete_news_by_source(source_key)
        try:
            tags = json.loads(news.tags_json or "[]")
            if not isinstance(tags, list):
                tags = []
        except Exception:
            tags = []
        tags_text = " ".join(str(t) for t in tags if t)
        # Embedding payload: title + AI summary + tags
        text = f"{news.title}\n{news.summary}\n{tags_text}".strip()
        if not text:
            return 0
        meta = {
            "source_file": source_key,
            "type": "industry_news",
            "id": news.id,
            "news_id": news.id,
            "title": news.title,
            "summary": news.summary,
            "tags": tags,
            "source_name": news.source_name,
            "source_url": news.source_url,
            "published_at": news.published_at.isoformat() if news.published_at else "",
        }
        return add_news_documents(
            [
                {
                    "source_file": source_key,
                    "title": news.title,
                    "summary": news.summary,
                    "tags": tags,
                    "source_url": news.source_url,
                    "published_at": news.published_at.isoformat() if news.published_at else "",
                    "metadata": meta,
                }
            ]
        )
    except Exception as exc:
        logger.warning(
            "embed news row failed(news_id=%s): %s",
            getattr(news, "id", None),
            _safe_log_text(exc),
        )
        return 0


def _ingest_news_to_kg_best_effort(db: Session, news: IndustryNews, raw_content: str = "") -> None:
    try:
        if raw_content:
            news.summary = (news.summary or raw_content).strip()
        res = ingest_news_row_to_kg_with_tracking(db=db, news=news, force=False)
        if not res.get("ok"):
            logger.info(
                "news->kg skipped/failed (news_id=%s): %s",
                getattr(news, "id", None),
                _safe_log_text(res.get("error", "unknown")),
            )
    except Exception as exc:
        logger.warning("news->kg best effort failed(news_id=%s): %s", getattr(news, "id", None), _safe_log_text(exc))


def _parse_rss_xml(content: bytes) -> ET.Element:
    try:
        return ET.fromstring(content)
    except Exception:
        # Fallback: decode and strip invalid control chars.
        text = _safe_decode_bytes(content)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        try:
            return ET.fromstring(text.encode("utf-8", errors="ignore"))
        except Exception:
            # HTML-like invalid XML fallback for malformed feeds/pages:
            # extract common item blocks by regex and wrap into synthetic RSS xml.
            item_blocks = re.findall(r"(?is)<item\b.*?>.*?</item>", text)
            if not item_blocks:
                item_blocks = re.findall(r"(?is)<entry\b.*?>.*?</entry>", text)
            wrapped = "<rss><channel>{}</channel></rss>".format("".join(item_blocks))
            try:
                return ET.fromstring(wrapped.encode("utf-8", errors="ignore"))
            except Exception:
                # final degraded empty rss document
                return ET.fromstring(b"<rss><channel></channel></rss>")


def _fetch_url_content(url: str) -> bytes:
    req = _build_request(url)
    content: bytes | None = None
    last_exc: Exception | None = None
    for attempt in range(FETCH_RETRY_TIMES + 1):
        try:
            with urllib.request.urlopen(req, timeout=CRAWLER_TIMEOUT_SEC) as resp:
                status = getattr(resp, "status", 200)
                if status == 429:
                    raise RuntimeError("HTTP 429")
                if status >= 400:
                    raise RuntimeError(f"HTTP {status}")
                content = resp.read()
                break
        except HTTPError as exc:
            last_exc = exc
            if exc.code == 429:
                raise RuntimeError("HTTP 429") from exc
            if exc.code == 404:
                raise RuntimeError("HTTP 404") from exc
        except (URLError, TimeoutError, RuntimeError) as exc:
            last_exc = exc
            if "429" in str(exc):
                raise RuntimeError("HTTP 429") from exc
            if "404" in str(exc):
                raise RuntimeError("HTTP 404") from exc
            # Windows socket aborted by software (WinError 10053): retry once then skip.
            if "10053" in str(exc):
                if attempt >= 1:
                    raise RuntimeError("WINERR_10053") from exc
        except Exception as exc:
            last_exc = exc
            if "10053" in str(exc):
                if attempt >= 1:
                    raise RuntimeError("WINERR_10053") from exc
        if attempt < FETCH_RETRY_TIMES:
            time.sleep(FETCH_BACKOFF_SEC * (attempt + 1))
    if content is None:
        raise RuntimeError(f"fetch failed: {last_exc}")
    return content


def _clean_html(text: str) -> str:
    s = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text or "")
    s = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", s)
    s = re.sub(r"(?is)<!--.*?-->", " ", s)
    return s


def _extract_links_from_html(html_text: str, page_url: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    body = _clean_html(html_text)
    # generic anchor extraction
    pattern = re.compile(r'(?is)<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>')
    for href, inner in pattern.findall(body):
        url = urljoin(page_url, href.strip())
        if not url.startswith(("http://", "https://")):
            continue
        title = _strip_html(inner).strip()
        if not title:
            continue
        if len(title) < HTML_MIN_TITLE_LEN or len(title) > HTML_MAX_TITLE_LEN:
            continue
        if any(x in url.lower() for x in (".jpg", ".png", ".gif", "javascript:", "mailto:")):
            continue
        links.append({"title": title[:512], "url": url[:512]})
        if len(links) >= HTML_MAX_LINKS_SCAN:
            break
    return links


def _extract_pagination_links(html_text: str, page_url: str, max_pages: int = HTML_LIST_MAX_PAGES) -> list[str]:
    """
    Generic pagination link extraction for list pages.
    Keeps same-host links that likely represent page navigation.
    """
    links: list[str] = []
    body = _clean_html(html_text)
    pattern = re.compile(r'(?is)<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>')
    base_host = (urlsplit(page_url).netloc or "").lower()
    for href, inner in pattern.findall(body):
        text = _strip_html(inner).strip().lower()
        url = urljoin(page_url, href.strip())
        if not url.startswith(("http://", "https://")):
            continue
        host = (urlsplit(url).netloc or "").lower()
        if base_host and host != base_host:
            continue
        # Common pagination cues
        if not (
            re.search(r"(下一页|下页|next|尾页|末页|^\d+$)", text)
            or re.search(r"([_/=-])(\d+)\.(s?html?)$", url.lower())
            or re.search(r"(page|p|index)[=/_-]?\d+", url.lower())
        ):
            continue
        links.append(url[:512])
    # Keep order and deduplicate
    unique: list[str] = []
    seen = set()
    for u in links:
        if u in seen:
            continue
        seen.add(u)
        unique.append(u)
        if len(unique) >= max_pages - 1:
            break
    return unique


def _build_list_page_urls(source_url: str, first_page_html: str, max_pages: int = HTML_LIST_MAX_PAGES) -> list[str]:
    urls = [source_url]
    extra = _extract_pagination_links(first_page_html, source_url, max_pages=max_pages)
    for u in extra:
        if u not in urls:
            urls.append(u)
        if len(urls) >= max_pages:
            break
    return urls


def _extract_pubdate_from_text(text: str) -> datetime | None:
    raw = (text or "").strip()
    # common patterns: 2026-04-29 / 2026/04/29 / 2026年04月29日
    m = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", raw)
    if not m:
        return None
    try:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return datetime(year, month, day)
    except Exception:
        return None


def _extract_summary_from_html(html_text: str) -> str:
    text = _strip_html(_clean_html(html_text))
    text = re.sub(r"\s+", " ", text).strip()
    return _trim_summary(text, HTML_SUMMARY_LEN)


def _extract_title_from_html(html_text: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text or "")
    if m:
        t = _strip_html(m.group(1)).strip()
        if t:
            return t[:512]
    h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", html_text or "")
    if h1:
        t = _strip_html(h1.group(1)).strip()
        if t:
            return t[:512]
    return ""


def _guess_source_name_from_url(url: str) -> str:
    host = (urlsplit(url).netloc or "").lower()
    if not host:
        return "手动添加"
    known_sources: list[dict[str, str]] = list(NEWS_WHITELIST)
    for s in KEYWORD_SEARCH_SOURCES:
        seed_url = str(s.get("url") or s.get("url_template") or "").strip()
        if not seed_url:
            continue
        # url_template may contain "{q}", use a safe placeholder for host extraction
        seed_url = seed_url.replace("{q}", "test")
        known_sources.append({"name": str(s.get("name", "")).strip(), "url": seed_url})
    for s in known_sources:
        netloc = (urlsplit(s.get("url", "")).netloc or "").lower()
        if netloc and netloc in host:
            return str(s.get("name", "")).strip() or host
    return host


def _is_authoritative_source_url(url: str) -> bool:
    host = (urlsplit(url).netloc or "").lower()
    if not host:
        return False
    # 允许白名单来源 + 常见权威站点
    allow_hosts = {
        (urlsplit(s.get("url", "")).netloc or "").lower()
        for s in NEWS_WHITELIST
    }
    allow_hosts.update({
        "www.gov.cn", "gov.cn", "www.ndrc.gov.cn", "www.mee.gov.cn", "www.miit.gov.cn",
        "www.nea.gov.cn", "www.cneeex.com", "www.cenews.com.cn", "huanbao.bjx.com.cn",
    })
    return any(h and h in host for h in allow_hosts)


def _manual_add_related_ok(title: str, summary: str, source_name: str = "") -> bool:
    """
    Rich-news friendly manual gate:
    - keep hard blacklist rejection
    - allow broader policy wording if carbon/energy context exists
    - authoritative energy agencies get relaxed acceptance
    """
    merged = f"{title}\n{summary}"
    low = (merged or "").lower()
    if any(b.lower() in low for b in CARBON_WEAK_BLACKLIST):
        return False
    if any(b.lower() in low for b in CONTENT_GARBAGE_BLACKLIST):
        return False

    # primary: existing related check
    if is_carbon_related(merged, source_name=source_name):
        return True

    # authoritative energy/environment agencies — single energy keyword is sufficient
    source_low = (source_name or "").lower()
    is_energy_authority = any(
        d in source_low
        for d in ("nea.gov.cn", "mee.gov.cn", "ndrc.gov.cn", "miit.gov.cn", "gov.cn",
                   "国家能源局", "生态环境部", "发改委", "工信部")
    )

    # secondary broad manual acceptance for policy-like content
    broad_terms = [
        "节能", "降碳", "低碳", "零碳", "碳", "新能源", "能源", "绿色", "环保", "能效", "减排",
        "电力", "储能", "光伏", "风电", "氢能", "碳中和", "碳达峰", "双碳",
        "资金补贴", "财政补贴", "奖补", "专项资金", "扶持政策", "支持政策", "补助",
    ]
    hit = sum(1 for t in broad_terms if t in merged)
    threshold = 1 if is_energy_authority else 2
    if hit >= threshold:
        return True
    # semantic fallback: related is enough
    sim = max_cosine_similarity(merged, SEMANTIC_NEWS_PROTOTYPES)
    return sim >= SEMANTIC_RELEVANCE_THRESHOLD


def _semantic_related_ok(title: str, summary: str) -> bool:
    merged = f"{title}\n{summary}".strip()
    if not merged:
        return False
    sim = max_cosine_similarity(merged, SEMANTIC_NEWS_PROTOTYPES)
    return sim >= SEMANTIC_RELEVANCE_THRESHOLD


def manual_add_industry_news(db: Session, url: str) -> ManualAddResult:
    _ensure_news_schema(db)
    safe_url = (url or "").strip()
    if not safe_url.startswith(("http://", "https://")):
        return ManualAddResult(False, "仅支持 http/https 新闻链接")
    authoritative = _is_authoritative_source_url(safe_url)

    # URL 去重：重复链接不允许重复添加
    exists = db.query(IndustryNews).filter(IndustryNews.source_url == safe_url[:512]).first()
    if exists:
        return ManualAddResult(False, "该链接已存在，未重复添加", exists)

    try:
        content = _fetch_url_content(safe_url)
        html_text = _safe_decode_bytes(content)
    except Exception as exc:
        return ManualAddResult(False, f"抓取失败: {_safe_log_text(exc)}")

    title = _extract_title_from_html(html_text) or safe_url
    raw_summary = _extract_summary_from_html(html_text)
    published_at = _extract_pubdate_from_text(html_text) or _extract_pubdate_from_text(title)
    source_name = _guess_source_name_from_url(safe_url)

    # 相关性校验（基于标题+原始正文摘要）
    if not _manual_add_related_ok(title=title, summary=raw_summary, source_name=source_name):
        return ManualAddResult(False, "该资讯与双碳/节能降碳相关性较弱，未通过入库校验")

    ai_summary = _build_ai_summary(title=title, description=raw_summary)
    tags = _infer_tags(title=title, summary=ai_summary or raw_summary, source_name=source_name)
    item = {
        "title": title[:512],
        "summary": ai_summary or _trim_summary(raw_summary or title, AI_SUMMARY_MAX_LEN),
        "raw_summary": _trim_summary(raw_summary or title, AI_SUMMARY_MAX_LEN),
        "source_name": source_name[:128],
        "source_url": safe_url[:512],
        "published_at": published_at,
        "fingerprint": _build_news_fingerprint(
            title=title[:512],
            published_at=published_at,
            source_name=source_name[:128],
        ),
        "tags_json": json.dumps(tags, ensure_ascii=False),
    }

    op = _upsert_news(db, item)
    if op == "duplicate_fingerprint":
        return ManualAddResult(False, "内容重复（指纹已存在），未重复添加")
    if op == "updated":
        # 手动添加以新增为主，命中更新说明 URL 已存在或被归并
        db.commit()
        row = db.query(IndustryNews).filter(IndustryNews.source_url == safe_url[:512]).first()
        if authoritative:
            return ManualAddResult(True, "已更新同链接资讯", row)
        return ManualAddResult(True, "已更新同链接资讯（非白名单来源）", row)
    if op == "inserted":
        db.commit()
        row = db.query(IndustryNews).filter(IndustryNews.source_url == safe_url[:512]).first()
        if authoritative:
            return ManualAddResult(True, "添加成功", row)
        return ManualAddResult(True, "添加成功（非白名单来源）", row)
    db.rollback()
    return ManualAddResult(False, "添加失败")


def _build_keyword_search_url(url_template: str, keyword: str) -> str:
    return url_template.format(q=quote(keyword))


def _contains_keyword(text: str, keywords: list[str]) -> bool:
    t = (text or "").lower()
    return any(k.lower() in t for k in keywords)

def _keyword_hit_count(text: str, keywords: list[str]) -> int:
    t = (text or "").lower()
    return sum(1 for k in keywords if k.lower() in t)


def is_carbon_related(text: str, source_name: str = "") -> bool:
    src = source_name or ""
    t = (text or "").strip()
    if not t:
        return False
    low = t.lower()
    if any(b.lower() in low for b in CARBON_WEAK_BLACKLIST):
        return False
    if any(b.lower() in low for b in CONTENT_GARBAGE_BLACKLIST):
        return False
    hit_count = _keyword_hit_count(low, CARBON_CORE_KEYWORDS)
    # 统一放宽门槛：命中 >=1 个核心词即放行（正文仍受黑名单约束）
    threshold = 1
    if hit_count >= threshold:
        return True
    # semantic fallback for richer recall
    return _semantic_related_ok(title="", summary=t)


def _is_polluted_summary(summary: str) -> bool:
    t = (summary or "").strip().lower()
    if not t:
        return False
    bad_markers = (
        "思考", "需要", "首先", "其次", "用户", "任务", "要求", "示例", "分析", "拆解", "步骤", "模板",
        "{item.title}", "{", "}"
    )
    return any(m in t for m in bad_markers)


def purge_dirty_industry_news(db: Session) -> dict[str, int]:
    _ensure_news_schema(db)
    rows = db.query(IndustryNews).all()
    delete_rows: list[IndustryNews] = []
    reason_polluted = 0
    reason_irrelevant = 0
    reason_source = 0
    for row in rows:
        title = (row.title or "").strip()
        summary = (row.summary or "").strip()
        source = (row.source_name or "").strip()
        # 来源质量兜底：空来源或明显无效来源直接清理
        if (not source) or source in {"未知", "unknown", "null"}:
            delete_rows.append(row)
            reason_source += 1
            continue
        if _is_polluted_summary(summary):
            delete_rows.append(row)
            reason_polluted += 1
            continue
        if not is_carbon_related(f"{title}\n{summary}", source_name=source):
            delete_rows.append(row)
            reason_irrelevant += 1
            continue

    for row in delete_rows:
        try:
            delete_news_by_source(_news_vector_source(row.id))
        except Exception:
            pass
        db.delete(row)
    if delete_rows:
        db.commit()
    return {
        "total": len(rows),
        "deleted": len(delete_rows),
        "kept": len(rows) - len(delete_rows),
        "polluted": reason_polluted,
        "irrelevant": reason_irrelevant,
        "bad_source": reason_source,
    }


def _fetch_keyword_search_html(
    source_name: str,
    search_url: str,
    keyword: str,
    existing_urls: set[str] | None = None,
    existing_title_keys: set[str] | None = None,
) -> list[dict]:
    content = _fetch_url_content(search_url)
    html_text = _safe_decode_bytes(content)
    candidates = _extract_links_from_html(html_text, search_url)
    items: list[dict] = []
    local_seen_urls: set[str] = set()
    local_seen_titles: set[str] = set()
    skipped_duplicates = 0
    existing_urls = existing_urls or set()
    existing_title_keys = existing_title_keys or set()
    for c in candidates[:MAX_ITEMS_PER_SOURCE]:
        title = c["title"]
        article_url = c["url"]
        title_key = _title_key(title)
        if (
            article_url in local_seen_urls
            or title_key in local_seen_titles
            or article_url in existing_urls
            or title_key in existing_title_keys
        ):
            skipped_duplicates += 1
            continue
        local_seen_urls.add(article_url)
        local_seen_titles.add(title_key)
        # 标题黑名单预过滤
        low_title = (title or "").lower()
        if any(b.lower() in low_title for b in CONTENT_GARBAGE_BLACKLIST):
            continue
        # 标题预过滤：不含任何双碳核心词则直接跳过，不进入正文抓取
        if _keyword_hit_count(title, CARBON_CORE_KEYWORDS) <= 0:
            continue
        summary_raw = ""
        published_at: datetime | None = None
        try:
            time.sleep(random.uniform(0.3, 0.9))
            article_content = _fetch_url_content(article_url)
            article_text = _safe_decode_bytes(article_content)
            summary_raw = _extract_summary_from_html(article_text)
            published_at = _extract_pubdate_from_text(article_text) or _extract_pubdate_from_text(title)
        except Exception as exc:
            logger.debug("keyword article fetch degraded for %s: %s", _safe_log_text(article_url), _safe_log_text(exc))
            summary_raw = _trim_summary(title, HTML_SUMMARY_LEN)
            published_at = _extract_pubdate_from_text(title)

        if len(_strip_html(summary_raw)) < MIN_VALID_SUMMARY_LEN:
            continue
        ai_summary = _build_ai_summary(title=title, description=summary_raw)
        merged_text = f"{title}\n{summary_raw}"
        if not is_carbon_related(merged_text, source_name=source_name):
            continue
        tags = _infer_tags(
            title=f"{title} {keyword}",
            summary=ai_summary or summary_raw,
            source_name=source_name,
        )
        items.append(
            {
                "title": title[:512],
                "summary": ai_summary or _trim_summary(summary_raw or title, AI_SUMMARY_MAX_LEN),
                "raw_summary": _trim_summary(summary_raw or title, AI_SUMMARY_MAX_LEN),
                "source_name": f"{source_name}({keyword})"[:128],
                "source_url": article_url[:512],
                "published_at": published_at,
                "fingerprint": _build_news_fingerprint(
                    title=title[:512],
                    published_at=published_at,
                    source_name=f"{source_name}({keyword})"[:128],
                ),
                "tags_json": json.dumps(tags, ensure_ascii=False),
            }
        )
    if skipped_duplicates:
        logger.info("keyword list pre-dedupe skipped %s duplicate candidates: %s", skipped_duplicates, _safe_log_text(source_name))
    return items


def _fetch_html(
    source_name: str,
    source_url: str,
    existing_urls: set[str] | None = None,
    existing_title_keys: set[str] | None = None,
) -> list[dict]:
    # list pages (home + pagination)
    list_content = _fetch_url_content(source_url)
    list_text = _safe_decode_bytes(list_content)
    list_page_urls = _build_list_page_urls(source_url, list_text, max_pages=HTML_LIST_MAX_PAGES)
    candidates: list[dict[str, str]] = []
    page_failures = 0
    for lp in list_page_urls:
        try:
            if lp == source_url:
                page_text = list_text
            else:
                page_bytes = _fetch_url_content(lp)
                page_text = _safe_decode_bytes(page_bytes)
            candidates.extend(_extract_links_from_html(page_text, lp))
        except Exception as exc:
            page_failures += 1
            logger.warning("list-page parse failed for %s page=%s: %s", _safe_log_text(source_name), _safe_log_text(lp), _safe_log_text(exc))
            continue
    if page_failures:
        logger.info("source=%s list-page failures=%s", _safe_log_text(source_name), page_failures)
    items: list[dict] = []
    local_seen_urls: set[str] = set()
    local_seen_titles: set[str] = set()
    skipped_duplicates = 0
    # crawl a limited set for stability/cost control
    existing_urls = existing_urls or set()
    existing_title_keys = existing_title_keys or set()
    for c in candidates[: max(MAX_ITEMS_PER_SOURCE * HTML_LIST_MAX_PAGES, MAX_ITEMS_PER_SOURCE)]:
        article_url = c["url"]
        title = c["title"]
        low_title = (title or "").lower()
        if any(b.lower() in low_title for b in CONTENT_GARBAGE_BLACKLIST):
            continue
        title_key = _title_key(title)
        if (
            article_url in local_seen_urls
            or title_key in local_seen_titles
            or article_url in existing_urls
            or title_key in existing_title_keys
        ):
            skipped_duplicates += 1
            continue
        local_seen_urls.add(article_url)
        local_seen_titles.add(title_key)
        summary_raw = ""
        published_at: datetime | None = None
        # 抓取前列表层过滤：标题门槛统一为至少命中 1 个核心词
        title_hits = _keyword_hit_count(title, CARBON_CORE_KEYWORDS)
        if title_hits < 1:
            continue
        try:
            time.sleep(random.uniform(0.4, 1.1))
            article_content = _fetch_url_content(article_url)
            article_text = _safe_decode_bytes(article_content)
            summary_raw = _extract_summary_from_html(article_text)
            published_at = _extract_pubdate_from_text(article_text) or _extract_pubdate_from_text(title)
        except Exception as exc:
            logger.debug("article fetch degraded for %s: %s", _safe_log_text(article_url), _safe_log_text(exc))
            # graceful degrade: keep from list page only
            summary_raw = _trim_summary(title, HTML_SUMMARY_LEN)
            published_at = _extract_pubdate_from_text(title)
        if len(_strip_html(summary_raw)) < MIN_VALID_SUMMARY_LEN:
            continue

        ai_summary = _build_ai_summary(title=title, description=summary_raw)
        tags = _infer_tags(title=title, summary=ai_summary or summary_raw, source_name=source_name)
        items.append(
            {
                "title": title[:512],
                "summary": ai_summary or _trim_summary(summary_raw or title, AI_SUMMARY_MAX_LEN),
                "raw_summary": _trim_summary(summary_raw or title, AI_SUMMARY_MAX_LEN),
                "source_name": source_name[:128],
                "source_url": article_url[:512],
                "published_at": published_at,
                "fingerprint": _build_news_fingerprint(
                    title=title[:512],
                    published_at=published_at,
                    source_name=source_name[:128],
                ),
                "tags_json": json.dumps(tags, ensure_ascii=False),
            }
        )
    if skipped_duplicates:
        logger.info("html list pre-dedupe skipped %s duplicate candidates: %s", skipped_duplicates, _safe_log_text(source_name))
    return items


def _fetch_rss(
    source_name: str,
    source_url: str,
    existing_urls: set[str] | None = None,
    existing_title_keys: set[str] | None = None,
) -> list[dict]:
    content = _fetch_url_content(source_url)

    root = _parse_rss_xml(content)
    items: list[dict] = []
    local_seen_urls: set[str] = set()
    local_seen_titles: set[str] = set()
    skipped_duplicates = 0
    nodes = root.findall(".//item")
    if not nodes:
        nodes = root.findall(".//{*}item")
    existing_urls = existing_urls or set()
    existing_title_keys = existing_title_keys or set()
    for node in nodes[: max(MAX_ITEMS_PER_SOURCE * 3, MAX_ITEMS_PER_SOURCE)]:
        title = _extract_item_field(node, "title") or _xml_children_text(node, "title")
        link = _extract_item_field(node, "link") or _xml_children_text(node, "link")
        desc = (
            _extract_item_field(node, "description", "content")
            or _xml_children_text(node, "description")
            or _xml_children_text(node, "content")
        )
        pubdate = _extract_item_field(node, "pubDate", "date", "published") or _xml_children_text(node, "pubDate")
        if not title or not link:
            continue
        low_title = (title or "").lower()
        if any(b.lower() in low_title for b in CONTENT_GARBAGE_BLACKLIST):
            continue
        # 抓取前列表层过滤：标题门槛统一为至少命中 1 个核心词
        title_hits = _keyword_hit_count(title, CARBON_CORE_KEYWORDS)
        if title_hits < 1:
            continue
        title_key = _title_key(title)
        if (
            link in local_seen_urls
            or title_key in local_seen_titles
            or link in existing_urls
            or title_key in existing_title_keys
        ):
            skipped_duplicates += 1
            continue
        local_seen_urls.add(link)
        local_seen_titles.add(title_key)
        published_at = _parse_pubdate(pubdate)
        if len(_strip_html(desc or "")) < MIN_VALID_SUMMARY_LEN:
            continue
        ai_summary = _build_ai_summary(title=title, description=desc)
        tags = _infer_tags(title=title, summary=ai_summary or desc, source_name=source_name)
        items.append(
            {
                "title": title[:512],
                "summary": ai_summary or _trim_summary(desc),
                "raw_summary": _trim_summary(desc),
                "source_name": source_name[:128],
                "source_url": link[:512],
                "published_at": published_at,
                "fingerprint": _build_news_fingerprint(
                    title=title[:512],
                    published_at=published_at,
                    source_name=source_name[:128],
                ),
                "tags_json": json.dumps(tags, ensure_ascii=False),
            }
        )
    if skipped_duplicates:
        logger.info("rss list pre-dedupe skipped %s duplicate candidates: %s", skipped_duplicates, _safe_log_text(source_name))
    return items


def _upsert_news(db: Session, item: dict) -> str:
    fingerprint = item.get("fingerprint") or _build_news_fingerprint(
        title=item.get("title", ""),
        published_at=item.get("published_at"),
        source_name=item.get("source_name", ""),
    )
    item["fingerprint"] = fingerprint

    exists = (
        db.query(IndustryNews)
        .filter(IndustryNews.source_url == item["source_url"])
        .first()
    )
    if exists:
        try:
            exists.title = item["title"]
            exists.summary = item["summary"]
            exists.tags_json = item.get("tags_json") or "[]"
            exists.published_at = item["published_at"]
            exists.fingerprint = fingerprint
            exists.fetched_at = datetime.utcnow()
            db.add(exists)
            db.flush()
            embedded = _embed_news_row(exists)
            if embedded <= 0:
                raise RuntimeError("news vector write failed")
            _ingest_news_to_kg_best_effort(db, exists, raw_content=item.get("raw_summary", ""))
            return "updated"
        except Exception as exc:
            db.rollback()
            logger.warning("upsert update rollback due to vector write failure: %s", _safe_log_text(exc))
            return "failed_vector"

    fp_exists = (
        db.query(IndustryNews.id)
        .filter(IndustryNews.fingerprint == fingerprint)
        .first()
    )
    if fp_exists:
        return "duplicate_fingerprint"

    try:
        row = IndustryNews(
            title=item["title"],
            summary=item["summary"],
            source_name=item["source_name"],
            source_url=item["source_url"],
            fingerprint=fingerprint,
            tags_json=item.get("tags_json") or "[]",
            published_at=item["published_at"],
        )
        db.add(row)
        db.flush()
        embedded = _embed_news_row(row)
        if embedded <= 0:
            raise RuntimeError("news vector write failed")
        _ingest_news_to_kg_best_effort(db, row, raw_content=item.get("raw_summary", ""))
        return "inserted"
    except Exception as exc:
        db.rollback()
        logger.warning("upsert insert rollback due to vector write failure: %s", _safe_log_text(exc))
        return "failed_vector"


def refresh_industry_news(db: Session, force: bool = False, time_window: str = NEWS_TIME_WINDOW_DEFAULT) -> RefreshStats:
    _ensure_news_schema(db)
    _clear_cooldown()  # 强制解除冷却，避免前序429导致长期无法抓取
    time_window = _normalize_window(time_window)
    stats = RefreshStats()
    if not _is_active_crawl_window(time_window):
        stats.message = f"时间窗 {time_window} 仅查询本地历史数据，不触发网页抓取。"
        return stats
    cooldown = _is_in_cooldown()
    if cooldown and not force:
        stats.cooldown_until = cooldown.replace(tzinfo=None)
        stats.message = "检测到429冷却期，已暂停抓取。"
        return stats

    if force:
        _clear_cooldown()
    # 前端刷新先清理历史脏数据，再抓取最新数据
    purge_stats = purge_dirty_industry_news(db)
    logger.info("news pre-refresh purge: %s", purge_stats)

    existing_urls, existing_title_keys = _load_existing_dedup_keys(db)
    remaining = MAX_FETCH_PER_REFRESH
    source_results: list[str] = []
    for source in NEWS_WHITELIST:
        if remaining <= 0:
            break
        try:
            time.sleep(random.uniform(CRAWLER_MIN_DELAY_SEC, CRAWLER_MAX_DELAY_SEC))
            kind = (source.get("kind") or "").strip().lower()
            if kind not in {"rss", "html"}:
                stats.skipped += 1
                continue

            def _source_fetch() -> list[dict]:
                if kind == "rss":
                    return _fetch_rss(
                        source_name=source["name"],
                        source_url=source["url"],
                        existing_urls=existing_urls,
                        existing_title_keys=existing_title_keys,
                    )
                return _fetch_html(
                    source_name=source["name"],
                    source_url=source["url"],
                    existing_urls=existing_urls,
                    existing_title_keys=existing_title_keys,
                )

            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(_source_fetch)
                try:
                    items = fut.result(timeout=SOURCE_FETCH_TIMEOUT_SEC)
                except FuturesTimeoutError:
                    logger.info("News source timeout skipped: %s", _safe_log_text(source.get("name")))
                    stats.skipped += 1
                    source_results.append(f"{source.get('name')}: timeout")
                    continue
            # keep only recent items in configured time window
            items = [it for it in items if _within_time_window(it.get("published_at"), time_window)]
            source_candidates = len(items)
            filtered_items: list[dict] = []
            for it in items:
                merged_text = f"{it.get('title', '')}\n{it.get('raw_summary', it.get('summary', ''))}"
                if not is_carbon_related(merged_text, source_name=it.get("source_name", "")):
                    stats.filtered += 1
                    continue
                filtered_items.append(it)
            items = filtered_items[:remaining]
            stats.fetched += len(items)
            source_inserted = 0
            source_updated = 0
            source_skipped = 0
            for item in items:
                op = _upsert_news(db, item)
                if op == "inserted":
                    stats.inserted += 1
                    source_inserted += 1
                    existing_urls.add((item.get("source_url") or "").strip())
                    existing_title_keys.add(_title_key(item.get("title") or ""))
                elif op == "updated":
                    stats.updated += 1
                    source_updated += 1
                else:
                    stats.skipped += 1
                    source_skipped += 1
                    continue
                stats.embedded += 1
                remaining -= 1
                if remaining <= 0:
                    break
            db.commit()
            source_results.append(
                f"{source.get('name')}: candidates={source_candidates}, kept={len(items)}, inserted={source_inserted}, updated={source_updated}, skipped={source_skipped}"
            )
        except Exception as exc:
            msg = _safe_log_text(exc)
            logger.warning("News fetch failed for %s: %s", _safe_log_text(source.get("name")), msg)
            if "429" in msg:
                until = _set_cooldown(CRAWLER_COOLDOWN_HOURS)
                stats.cooldown_until = until.replace(tzinfo=None)
                stats.message = "触发429限流，已自动暂停24小时。"
                break
            if ("404" in msg) or ("WINERR_10053" in msg):
                # Per-source hard failure: skip and continue others.
                stats.skipped += 1
                source_results.append(f"{source.get('name')}: hard-fail={msg[:80]}")
                continue
            stats.skipped += 1
            source_results.append(f"{source.get('name')}: fail={msg[:80]}")

    # 补抓：若本轮还有容量，追加关键词抓取（官方站内搜索）
    if remaining > 0:
        try:
            # limit keyword supplement per refresh to avoid very long-running tasks
            supplement_terms = POLICY_KEYWORDS[: min(4, len(POLICY_KEYWORDS))]
            kw_stats = crawl_news_by_keywords(db, keywords=supplement_terms, time_window=time_window)
            stats.fetched += kw_stats.fetched
            stats.inserted += kw_stats.inserted
            stats.updated += kw_stats.updated
            stats.filtered += kw_stats.filtered
            stats.embedded += kw_stats.embedded
            stats.skipped += kw_stats.skipped
        except Exception as exc:
            logger.warning("keyword supplement crawl failed: %s", _safe_log_text(exc))

    # optional cleanup (disabled by default when NEWS_RETENTION_DAYS=0)
    if NEWS_RETENTION_DAYS > 0:
        try:
            stats.pruned = _cleanup_old_news(db, retention_days=NEWS_RETENTION_DAYS)
        except Exception as exc:
            logger.warning("old news cleanup failed: %s", _safe_log_text(exc))

    if not stats.message:
        stats.message = (
            f"资讯刷新完成（时间窗口: {time_window}，过滤无关资讯: {stats.filtered}，"
            f"清理旧资讯: {stats.pruned}）"
        )
    logger.info(
        "news refresh stats: candidates=%s, filtered=%s, inserted=%s, updated=%s, skipped=%s",
        stats.fetched,
        stats.filtered,
        stats.inserted,
        stats.updated,
        stats.skipped,
    )
    stats.source_details = source_results
    for line in source_results:
        logger.info("news source result | %s", line)
    return stats


def list_industry_news(
    db: Session,
    limit: int = 20,
    time_window: str = NEWS_TIME_WINDOW_DEFAULT,
) -> list[IndustryNews]:
    _ensure_news_schema(db)
    limit = max(1, min(limit, 100))
    query = (
        db.query(IndustryNews)
    )
    if (time_window or NEWS_TIME_WINDOW_DEFAULT).strip().lower() != "all":
        cutoff = _window_start(time_window)
        query = query.filter(
            or_(
                and_(IndustryNews.published_at.is_not(None), IndustryNews.published_at >= cutoff),
                and_(IndustryNews.fetched_at.is_not(None), IndustryNews.fetched_at >= cutoff),
            )
        )
    return (
        query.order_by(
            IndustryNews.published_at.is_(None).asc(),
            IndustryNews.published_at.desc(),
            IndustryNews.id.desc(),
        )
        .limit(limit)
        .all()
    )


def list_industry_news_paginated(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    time_window: str = NEWS_TIME_WINDOW_DEFAULT,
    track_tag: str | None = None,
    question: str | None = None,
) -> tuple[list[IndustryNews], int, int]:
    """
    Paginated list with optional time/tag filters.
    If question is provided, semantic+tag hybrid retrieval is used then paginated in-memory.
    """
    _ensure_news_schema(db)
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 100))
    page_size = min(page_size, MAX_NEWS_RETURN)

    if question and question.strip():
        rows = hybrid_search_industry_news(
            db=db,
            question=question.strip(),
            track_tag=track_tag,
            top_k=MAX_NEWS_RETURN,
            time_window=time_window,
        )
        rows = rows[:MAX_NEWS_RETURN]
        total = len(rows)
        total_pages = max(1, math.ceil(total / page_size)) if total > 0 else 0
        start = (page - 1) * page_size
        return rows[start : start + page_size], total, total_pages

    query = db.query(IndustryNews)
    if (time_window or NEWS_TIME_WINDOW_DEFAULT).strip().lower() != "all":
        cutoff = _window_start(time_window)
        query = query.filter(
            or_(
                and_(IndustryNews.published_at.is_not(None), IndustryNews.published_at >= cutoff),
                and_(IndustryNews.fetched_at.is_not(None), IndustryNews.fetched_at >= cutoff),
            )
        )

    rows = (
        query.order_by(
            IndustryNews.published_at.is_(None).asc(),
            IndustryNews.published_at.desc(),
            IndustryNews.id.desc(),
        )
        .limit(MAX_NEWS_RETURN)
        .all()
    )
    if track_tag:
        rows = [r for r in rows if _match_tag_filter(r, track_tag)]
    total = len(rows)
    total_pages = max(1, math.ceil(total / page_size)) if total > 0 else 0
    start = (page - 1) * page_size
    return rows[start : start + page_size], total, total_pages


def latest_news_fetched_at(db: Session) -> datetime | None:
    _ensure_news_schema(db)
    return db.query(func.max(IndustryNews.fetched_at)).scalar()


def semantic_search_industry_news(
    db: Session,
    question: str,
    top_k: int = DEFAULT_SEMANTIC_TOP_K,
) -> list[IndustryNews]:
    """
    Semantic retrieval for industry news:
    - vector search on "title + AI summary" embeddings
    - map vector hits back to relational rows for stable rendering
    """
    _ensure_news_schema(db)
    q = (question or "").strip()
    if not q:
        return []
    top_k = max(1, min(top_k, 20))
    hits = similarity_search_news(q, k=top_k * 2)
    if not hits:
        return []

    ids: list[int] = []
    for hit in hits:
        meta = hit.get("metadata") or {}
        source_file = str(meta.get("source_file", ""))
        if source_file.startswith(NEWS_VECTOR_SOURCE_PREFIX):
            try:
                ids.append(int(source_file.replace(NEWS_VECTOR_SOURCE_PREFIX, "", 1)))
            except Exception:
                continue
            continue
        news_id = meta.get("news_id")
        if isinstance(news_id, int):
            ids.append(news_id)
            continue
        if isinstance(news_id, str) and news_id.isdigit():
            ids.append(int(news_id))

    # de-dup while preserving hit order
    uniq_ids: list[int] = []
    seen: set[int] = set()
    for nid in ids:
        if nid not in seen:
            uniq_ids.append(nid)
            seen.add(nid)
        if len(uniq_ids) >= top_k:
            break
    if not uniq_ids:
        return []

    rows = db.query(IndustryNews).filter(IndustryNews.id.in_(uniq_ids)).all()
    row_map = {r.id: r for r in rows}
    ordered = [row_map[nid] for nid in uniq_ids if nid in row_map]
    return ordered


def _match_tag_filter(news: IndustryNews, track_tag: str | None) -> bool:
    if not track_tag:
        return True
    try:
        tags = json.loads(news.tags_json or "[]")
    except Exception:
        tags = []
    return track_tag in tags


def hybrid_search_industry_news(
    db: Session,
    question: str,
    track_tag: str | None = None,
    top_k: int = DEFAULT_SEMANTIC_TOP_K,
    time_window: str = NEWS_TIME_WINDOW_DEFAULT,
) -> list[IndustryNews]:
    """
    Hybrid retrieval:
    1) optional track filter
    2) semantic ranking
    """
    _ensure_news_schema(db)
    rows = semantic_search_industry_news(db=db, question=question, top_k=max(top_k * 2, 10))
    rows = [r for r in rows if _row_within_time_window(r, time_window)]
    filtered = [r for r in rows if _match_tag_filter(r, track_tag)]
    if filtered:
        return filtered[:top_k]

    query = db.query(IndustryNews)
    if (time_window or NEWS_TIME_WINDOW_DEFAULT).strip().lower() != "all":
        cutoff = _window_start(time_window)
        query = query.filter(
            or_(
                and_(IndustryNews.published_at.is_not(None), IndustryNews.published_at >= cutoff),
                and_(IndustryNews.fetched_at.is_not(None), IndustryNews.fetched_at >= cutoff),
            )
        )
    candidates = (
        query.order_by(
            IndustryNews.published_at.is_(None).asc(),
            IndustryNews.published_at.desc(),
            IndustryNews.id.desc(),
        )
        .limit(80 if track_tag else top_k)
        .all()
    )
    if track_tag:
        return [r for r in candidates if _match_tag_filter(r, track_tag)][:top_k]
    return candidates[:top_k]


def semantic_search_news_for_agent(
    db: Session,
    question: str,
    track_tag: str | None = None,
    top_k: int = DEFAULT_SEMANTIC_TOP_K,
    time_window: str = NEWS_TIME_WINDOW_DEFAULT,
) -> dict[str, Any]:
    """
    Agent-friendly semantic news search tool output.
    """
    rows = hybrid_search_industry_news(
        db=db,
        question=question,
        track_tag=track_tag,
        top_k=top_k,
        time_window=time_window,
    )
    items: list[dict[str, Any]] = []
    for r in rows:
        items.append(
            {
                "id": r.id,
                "title": r.title,
                "summary": r.summary,
                "source_name": r.source_name,
                "source_url": r.source_url,
                "tags": json.loads(r.tags_json or "[]"),
                "published_at": r.published_at.isoformat() if r.published_at else None,
            }
        )
    return {
        "question": question,
        "track_tag": track_tag,
        "time_window": time_window,
        "count": len(items),
        "items": items,
        "message": "ok" if items else "no_related_news",
    }


def backfill_existing_news_vectors(db: Session, reset_collection_first: bool = True) -> dict[str, int]:
    """
    Rebuild news vectors from MySQL to Milvus `carbon_ai_news`.
    - Optionally reset news collection first to remove invalid/orphan vectors.
    """
    _ensure_news_schema(db)
    if reset_collection_first:
        reset_news_collection()

    rows = (
        db.query(IndustryNews)
        .order_by(IndustryNews.id.asc())
        .all()
    )
    total = len(rows)
    success = 0
    failed = 0
    for row in rows:
        try:
            embedded = _embed_news_row(row)
            if embedded > 0:
                success += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    return {"total": total, "success": success, "failed": failed}


def crawl_news_by_keywords(
    db: Session,
    keywords: list[str] | None = None,
    time_window: str = NEWS_TIME_WINDOW_DEFAULT,
) -> RefreshStats:
    """
    Keyword-driven policy/news crawling against official search entry pages.
    Keeps existing pipeline: parse -> AI summary -> tags -> embedding -> upsert de-dup.
    """
    _ensure_news_schema(db)
    time_window = _normalize_window(time_window)
    stats = RefreshStats(message="关键词抓取完成")
    if not _is_active_crawl_window(time_window):
        stats.message = f"时间窗 {time_window} 仅查询本地历史数据，不触发关键词网页抓取。"
        return stats
    terms = [k.strip() for k in (keywords or POLICY_KEYWORDS) if k and k.strip()]
    if not terms:
        stats.message = "关键词为空，未执行抓取"
        return stats

    existing_urls, existing_title_keys = _load_existing_dedup_keys(db)
    remaining = MAX_FETCH_PER_REFRESH
    for source in KEYWORD_SEARCH_SOURCES:
        if remaining <= 0:
            break
        for kw in terms:
            if remaining <= 0:
                break
            try:
                time.sleep(random.uniform(CRAWLER_MIN_DELAY_SEC, CRAWLER_MAX_DELAY_SEC))
                search_url = _build_keyword_search_url(source["url_template"], kw)
                items = _fetch_keyword_search_html(
                    source["name"],
                    search_url,
                    kw,
                    existing_urls=existing_urls,
                    existing_title_keys=existing_title_keys,
                )
                items = [it for it in items if _within_time_window(it.get("published_at"), time_window)]
                filtered_items: list[dict] = []
                for it in items:
                    merged_text = f"{it.get('title', '')}\n{it.get('raw_summary', it.get('summary', ''))}"
                    if not is_carbon_related(merged_text, source_name=it.get("source_name", "")):
                        stats.filtered += 1
                        continue
                    filtered_items.append(it)
                items = filtered_items[:remaining]
                stats.fetched += len(items)
                for item in items:
                    op = _upsert_news(db, item)
                    if op == "inserted":
                        stats.inserted += 1
                        existing_urls.add((item.get("source_url") or "").strip())
                        existing_title_keys.add(_title_key(item.get("title") or ""))
                    elif op == "updated":
                        stats.updated += 1
                    else:
                        stats.skipped += 1
                        continue
                    stats.embedded += 1
                    remaining -= 1
                    if remaining <= 0:
                        break
                db.commit()
            except Exception as exc:
                msg = _safe_log_text(exc)
                logger.info("Keyword crawl skipped for %s/%s: %s", _safe_log_text(source.get("name")), _safe_log_text(kw), msg)
                stats.skipped += 1
                # keep silent skip behaviour for robustness
                continue
    stats.message = f"关键词抓取完成（时间窗口: {time_window}，过滤无关资讯: {stats.filtered}）"
    logger.info("keyword crawl stats: filtered=%s, inserted=%s, updated=%s, skipped=%s", stats.filtered, stats.inserted, stats.updated, stats.skipped)
    return stats


# ==================================================================
# Three-tier fallback refresh (mirrors carbon_market_price_service)
# ==================================================================

@dataclass
class NewsRefreshResult:
    """Unified result from the three-tier refresh pipeline."""
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    filtered: int = 0
    pruned: int = 0
    embedded: int = 0
    fallback_layer: int = 0  # 0=live scrape, 1=keyword API, 2=db cache
    source: str = ""
    message: str = ""
    source_details: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    db_cached_count: int = 0  # rows already in DB (for tier 2)


def refresh_news_with_fallback(
    db: Session,
    force: bool = False,
    time_window: str = NEWS_TIME_WINDOW_DEFAULT,
) -> NewsRefreshResult:
    """Three-tier news refresh with full trace logging.

    Tier 0 — live scrape from whitelist government/industry sources
    Tier 1 — keyword API search against official site search engines
    Tier 2 — return cached DB rows (data from previous successful runs)

    Returns NewsRefreshResult with trace for debugging.
    """
    _ensure_news_schema(db)
    time_window = _normalize_window(time_window)
    t0 = time.monotonic()
    trace: list[str] = []
    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")

    trace.append(f"[{now_str}] refresh_news_with_fallback(force={force}, window={time_window})")

    # --- count existing DB cache ---
    db_cached = db.query(func.count(IndustryNews.id)).scalar() or 0
    trace.append(f"[{_ts()}] DB cached rows: {db_cached}")

    result = NewsRefreshResult(db_cached_count=db_cached)

    # ==================================================================
    # Tier 0 — live scrape from whitelist sources
    # ==================================================================
    trace.append(f"[{_ts()}] TIER 0: live scrape from {len(NEWS_WHITELIST)} whitelist sources...")
    logger.info("news_refresh: tier0_start — scraping %d whitelist sources", len(NEWS_WHITELIST))
    tier0_ok = False
    try:
        if not _is_active_crawl_window(time_window):
            trace.append(f"[{_ts()}] TIER 0 SKIPPED — window={time_window} not in active crawl windows")
        else:
            cooldown = _is_in_cooldown()
            if cooldown and not force:
                trace.append(f"[{_ts()}] TIER 0 SKIPPED — cooldown until {cooldown.isoformat()}")
            else:
                if force:
                    _clear_cooldown()
                stats = refresh_industry_news(db, force=force, time_window=time_window)
                if stats.inserted > 0 or stats.updated > 0:
                    tier0_ok = True
                    result.fallback_layer = 0
                    result.source = "live scrape (whitelist sources)"
                    result.fetched = stats.fetched
                    result.inserted = stats.inserted
                    result.updated = stats.updated
                    result.skipped = stats.skipped
                    result.filtered = stats.filtered
                    result.pruned = stats.pruned
                    result.embedded = stats.embedded
                    result.source_details = stats.source_details
                    trace.append(
                        f"[{_ts()}] TIER 0 SUCCESS — "
                        f"fetched={stats.fetched} inserted={stats.inserted} "
                        f"updated={stats.updated} filtered={stats.filtered}"
                    )
                    logger.info(
                        "news_refresh: tier0_ok inserted=%d updated=%d filtered=%d",
                        stats.inserted, stats.updated, stats.filtered,
                    )
                else:
                    trace.append(
                        f"[{_ts()}] TIER 0 returned 0 new items — "
                        f"fetched={stats.fetched} filtered={stats.filtered}"
                    )
                    logger.warning(
                        "news_refresh: tier0_empty fetched=%d filtered=%d",
                        stats.fetched, stats.filtered,
                    )
    except Exception as exc:
        trace.append(f"[{_ts()}] TIER 0 EXCEPTION: {exc!r}")
        logger.warning("news_refresh: tier0_exception %s", exc)

    # ==================================================================
    # Tier 1 — keyword API search fallback
    # ==================================================================
    if not tier0_ok:
        trace.append(f"[{_ts()}] TIER 1: keyword API search fallback...")
        logger.info("news_refresh: tier1_start — keyword search")
        try:
            kw_stats = crawl_news_by_keywords(
                db,
                keywords=POLICY_KEYWORDS[:6],
                time_window=time_window,
            )
            if kw_stats.inserted > 0 or kw_stats.updated > 0:
                result.fallback_layer = 1
                result.source = "keyword search (official site APIs)"
                result.fetched = kw_stats.fetched
                result.inserted = kw_stats.inserted
                result.updated = kw_stats.updated
                result.skipped = kw_stats.skipped
                result.filtered = kw_stats.filtered
                result.embedded = kw_stats.embedded
                result.source_details = [f"keyword_search: inserted={kw_stats.inserted}"]
                trace.append(
                    f"[{_ts()}] TIER 1 SUCCESS — "
                    f"fetched={kw_stats.fetched} inserted={kw_stats.inserted}"
                )
                logger.info(
                    "news_refresh: tier1_ok inserted=%d fetched=%d",
                    kw_stats.inserted, kw_stats.fetched,
                )
            else:
                trace.append(
                    f"[{_ts()}] TIER 1 returned 0 new items — "
                    f"fetched={kw_stats.fetched}"
                )
                logger.warning("news_refresh: tier1_empty fetched=%d", kw_stats.fetched)
        except Exception as exc:
            trace.append(f"[{_ts()}] TIER 1 EXCEPTION: {exc!r}")
            logger.warning("news_refresh: tier1_exception %s", exc)

    # ==================================================================
    # Tier 2 — DB cache (always available, never fails)
    # ==================================================================
    if result.inserted == 0 and result.updated == 0:
        trace.append(f"[{_ts()}] TIER 2: DB cache fallback (no new items from live sources)...")
        logger.info("news_refresh: tier2_cache — using existing DB rows")
        result.fallback_layer = 2
        result.source = "database cache (previous successful refresh)"
        result.message = (
            f"实时爬取暂无新资讯，展示数据库缓存的 {db_cached} 条历史资讯"
        )
        trace.append(
            f"[{_ts()}] TIER 2 — returning {db_cached} cached DB rows (offline fallback)"
        )

    # final summary
    if not result.message:
        result.message = (
            f"资讯刷新完成（来源: {result.source}，"
            f"新增 {result.inserted} 条，更新 {result.updated} 条，"
            f"过滤 {result.filtered} 条）"
        )
    elapsed = time.monotonic() - t0
    trace.append(
        f"[{_ts()}] DONE in {elapsed:.2f}s → "
        f"layer={result.fallback_layer} inserted={result.inserted} "
        f"source={result.source!r}"
    )
    logger.info(
        "news_refresh: final layer=%d inserted=%d updated=%d source=%s elapsed=%.2fs",
        result.fallback_layer, result.inserted, result.updated,
        result.source, elapsed,
    )
    result.trace = trace
    return result


def debug_news_system(db: Session, time_window: str = NEWS_TIME_WINDOW_DEFAULT) -> dict:
    """Return full debug snapshot of the news system."""
    _ensure_news_schema(db)
    time_window = _normalize_window(time_window)

    db_total = db.query(func.count(IndustryNews.id)).scalar() or 0
    db_latest = db.query(func.max(IndustryNews.fetched_at)).scalar()
    db_sources = (
        db.query(IndustryNews.source_name, func.count(IndustryNews.id))
        .group_by(IndustryNews.source_name)
        .order_by(func.count(IndustryNews.id).desc())
        .all()
    )

    whitelist_sources = [
        {"name": s["name"], "url": s["url"], "kind": s.get("kind", "html")}
        for s in NEWS_WHITELIST
    ]

    cooldown = _is_in_cooldown()
    state = _load_state()

    return {
        "db_total_rows": db_total,
        "db_latest_fetched_at": db_latest.isoformat() if db_latest else None,
        "db_sources": [{"name": name, "count": cnt} for name, cnt in db_sources],
        "whitelist_sources": whitelist_sources,
        "cooldown_active": cooldown is not None,
        "cooldown_until": cooldown.isoformat() if cooldown else None,
        "crawler_state": state,
        "time_window": time_window,
        "active_crawl_windows": list(ACTIVE_CRAWL_WINDOWS),
        "keyword_sources_count": len(KEYWORD_SEARCH_SOURCES),
        "policy_keywords": POLICY_KEYWORDS[:6],
    }

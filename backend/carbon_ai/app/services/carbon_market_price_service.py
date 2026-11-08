"""Fetch real-time CEA carbon market prices with in-memory caching.

Three-tier pipeline (each tier logs its entry/exit/result):
  Tier 0 — scrape tanpaifang.com (CEA national market daily report)
  Tier 1 — AKShare energy_carbon_domestic() regional pilot fallback
  Tier 2 — hardcoded benchmark (offline fallback)

Every code path returns a MarketPriceSnapshot — no unhandled exceptions escape.
"""

from __future__ import annotations

import logging
import re
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CACHE_TTL_SEC = 600  # 10 minutes
FETCH_TIMEOUT_SEC = 12  # per-HTTP-call timeout
CEA_SYMBOL = "CEA"

# ---------------------------------------------------------------------------
# in-memory cache
# ---------------------------------------------------------------------------
_cache: dict[str, dict[str, Any]] = {}


@dataclass
class MarketPriceSnapshot:
    symbol: str = CEA_SYMBOL
    price: float = 0.0
    price_date: str = ""
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    close_price: float = 0.0
    volume: float = 0.0
    turnover: float = 0.0
    change_pct: float = 0.0
    source: str = ""
    fetched_at: str = ""
    cached: bool = False
    fallback_layer: int = 0  # 0=tier0(tanpaifang), 1=tier1(AKShare), 2=tier2(benchmark)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "price_date": self.price_date,
            "open_price": self.open_price,
            "high_price": self.high_price,
            "low_price": self.low_price,
            "close_price": self.close_price,
            "volume": self.volume,
            "turnover": self.turnover,
            "change_pct": self.change_pct,
            "source": self.source,
            "fetched_at": self.fetched_at,
            "cached": self.cached,
            "fallback_layer": self.fallback_layer,
        }


# ==================================================================
# public API
# ==================================================================

def fetch_latest_price(
    symbol: str = CEA_SYMBOL,
    force: bool = False,
) -> tuple[MarketPriceSnapshot, list[str]]:
    """Return (snapshot, trace_logs) for the latest carbon market price.

    trace_logs is a list of human-readable step messages for debugging.
    """
    trace: list[str] = []
    cache_key = f"latest_{symbol}"
    now = datetime.now(timezone.utc)
    t0 = time.monotonic()

    trace.append(f"[{_ts()}] fetch_latest_price(symbol={symbol!r}, force={force})")

    # --- cache hit (fresh) ---
    if not force and cache_key in _cache:
        entry = _cache[cache_key]
        cached_at = entry.get("cached_at")
        if cached_at:
            age = (now - cached_at).total_seconds()
            if age < CACHE_TTL_SEC:
                snap: MarketPriceSnapshot = entry["snapshot"]
                snap.cached = True
                trace.append(f"[{_ts()}] CACHE HIT age={age:.0f}s layer={snap.fallback_layer} source={snap.source!r}")
                trace.append(f"[{_ts()}] DONE in {_elapsed(t0):.2f}s → price={snap.price} date={snap.price_date}")
                logger.info("carbon_price: cache_hit age=%.0fs layer=%d price=%.2f", age, snap.fallback_layer, snap.price)
                return snap, trace

    snapshot: MarketPriceSnapshot | None = None

    # ==================================================================
    # Tier 0 — tanpaifang.com CEA scraper
    # ==================================================================
    trace.append(f"[{_ts()}] TIER 0: trying tanpaifang.com scraper...")
    logger.info("carbon_price: tier0_start — scraping tanpaifang.com")
    try:
        snapshot = _try_tanpaifang(trace)
        if snapshot is not None:
            snapshot.fallback_layer = 0
            trace.append(f"[{_ts()}] TIER 0 SUCCESS — source={snapshot.source!r} price={snapshot.price} date={snapshot.price_date}")
            logger.info("carbon_price: tier0_ok price=%.2f date=%s", snapshot.price, snapshot.price_date)
        else:
            trace.append(f"[{_ts()}] TIER 0 FAILED — returned None")
            logger.warning("carbon_price: tier0_fail — tanpaifang returned None")
    except Exception as exc:
        trace.append(f"[{_ts()}] TIER 0 EXCEPTION: {exc!r}")
        logger.warning("carbon_price: tier0_exception %s", exc)

    # ==================================================================
    # Tier 1 — AKShare regional pilot
    # ==================================================================
    if snapshot is None:
        trace.append(f"[{_ts()}] TIER 1: trying AKShare (Hubei pilot)...")
        logger.info("carbon_price: tier1_start — AKShare")
        try:
            snapshot = _try_akshare("湖北", trace)
            if snapshot is not None:
                snapshot.fallback_layer = 1
                trace.append(f"[{_ts()}] TIER 1 SUCCESS — source={snapshot.source!r} price={snapshot.price}")
                logger.info("carbon_price: tier1_ok price=%.2f date=%s", snapshot.price, snapshot.price_date)
            else:
                trace.append(f"[{_ts()}] TIER 1 FAILED — returned None")
                logger.warning("carbon_price: tier1_fail — AKShare returned None")
        except Exception as exc:
            trace.append(f"[{_ts()}] TIER 1 EXCEPTION: {exc!r}")
            logger.warning("carbon_price: tier1_exception %s", exc)

    # ==================================================================
    # Tier 1.5 — stale cache
    # ==================================================================
    if snapshot is None and cache_key in _cache:
        entry = _cache[cache_key]
        stale = entry.get("snapshot")
        if isinstance(stale, MarketPriceSnapshot):
            stale.cached = True
            trace.append(f"[{_ts()}] STALE CACHE — reusing layer={stale.fallback_layer} price={stale.price}")
            logger.warning("carbon_price: stale_cache layer=%d price=%.2f", stale.fallback_layer, stale.price)
            trace.append(f"[{_ts()}] DONE in {_elapsed(t0):.2f}s (stale cache)")
            return stale, trace

    # ==================================================================
    # Tier 2 — hardcoded benchmark (NEVER returns None)
    # ==================================================================
    if snapshot is None:
        trace.append(f"[{_ts()}] TIER 2: using hardcoded benchmark fallback...")
        logger.warning("carbon_price: tier2_fallback — all live sources failed, using benchmark")
        snapshot = _cea_fallback()
        snapshot.fallback_layer = 2
        trace.append(f"[{_ts()}] TIER 2 — benchmark price={snapshot.price} (offline)")

    # write cache
    _cache[cache_key] = {"snapshot": snapshot, "cached_at": now}
    trace.append(f"[{_ts()}] DONE in {_elapsed(t0):.2f}s → layer={snapshot.fallback_layer} price={snapshot.price}")
    logger.info("carbon_price: final layer=%d price=%.2f source=%s elapsed=%.2fs",
                snapshot.fallback_layer, snapshot.price, snapshot.source, _elapsed(t0))
    return snapshot, trace


# ==================================================================
# Tier 0 — tanpaifang.com CEA scraper
# ==================================================================
_TANPAIFANG_LIST = "http://www.tanpaifang.com/tanshichang/"
_TANPAIFANG_ARTICLE_RE = re.compile(
    r'href="(https?://www\.tanpaifang\.com)?(/tanshichang/(\d{4})(\d{2})/(\d{2})\d+\.html)"'
)
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 CarbonAI/1.0"


def _try_tanpaifang(trace: list[str] | None = None) -> MarketPriceSnapshot | None:
    """Scrape the latest CEA daily report from tanpaifang.com."""
    t0 = time.monotonic()
    if trace is not None:
        trace.append(f"[{_ts()}]   fetching list page {_TANPAIFANG_LIST!r}...")

    try:
        resp = httpx.get(
            _TANPAIFANG_LIST,
            timeout=FETCH_TIMEOUT_SEC,
            follow_redirects=True,
            headers={"User-Agent": _UA},
        )
        if trace is not None:
            trace.append(f"[{_ts()}]   list page HTTP {resp.status_code} len={len(resp.content)}")
        if resp.status_code != 200:
            logger.warning("tanpaifang list page returned %d", resp.status_code)
            return None

        html = resp.content.decode("utf-8", errors="replace")

        matches = _TANPAIFANG_ARTICLE_RE.findall(html)
        if trace is not None:
            trace.append(f"[{_ts()}]   found {len(matches)} article links")
        if not matches:
            logger.warning("No article links found on tanpaifang list page")
            return None

        # matches: (prefix, path, year, month, day) — sort by path desc
        matches.sort(key=lambda m: m[1], reverse=True)
        article_path = matches[0][1]
        year, month, day = matches[0][2], matches[0][3], matches[0][4]
        article_url = f"http://www.tanpaifang.com{article_path}"
        article_date = f"{year}-{month}-{day}"

        if trace is not None:
            trace.append(f"[{_ts()}]   latest article: {article_url} date={article_date}")

        # 2. Fetch article page
        resp2 = httpx.get(
            article_url,
            timeout=FETCH_TIMEOUT_SEC,
            follow_redirects=True,
            headers={"User-Agent": _UA},
        )
        if trace is not None:
            trace.append(f"[{_ts()}]   article page HTTP {resp2.status_code} len={len(resp2.content)}")
        if resp2.status_code != 200:
            logger.warning("tanpaifang article page returned %d", resp2.status_code)
            return None

        article_html = resp2.content.decode("utf-8", errors="replace")
        clean = re.sub(r"<[^>]+>", " ", article_html)
        clean = re.sub(r"&nbsp;", " ", clean)
        clean = re.sub(r"\s+", " ", clean)

        snap = _parse_tanpaifang_article(clean, article_date, trace)
        if snap:
            snap.source = "tanpaifang.com"
            return snap

        # fallback: parse from list page embedded snippet
        snap = _parse_tanpaifang_list_snippet(html, trace)
        if snap:
            snap.source = "tanpaifang.com (list snippet)"
            return snap

        return None
    except httpx.TimeoutException as exc:
        logger.warning("tanpaifang HTTP timeout: %s", exc)
        if trace is not None:
            trace.append(f"[{_ts()}]   TIMEOUT: {exc!r}")
        return None
    except Exception as exc:
        logger.warning("tanpaifang scrape failed: %s", exc)
        if trace is not None:
            trace.append(f"[{_ts()}]   EXCEPTION: {exc!r}")
        return None


def _parse_tanpaifang_article(
    clean_text: str, article_date: str, trace: list[str] | None = None
) -> MarketPriceSnapshot | None:
    """Parse CEA data from a tanpaifang article plain text."""
    idx = clean_text.find("来源:全国碳交易")
    if idx < 0:
        idx = clean_text.find("全国碳市场")
    if idx < 0:
        if trace is not None:
            trace.append(f"[{_ts()}]   parse: keyword anchor not found in article")
        return None

    segment = clean_text[idx : idx + 1200]

    open_p = re.search(r"开盘价\s*(\d+\.?\d*)\s*元/吨", segment)
    high_p = re.search(r"最高价\s*(\d+\.?\d*)\s*元/吨", segment)
    low_p = re.search(r"最低价\s*(\d+\.?\d*)\s*元/吨", segment)
    close_p = re.search(r"收盘价\s*(\d+\.?\d*)\s*元/吨", segment)

    close_val = float(close_p.group(1)) if close_p else 0.0
    if trace is not None:
        trace.append(
            f"[{_ts()}]   parsed: open={open_p.group(1) if open_p else '?'} "
            f"high={high_p.group(1) if high_p else '?'} "
            f"low={low_p.group(1) if low_p else '?'} "
            f"close={close_p.group(1) if close_p else '?'}"
        )
    if close_val <= 0:
        return None

    change_pct_val = 0.0
    change_dir = 1.0
    chg = re.search(r"(?:上涨|下跌)\s*(\d+\.?\d*)\s*%", segment)
    if chg:
        change_pct_val = float(chg.group(1))
        if "下跌" in segment[chg.start() - 10 : chg.start()]:
            change_dir = -1.0
    change_pct_val = round(change_pct_val * change_dir, 2)

    vol_listed = 0.0
    vm = re.search(r"挂牌协议交易成交量\s*([\d,]+\.?\d*)\s*吨", segment)
    if vm:
        vol_listed = float(vm.group(1).replace(",", ""))

    vol_block = 0.0
    vbm = re.search(r"大宗协议交易成交量\s*([\d,]+\.?\d*)\s*吨", segment)
    if vbm:
        vol_block = float(vbm.group(1).replace(",", ""))

    total_volume = vol_listed + vol_block

    turnover_val = 0.0
    tm = re.search(r"成交额\s*([\d,]+\.?\d*)\s*元", segment)
    if tm:
        turnover_val = float(tm.group(1).replace(",", ""))

    if trace is not None:
        trace.append(
            f"[{_ts()}]   parsed: vol_listed={vol_listed} vol_block={vol_block} "
            f"turnover={turnover_val} chg={change_pct_val}%"
        )

    return MarketPriceSnapshot(
        symbol=CEA_SYMBOL,
        price=close_val,
        price_date=article_date,
        open_price=float(open_p.group(1)) if open_p else close_val,
        high_price=float(high_p.group(1)) if high_p else close_val,
        low_price=float(low_p.group(1)) if low_p else close_val,
        close_price=close_val,
        volume=total_volume if total_volume > 0 else (float(vm.group(1).replace(",", "")) if vm else 0),
        turnover=turnover_val,
        change_pct=change_pct_val,
        source="tanpaifang.com",
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


def _parse_tanpaifang_list_snippet(
    html: str, trace: list[str] | None = None
) -> MarketPriceSnapshot | None:
    """Parse CEA data from the list page embedded snippet."""
    m = re.search(
        r"开盘价(\d+\.?\d*)元/吨[，,]?\s*最高价(\d+\.?\d*)元/吨[，,]?\s*最低价(\d+\.?\d*)元/吨[，,]?\s*收盘价(\d+\.?\d*)元/吨",
        html,
    )
    if not m:
        return None

    open_val = float(m.group(1))
    high_val = float(m.group(2))
    low_val = float(m.group(3))
    close_val = float(m.group(4))

    date_match = re.search(
        r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})",
        html[max(0, m.start() - 200) : m.end()],
    )
    date_str = ""
    if date_match:
        date_str = f"{date_match.group(1)}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"

    if trace is not None:
        trace.append(f"[{_ts()}]   list-snippet parsed: O={open_val} H={high_val} L={low_val} C={close_val}")

    return MarketPriceSnapshot(
        symbol=CEA_SYMBOL,
        price=close_val,
        price_date=date_str,
        open_price=open_val,
        high_price=high_val,
        low_price=low_val,
        close_price=close_val,
        volume=0.0,
        turnover=0.0,
        change_pct=0.0,
        source="tanpaifang.com",
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


# ==================================================================
# Tier 1 — AKShare fallback
# ==================================================================

def _try_akshare(symbol: str, trace: list[str] | None = None) -> MarketPriceSnapshot | None:
    """AKShare energy_carbon_domestic() regional pilot data."""
    try:
        import akshare as ak  # type: ignore

        if trace is not None:
            trace.append(f"[{_ts()}]   calling ak.energy_carbon_domestic(symbol={symbol!r})...")
        df = ak.energy_carbon_domestic(symbol=symbol)
        if df is None or df.empty:
            if trace is not None:
                trace.append(f"[{_ts()}]   AKShare returned empty DataFrame")
            return None

        last = df.iloc[-1]
        cols = df.columns.tolist()
        if trace is not None:
            trace.append(f"[{_ts()}]   AKShare returned {len(df)} rows, cols={cols!r}")

        date_val = str(last.iloc[0]) if len(cols) > 0 else ""
        close_val = float(last.iloc[1] or 0) if len(cols) > 1 else 0.0
        volume_val = float(last.iloc[2] or 0) if len(cols) > 2 else 0.0
        turnover_val = float(last.iloc[3] or 0) if len(cols) > 3 else 0.0

        if trace is not None:
            trace.append(
                f"[{_ts()}]   AKShare last row: date={date_val!r} close={close_val} "
                f"vol={volume_val} turnover={turnover_val}"
            )

        if not date_val or close_val <= 0:
            return None

        change_pct = 0.0
        if len(df) >= 2:
            prev_close = float(df.iloc[-2].iloc[1] or 0)
            if prev_close > 0:
                change_pct = round(((close_val - prev_close) / prev_close) * 100, 2)

        return MarketPriceSnapshot(
            symbol=symbol,
            price=round(close_val, 2),
            price_date=date_val,
            open_price=round(close_val, 2),
            high_price=round(close_val, 2),
            low_price=round(close_val, 2),
            close_price=round(close_val, 2),
            volume=round(volume_val, 2),
            turnover=round(turnover_val, 2),
            change_pct=change_pct,
            source=f"akshare ({symbol}试点)",
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        logger.warning("AKShare fetch failed for %s: %s", symbol, exc)
        if trace is not None:
            trace.append(f"[{_ts()}]   AKShare exception: {exc!r}")
        return None


# ==================================================================
# Tier 2 — hardcoded benchmark
# ==================================================================

def _cea_fallback() -> MarketPriceSnapshot:
    """Hardcoded CEA benchmark — last resort when all live sources fail."""
    return MarketPriceSnapshot(
        symbol=CEA_SYMBOL,
        price=80.06,
        price_date="2026-05-08",
        open_price=79.90,
        high_price=80.80,
        low_price=79.90,
        close_price=80.06,
        volume=681400.0,
        turnover=52897200.0,
        change_pct=0.08,
        source="benchmark (offline fallback)",
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


# ==================================================================
# helpers
# ==================================================================

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _elapsed(t0: float) -> float:
    return time.monotonic() - t0

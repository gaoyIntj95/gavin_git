"""Fetch real-time EUA (European Union Allowance) carbon futures prices.

Three-tier pipeline (each tier logs its entry/exit/result):
  Tier 0 — scrape investing.com EUA futures page
  Tier 1 — stale cache (reuse last known good data)
  Tier 2 — hardcoded benchmark (offline fallback)

Every code path returns a MarketPriceSnapshot — no unhandled exceptions escape.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CACHE_TTL_SEC = 600  # 10 minutes
FETCH_TIMEOUT_SEC = 15  # per-HTTP-call timeout
EUA_SYMBOL = "EUA"

# ---------------------------------------------------------------------------
# in-memory cache
# ---------------------------------------------------------------------------
_cache: dict[str, dict[str, Any]] = {}

# investing.com EUA futures page
_INVESTING_EUA_URL = (
    "https://cn.investing.com/commodities/"
    "european-union-allowance-eua-year-futures"
)
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class MarketPriceSnapshot:
    symbol: str = EUA_SYMBOL
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
    fallback_layer: int = 0  # 0=live scraper, 1=stale cache, 2=offline benchmark
    settlement_date: str = ""  # EUA futures settlement date

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
            "settlement_date": self.settlement_date,
        }


# ==================================================================
# public API
# ==================================================================

def fetch_latest_price(
    force: bool = False,
) -> tuple[MarketPriceSnapshot, list[str]]:
    """Return (snapshot, trace_logs) for the latest EUA carbon futures price."""
    trace: list[str] = []
    cache_key = "latest_eua"
    now = datetime.now(timezone.utc)
    t0 = time.monotonic()

    trace.append(f"[{_ts()}] fetch_latest_eua_price(force={force})")

    # --- cache hit (fresh) ---
    if not force and cache_key in _cache:
        entry = _cache[cache_key]
        cached_at = entry.get("cached_at")
        if cached_at:
            age = (now - cached_at).total_seconds()
            if age < CACHE_TTL_SEC:
                snap: MarketPriceSnapshot = entry["snapshot"]
                snap.cached = True
                trace.append(
                    f"[{_ts()}] CACHE HIT age={age:.0f}s "
                    f"layer={snap.fallback_layer} source={snap.source!r}"
                )
                trace.append(
                    f"[{_ts()}] DONE in {_elapsed(t0):.2f}s "
                    f"→ price={snap.price} settlement={snap.settlement_date}"
                )
                logger.info(
                    "eu_carbon_price: cache_hit age=%.0fs layer=%d price=%.2f",
                    age, snap.fallback_layer, snap.price,
                )
                return snap, trace

    snapshot: MarketPriceSnapshot | None = None

    # ==================================================================
    # Tier 0 — investing.com EUA scraper
    # ==================================================================
    trace.append(f"[{_ts()}] TIER 0: trying investing.com EUA scraper...")
    logger.info("eu_carbon_price: tier0_start — scraping investing.com")
    try:
        snapshot = _try_investing_eua(trace)
        if snapshot is not None:
            snapshot.fallback_layer = 0
            trace.append(
                f"[{_ts()}] TIER 0 SUCCESS — source={snapshot.source!r} "
                f"price={snapshot.price} settlement={snapshot.settlement_date}"
            )
            logger.info(
                "eu_carbon_price: tier0_ok price=%.2f settlement=%s",
                snapshot.price, snapshot.settlement_date,
            )
        else:
            trace.append(f"[{_ts()}] TIER 0 FAILED — returned None")
            logger.warning("eu_carbon_price: tier0_fail — investing.com returned None")
    except Exception as exc:
        trace.append(f"[{_ts()}] TIER 0 EXCEPTION: {exc!r}")
        logger.warning("eu_carbon_price: tier0_exception %s", exc)

    # ==================================================================
    # Tier 1 — stale cache
    # ==================================================================
    if snapshot is None and cache_key in _cache:
        entry = _cache[cache_key]
        stale = entry.get("snapshot")
        if isinstance(stale, MarketPriceSnapshot):
            stale.cached = True
            trace.append(
                f"[{_ts()}] STALE CACHE — reusing layer={stale.fallback_layer} "
                f"price={stale.price}"
            )
            logger.warning(
                "eu_carbon_price: stale_cache layer=%d price=%.2f",
                stale.fallback_layer, stale.price,
            )
            trace.append(f"[{_ts()}] DONE in {_elapsed(t0):.2f}s (stale cache)")
            return stale, trace

    # ==================================================================
    # Tier 2 — hardcoded benchmark (NEVER returns None)
    # ==================================================================
    if snapshot is None:
        trace.append(f"[{_ts()}] TIER 2: using hardcoded benchmark fallback...")
        logger.warning(
            "eu_carbon_price: tier2_fallback — all live sources failed, "
            "using benchmark"
        )
        snapshot = _eua_fallback()
        snapshot.fallback_layer = 2
        trace.append(
            f"[{_ts()}] TIER 2 — benchmark price={snapshot.price} (offline)"
        )

    # write cache
    _cache[cache_key] = {"snapshot": snapshot, "cached_at": now}
    trace.append(
        f"[{_ts()}] DONE in {_elapsed(t0):.2f}s "
        f"→ layer={snapshot.fallback_layer} price={snapshot.price}"
    )
    logger.info(
        "eu_carbon_price: final layer=%d price=%.2f source=%s elapsed=%.2fs",
        snapshot.fallback_layer, snapshot.price, snapshot.source, _elapsed(t0),
    )
    return snapshot, trace


# ==================================================================
# Tier 0 — investing.com EUA scraper
# ==================================================================

def _try_investing_eua(trace: list[str] | None = None) -> MarketPriceSnapshot | None:
    """Scrape EUA futures price from investing.com."""
    t0 = time.monotonic()
    if trace is not None:
        trace.append(f"[{_ts()}]   fetching {_INVESTING_EUA_URL!r}...")

    try:
        resp = httpx.get(
            _INVESTING_EUA_URL,
            timeout=FETCH_TIMEOUT_SEC,
            follow_redirects=True,
            headers={
                "User-Agent": _UA,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        if trace is not None:
            trace.append(
                f"[{_ts()}]   HTTP {resp.status_code} len={len(resp.content)}"
            )
        if resp.status_code != 200:
            logger.warning("investing.com EUA page returned %d", resp.status_code)
            return None

        html = resp.content.decode("utf-8", errors="replace")
        return _parse_investing_eua_html(html, trace)

    except httpx.TimeoutException as exc:
        logger.warning("investing.com EUA HTTP timeout: %s", exc)
        if trace is not None:
            trace.append(f"[{_ts()}]   TIMEOUT: {exc!r}")
        return None
    except Exception as exc:
        logger.warning("investing.com EUA scrape failed: %s", exc)
        if trace is not None:
            trace.append(f"[{_ts()}]   EXCEPTION: {exc!r}")
        return None


def _parse_investing_eua_html(
    html: str, trace: list[str] | None = None
) -> MarketPriceSnapshot | None:
    """Parse EUA price data from investing.com HTML."""

    # --- instrument price (confirmed working via data-test) ---
    price_val = _extract_data_test_value(html, "instrument-price-last")
    if price_val is None:
        if trace is not None:
            trace.append(f"[{_ts()}]   parse: instrument-price-last not found")
        return None

    price = float(price_val.replace(",", ""))
    if price <= 0:
        return None

    # --- change ---
    change_raw = _extract_data_test_value(html, "instrument-price-change")
    change_val = 0.0
    if change_raw:
        try:
            change_val = float(change_raw.replace(",", ""))
        except ValueError:
            pass

    # --- change percent ---
    change_pct_raw = _extract_data_test_value(html, "instrument-price-change-percent")
    change_pct = 0.0
    if change_pct_raw:
        pct_match = re.search(r"([+-]?[\d.]+)\s*%?", change_pct_raw)
        if pct_match:
            change_pct = float(pct_match.group(1))

    # --- trading date ---
    # cn.investing.com (zh-Hans) uses DD/MM format in trading-time-label
    date_raw = _extract_data_test_value(html, "trading-time-label")
    price_date = ""
    if date_raw:
        # Strip garbled suffix (e.g. "06/05       日内范围   75.62")
        clean_date = date_raw.strip().split()[0] if date_raw.strip() else ""
        dm = re.match(r"(\d{1,2})/(\d{1,2})", clean_date)
        if dm:
            now = datetime.now()
            a, b = int(dm.group(1)), int(dm.group(2))
            # Auto-detect DD/MM vs MM/DD: if a > 12 it's DD/MM, if b > 12 it's MM/DD
            if a > 12:
                day, month = a, b
            elif b > 12:
                month, day = a, b
            else:
                # Both <= 12: cn.investing.com uses DD/MM
                day, month = a, b
            year = now.year
            trading_date = datetime(year, month, day)
            if trading_date > now:
                trading_date = datetime(year - 1, month, day)
            price_date = trading_date.strftime("%Y-%m-%d")

    # --- OHLC & volume from key-info dd/dt blocks ---
    key_data = _parse_key_info_blocks(html)

    open_price = key_data.get("open", 0.0)
    prev_close = key_data.get("prevClose", 0.0)
    volume = key_data.get("volume", 0.0)
    daily_range = key_data.get("dailyRange", [])
    settlement_date = key_data.get("settlement_date", "")

    high_price = price
    low_price = price
    if len(daily_range) >= 2:
        high_price = max(daily_range)
        low_price = min(daily_range)

    if open_price <= 0:
        open_price = price

    if trace is not None:
        trace.append(
            f"[{_ts()}]   parsed: price={price} prev_close={prev_close} "
            f"open={open_price} high={high_price} low={low_price} "
            f"volume={volume} change={change_val} change_pct={change_pct}%"
        )
        trace.append(
            f"[{_ts()}]   date={price_date} settlement={settlement_date} "
            f"daily_range={daily_range}"
        )

    return MarketPriceSnapshot(
        symbol=EUA_SYMBOL,
        price=price,
        price_date=price_date,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=price,
        volume=volume,
        turnover=0.0,
        change_pct=change_pct,
        source="investing.com (EUA Futures)",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        settlement_date=settlement_date,
    )


def _parse_key_info_blocks(html: str) -> dict[str, Any]:
    """Parse all key-info dd/dt blocks, returning a dict keyed by data-test name.

    Each value is either a float (single numeric), a list[float] (multi-numeric),
    or a string (no numeric spans found, fallback to text content).
    """
    result: dict[str, Any] = {}
    seen: set[str] = set()

    blocks = re.findall(
        r'<(dd|dt)\s+data-test="([^"]+)"[^>]*>(.*?)</\1>',
        html, re.DOTALL,
    )

    for _tag, name, content in blocks:
        if name in seen:
            continue
        seen.add(name)

        # Extract all numeric values from key-info_dd-numeric spans
        nums = re.findall(
            r'key-info_dd-numeric[^>]*>\s*<span>[^<]*</span>\s*'
            r'<span>([\d,.]+)</span>',
            content,
        )
        if nums:
            vals = [float(n.replace(",", "")) for n in nums]
            result[name] = vals[0] if len(vals) == 1 else vals
        else:
            # Non-numeric field — extract plain text
            text = re.sub(r"<[^>]+>", " ", content)
            text = re.sub(r"&nbsp;", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            result[name] = text

    return result


def _extract_data_test_value(html: str, name: str) -> str | None:
    """Extract text value from a data-test attribute element."""
    pattern = rf'data-test="{re.escape(name)}"[^>]*>(.*?)</(?:dd|dt|span|div)>'
    m = re.search(pattern, html, re.DOTALL)
    if not m:
        return None

    content = m.group(1)
    text = re.sub(r"<[^>]+>", " ", content)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if text else None


# ==================================================================
# Tier 2 — hardcoded benchmark
# ==================================================================

def _eua_fallback() -> MarketPriceSnapshot:
    """Hardcoded EUA benchmark — last resort when all live sources fail."""
    return MarketPriceSnapshot(
        symbol=EUA_SYMBOL,
        price=76.05,
        price_date="2026-05-08",
        open_price=76.05,
        high_price=77.11,
        low_price=75.62,
        close_price=76.05,
        volume=21709.0,
        turnover=0.0,
        change_pct=0.45,
        source="benchmark (offline fallback)",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        settlement_date="2026-12-14",
    )


# ==================================================================
# helpers
# ==================================================================

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _elapsed(t0: float) -> float:
    return time.monotonic() - t0

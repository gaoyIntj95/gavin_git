from __future__ import annotations

from collections import Counter, deque
from datetime import datetime
from threading import Lock
from typing import Any

_LOCK = Lock()
_COUNTERS: Counter[str] = Counter()
_RECENT_EVENTS: deque[dict[str, Any]] = deque(maxlen=200)


def _key(prefix: str, value: str) -> str:
    return f"{prefix}:{value or 'unknown'}"


def record_route_event(
    *,
    session_id: str,
    requested_mode: str,
    execution_mode: str,
    chain: str,
    route_reason: str,
    intake_active: bool,
    has_project: bool,
    allow_preset: bool,
) -> None:
    with _LOCK:
        _COUNTERS["route.total"] += 1
        _COUNTERS[_key("route.requested_mode", requested_mode)] += 1
        _COUNTERS[_key("route.execution_mode", execution_mode)] += 1
        _COUNTERS[_key("route.chain", chain)] += 1
        _COUNTERS[_key("route.reason", route_reason)] += 1
        _COUNTERS[_key("route.intake_active", str(bool(intake_active)).lower())] += 1
        _COUNTERS[_key("route.has_project", str(bool(has_project)).lower())] += 1
        _COUNTERS[_key("route.allow_preset", str(bool(allow_preset)).lower())] += 1
        _RECENT_EVENTS.append(
            {
                "ts": datetime.utcnow().isoformat(),
                "type": "route",
                "session_id": session_id,
                "requested_mode": requested_mode,
                "execution_mode": execution_mode,
                "chain": chain,
                "route_reason": route_reason,
                "intake_active": bool(intake_active),
                "has_project": bool(has_project),
                "allow_preset": bool(allow_preset),
            }
        )


def record_result_event(
    *,
    session_id: str,
    chain: str,
    effective_mode: str,
    used_preset: bool,
    used_tool: bool,
) -> None:
    with _LOCK:
        _COUNTERS["result.total"] += 1
        _COUNTERS[_key("result.chain", chain)] += 1
        _COUNTERS[_key("result.mode", effective_mode)] += 1
        _COUNTERS[_key("result.used_preset", str(bool(used_preset)).lower())] += 1
        _COUNTERS[_key("result.used_tool", str(bool(used_tool)).lower())] += 1
        _RECENT_EVENTS.append(
            {
                "ts": datetime.utcnow().isoformat(),
                "type": "result",
                "session_id": session_id,
                "chain": chain,
                "effective_mode": effective_mode,
                "used_preset": bool(used_preset),
                "used_tool": bool(used_tool),
            }
        )


def snapshot_metrics() -> dict[str, Any]:
    with _LOCK:
        counters = dict(_COUNTERS)
        recent = list(_RECENT_EVENTS)
    route_total = counters.get("route.total", 0)
    result_total = counters.get("result.total", 0)
    preset_hits = counters.get("result.used_preset:true", 0)
    tool_hits = counters.get("result.used_tool:true", 0)
    return {
        "route_total": route_total,
        "result_total": result_total,
        "preset_hit_rate": (preset_hits / result_total) if result_total else 0.0,
        "tool_hit_rate": (tool_hits / result_total) if result_total else 0.0,
        "counters": counters,
        "recent_events": recent,
    }


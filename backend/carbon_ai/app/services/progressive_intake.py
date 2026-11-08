from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

from app.models.chat_session import ChatSession

INTAKE_ENABLED = os.getenv("CHAT_INTAKE_ENABLED", "true").lower() == "true"
INTAKE_RECOVERY_ENABLED = os.getenv("CHAT_INTAKE_RECOVERY_ENABLED", "true").lower() == "true"
INTAKE_MAX_REASK = max(1, int(os.getenv("CHAT_INTAKE_MAX_REASK", "2")))
INTAKE_BOOTSTRAP_KEYWORDS = [
    "开始核算",
    "新建盘查",
    "盘查启动",
    "生成报告",
    "报告生成",
    "建立台账",
    "台账导入",
    "填报",
]
PROJECT_REF_PATTERN = re.compile(
    r"(?:项目|project)\s*([0-9]{1,9})|^\s*\d{1,9}(?:\s*[、,，/\s-]\s*\d{1,9})+\s*$",
    re.IGNORECASE,
)

MANUAL_FINISH_KEYWORDS = [
    "直接开始",
    "信息齐全",
    "开始吧",
    "直接执行",
    "继续执行",
    "开始核算",
    "开始分析",
]

INTENT_KEYWORDS = {
    "calculation": ["核算", "盘查", "计算", "排放量", "scope", "边界", "碳核算"],
    "analysis": ["分析", "占比", "趋势", "拆分", "明细", "对比", "结构"],
    "report": ["报告", "报表", "生成报告", "报告生成"],
    "policy": ["政策", "标准", "合规", "条例", "iso", "cbam", "国标"],
}

FIELD_DEFINITIONS = {
    "enterprise_name": {
        "label": "企业名称",
        "required": True,
        "priority": 1,
        "question": "为了准确落到你的业务场景，先告诉我企业名称或项目主体名称，可以吗？",
        "hint": "例如：XX科技有限公司",
    },
    "accounting_year": {
        "label": "核算年份",
        "required": True,
        "priority": 2,
        "question": "这次主要核算哪个年份？",
        "hint": "例如：2024年",
    },
    "scope": {
        "label": "排放范围Scope",
        "required": True,
        "priority": 3,
        "question": "本次范围先做哪些 Scope（1/2/3）？",
        "hint": "例如：Scope1+2",
    },
    "standard": {
        "label": "执行标准",
        "required": True,
        "priority": 4,
        "question": "你希望按哪套口径执行（ISO14064 / 国标 / CBAM）？",
        "hint": "例如：ISO14064-1:2018",
    },
    "boundary": {
        "label": "核算边界",
        "required": True,
        "priority": 5,
        "question": "核算边界希望按哪种方式？",
        "hint": "例如：运营控制边界",
    },
    "data_source": {
        "label": "数据来源",
        "required": True,
        "priority": 6,
        "question": "活动数据主要来源是什么？",
        "hint": "例如：电表台账+发票+ERP导出",
    },
}

INTENT_REQUIRED_FIELDS = {
    "calculation": [
        "enterprise_name",
        "accounting_year",
        "scope",
        "standard",
        "boundary",
        "data_source",
    ],
    "analysis": [
        "enterprise_name",
        "accounting_year",
        "scope",
        "boundary",
        "data_source",
    ],
    "report": [
        "enterprise_name",
        "accounting_year",
        "scope",
        "standard",
        "boundary",
        "data_source",
    ],
    "policy": ["standard"],
}

DEFAULT_INTENT = "calculation"


def _utc_now() -> str:
    return datetime.utcnow().isoformat()


def _safe_text(v: Any) -> str:
    return str(v or "").strip()


def _contains_any(text: str, keywords: list[str]) -> bool:
    lower = _safe_text(text).lower()
    return any(k.lower() in lower for k in keywords)


def _detect_intent(question: str, fallback_intent: str | None = None) -> str | None:
    q = _safe_text(question).lower()
    if not q:
        return fallback_intent
    for intent, words in INTENT_KEYWORDS.items():
        if any(w.lower() in q for w in words):
            return intent
    return fallback_intent


def _is_business_scene(question: str) -> bool:
    return _detect_intent(question) is not None


def _is_manual_finish(question: str) -> bool:
    return _contains_any(question, MANUAL_FINISH_KEYWORDS)


def _build_empty_state() -> dict[str, Any]:
    fields = {}
    for key in FIELD_DEFINITIONS:
        fields[key] = {"value": None, "updated_at": None}
    return {
        "version": 1,
        "active": False,
        "intent": None,
        "completed": False,
        "forced_finish": False,
        "pending_field": None,
        "pending_attempts": 0,
        "fields": fields,
    }


def _load_state_from_raw(raw: str) -> dict[str, Any]:
    text = _safe_text(raw)
    if not text:
        return _build_empty_state()
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return _build_empty_state()
    except Exception:
        return _build_empty_state()

    base = _build_empty_state()
    base.update({k: v for k, v in data.items() if k != "fields"})
    if isinstance(data.get("fields"), dict):
        for k in base["fields"]:
            val = data["fields"].get(k)
            if isinstance(val, dict):
                base["fields"][k]["value"] = val.get("value")
                base["fields"][k]["updated_at"] = val.get("updated_at")
    return base


def _load_state(session: ChatSession) -> dict[str, Any]:
    raw = _safe_text(getattr(session, "intake_form_json", ""))
    return _load_state_from_raw(raw)


def _save_state(session: ChatSession, state: dict[str, Any]) -> None:
    session.intake_form_json = json.dumps(state, ensure_ascii=False)


def _normalize_scope(text: str) -> str | None:
    q = _safe_text(text).lower()
    if not q:
        return None
    scopes: list[str] = []
    if any(token in q for token in ["scope1", "scope 1", "范围一", "范围1", "scope一"]):
        scopes.append("Scope1")
    if any(token in q for token in ["scope2", "scope 2", "范围二", "范围2", "scope二"]):
        scopes.append("Scope2")
    if any(token in q for token in ["scope3", "scope 3", "范围三", "范围3", "scope三"]):
        scopes.append("Scope3")
    if not scopes and any(token in q for token in ["全部", "全范围", "所有范围"]):
        scopes = ["Scope1", "Scope2", "Scope3"]
    if not scopes:
        return None
    return "+".join(scopes)


def _normalize_standard(text: str) -> str | None:
    q = _safe_text(text).lower()
    if "iso14064" in q or "iso 14064" in q:
        return "ISO14064"
    if "cbam" in q:
        return "CBAM"
    if any(token in q for token in ["国标", "gb/t", "国家标准", "js/t"]):
        return "国标"
    return None


def _normalize_boundary(text: str) -> str | None:
    q = _safe_text(text).lower()
    if any(token in q for token in ["运营控制", "运营边界", "operational control"]):
        return "运营控制边界"
    if any(token in q for token in ["财务控制", "financial control"]):
        return "财务控制边界"
    if any(token in q for token in ["股权", "权益", "equity share"]):
        return "股权边界"
    if "边界" in q:
        return _safe_text(text)
    return None


def _normalize_data_source(text: str) -> str | None:
    q = _safe_text(text).lower()
    parts: list[str] = []
    if any(t in q for t in ["电表", "计量", "抄表"]):
        parts.append("电表/计量系统")
    if any(t in q for t in ["发票", "票据"]):
        parts.append("发票")
    if any(t in q for t in ["erp", "系统导出", "业务系统"]):
        parts.append("ERP/业务系统")
    if any(t in q for t in ["台账", "excel", "手工"]):
        parts.append("台账/手工报表")
    if parts:
        return " + ".join(dict.fromkeys(parts))
    if any(t in q for t in ["来源", "数据"]):
        return _safe_text(text)
    return None


def _extract_enterprise_name(text: str) -> str | None:
    q = _safe_text(text)
    if not q:
        return None
    patterns = [
        r"(?:企业|单位|组织|主体(?:名称)?)[：:\s]*([\u4e00-\u9fa5A-Za-z0-9（）()·\-_]{2,50}(?:公司|集团|厂|中心|研究院)?)",
        r"(?:我是|我们是|主体是)[：:\s]*([\u4e00-\u9fa5A-Za-z0-9（）()·\-_]{2,50}(?:公司|集团|厂|中心|研究院)?)",
        r"([\u4e00-\u9fa5A-Za-z0-9（）()·\-_]{2,50}(?:公司|集团|厂|中心|研究院))",
    ]
    for p in patterns:
        m = re.search(p, q)
        if m:
            return _safe_text(m.group(1))
    return None


def _extract_year(text: str) -> str | None:
    m = re.search(r"(20\d{2})", _safe_text(text))
    if not m:
        return None
    year = int(m.group(1))
    if 2000 <= year <= 2100:
        return str(year)
    return None


def _non_informative(text: str) -> bool:
    q = _safe_text(text).lower()
    if not q:
        return True
    cues = ["不知道", "不清楚", "随便", "你看着办", "无所谓", "先这样", "待定"]
    return any(c in q for c in cues)


def _extract_field_updates(text: str) -> dict[str, str]:
    updates: dict[str, str] = {}

    company = _extract_enterprise_name(text)
    if company:
        updates["enterprise_name"] = company

    year = _extract_year(text)
    if year:
        updates["accounting_year"] = year

    scope = _normalize_scope(text)
    if scope:
        updates["scope"] = scope

    standard = _normalize_standard(text)
    if standard:
        updates["standard"] = standard

    boundary = _normalize_boundary(text)
    if boundary:
        updates["boundary"] = boundary

    source = _normalize_data_source(text)
    if source:
        updates["data_source"] = source

    return updates


def _update_state_fields(state: dict[str, Any], updates: dict[str, str]) -> list[str]:
    changed: list[str] = []
    for key, value in updates.items():
        if key not in state["fields"]:
            continue
        cleaned = _safe_text(value)
        if not cleaned:
            continue
        old = _safe_text(state["fields"][key].get("value"))
        if old != cleaned:
            state["fields"][key]["value"] = cleaned
            state["fields"][key]["updated_at"] = _utc_now()
            changed.append(key)
    return changed


def _required_fields(intent: str | None) -> list[str]:
    if intent in INTENT_REQUIRED_FIELDS:
        return INTENT_REQUIRED_FIELDS[intent]  # type: ignore[return-value]
    return INTENT_REQUIRED_FIELDS[DEFAULT_INTENT]


def _missing_fields(state: dict[str, Any], intent: str | None) -> list[str]:
    required = _required_fields(intent)
    missing: list[str] = []
    for key in required:
        value = _safe_text(state["fields"].get(key, {}).get("value"))
        if not value:
            missing.append(key)
    return missing


def _next_missing_field(missing: list[str]) -> str | None:
    if not missing:
        return None
    return sorted(
        missing,
        key=lambda k: FIELD_DEFINITIONS.get(k, {}).get("priority", 999),
    )[0]


def _build_followup(field_key: str, retry: int = 0) -> str:
    fd = FIELD_DEFINITIONS[field_key]
    q = fd["question"]
    hint = fd.get("hint", "")
    if retry > 0 and INTAKE_RECOVERY_ENABLED:
        return f"我先帮你把信息补齐，这样后续结果会更准。{q}（可直接回复：{hint}）"
    return f"{q}（可直接回复：{hint}）"


def _state_snapshot_text(state: dict[str, Any], intent: str | None) -> str:
    missing = _missing_fields(state, intent)
    done = []
    for key in FIELD_DEFINITIONS:
        value = _safe_text(state["fields"][key].get("value"))
        if value:
            done.append(f"{FIELD_DEFINITIONS[key]['label']}={value}")
    done_text = "；".join(done) if done else "暂无"
    missing_text = "、".join(FIELD_DEFINITIONS[k]["label"] for k in missing) if missing else "无"
    return f"已收集: {done_text} | 待补充: {missing_text}"


def should_run_progressive_intake(
    session: ChatSession,
    question: str,
    project_id: int | None,
) -> bool:
    if not INTAKE_ENABLED:
        return False
    state = _load_state_from_raw(_safe_text(getattr(session, "intake_form_json", "")))
    if project_id is not None and project_id > 0:
        return False
    text = _safe_text(question)
    if PROJECT_REF_PATTERN.search(text):
        return False
    if bool(state.get("active")):
        return True
    if _is_manual_finish(text):
        return True
    # Only bootstrap intake for explicit onboarding/collection intents.
    return _contains_any(text, INTAKE_BOOTSTRAP_KEYWORDS)


def is_progressive_intake_active(session: ChatSession) -> bool:
    state = _load_state_from_raw(_safe_text(getattr(session, "intake_form_json", "")))
    return bool(state.get("active"))


def deactivate_progressive_intake(session: ChatSession) -> None:
    state = _load_state_from_raw(_safe_text(getattr(session, "intake_form_json", "")))
    state["active"] = False
    state["pending_field"] = None
    state["pending_attempts"] = 0
    _save_state(session, state)


def handle_progressive_intake(session: ChatSession, question: str) -> dict[str, Any]:
    state = _load_state(session)
    text = _safe_text(question)

    result = {
        "active": False,
        "intent": None,
        "should_ask": False,
        "followup_question": None,
        "forced_finish": False,
        "missing_fields": [],
        "collected_fields": [],
        "snapshot": "",
    }

    if not INTAKE_ENABLED:
        _save_state(session, state)
        return result

    prev_intent = state.get("intent")
    current_intent = _detect_intent(text, fallback_intent=prev_intent)
    if current_intent:
        state["intent"] = current_intent

    updates = _extract_field_updates(text)
    changed = _update_state_fields(state, updates)

    if _is_manual_finish(text):
        state["active"] = False
        state["completed"] = True
        state["forced_finish"] = True
        state["pending_field"] = None
        state["pending_attempts"] = 0
        _save_state(session, state)
        result["forced_finish"] = True
        result["intent"] = state.get("intent")
        result["collected_fields"] = changed
        result["snapshot"] = _state_snapshot_text(state, state.get("intent"))
        return result

    state["active"] = bool(state.get("active")) or _is_business_scene(text) or bool(state.get("intent"))
    result["active"] = bool(state["active"])
    result["intent"] = state.get("intent")
    result["collected_fields"] = changed

    if not state["active"]:
        _save_state(session, state)
        return result

    missing = _missing_fields(state, state.get("intent"))
    state["completed"] = len(missing) == 0
    result["missing_fields"] = missing

    if not missing:
        state["active"] = False
        state["pending_field"] = None
        state["pending_attempts"] = 0
        _save_state(session, state)
        result["snapshot"] = _state_snapshot_text(state, state.get("intent"))
        return result

    next_field = _next_missing_field(missing)
    if not next_field:
        _save_state(session, state)
        return result

    pending = state.get("pending_field")
    pending_attempts = int(state.get("pending_attempts") or 0)
    if pending == next_field and next_field not in changed and _non_informative(text):
        pending_attempts += 1
    else:
        pending_attempts = 0

    state["pending_field"] = next_field
    state["pending_attempts"] = min(pending_attempts, INTAKE_MAX_REASK)
    _save_state(session, state)

    result["should_ask"] = True
    result["followup_question"] = _build_followup(next_field, retry=state["pending_attempts"])
    result["snapshot"] = _state_snapshot_text(state, state.get("intent"))
    return result

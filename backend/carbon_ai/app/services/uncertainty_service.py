from __future__ import annotations

from math import isclose


ACTIVITY_CATEGORY_TO_LEVEL: dict[str, int] = {
    "自动连续监测": 6,
    "定期量测/抄表/铭牌": 3,
    "自行推估": 1,
}

FACTOR_CATEGORY_TO_LEVEL: dict[str, int] = {
    "国际排放因子": 1,
    "国家排放因子": 2,
    "区域排放因子": 3,
}

_ACTIVITY_ALIASES: dict[str, str] = {
    "自动连续监测": "自动连续监测",
    "continuous": "自动连续监测",
    "continuous_monitoring": "自动连续监测",
    "online_monitoring": "自动连续监测",
    "定期量测/抄表/铭牌": "定期量测/抄表/铭牌",
    "定期量测": "定期量测/抄表/铭牌",
    "抄表记录": "定期量测/抄表/铭牌",
    "抄表": "定期量测/抄表/铭牌",
    "铭牌": "定期量测/抄表/铭牌",
    "meter_reading": "定期量测/抄表/铭牌",
    "metering": "定期量测/抄表/铭牌",
    "nameplate": "定期量测/抄表/铭牌",
    "自行推估": "自行推估",
    "推估": "自行推估",
    "estimate": "自行推估",
    "manual_estimation": "自行推估",
    "manual": "自行推估",
}

_FACTOR_ALIASES: dict[str, str] = {
    "国际排放因子": "国际排放因子",
    "国际": "国际排放因子",
    "国际级": "国际排放因子",
    "international": "国际排放因子",
    "international_factor": "国际排放因子",
    "国家排放因子": "国家排放因子",
    "国家": "国家排放因子",
    "国家级": "国家排放因子",
    "national": "国家排放因子",
    "national_factor": "国家排放因子",
    "national_default": "国家排放因子",
    "区域排放因子": "区域排放因子",
    "区域": "区域排放因子",
    "区域级": "区域排放因子",
    "regional": "区域排放因子",
    "regional_factor": "区域排放因子",
    "regional_default": "区域排放因子",
}


def normalize_activity_data_category(value: str | None) -> str:
    token = (value or "").strip()
    if not token:
        return "定期量测/抄表/铭牌"
    normalized = _ACTIVITY_ALIASES.get(token)
    if normalized:
        return normalized
    lowered = token.lower()
    normalized = _ACTIVITY_ALIASES.get(lowered)
    if normalized:
        return normalized
    raise ValueError("activity_data_category must be one of: 自动连续监测 / 定期量测/抄表/铭牌 / 自行推估")


def normalize_factor_category(value: str | None) -> str:
    token = (value or "").strip()
    if not token:
        return "国家排放因子"
    normalized = _FACTOR_ALIASES.get(token)
    if normalized:
        return normalized
    lowered = token.lower()
    normalized = _FACTOR_ALIASES.get(lowered)
    if normalized:
        return normalized
    raise ValueError("factor_category must be one of: 国际排放因子 / 国家排放因子 / 区域排放因子")


def category_to_levels(activity_data_category: str, factor_category: str) -> tuple[int, int]:
    canonical_activity = normalize_activity_data_category(activity_data_category)
    canonical_factor = normalize_factor_category(factor_category)
    return ACTIVITY_CATEGORY_TO_LEVEL[canonical_activity], FACTOR_CATEGORY_TO_LEVEL[canonical_factor]


def compute_average_score(activity_level: int, factor_level: int) -> float:
    return round((activity_level + factor_level) / 2.0, 6)


def compute_emission_share(emission_amount: float, total_emission: float) -> float:
    if total_emission <= 0:
        return 0.0
    return round(emission_amount / total_emission, 6)


def compute_weighted_score(average_score: float, emission_share: float) -> float:
    return round(average_score * emission_share, 6)


def is_close_score(actual: float | None, expected: float, tolerance: float = 1e-6) -> bool:
    if actual is None:
        return False
    return isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance)

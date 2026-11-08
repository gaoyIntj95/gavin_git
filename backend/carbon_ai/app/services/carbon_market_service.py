ALLOCATION_METHODS = {
    "grandfathering": 0.85,
    "benchmark": 0.80,
    "hybrid": 0.75,
}


def calculate_quota_gap(total_emission: float, allocation_method: str) -> tuple[float, float]:
    ratio = ALLOCATION_METHODS.get(allocation_method.lower(), 0.80)
    free_quota = round(total_emission * ratio, 6)
    quota_gap = round(total_emission - free_quota, 6)
    return free_quota, quota_gap


def optimize_compliance_cost(
    quota_gap: float,
    carbon_price: float,
    ccer_price: float,
    green_electricity_price: float,
) -> tuple[dict[str, float], float]:
    if quota_gap <= 0:
        return {"quota_buy": 0.0, "ccer_buy": 0.0, "green_power_buy": 0.0}, 0.0

    ccer_limit = quota_gap * 0.30
    green_limit = quota_gap * 0.20

    ccer_buy = ccer_limit if ccer_price <= carbon_price else 0.0
    remaining = quota_gap - ccer_buy

    green_buy = green_limit if green_electricity_price <= carbon_price else 0.0
    green_buy = min(green_buy, remaining)
    remaining -= green_buy

    quota_buy = max(remaining, 0.0)
    total_cost = round(
        quota_buy * carbon_price + ccer_buy * ccer_price + green_buy * green_electricity_price,
        6,
    )

    return {
        "quota_buy": round(quota_buy, 6),
        "ccer_buy": round(ccer_buy, 6),
        "green_power_buy": round(green_buy, 6),
    }, total_cost


def build_compliance_summary(
    total_emission: float,
    allocation_method: str = "benchmark",
    ccer_max_ratio: float = 0.30,
    green_power_max_ratio: float = 0.20,
) -> dict[str, float]:
    free_quota, quota_gap = calculate_quota_gap(total_emission, allocation_method)
    ccer_limit = round(max(quota_gap, 0.0) * max(ccer_max_ratio, 0.0), 6)
    green_limit = round(max(quota_gap, 0.0) * max(green_power_max_ratio, 0.0), 6)
    return {
        "total_emission": round(total_emission, 6),
        "free_quota": free_quota,
        "quota_gap": quota_gap,
        "ccer_offset_limit": ccer_limit,
        "green_power_offset_limit": green_limit,
    }


def simulate_compliance_plans(
    total_emission: float,
    allocation_method: str,
    carbon_price: float,
    ccer_price: float,
    green_electricity_price: float,
    ccer_max_ratio: float = 0.30,
    green_power_max_ratio: float = 0.20,
) -> dict:
    summary = build_compliance_summary(
        total_emission=total_emission,
        allocation_method=allocation_method,
        ccer_max_ratio=ccer_max_ratio,
        green_power_max_ratio=green_power_max_ratio,
    )
    gap = summary["quota_gap"]

    plan_a_cost = round(gap * carbon_price, 6)
    plan_a = {
        "name": "A_全额购碳配额",
        "quota_buy": round(gap, 6),
        "ccer_buy": 0.0,
        "green_power_buy": 0.0,
        "total_cost": plan_a_cost,
        "notes": "全部缺口由配额购买覆盖。",
    }

    ccer_buy = min(summary["ccer_offset_limit"], gap)
    rem_after_ccer = max(gap - ccer_buy, 0.0)
    plan_b_cost = round(ccer_buy * ccer_price + rem_after_ccer * carbon_price, 6)
    plan_b = {
        "name": "B_配额_CCER",
        "quota_buy": round(rem_after_ccer, 6),
        "ccer_buy": round(ccer_buy, 6),
        "green_power_buy": 0.0,
        "total_cost": plan_b_cost,
        "notes": "先用CCER抵扣上限，剩余购买配额。",
    }

    green_buy = min(summary["green_power_offset_limit"], gap)
    rem_after_green = max(gap - green_buy, 0.0)
    plan_c_cost = round(green_buy * green_electricity_price + rem_after_green * carbon_price, 6)
    plan_c = {
        "name": "C_配额_绿电",
        "quota_buy": round(rem_after_green, 6),
        "ccer_buy": 0.0,
        "green_power_buy": round(green_buy, 6),
        "total_cost": plan_c_cost,
        "notes": "先用绿电抵扣上限，剩余购买配额。",
    }

    plans = [plan_a, plan_b, plan_c]
    best = min(plans, key=lambda x: x["total_cost"])
    saving_ratio = 0.0
    if plan_a_cost > 0:
        saving_ratio = round(max(plan_a_cost - best["total_cost"], 0.0) / plan_a_cost, 6)
    return {
        "summary": summary,
        "plans": plans,
        "recommended_plan": best["name"],
        "recommended_saving_ratio": saving_ratio,
    }

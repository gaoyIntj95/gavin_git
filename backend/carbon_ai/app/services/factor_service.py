from datetime import date

from sqlalchemy.orm import Session

from app.models.factor_library import FactorLibrary


def _pick_candidates(
    factors: list[FactorLibrary],
    *,
    today: date,
    industry: str | None,
    region: str | None,
    emission_class: str | None,
    energy_type: str | None,
    consumption_type: str | None,
    gas: str | None,
) -> list[FactorLibrary]:
    candidates: list[FactorLibrary] = []
    for factor in factors:
        if factor.effective_date > today:
            continue
        if factor.expiry_date is not None and factor.expiry_date < today:
            continue
        if emission_class and factor.emission_class != emission_class:
            continue
        if energy_type and factor.energy_type != energy_type:
            continue
        if consumption_type and factor.consumption_type != consumption_type:
            continue
        if gas and factor.gas.upper() != gas.upper():
            continue
        if industry and factor.industry and factor.industry not in (industry, "通用"):
            continue
        if region and factor.region and factor.region not in (region, "全国"):
            continue
        candidates.append(factor)
    return candidates


def match_factor(
    db: Session,
    category: str,
    industry: str | None = None,
    region: str | None = None,
    emission_class: str | None = None,
    energy_type: str | None = None,
    consumption_type: str | None = None,
    gas: str | None = None,
) -> tuple[float, str]:
    today = date.today()
    same_category = db.query(FactorLibrary).filter(FactorLibrary.category == category).all()
    candidates = _pick_candidates(
        same_category,
        today=today,
        industry=industry,
        region=region,
        emission_class=emission_class,
        energy_type=energy_type,
        consumption_type=consumption_type,
        gas=gas,
    )

    if not candidates and consumption_type == "transferred":
        candidates = _pick_candidates(
            same_category,
            today=today,
            industry=industry,
            region=region,
            emission_class=emission_class,
            energy_type=energy_type,
            consumption_type="purchased",
            gas=gas,
        )

    if not candidates and energy_type:
        same_energy_type = db.query(FactorLibrary).filter(FactorLibrary.energy_type == energy_type).all()
        candidates = _pick_candidates(
            same_energy_type,
            today=today,
            industry=industry,
            region=region,
            emission_class=emission_class,
            energy_type=energy_type,
            consumption_type=consumption_type,
            gas=gas,
        )

    if not candidates and energy_type and consumption_type == "transferred":
        same_energy_type = db.query(FactorLibrary).filter(FactorLibrary.energy_type == energy_type).all()
        candidates = _pick_candidates(
            same_energy_type,
            today=today,
            industry=industry,
            region=region,
            emission_class=emission_class,
            energy_type=energy_type,
            consumption_type="purchased",
            gas=gas,
        )

    if not candidates:
        return 1.0, "未匹配到排放因子，使用默认值 1.0"

    best = sorted(candidates, key=lambda item: item.priority)[0]
    return best.value, best.source


def match_factor_optional(
    db: Session,
    category: str,
    industry: str | None = None,
    region: str | None = None,
    emission_class: str | None = None,
    energy_type: str | None = None,
    consumption_type: str | None = None,
    gas: str | None = None,
) -> tuple[float, str] | None:
    """
    Same matching strategy as match_factor, but returns None when no factor is found.
    Useful for multi-gas aggregation where missing gases should be treated as 0,
    instead of falling back to the default 1.0 sentinel.
    """
    today = date.today()
    same_category = db.query(FactorLibrary).filter(FactorLibrary.category == category).all()
    candidates = _pick_candidates(
        same_category,
        today=today,
        industry=industry,
        region=region,
        emission_class=emission_class,
        energy_type=energy_type,
        consumption_type=consumption_type,
        gas=gas,
    )

    if not candidates and consumption_type == "transferred":
        candidates = _pick_candidates(
            same_category,
            today=today,
            industry=industry,
            region=region,
            emission_class=emission_class,
            energy_type=energy_type,
            consumption_type="purchased",
            gas=gas,
        )

    if not candidates and energy_type:
        same_energy_type = db.query(FactorLibrary).filter(FactorLibrary.energy_type == energy_type).all()
        candidates = _pick_candidates(
            same_energy_type,
            today=today,
            industry=industry,
            region=region,
            emission_class=emission_class,
            energy_type=energy_type,
            consumption_type=consumption_type,
            gas=gas,
        )

    if not candidates and energy_type and consumption_type == "transferred":
        same_energy_type = db.query(FactorLibrary).filter(FactorLibrary.energy_type == energy_type).all()
        candidates = _pick_candidates(
            same_energy_type,
            today=today,
            industry=industry,
            region=region,
            emission_class=emission_class,
            energy_type=energy_type,
            consumption_type="purchased",
            gas=gas,
        )

    if not candidates:
        return None

    best = sorted(candidates, key=lambda item: item.priority)[0]
    return best.value, best.source

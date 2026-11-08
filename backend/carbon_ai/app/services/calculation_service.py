from __future__ import annotations

from collections import defaultdict
from math import isclose

from sqlalchemy.orm import Session

from app.models.emission_source import EmissionSource
from app.models.project import Project
from app.services.uncertainty_service import (
    compute_average_score,
    compute_emission_share,
    compute_weighted_score,
    normalize_activity_data_category,
    normalize_factor_category,
    category_to_levels,
    is_close_score,
)


VALID_EMISSION_CLASSES = {"direct", "indirect"}
VALID_ENERGY_TYPES = {"fuel", "electricity", "heat"}
VALID_CONSUMPTION_TYPES = {"purchased", "transferred"}

EMISSION_CLASS_ALIASES = {
    "direct": "direct",
    "indirect": "indirect",
    "直接排放": "direct",
    "间接排放": "indirect",
}

ENERGY_TYPE_ALIASES = {
    "fuel": "fuel",
    "electricity": "electricity",
    "heat": "heat",
    "燃料": "fuel",
    "电力": "electricity",
    "热力": "heat",
    "蒸汽": "heat",
}

CONSUMPTION_TYPE_ALIASES = {
    "purchased": "purchased",
    "transferred": "transferred",
    "购入": "purchased",
    "外购": "purchased",
    "购买": "purchased",
    "转供": "transferred",
    "转售": "transferred",
}

VALID_GASES = {
    "CO2",
    "CH4",
    "CH4_BIOGENIC",
    "CH4_FOSSIL_COMB",
    "CH4_FOSSIL_FUG",
    "N2O",
    "HFC32",
    "HFC143A",
    "HFC134A",
    "HFCs",
    "PFCs",
    "SF6",
    "NF3",
    "OTHER",
}

DEFAULT_GWP_BY_GAS = {
    "CO2": 1.0,
    "CH4": 27.9,
    "CH4_BIOGENIC": 27.0,
    "CH4_FOSSIL_COMB": 27.0,
    "CH4_FOSSIL_FUG": 29.8,
    "N2O": 273.0,
    "HFC32": 770.0,
    "HFC143A": 5807.0,
    "HFC134A": 1526.0,
    "SF6": 25184.0,
    "NF3": 17423.0,
}

ELECTRICITY_UNITS = {"mwh", "kwh", "兆瓦时", "千瓦时"}
HEAT_UNITS = {"gj", "吉焦"}

TRANSFER_KEYWORDS = ("转供", "转售", "transfer", "resale")
ELECTRICITY_KEYWORDS = ("电", "electric", "power", "kwh", "mwh")
HEAT_KEYWORDS = ("热", "heat", "steam", "gj", "供暖")
GREEN_KEYWORDS = ("绿电", "绿色电力", "green")
MOBILE_COMBUSTION_KEYWORDS = ("车", "车辆", "商务车", "vehicle", "fleet", "transport")
PROCESS_EMISSION_KEYWORDS = ("工艺", "process")
FUGITIVE_EMISSION_KEYWORDS = ("空调", "冰箱", "灭火器", "wd-40", "化粪池", "冷媒", "制冷剂", "fugitive", "refrigerant")
BIOMASS_COMBUSTION_KEYWORDS = ("生物质", "biomass")
GASOLINE_KEYWORDS = ("汽油", "gasoline")
DIESEL_KEYWORDS = ("柴油", "diesel")
NATURAL_GAS_KEYWORDS = ("天然气", "natural gas")


def resolve_project_calculation_profile(standard: str | None, calculation_profile: str | None = None) -> str:
    explicit = (calculation_profile or "").strip().upper()
    if explicit in {"ISO14064", "ISO_14064", "ISO14064-1"}:
        return "ISO14064"
    if explicit in {"JS_T303", "JS/T303", "JS/T303-2026", "PUBLIC_INSTITUTION"}:
        return "JS_T303"

    text = (standard or "").lower()
    if "iso" in text and "14064" in text:
        return "ISO14064"
    if "js/t" in text or "303" in text or "鍏叡鏈烘瀯" in text:
        return "JS_T303"
    return "JS_T303"


def _normalize_token(value: str | None, valid_values: set[str], aliases: dict[str, str] | None = None) -> str | None:
    if value is None:
        return None
    token = str(value).strip().replace(" ", "").lower()
    if aliases and token in aliases:
        token = aliases[token]
    return token if token in valid_values else None


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def normalize_source_classification(
    *,
    scope: int,
    category: str,
    name: str,
    emission_class: str | None,
    energy_type: str | None,
    consumption_type: str | None,
    is_green_electricity: bool | None,
) -> dict[str, str | bool | int]:
    merged_text = f"{category} {name}".strip().lower()

    normalized_emission_class = _normalize_token(emission_class, VALID_EMISSION_CLASSES, EMISSION_CLASS_ALIASES)
    normalized_energy_type = _normalize_token(energy_type, VALID_ENERGY_TYPES, ENERGY_TYPE_ALIASES)
    normalized_consumption_type = _normalize_token(consumption_type, VALID_CONSUMPTION_TYPES, CONSUMPTION_TYPE_ALIASES)

    if normalized_emission_class is None:
        if scope == 1:
            normalized_emission_class = "direct"
        elif scope in (2, 3):
            normalized_emission_class = "indirect"
        elif _contains_any(merged_text, ELECTRICITY_KEYWORDS + HEAT_KEYWORDS):
            normalized_emission_class = "indirect"
        else:
            normalized_emission_class = "direct"

    if normalized_energy_type is None:
        if _contains_any(merged_text, ELECTRICITY_KEYWORDS):
            normalized_energy_type = "electricity"
        elif _contains_any(merged_text, HEAT_KEYWORDS):
            normalized_energy_type = "heat"
        else:
            normalized_energy_type = "fuel"

    if normalized_consumption_type is None:
        normalized_consumption_type = "transferred" if _contains_any(merged_text, TRANSFER_KEYWORDS) else "purchased"

    green_from_keyword = _contains_any(merged_text, GREEN_KEYWORDS)
    normalized_green = bool(is_green_electricity) or green_from_keyword
    inferred_scope = 1 if normalized_emission_class == "direct" else 2

    return {
        "emission_class": normalized_emission_class,
        "energy_type": normalized_energy_type,
        "consumption_type": normalized_consumption_type,
        "is_green_electricity": normalized_green,
        "inferred_scope": inferred_scope,
    }


def infer_iso_category(
    *,
    category: str,
    name: str,
    emission_class: str,
    energy_type: str,
) -> tuple[int, str]:
    merged_text = f"{category} {name}".strip().lower()

    if emission_class == "indirect":
        if energy_type == "electricity":
            return 2, "2.1"
        if energy_type == "heat":
            return 2, "2.2"
        return 3, "3.1"

    if _contains_any(merged_text, MOBILE_COMBUSTION_KEYWORDS):
        return 1, "1.3"
    if _contains_any(merged_text, PROCESS_EMISSION_KEYWORDS):
        return 1, "1.2"
    if _contains_any(merged_text, FUGITIVE_EMISSION_KEYWORDS):
        return 1, "1.4"
    if _contains_any(merged_text, BIOMASS_COMBUSTION_KEYWORDS):
        return 1, "1.5"
    return 1, "1.1"


def normalize_ghg_category(
    value: str | None,
    *,
    iso_category_major: int,
    iso_category_code: str,
    energy_type: str,
) -> str:
    text = (value or "").strip()
    if text:
        return text

    mapping = {
        (1, "1.1"): "1.1????",
        (1, "1.2"): "1.2????",
        (1, "1.3"): "1.3????",
        (1, "1.4"): "1.4?????",
        (1, "1.5"): "1.5?????",
        (2, "2.1"): "2.1?????????",
        (2, "2.2"): "2.2?????????",
    }
    if (iso_category_major, iso_category_code) in mapping:
        return mapping[(iso_category_major, iso_category_code)]
    if iso_category_major == 2 and energy_type == "electricity":
        return "2.1?????????"
    if iso_category_major == 2 and energy_type == "heat":
        return "2.2?????????"
    if iso_category_major == 1:
        return "1.1????"
    return "3.1??????"


def calculate_co2e(activity_data: float, factor: float, gwp: float = 1.0, *, is_green_electricity: bool = False) -> float:
    effective_factor = 0.0 if is_green_electricity else factor
    return round(activity_data * effective_factor * gwp, 6)


def _is_scope1_fuel_combustion(source: EmissionSource, keywords: tuple[str, ...]) -> bool:
    merged_text = f"{source.category} {source.name}".strip().lower()
    return (
        source.emission_class == "direct"
        and source.energy_type == "fuel"
        and _contains_any(merged_text, keywords)
    )


def _calculate_scope1_fuel_total_co2e(
    mass_m: float,
    *,
    calorific_value: float,
    carbon_content: float,
    oxidation_rate: float,
    ch4_mass_coeff: float,
    n2o_mass_coeff: float,
) -> tuple[float, dict[str, float]]:
    co2 = mass_m * calorific_value * (carbon_content * oxidation_rate * 44 / 12) / 1000
    ch4 = mass_m * ch4_mass_coeff * calorific_value * (10**-6) * (10**-3) * 27
    n2o = mass_m * n2o_mass_coeff * calorific_value * (10**-6) * (10**-3) * 273
    total = co2 + ch4 + n2o
    return round(total, 6), {
        "CO2": round(co2, 6),
        "CH4": round(ch4, 6),
        "N2O": round(n2o, 6),
    }


def calculate_scope1_gasoline_total_co2e(mass_m: float) -> tuple[float, dict[str, float]]:
    """
    Public-institution gasoline combustion formula (m: fuel mass).
    CO2e(t) = CO2(t) + CH4(t) + N2O(t)
    汽油:热值为43.07GJ/t, 单位热值含碳量为0.0189tc/GJ,碳氧化率为98%，相对分子质量44，CH4的GWP27，N2OGWP为273
    """
    return _calculate_scope1_fuel_total_co2e(
        mass_m,
        calorific_value=43.07,
        carbon_content=0.0189,
        oxidation_rate=0.98,
        ch4_mass_coeff=25,
        n2o_mass_coeff=8,
    )


def calculate_scope1_diesel_total_co2e(mass_m: float) -> tuple[float, dict[str, float]]:
    """
    Public-institution diesel combustion formula (m: fuel mass).
    CO2e(t) = CO2(t) + CH4(t) + N2O(t)
    柴油:热值为42.652GJ/t, 单位热值含碳量为0.0202tc/GJ,碳氧化率为98%，相对分子质量44，CH4的GWP27，N2OGWP为273
    """
    return _calculate_scope1_fuel_total_co2e(
        mass_m,
        calorific_value=42.652,
        carbon_content=0.0202,
        oxidation_rate=0.98,
        ch4_mass_coeff=3,
        n2o_mass_coeff=0.6,
    )


def calculate_scope1_natural_gas_total_co2e(volume_v: float) -> tuple[float, dict[str, float]]:
    """
    Public-institution natural gas combustion formula (V: gas volume).
    CO2e(t) = CO2(t) + CH4(t) + N2O(t)
    天然气: 按给定公式计算三气体总量。
    热值为389.31GJ*10^(-4)m³，单位热值含碳量为0.0153tc/GJ；碳氧化率为99%，相对分子质量44，CH4的GWP27，N2OGWP为273
    """
    co2 = volume_v * 389.31 * (0.0153 * 0.99 * 44 / 12) / 10000
    ch4 = volume_v * 389.31 * 1 * (10**-7) * (10**-3) * 27
    n2o = volume_v * 389.31 * 0.1 * (10**-7) * (10**-3) * 273
    total = co2 + ch4 + n2o
    return round(total, 6), {
        "CO2": round(co2, 6),
        "CH4": round(ch4, 6),
        "N2O": round(n2o, 6),
    }


def calculate_refrigerant_fugitive_total_co2e(
    mass_m: float,
    *,
    factor: float,
    gwp: float,
) -> tuple[float, dict[str, float]]:
    """
    Refrigerant fugitive emission formula.
    activity_data = refrigerant mass (kg)
    CO2e(t) = m * 10^(-3) * EF * GWP
    EF can be passed either as a fraction (0.055) or percentage value (5.5).
    """
    effective_factor = factor / 100 if factor > 1 else factor
    co2e = mass_m * (10**-3) * effective_factor * gwp
    total = round(co2e, 6)
    return total, {"CO2e": total}


def calculate_portable_fire_extinguisher_total_co2e(
    mass_m: float,
    *,
    gwp: float = 1.0,
) -> tuple[float, dict[str, float]]:
    """
    Portable fire extinguisher fugitive formula.
    activity_data = filled CO2 mass (kg)
    CO2e(t) = m * EF(逸散) * 10^(-3) * GWP
    便携式灭火器通常为 CO2 工质，默认 GWP=1。
    """
    effective_factor = 0.04
    co2e = mass_m * effective_factor * (10**-3) * gwp
    total = round(co2e, 6)
    return total, {"CO2": total}


def calculate_central_fire_extinguisher_total_co2e(
    mass_m: float,
) -> tuple[float, dict[str, float]]:
    """
    Central fire extinguishing system fugitive formula.
    activity_data = filled CO2 mass (kg)
    中央灭火系统（FM200/七氟丙烷）固定口径：
    EF = 2%，GWP = 2050
    CO2e(t) = m * 2% * 10^(-3) * 2050
    """
    effective_factor = 0.02
    co2e = mass_m * effective_factor * (10**-3) * 2050.0
    total = round(co2e, 6)
    return total, {"HFCs": total}


def _is_green_purchased_electricity(source: EmissionSource) -> bool:
    return (
        source.emission_class == "indirect"
        and source.energy_type == "electricity"
        and source.consumption_type == "purchased"
        and source.is_green_electricity
    )


def _canonical_gas(gas: str) -> str:
    token = (gas or "").strip().replace(" ", "")
    lower = token.lower()
    aliases = {
        "co2": "CO2",
        "ch4": "CH4",
        "ch4_biogenic": "CH4_BIOGENIC",
        "ch4_fossil_comb": "CH4_FOSSIL_COMB",
        "ch4_fossil_fug": "CH4_FOSSIL_FUG",
        "n2o": "N2O",
        "hfc32": "HFC32",
        "hfc-32": "HFC32",
        "hfc143a": "HFC143A",
        "hfc-143a": "HFC143A",
        "hfc134a": "HFC134A",
        "hfc-134a": "HFC134A",
        "hfcs": "HFCs",
        "pfcs": "PFCs",
        "sf6": "SF6",
        "nf3": "NF3",
        "other": "OTHER",
        "生物源ch4": "CH4_BIOGENIC",
        "化石源ch4(燃烧)": "CH4_FOSSIL_COMB",
        "化石源ch4（燃烧）": "CH4_FOSSIL_COMB",
        "化石源ch4(无组织/工艺)": "CH4_FOSSIL_FUG",
        "化石源ch4（无组织/工艺）": "CH4_FOSSIL_FUG",
    }
    return aliases.get(lower, token)


def normalize_gas_and_gwp(gas: str, gwp: float | None = None) -> tuple[str, float]:
    canonical_gas = _canonical_gas(gas)
    if gwp is not None and gwp > 0:
        return canonical_gas, gwp
    return canonical_gas, DEFAULT_GWP_BY_GAS.get(canonical_gas, 1.0)


def _calculate_source_gas_total(source: EmissionSource) -> tuple[float, dict[str, float]]:
    gas_totals = defaultdict(float)
    merged_text = f"{source.category} {source.name}".strip().lower()

    # 1.4 无组织排放专用口径：先于通用 activity_data * factor * gwp 计算
    if "制冷剂" in merged_text or "冷媒" in merged_text or "refrigerant" in merged_text:
        total, _parts = calculate_refrigerant_fugitive_total_co2e(
            source.activity_data,
            factor=source.factor,
            gwp=source.gwp,
        )
        source.co2e = total
        source.gas = _canonical_gas(source.gas)
        gas_totals[source.gas] += total
        return total, gas_totals

    if "灭火器" in merged_text:
        if "便携式灭火器" in merged_text or "portable extinguisher" in merged_text:
            total, _parts = calculate_portable_fire_extinguisher_total_co2e(
                source.activity_data,
                gwp=(source.gwp if source.gwp > 0 else 1.0),
            )
            source.co2e = total
            source.gas = "CO2"
            gas_totals["CO2"] += total
            return total, gas_totals
        if "中央灭火系统" in merged_text or "central extinguishing system" in merged_text:
            total, _parts = calculate_central_fire_extinguisher_total_co2e(source.activity_data)
            source.co2e = total
            source.gas = "HFCs"
            gas_totals["HFCs"] += total
            return total, gas_totals

    if _is_scope1_fuel_combustion(source, GASOLINE_KEYWORDS):
        total, parts = calculate_scope1_gasoline_total_co2e(source.activity_data)
        source.co2e = total
        gas_totals["CO2"] += parts["CO2"]
        gas_totals["CH4"] += parts["CH4"]
        gas_totals["N2O"] += parts["N2O"]
        return total, gas_totals

    if _is_scope1_fuel_combustion(source, DIESEL_KEYWORDS):
        total, parts = calculate_scope1_diesel_total_co2e(source.activity_data)
        source.co2e = total
        gas_totals["CO2"] += parts["CO2"]
        gas_totals["CH4"] += parts["CH4"]
        gas_totals["N2O"] += parts["N2O"]
        return total, gas_totals

    if _is_scope1_fuel_combustion(source, NATURAL_GAS_KEYWORDS):
        total, parts = calculate_scope1_natural_gas_total_co2e(source.activity_data)
        source.co2e = total
        gas_totals["CO2"] += parts["CO2"]
        gas_totals["CH4"] += parts["CH4"]
        gas_totals["N2O"] += parts["N2O"]
        return total, gas_totals

    source.gas = _canonical_gas(source.gas)
    source.co2e = calculate_co2e(
        source.activity_data,
        source.factor,
        source.gwp,
        is_green_electricity=_is_green_purchased_electricity(source),
    )
    gas_totals[source.gas] += source.co2e
    return source.co2e, gas_totals


def _calculate_js_t303_totals(sources: list[EmissionSource]) -> dict[str, float]:
    direct_emission = 0.0
    purchased_electricity_emission = 0.0
    transferred_electricity_emission = 0.0
    purchased_heat_emission = 0.0
    transferred_heat_emission = 0.0

    for source in sources:
        normalized = normalize_source_classification(
            scope=source.scope,
            category=source.category,
            name=source.name,
            emission_class=source.emission_class,
            energy_type=source.energy_type,
            consumption_type=source.consumption_type,
            is_green_electricity=source.is_green_electricity,
        )
        source.emission_class = str(normalized["emission_class"])
        source.energy_type = str(normalized["energy_type"])
        source.consumption_type = str(normalized["consumption_type"])
        source.is_green_electricity = bool(normalized["is_green_electricity"])
        source.scope = int(normalized["inferred_scope"])
        source.iso_category_major, source.iso_category_code = infer_iso_category(
            category=source.category,
            name=source.name,
            emission_class=source.emission_class,
            energy_type=source.energy_type,
        )

        value, _ = _calculate_source_gas_total(source)

        if source.emission_class == "direct":
            direct_emission += value
            continue
        if source.energy_type == "electricity":
            if source.consumption_type == "transferred":
                transferred_electricity_emission += value
            else:
                purchased_electricity_emission += value
            continue
        if source.energy_type == "heat":
            if source.consumption_type == "transferred":
                transferred_heat_emission += value
            else:
                purchased_heat_emission += value

    indirect_electricity_emission = purchased_electricity_emission - transferred_electricity_emission
    indirect_heat_emission = purchased_heat_emission - transferred_heat_emission
    indirect_emission = indirect_electricity_emission + indirect_heat_emission
    total_emission = direct_emission + indirect_emission

    return {
        "total_emission": round(total_emission, 6),
        "direct_emission": round(direct_emission, 6),
        "indirect_emission": round(indirect_emission, 6),
        "removal_emission": 0.0,
        "storage_emission": 0.0,
        "indirect_electricity_emission": round(indirect_electricity_emission, 6),
        "indirect_heat_emission": round(indirect_heat_emission, 6),
        "indirect_other_emission": 0.0,
        "purchased_electricity_emission": round(purchased_electricity_emission, 6),
        "transferred_electricity_emission": round(transferred_electricity_emission, 6),
        "purchased_heat_emission": round(purchased_heat_emission, 6),
        "transferred_heat_emission": round(transferred_heat_emission, 6),
        "scope1_emission": round(direct_emission, 6),
        "scope2_emission": round(indirect_emission, 6),
        "scope3_emission": 0.0,
    }


def _calculate_iso14064_totals(sources: list[EmissionSource]) -> dict[str, float]:
    direct_emission = 0.0
    indirect_energy_emission = 0.0
    indirect_other_emission = 0.0
    removal_emission = 0.0
    storage_emission = 0.0
    purchased_electricity_emission = 0.0
    transferred_electricity_emission = 0.0
    purchased_heat_emission = 0.0
    transferred_heat_emission = 0.0

    for source in sources:
        normalized = normalize_source_classification(
            scope=source.scope,
            category=source.category,
            name=source.name,
            emission_class=source.emission_class,
            energy_type=source.energy_type,
            consumption_type=source.consumption_type,
            is_green_electricity=source.is_green_electricity,
        )
        source.emission_class = str(normalized["emission_class"])
        source.energy_type = str(normalized["energy_type"])
        source.consumption_type = str(normalized["consumption_type"])
        source.is_green_electricity = bool(normalized["is_green_electricity"])
        source.iso_category_major, source.iso_category_code = infer_iso_category(
            category=source.category,
            name=source.name,
            emission_class=source.emission_class,
            energy_type=source.energy_type,
        )

        if source.iso_category_major == 1:
            source.scope = 1
        elif source.iso_category_major == 2:
            source.scope = 2
        else:
            source.scope = 3

        value, _ = _calculate_source_gas_total(source)

        if source.is_removal:
            removal_emission += value
            continue
        if source.is_storage:
            storage_emission += value
            continue

        if source.iso_category_major == 1:
            direct_emission += value
            continue

        if source.iso_category_major == 2:
            indirect_energy_emission += value
            if source.energy_type == "electricity":
                if source.consumption_type == "transferred":
                    transferred_electricity_emission += value
                else:
                    purchased_electricity_emission += value
            elif source.energy_type == "heat":
                if source.consumption_type == "transferred":
                    transferred_heat_emission += value
                else:
                    purchased_heat_emission += value
            continue

        indirect_other_emission += value

    indirect_emission = indirect_energy_emission + indirect_other_emission
    net_total = direct_emission + indirect_emission - removal_emission - storage_emission
    net_energy_electricity = purchased_electricity_emission - transferred_electricity_emission
    net_energy_heat = purchased_heat_emission - transferred_heat_emission

    return {
        "total_emission": round(net_total, 6),
        "direct_emission": round(direct_emission, 6),
        "indirect_emission": round(indirect_emission, 6),
        "removal_emission": round(removal_emission, 6),
        "storage_emission": round(storage_emission, 6),
        "indirect_electricity_emission": round(net_energy_electricity, 6),
        "indirect_heat_emission": round(net_energy_heat, 6),
        "indirect_other_emission": round(indirect_other_emission, 6),
        "purchased_electricity_emission": round(purchased_electricity_emission, 6),
        "transferred_electricity_emission": round(transferred_electricity_emission, 6),
        "purchased_heat_emission": round(purchased_heat_emission, 6),
        "transferred_heat_emission": round(transferred_heat_emission, 6),
        "scope1_emission": round(direct_emission, 6),
        "scope2_emission": round(indirect_energy_emission, 6),
        "scope3_emission": round(indirect_other_emission, 6),
    }


def _sync_uncertainty_assessments_for_sources(sources: list[EmissionSource]) -> None:
    total_emission = sum(max(source.co2e, 0.0) for source in sources)
    for source in sources:
        emission_amount = round(max(source.co2e, 0.0), 6)
        emission_share = compute_emission_share(emission_amount, total_emission)
        for item in source.uncertainties:
            activity_category = normalize_activity_data_category(item.activity_data_category)
            factor_category = normalize_factor_category(item.factor_category)
            activity_level, factor_level = category_to_levels(activity_category, factor_category)
            average_score = compute_average_score(activity_level, factor_level)
            weighted_score = compute_weighted_score(average_score, emission_share)

            item.emission_source_name = source.category
            item.facility = (item.facility or source.name).strip() or source.name
            item.activity_data_category = activity_category
            item.factor_category = factor_category
            item.activity_level = activity_level
            item.factor_level = factor_level
            item.average_score = average_score
            item.emission_amount = emission_amount
            item.emission_share = emission_share
            item.weighted_score = weighted_score


def sync_project_uncertainty_assessments(db: Session, project_id: int) -> None:
    sources = db.query(EmissionSource).filter(EmissionSource.project_id == project_id).all()
    _sync_uncertainty_assessments_for_sources(sources)
    db.flush()


def calculate_project_totals(db: Session, project_id: int) -> dict[str, float]:
    project = db.query(Project).filter(Project.id == project_id).first()
    sources = db.query(EmissionSource).filter(EmissionSource.project_id == project_id).all()

    profile = resolve_project_calculation_profile(
        project.standard if project else None,
        project.calculation_profile if project else None,
    )
    if profile == "ISO14064":
        totals = _calculate_iso14064_totals(sources)
    else:
        totals = _calculate_js_t303_totals(sources)

    _sync_uncertainty_assessments_for_sources(sources)
    db.commit()
    totals["calculation_profile"] = profile
    return totals


def _validate_common_fields(source: EmissionSource, *, errors: list[str], warnings: list[str]) -> None:
    prefix = f"[source {source.id}:{source.name}]"
    if source.activity_data <= 0:
        errors.append(f"{prefix} activity_data must be greater than 0.")
    if source.gwp <= 0:
        errors.append(f"{prefix} gwp must be greater than 0.")
    if not source.factor_source or not source.factor_source.strip():
        errors.append(f"{prefix} factor_source is required.")
    if source.activity_data > 10_000_000:
        warnings.append(f"{prefix} activity_data seems unusually large; please double check.")
    if source.co2e == 0:
        warnings.append(f"{prefix} co2e is 0; run project calculation first.")


def _validate_js_t303_sources(sources: list[EmissionSource]) -> dict[str, list[str]]:
    warnings: list[str] = []
    errors: list[str] = []

    purchased_electricity_amount = 0.0
    transferred_electricity_amount = 0.0
    purchased_heat_amount = 0.0
    transferred_heat_amount = 0.0
    purchased_heat_factors: list[float] = []
    transferred_heat_factors: list[tuple[str, float]] = []

    for source in sources:
        prefix = f"[source {source.id}:{source.name}]"
        normalized = normalize_source_classification(
            scope=source.scope,
            category=source.category,
            name=source.name,
            emission_class=source.emission_class,
            energy_type=source.energy_type,
            consumption_type=source.consumption_type,
            is_green_electricity=source.is_green_electricity,
        )

        emission_class = str(normalized["emission_class"])
        energy_type = str(normalized["energy_type"])
        consumption_type = str(normalized["consumption_type"])
        inferred_scope = int(normalized["inferred_scope"])

        if source.scope not in (1, 2):
            errors.append(f"{prefix} scope must be 1 or 2 in JS/T303 mode.")
        elif source.scope != inferred_scope:
            errors.append(f"{prefix} scope mismatch: {emission_class} should map to scope={inferred_scope}.")

        _validate_common_fields(source, errors=errors, warnings=warnings)

        if _is_green_purchased_electricity(source):
            if source.factor < 0:
                errors.append(f"{prefix} green purchased electricity factor cannot be negative.")
            if not isclose(source.factor, 0.0, abs_tol=1e-9):
                errors.append(f"{prefix} green purchased electricity factor must be 0.")
        elif source.factor <= 0:
            errors.append(f"{prefix} factor must be greater than 0.")

        if emission_class == "direct" and energy_type != "fuel":
            errors.append(f"{prefix} direct emissions must use energy_type='fuel'.")
        if emission_class == "direct" and consumption_type != "purchased":
            errors.append(f"{prefix} direct emissions cannot be marked as transferred.")
        if emission_class == "indirect" and energy_type not in ("electricity", "heat"):
            errors.append(f"{prefix} indirect emissions must be electricity or heat.")

        unit_text = source.unit.strip().lower()
        if energy_type == "electricity" and unit_text not in ELECTRICITY_UNITS:
            errors.append(f"{prefix} electricity unit must be MWh or kWh.")
        if energy_type == "heat" and unit_text not in HEAT_UNITS:
            errors.append(f"{prefix} heat unit must be GJ.")

        if emission_class == "indirect" and energy_type == "electricity":
            if consumption_type == "transferred":
                transferred_electricity_amount += source.activity_data
            else:
                purchased_electricity_amount += source.activity_data
        if emission_class == "indirect" and energy_type == "heat":
            if consumption_type == "transferred":
                transferred_heat_amount += source.activity_data
                transferred_heat_factors.append((prefix, source.factor))
            else:
                purchased_heat_amount += source.activity_data
                purchased_heat_factors.append(source.factor)

    if transferred_electricity_amount - purchased_electricity_amount > 1e-9:
        errors.append("Transferred electricity cannot exceed purchased electricity.")
    if transferred_heat_amount - purchased_heat_amount > 1e-9:
        errors.append("Transferred heat cannot exceed purchased heat.")

    if purchased_heat_factors:
        for prefix, factor in transferred_heat_factors:
            if not any(isclose(factor, purchased_factor, rel_tol=0, abs_tol=1e-9) for purchased_factor in purchased_heat_factors):
                errors.append(f"{prefix} transferred heat factor must match a purchased heat factor.")

    return {"warnings": warnings, "errors": errors}


def _validate_iso14064_sources(sources: list[EmissionSource]) -> dict[str, list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    indirect_count = 0

    for source in sources:
        prefix = f"[source {source.id}:{source.name}]"
        _validate_common_fields(source, errors=errors, warnings=warnings)

        normalized = normalize_source_classification(
            scope=source.scope,
            category=source.category,
            name=source.name,
            emission_class=source.emission_class,
            energy_type=source.energy_type,
            consumption_type=source.consumption_type,
            is_green_electricity=source.is_green_electricity,
        )
        emission_class = str(normalized["emission_class"])
        energy_type = str(normalized["energy_type"])
        major, code = infer_iso_category(
            category=source.category,
            name=source.name,
            emission_class=emission_class,
            energy_type=energy_type,
        )

        expected_scope = 1 if major == 1 else 2 if major == 2 else 3
        if source.scope != expected_scope:
            errors.append(f"{prefix} scope mismatch with ISO category; expected scope={expected_scope}.")
        if not code.startswith(f"{major}."):
            errors.append(f"{prefix} ISO category code must start with `{major}.`.")
        if source.is_removal and source.is_storage:
            errors.append(f"{prefix} source cannot be both removal and storage.")

        if source.period_start and source.period_end and source.period_start > source.period_end:
            errors.append(f"{prefix} period_start cannot be later than period_end.")

        source.gas = _canonical_gas(source.gas)
        if source.gas not in VALID_GASES:
            warnings.append(f"{prefix} gas `{source.gas}` is treated as custom gas; ensure gwp value is justified.")
        if source.gwp <= 0:
            errors.append(f"{prefix} gas {source.gas} gwp must be greater than 0.")
        if source.factor < 0:
            errors.append(f"{prefix} factor cannot be negative.")

        if not source.evidences:
            warnings.append(f"{prefix} no evidence records attached.")
        else:
            for evidence in source.evidences:
                if not evidence.file_path:
                    errors.append(f"{prefix} evidence record missing file_path.")
                if evidence.period_start and evidence.period_end and evidence.period_start > evidence.period_end:
                    errors.append(f"{prefix} evidence period_start cannot be later than period_end.")

        if source.uncertainties:
            source_emission_amount = round(max(source.co2e, 0.0), 6)
            project_total = sum(max(item.co2e, 0.0) for item in sources)
            expected_share = compute_emission_share(source_emission_amount, project_total)
            for item in source.uncertainties:
                if not item.facility or not item.facility.strip():
                    errors.append(f"{prefix} uncertainty facility is required.")
                if item.emission_amount is not None and not is_close_score(item.emission_amount, source_emission_amount):
                    errors.append(f"{prefix} uncertainty emission_amount must equal source co2e.")

                try:
                    activity_category = normalize_activity_data_category(item.activity_data_category)
                    factor_category = normalize_factor_category(item.factor_category)
                except ValueError as exc:
                    errors.append(f"{prefix} {exc}")
                    continue

                expected_activity_level, expected_factor_level = category_to_levels(activity_category, factor_category)
                expected_average_score = compute_average_score(expected_activity_level, expected_factor_level)
                expected_weighted_score = compute_weighted_score(expected_average_score, expected_share)

                if item.activity_level != expected_activity_level:
                    errors.append(f"{prefix} uncertainty activity_level must match activity_data_category.")
                if item.factor_level != expected_factor_level:
                    errors.append(f"{prefix} uncertainty factor_level must match factor_category.")
                if not is_close_score(item.average_score, expected_average_score):
                    errors.append(f"{prefix} uncertainty average_score must be (activity_level+factor_level)/2.")
                if not is_close_score(item.emission_share, expected_share):
                    errors.append(f"{prefix} uncertainty emission_share must equal source emission proportion.")
                if not is_close_score(item.weighted_score, expected_weighted_score):
                    errors.append(f"{prefix} uncertainty weighted_score must equal average_score * emission_share.")
        else:
            warnings.append(f"{prefix} uncertainty assessment is missing.")

        if major >= 2:
            indirect_count += 1

    if indirect_count == 0:
        warnings.append("No ISO indirect sources (major categories 2 or 3) were found.")

    return {"warnings": warnings, "errors": errors}


def validate_project_sources(db: Session, project_id: int) -> dict[str, list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    project = db.query(Project).filter(Project.id == project_id).first()
    sources = db.query(EmissionSource).filter(EmissionSource.project_id == project_id).all()

    if not sources:
        warnings.append("No emission sources under this project.")
        return {"warnings": warnings, "errors": errors}

    profile = resolve_project_calculation_profile(
        project.standard if project else None,
        project.calculation_profile if project else None,
    )
    if profile == "ISO14064":
        result = _validate_iso14064_sources(sources)
    else:
        result = _validate_js_t303_sources(sources)

    return {"warnings": result["warnings"], "errors": result["errors"]}

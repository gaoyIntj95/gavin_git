from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.uncertainty_service import (
    normalize_activity_data_category,
    normalize_factor_category,
)


GasType = str
ActivityDataCategoryType = Literal["自动连续监测", "定期量测/抄表/铭牌", "自行推估"]
FactorCategoryType = Literal["国际排放因子", "国家排放因子", "区域排放因子"]

SCOPE_ALIASES: dict[str, int] = {
    "1": 1,
    "2": 2,
    "3": 3,
    "范围一": 1,
    "范围二": 2,
    "范围三": 3,
    "scope1": 1,
    "scope2": 2,
    "scope3": 3,
}

EMISSION_CLASS_ALIASES: dict[str, str] = {
    "direct": "direct",
    "indirect": "indirect",
    "直接排放": "direct",
    "间接排放": "indirect",
}

ENERGY_TYPE_ALIASES: dict[str, str] = {
    "fuel": "fuel",
    "electricity": "electricity",
    "heat": "heat",
    "燃料": "fuel",
    "电力": "electricity",
    "热力": "heat",
}

CONSUMPTION_TYPE_ALIASES: dict[str, str] = {
    "purchased": "purchased",
    "transferred": "transferred",
    "购入": "purchased",
    "外购": "purchased",
    "转供": "transferred",
}

GAS_ALIASES: dict[str, str] = {
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
    "甲烷": "CH4",
    "生物源ch4": "CH4_BIOGENIC",
    "化石源ch4(燃烧)": "CH4_FOSSIL_COMB",
    "化石源ch4（燃烧）": "CH4_FOSSIL_COMB",
    "化石源ch4(无组织/工艺)": "CH4_FOSSIL_FUG",
    "化石源ch4（无组织/工艺）": "CH4_FOSSIL_FUG",
}


class UncertaintyAssessmentBase(BaseModel):
    facility: str | None = Field(default=None, max_length=255)
    activity_data_category: ActivityDataCategoryType = "定期量测/抄表/铭牌"
    factor_category: FactorCategoryType = "国家排放因子"
    notes: str | None = None

    @field_validator("activity_data_category", mode="before")
    @classmethod
    def _normalize_activity_data_category(cls, value: str | None) -> str:
        return normalize_activity_data_category(value)

    @field_validator("factor_category", mode="before")
    @classmethod
    def _normalize_factor_category(cls, value: str | None) -> str:
        return normalize_factor_category(value)


class UncertaintyAssessmentCreate(UncertaintyAssessmentBase):
    pass


class UncertaintyAssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    emission_source_name: str
    facility: str
    activity_data_category: ActivityDataCategoryType
    factor_category: FactorCategoryType
    activity_level: int
    factor_level: int
    average_score: float
    emission_amount: float
    emission_share: float
    weighted_score: float
    notes: str | None
    created_at: datetime
    updated_at: datetime


class EvidenceRecordBase(BaseModel):
    evidence_type: str = Field(default="other", min_length=1, max_length=64)
    file_path: str = Field(..., min_length=1, max_length=512)
    description: str | None = None
    period_start: date | None = None
    period_end: date | None = None


class EvidenceRecordCreate(EvidenceRecordBase):
    pass


class EvidenceRecordRead(EvidenceRecordBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    created_at: datetime
    updated_at: datetime


class EmissionSourceBase(BaseModel):
    scope: int = Field(..., ge=1, le=3)
    category: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=255)
    activity_data: float = Field(..., gt=0)
    unit: str = Field(..., min_length=1, max_length=64)
    gas: GasType = Field(default="CO2", min_length=1, max_length=32)
    gwp: float = Field(default=1.0, gt=0)
    factor: float | None = Field(default=None, gt=0)
    factor_source: str | None = Field(default=None, max_length=255)
    emission_class: Literal["direct", "indirect"] | None = None
    ghg_category: str | None = Field(default=None, max_length=64)
    energy_type: Literal["fuel", "electricity", "heat"] | None = None
    consumption_type: Literal["purchased", "transferred"] | None = None
    is_green_electricity: bool = False
    is_removal: bool = False
    is_storage: bool = False
    period_start: date | None = None
    period_end: date | None = None
    notes: str | None = None
    uncertainties: list[UncertaintyAssessmentCreate] | None = None
    evidences: list[EvidenceRecordCreate] | None = None

    @field_validator("scope", mode="before")
    @classmethod
    def _normalize_scope(cls, value: int | str) -> int:
        if isinstance(value, int):
            return value
        token = str(value).strip().replace(" ", "").lower()
        mapped = SCOPE_ALIASES.get(token)
        if mapped is not None:
            return mapped
        raise ValueError("scope 必须是 1/2/3 或 范围一/范围二/范围三")

    @field_validator("emission_class", mode="before")
    @classmethod
    def _normalize_emission_class(cls, value: str | None) -> str | None:
        if value is None:
            return None
        token = str(value).strip().replace(" ", "").lower()
        return EMISSION_CLASS_ALIASES.get(token, token)

    @field_validator("energy_type", mode="before")
    @classmethod
    def _normalize_energy_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        token = str(value).strip().replace(" ", "").lower()
        return ENERGY_TYPE_ALIASES.get(token, token)

    @field_validator("consumption_type", mode="before")
    @classmethod
    def _normalize_consumption_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        token = str(value).strip().replace(" ", "").lower()
        return CONSUMPTION_TYPE_ALIASES.get(token, token)

    @field_validator("gas", mode="before")
    @classmethod
    def _normalize_gas(cls, value: str) -> str:
        raw = str(value).strip()
        if not raw:
            raise ValueError("gas 不能为空")
        token = raw.replace(" ", "").lower()
        return GAS_ALIASES.get(token, raw)

    @field_validator("factor_source", mode="before")
    @classmethod
    def _normalize_factor_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("ghg_category", mode="before")
    @classmethod
    def _normalize_ghg_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class EmissionSourceCreate(EmissionSourceBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "scope": 2,
                "category": "外购电力",
                "name": "支行办公用电",
                "activity_data": 34.5,
                "unit": "MWh",
                "gas": "CO2",
                "gwp": 1,
                "ghg_category": "2.1电力产生的间接排放",
                "factor_source": "国家排放因子",
                "factor": 0.5306,
                "emission_class": "indirect",
                "energy_type": "electricity",
                "consumption_type": "purchased",
                "is_green_electricity": False,
                "is_removal": False,
                "is_storage": False,
                "period_start": "2023-01-01",
                "period_end": "2023-12-31",
                "notes": "年度电量",
                "uncertainties": [
                    {
                        "facility": "用电设备",
                        "activity_data_category": "自动连续监测",
                        "factor_category": "国家排放因子",
                        "notes": "由系统自动计算等级、排放量占比和加权得分",
                    }
                ],
                "evidences": [
                    {
                        "evidence_type": "invoice",
                        "file_path": "evidence/2023-electricity-invoice.pdf",
                        "description": "电费发票与抄表记录",
                        "period_start": "2023-01-01",
                        "period_end": "2023-12-31",
                    }
                ],
            }
        }
    )


class EmissionSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    scope: int
    category: str
    name: str
    activity_data: float
    unit: str
    gas: GasType
    factor: float
    factor_source: str
    gwp: float
    ghg_category: str
    co2e: float
    emission_class: Literal["direct", "indirect"]
    energy_type: Literal["fuel", "electricity", "heat"]
    consumption_type: Literal["purchased", "transferred"]
    is_green_electricity: bool
    iso_category_major: int
    iso_category_code: str
    iso_category_name: str
    is_removal: bool
    is_storage: bool
    period_start: date | None
    period_end: date | None
    notes: str | None
    uncertainties: list[UncertaintyAssessmentRead] = []
    evidences: list[EvidenceRecordRead] = []
    created_at: datetime
    updated_at: datetime


class BatchImportResult(BaseModel):
    success_count: int
    fail_count: int
    errors: list[str]


class CalculationResult(BaseModel):
    total_emission: float
    calculation_profile: str
    direct_emission: float
    indirect_emission: float
    removal_emission: float
    storage_emission: float
    indirect_electricity_emission: float
    indirect_heat_emission: float
    indirect_other_emission: float
    purchased_electricity_emission: float
    transferred_electricity_emission: float
    purchased_heat_emission: float
    transferred_heat_emission: float
    scope1_emission: float
    scope2_emission: float
    scope3_emission: float


class ValidationResult(BaseModel):
    warnings: list[str]
    errors: list[str]


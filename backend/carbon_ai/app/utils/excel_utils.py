from pathlib import Path

import pandas as pd


COLUMN_ALIASES = {
    "scope": ["scope", "排放范围"],
    "category": ["category", "排放源类别"],
    "name": ["name", "排放源名称"],
    "activity_data": ["activity_data", "活动数据"],
    "unit": ["unit", "单位"],
    "gas": ["gas", "温室气体类型", "气体"],
    "gwp": ["gwp", "GWP"],
    "emission_class": ["emission_class", "排放类型", "核算类型"],
    "energy_type": ["energy_type", "能源类型"],
    "consumption_type": ["consumption_type", "购入转供类型", "活动类型"],
    "is_green_electricity": ["is_green_electricity", "是否绿电直连", "绿电直连"],
    "is_removal": ["is_removal", "是否移除"],
    "is_storage": ["is_storage", "是否储存"],
    "period_start": ["period_start", "起始日期", "盘查开始"],
    "period_end": ["period_end", "结束日期", "盘查结束"],
    "notes": ["notes", "备注"],
}


TRUE_VALUES = {"1", "true", "yes", "y", "是", "真"}
FALSE_VALUES = {"0", "false", "no", "n", "否", "假"}


def _read_table(file_path: Path) -> pd.DataFrame:
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(file_path)
    if suffix in (".xls", ".xlsx"):
        return pd.read_excel(file_path)
    raise ValueError("仅支持 CSV / XLS / XLSX 文件。")


def _resolve_columns(df: pd.DataFrame) -> dict[str, str]:
    mapping: dict[str, str] = {}
    lower_columns = {str(column).lower(): str(column) for column in df.columns}

    for target, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            matched = lower_columns.get(alias.lower())
            if matched:
                mapping[target] = matched
                break
    return mapping


def _parse_bool(value: object) -> bool | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return None


def parse_emission_source_file(file_path: Path) -> list[dict]:
    df = _read_table(file_path)
    mapping = _resolve_columns(df)
    required = ["scope", "category", "name", "activity_data", "unit"]
    missing = [field for field in required if field not in mapping]
    if missing:
        raise ValueError(f"导入文件缺少必要字段: {', '.join(missing)}")

    rows: list[dict] = []
    for _, row in df.iterrows():
        green_flag = (
            _parse_bool(row[mapping["is_green_electricity"]]) if "is_green_electricity" in mapping else None
        )
        item = {
            "scope": int(row[mapping["scope"]]),
            "category": str(row[mapping["category"]]).strip(),
            "name": str(row[mapping["name"]]).strip(),
            "activity_data": float(row[mapping["activity_data"]]),
            "unit": str(row[mapping["unit"]]).strip(),
            "gas": str(row[mapping["gas"]]).strip() if "gas" in mapping and pd.notna(row[mapping["gas"]]) else "CO2",
            "gwp": float(row[mapping["gwp"]]) if "gwp" in mapping and pd.notna(row[mapping["gwp"]]) else 1.0,
            "emission_class": (
                str(row[mapping["emission_class"]]).strip().lower()
                if "emission_class" in mapping and pd.notna(row[mapping["emission_class"]])
                else None
            ),
            "energy_type": (
                str(row[mapping["energy_type"]]).strip().lower()
                if "energy_type" in mapping and pd.notna(row[mapping["energy_type"]])
                else None
            ),
            "consumption_type": (
                str(row[mapping["consumption_type"]]).strip().lower()
                if "consumption_type" in mapping and pd.notna(row[mapping["consumption_type"]])
                else None
            ),
            "is_green_electricity": green_flag if green_flag is not None else False,
            "is_removal": (
                bool(_parse_bool(row[mapping["is_removal"]]))
                if "is_removal" in mapping and pd.notna(row[mapping["is_removal"]])
                else False
            ),
            "is_storage": (
                bool(_parse_bool(row[mapping["is_storage"]]))
                if "is_storage" in mapping and pd.notna(row[mapping["is_storage"]])
                else False
            ),
            "period_start": (
                pd.to_datetime(row[mapping["period_start"]]).date()
                if "period_start" in mapping and pd.notna(row[mapping["period_start"]])
                else None
            ),
            "period_end": (
                pd.to_datetime(row[mapping["period_end"]]).date()
                if "period_end" in mapping and pd.notna(row[mapping["period_end"]])
                else None
            ),
            "notes": str(row[mapping["notes"]]).strip() if "notes" in mapping and pd.notna(row[mapping["notes"]]) else None,
        }
        rows.append(item)
    return rows

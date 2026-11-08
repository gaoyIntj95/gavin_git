import { callApi } from "../composables/useApi";

export type PeriodType = "day" | "month" | "year";

export interface NaturalGasPayload {
  period_type: PeriodType;
  period_start: string;
  period_end: string;
  activity_data: number;
  activity_unit: string;
  factor: number;
  factor_unit: string;
  factor_source: string;
  gwp: number;
  gas: string;
  scope: number;
  iso_category_code: string;
  data_quality: string;
  source_system?: string | null;
  notes?: string | null;
}

export interface PurchasedElectricityPayload {
  period_type: PeriodType;
  period_start: string;
  period_end: string;
  electricity_consumption: number;
  electricity_unit: string;
  is_green_electricity: boolean;
  green_power_ratio: number;
  factor: number;
  factor_unit: string;
  factor_source: string;
  gwp: number;
  gas: string;
  scope: number;
  iso_category_code: string;
  consumption_type: string;
  data_quality: string;
  source_system?: string | null;
  notes?: string | null;
}

export interface NaturalGasRecord extends NaturalGasPayload {
  id: number;
  project_id: number;
  co2e: number;
  created_at: string;
  updated_at: string;
}

export interface PurchasedElectricityRecord extends PurchasedElectricityPayload {
  id: number;
  project_id: number;
  co2e: number;
  created_at: string;
  updated_at: string;
}

export async function createNaturalGasTimeseries(projectId: number, payload: NaturalGasPayload) {
  return callApi<NaturalGasRecord>(`/api/timeseries/natural-gas/${projectId}`, "POST", payload);
}

export async function listNaturalGasTimeseries(projectId: number, periodType?: string, year?: number) {
  const params = new URLSearchParams();
  if (periodType) params.set("period_type", periodType);
  if (year != null) params.set("year", String(year));
  const query = params.toString() ? `?${params.toString()}` : "";
  return callApi<{ items: NaturalGasRecord[] }>(`/api/timeseries/natural-gas/${projectId}${query}`);
}

export async function createPurchasedElectricityTimeseries(
  projectId: number,
  payload: PurchasedElectricityPayload,
) {
  return callApi<PurchasedElectricityRecord>(
    `/api/timeseries/purchased-electricity/${projectId}`,
    "POST",
    payload,
  );
}

export async function listPurchasedElectricityTimeseries(projectId: number, periodType?: string, year?: number) {
  const params = new URLSearchParams();
  if (periodType) params.set("period_type", periodType);
  if (year != null) params.set("year", String(year));
  const query = params.toString() ? `?${params.toString()}` : "";
  return callApi<{ items: PurchasedElectricityRecord[] }>(
    `/api/timeseries/purchased-electricity/${projectId}${query}`,
  );
}


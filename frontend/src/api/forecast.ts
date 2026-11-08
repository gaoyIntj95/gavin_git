import { callApi } from "../composables/useApi";

export interface ForecastRequest {
  granularity: "month" | "day";
  model: "auto" | "prophet" | "lstm" | "hw" | "holt_winters" | "linear" | "ensemble";
  horizon_months: number;
  allocation_method: "grandfathering" | "benchmark" | "hybrid";
  warning_threshold_pct: number;
  reference_year?: number;
}

export interface ForecastPoint {
  date: string;
  value: number | null;
  kind: "actual" | "forecast";
  is_interpolated: boolean;
  yhat_lower: number | null;       // 95% CI lower
  yhat_upper: number | null;       // 95% CI upper
  yhat_lower_80: number | null;    // 80% CI lower
  yhat_upper_80: number | null;    // 80% CI upper
}

export interface SubItemForecast {
  source_type: "natural_gas" | "purchased_electricity";
  scope: number;
  history: Array<{ date: string; value: number | null }>;
  forecast: Array<{
    date: string;
    yhat: number;
    yhat_lower_80: number;
    yhat_upper_80: number;
    yhat_lower_95: number;
    yhat_upper_95: number;
  }>;
}

export interface ForecastResponse {
  project_id: number;
  granularity: string;
  model_used: string;
  horizon_months: number;
  trend: string;
  reduction_warning: string;
  compliance_gap_preview: {
    allocation_method: string;
    max_gap: number;
    min_gap: number;
    periods: Array<{
      date: string;
      predicted_total_emission: number;
      free_quota: number;
      quota_gap: number;
    }>;
  };
  points: ForecastPoint[];
  echarts: {
    xAxis: string[];
    legend: string[];
    series: Array<{
      name: string;
      type: string;
      smooth?: boolean;
      symbol?: string;
      symbolSize?: number;
      lineStyle?: Record<string, unknown>;
      itemStyle?: Record<string, unknown>;
      areaStyle?: Record<string, unknown>;
      data: (number | null)[];
      stack?: string;
      z?: number;
    }>;
  };
  data_sources: string[];
  data_quality: Record<string, unknown>;
  interpolation_count: number;
  outlier_count: number;
  // New fields
  sub_item_forecasts: SubItemForecast[];
  debug_info: Record<string, unknown>;
  historical_max: number | null;
  historical_avg: number | null;
  scope_ratio: Record<string, number>;
}

export interface ForecastDebugResponse {
  project_id: number;
  model_used: string;
  horizon_months: number;
  model_input: Record<string, unknown>;
  model_output: Record<string, unknown>;
  confidence_intervals: Record<string, unknown>;
  constraints: Record<string, unknown>;
  warnings: string[];
  trace: string[];
}

export async function forecastEmission(projectId: number, payload: ForecastRequest) {
  return callApi<ForecastResponse>(`/api/forecast/emission/${projectId}`, "POST", payload);
}

export async function debugForecast(projectId: number, payload: ForecastRequest) {
  return callApi<ForecastDebugResponse>(`/api/forecast/debug/${projectId}`, "POST", payload);
}

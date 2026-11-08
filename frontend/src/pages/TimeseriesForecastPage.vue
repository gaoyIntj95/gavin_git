<template>
  <section class="page-view ts-page">
    <div class="panel toolbar">
      <label>
        项目ID
        <input v-model.number="projectId" type="number" min="1" class="field" />
      </label>
      <label>
        年度
        <select v-model.number="selectedYear" class="field">
          <option v-for="y in availableYears" :key="y" :value="y">{{ y }}</option>
        </select>
      </label>
      <button class="action-btn blue" @click="reloadAll">刷新数据</button>
      <span class="status">{{ status }}</span>
    </div>

    <div class="panel two-col">
      <article>
        <h3>天然气能耗录入</h3>
        <div class="form-grid">
          <input v-model="gasForm.period_start" type="date" class="field" />
          <input v-model="gasForm.period_end" type="date" class="field" />
          <input v-model.number="gasForm.activity_data" type="number" step="0.0001" class="field" placeholder="活动数据 (Nm³)" />
          <input v-model.number="gasForm.factor" type="number" step="0.000001" class="field" placeholder="排放因子" />
        </div>
        <button class="action-btn blue" @click="submitGas">保存天然气能耗</button>
      </article>

      <article>
        <h3>外购电能耗录入</h3>
        <div class="form-grid">
          <input v-model="elecForm.period_start" type="date" class="field" />
          <input v-model="elecForm.period_end" type="date" class="field" />
          <input v-model.number="elecForm.electricity_consumption" type="number" step="0.0001" class="field" placeholder="电量 (kWh)" />
          <input v-model.number="elecForm.factor" type="number" step="0.000001" class="field" placeholder="排放因子" />
        </div>
        <button class="action-btn blue" @click="submitElec">保存外购电能耗</button>
      </article>
    </div>

    <div class="panel">
      <h3>{{ selectedYear }} 年月度数据查询</h3>
      <table>
        <thead>
          <tr>
            <th>月份</th>
            <th>天然气活动数据(Nm³)</th>
            <th>天然气CO₂e(吨)</th>
            <th>外购电电量(kWh)</th>
            <th>外购电CO₂e(吨)</th>
            <th>合计CO₂e(吨)</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in monthlySummary" :key="m.month">
            <td>{{ m.month }}月</td>
            <td>{{ m.gasActivity != null ? m.gasActivity.toLocaleString() : "-" }}</td>
            <td>{{ m.gasCo2e != null ? m.gasCo2e.toFixed(4) : "-" }}</td>
            <td>{{ m.elecConsumption != null ? m.elecConsumption.toLocaleString() : "-" }}</td>
            <td>{{ m.elecCo2e != null ? m.elecCo2e.toFixed(4) : "-" }}</td>
            <td>{{ m.totalCo2e != null ? m.totalCo2e.toFixed(4) : "-" }}</td>
          </tr>
          <tr v-if="monthlySummary.length > 0" class="summary-row">
            <td><strong>年度合计</strong></td>
            <td><strong>{{ annualGasActivity.toLocaleString() }}</strong></td>
            <td><strong>{{ annualGasCo2e.toFixed(4) }}</strong></td>
            <td><strong>{{ annualElecConsumption.toLocaleString() }}</strong></td>
            <td><strong>{{ annualElecCo2e.toFixed(4) }}</strong></td>
            <td><strong>{{ annualTotalCo2e.toFixed(4) }}</strong></td>
          </tr>
        </tbody>
      </table>
      <p v-if="monthlySummary.length === 0" class="status">暂无 {{ selectedYear }} 年数据</p>
    </div>

    <div class="panel">
      <div class="forecast-toolbar">
        <h3>时序情景预测</h3>
        <select v-model="forecastForm.model" class="field">
          <option value="auto">auto（集成）</option>
          <option value="prophet">Prophet</option>
          <option value="hw">Holt-Winters</option>
          <option value="linear">线性回归</option>
        </select>
        <select v-model.number="forecastForm.horizon_months" class="field">
          <option :value="6">6个月</option>
          <option :value="12">12个月</option>
        </select>
        <button
          class="action-btn blue"
          :disabled="forecasting"
          @click="runForecast"
        >
          {{ forecasting ? "预测中..." : "执行预测" }}
        </button>
      </div>

      <!-- Chart with loading overlay -->
      <div class="chart-wrapper">
        <div v-if="forecasting" class="chart-loading">
          <span>正在运行预测模型...</span>
        </div>
        <div ref="chartEl" class="chart" :class="{ 'chart-dimmed': forecasting }"></div>
      </div>

      <!-- Forecast summary -->
      <div v-if="forecastResult" class="forecast-summary">
        <p class="status">
          模型：{{ forecastResult.model_used }} |
          预测周期：{{ forecastResult.horizon_months }}个月
        </p>
        <p class="status warning-text">{{ forecastResult.reduction_warning }}</p>
        <p class="status">
          履约缺口区间：{{ forecastResult.compliance_gap_preview?.min_gap?.toFixed(2) ?? "-" }}
          ~ {{ forecastResult.compliance_gap_preview?.max_gap?.toFixed(2) ?? "-" }} tCO₂e
          （{{ forecastResult.compliance_gap_preview?.allocation_method ?? "-" }}法）
        </p>
        <p v-if="forecastResult.historical_max != null" class="status dim">
          历史最大值：{{ forecastResult.historical_max?.toFixed(2) }} tCO₂e |
          历史均值：{{ forecastResult.historical_avg?.toFixed(2) }} tCO₂e
          <span v-if="forecastResult.scope_ratio?.scope1_pct">
            | Scope1占比：{{ (forecastResult.scope_ratio.scope1_pct * 100).toFixed(1) }}%
            | Scope2占比：{{ (forecastResult.scope_ratio.scope2_pct * 100).toFixed(1) }}%
          </span>
        </p>
        <p v-if="forecastResult.interpolation_count > 0 || forecastResult.outlier_count > 0" class="status dim">
          数据修复：插值 {{ forecastResult.interpolation_count }} 处
          <span v-if="forecastResult.outlier_count > 0">| 异常值裁剪 {{ forecastResult.outlier_count }} 处</span>
        </p>
      </div>
      <p v-else class="status">点击「执行预测」按钮开始预测</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as echarts from "echarts";
import {
  createNaturalGasTimeseries,
  createPurchasedElectricityTimeseries,
  listNaturalGasTimeseries,
  listPurchasedElectricityTimeseries,
  type NaturalGasPayload,
  type NaturalGasRecord,
  type PurchasedElectricityPayload,
  type PurchasedElectricityRecord,
} from "../api/timeseries";
import { forecastEmission, type ForecastResponse } from "../api/forecast";

const projectId = ref(1);
const status = ref("准备就绪，选择年度后自动加载数据");
const selectedYear = ref(2021);
const availableYears = ref<number[]>([2021, 2022, 2023, 2024, 2025, 2026]);
const gasRows = ref<NaturalGasRecord[]>([]);
const elecRows = ref<PurchasedElectricityRecord[]>([]);
const forecastResult = ref<ForecastResponse | null>(null);
const forecasting = ref(false);

const gasForm = ref<NaturalGasPayload>({
  period_type: "month",
  period_start: "",
  period_end: "",
  activity_data: 0,
  activity_unit: "Nm3",
  factor: 2.16,
  factor_unit: "kgCO2e/Nm3",
  factor_source: "JS/T 303-2026",
  gwp: 1,
  gas: "CO2",
  scope: 1,
  iso_category_code: "1.1",
  data_quality: "measured",
  source_system: "manual",
  notes: "",
});

const elecForm = ref<PurchasedElectricityPayload>({
  period_type: "month",
  period_start: "",
  period_end: "",
  electricity_consumption: 0,
  electricity_unit: "kWh",
  is_green_electricity: false,
  green_power_ratio: 0,
  factor: 0.581,
  factor_unit: "tCO2e/MWh",
  factor_source: "JS/T 303-2026",
  gwp: 1,
  gas: "CO2",
  scope: 2,
  iso_category_code: "2.1",
  consumption_type: "purchased",
  data_quality: "measured",
  source_system: "manual",
  notes: "",
});

const forecastForm = ref({
  granularity: "month" as const,
  model: "auto" as const,
  horizon_months: 6,
  allocation_method: "benchmark" as const,
  warning_threshold_pct: 30,
});

// ---- Monthly summary table ----

interface MonthlyRow {
  month: number;
  gasActivity: number | null;
  gasCo2e: number | null;
  elecConsumption: number | null;
  elecCo2e: number | null;
  totalCo2e: number | null;
}

const monthlySummary = computed<MonthlyRow[]>(() => {
  const map = new Map<number, MonthlyRow>();
  for (let m = 1; m <= 12; m++) {
    map.set(m, { month: m, gasActivity: null, gasCo2e: null, elecConsumption: null, elecCo2e: null, totalCo2e: null });
  }
  for (const r of gasRows.value) {
    const m = new Date(r.period_start).getMonth() + 1;
    const row = map.get(m);
    if (row) {
      row.gasActivity = r.activity_data;
      row.gasCo2e = r.co2e;
    }
  }
  for (const r of elecRows.value) {
    const m = new Date(r.period_start).getMonth() + 1;
    const row = map.get(m);
    if (row) {
      row.elecConsumption = r.electricity_consumption;
      row.elecCo2e = r.co2e;
    }
  }
  for (const row of map.values()) {
    const g = row.gasCo2e ?? 0;
    const e = row.elecCo2e ?? 0;
    row.totalCo2e = row.gasCo2e != null || row.elecCo2e != null ? Math.round((g + e) * 10000) / 10000 : null;
  }
  return [...map.values()];
});

const annualGasActivity = computed(() => monthlySummary.value.reduce((s, r) => s + (r.gasActivity ?? 0), 0));
const annualGasCo2e = computed(() => Math.round(monthlySummary.value.reduce((s, r) => s + (r.gasCo2e ?? 0), 0) * 10000) / 10000);
const annualElecConsumption = computed(() => monthlySummary.value.reduce((s, r) => s + (r.elecConsumption ?? 0), 0));
const annualElecCo2e = computed(() => Math.round(monthlySummary.value.reduce((s, r) => s + (r.elecCo2e ?? 0), 0) * 10000) / 10000);
const annualTotalCo2e = computed(() => Math.round((annualGasCo2e.value + annualElecCo2e.value) * 10000) / 10000);

// ---- Chart ----

const chartEl = ref<HTMLElement | null>(null);
let chart: echarts.ECharts | null = null;

function initChart() {
  if (!chartEl.value) return;
  if (chart) {
    chart.dispose();
  }
  chart = echarts.init(chartEl.value);
  // Responsive resize
  const ro = new ResizeObserver(() => chart?.resize());
  ro.observe(chartEl.value);
}

function renderChart(payload: ForecastResponse) {
  if (!chartEl.value) return;
  if (!chart) {
    initChart();
  }
  if (!chart) return;

  const { xAxis, legend, series } = payload.echarts;

  chart.setOption(
    {
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(255,255,255,0.95)",
        borderColor: "#e5e7eb",
        textStyle: { color: "#374151", fontSize: 12 },
        formatter: (params: any[]) => {
          if (!params || params.length === 0) return "";
          let html = `<b>${params[0].axisValue}</b><br/>`;
          for (const p of params) {
            // Hide internal stacked series from tooltip
            if (p.seriesName === "95%置信区间下界") continue;
            const val = p.value != null ? Number(p.value).toLocaleString(undefined, { maximumFractionDigits: 2 }) : "-";
            html += `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${p.color};margin-right:6px;"></span>${p.seriesName}: <b>${val} tCO₂e</b><br/>`;
          }
          return html;
        },
      },
      legend: {
        data: legend,
        bottom: 0,
        textStyle: { fontSize: 11 },
        selected: {
          // Ensure only visible series show in legend
          "95%置信区间下界": false,
        },
      },
      grid: { left: 60, right: 30, top: 20, bottom: 45 },
      xAxis: [
        {
          type: "category",
          data: xAxis,
          axisLabel: { rotate: 30, fontSize: 10 },
          boundaryGap: false,
        },
      ],
      yAxis: [
        {
          type: "value",
          name: "tCO₂e",
          nameTextStyle: { fontSize: 11 },
          axisLabel: { fontSize: 10 },
        },
      ],
      series,
    },
    { notMerge: true },
  );
}

// ---- Data loading ----

async function reloadAll() {
  try {
    gasRows.value = [];
    elecRows.value = [];
    status.value = "正在加载...";
    const [gas, elec] = await Promise.all([
      listNaturalGasTimeseries(projectId.value, "month", selectedYear.value),
      listPurchasedElectricityTimeseries(projectId.value, "month", selectedYear.value),
    ]);
    gasRows.value = gas.items || [];
    elecRows.value = elec.items || [];
    const total = gasRows.value.length + elecRows.value.length;
    status.value = `已加载 ${selectedYear.value} 年能耗/碳排数据（共 ${total} 条记录）。`;
  } catch (err) {
    gasRows.value = [];
    elecRows.value = [];
    const msg = err instanceof Error ? err.message : String(err);
    status.value = `加载失败：${msg}`;
  }
}

// ---- Forecast ----

async function runForecast() {
  if (forecasting.value) return;
  forecasting.value = true;
  forecastResult.value = null;
  status.value = "正在运行预测模型...";

  try {
    const res = await forecastEmission(projectId.value, {
      ...forecastForm.value,
      reference_year: selectedYear.value,
    });
    forecastResult.value = res;
    renderChart(res);
    status.value = `预测完成，模型：${res.model_used}，基于 ≤${selectedYear.value} 年历史数据`;
  } catch (err) {
    // Backend unavailable — use simple constrained linear fallback
    try {
      const localResult = runLocalForecastFallback();
      forecastResult.value = localResult;
      renderChart(localResult);
      status.value = `本地预测完成（后端不可用），基于 ≤${selectedYear.value} 年数据。建议检查后端服务。`;
    } catch (fallbackErr) {
      const msg = fallbackErr instanceof Error ? fallbackErr.message : String(fallbackErr);
      status.value = `预测失败：${msg}`;
    }
  } finally {
    forecasting.value = false;
  }
}

/** Simple local linear fallback with value cap and proper confidence band. */
function runLocalForecastFallback(): ForecastResponse {
  const allGas: NaturalGasRecord[] = [];
  const allElec: PurchasedElectricityRecord[] = [];

  // Build monthly total CO2e map using YYYY-MM keys
  const totalMap: Record<string, number> = {};
  const ngMap: Record<string, number> = {};
  const peMap: Record<string, number> = {};

  for (const g of gasRows.value) {
    const key = g.period_start?.slice(0, 7);
    if (key) {
      totalMap[key] = (totalMap[key] || 0) + g.co2e;
      ngMap[key] = (ngMap[key] || 0) + g.co2e;
    }
  }
  for (const e of elecRows.value) {
    const key = e.period_start?.slice(0, 7);
    if (key) {
      totalMap[key] = (totalMap[key] || 0) + e.co2e;
      peMap[key] = (peMap[key] || 0) + e.co2e;
    }
  }

  const histKeys = Object.keys(totalMap).sort();
  const histValues = histKeys.map((k) => totalMap[k]);

  if (histValues.length < 2) {
    throw new Error("至少需要 2 个月数据才能预测（请确认当前年度有足够的历史月度记录）");
  }

  const n = histValues.length;
  const xMean = (n - 1) / 2;
  const yMean = histValues.reduce((a, b) => a + b, 0) / n;
  let num = 0;
  let den = 0;
  for (let i = 0; i < n; i++) {
    num += (i - xMean) * (histValues[i] - yMean);
    den += (i - xMean) * (i - xMean);
  }
  const slope = den === 0 ? 0 : num / den;
  const intercept = yMean - slope * xMean;
  const histMax = Math.max(...histValues);
  const histAvg = yMean;
  const capValue = histMax * 1.2;

  // Trend
  const deltaPct = histAvg > 0 ? ((slope * (n + forecastForm.value.horizon_months - 1) + intercept - histValues[n - 1]) / histValues[n - 1]) * 100 : 0;
  const trend =
    deltaPct > 10 ? "快速上升" : deltaPct > 2 ? "缓慢上升" : deltaPct < -10 ? "快速下降" : deltaPct < -2 ? "缓慢下降" : "基本持平";

  // Build xAxis
  const xAxis: string[] = [...histKeys];
  const lastKey = histKeys[n - 1];
  const [lastY, lastM] = lastKey.split("-").map(Number);
  const horizon = forecastForm.value.horizon_months;

  for (let i = 1; i <= horizon; i++) {
    const m = lastM + i;
    const y = lastY + Math.floor((m - 1) / 12);
    const mm = ((m - 1) % 12) + 1;
    xAxis.push(`${y}-${String(mm).padStart(2, "0")}`);
  }

  // Historical series
  const historicalSeries: (number | null)[] = [...histValues];

  // Forecast series with cap
  const lastActual = histValues[n - 1];
  const forecastSeries: (number | null)[] = new Array(n).fill(null);
  forecastSeries[n - 1] = lastActual;
  const upper95: (number | null)[] = new Array(n).fill(null);
  upper95[n - 1] = lastActual;
  const lower95: (number | null)[] = new Array(n).fill(null);
  lower95[n - 1] = lastActual;

  // Residual std error for CI
  const fittedVals = histValues.map((_, i) => intercept + slope * i);
  const residuals = histValues.map((v, i) => v - fittedVals[i]);
  const rse = n > 2 ? Math.sqrt(residuals.reduce((s, r) => s + r * r, 0) / (n - 2)) : 0;

  for (let i = 0; i < horizon; i++) {
    const rawPred = intercept + slope * (n + i);
    const cappedPred = Math.max(0, Math.min(rawPred, capValue));
    forecastSeries.push(Math.round(cappedPred * 10000) / 10000);

    // CI widens with horizon
    const seH = rse * Math.sqrt(1 + 1 / n + Math.pow(i + 1, 2) / ((n - 1) * n / 12 || 1));
    const margin95 = 1.96 * seH;
    upper95.push(Math.max(0, Math.round((cappedPred + margin95) * 10000) / 10000));
    lower95.push(Math.max(0, Math.round((cappedPred - margin95) * 10000) / 10000));
    historicalSeries.push(null);
  }

  // NG and PE series aligned to xAxis (using YYYY-MM key)
  const ngSeries = xAxis.map((d) => {
    const v = ngMap[d];
    return v != null ? Math.round(v * 10000) / 10000 : null;
  });
  const peSeries = xAxis.map((d) => {
    const v = peMap[d];
    return v != null ? Math.round(v * 10000) / 10000 : null;
  });

  // Quota gap
  const freeQuotaRatio = 0.80; // benchmark
  const gapPeriods: ForecastResponse["compliance_gap_preview"]["periods"] = [];
  for (let i = 0; i < horizon; i++) {
    const predVal = (forecastSeries[n + i] as number) ?? 0;
    const freeQuota = Math.round(predVal * freeQuotaRatio * 10000) / 10000;
    const gap = Math.round((predVal - freeQuota) * 10000) / 10000;
    gapPeriods.push({
      date: xAxis[n + i],
      predicted_total_emission: predVal,
      free_quota: freeQuota,
      quota_gap: gap,
    });
  }
  const gaps = gapPeriods.map((p) => p.quota_gap);
  const maxGap = Math.max(...gaps);
  const minGap = Math.min(...gaps);

  // Warning
  const significantChange = Math.abs(deltaPct) > forecastForm.value.warning_threshold_pct;
  const hasQuotaRisk = maxGap > 0;
  let warning: string;
  if (hasQuotaRisk && significantChange) {
    warning = `趋势：${trend}；预警：预测期排放同比增长${deltaPct >= 0 ? "+" : ""}${deltaPct.toFixed(1)}%，超出免费配额${maxGap.toFixed(2)} tCO₂e，需关注配额缺口风险`;
  } else if (hasQuotaRisk) {
    warning = `趋势：${trend}；提示：预测期存在配额缺口（最大${maxGap.toFixed(2)} tCO₂e），但同比变化${deltaPct >= 0 ? "+" : ""}${deltaPct.toFixed(1)}%，未触发预警阈值`;
  } else if (significantChange) {
    warning = `趋势：${trend}；预警：预测期排放同比增长${deltaPct >= 0 ? "+" : ""}${deltaPct.toFixed(1)}%，超过${forecastForm.value.warning_threshold_pct}%预警阈值，建议关注排放趋势`;
  } else {
    warning = `趋势：${trend}；排放量在配额范围内，暂无履约风险`;
  }

  return {
    project_id: projectId.value,
    granularity: "month",
    model_used: `local_${forecastForm.value.model}`,
    horizon_months: horizon,
    trend,
    reduction_warning: warning,
    compliance_gap_preview: {
      allocation_method: "benchmark",
      min_gap: Math.round(minGap * 10000) / 10000,
      max_gap: Math.round(maxGap * 10000) / 10000,
      periods: gapPeriods,
    },
    points: [],
    echarts: {
      xAxis,
      legend: ["实际综合排放", "天然气排放", "外购电排放", "预测排放", "95%置信区间"],
      series: [
        {
          name: "实际综合排放",
          type: "line",
          smooth: false,
          symbol: "circle",
          symbolSize: 6,
          lineStyle: { color: "#2563eb", width: 2.5 },
          itemStyle: { color: "#2563eb" },
          data: historicalSeries,
          z: 4,
        },
        {
          name: "天然气排放",
          type: "line",
          smooth: false,
          symbol: "none",
          lineStyle: { color: "#f97316", width: 1.5, type: "dashed" },
          itemStyle: { color: "#f97316" },
          data: ngSeries,
          z: 3,
        },
        {
          name: "外购电排放",
          type: "line",
          smooth: false,
          symbol: "none",
          lineStyle: { color: "#8b5cf6", width: 1.5, type: "dashed" },
          itemStyle: { color: "#8b5cf6" },
          data: peSeries,
          z: 3,
        },
        {
          name: "预测排放",
          type: "line",
          smooth: true,
          symbol: "none",
          lineStyle: { color: "#16a34a", width: 2.5, type: "dashed" },
          itemStyle: { color: "#16a34a" },
          data: forecastSeries,
          z: 5,
        },
        {
          name: "95%置信区间",
          type: "line",
          smooth: true,
          symbol: "none",
          lineStyle: { color: "rgba(22,163,74,0.15)", width: 0 },
          areaStyle: { color: "rgba(22,163,74,0.12)" },
          data: upper95,
          stack: "confidence-band",
          z: 1,
        },
        {
          name: "95%置信区间下界",
          type: "line",
          smooth: true,
          symbol: "none",
          lineStyle: { color: "transparent", width: 0 },
          areaStyle: { color: "#ffffff" },
          data: lower95,
          stack: "confidence-band",
          z: 1,
        },
      ],
    },
    data_sources: ["local_natural_gas_timeseries", "local_purchased_electricity_timeseries", "local_linear_regression"],
    data_quality: {},
    interpolation_count: 0,
    outlier_count: 0,
    sub_item_forecasts: [],
    debug_info: { fallback: true, model: "linear_regression_with_cap" },
    historical_max: histMax,
    historical_avg: histAvg,
    scope_ratio: {},
  };
}

// ---- Form submission ----

async function submitGas() {
  try {
    await createNaturalGasTimeseries(projectId.value, gasForm.value);
    await reloadAll();
    status.value = "天然气能耗数据已保存。";
  } catch (err) {
    status.value = `保存失败：${err instanceof Error ? err.message : "unknown"}`;
  }
}

async function submitElec() {
  try {
    await createPurchasedElectricityTimeseries(projectId.value, elecForm.value);
    await reloadAll();
    status.value = "外购电能耗数据已保存。";
  } catch (err) {
    status.value = `保存失败：${err instanceof Error ? err.message : "unknown"}`;
  }
}

// ---- Watchers ----

// Reload data when project or year changes
watch([projectId, selectedYear], () => {
  reloadAll();
});

// Auto-refresh forecast when model or horizon changes (if we already have a result)
watch(
  () => [forecastForm.value.model, forecastForm.value.horizon_months],
  () => {
    if (forecastResult.value != null && !forecasting.value) {
      runForecast();
    }
  },
);

// ---- Lifecycle ----

onMounted(() => {
  void reloadAll();
});

onBeforeUnmount(() => {
  chart?.dispose();
  chart = null;
});
</script>

<style scoped>
.ts-page { display: grid; gap: 12px; }
.panel { border: 1px solid #d9e1ec; border-radius: 8px; background: #fff; padding: 12px; }
.toolbar { display: flex; align-items: center; gap: 10px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 8px 0; }
.field { border: 1px solid #cdd8d5; border-radius: 6px; padding: 8px; }
.action-btn.blue { background: #1d8fd8; color: #fff; border: none; border-radius: 8px; padding: 8px 12px; cursor: pointer; }
.action-btn.blue:disabled { background: #94a3b8; cursor: not-allowed; }
.action-btn.green { background: #16a34a; color: #fff; border: none; border-radius: 8px; padding: 8px 12px; cursor: pointer; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid #edf2f7; padding: 8px; text-align: left; }
.forecast-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.chart-wrapper { position: relative; }
.chart { width: 100%; height: 380px; }
.chart-dimmed { opacity: 0.4; pointer-events: none; }
.chart-loading {
  position: absolute; top: 0; left: 0; right: 0; bottom: 0;
  display: flex; align-items: center; justify-content: center;
  background: rgba(255,255,255,0.7); z-index: 10;
  font-size: 14px; color: #4a627a; border-radius: 8px;
}
.forecast-summary { margin-top: 8px; }
.summary-row td { font-weight: 600; background: #f8fafc; }
.status { margin: 6px 0 0; font-size: 13px; color: #4a627a; }
.status.dim { color: #94a3b8; font-size: 12px; }
.warning-text { font-weight: 500; color: #b45309; }
@media (max-width: 1100px) {
  .two-col { grid-template-columns: 1fr; }
}
</style>
